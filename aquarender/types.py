from __future__ import annotations

from typing import Literal

JobId = str
JobKind = Literal["single", "batch", "batch_item"]
JobStatusValue = Literal["queued", "running", "paused", "success", "failed", "cancelled"]
EngineType = Literal["kaggle", "colab", "hf-space", "local", "unknown"]
SeedMode = Literal["random", "fixed", "filename_hash"]
WatercolorStrength = Literal["Light", "Medium", "Strong"]
StructurePreservation = Literal["Low", "Medium", "High"]
OutputSize = Literal[768, 1024, 1536]
