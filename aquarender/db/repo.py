"""Repository pattern over SQLAlchemy models.

`core/` MUST only talk to repositories; never to SQLAlchemy directly.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aquarender.db.models import EngineSessionModel, JobModel, OutputModel, PresetModel


def _utc_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def new_id() -> str:
    return str(uuid.uuid4())


# ── Preset ────────────────────────────────────────────────────────────────────


class PresetRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def list(self, *, include_user: bool = True) -> list[PresetModel]:
        stmt = select(PresetModel).order_by(PresetModel.is_builtin.desc(), PresetModel.name)
        if not include_user:
            stmt = stmt.where(PresetModel.is_builtin == 1)
        return list(self._s.execute(stmt).scalars())

    def get(self, preset_id: str) -> PresetModel | None:
        return self._s.get(PresetModel, preset_id)

    def create(
        self,
        *,
        preset_id: str,
        name: str,
        description: str | None,
        params: dict[str, Any],
        is_builtin: bool = False,
    ) -> PresetModel:
        row = PresetModel(
            id=preset_id,
            name=name,
            description=description,
            params_json=json.dumps(params, sort_keys=True),
            is_builtin=1 if is_builtin else 0,
        )
        self._s.add(row)
        self._s.flush()
        return row

    def update_params(self, preset_id: str, params: dict[str, Any]) -> PresetModel | None:
        row = self.get(preset_id)
        if row is None:
            return None
        row.params_json = json.dumps(params, sort_keys=True)
        row.updated_at = _utc_iso()
        self._s.flush()
        return row

    def delete(self, preset_id: str) -> bool:
        row = self.get(preset_id)
        if row is None:
            return False
        self._s.delete(row)
        self._s.flush()
        return True


# ── EngineSession ─────────────────────────────────────────────────────────────


class EngineSessionRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def open(
        self,
        *,
        tunnel_url: str,
        engine_type: str,
        gpu_name: str | None,
        comfyui_version: str | None,
    ) -> EngineSessionModel:
        row = EngineSessionModel(
            id=new_id(),
            tunnel_url=tunnel_url,
            engine_type=engine_type,
            gpu_name=gpu_name,
            comfyui_version=comfyui_version,
        )
        self._s.add(row)
        self._s.flush()
        return row

    def get(self, session_id: str) -> EngineSessionModel | None:
        return self._s.get(EngineSessionModel, session_id)

    def touch(self, session_id: str) -> None:
        row = self.get(session_id)
        if row is not None:
            row.last_seen_at = _utc_iso()
            self._s.flush()

    def close(self, session_id: str) -> None:
        row = self.get(session_id)
        if row is not None and row.disconnected_at is None:
            row.disconnected_at = _utc_iso()
            self._s.flush()

    def list_active(self) -> list[EngineSessionModel]:
        stmt = select(EngineSessionModel).where(EngineSessionModel.disconnected_at.is_(None))
        return list(self._s.execute(stmt).scalars())


# ── Job ───────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class JobCreateArgs:
    kind: str
    preset_id: str
    engine_session_id: str | None
    parent_job_id: str | None = None
    overrides: dict[str, Any] | None = None
    input_count: int = 1


class JobRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def create(self, args: JobCreateArgs) -> JobModel:
        row = JobModel(
            id=new_id(),
            parent_job_id=args.parent_job_id,
            preset_id=args.preset_id,
            engine_session_id=args.engine_session_id,
            kind=args.kind,
            status="queued",
            overrides_json=json.dumps(args.overrides) if args.overrides else None,
            input_count=args.input_count,
        )
        self._s.add(row)
        self._s.flush()
        return row

    def get(self, job_id: str) -> JobModel | None:
        return self._s.get(JobModel, job_id)

    def children(self, parent_id: str) -> list[JobModel]:
        stmt = (
            select(JobModel)
            .where(JobModel.parent_job_id == parent_id)
            .order_by(JobModel.created_at)
        )
        return list(self._s.execute(stmt).scalars())

    def list(
        self,
        *,
        kind: str | None = None,
        status: str | None = None,
        preset_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[JobModel]:
        stmt = select(JobModel).order_by(JobModel.created_at.desc())
        if kind is not None:
            stmt = stmt.where(JobModel.kind == kind)
        if status is not None:
            stmt = stmt.where(JobModel.status == status)
        if preset_id is not None:
            stmt = stmt.where(JobModel.preset_id == preset_id)
        stmt = stmt.limit(limit).offset(offset)
        return list(self._s.execute(stmt).scalars())

    def update_status(
        self,
        job_id: str,
        status: str,
        *,
        error_message: str | None = None,
        engine_session_id: str | None = None,
    ) -> None:
        row = self.get(job_id)
        if row is None:
            return
        row.status = status
        now = _utc_iso()
        if status == "running" and row.started_at is None:
            row.started_at = now
        if status in {"success", "failed", "cancelled"}:
            row.finished_at = now
        if error_message is not None:
            row.error_message = error_message
        if engine_session_id is not None:
            row.engine_session_id = engine_session_id
        self._s.flush()

    def increment_counts(self, job_id: str, *, succeeded: int = 0, failed: int = 0) -> None:
        row = self.get(job_id)
        if row is None:
            return
        row.success_count += succeeded
        row.failure_count += failed
        self._s.flush()

    def pause_with_checkpoint(self, job_id: str, paused_at_index: int) -> None:
        row = self.get(job_id)
        if row is None:
            return
        row.status = "paused"
        row.paused_at_index = paused_at_index
        self._s.flush()

    def clear_checkpoint(self, job_id: str) -> None:
        row = self.get(job_id)
        if row is None:
            return
        row.paused_at_index = None
        self._s.flush()


# ── Output ────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class OutputCreateArgs:
    job_id: str
    engine_session_id: str
    input_path: str
    output_path: str
    params: dict[str, Any]
    seed: int
    duration_ms: int
    width: int
    height: int
    file_size_bytes: int


class OutputRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def create(self, args: OutputCreateArgs) -> OutputModel:
        row = OutputModel(
            id=new_id(),
            job_id=args.job_id,
            engine_session_id=args.engine_session_id,
            input_path=args.input_path,
            output_path=args.output_path,
            params_json=json.dumps(args.params, sort_keys=True),
            seed=args.seed,
            duration_ms=args.duration_ms,
            width=args.width,
            height=args.height,
            file_size_bytes=args.file_size_bytes,
        )
        self._s.add(row)
        self._s.flush()
        return row

    def get_by_job(self, job_id: str) -> OutputModel | None:
        stmt = select(OutputModel).where(OutputModel.job_id == job_id)
        return self._s.execute(stmt).scalar_one_or_none()
