# AquaRender — Claude Development Guide

Auto-loaded every session. Keep tight. Update in the same PR as any change it covers.

---

## Project at a Glance

**AquaRender** is a free-tier-only watercolor batch image transformer. The local app is a thin Streamlit UI + Python core + SQLite. The actual generation runs on a free Kaggle GPU notebook running ComfyUI, exposed to the local app via a Cloudflare Tunnel. The user's laptop never holds models, never needs a GPU, and never pays a cent.

**Why this exists:** every paid SaaS censors output and locks you out of swapping LoRAs. Generic image-edit APIs (Gemini, OpenAI, Firefly) aren't the SDXL+LoRA stack. Local installs need a 12GB GPU. We solve all three by putting open-source ComfyUI on free Kaggle compute.

**Read these in order before coding:**
1. `docs/PRD.md`
2. `docs/ARCHITECTURE.md`
3. `docs/DATABASE.md`
4. `docs/API.md`
5. This file
6. `docs/PROMPT.md`

---

## Quick Commands

```bash
# Install
uv sync
uv pip install -e ".[dev]"

# Run the local app
uv run aquarender start              # Streamlit on :8501
uv run aquarender doctor             # Verify env, DB, engine connection

# Database
uv run aquarender migrate
uv run alembic revision -m "..." --autogenerate
uv run alembic downgrade -1          # dev only

# Tests
uv run pytest tests/unit              # No Kaggle needed (uses FakeRemoteClient)
uv run pytest tests/integration       # Mocked engine, real DB
uv run pytest tests/e2e               # NEEDS A LIVE KAGGLE TUNNEL (manual / nightly)
uv run pytest -k "preset"
uv run pytest --cov=aquarender

# Lint / format / types
uv run ruff check --fix .
uv run ruff format .
uv run mypy aquarender                # strict

# Distribution
uv build                              # wheel + sdist
pipx install dist/aquarender-*.whl    # local install test
```

---

## Tech Stack

| Layer | Choice |
|-------|--------|
| Local UI | Streamlit 1.32+ |
| Local Python | 3.11 (3.10/3.12 also supported) |
| Local DB | SQLite + SQLAlchemy 2.0 + Alembic |
| HTTP client | httpx (async) |
| Validation | Pydantic 2.x |
| Logging | structlog |
| Tests | pytest, pytest-asyncio, pytest-cov |
| Lint/types | ruff + mypy strict |
| Packaging | uv preferred, pip-compatible, pipx-distributable |
| **Remote engine** | ComfyUI (pinned commit) on Kaggle |
| **Tunnel** | Cloudflare Tunnel (`cloudflared`) — anonymous trycloudflare.com |
| **Diffusion model** | SDXL Base 1.0 |
| **Default LoRA** | `ostris/watercolor_style_lora_sdxl` |
| **ControlNet** | Lineart-Realistic SDXL primary, Canny SDXL fallback |

**Notebooks shipped:**
- `notebooks/aquarender_kaggle.ipynb` — primary
- `notebooks/aquarender_colab.ipynb` — secondary

---

## Repository Layout

```
aquarender/
├── notebooks/        # KAGGLE NOTEBOOK IS A FIRST-CLASS DELIVERABLE
├── ui/               # Streamlit ONLY. Imports from core/. Never engine/ or db/.
├── core/             # Pure Python. No httpx, no Streamlit, no SQLAlchemy outside repo.
├── engine/           # Remote ComfyUI integration: client, tunnel monitor, keepalive.
│   ├── client.py
│   ├── workflows.py
│   ├── tunnel.py
│   └── keepalive.py
├── db/               # SQLAlchemy + Alembic. Repository pattern.
├── presets/          # JSON files in Git.
└── cli.py
workflows/            # ComfyUI workflow JSON template
tests/
```

### Layering (enforced by `import-linter`)

```
ui  →  core  →  db (via repo)
              →  engine
```

