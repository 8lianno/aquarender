"""Engine-layer dataclasses. Pure values, no I/O."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aquarender.types import EngineType


@dataclass(slots=True)
class EngineInfo:
    reachable: bool
    gpu_name: str | None = None
    vram_total_mb: int | None = None
    vram_free_mb: int | None = None
    comfyui_version: str | None = None
    available_checkpoints: list[str] = field(default_factory=list)
    available_loras: list[str] = field(default_factory=list)
    available_controlnets: list[str] = field(default_factory=list)
    inferred_engine_type: EngineType = "unknown"


@dataclass(slots=True, frozen=True)
class ImageRef:
    name: str
    subfolder: str = ""
    type: str = "input"


@dataclass(slots=True)
class ExecutionResult:
    prompt_id: str
    output_filename: str
    output_subfolder: str
    output_type: str
    raw_history: dict[str, Any]


@dataclass(slots=True)
class TunnelEvent:
    kind: str  # 'tunnel_down' | 'tunnel_recovered' | 'tunnel_degraded'
    base_url: str
    detail: str | None = None
