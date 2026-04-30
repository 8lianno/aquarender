# AquaRender — API Reference

**Version**: 2.0
**Date**: 2026-04-30
**Scope**: Internal Python API (`core` + `engine`) and the remote ComfyUI HTTP surface we depend on

---

## Overview

AquaRender's "API" in v1 is **internal Python** — there is no AquaRender HTTP server. The Streamlit UI calls `core.JobOrchestrator` directly, which calls `engine.RemoteComfyUIClient` to drive a remote ComfyUI instance over HTTPS.

This doc covers two things:

1. **Internal Python API** — the surfaces UI/CLI/tests use. Stable contract.
2. **Remote ComfyUI HTTP API** — the third-party endpoints we consume. Documented here because version drift in ComfyUI is a real risk we manage.

A future external HTTP API (P2) is sketched at the end.

---

## Part 1 — Internal Python API

### `aquarender.core.orchestrator.JobOrchestrator`

The single coordination point. UI and CLI talk to this.

```python
class JobOrchestrator:
    def __init__(
        self,
        client: RemoteComfyUIClient,
        preset_service: PresetService,
        preprocessor: ImagePreprocessor,
        metadata_writer: MetadataWriter,
        job_repo: JobRepository,
        output_repo: OutputRepository,
        session_repo: EngineSessionRepository,
        outputs_dir: Path,
    ): ...

    def run_single_sync(
        self,
        image: bytes | Path | Image.Image,
        preset_id: str,
        overrides: SliderOverrides | None = None,
        seed: int | None = None,
    ) -> JobId: ...

    def run_batch_sync(
        self,
        inputs: Path | list[Path] | bytes,
        preset_id: str,
        overrides: SliderOverrides | None = None,
        seed_mode: Literal["random", "fixed", "filename_hash"] = "random",
        fixed_seed: int | None = None,
    ) -> JobId: ...

    def get_status(self, job_id: JobId) -> JobStatus: ...

    def cancel(self, job_id: JobId) -> None: ...

    def retry_failed(self, job_id: JobId, *, new_seed: bool = True) -> JobId: ...

    def resume(self, job_id: JobId) -> JobId:
        """Resume a paused batch from its checkpoint."""

    def list_jobs(
        self,
        kind: Literal["single", "batch"] | None = None,
        status: JobStatusValue | None = None,
        preset_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[JobStatus]: ...

    def rebind_engine(self, new_client: RemoteComfyUIClient) -> None:
        """Called when the user reconnects to a new tunnel URL.
        Swaps the ComfyUI client; in-flight jobs see the new client on their next call."""
```

#### `JobStatus`

```python
@dataclass
class JobStatus:
    job_id: JobId
    kind: Literal["single", "batch", "batch_item"]
    status: Literal["queued", "running", "paused", "success", "failed", "cancelled"]
    preset_id: str
    engine_session_id: str | None
    progress: Progress
    paused_at_index: int | None
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    outputs: list[OutputRef]
    children: list[JobStatus]   # for batches

@dataclass
class Progress:
    total: int
    succeeded: int
    failed: int
    in_flight: int
    eta_seconds: float | None
```

---

### `aquarender.core.presets.PresetService`

```python
class PresetService:
    def list(self, include_user: bool = True) -> list[Preset]: ...
    def get(self, preset_id: str) -> Preset: ...
    def create(self, name: str, params: ResolvedParams, description: str = "") -> Preset: ...
    def update(self, preset_id: str, params: ResolvedParams) -> Preset:
        """Raises ImmutableBuiltinError if builtin."""
    def delete(self, preset_id: str) -> None:
        """Raises ImmutableBuiltinError if builtin."""
    def export(self, preset_id: str) -> dict: ...
    def import_(self, data: dict) -> Preset:
        """Imports preset; new id with 'user_' prefix to avoid collision."""
    def merge(self, preset: Preset, overrides: SliderOverrides | None) -> ResolvedParams: ...
```

---

### `aquarender.core.preprocessor.ImagePreprocessor`

