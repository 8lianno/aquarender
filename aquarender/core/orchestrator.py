"""JobOrchestrator — single coordination point for generation jobs.

UI / CLI talk to this. It in turn drives the engine client and persists
state through the repositories. See API.md § Internal Python API.
"""
from __future__ import annotations

import asyncio
import dataclasses as _dc
import hashlib
import json
import random
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from PIL import Image

from aquarender.core.metadata import EngineContext, MetadataWriter
from aquarender.core.preprocessor import ImagePreprocessor
from aquarender.core.presets import PresetService
from aquarender.engine.types import EngineInfo
from aquarender.engine.workflows import WorkflowBuilder
from aquarender.errors import (
    AquaRenderError,
    EngineNotConnectedError,
    JobCannotResumeError,
    JobNotFoundError,
    LoraMissingError,
    TunnelDownError,
)
from aquarender.logging_setup import get_logger
from aquarender.params import ResolvedParams, SliderOverrides
from aquarender.types import EngineType, JobId, JobKind, JobStatusValue, SeedMode

log = get_logger(__name__)


# ── Shapes returned from the orchestrator surface ─────────────────────────────


@_dc.dataclass(slots=True)
class Progress:
    total: int
    succeeded: int
    failed: int
    in_flight: int
    eta_seconds: float | None = None


@_dc.dataclass(slots=True)
class OutputRef:
    job_id: JobId
    output_path: Path
    sidecar_path: Path
    seed: int
    duration_ms: int


@_dc.dataclass(slots=True)
class JobStatus:
    job_id: JobId
    kind: JobKind
    status: JobStatusValue
    preset_id: str
    engine_session_id: str | None
    progress: Progress
    paused_at_index: int | None
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    outputs: list[OutputRef]
    children: list[JobStatus]


# ── Repository protocols ──────────────────────────────────────────────────────


class _JobRepoProto(Protocol):  # pragma: no cover — typing only
    def create(self, args: Any) -> Any: ...
    def get(self, job_id: str) -> Any: ...
    def children(self, parent_id: str) -> list[Any]: ...
    def list(
        self,
        *,
        kind: str | None = ...,
        status: str | None = ...,
        preset_id: str | None = ...,
        limit: int = ...,
        offset: int = ...,
    ) -> list[Any]: ...
    def update_status(
        self,
        job_id: str,
        status: str,
        *,
        error_message: str | None = ...,
        engine_session_id: str | None = ...,
    ) -> None: ...
    def increment_counts(self, job_id: str, *, succeeded: int = ..., failed: int = ...) -> None: ...
    def pause_with_checkpoint(self, job_id: str, paused_at_index: int) -> None: ...
    def clear_checkpoint(self, job_id: str) -> None: ...


class _OutputRepoProto(Protocol):  # pragma: no cover
    def create(self, args: Any) -> Any: ...
    def get_by_job(self, job_id: str) -> Any: ...


class _SessionRepoProto(Protocol):  # pragma: no cover
    def open(
        self, *, tunnel_url: str, engine_type: str, gpu_name: str | None, comfyui_version: str | None
    ) -> Any: ...
    def get(self, session_id: str) -> Any: ...
    def touch(self, session_id: str) -> None: ...
    def close(self, session_id: str) -> None: ...


class _ClientProto(Protocol):  # pragma: no cover
    base_url: str

    async def health(self) -> EngineInfo: ...
    async def upload_image(
        self, image: Image.Image, *, filename: str | None = ...
    ) -> Any: ...
    async def queue_prompt(self, workflow: dict[str, Any]) -> str: ...
    async def poll_until_done(
        self, prompt_id: str, *, timeout_s: int | None = ..., poll_interval_s: float = ...
    ) -> Any: ...
    async def fetch_output(self, prompt_id: str, result: Any | None = ...) -> bytes: ...
    async def interrupt(self) -> None: ...
    async def keepalive_ping(self) -> None: ...


# ── Orchestrator ──────────────────────────────────────────────────────────────


