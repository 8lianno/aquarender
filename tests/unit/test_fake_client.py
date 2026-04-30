from __future__ import annotations

import pytest

from aquarender.engine.fakes import FakeRemoteComfyUIClient
from aquarender.errors import LoraMissingError, TunnelDownError


@pytest.mark.asyncio
async def test_health_returns_engine_info() -> None:
    c = FakeRemoteComfyUIClient()
    info = await c.health()
    assert info.reachable
    assert info.gpu_name == "Tesla P100-PCIE-16GB"
    assert "watercolor_v1_sdxl.safetensors" in info.available_loras


@pytest.mark.asyncio
async def test_simulate_tunnel_down() -> None:
    c = FakeRemoteComfyUIClient()
    c.simulate_tunnel_down()
    with pytest.raises(TunnelDownError):
        await c.health()
    c.simulate_tunnel_up()
    info = await c.health()
    assert info.reachable


@pytest.mark.asyncio
async def test_fail_next_queue_lora_missing() -> None:
    c = FakeRemoteComfyUIClient()
    c.fail_next_queue(reason="lora")
    with pytest.raises(LoraMissingError):
        await c.queue_prompt({"2": {"inputs": {"lora_name": "x.safetensors"}}})


@pytest.mark.asyncio
async def test_full_round_trip() -> None:
    c = FakeRemoteComfyUIClient()
    from PIL import Image

    pil = Image.new("RGB", (1024, 1024))
    await c.upload_image(pil)
    pid = await c.queue_prompt({"any": "workflow"})
    result = await c.poll_until_done(pid)
    bytes_ = await c.fetch_output(pid, result)
    assert bytes_.startswith(b"\x89PNG")