**Forbidden:**
- `ui` → `engine`, `db`, anything HTTP-y
- `core` → `streamlit`, `httpx` (only `engine` may use httpx)
- `engine` → `core`, `db`, `streamlit`
- Anything outside `db/` importing SQLAlchemy directly

---

## Code Conventions

### Naming
- Modules: `snake_case.py`
- Classes / Pydantic models / SQLAlchemy models: `PascalCase`
- Functions / variables: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Type aliases: `PascalCase` (`type JobId = str`)

### Type hints

**Strict mypy. Every signature annotated. No `Any` except at HTTP/JSON boundaries.**

```python
# Good
def run_single(image: bytes | Path | Image, preset_id: str) -> JobId: ...

# Bad — missing types
def run_single(image, preset_id): ...
```

`from __future__ import annotations` at the top of every module.

### Imports

```python
# 1. stdlib
from __future__ import annotations
import asyncio
from pathlib import Path

# 2. third-party
import httpx
from pydantic import BaseModel
from PIL import Image

# 3. first-party (absolute)
from aquarender.core.presets import PresetService
from aquarender.db.repo import JobRepository

# 4. relative (only intra-package)
from .errors import AquaRenderError
```

### Errors

Every domain error inherits `AquaRenderError` and has a stable `code`:

```python
class TunnelDownError(AquaRenderError):
    code = "engine.tunnel_down"
    def __init__(self, base_url: str, reason: str) -> None:
        super().__init__(f"Engine at {base_url} unreachable: {reason}")
        self.base_url = base_url
        self.reason = reason
```

**Never raise bare `Exception`/`ValueError` from `core/` or `engine/`.** Always typed.

### Pydantic at boundaries, dataclass internally

- `core/` business logic → `@dataclass(slots=True)` is fine.
- Anything that loads JSON (presets, metadata sidecars, ComfyUI responses) → Pydantic `BaseModel` with strict validation.

### Async vs sync

- `engine/` is async (httpx + polling).
- `core/orchestrator.py` is async at its public boundary; provides `_sync` wrappers (`run_single_sync`, `run_batch_sync`) that wrap with `asyncio.run` for Streamlit.
- `db/` is sync (SQLAlchemy sync engine).
- Streamlit is sync; only ever calls the `_sync` wrappers.

### Logging

```python
import structlog
log = structlog.get_logger(__name__)

log.info("job.started", job_id=job_id, preset_id=preset_id, kind="batch", n=47)
log.warning("tunnel.degraded", base_url=url, missed_pings=2)
log.error("engine.timeout", job_id=job_id, elapsed_s=92.1)
```

JSON renderer in production, console renderer in dev. **Always pass `key=value` context.** Never f-string into the message.

---

## Component Patterns

### Pydantic config model

```python
class SamplerParams(BaseModel):
    name: str
    scheduler: str
    steps: int = Field(ge=1, le=150)
    cfg: float = Field(ge=1.0, le=30.0)
    denoise: float = Field(ge=0.0, le=1.0)
```

### Repository pattern

```python
class JobRepository:
    def __init__(self, session: Session) -> None:
        self._s = session
    def create(self, *, kind: str, preset_id: str, engine_session_id: str | None, ...) -> JobModel: ...
    def get(self, job_id: str) -> JobModel | None: ...
    def update_status(self, job_id: str, status: str, *, error: str | None = None) -> None: ...
    def pause_with_checkpoint(self, job_id: str, paused_at_index: int) -> None: ...
```

`core/` only ever talks to repositories.

### Orchestrator skeleton

