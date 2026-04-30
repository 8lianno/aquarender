"""Presets page — list, view, export, import, delete user presets."""
from __future__ import annotations

import json

import streamlit as st

from aquarender.errors import AquaRenderError
from aquarender.ui.deps import get_context


def render() -> None:
    ctx = get_context()
    st.header("Presets")
    presets = ctx.preset_service.list()

    for p in presets:
        with st.expander(f"{p.name} ({p.id})  {'· builtin' if p.is_builtin else ''}"):
            st.write(p.description or "_(no description)_")
            st.json(p.params.model_dump())
            col1, col2 = st.columns(2)
            with col1:
                payload = json.dumps(ctx.preset_service.export(p.id), indent=2)
                st.download_button(
                    "Export JSON", payload, file_name=f"{p.id}.json", mime="application/json"
                )
            with col2:
                if not p.is_builtin and st.button(f"Delete {p.id}", key=f"delete-{p.id}"):
                    try:
                        ctx.preset_service.delete(p.id)
                        st.success(f"Deleted {p.id}")
                        st.rerun()
                    except AquaRenderError as e:
                        st.error(str(e))

    st.divider()
    st.subheader("Import preset")
    uploaded = st.file_uploader("Preset JSON", type=["json"])
    if uploaded is not None:
        try:
            data = json.loads(uploaded.getvalue().decode("utf-8"))
            new = ctx.preset_service.import_(data)
            st.success(f"Imported as {new.id}")
            st.rerun()
        except (AquaRenderError, ValueError) as e:
            st.error(f"Import failed: {e}")
