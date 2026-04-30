# AquaRender — System Architecture

**Version**: 2.0
**Date**: 2026-04-30
**Architect**: Ali Naserifar

---

## Overview

The architectural commitment that drives everything: **the heavy stuff runs somewhere else for free**. The user's laptop holds a Streamlit app, an SQLite file, and the output PNGs. Models, GPU, and ComfyUI live on Kaggle (or Colab or a HuggingFace Space, identically interchangeable). A Cloudflare Tunnel exposes the remote ComfyUI to the local app over HTTPS.

This is the *only* way to deliver:
- Free tier that's actually usable for real workloads (Kaggle gives 30 GPU-hours/week)
- No GPU requirement on the user's laptop
- Full SDXL + LoRA + ControlNet stack with no proprietary censorship
- No 12GB model download to the user's disk

### Architectural Principles

1. **Local app is thin.** Nothing on the laptop should require a GPU, more than 200MB of disk, or more than ~500MB of RAM. The laptop is a remote control.
2. **Engine is fungible.** ComfyUI on Kaggle is the default, but the same `RemoteComfyUIClient` works against ComfyUI on Colab, on a HuggingFace Space, or on a local install. The transport is HTTPS to a `/prompt` endpoint; we don't care where it terminates.
3. **The tunnel is a first-class citizen.** Tunnel drops are not exceptional — they're a normal Tuesday. Every code path that talks to the remote assumes the tunnel can vanish at any moment, and recovery is built in, not bolted on.
4. **Stateful storage is local; stateless compute is remote.** SQLite, output files, and metadata stay on the user's machine. The Kaggle session is ephemeral by design — when it dies, nothing important dies with it.
5. **Reproducibility within a session, not across sessions.** Same seed + same params + same LoRA file produces the same output bit-for-bit *within a single Kaggle session*. Across sessions, GPU class differences (T4 vs P100) cause minor drift; we document this, don't fight it.
6. **No filtering anywhere in our code.** We pass prompts and images to the user's own engine. If a community LoRA generates something edgy, that's between the user and their LoRA. Our app is a transport, not a moderator.

---