```python
async def run_single(self, image, preset_id, overrides=None, seed=None) -> JobId:
    log = self._log.bind(preset_id=preset_id)

    # 1. Validate
    pil = self._preprocessor.validate(image)

    # 2. Resolve params
    preset = self._presets.get(preset_id)
    params = self._presets.merge(preset, overrides)

    # 3. Verify engine has the required LoRA / ControlNet
    info = await self._client.health()
    if params.lora.name not in info.available_loras:
        raise LoraMissingError(params.lora.name)

    # 4. Persist job
    seed = seed if seed is not None else random.randint(0, 2**32 - 1)
    job = self._jobs.create(
        kind="single",
        preset_id=preset_id,
        engine_session_id=self._current_session_id,
    )

    # 5. Dispatch async
    asyncio.create_task(self._execute_one(job.id, pil, params, seed))
    return job.id

async def _execute_one(self, job_id, image, params, seed) -> None:
    self._jobs.update_status(job_id, "running")
    try:
        ref = await self._client.upload_image(image)
        wf = self._workflows.build(ref, params, seed)
        prompt_id = await self._client.queue_prompt(wf)
        await self._client.poll_until_done(prompt_id, timeout_s=90)
        bytes_ = await self._client.fetch_output(prompt_id)
        out_path = self._metadata.write(job_id, image, bytes_, params, seed)
        self._jobs.complete(job_id, output_path=out_path)
    except TunnelDownError:
        self._jobs.update_status(job_id, "paused")
        log.warning("job.paused.tunnel_down", job_id=job_id)
    except AquaRenderError as e:
        self._jobs.fail(job_id, error_message=str(e))
        log.error("job.failed", job_id=job_id, code=e.code)
    except Exception:
        log.exception("job.crashed", job_id=job_id)
        self._jobs.fail(job_id, error_message="Internal error")
```

Note the critical distinction: `TunnelDownError` → status `paused`, not `failed`. Different recovery path.

### Streamlit page pattern

```python
def render() -> None:
    if not st.session_state.get("engine_connected"):
        st.warning("Connect to an engine first")
        st.button("Go to Connect tab", on_click=lambda: st.switch_page("pages/connect.py"))
        st.stop()

    st.header("Single Image")
    uploaded = st.file_uploader("Upload image", type=["png", "jpg", "jpeg", "webp"])
    preset_id = st.selectbox("Preset", _list_preset_ids(), format_func=_preset_label)
    strength = st.select_slider("Watercolor strength", ["Light", "Medium", "Strong"], value="Medium")
    preservation = st.select_slider("Structure preservation", ["Low", "Medium", "High"], value="Medium")

    if st.button("Generate", disabled=uploaded is None):
        orch = get_orchestrator()
        job_id = orch.run_single_sync(
            image=uploaded.getvalue(),
            preset_id=preset_id,
            overrides=SliderOverrides(watercolor_strength=strength, structure_preservation=preservation),
        )
        st.session_state.current_job_id = job_id

    _render_progress_and_result()
```

UI files contain **zero generation logic**. They call `orchestrator` and render state. They check `engine_connected` and refuse to render if not.

---

## Testing

### Pyramid

- `tests/unit/` — fast, no network, no GPU. Uses `FakeRemoteComfyUIClient`. **Run on every commit.**
- `tests/integration/` — orchestrator + DB + mocked engine. Medium speed.
- `tests/e2e/` — full pipeline against a real Kaggle tunnel. **Manual / nightly.** Require an env var `AQUARENDER_E2E_TUNNEL_URL`.

### `FakeRemoteComfyUIClient`

```python
class FakeRemoteComfyUIClient:
    def __init__(self, fixture_image: Path, gpu_name: str = "Tesla P100-PCIE-16GB") -> None:
        self._fixture = fixture_image
        self._gpu = gpu_name
        self._tunnel_alive = True

    def simulate_tunnel_down(self) -> None:
        self._tunnel_alive = False

    def simulate_tunnel_up(self) -> None:
        self._tunnel_alive = True

    async def health(self) -> EngineInfo:
        if not self._tunnel_alive:
            raise TunnelDownError("https://fake.test", "simulated")
        return EngineInfo(reachable=True, gpu_name=self._gpu, ...)

    async def upload_image(self, image): ...
    async def queue_prompt(self, workflow): return "fake_prompt_id"
    async def poll_until_done(self, prompt_id, timeout_s=90):
        if not self._tunnel_alive:
            raise TunnelDownError(...)
        return {"status": "success"}
    async def fetch_output(self, prompt_id):
        return self._fixture.read_bytes()
```

