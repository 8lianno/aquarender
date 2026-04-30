"""Connect page — paste tunnel URL, verify, store engine state."""
from __future__ import annotations

import asyncio

import streamlit as st

from aquarender.config import Settings
from aquarender.deps import connect_engine
from aquarender.errors import TunnelDownError
from aquarender.ui.deps import EngineState, get_context, get_engine_state, set_engine_state


def render() -> None:
    st.header("Connect to engine")
    st.write(
        "AquaRender drives a remote ComfyUI engine running on Kaggle (or any "
        "tunnel-exposed ComfyUI). Open the Kaggle notebook, copy the printed "
        "tunnel URL, and paste it below."
    )

    state = get_engine_state()
    settings = Settings.from_env()

    default_url = state.base_url if state else (settings.engine_url or "")
    default_secret = state.secret if state else (settings.engine_secret or "")

    with st.form("connect-form", clear_on_submit=False):
        base_url = st.text_input("Engine URL", value=default_url, placeholder="https://abc-def.trycloudflare.com")
        secret = st.text_input("Shared secret (optional)", value=default_secret or "", type="password")
        submitted = st.form_submit_button("Connect")

    if submitted:
        url = base_url.strip().rstrip("/")
        if not url.startswith(("http://", "https://")):
            st.error("URL must start with http:// or https://")
            return
        with st.spinner("Probing engine…"):
            try:
                info, session_id = asyncio.run(_connect(url, secret or None))
            except TunnelDownError as e:
                st.error(f"Engine unreachable: {e.reason}")
                return
            except Exception as e:
                st.error(f"Failed to connect: {e}")
                return

        set_engine_state(
            EngineState(
                base_url=url,
                secret=secret or None,
                info=info,
                session_id=session_id,
            )
        )
        st.success(f"Connected — {getattr(info, 'gpu_name', None) or 'GPU'}, ComfyUI {getattr(info, 'comfyui_version', None) or '?'}")
        st.rerun()

    if state is not None:
        info = state.info
        st.divider()
        st.subheader("Status")
        col1, col2 = st.columns(2)
        with col1:
            st.metric("GPU", info.gpu_name or "—")
            st.metric("VRAM total", _mb_str(info.vram_total_mb))
        with col2:
            st.metric("ComfyUI", info.comfyui_version or "—")
            st.metric("VRAM free", _mb_str(info.vram_free_mb))

        st.write(f"**Checkpoints** ({len(info.available_checkpoints)})")
        st.code("\n".join(info.available_checkpoints) or "(none)")
        st.write(f"**LoRAs** ({len(info.available_loras)})")
        st.code("\n".join(info.available_loras) or "(none)")
        st.write(f"**ControlNets** ({len(info.available_controlnets)})")
        st.code("\n".join(info.available_controlnets) or "(none)")

        if st.button("Disconnect", type="secondary"):
            ctx = get_context()
            ctx.orchestrator.disconnect()
            set_engine_state(None)
            st.rerun()


async def _connect(url: str, secret: str | None) -> tuple[object, str]:
    ctx = get_context()
    info, engine_ctx = await connect_engine(ctx, url=url, secret=secret)
    return info, engine_ctx.session_id


def _mb_str(mb: int | None) -> str:
    if mb is None:
        return "—"
    if mb >= 1024:
        return f"{mb / 1024:.1f} GB"
    return f"{mb} MB"