class JobOrchestrator:
    """Coordinates: validate → resolve → execute → persist.

    Engine must be `connect()`-ed before submitting jobs.
    """

    def __init__(
        self,
        *,
        client: _ClientProto | None,
        preset_service: PresetService,
        preprocessor: ImagePreprocessor,
        metadata_writer: MetadataWriter,
        workflow_builder: WorkflowBuilder,
        job_repo: _JobRepoProto,
        output_repo: _OutputRepoProto,
        session_repo: _SessionRepoProto,
        outputs_dir: Path,
        engine_session_id: str | None = None,
        engine_context: EngineContext | None = None,
        commit: Callable[[], None] | None = None,
    ) -> None:
        self._client = client
        self._presets = preset_service
        self._preprocessor = preprocessor
        self._metadata = metadata_writer
        self._workflows = workflow_builder
        self._jobs = job_repo
        self._outputs = output_repo
        self._sessions = session_repo
        self._outputs_dir = outputs_dir
        self._engine_session_id = engine_session_id
        self._engine_context = engine_context
        self._commit: Callable[[], None] = commit or (lambda: None)
        # Track tasks so callers can introspect / await
        self._tasks: dict[JobId, asyncio.Task[None]] = {}
        # Per-batch cancellation flags
        self._cancelled: set[JobId] = set()

    # ── connection management ──

    async def connect(
        self, client: _ClientProto, *, engine_type_hint: EngineType | None = None
    ) -> EngineContext:
        info = await client.health()
        engine_type: EngineType = (
            engine_type_hint
            if engine_type_hint is not None
            else getattr(info, "inferred_engine_type", "unknown")
        )
        session_row = self._sessions.open(
            tunnel_url=client.base_url,
            engine_type=engine_type,
            gpu_name=info.gpu_name,
            comfyui_version=info.comfyui_version,
        )
        ctx = EngineContext(
            session_id=session_row.id,
            engine_type=engine_type,
            gpu_name=info.gpu_name,
            comfyui_version=info.comfyui_version,
            tunnel_url=client.base_url,
        )
        self._client = client
        self._engine_session_id = session_row.id
        self._engine_context = ctx
        log.info(
            "engine.connected",
            base_url=client.base_url,
            gpu=info.gpu_name,
            session_id=session_row.id,
        )
        return ctx

    def disconnect(self) -> None:
        if self._engine_session_id is not None:
            self._sessions.close(self._engine_session_id)
        self._client = None
        self._engine_session_id = None
        self._engine_context = None

    def rebind_engine(self, new_client: _ClientProto, new_context: EngineContext) -> None:
        """Swap client without closing the old session row.

        Used when the user reconnects with a new tunnel URL mid-batch. Caller
        is responsible for opening the new session via `connect()`.
        """
        self._client = new_client
        self._engine_session_id = new_context.session_id
        self._engine_context = new_context

    @property
    def engine_session_id(self) -> str | None:
        return self._engine_session_id

    @property
    def engine_context(self) -> EngineContext | None:
        return self._engine_context

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._engine_session_id is not None

    # ── public sync wrappers (Streamlit uses these) ──

    def run_single_sync(
        self,
        image: bytes | Path | Image.Image,
        preset_id: str,
        overrides: SliderOverrides | None = None,
        seed: int | None = None,
    ) -> JobId:
        return asyncio.run(self.run_single(image, preset_id, overrides, seed))

    def run_batch_sync(
        self,
        inputs: Path | list[Path] | bytes,
        preset_id: str,
        overrides: SliderOverrides | None = None,
        seed_mode: SeedMode = "random",
        fixed_seed: int | None = None,
    ) -> JobId:
        return asyncio.run(self.run_batch(inputs, preset_id, overrides, seed_mode, fixed_seed))

    def resume_sync(self, job_id: JobId) -> JobId:
        return asyncio.run(self.resume(job_id))

    def retry_failed_sync(self, job_id: JobId, *, new_seed: bool = True) -> JobId:
        return asyncio.run(self.retry_failed(job_id, new_seed=new_seed))

    # ── async core ──

    async def run_single(
        self,
        image: bytes | Path | Image.Image,
        preset_id: str,
        overrides: SliderOverrides | None = None,
        seed: int | None = None,
    ) -> JobId:
        self._require_connected()

        preset = self._presets.get(preset_id)
        params = self._presets.merge(preset, overrides)

        pil = self._preprocessor.validate(image)

        await self._verify_engine_resources(params)

        if seed is None:
            seed = random.randint(0, 2**32 - 1)

        from aquarender.db.repo import JobCreateArgs

        job = self._jobs.create(
            JobCreateArgs(
                kind="single",
                preset_id=preset_id,
                engine_session_id=self._engine_session_id,
                overrides=_overrides_to_json(overrides),
            )
        )

        input_path = _input_path_of(image)
        input_filename = _input_filename_of(image)

        self._commit()
        try:
            await self._execute_one(
                job_id=job.id,
                pil=pil,
                params=params,
                seed=seed,
                preset_id=preset_id,
                preset_name=preset.name,
                input_path=input_path,
                input_filename=input_filename,
                batch_id=None,
            )
        except TunnelDownError:
            self._jobs.update_status(job.id, "paused")
        except AquaRenderError as e:
            self._jobs.update_status(job.id, "failed", error_message=str(e))
        except Exception as e:  # pragma: no cover — defensive
            log.exception("job.crashed", job_id=job.id)
            self._jobs.update_status(job.id, "failed", error_message=f"Internal error: {e}")
        finally:
            self._commit()
        return str(job.id)

    async def run_batch(
        self,
        inputs: Path | list[Path] | bytes,
        preset_id: str,
        overrides: SliderOverrides | None = None,
        seed_mode: SeedMode = "random",
        fixed_seed: int | None = None,
    ) -> JobId:
        self._require_connected()

        preset = self._presets.get(preset_id)
        params = self._presets.merge(preset, overrides)

        await self._verify_engine_resources(params)

        paths = self._materialize_batch_inputs(inputs)
        if not paths:
            raise AquaRenderError("Batch contains no usable images.")

        from aquarender.db.repo import JobCreateArgs

        parent = self._jobs.create(
            JobCreateArgs(
                kind="batch",
                preset_id=preset_id,
                engine_session_id=self._engine_session_id,
                overrides=_overrides_to_json(overrides),
                input_count=len(paths),
            )
        )

        self._commit()
        await self._execute_batch(
            parent_id=parent.id,
            preset_id=preset_id,
            preset_name=preset.name,
            params=params,
            paths=paths,
            seed_mode=seed_mode,
            fixed_seed=fixed_seed,
            start_index=0,
        )
        self._commit()
        return str(parent.id)

    async def resume(self, job_id: JobId) -> JobId:
        self._require_connected()
        row = self._jobs.get(job_id)
        if row is None:
            raise JobNotFoundError(job_id)
        if row.kind != "batch" or row.status != "paused":
            raise JobCannotResumeError(f"Job {job_id} is not a paused batch (status={row.status}).")

        checkpoint = _read_checkpoint(self._outputs_dir, job_id)
        if checkpoint is None:
            raise JobCannotResumeError(f"No checkpoint found for batch {job_id}.")

        paths = [Path(p) for p in checkpoint["inputs"]]
        start_index = int(checkpoint.get("next_index", row.paused_at_index or 0))
        seed_mode: SeedMode = checkpoint.get("seed_mode", "random")
        fixed_seed = checkpoint.get("fixed_seed")
        preset_id = row.preset_id

        preset = self._presets.get(preset_id)
        overrides = (
            _overrides_from_json(json.loads(row.overrides_json))
            if row.overrides_json
            else None
        )
        params = self._presets.merge(preset, overrides)

        # Rebind to current engine session
        self._jobs.update_status(
            job_id, "running", engine_session_id=self._engine_session_id
        )

        await self._execute_batch(
            parent_id=job_id,
            preset_id=preset_id,
            preset_name=preset.name,
            params=params,
            paths=paths,
            seed_mode=seed_mode,
            fixed_seed=fixed_seed,
            start_index=start_index,
        )
        return job_id

    async def retry_failed(self, job_id: JobId, *, new_seed: bool = True) -> JobId:
        self._require_connected()
        row = self._jobs.get(job_id)
        if row is None:
            raise JobNotFoundError(job_id)
        children = self._jobs.children(job_id) if row.kind == "batch" else []
        failed = [c for c in children if c.status == "failed"]
        if not failed:
            return job_id

        preset = self._presets.get(row.preset_id)
        overrides = (
            _overrides_from_json(json.loads(row.overrides_json))
            if row.overrides_json
            else None
        )
        params = self._presets.merge(preset, overrides)

        for child in failed:
            output = self._outputs.get_by_job(child.id)
            input_path = (
                Path(output.input_path) if output is not None else Path(child.error_message or "")
            )
            if not input_path.exists():
                continue
            try:
                pil = self._preprocessor.validate(input_path)
            except AquaRenderError as e:
                self._jobs.update_status(child.id, "failed", error_message=str(e))
                continue
            seed = random.randint(0, 2**32 - 1) if new_seed else _seed_from_filename(input_path.name)
            self._jobs.update_status(child.id, "queued", error_message=None)
            try:
                await self._execute_one(
                    job_id=child.id,
                    pil=pil,
                    params=params,
                    seed=seed,
                    preset_id=row.preset_id,
                    preset_name=preset.name,
                    input_path=input_path,
                    input_filename=input_path.name,
                    batch_id=row.id,
                )
                self._jobs.increment_counts(row.id, succeeded=1, failed=-1)
            except TunnelDownError:
                self._jobs.update_status(child.id, "paused")
                raise
            except AquaRenderError as e:
                self._jobs.update_status(child.id, "failed", error_message=str(e))
        return job_id

    def cancel(self, job_id: JobId) -> None:
        row = self._jobs.get(job_id)
        if row is None:
            raise JobNotFoundError(job_id)
        self._cancelled.add(job_id)
        self._jobs.update_status(job_id, "cancelled")
        # Best-effort interrupt of in-flight remote execution
        if self._client is not None:
            try:
                asyncio.get_event_loop().run_until_complete(self._client.interrupt())
            except RuntimeError:
                # Likely no running loop; fire-and-forget
                pass

    # ── status / listing ──

    def get_status(self, job_id: JobId) -> JobStatus:
        row = self._jobs.get(job_id)
        if row is None:
            raise JobNotFoundError(job_id)
        return self._status_for(row)

    def list_jobs(
        self,
        *,
        kind: JobKind | None = None,
        status: JobStatusValue | None = None,
        preset_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[JobStatus]:
        rows = self._jobs.list(
            kind=kind, status=status, preset_id=preset_id, limit=limit, offset=offset
        )
        return [self._status_for(r) for r in rows]

    # ── internals ──

    def _status_for(self, row: Any) -> JobStatus:
        children_rows = self._jobs.children(row.id) if row.kind == "batch" else []
        children = [self._status_for(c) for c in children_rows]
        outputs: list[OutputRef] = []
        if row.kind != "batch":
            o = self._outputs.get_by_job(row.id)
            if o is not None:
                outputs.append(_output_ref_from_row(row.id, o))
        in_flight = sum(1 for c in children if c.status in {"queued", "running"})
        total = row.input_count
        return JobStatus(
            job_id=row.id,
            kind=row.kind,
            status=row.status,
            preset_id=row.preset_id,
            engine_session_id=row.engine_session_id,
            progress=Progress(
                total=total,
                succeeded=row.success_count if row.kind == "batch" else (1 if row.status == "success" else 0),
                failed=row.failure_count if row.kind == "batch" else (1 if row.status == "failed" else 0),
                in_flight=in_flight,
                eta_seconds=None,
            ),
            paused_at_index=row.paused_at_index,
            started_at=_parse_dt(row.started_at),
            finished_at=_parse_dt(row.finished_at),
            error_message=row.error_message,
            outputs=outputs,
            children=children,
        )

    def _require_connected(self) -> None:
        if self._client is None or self._engine_session_id is None or self._engine_context is None:
            raise EngineNotConnectedError("Connect to an engine first.")

    async def _verify_engine_resources(self, params: ResolvedParams) -> None:
        assert self._client is not None
        try:
            info = await self._client.health()
        except TunnelDownError:
            raise
        if info.available_loras and params.lora.name not in info.available_loras:
            raise LoraMissingError(params.lora.name)

    async def _execute_one(
        self,
        *,
        job_id: JobId,
        pil: Image.Image,
        params: ResolvedParams,
        seed: int,
        preset_id: str,
        preset_name: str,
        input_path: Path | str | None,
        input_filename: str,
        batch_id: str | None,
    ) -> None:
        assert self._client is not None
        assert self._engine_session_id is not None
        assert self._engine_context is not None

        self._jobs.update_status(
            job_id, "running", engine_session_id=self._engine_session_id
        )
        start = time.monotonic()
        try:
            ref = await self._client.upload_image(pil)
            workflow = self._workflows.build(ref, params, seed)
            prompt_id = await self._client.queue_prompt(workflow)
            result = await self._client.poll_until_done(prompt_id, timeout_s=120)
            output_bytes = await self._client.fetch_output(prompt_id, result)
        except TunnelDownError:
            raise

        duration_ms = int((time.monotonic() - start) * 1000)

        written = self._metadata.write(
            job_id=job_id,
            batch_id=batch_id,
            preset_id=preset_id,
            preset_name=preset_name,
            input_path=input_path or input_filename,
            input_filename=input_filename,
            output_bytes=output_bytes,
            params=params,
            seed=seed,
            duration_ms=duration_ms,
            engine=self._engine_context,
        )

        from aquarender.db.repo import OutputCreateArgs

        self._outputs.create(
            OutputCreateArgs(
                job_id=job_id,
                engine_session_id=self._engine_session_id,
                input_path=str(input_path) if input_path else input_filename,
                output_path=str(written.output_path),
                params=params.model_dump(),
                seed=seed,
                duration_ms=duration_ms,
                width=written.width,
                height=written.height,
                file_size_bytes=written.file_size_bytes,
            )
        )
        self._jobs.update_status(job_id, "success")
        log.info(
            "job.completed",
            job_id=job_id,
            preset=preset_id,
            seed=seed,
            duration_ms=duration_ms,
        )

    async def _execute_batch(
        self,
        *,
        parent_id: JobId,
        preset_id: str,
        preset_name: str,
        params: ResolvedParams,
        paths: list[Path],
        seed_mode: SeedMode,
        fixed_seed: int | None,
        start_index: int,
    ) -> None:
        from aquarender.db.repo import JobCreateArgs

        self._jobs.update_status(parent_id, "running")
        # Persist inputs list once for resume; refreshes safe.
        _write_checkpoint(
            self._outputs_dir,
            parent_id,
            {
                "inputs": [str(p) for p in paths],
                "seed_mode": seed_mode,
                "fixed_seed": fixed_seed,
                "next_index": start_index,
            },
        )

        for i in range(start_index, len(paths)):
            if parent_id in self._cancelled:
                self._jobs.update_status(parent_id, "cancelled")
                self._commit()
                return

            path = paths[i]
            try:
                pil = self._preprocessor.validate(path)
            except AquaRenderError as e:
                child = self._jobs.create(
                    JobCreateArgs(
                        kind="batch_item",
                        preset_id=preset_id,
                        engine_session_id=self._engine_session_id,
                        parent_job_id=parent_id,
                    )
                )
                self._jobs.update_status(child.id, "failed", error_message=str(e))
                self._jobs.increment_counts(parent_id, failed=1)
                _bump_checkpoint(self._outputs_dir, parent_id, i + 1)
                self._commit()
                continue

            child = self._jobs.create(
                JobCreateArgs(
                    kind="batch_item",
                    preset_id=preset_id,
                    engine_session_id=self._engine_session_id,
                    parent_job_id=parent_id,
                )
            )

            seed = _resolve_seed(seed_mode, fixed_seed, path.name)

            try:
                await self._execute_one(
                    job_id=child.id,
                    pil=pil,
                    params=params,
                    seed=seed,
                    preset_id=preset_id,
                    preset_name=preset_name,
                    input_path=path,
                    input_filename=path.name,
                    batch_id=parent_id,
                )
                self._jobs.increment_counts(parent_id, succeeded=1)
                _bump_checkpoint(self._outputs_dir, parent_id, i + 1)
            except TunnelDownError:
                self._jobs.update_status(child.id, "paused")
                self._jobs.pause_with_checkpoint(parent_id, i)
                _bump_checkpoint(self._outputs_dir, parent_id, i)
                self._commit()
                log.warning("batch.paused.tunnel_down", parent_id=parent_id, paused_at_index=i)
                return
            except AquaRenderError as e:
                self._jobs.update_status(child.id, "failed", error_message=str(e))
                self._jobs.increment_counts(parent_id, failed=1)
                _bump_checkpoint(self._outputs_dir, parent_id, i + 1)
            except Exception as e:  # pragma: no cover — defensive
                log.exception("batch.child.crashed", parent_id=parent_id, child_id=child.id)
                self._jobs.update_status(child.id, "failed", error_message=f"Internal: {e}")
                self._jobs.increment_counts(parent_id, failed=1)
                _bump_checkpoint(self._outputs_dir, parent_id, i + 1)
            self._commit()

        # Finalize
        row = self._jobs.get(parent_id)
        assert row is not None
        if row.failure_count == 0:
            self._jobs.update_status(parent_id, "success")
        elif row.success_count == 0:
            self._jobs.update_status(parent_id, "failed", error_message="All children failed.")
        else:
            self._jobs.update_status(
                parent_id, "success", error_message=f"{row.failure_count} child(ren) failed."
            )
        self._jobs.clear_checkpoint(parent_id)
        self._commit()

    def _materialize_batch_inputs(
        self, inputs: Path | list[Path] | bytes
    ) -> list[Path]:
        if isinstance(inputs, bytes):
            dest = self._outputs_dir.parent / "inputs" / f"_extract_{int(time.time())}"
            return self._preprocessor.extract_zip(inputs, dest)
        if isinstance(inputs, Path):
            if inputs.is_dir():
                return self._preprocessor.enumerate_dir(inputs)
            return [inputs] if inputs.is_file() else []
        if isinstance(inputs, list):
            from aquarender.core.preprocessor import iter_paths

            return iter_paths(inputs)
        return []


# ── helpers ────────────────────────────────────────────────────────────────────


def _overrides_to_json(overrides: SliderOverrides | None) -> dict[str, Any] | None:
    if overrides is None:
        return None
    return {
        "watercolor_strength": overrides.watercolor_strength,
        "structure_preservation": overrides.structure_preservation,
        "output_size": overrides.output_size,
        "custom_lora": overrides.custom_lora,
    }


def _overrides_from_json(data: dict[str, Any]) -> SliderOverrides:
    return SliderOverrides(
        watercolor_strength=data.get("watercolor_strength"),
        structure_preservation=data.get("structure_preservation"),
        output_size=data.get("output_size"),
        custom_lora=data.get("custom_lora"),
    )


def _input_filename_of(image: bytes | Path | Image.Image) -> str:
    if isinstance(image, Path):
        return image.name
    if isinstance(image, Image.Image):
        return getattr(image, "filename", None) or "image.png"
    return f"upload_{int(time.time())}.png"


def _input_path_of(image: bytes | Path | Image.Image) -> Path | str | None:
    if isinstance(image, Path):
        return image
    return None


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).replace(tzinfo=UTC)
    except ValueError:
        try:
            return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        except ValueError:
            return None


