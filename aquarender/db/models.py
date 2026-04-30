"""SQLAlchemy 2.0 ORM models. Mirrors DATABASE.md."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class PresetModel(Base):
    __tablename__ = "presets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    params_json: Mapped[str] = mapped_column(Text, nullable=False)
    is_builtin: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=func.datetime("now")
    )
    updated_at: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=func.datetime("now")
    )

    __table_args__ = (
        CheckConstraint("is_builtin IN (0, 1)", name="ck_presets_is_builtin"),
        Index("idx_presets_is_builtin", "is_builtin"),
    )


class EngineSessionModel(Base):
    __tablename__ = "engine_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tunnel_url: Mapped[str] = mapped_column(Text, nullable=False)
    engine_type: Mapped[str] = mapped_column(Text, nullable=False)
    gpu_name: Mapped[str | None] = mapped_column(Text)
    comfyui_version: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=func.datetime("now")
    )
    last_seen_at: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=func.datetime("now")
    )
    disconnected_at: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "engine_type IN ('kaggle', 'colab', 'hf-space', 'local', 'unknown')",
            name="ck_engine_sessions_type",
        ),
        Index(
            "idx_engine_sessions_active",
            "disconnected_at",
            sqlite_where=text("disconnected_at IS NULL"),
        ),
        Index("idx_engine_sessions_first_seen", "first_seen_at"),
    )


class JobModel(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    parent_job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="CASCADE")
    )
    preset_id: Mapped[str] = mapped_column(String(64), ForeignKey("presets.id"), nullable=False)
    engine_session_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("engine_sessions.id")
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    overrides_json: Mapped[str | None] = mapped_column(Text)
    input_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    paused_at_index: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=func.datetime("now")
    )

    output: Mapped[OutputModel | None] = relationship(back_populates="job", uselist=False)

    __table_args__ = (
        CheckConstraint("kind IN ('single', 'batch', 'batch_item')", name="ck_jobs_kind"),
        CheckConstraint(
            "status IN ('queued', 'running', 'paused', 'success', 'failed', 'cancelled')",
            name="ck_jobs_status",
        ),
        CheckConstraint(
            "(kind IN ('single','batch') AND parent_job_id IS NULL) OR "
            "(kind = 'batch_item' AND parent_job_id IS NOT NULL)",
            name="ck_jobs_parent_consistency",
        ),
        Index("idx_jobs_status", "status"),
        Index("idx_jobs_kind", "kind"),
        Index("idx_jobs_parent_job_id", "parent_job_id"),
        Index("idx_jobs_preset_id", "preset_id"),
        Index("idx_jobs_engine_session_id", "engine_session_id"),
        Index("idx_jobs_created_at", "created_at"),
        Index("idx_jobs_status_kind", "status", "kind"),
    )


class OutputModel(Base):
    __tablename__ = "outputs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    engine_session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("engine_sessions.id"), nullable=False
    )
    input_path: Mapped[str] = mapped_column(Text, nullable=False)
    output_path: Mapped[str] = mapped_column(Text, nullable=False)
    params_json: Mapped[str] = mapped_column(Text, nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=func.datetime("now")
    )

    job: Mapped[JobModel] = relationship(back_populates="output")

    __table_args__ = (
        Index("idx_outputs_job_id", "job_id"),
        Index("idx_outputs_engine_session_id", "engine_session_id"),
        Index("idx_outputs_created_at", "created_at"),
    )


def _now() -> datetime:  # pragma: no cover — convenience for typing
    return datetime.utcnow()


__all__ = ["Any", "Base", "EngineSessionModel", "JobModel", "OutputModel", "PresetModel"]
