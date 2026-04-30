"""Build the ComfyUI workflow graph from resolved params + an uploaded image ref.

One template lives at workflows/img2img_controlnet_lora.json; we deep-copy it
and substitute node inputs. Adding a new preset never edits the template.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from aquarender.engine.types import ImageRef
from aquarender.params import ResolvedParams


class WorkflowBuilder:
    def __init__(self, template_path: Path) -> None:
        self._template_path = template_path
        self._template_cache: dict[str, Any] | None = None

    def _template(self) -> dict[str, Any]:
        if self._template_cache is None:
            with self._template_path.open("r", encoding="utf-8") as f:
                self._template_cache = json.load(f)
        return self._template_cache

    def build(self, image_ref: ImageRef, params: ResolvedParams, seed: int) -> dict[str, Any]:
        wf: dict[str, Any] = copy.deepcopy(self._template())

        # 1: CheckpointLoaderSimple
        wf["1"]["inputs"]["ckpt_name"] = params.model.checkpoint

        # 2: LoraLoader
        wf["2"]["inputs"]["lora_name"] = params.lora.name
        wf["2"]["inputs"]["strength_model"] = params.lora.weight
        wf["2"]["inputs"]["strength_clip"] = params.lora.weight

        # 3/4: positive / negative CLIPTextEncode
        wf["3"]["inputs"]["text"] = params.prompt.positive
        wf["4"]["inputs"]["text"] = params.prompt.negative

        # 5: LoadImage — use the uploaded ref name. ComfyUI auto-resolves type=input.
        if image_ref.subfolder:
            wf["5"]["inputs"]["image"] = f"{image_ref.subfolder}/{image_ref.name}"
        else:
            wf["5"]["inputs"]["image"] = image_ref.name

        # 7: ControlNetLoader
        wf["7"]["inputs"]["control_net_name"] = params.controlnet.model

        # 10: ControlNetApplyAdvanced
        wf["10"]["inputs"]["strength"] = params.controlnet.strength
        wf["10"]["inputs"]["start_percent"] = params.controlnet.start_percent
        wf["10"]["inputs"]["end_percent"] = params.controlnet.end_percent

        # 8: KSampler
        wf["8"]["inputs"]["seed"] = int(seed)
        wf["8"]["inputs"]["steps"] = params.sampler.steps
        wf["8"]["inputs"]["cfg"] = params.sampler.cfg
        wf["8"]["inputs"]["sampler_name"] = params.sampler.name
        wf["8"]["inputs"]["scheduler"] = params.sampler.scheduler
        wf["8"]["inputs"]["denoise"] = params.sampler.denoise

        # 9: SaveImage prefix
        wf["9"]["inputs"]["filename_prefix"] = "aquarender"

        return wf


def default_template_path() -> Path:
    """Resolve the default workflow template ./workflows/img2img_controlnet_lora.json."""
    # Walk up from this file to find the project root (which contains workflows/).
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        candidate = parent / "workflows" / "img2img_controlnet_lora.json"
        if candidate.exists():
            return candidate
    # Fall back to CWD-relative
    return Path("workflows/img2img_controlnet_lora.json").resolve()
