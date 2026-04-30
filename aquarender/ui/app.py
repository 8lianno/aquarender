"""Streamlit entry point. Run with: `aquarender start`."""
from __future__ import annotations

import streamlit as st

from aquarender.logging_setup import configure_logging
from aquarender.ui.deps import get_context, get_engine_state
from aquarender.ui.pages import batch as batch_page
from aquarender.ui.pages import connect as connect_page
from aquarender.ui.pages import presets as presets_page
from aquarender.ui.pages import single as single_page

st.set_page_config(
    page_title="AquaRender",
    page_icon="🎨",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _render_engine_indicator() -> None:
    state = get_engine_state()
    if state is None:
        st.sidebar.markdown("**Engine** ❌ not connected")
    else:
        gpu = state.info.gpu_name or "GPU"
        st.sidebar.markdown(f"**Engine** ✅ {gpu}")
        st.sidebar.caption(state.base_url)


def main() -> None:
    configure_logging()
    get_context()  # warm cache

    st.sidebar.title("AquaRender")
    _render_engine_indicator()
    st.sidebar.divider()

    page = st.sidebar.radio(
        "Pages",
        options=["Connect", "Single image", "Batch", "Presets"],
        index=0 if get_engine_state() is None else 1,
        label_visibility="collapsed",
    )

    if page == "Connect":
        connect_page.render()
    elif page == "Single image":
        single_page.render()
    elif page == "Batch":
        batch_page.render()
    elif page == "Presets":
        presets_page.render()


main()
