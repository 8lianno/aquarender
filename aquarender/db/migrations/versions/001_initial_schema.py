"""initial schema with builtin presets

Revision ID: 001
Revises:
Create Date: 2026-04-30
"""
from __future__ import annotations

import json
from importlib import resources
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


BUILTIN_PRESET_FILES = (
    "soft_watercolor.json",
    "ink_watercolor.json",
    "childrens_book.json",
    "product_watercolor.json",
)


def upgrade() -> None:
    op.create_table(
        "presets",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("params_json", sa.Text, nullable=False),
        sa.Column("is_builtin", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.Text, nullable=False, server_default=sa.func.datetime("now")),
        sa.Column("updated_at", sa.Text, nullable=False, server_default=sa.func.datetime("now")),
        sa.CheckConstraint("is_builtin IN (0, 1)", name="ck_presets_is_builtin"),
    )
    op.create_index("idx_presets_is_builtin", "presets", ["is_builtin"])

    op.create_table(
        "engine_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tunnel_url", sa.Text, nullable=False),
        sa.Column("engine_type", sa.Text, nullable=False),
        sa.Column("gpu_name", sa.Text),
        sa.Column("comfyui_version", sa.Text),
        sa.Column(
            "first_seen_at", sa.Text, nullable=False, server_default=sa.func.datetime("now")
        ),
        sa.Column(
            "last_seen_at", sa.Text, nullable=False, server_default=sa.func.datetime("now")
        ),
        sa.Column("disconnected_at", sa.Text),
        sa.CheckConstraint(
            "engine_type IN ('kaggle', 'colab', 'hf-space', 'local', 'unknown')",
            name="ck_engine_sessions_type",
        ),
    )
    op.create_index(
        "idx_engine_sessions_active",
        "engine_sessions",
        ["disconnected_at"],
        sqlite_where=sa.text("disconnected_at IS NULL"),
    )
    op.create_index(
        "idx_engine_sessions_first_seen", "engine_sessions", ["first_seen_at"]
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "parent_job_id",
            sa.String(36),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "preset_id", sa.String(64), sa.ForeignKey("presets.id"), nullable=False
        ),
        sa.Column(
            "engine_session_id",
            sa.String(36),
            sa.ForeignKey("engine_sessions.id"),
        ),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("overrides_json", sa.Text),
        sa.Column("input_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("success_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("paused_at_index", sa.Integer),
        sa.Column("started_at", sa.Text),
        sa.Column("finished_at", sa.Text),
        sa.Column("error_message", sa.Text),
        sa.Column(
            "created_at", sa.Text, nullable=False, server_default=sa.func.datetime("now")
        ),
        sa.CheckConstraint(
            "kind IN ('single', 'batch', 'batch_item')", name="ck_jobs_kind"
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'paused', 'success', 'failed', 'cancelled')",
            name="ck_jobs_status",
        ),
        sa.CheckConstraint(
            "(kind IN ('single','batch') AND parent_job_id IS NULL) OR "
            "(kind = 'batch_item' AND parent_job_id IS NOT NULL)",
            name="ck_jobs_parent_consistency",
        ),
    )
    op.create_index("idx_jobs_status", "jobs", ["status"])
    op.create_index("idx_jobs_kind", "jobs", ["kind"])
    op.create_index("idx_jobs_parent_job_id", "jobs", ["parent_job_id"])
    op.create_index("idx_jobs_preset_id", "jobs", ["preset_id"])
    op.create_index("idx_jobs_engine_session_id", "jobs", ["engine_session_id"])
    op.create_index("idx_jobs_created_at", "jobs", ["created_at"])
    op.create_index("idx_jobs_status_kind", "jobs", ["status", "kind"])

    op.create_table(
        "outputs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "engine_session_id",
            sa.String(36),
            sa.ForeignKey("engine_sessions.id"),
            nullable=False,
        ),
        sa.Column("input_path", sa.Text, nullable=False),
        sa.Column("output_path", sa.Text, nullable=False),
        sa.Column("params_json", sa.Text, nullable=False),
        sa.Column("seed", sa.Integer, nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=False),
        sa.Column("width", sa.Integer, nullable=False),
        sa.Column("height", sa.Integer, nullable=False),
        sa.Column("file_size_bytes", sa.Integer, nullable=False),
        sa.Column(
            "created_at", sa.Text, nullable=False, server_default=sa.func.datetime("now")
        ),
    )
    op.create_index("idx_outputs_job_id", "outputs", ["job_id"])
    op.create_index("idx_outputs_engine_session_id", "outputs", ["engine_session_id"])
    op.create_index("idx_outputs_created_at", "outputs", ["created_at"])

    _seed_builtin_presets()


def downgrade() -> None:
    op.drop_index("idx_outputs_created_at", table_name="outputs")
    op.drop_index("idx_outputs_engine_session_id", table_name="outputs")
    op.drop_index("idx_outputs_job_id", table_name="outputs")
    op.drop_table("outputs")

    op.drop_index("idx_jobs_status_kind", table_name="jobs")
    op.drop_index("idx_jobs_created_at", table_name="jobs")
    op.drop_index("idx_jobs_engine_session_id", table_name="jobs")
    op.drop_index("idx_jobs_preset_id", table_name="jobs")
    op.drop_index("idx_jobs_parent_job_id", table_name="jobs")
    op.drop_index("idx_jobs_kind", table_name="jobs")
    op.drop_index("idx_jobs_status", table_name="jobs")
    op.drop_table("jobs")

    op.drop_index("idx_engine_sessions_first_seen", table_name="engine_sessions")
    op.drop_index("idx_engine_sessions_active", table_name="engine_sessions")
    op.drop_table("engine_sessions")

    op.drop_index("idx_presets_is_builtin", table_name="presets")
    op.drop_table("presets")


def _load_builtin_preset(filename: str) -> dict[str, Any]:
    pkg = resources.files("aquarender.presets")
    with (pkg / filename).open("r", encoding="utf-8") as f:
        return json.load(f)


def _seed_builtin_presets() -> None:
    rows = []
    for filename in BUILTIN_PRESET_FILES:
        data = _load_builtin_preset(filename)
        rows.append(
            {
                "id": data["id"],
                "name": data["name"],
                "description": data.get("description"),
                "params_json": json.dumps(data["params"], sort_keys=True),
                "is_builtin": 1,
            }
        )
    presets = sa.table(
        "presets",
        sa.column("id", sa.String),
        sa.column("name", sa.Text),
        sa.column("description", sa.Text),
        sa.column("params_json", sa.Text),
        sa.column("is_builtin", sa.Integer),
    )
    op.bulk_insert(presets, rows)
