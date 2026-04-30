"""Batch page — directory or zip, run, progress, grid output."""
from __future__ import annotations

from typing import cast

import streamlit as st

from aquarender.errors import AquaRenderError
from aquarender.params import SliderOverrides
from aquarender.types import OutputSize, SeedMode, StructurePreservation, WatercolorStrength
from aquarender.ui.deps import get_context, require_engine


def render() -> None:
    require_engine()
    ctx = get_context()
    presets = ctx.preset_service.list()

    st.header("Batch")
    st.write("Drop a zip of images or pick an inputs folder.")

    uploaded_zip = st.file_uploader("Upload a .zip", type=["zip"])
    folder_path = st.text_input(
        "…or path to a local folder",
        placeholder=str(ctx.settings.inputs_dir),
        help="Use this if you have a folder on the same machine.",
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

    seed_mode = st.radio(
        "Seed mode",
        options=["random", "fixed", "filename_hash"],
        horizontal=True,
        help=(
            "random: each image new seed. "
            "fixed: same seed for whole batch. "
            "filename_hash: deterministic per filename."
        ),
    )
    fixed_seed = (
        st.number_input("Fixed seed", min_value=0, max_value=2**32 - 1, value=42, step=1)
        if seed_mode == "fixed"
        else None
    )

    can_run = uploaded_zip is not None or bool(folder_path.strip())
    if st.button("Run batch", type="primary", disabled=not can_run):
        try:
            inputs: object
            if uploaded_zip is not None:
                inputs = uploaded_zip.getvalue()
            else:
                from pathlib import Path

                inputs = Path(folder_path.strip())
            job_id = ctx.orchestrator.run_batch_sync(
                inputs=inputs,
                preset_id=preset_id,
                overrides=SliderOverrides(
                    watercolor_strength=cast(WatercolorStrength, strength),
                    structure_preservation=cast(StructurePreservation, preservation),
                    output_size=cast(OutputSize, output_size),
                ),
                seed_mode=cast(SeedMode, seed_mode),
                fixed_seed=int(fixed_seed) if fixed_seed is not None else None,
            )
        except AquaRenderError as e:
            st.error(f"Batch failed: {e}")
            return
        except Exception as e:
            st.error(f"Unexpected error: {e}")
            return

        st.session_state["last_batch_id"] = job_id
        st.rerun()

    last_batch_id = st.session_state.get("last_batch_id")
    if last_batch_id:
        _render_batch_status(last_batch_id)


def _render_batch_status(batch_id: str) -> None:
    ctx = get_context()
    try:
        status = ctx.orchestrator.get_status(batch_id)
    except Exception as e:
        st.error(f"Could not load batch {batch_id}: {e}")
        return

    st.subheader(f"Batch {batch_id}")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Status", status.status)
    col2.metric("Total", status.progress.total)
    col3.metric("Succeeded", status.progress.succeeded)
    col4.metric("Failed", status.progress.failed)

    if status.status == "paused":
        st.warning(
            f"Tunnel dropped at image {status.paused_at_index}. Reconnect, then click Resume."
        )
        if st.button("Resume"):
            try:
                ctx.orchestrator.resume_sync(batch_id)
                st.rerun()
            except Exception as e:
                st.error(f"Resume failed: {e}")

    if status.children:
        cols = st.columns(4)
        for idx, child in enumerate(status.children):
            with cols[idx % 4]:
                if child.outputs:
                    st.image(str(child.outputs[0].output_path), use_column_width=True)
                else:
                    st.write(f"`{child.status}`")
                st.caption(f"{child.status} · {child.outputs[0].seed if child.outputs else ''}")