```python
class ImagePreprocessor:
    def validate(self, image: bytes | Path | Image.Image) -> Image.Image:
        """Loads, validates, normalizes. Returns RGB PIL.

        Rules:
        - Format: JPG/PNG/WEBP/HEIC.
        - Min: 256px shortest side.
        - Max: 4096px longest side (auto-resize to 2048; warning logged).
        - EXIF orientation auto-applied.
        - Alpha channel dropped.

        Raises: UnsupportedFormatError, ImageTooSmallError.
        """

    def enumerate_dir(self, path: Path) -> list[Path]: ...
    def extract_zip(self, zip_bytes: bytes, dest: Path) -> list[Path]: ...
```

---

### `aquarender.core.presets.SLIDER_TO_PARAMS`

```python
SLIDER_TO_PARAMS: dict = {
    "watercolor_strength": {
        "Light":  {"denoise": 0.35, "lora_weight": 0.6},
        "Medium": {"denoise": 0.50, "lora_weight": 0.8},
        "Strong": {"denoise": 0.65, "lora_weight": 1.0},
    },
    "structure_preservation": {
        "Low":    {"cn_strength": 0.50},
        "Medium": {"cn_strength": 0.75},
        "High":   {"cn_strength": 0.90},
    },
}

@dataclass
class SliderOverrides:
    watercolor_strength: Literal["Light", "Medium", "Strong"] | None = None
    structure_preservation: Literal["Low", "Medium", "High"] | None = None
    output_size: Literal[768, 1024, 1536] | None = None
    custom_lora: str | None = None       # NEW v2: filename of LoRA on remote
```

---

### `aquarender.engine.client.RemoteComfyUIClient`

The only thing in our codebase that knows the engine is remote.

```python
class RemoteComfyUIClient:
    def __init__(
        self,
        base_url: str,
        timeout_s: int = 90,
        secret: str | None = None,           # P1: optional shared-secret header
    ): ...

    async def health(self) -> EngineInfo:
        """GET /system_stats. Also lists checkpoints/loras/controlnets via /object_info.

        Raises: TunnelDownError if unreachable."""

    async def list_loras(self) -> list[str]: ...
    async def list_controlnets(self) -> list[str]: ...
    async def list_checkpoints(self) -> list[str]: ...

    async def upload_image(self, image: Image.Image) -> ImageRef:
        """POST /upload/image. Returns ref usable in workflow JSON."""

    async def queue_prompt(self, workflow: dict) -> str:
        """POST /prompt. Returns prompt_id immediately."""

    async def poll_until_done(
        self, prompt_id: str, *, timeout_s: int = 90, poll_interval_s: float = 1.0
    ) -> ExecutionResult: ...

    async def fetch_output(self, prompt_id: str) -> bytes:
        """GET /view. Returns PNG bytes."""

    async def interrupt(self) -> None:
        """POST /interrupt."""

    async def keepalive_ping(self) -> None:
        """GET / — used by KeepaliveTask, doesn't raise on transient errors."""
```

#### `EngineInfo`

```python
@dataclass
class EngineInfo:
    reachable: bool
    gpu_name: str | None         # 'Tesla P100-PCIE-16GB' etc.
    vram_total_mb: int | None
    vram_free_mb: int | None
    comfyui_version: str | None
    available_checkpoints: list[str]
    available_loras: list[str]
    available_controlnets: list[str]
    inferred_engine_type: Literal["kaggle", "colab", "hf-space", "local", "unknown"]
```

---

### `aquarender.engine.tunnel.TunnelHealthMonitor`

```python
class TunnelHealthMonitor:
    """Background coroutine pinging /system_stats every 30s.
    Emits 'tunnel_down' / 'tunnel_recovered' events to subscribers."""

    def __init__(self, client: RemoteComfyUIClient, interval_s: float = 30.0): ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def subscribe(self, callback: Callable[[TunnelEvent], None]) -> None: ...
```

---

### Errors

All inherit from `AquaRenderError` and carry a stable `code` attribute.

