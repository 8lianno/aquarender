from __future__ import annotations

import io
import json
from pathlib import Path

from PIL import Image

from aquarender.core.metadata import EngineContext, MetadataWriter
from aquarender.params import (
    ControlNetParams,
    LoraParams,
    ModelParams,
    OutputParams,
    PromptParams,
    ResolvedParams,
    SamplerParams,
)


def _make_params() -> ResolvedParams:
    return ResolvedParams(
        model=ModelParams(checkpoint="sd_xl_base_1.0.safetensors"),
        lora=LoraParams(name="watercolor.safetensors", weight=0.8),
        controlnet=ControlNetParams(
            model="lineart.safetensors", preprocessor="lineart_realistic", strength=0.85
        ),
        sampler=SamplerParams(name="dpmpp_2m_sde", scheduler="karras", steps=28, cfg=5.5, denoise=0.5),
        prompt=PromptParams(positive="watercolor painting"),
        output=OutputParams(width=1024, height=1024, format="png"),
    )


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (1024, 1024), color=(200, 180, 160)).save(buf, "PNG")
    return buf.getvalue()


def test_write_creates_png_and_sidecar(tmp_path: Path) -> None:
    writer = MetadataWriter(tmp_path)
    engine = EngineContext(
        session_id="sess-1",
        engine_type="kaggle",
        gpu_name="P100",
        comfyui_version="0.3.10",
        tunnel_url="https://abc.trycloudflare.com",
    )
    written = writer.write(
        job_id="job-1",
        batch_id=None,
        preset_id="soft_watercolor",
        preset_name="Soft Watercolor",
        input_path="/tmp/x.png",
        input_filename="x.png",
        output_bytes=_png_bytes(),
        params=_make_params(),
        seed=42,
        duration_ms=12345,
        engine=engine,
    )
    assert written.output_path.exists()
    assert written.sidecar_path.exists()
    sidecar = json.loads(written.sidecar_path.read_text())
    assert sidecar["seed"] == 42
    assert sidecar["preset_id"] == "soft_watercolor"
    assert sidecar["engine"]["session_id"] == "sess-1"
    assert sidecar["params"]["lora"]["weight"] == 0.8


def test_batch_outputs_under_batch_dir(tmp_path: Path) -> None:
    writer = MetadataWriter(tmp_path)
    engine = EngineContext(
        session_id="s",
        engine_type="kaggle",
        gpu_name=None,
        comfyui_version=None,
        tunnel_url="https://x.test",
    )
    out = writer.write(
        job_id="j",
        batch_id="batch-7",
        preset_id="soft_watercolor",
        preset_name="x",
        input_path="x.png",
        input_filename="x.png",
        output_bytes=_png_bytes(),
        params=_make_params(),
        seed=1,
        duration_ms=1,
        engine=engine,
    )
    assert "batch-7" in str(out.output_path)


def test_unique_path_avoids_clobber(tmp_path: Path) -> None:
    writer = MetadataWriter(tmp_path)
    engine = EngineContext(
        session_id="s",
        engine_type="kaggle",
        gpu_name=None,
        comfyui_version=None,
        tunnel_url="https://x.test",
    )
    paths = []
    for _ in range(2):
        out = writer.write(
            job_id="j",
            batch_id="batch-1",
            preset_id="p",
            preset_name="p",
            input_path="same.png",
            input_filename="same.png",
            output_bytes=_png_bytes(),
            params=_make_params(),
            seed=1,
            duration_ms=1,
            engine=engine,
        )
        paths.append(out.output_path)
    assert paths[0] != paths[1]