This is THE most-used test fixture. It must support tunnel-down simulation; that's a top-tier code path.

### Coverage targets

- `core/`: 90% line coverage
- `db/`: 85%
- `engine/`: 75% (mocking httpx is high-effort)
- `ui/`: 50% (Streamlit is hard to test; rely on smoke tests)

---

## Database Conventions

- Alembic for all schema changes. Hand-edit only data migrations.
- Every migration reviewed; no autogenerate accepted blindly.
- UTC everywhere. (`datetime('now')` in SQLite is UTC.)
- IDs as UUIDv4 strings (`TEXT PRIMARY KEY`).
- Booleans as `INTEGER` 0/1 with CHECK constraint.
- Always `created_at`; `updated_at` only on mutable rows.
- WAL mode pragma at connection time.

---

## Generation / Workflow Conventions

### One template, many presets

`workflows/img2img_controlnet_lora.json` is the only ComfyUI graph. Presets supply values. Don't fork the graph for a new preset; only fork for fundamentally different topology.

### Determinism rules

- Every random number seeded explicitly.
- `seed` recorded before generation, even when `seed_mode="random"`.
- Determinism is **per-engine-session** — same Kaggle session + same params + same LoRA = identical output. Across sessions, GPU class differences cause minor drift.

### Sampler defaults

DPM++ 2M SDE + Karras, 28 steps, CFG 5.5. Tuned in `tests/fixtures/preset_tuning_2026_04.md`. Change only in preset JSONs, never as code defaults.

---

## Environment Variables

```bash
# .env.local — never commit
AQUARENDER_DB_URL=sqlite:///./aquarender.db
AQUARENDER_OUTPUTS_DIR=./outputs
AQUARENDER_INPUTS_DIR=./inputs
AQUARENDER_LOG_LEVEL=info
AQUARENDER_LOG_JSON=false                            # true in CI

# Engine (pasted in UI; can also be set here for headless / scripts)
AQUARENDER_ENGINE_URL=https://abc-def.trycloudflare.com
AQUARENDER_ENGINE_SECRET=                            # optional shared-secret header (P1)

# E2E tests
AQUARENDER_E2E_TUNNEL_URL=                           # set when running e2e suite
```

### First-run

```bash
pipx install aquarender                              # or: uv tool install aquarender
aquarender doctor                                    # checks DB, outputs dir, etc.
# → Open Kaggle, run the notebook (one-time setup)
aquarender start                                     # opens localhost:8501
# → Paste tunnel URL into Connect tab
# → Start generating
```

---

## Performance Targets

| Metric | P100 target | T4 target |
|--------|-------------|-----------|
| Cold first generation (after notebook restart) | ≤ 60s | ≤ 90s |
| Warm 1024px generation | ≤ 20s | ≤ 35s |
| 50-image batch wall time | ≤ 18 min | ≤ 30 min |
| Tunnel RTT (laptop ↔ Kaggle) | ≤ 200ms | same |
| Image upload (1024px) | ≤ 1s | same |
| Image download (1024px) | ≤ 1s | same |
| UI interaction (non-gen) | ≤ 200ms | n/a |

Regressions > 10% need to be flagged in PR description.

---

## Security Checklist

For every PR touching input handling:

- [ ] User-supplied paths validated (no traversal)
- [ ] Zip uploads bounded (1GB uncompressed, 1000 files)
- [ ] PIL `MAX_IMAGE_PIXELS` enforced
- [ ] No `eval()`/`exec()`/`pickle.loads()` of user data
- [ ] No secrets in code (env vars only)
- [ ] No telemetry / phone-home anywhere
- [ ] No content filtering of prompts or outputs (this is a feature)
- [ ] Pydantic validation at every input boundary

---

## Known Issues & Gotchas

### Tunnel URL changes every Kaggle session
The Cloudflare URL is regenerated each time the notebook starts. Document prominently. The Connect tab persists the *most recent* URL but always asks for confirmation on app start.