## High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                       USER'S LAPTOP (no GPU needed)                   │
│                                                                       │
│  ┌─────────────────┐         ┌──────────────────────────────────┐   │
│  │ Streamlit UI    │  HTTP   │      AquaRender Core (Python)     │   │
│  │ localhost:8501  │────────▶│  - PresetService                  │   │
│  │                 │         │  - JobOrchestrator                │   │
│  │  - Connect tab  │◀────────│  - ImagePreprocessor              │   │
│  │  - Single tab   │ (state) │  - MetadataWriter                 │   │
│  │  - Batch tab    │         │  - RemoteComfyUIClient            │   │
│  │  - Presets tab  │         │  - TunnelHealthMonitor            │   │
│  └─────────────────┘         └────────────────┬─────────────────┘   │
│                                               │                      │
│  ┌──────────────┐    ┌──────────────┐         │                      │
│  │ ./outputs/   │    │ aquarender.db│         │                      │
│  │ PNG + JSON   │    │ jobs/outputs │         │                      │
│  │ (~MB-GB)     │    │ presets      │         │                      │
│  └──────────────┘    └──────────────┘         │                      │
│                                               │                      │
└───────────────────────────────────────────────┼──────────────────────┘
                                                │
                            HTTPS over Cloudflare Tunnel
                          (https://abc-def.trycloudflare.com)
                                                │
┌───────────────────────────────────────────────┼──────────────────────┐
│            FREE GPU ENGINE (Kaggle / Colab / HF Space)                │
│                                                ▼                      │
│  ┌──────────────┐    ┌──────────────────────────────────────────┐   │
│  │  cloudflared │───▶│  ComfyUI (127.0.0.1:8188)                 │   │
│  │  (tunnel)    │    │   POST /prompt   GET /history   GET /view │   │
│  └──────────────┘    └──────────────────┬───────────────────────┘   │
│                                          │                           │
│                              ┌───────────▼──────────────┐            │
│                              │  Models on Kaggle disk   │            │
│                              │  (~70GB free, persistent │            │
│                              │   per dataset, ephemeral │            │
│                              │   per session for /tmp)  │            │
│                              │                          │            │
│                              │  - SDXL Base 1.0 (~7GB)  │            │
│                              │  - watercolor LoRA(s)    │            │
│                              │    (~150MB each)         │            │
│                              │  - ControlNet Lineart    │            │
│                              │    (~5GB)                │            │
│                              │  - ControlNet Canny      │            │
│                              └────────────┬─────────────┘            │
│                                           ▼                          │
│                              ┌──────────────────────────┐            │
│                              │  P100 / T4 GPU (free)    │            │
│                              └──────────────────────────┘            │
│                                                                      │
│  Free tier: P100/T4, 30 GPU-hrs/week, 9hr session max,               │
│  5min idle timeout (we ping every 4min from local app to keep alive) │
└──────────────────────────────────────────────────────────────────────┘
```

### Why this works for "free tier only"

| Resource | Free quota | Our usage |
|----------|-----------|-----------|
| Kaggle GPU hours | 30/week (P100 or T4) | ~10s/image → 10,800 images/week ceiling |
| Kaggle disk (workspace) | ~70GB | ~15GB used by models |
| Kaggle session length | 9 hours | Most batches are minutes |
| Cloudflare Tunnel | Unlimited bandwidth, no signup | We use trycloudflare.com (anonymous) |
| Local laptop | n/a | ≤ 200MB install, ≤ 500MB RAM |

**No path in this architecture costs money.** None.

---

## Data Flow

### Single image — happy path

```
1. User uploads image, picks preset, clicks Generate
2. UI calls JobOrchestrator.run_single_sync(bytes, preset_id, overrides)
3. ImagePreprocessor: validate, resize, EXIF-orient → PIL.Image
4. PresetService: get(preset_id) + merge(overrides) → ResolvedParams
5. JobRepo: INSERT job (status=running)
6. RemoteComfyUIClient.upload_image(pil) → POST /upload/image → {name, subfolder}
7. WorkflowBuilder.build(image_ref, params, seed) → ComfyUI workflow JSON
8. RemoteComfyUIClient.queue_prompt(workflow) → POST /prompt → prompt_id
9. RemoteComfyUIClient.poll_until_done(prompt_id) → GET /history/{id} (every 1s)
10. RemoteComfyUIClient.fetch_output(prompt_id) → GET /view → bytes
11. MetadataWriter.write(image_in, image_out, params, seed) → ./outputs/.../*.png + .json
12. JobRepo: UPDATE job (status=success); INSERT output
13. UI polls get_status(job_id), renders before/after
```

### Batch — happy path

```
For N images:
  1. Orchestrator iterates input list
  2. Each image: same as single, but creates child job linked to parent
  3. After each image: write checkpoint to ./outputs/.checkpoint.{batch_id}.json
  4. On image failure: log, mark child failed, continue
  5. Every 4 minutes during batch: send keepalive ping to Kaggle
       (touches a no-op endpoint to prevent idle timeout)

After loop:
  - Generate batch_report.html (grid of before/after thumbnails)
  - Mark parent job success/failed/partial
  - Optionally zip ./outputs/{batch_id}/
```

### Tunnel drop — recovery flow

```
1. RemoteComfyUIClient.poll_until_done() raises TunnelDownError
   (httpx ConnectError, or 502/503 from Cloudflare, or DNS fail)
2. JobOrchestrator catches, marks current image as 'paused' (NEW status — not 'failed')
3. Orchestrator emits "tunnel_down" event to UI via shared state
4. UI shows: "Connection to engine lost. Restart your Kaggle notebook and paste the new URL."
5. User restarts Kaggle notebook → new tunnel URL
6. User pastes URL → Connect → health check passes
7. Orchestrator detects engine reconnected, prompts user: "Resume batch from image 12 of 47?"
8. User clicks Resume → batch continues from next unprocessed (paused → running again)
9. Already-completed outputs are not regenerated (checkpoint authoritative)
```

---

## Component Architecture

### Repository layout

```
aquarender/
├── README.md                  # 30-second pitch + "Open in Kaggle" badge
├── pyproject.toml
├── notebooks/
│   ├── aquarender_kaggle.ipynb  # PRIMARY ENGINE
│   ├── aquarender_colab.ipynb   # SECONDARY
│   └── README.md                # How to use them
├── docs/
│   ├── PRD.md
│   ├── ARCHITECTURE.md
│   ├── API.md
│   ├── DATABASE.md
│   ├── CLAUDE.md
│   └── PROMPT.md
├── aquarender/
│   ├── __init__.py
│   ├── cli.py                 # `aquarender start|doctor|migrate`
│   ├── ui/                    # Streamlit
│   │   ├── app.py
│   │   ├── pages/
│   │   │   ├── connect.py     # NEW: paste tunnel URL, verify, store
│   │   │   ├── single.py
│   │   │   ├── batch.py
│   │   │   └── presets.py
│   │   └── components/
│   ├── core/                  # Pure Python, no UI/HTTP/DB-direct
│   │   ├── orchestrator.py
│   │   ├── preprocessor.py
│   │   ├── metadata.py
│   │   └── presets.py
│   ├── engine/                # Remote ComfyUI integration
│   │   ├── client.py          # RemoteComfyUIClient (httpx)
│   │   ├── workflows.py       # WorkflowBuilder
│   │   ├── tunnel.py          # TunnelHealthMonitor + reconnect logic
│   │   └── keepalive.py       # KeepaliveTask (4min ping during batches)
│   ├── db/
│   │   ├── models.py
│   │   ├── repo.py
│   │   └── migrations/
│   └── presets/               # JSON files, version-controlled
│       ├── soft_watercolor.json
│       ├── ink_watercolor.json
│       ├── childrens_book.json
│       └── product_watercolor.json
├── workflows/                 # ComfyUI workflow JSON template
│   └── img2img_controlnet_lora.json
├── tests/
└── scripts/
    └── benchmark.py
```

### Component responsibilities

#### `notebooks/aquarender_kaggle.ipynb` — **the engine deliverable**

This is as much a product surface as the Streamlit app. It must:

1. Detect available GPU; fail loudly if Kaggle didn't give us one (toggle GPU in notebook settings).
2. Install ComfyUI to `/kaggle/working/ComfyUI` (pinned commit).
3. Download models with `wget` to ComfyUI's expected paths:
   - `models/checkpoints/sd_xl_base_1.0.safetensors`
   - `models/loras/watercolor_style_lora_sdxl.safetensors`
   - `models/controlnet/diffusers_xl_lineart_full.safetensors`
   - `models/controlnet/diffusers_xl_canny_full.safetensors`
4. Mount any user-provided LoRA datasets from `/kaggle/input/` into ComfyUI's `loras/` folder via symlinks.
5. Install `cloudflared` binary, launch ComfyUI on `:8188`, launch tunnel.
6. Print the tunnel URL prominently with copy-paste hint:
   ```
   ✅ AquaRender engine ready
   ─────────────────────────────────────
   Engine URL:  https://abc-def.trycloudflare.com
   Copy this URL and paste it into AquaRender's Connect tab.
   ─────────────────────────────────────
   ⚠️  This URL changes every time you restart the notebook.
   ```
7. Keep the notebook cell running (so the session stays alive while ComfyUI runs).

The notebook is shipped, version-controlled, and treated as production code. Breaking the notebook breaks the product.

#### `engine/client.py` — `RemoteComfyUIClient`

Wraps the ComfyUI HTTP API. Identical interface whether the remote is Kaggle, Colab, HF Space, or a local install.

```python
class RemoteComfyUIClient:
    def __init__(self, base_url: str, timeout_s: int = 90, secret: str | None = None): ...

    async def health(self) -> EngineInfo:
        """GET /system_stats — also checks model list, returns GPU name + loaded models."""

    async def list_loras(self) -> list[str]:
        """GET /object_info → extract LoraLoader's combo of LoRA names."""

    async def list_controlnets(self) -> list[str]:
        """Same idea for ControlNet."""

    async def upload_image(self, image: Image) -> ImageRef:
        """POST /upload/image → {name, subfolder, type}."""

    async def queue_prompt(self, workflow: dict) -> str:
        """POST /prompt → prompt_id. Returns immediately."""

    async def poll_until_done(self, prompt_id: str, timeout_s: int = 90) -> ExecutionResult:
        """GET /history/{prompt_id} every 1s until terminal. Raises GenerationTimeoutError or TunnelDownError."""

    async def fetch_output(self, prompt_id: str) -> bytes:
        """GET /view?filename=...&subfolder=...&type=output → PNG bytes."""

    async def interrupt(self) -> None:
        """POST /interrupt — used on cancel."""
```

All HTTP errors classified into:
- `TunnelDownError` — connection refused, DNS fail, Cloudflare 502/503/504
- `EngineError` — ComfyUI returned 4xx/5xx with a body
- `GenerationTimeoutError` — exceeded wall-clock budget

Different error types drive different recovery: `TunnelDownError` → pause batch and prompt reconnect; `EngineError` → mark image failed and continue; `GenerationTimeoutError` → mark image failed.

#### `engine/tunnel.py` — `TunnelHealthMonitor`

A background coroutine that pings `GET /system_stats` every 30s. On failure:
- 1st miss: silent retry in 5s
- 2nd miss: log warning
- 3rd miss: emit `tunnel_down` event to orchestrator and UI

Why background-monitored, not on-demand: a batch sitting between images for ~5s shouldn't only discover the tunnel is dead when it tries the next image. We want the UI to show "disconnected" within ~30s of actual disconnect.

#### `engine/keepalive.py` — `KeepaliveTask`

During batches, ping `GET /` every 4 minutes to prevent Kaggle idle timeout (5 minutes). Stops when batch ends. This is annoying-but-necessary infrastructure; without it, a 50-image batch with a few slow images can hit the Kaggle idle threshold during preprocessing pauses.

#### `engine/workflows.py` — `WorkflowBuilder`

Loads `workflows/img2img_controlnet_lora.json` (a complete ComfyUI graph), substitutes node inputs:
- `LoadImage` → uploaded image ref
- `CheckpointLoaderSimple.ckpt_name` → `sd_xl_base_1.0.safetensors`
- `LoraLoader.lora_name` and `.strength_model` → from `params.lora`
- `ControlNetLoader.control_net_name` → from `params.controlnet.model`
- `ControlNetApplyAdvanced.strength` → from `params.controlnet.strength`
- `KSampler.seed`, `.steps`, `.cfg`, `.denoise`, `.sampler_name`, `.scheduler` → from `params.sampler`
- `CLIPTextEncode` (positive/negative) → from `params.prompt`

One template, parameterized. Same rule as v1.

#### `core/orchestrator.py` — `JobOrchestrator`

Public methods identical to v1 (`run_single`, `run_batch`, `get_status`, `cancel`, `retry_failed`). Two new responsibilities specific to remote engine:

1. **Engine binding**: orchestrator is constructed with a `RemoteComfyUIClient` instance whose `base_url` was set when the user pasted the tunnel URL. If the URL changes (reconnect), the client is replaced; in-flight jobs see the swap.
2. **Pause/resume on tunnel drop**: new job status `paused` (status enum extended); orchestrator transitions running → paused on `TunnelDownError`, paused → running on user-confirmed reconnect + resume.

#### `core/preprocessor.py`, `core/metadata.py`, `core/presets.py`

Unchanged from v1. They're pure Python, don't care where generation happens.

#### `db/`

Unchanged shape; one column added to `jobs` and `outputs` to record which engine session produced them. See `DATABASE.md`.

#### `ui/pages/connect.py` — new top-level page

```
┌─────────────────────────────────────────────────────────┐
│  Connect to engine                                      │
│                                                         │
│  Engine URL: [https://abc-def.trycloudflare.com    ]   │
│              [Connect]                                  │
│                                                         │
│  Status: ✅ Connected                                   │
│    GPU: NVIDIA Tesla P100-PCIE-16GB                    │
│    SDXL: sd_xl_base_1.0.safetensors                    │
│    LoRAs available: watercolor_style_lora_sdxl,        │
│                     my_custom_watercolor                │
│    ControlNets: lineart, canny                         │
│                                                         │
│  Free GPU minutes used this session: 12 / 540          │
└─────────────────────────────────────────────────────────┘

⚠️  No engine connected. [Open Kaggle notebook ↗]   ← when disconnected
```

This page is the gatekeeper. Other tabs (Single/Batch) refuse to render if no engine is connected.

---

## Tech Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| **Local UI** | Streamlit 1.32+ | Keeps app installable as `pipx install aquarender`; no Electron, no Node toolchain. |
| **Local backend** | Python 3.11 | Universal, async via asyncio. |
| **Local DB** | SQLite + SQLAlchemy 2.0 + Alembic | Zero setup. |
| **HTTP client** | httpx | Async-native, retries, timeouts. |
| **Validation** | Pydantic 2.x | Strict at all boundaries. |
| **Remote engine** | ComfyUI (pinned commit) on Kaggle | 30 GPU-hrs/week free, P100/T4, 70GB disk. |
| **Diffusion model** | SDXL Base 1.0 | Open license, mature ecosystem. |
| **Default LoRA** | `ostris/watercolor_style_lora_sdxl` | Public, SDXL, tested. User can swap. |
| **ControlNet** | Lineart-Realistic SDXL primary, Canny SDXL fallback | Standard. |
| **Tunnel** | Cloudflare Tunnel (`cloudflared`, anonymous trycloudflare.com) | Free, no signup, stable. |
| **Tunnel alternates** | ngrok (signup), bore (self-host) | Documented for users where Cloudflare is blocked. |
| **Logging** | structlog | JSON-able, key=value context. |
| **Tests** | pytest + pytest-asyncio | Standard. |
| **Lint/types** | ruff + mypy strict | Standard. |
| **Packaging** | uv (preferred), pip | uv for speed; pip-compatible. |
| **Distribution** | pipx / `uv tool install` | One command, no virtualenv work for the user. |

### Why not these alternatives?

- **Why not host a public AquaRender HuggingFace Space as the default?** Free public Spaces invite abuse and put us in the moderation business — exactly what we're avoiding. Users running their own Kaggle session put the GPU on their account. F-17 (HF Space alternative) is documented for users who prefer it, but it's their fork, not ours.
- **Why not Modal / RunPod / Lightning Studios free credits?** They expire. The user wakes up one day with no compute. Kaggle's 30hrs/week is *renewable*.
- **Why not just Pollinations.ai?** It works but offers no fine-grained control over LoRA weight, ControlNet strength, denoise. The whole product *is* that control.
- **Why not Gemini/OpenAI image edit?** See the PRD. The product is the LoRA stack, not a generic image-edit wrapper.

---

## Key Design Decisions

### Decision 1 — Engine fungibility through one HTTP interface
Whether the engine runs on Kaggle, Colab, HF Space, or a local box, AquaRender talks to it through the same `/prompt`, `/history`, `/view`, `/upload/image` endpoints. We never code a Kaggle-specific path. **Result:** users in regions where Kaggle is slow can use Colab; power users can run local; we don't have to build separate code for each.

### Decision 2 — Tunnel drops are normal, not exceptional
Status enum has `paused` between `running` and `success/failed`. UI has a permanent "Engine status: ✅/⚠️/❌" indicator. Reconnect flow is a primary user flow, not an error path. **Result:** 9-hour Kaggle limits don't kill the product.

### Decision 3 — Models live on Kaggle, never on the laptop
Local install is ≤ 200MB. The only thing the user downloads is the AquaRender Python package and the notebook file. **Result:** Etsy seller on a MacBook Air is a real user, not a stretch persona.

### Decision 4 — Cloudflare Tunnel as default, no signup required
Anonymous `trycloudflare.com` URLs work without an account. The notebook prints the URL and dies if Cloudflare doesn't respond. **Result:** zero-account-creation cost beyond Kaggle itself.

### Decision 5 — Built-in keepalive is a feature, not a hack
KeepaliveTask is a real component with tests. We do not pretend Kaggle's idle timeout doesn't exist. **Result:** long batches actually finish.

### Decision 6 — One workflow template, presets are values
Same rule as v1: `workflows/img2img_controlnet_lora.json` is the only graph. Presets are JSON values. New topology = new template (rare). **Result:** debugging is centralized.

### Decision 7 — Reproducibility is per-session, not cross-session
Same Kaggle session + same seed + same params = identical output. Different session = drift (different GPU model possibly). We document this; we don't promise more than we can deliver.

### Decision 8 — No content moderation in our code path
We pass user prompts and user images to the user's own engine. Period. **Result:** users can use any LoRA they want for any subject they want, on their own GPU, without us in the way.

---

## Failure Modes & Recovery

| Failure | Detection | Recovery |
|---------|-----------|----------|
| Cloudflare tunnel drops mid-batch | TunnelHealthMonitor 3 missed pings | Pause batch, prompt for new URL, resume from checkpoint |
| Kaggle session times out (9hr) | Same as above | Same |
| Kaggle session idles out (5min) | Same as above | KeepaliveTask should prevent during batches; same recovery if it leaks through |
| User pastes wrong URL | `RemoteComfyUIClient.health()` returns error or non-ComfyUI response | Show "URL doesn't look like a ComfyUI engine" error, don't connect |
| ComfyUI crashes on remote | `/history` returns error or never reaches success | Mark image failed, continue batch (other images may succeed) |
| Single image OOMs on T4 | ComfyUI history shows error | Mark failed, suggest "try lower resolution preset" |
| Single image times out (90s) | poll exceeds budget | `interrupt()` ComfyUI, mark failed, continue |
| User Ctrl+C local app mid-batch | KeyboardInterrupt | Checkpoint already on disk; UI shows "resume" on next launch |
| Disk full locally | OSError on PNG write | Mark failed, halt batch, surface error |
| Required model missing on remote | Initial `health()` lists models; we check the preset's required LoRA + CN are present | Refuse to start, show "this preset requires LoRA X — re-run notebook to download" |

### `aquarender doctor`

```
$ aquarender doctor
✅ Python 3.11.6
✅ SQLite ./aquarender.db (writable, 12 jobs)
✅ Outputs dir ./outputs/ (writable, 4.2GB free)
✅ Engine connected: https://abc-def.trycloudflare.com
   GPU: Tesla P100 (16GB)
   ComfyUI: 0.3.10
   SDXL: present
   LoRAs: watercolor_style_lora_sdxl, my_custom_lora
   ControlNets: lineart, canny
   Used GPU minutes this session: 14 / 540

All systems go.
```

---

## Performance Targets

| Metric | Target on P100 | Target on T4 |
|--------|---------------|--------------|
| Cold first generation (after notebook restart) | ≤ 60s | ≤ 90s |
| Warm 1024px generation | ≤ 20s | ≤ 35s |
| 50-image batch wall time | ≤ 18 min | ≤ 30 min |
| Network RTT (laptop → Kaggle via Cloudflare) | ≤ 200ms | same |
| Image upload (1024px PNG, ~1.5MB) | ≤ 1s | same |
| Output download (1024px PNG, ~1.8MB) | ≤ 1s | same |
| UI interaction (non-generation) | ≤ 200ms | n/a |

---

## Security Considerations

### Threat model: small but real

The default Cloudflare tunnel URL is **public** while it's alive. Anyone who has the URL can hit your ComfyUI and use your free Kaggle GPU. Threats:

| Threat | Severity | Mitigation |
|--------|----------|------------|
| URL leaks (screenshot, paste in Discord) | Medium | Tunnel URLs change every session. Don't paste them anywhere. P1: shared-secret token in `X-AquaRender-Auth` header. |
| URL guessed | Low | Cloudflare URLs are random subdomains; effectively impossible to brute-force. |
| Remote ComfyUI run by malicious user | n/a | The remote is *the user's own Kaggle session*. They are the principal. |
| Kaggle session compromised via the tunnel | Low | ComfyUI exposes only its own API; the rest of Kaggle isn't reachable through it. |

### Local-side hygiene

- User-supplied paths validated (no traversal).
- Zip uploads bounded (1GB uncompressed, 1000 files).
- PIL `MAX_IMAGE_PIXELS` enforced.
- No `eval()`/`exec()`/`pickle.loads()` on user data.

### What we explicitly don't do

- We don't filter prompts.
- We don't filter output images.
- We don't telemeter usage.
- We don't phone home.

---

## Future Architecture (out of v1 scope)

### v2 — Optional self-hosted persistent engine

For users who outgrow 30 GPU-hours/week and want to spin up their own GPU on RunPod/Vast.ai/Modal *with their own money*, the same `RemoteComfyUIClient` works against any ComfyUI HTTP endpoint. We document the recipe; we don't host it.

### v2 — Custom LoRA training

Notebook variant that trains a watercolor LoRA on user-supplied references using Kohya-ss on Kaggle GPU. Same free GPU; just a different notebook. No app changes required beyond pointing at the new LoRA filename.

### v2 — Public registry of community LoRAs

Read-only browser inside the Connect tab listing community watercolor/style LoRAs from Civitai/HuggingFace, with copy-paste `wget` commands for the user's notebook. We don't host LoRAs; we link to them.

---

## Related Documents

- [`PRD.md`](./PRD.md) — what we're building and why
- [`API.md`](./API.md) — internal Python API + remote ComfyUI surface used
- [`DATABASE.md`](./DATABASE.md) — SQLite schema
- [`CLAUDE.md`](./CLAUDE.md) — conventions and commands
- [`PROMPT.md`](./PROMPT.md) — agentic-coding kickoff
