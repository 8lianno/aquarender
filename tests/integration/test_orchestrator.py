"""Integration: orchestrator + real DB + FakeRemoteComfyUIClient."""
from __future__ import annotations

from pathlib import Path

import pytest

from aquarender.core.orchestrator import JobOrchestrator
from aquarender.engine.fakes import FakeRemoteComfyUIClient
from aquarender.errors import LoraMissingError
from aquarender.params import SliderOverrides


def test_run_single_happy_path(orchestrator: JobOrchestrator, sample_png: Path) -> None:
    job_id = orchestrator.run_single_sync(
        image=sample_png,
        preset_id="soft_watercolor",
    )
    status = orchestrator.get_status(job_id)
    assert status.status == "success"
    assert len(status.outputs) == 1
    assert status.outputs[0].output_path.exists()


def test_run_single_with_overrides(orchestrator: JobOrchestrator, sample_png: Path) -> None:
    job_id = orchestrator.run_single_sync(
        image=sample_png,
        preset_id="soft_watercolor",
        overrides=SliderOverrides(
            watercolor_strength="Strong", structure_preservation="Low"
        ),
    )
    status = orchestrator.get_status(job_id)
    assert status.status == "success"


def test_batch_happy_path(
    orchestrator: JobOrchestrator,
    sample_png: Path,
    tmp_path: Path,
) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    from PIL import Image

    for i in range(3):
        Image.new("RGB", (1024, 768), color=(50 * i, 100, 200)).save(inputs / f"img_{i}.png")

    batch_id = orchestrator.run_batch_sync(
        inputs=inputs,
        preset_id="soft_watercolor",
    )
    status = orchestrator.get_status(batch_id)
    assert status.status == "success"
    assert status.progress.succeeded == 3
    assert status.progress.failed == 0


def test_batch_isolates_per_image_failure(
    orchestrator: JobOrchestrator, tmp_path: Path
) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    from PIL import Image

    # 2 valid, 1 too small
    Image.new("RGB", (1024, 1024)).save(inputs / "ok1.png")
    Image.new("RGB", (1024, 1024)).save(inputs / "ok2.png")
    Image.new("RGB", (50, 50)).save(inputs / "too_small.png")

    batch_id = orchestrator.run_batch_sync(
        inputs=inputs,
        preset_id="soft_watercolor",
    )
    status = orchestrator.get_status(batch_id)
    assert status.progress.succeeded == 2
    assert status.progress.failed == 1


def test_lora_missing_rejects_run(
    orchestrator: JobOrchestrator,
    sample_png: Path,
) -> None:
    """Pre-flight LoRA check fails fast before a job row is even created."""
    with pytest.raises(LoraMissingError, match=r"ghost\.safetensors"):
        orchestrator.run_single_sync(
            image=sample_png,
            preset_id="soft_watercolor",
            overrides=SliderOverrides(custom_lora="ghost.safetensors"),
        )


def test_tunnel_drop_pauses_batch(
    orchestrator: JobOrchestrator,
    fake_client: FakeRemoteComfyUIClient,
    tmp_path: Path,
) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    from PIL import Image

    for i in range(5):
        Image.new("RGB", (1024, 768)).save(inputs / f"img_{i}.png")

    # Drop the tunnel after the orchestrator has done its preflight health check.
    # Simplest approach: monkeypatch fake_client's poll to drop after first call.
    original_poll = fake_client.poll_until_done
    call_count = {"n": 0}

    async def flaky_poll(prompt_id, *, timeout_s=None, poll_interval_s=0.0):
        call_count["n"] += 1
        if call_count["n"] >= 3:
            fake_client.simulate_tunnel_down()
        return await original_poll(prompt_id, timeout_s=timeout_s, poll_interval_s=poll_interval_s)

    fake_client.poll_until_done = flaky_poll  # type: ignore[method-assign]

    batch_id = orchestrator.run_batch_sync(
        inputs=inputs,
        preset_id="soft_watercolor",
    )
    status = orchestrator.get_status(batch_id)
    assert status.status == "paused"
    assert status.paused_at_index is not None and status.paused_at_index >= 1
