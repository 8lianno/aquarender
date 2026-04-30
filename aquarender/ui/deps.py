"""Streamlit-side dependency wiring (cached singletons).

UI files only ever talk to:
  - get_context()  → orchestrator + presets + settings
  - get_engine_state() / set_engine_state()  → connect/disconnect lifecycle
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import streamlit as st

from aquarender.deps import AquaRenderContext, build_context


@st.cache_resource
def get_context() -> AquaRenderContext:
    return build_context()


@dataclass(slots=True)
class EngineState:
    base_url: str
    secret: str | None
    # `EngineInfo` lives in aquarender.engine; we hold it as Any here to keep
    # the UI layer from depending on the engine package directly.
    info: Any
    session_id: str
    last_event: str | None = None


def get_engine_state() -> EngineState | None:
    return st.session_state.get("engine_state")


def set_engine_state(state: EngineState | None) -> None:
    st.session_state["engine_state"] = state


def require_engine() -> EngineState:
    state = get_engine_state()
    if state is None:
        st.warning("Connect to an engine first — go to **Connect** in the sidebar.")
        st.stop()
        raise RuntimeError("unreachable: st.stop()")
    return state
