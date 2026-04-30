"""In-memory fake of RemoteComfyUIClient — the lifeblood of unit tests."""
from __future__ import annotations

import io
import uuid
from pathlib import Path
from typing import Any

from PIL import Image

from aquarender.engine.types import EngineInfo, ExecutionResult, ImageRef
from aquarender.errors import LoraMissingError, TunnelDownError


class FakeRemoteComfyUIClient:
    def __init__(
        self,
        *,
        fixture_image: bytes | Path | None = None,
        gpu_name: str = "Tesla P100-PCIE-16GB",
        comfyui_version: str = "0.3.10",
        loras: list[str] | None = None,
        controlnets: list[str] | None = None,
        checkpoints: list[str] | None = None,
        engine_type: str = "kaggle",
        base_url: str = "https://fake.test",
    ) -> None:
        self.base_url = base_url
        self.client_id = f"aquarender-fake-{uuid.uuid4()}"
        self._fixture = fixture_image
        self._gpu = gpu_name
        self._version = comfyui_version
        self._loras = loras or ["watercolor_style_lora_sdxl.safetensors"]
        self._controlnets = controlnets or [
            "diffusers_xl_lineart_full.safetensors",
            "diffusers_xl_canny_full.safetensors",
        ]
        self._checkpoints = checkpoints or ["sd_xl_base_1.0.safetensors"]
        self._engine_type = engine_type
        self._tunnel_alive = True
        self._fail_next_queue: str | None = None
        self._uploaded: list[ImageRef] = []
        self._submitted_prompts: list[dict[str, Any]] = []

    # ── tunnel simulation ──

    def simulate_tunnel_down(self) -> None:
        self._tunnel_alive = False

    def simulate_tunnel_up(self) -> None:
        self._tunnel_alive = True

    def fail_next_queue(self, *, reason: str = "lora") -> None:
        self._fail_next_queue = reason

    def _check(self) -> None:
        if not self._tunnel_alive:
            raise TunnelDownError(self.base_url, "simulated")

    # ── client surface ──

    async def aclose(self) -> None:
        return None

    async def __aenter__(self) -> FakeRemoteComfyUIClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def health(self) -> EngineInfo:
        self._check()
        return EngineInfo(
            reachable=True,
            gpu_name=self._gpu,
            vram_total_mb=16 * 1024,
            vram_free_mb=14 * 1024,
            comfyui_version=self._version,
            available_checkpoints=list(self._checkpoints),
            available_loras=list(self._loras),
            available_controlnets=list(self._controlnets),
            inferred_engine_type=self._engine_type,  # type: ignore[arg-type]
        )

    async def list_loras(self) -> list[str]:
        self._check()
        return list(self._loras)

    async def list_controlnets(self) -> list[str]:
        self._check()
        return list(self._controlnets)

    async def list_checkpoints(self) -> list[str]:
        self._check()
        return list(self._checkpoints)

    async def upload_image(self, image: Image.Image, *, filename: str | None = None) -> ImageRef:
        self._check()
        ref = ImageRef(name=filename or f"fake_{uuid.uuid4().hex}.png")
        self._uploaded.append(ref)
        return ref

    async def queue_prompt(self, workflow: dict[str, Any]) -> str:
        self._check()
        if self._fail_next_queue is not None:
            kind = self._fail_next_queue
            self._fail_next_queue = None
            if kind == "lora":
                raise LoraMissingError(workflow["2"]["inputs"]["lora_name"])
        self._submitted_prompts.append(workflow)
        return f"fake-prompt-{len(self._submitted_prompts)}"

    async def poll_until_done(
        self,
        prompt_id: str,
        *,
        timeout_s: int | None = None,
        poll_interval_s: float = 0.0,
    ) -> ExecutionResult:
        self._check()
        return ExecutionResult(
            prompt_id=prompt_id,
            output_filename=f"{prompt_id}.png",
            output_subfolder="",
            output_type="output",
            raw_history={"status": {"completed": True, "status_str": "success"}},
        )

    async def fetch_output(self, prompt_id: str, result: ExecutionResult | None = None) -> bytes:
        self._check()
        if isinstance(self._fixture, Path):
            return self._fixture.read_bytes()
        if isinstance(self._fixture, (bytes, bytearray)):
            return bytes(self._fixture)
        # Synthesize a tiny valid PNG so tests don't require a fixture file.
        img = Image.new("RGB", (1024, 1024), color=(180, 200, 220))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    async def interrupt(self) -> None:
        return None

    async def keepalive_ping(self) -> None:
        return None