### Kaggle 5-minute idle timeout
Kaggle kills the kernel if no cell is executing for 5 minutes. **`KeepaliveTask` pings every 4 minutes during batches** to prevent this. If a batch is paused mid-flight (e.g., user closes laptop), Kaggle will eventually kill the session — that's expected, the user reconnects on resume.

### Kaggle 9-hour session limit
Hard cap. Long batches must be split. Resume-from-checkpoint handles this transparently, but communicate it in batch progress UI.

### ComfyUI version drift
Pin the ComfyUI commit in the notebook (`!cd ComfyUI && git checkout <sha>`). Same pin tested in our `RemoteComfyUIClient`. Bumping the pin = test the full flow against a fresh Kaggle.

### `/object_info` is HUGE
~1MB of JSON listing every node. We call it once on connect (to enumerate LoRAs/ControlNets), cache it, refresh only on reconnect. Don't call it per-generation.

### EXIF orientation on iPhone photos
PIL doesn't auto-orient. **Always call `ImageOps.exif_transpose(img)` in the preprocessor.** Otherwise sideways outputs blamed on the model.

### Streamlit reruns
Every widget interaction triggers a full script rerun. Cache the orchestrator with `@st.cache_resource` (singleton). **Don't `@st.cache_data` large blobs (images)** — memory grows unbounded.

### SQLite WAL files on macOS
`-wal` and `-shm` files appear next to the DB. Fine. Gitignore `*.db`, `*.db-wal`, `*.db-shm`.

### Watercolor LoRA prompt anchor
The default LoRA expects "watercolor painting" or "watercolor style" in the positive prompt. Don't strip the watercolor anchor when users edit prompts.

### Kaggle dataset paths
User-uploaded LoRAs land in `/kaggle/input/<dataset-name>/`. The notebook symlinks them into `/kaggle/working/ComfyUI/models/loras/`. `RemoteComfyUIClient.list_loras()` returns the names visible to ComfyUI, including the symlinked ones.

### "Model not found" errors
ComfyUI reports `node_errors` in the `/prompt` response. We map these to `LoraMissingError`/`CheckpointMissingError`/`ControlNetMissingError` based on which node raised. Common cause: notebook didn't finish downloading models before the user tried to generate; `aquarender doctor` should catch this.

### Public tunnel URL caveat
`*.trycloudflare.com` URLs are accessible to anyone who has them. Document: **don't paste your tunnel URL anywhere public.** P1 adds an optional shared-secret header.

---

## Commit Conventions

```
[type]([scope]): [imperative summary]
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`.
Scopes: `core`, `engine`, `ui`, `db`, `cli`, `presets`, `workflows`, `notebook`, `infra`.

Examples:
```
feat(engine): add TunnelHealthMonitor with 30s ping interval
fix(notebook): handle Kaggle's switch from cuda:0 to cuda:1 ordering
docs(prd): clarify free-tier-only constraint
perf(engine): drop /object_info call from per-generation path; cache once at connect
```

---

## When You're Stuck

1. **Layering question?** `ARCHITECTURE.md` § "Component Architecture" + the layering rule above.
2. **What's the API contract?** `API.md`.
3. **What's in this column?** `DATABASE.md`.
4. **Why are we building this?** `PRD.md`.
5. **Tunnel issue?** Check `aquarender doctor` first; check that the Kaggle notebook cell is still running.
6. **ComfyUI weirdness?** Check the notebook output cell (its `print(...)` shows ComfyUI logs). The error is almost always there.

---

## Useful Resources

- ComfyUI HTTP API: read `RemoteComfyUIClient` source — it's the canonical reference for what we use.
- Diffusers img2img: https://huggingface.co/docs/diffusers/using-diffusers/img2img
- Diffusers ControlNet: https://huggingface.co/docs/diffusers/using-diffusers/controlnet
- Watercolor LoRA: https://huggingface.co/ostris/watercolor_style_lora_sdxl
- Cloudflare Tunnel docs: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/
- Kaggle GPU notebook docs: https://www.kaggle.com/docs/notebooks

---

**Last updated**: 2026-04-30
**Maintained by**: Ali Naserifar
