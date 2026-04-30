"""HTTP client over remote ComfyUI. The only place that knows the engine is remote.

Endpoints documented in API.md § Part 2.
"""
from __future__ import annotations

import asyncio
import io
import time
import uuid
from typing import Any
from urllib.parse import urlparse

import httpx
from PIL import Image

from aquarender.engine.types import EngineInfo, ExecutionResult, ImageRef
from aquarender.errors import (
    CheckpointMissingError,
    ControlNetMissingError,
    EngineError,
    GenerationFailedError,
    GenerationTimeoutError,
    LoraMissingError,
    TunnelDownError,
)
from aquarender.types import EngineType

_DEFAULT_TIMEOUT_S = 90
_SAVE_NODE_ID = "9"  # SaveImage node in our workflow template


class RemoteComfyUIClient:
    """Async HTTP wrapper around the remote ComfyUI instance.

    `base_url` is whatever Cloudflare Tunnel printed in the Kaggle notebook.
    Reuses one httpx.AsyncClient per instance.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: int = _DEFAULT_TIMEOUT_S,
        secret: str | None = None,
        client_id: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.secret = secret
        self.client_id = client_id or f"aquarender-{uuid.uuid4()}"

        headers: dict[str, str] = {"User-Agent": f"AquaRender/0.1 ({self.client_id})"}
        if secret:
            headers["X-AquaRender-Auth"] = secret
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout_s, connect=10.0),
            headers=headers,
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> RemoteComfyUIClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    # ── health / discovery ──

    async def health(self) -> EngineInfo:
        try:
            stats = (await self._http.get("/system_stats")).json()
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
            raise TunnelDownError(self.base_url, str(e)) from e
        except httpx.HTTPError as e:
            raise EngineError(f"system_stats failed: {e}") from e

        gpu_name: str | None = None
        vram_total_mb: int | None = None
        vram_free_mb: int | None = None
        devices = stats.get("devices") or []
        if devices:
            d0 = devices[0]
            gpu_name = d0.get("name")
            if d0.get("vram_total"):
                vram_total_mb = int(d0["vram_total"]) // (1024 * 1024)
            if d0.get("vram_free"):
                vram_free_mb = int(d0["vram_free"]) // (1024 * 1024)

        comfy_version = (stats.get("system") or {}).get("comfyui_version")

        # Lists; tolerate missing nodes by returning empty
        try:
            object_info = (await self._http.get("/object_info")).json()
        except httpx.HTTPError:
            object_info = {}
        ckpts = _extract_combo(object_info, "CheckpointLoaderSimple", "ckpt_name")
        loras = _extract_combo(object_info, "LoraLoader", "lora_name")
        cnets = _extract_combo(object_info, "ControlNetLoader", "control_net_name")

        return EngineInfo(
            reachable=True,
            gpu_name=gpu_name,
            vram_total_mb=vram_total_mb,
            vram_free_mb=vram_free_mb,
            comfyui_version=comfy_version,
            available_checkpoints=ckpts,
            available_loras=loras,
            available_controlnets=cnets,
            inferred_engine_type=infer_engine_type(self.base_url),
        )

    async def list_loras(self) -> list[str]:
        info = (await self._http.get("/object_info")).json()
        return _extract_combo(info, "LoraLoader", "lora_name")

    async def list_controlnets(self) -> list[str]:
        info = (await self._http.get("/object_info")).json()
        return _extract_combo(info, "ControlNetLoader", "control_net_name")

    async def list_checkpoints(self) -> list[str]:
        info = (await self._http.get("/object_info")).json()
        return _extract_combo(info, "CheckpointLoaderSimple", "ckpt_name")

    # ── work submission ──

    async def upload_image(self, image: Image.Image, *, filename: str | None = None) -> ImageRef:
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        buf.seek(0)
        name = filename or f"aqua_{uuid.uuid4().hex}.png"
        try:
            r = await self._http.post(
                "/upload/image",
                files={"image": (name, buf.getvalue(), "image/png")},
                data={"type": "input", "overwrite": "true"},
            )
            r.raise_for_status()
            data = r.json()
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise TunnelDownError(self.base_url, str(e)) from e
        except httpx.HTTPError as e:
            raise EngineError(f"upload_image failed: {e}") from e
        return ImageRef(
            name=str(data["name"]),
            subfolder=str(data.get("subfolder") or ""),
            type=str(data.get("type") or "input"),
        )

    async def queue_prompt(self, workflow: dict[str, Any]) -> str:
        try:
            r = await self._http.post(
                "/prompt",
                json={"prompt": workflow, "client_id": self.client_id},
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise TunnelDownError(self.base_url, str(e)) from e
        except httpx.HTTPError as e:
            raise EngineError(f"queue_prompt transport error: {e}") from e

        if r.status_code >= 400:
            _raise_node_error_from_body(r)

        body = r.json()
        node_errors = body.get("node_errors") or {}
        if node_errors:
            _raise_node_error(node_errors)
        return str(body["prompt_id"])

    async def poll_until_done(
        self,
        prompt_id: str,
        *,
        timeout_s: int | None = None,
        poll_interval_s: float = 1.0,
    ) -> ExecutionResult:
        budget = timeout_s if timeout_s is not None else self.timeout_s
        deadline = time.monotonic() + budget
        while True:
            if time.monotonic() > deadline:
                raise GenerationTimeoutError(
                    f"Generation {prompt_id} exceeded {budget}s",
                )
            try:
                r = await self._http.get(f"/history/{prompt_id}")
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
                raise TunnelDownError(self.base_url, str(e)) from e
            except httpx.HTTPError as e:
                raise EngineError(f"history poll failed: {e}") from e

            history = r.json() or {}
            entry = history.get(prompt_id)
            if entry is not None:
                status = entry.get("status") or {}
                if status.get("completed"):
                    if status.get("status_str") == "error":
                        raise GenerationFailedError(_format_history_error(entry))
                    save_outputs = (entry.get("outputs") or {}).get(_SAVE_NODE_ID) or {}
                    images = save_outputs.get("images") or []
                    if not images:
                        # Look at any output node — be lenient about node ids.
                        for node_outputs in (entry.get("outputs") or {}).values():
                            if isinstance(node_outputs, dict) and node_outputs.get("images"):
                                images = node_outputs["images"]
                                break
                    if not images:
                        raise GenerationFailedError(
                            f"Prompt {prompt_id} completed without images."
                        )
                    img = images[0]
                    return ExecutionResult(
                        prompt_id=prompt_id,
                        output_filename=str(img["filename"]),
                        output_subfolder=str(img.get("subfolder") or ""),
                        output_type=str(img.get("type") or "output"),
                        raw_history=entry,
                    )
            await asyncio.sleep(poll_interval_s)

    async def fetch_output(self, prompt_id: str, result: ExecutionResult | None = None) -> bytes:
        if result is None:
            result = await self.poll_until_done(prompt_id)
        try:
            r = await self._http.get(
                "/view",
                params={
                    "filename": result.output_filename,
                    "subfolder": result.output_subfolder,
                    "type": result.output_type,
                },
            )
            r.raise_for_status()
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise TunnelDownError(self.base_url, str(e)) from e
        except httpx.HTTPError as e:
            raise EngineError(f"fetch_output failed: {e}") from e
        return r.content

    async def interrupt(self) -> None:
        try:
            await self._http.post("/interrupt")
        except httpx.HTTPError:
            pass

    async def keepalive_ping(self) -> None:
        try:
            await self._http.get("/", timeout=5.0)
        except httpx.HTTPError:
            # Best-effort; the tunnel monitor reports actual outages
            pass


def _extract_combo(object_info: dict[str, Any], node: str, field: str) -> list[str]:
    spec = object_info.get(node) or {}
    required = ((spec.get("input") or {}).get("required")) or {}
    raw = required.get(field)
    if not raw:
        return []
    # ComfyUI returns combos as `[ [values...], { ...meta } ]`
    if isinstance(raw, list) and raw:
        first = raw[0]
        if isinstance(first, list):
            return [str(v) for v in first]
    return []


def infer_engine_type(base_url: str) -> EngineType:
    host = urlparse(base_url).hostname or ""
    if "kaggle" in host:
        return "kaggle"
    if "colab" in host or "googleusercontent" in host:
        return "colab"
    if "hf.space" in host or "huggingface" in host:
        return "hf-space"
    if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local"):
        return "local"
    return "unknown"


def _format_history_error(entry: dict[str, Any]) -> str:
    msgs = (entry.get("status") or {}).get("messages") or []
    parts: list[str] = []
    for m in msgs:
        if isinstance(m, list) and len(m) >= 2:
            parts.append(str(m[1]))
        else:
            parts.append(str(m))
    return "; ".join(parts) or "ComfyUI reported an error"


def _raise_node_error(node_errors: dict[str, Any]) -> None:
    for node_id, err in node_errors.items():
        cls = (err.get("class_type") if isinstance(err, dict) else None) or ""
        msg = ""
        if isinstance(err, dict):
            errs = err.get("errors") or []
            for e in errs:
                if isinstance(e, dict):
                    msg = str(e.get("message") or e.get("type") or msg)
        text = f"{cls}#{node_id}: {msg}".strip()
        if "lora" in cls.lower() or "lora" in msg.lower():
            raise LoraMissingError(_extract_name(msg) or text)
        if "controlnet" in cls.lower() or "controlnet" in msg.lower():
            raise ControlNetMissingError(_extract_name(msg) or text)
        if "checkpoint" in cls.lower() or "checkpoint" in msg.lower():
            raise CheckpointMissingError(_extract_name(msg) or text)
        raise EngineError(text or "ComfyUI rejected the workflow")
    raise EngineError("ComfyUI rejected the workflow with empty error map")


def _raise_node_error_from_body(r: httpx.Response) -> None:
    try:
        body = r.json()
    except ValueError:
        raise EngineError(
            f"ComfyUI responded {r.status_code}: {r.text[:200]}",
            status=r.status_code,
        ) from None
    err = (body or {}).get("error") or {}
    msg = str(err.get("message") or body)
    raise EngineError(msg, status=r.status_code)


def _extract_name(message: str) -> str | None:
    """Heuristic: pull a `.safetensors`/`.ckpt` filename out of an error message."""
    import re

    m = re.search(r"([\w\-./]+\.(?:safetensors|ckpt|pth))", message)
    return m.group(1) if m else None
