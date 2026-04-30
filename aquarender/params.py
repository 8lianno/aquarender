"""Pydantic models for resolved generation parameters and slider overrides.

These shapes are validated on every read of presets and metadata sidecars.
Schema lives in DATABASE.md § Resolved Params.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from aquarender.types import OutputSize, StructurePreservation, WatercolorStrength


class ModelParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checkpoint: str


class LoraParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    weight: float = Field(ge=0.0, le=2.0)


class ControlNetParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    preprocessor: Literal["lineart_realistic", "canny", "depth_midas"]
    strength: float = Field(ge=0.0, le=1.0)
    start_percent: float = Field(ge=0.0, le=1.0, default=0.0)
    end_percent: float = Field(ge=0.0, le=1.0, default=1.0)


class SamplerParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    scheduler: str
    steps: int = Field(ge=1, le=150)
    cfg: float = Field(ge=1.0, le=30.0)
    denoise: float = Field(ge=0.0, le=1.0)


class PromptParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    positive: str
    negative: str = ""


class OutputParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    width: int = Field(ge=256, le=2048)
    height: int = Field(ge=256, le=2048)
    format: Literal["png", "webp"] = "png"


class ResolvedParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    model: ModelParams
    lora: LoraParams
    controlnet: ControlNetParams
    sampler: SamplerParams
    prompt: PromptParams
    output: OutputParams


@dataclass(slots=True)
class SliderOverrides:
    watercolor_strength: WatercolorStrength | None = None
    structure_preservation: StructurePreservation | None = None
    output_size: OutputSize | None = None
    custom_lora: str | None = None


# Slider→numeric translation. Tuned defaults; only override per-preset in JSON.
SLIDER_TO_PARAMS: dict[str, dict[str, dict[str, float]]] = {
    "watercolor_strength": {
        "Light": {"denoise": 0.35, "lora_weight": 0.6},
        "Medium": {"denoise": 0.50, "lora_weight": 0.8},
        "Strong": {"denoise": 0.65, "lora_weight": 1.0},
    },
    "structure_preservation": {
        "Low": {"cn_strength": 0.50},
        "Medium": {"cn_strength": 0.75},
        "High": {"cn_strength": 0.90},
    },
}