```python
class AquaRenderError(Exception):
    code: str

class PresetNotFoundError(AquaRenderError): code = "preset.not_found"
class ImmutableBuiltinError(AquaRenderError): code = "preset.immutable_builtin"
class InvalidImageError(AquaRenderError): code = "image.invalid"
class UnsupportedFormatError(InvalidImageError): code = "image.unsupported_format"
class ImageTooSmallError(InvalidImageError): code = "image.too_small"
class ImageTooLargeError(InvalidImageError): code = "image.too_large"
class ZipTooLargeError(InvalidImageError): code = "zip.too_large"
class ZipTooManyFilesError(InvalidImageError): code = "zip.too_many_files"

# Engine errors
class EngineNotConnectedError(AquaRenderError): code = "engine.not_connected"
class TunnelDownError(AquaRenderError): code = "engine.tunnel_down"
class EngineError(AquaRenderError): code = "engine.error"            # 4xx/5xx from ComfyUI
class GenerationTimeoutError(AquaRenderError): code = "engine.timeout"
class GenerationFailedError(AquaRenderError): code = "engine.generation_failed"

# Engine resource errors
class CheckpointMissingError(EngineError): code = "engine.checkpoint_missing"
class LoraMissingError(EngineError): code = "engine.lora_missing"
class ControlNetMissingError(EngineError): code = "engine.controlnet_missing"

# Job errors
class JobNotFoundError(AquaRenderError): code = "job.not_found"
class JobCannotResumeError(AquaRenderError): code = "job.cannot_resume"
```

---

## Part 2 — Remote ComfyUI HTTP API (consumed)

We don't own this API — ComfyUI does. We pin the version in the Kaggle notebook and document the endpoints we use. If ComfyUI changes any of these in a breaking way, our `RemoteComfyUIClient` is the single point we need to update.

**Base URL**: whatever Cloudflare Tunnel gave us (e.g. `https://abc-def.trycloudflare.com`).
**Auth**: none in v1. P1: optional `X-AquaRender-Auth: <shared-secret>` header.

### Endpoints we call

#### `GET /system_stats`

Health + GPU info.

**Response (200):**
```json
{
  "system": {
    "os": "linux",
    "python_version": "3.10.13",
    "embedded_python": false,
    "comfyui_version": "0.3.10"
  },
  "devices": [{
    "name": "cuda:0 NVIDIA Tesla P100-PCIE-16GB",
    "type": "cuda",
    "index": 0,
    "vram_total": 17179869184,
    "vram_free": 14000000000,
    "torch_vram_total": 17179869184,
    "torch_vram_free": 14000000000
  }]
}
```

We parse `devices[0].name` for `gpu_name`, compute `vram_total_mb = vram_total / 1024 / 1024`, etc.

---

#### `GET /object_info`

Returns the full schema of all ComfyUI nodes. We use it to enumerate available LoRAs and ControlNets.

**Response (200):** large JSON. We extract:
- `LoraLoader.input.required.lora_name[0]` → list of LoRA filenames
- `ControlNetLoader.input.required.control_net_name[0]` → list of ControlNet filenames
- `CheckpointLoaderSimple.input.required.ckpt_name[0]` → list of checkpoints

```python
async def list_loras(self) -> list[str]:
    info = await self._http.get(f"{self.base_url}/object_info")
    return info.json()["LoraLoader"]["input"]["required"]["lora_name"][0]
```

---

#### `POST /upload/image`

Upload an image so it can be referenced by `LoadImage` nodes.

**Request:** `multipart/form-data` with `image` field (file), optional `subfolder` and `type` (default "input").

**Response (200):**
```json
{ "name": "uploaded_abc123.png", "subfolder": "", "type": "input" }
```

We use `name` as the value for `LoadImage.image` in workflows.

---

#### `POST /prompt`

Submit a workflow for execution. Returns immediately; execution is async.

**Request:**
```json
{
  "prompt": { /* full workflow JSON */ },
  "client_id": "aquarender-<uuid>"
}
```

**Response (200):**
```json
{
  "prompt_id": "f9c1c3f4-1234-5678-9abc-def012345678",
  "number": 4,
  "node_errors": {}
}
```

If `node_errors` is non-empty, we raise `EngineError` with the error map.

**Response (4xx/5xx):**
```json
{ "error": { "type": "...", "message": "..." } }
```

We map specific errors:
- "model not found" + LoRA → `LoraMissingError`
- "model not found" + checkpoint → `CheckpointMissingError`
- "model not found" + ControlNet → `ControlNetMissingError`
- generic → `EngineError`

---

#### `GET /history/{prompt_id}`

