"""Single-image page — upload, slider, generate, before/after."""
from __future__ import annotations

import io
from typing import cast

import streamlit as st
from PIL import Image

from aquarender.errors import AquaRenderError
from aquarender.params import SliderOverrides
from aquarender.types import OutputSize, StructurePreservation, WatercolorStrength
from aquarender.ui.deps import get_context, require_engine


def render() -> None:
    require_engine()
    ctx = get_context()
    presets = ctx.preset_service.list()

    st.header("Single image")

    uploaded = st.file_uploader(
        "Upload an image", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=False
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        preset_id = st.selectbox(
            "Preset",
            options=[p.id for p in presets],
            format_func=lambda pid: next(p.name for p in presets if p.id == pid),
        )
    with col2:
        strength = st.select_slider(
            "Watercolor strength", options=["Light", "Medium", "Strong"], value="Medium"
        )
    with col3:
        preservation = st.select_slider(
            "Structure preservation", options=["Low", "Medium", "High"], value="Medium"
        )

    output_size = st.select_slider("Output size", options=[768, 1024, 1536], value=1024)
    custom_lora = st.text_input(
        "Custom LoRA filename (optional)",
        placeholder="my_custom_watercolor.safetensors",
        help="Override the preset's LoRA. Must already be loaded on the remote.",
    )

    can_generate = uploaded is not None
    if st.button("Generate", type="primary", disabled=not can_generate):
        if uploaded is None:
            return
        try:
            data = uploaded.getvalue()
            job_id = ctx.orchestrator.run_single_sync(
                image=data,
                preset_id=preset_id,
                overrides=SliderOverrides(
                    watercolor_strength=cast(WatercolorStrength, strength),
                    structure_preservation=cast(StructurePreservation, preservation),
                    output_size=cast(OutputSize, output_size),
                    custom_lora=custom_lora.strip() or None,
                ),
            )
        except AquaRenderError as e:
            st.error(f"Generation failed: {e}")
            return
        except Exception as e:
            st.error(f"Unexpected error: {e}")
            return

        status = ctx.orchestrator.get_status(job_id)
        if status.status == "success" and status.outputs:
            ref = status.outputs[0]
            st.success(f"Done in {ref.duration_ms / 1000:.1f}s")
            col_in, col_out = st.columns(2)
            with col_in:
                st.subheader("Input")
                st.image(Image.open(io.BytesIO(data)))
            with col_out:
                st.subheader("Watercolor")
                st.image(str(ref.output_path))
            with open(ref.output_path, "rb") as f:
                st.download_button(
                    "Download PNG",
                    f.read(),
                    file_name=ref.output_path.name,
                    mime="image/png",
                )
        elif status.status == "paused":
            st.warning(
                "Engine connection dropped during generation. Reconnect on the **Connect** "
                "tab — the job is paused, not failed."
            )
        else:
            st.error(f"Job {status.status}: {status.error_message or ''}")