def _output_ref_from_row(job_id: JobId, output_row: Any) -> OutputRef:
    return OutputRef(
        job_id=job_id,
        output_path=Path(output_row.output_path),
        sidecar_path=Path(output_row.output_path).with_suffix(".json"),
        seed=output_row.seed,
        duration_ms=output_row.duration_ms,
    )


def _seed_from_filename(filename: str) -> int:
    h = hashlib.sha1(filename.encode("utf-8")).digest()
    return int.from_bytes(h[:4], "big")


def _resolve_seed(mode: SeedMode, fixed_seed: int | None, filename: str) -> int:
    if mode == "fixed":
        if fixed_seed is None:
            raise AquaRenderError("seed_mode='fixed' requires fixed_seed")
        return int(fixed_seed)
    if mode == "filename_hash":
        return _seed_from_filename(filename)
    return random.randint(0, 2**32 - 1)


def _checkpoint_path(outputs_dir: Path, batch_id: str) -> Path:
    return outputs_dir / f".checkpoint.{batch_id}.json"


def _write_checkpoint(outputs_dir: Path, batch_id: str, data: dict[str, Any]) -> None:
    outputs_dir.mkdir(parents=True, exist_ok=True)
    _checkpoint_path(outputs_dir, batch_id).write_text(json.dumps(data, indent=2))


def _read_checkpoint(outputs_dir: Path, batch_id: str) -> dict[str, Any] | None:
    p = _checkpoint_path(outputs_dir, batch_id)
    if not p.exists():
        return None
    data: dict[str, Any] = json.loads(p.read_text())
    return data


def _bump_checkpoint(outputs_dir: Path, batch_id: str, next_index: int) -> None:
    data = _read_checkpoint(outputs_dir, batch_id)
    if data is None:
        return
    data["next_index"] = next_index
    _write_checkpoint(outputs_dir, batch_id, data)


def _read_image_bytes(path: Path) -> bytes:
    return path.read_bytes()


# Re-export for tests / callers
__all__ = [
    "EngineContext",
    "JobOrchestrator",
    "JobStatus",
    "OutputRef",
    "Progress",
]