Poll execution state.

**Response (200) when in progress:**
```json
{}
```

**Response (200) when done:**
```json
{
  "f9c1c3f4-...": {
    "prompt": [...],
    "outputs": {
      "9": {
        "images": [
          { "filename": "ComfyUI_00042_.png", "subfolder": "", "type": "output" }
        ]
      }
    },
    "status": {
      "status_str": "success",
      "completed": true,
      "messages": [...]
    }
  }
}
```

We poll at 1Hz. Done = `status.completed == true`. We extract `outputs.{node_id}.images[0]` for `fetch_output`. (Node id `9` here is just whatever the SaveImage node id is in our template — we hardcode the expected id.)

---

#### `GET /view?filename=...&subfolder=...&type=output`

Download a generated image.

**Response (200):** `image/png` (or webp/jpeg per workflow). Body = bytes.

---

#### `POST /interrupt`

Cancel currently-executing prompt.

**Request:** empty body.
**Response (200):** empty body.

---

### Endpoints we don't use (deliberately)

- `WS /ws` — ComfyUI's WebSocket for real-time progress. We poll instead because (a) WebSockets through Cloudflare Tunnel have edge cases, (b) HTTP polling is sufficient at 1s and fits cleanly with the rest of our async code.
- `GET /queue` — current queue. We don't need it; `/history/{id}` tells us our specific prompt's state.
- `POST /free` — model unload. We don't manage memory on the remote; that's the user's session.

---

## Part 3 — Future External HTTP API (P2, sketch only)

If we ever wrap AquaRender in FastAPI for programmatic use, the surface looks like:

```
GET    /v1/health
GET    /v1/engine/info               # passthrough to remote
POST   /v1/engine/connect            # body: { tunnel_url, secret? }
POST   /v1/engine/disconnect

GET    /v1/presets
GET    /v1/presets/{id}
POST   /v1/presets
PUT    /v1/presets/{id}
DELETE /v1/presets/{id}

POST   /v1/jobs/single                    # multipart: image + preset_id + overrides
POST   /v1/jobs/batch                     # multipart: zip + preset_id + ...
GET    /v1/jobs/{id}
GET    /v1/jobs/{id}/children
POST   /v1/jobs/{id}/cancel
POST   /v1/jobs/{id}/retry
POST   /v1/jobs/{id}/resume               # NEW v2: resume paused batch
GET    /v1/jobs/{id}/zip

GET    /v1/outputs/{id}/image
GET    /v1/outputs/{id}/metadata
```

Error format:

```json
{ "error": { "code": "engine.tunnel_down", "message": "...", "details": {} } }
```

Code → HTTP status mapping uses the same `code` attribute from internal errors, so the HTTP layer is a translator, not a logic layer.

**Not in v1.**

---

## Versioning

- Internal Python API follows semver of the AquaRender package.
- ComfyUI HTTP API is pinned via the Kaggle notebook's `git checkout` of a specific commit.
- If ComfyUI introduces a breaking change, we update the pin and `RemoteComfyUIClient` together; everything else is unaffected.

---

## Cross-Document Mapping

| Concept | DB | Internal Python | Remote HTTP |
|---------|----|-----------------|-------------|
| Preset | `presets` | `PresetService` | n/a (lives only locally) |
| Job | `jobs` | `JobOrchestrator` | n/a |
| Engine session | `engine_sessions` | `RemoteComfyUIClient` + `TunnelHealthMonitor` | `GET /system_stats` |
| LoRA available | n/a | `RemoteComfyUIClient.list_loras()` | `GET /object_info` |
| Image upload | n/a | `RemoteComfyUIClient.upload_image()` | `POST /upload/image` |
| Generation | `outputs` | `JobOrchestrator._execute_one()` | `POST /prompt` + `GET /history` + `GET /view` |
| Cancel | n/a | `JobOrchestrator.cancel()` | `POST /interrupt` |

---

## Related Documents

- [`PRD.md`](./PRD.md) — features driving these surfaces
- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — how `core` + `engine` + `db` fit together
- [`DATABASE.md`](./DATABASE.md) — entities mapped to API resources
- [`CLAUDE.md`](./CLAUDE.md) — coding conventions
