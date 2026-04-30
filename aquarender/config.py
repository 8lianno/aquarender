"""Process-wide configuration loaded from env."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    db_url: str
    outputs_dir: Path
    inputs_dir: Path
    engine_url: str | None
    # repr=False so accidental `print(settings)` or structlog dump doesn't leak
    # the shared-secret header value into logs or crash reports.
    engine_secret: str | None = field(repr=False)

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            db_url=os.environ.get("AQUARENDER_DB_URL", "sqlite:///./aquarender.db"),
            outputs_dir=Path(os.environ.get("AQUARENDER_OUTPUTS_DIR", "./outputs")).resolve(),
            inputs_dir=Path(os.environ.get("AQUARENDER_INPUTS_DIR", "./inputs")).resolve(),
            engine_url=os.environ.get("AQUARENDER_ENGINE_URL") or None,
            engine_secret=os.environ.get("AQUARENDER_ENGINE_SECRET") or None,
        )

    def ensure_dirs(self) -> None:
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self.inputs_dir.mkdir(parents=True, exist_ok=True)
