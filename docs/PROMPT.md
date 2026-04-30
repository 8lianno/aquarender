# AquaRender — Agentic Coding Kickoff Prompt

You are building **AquaRender** — a free-tier-only watercolor batch image transformer. The local app is a thin Streamlit UI + Python core + SQLite. The actual SDXL + watercolor LoRA + ControlNet generation runs on a free Kaggle GPU notebook running ComfyUI, exposed via Cloudflare Tunnel. The user's laptop never holds models, never needs a GPU, never pays.

The product promise: **drop a folder of photos in, get back a folder of watercolor paintings — your choice of LoRA, no fees, no filters, no GPU on your laptop.**

---

## Required reading (in order)

1. `CLAUDE.md` — your dev guide. Re-read every task.
2. `PRD.md` — what + why + scope.
3. `ARCHITECTURE.md` — system design. The layering rule and Decision N sections are non-negotiable.
4. `API.md` — internal Python API + remote ComfyUI surface we consume.
5. `DATABASE.md` — schema.

---

## Build phases

Build in order. Each phase ships working software. Don't skip ahead.

### Phase 1 — The Kaggle notebook (engine deliverable) — 2 days

**This is foundational.** Without a working notebook, nothing downstream can be tested.

**Tasks:**
- [ ] `notebooks/aquarender_kaggle.ipynb` with cells:
  1. Detect GPU; abort with friendly error if none (toggle GPU in notebook settings)
  2. `git clone` ComfyUI at pinned commit; `pip install -r requirements.txt`
  3. Download SDXL Base 1.0 to `models/checkpoints/`
  4. Download `ostris/watercolor_style_lora_sdxl` to `models/loras/`
  5. Download Lineart-Realistic SDXL ControlNet to `models/controlnet/`
  6. Download Canny SDXL ControlNet to `models/controlnet/`
  7. Symlink any user LoRA datasets from `/kaggle/input/*/` into `models/loras/`
  8. Install `cloudflared` binary
  9. Launch ComfyUI on `127.0.0.1:8188` as background process
  10. Wait for ComfyUI health (poll `/system_stats`)
  11. Launch `cloudflared tunnel --url http://localhost:8188`, parse public URL
  12. Print URL prominently with copy-paste hint
  13. Tail ComfyUI logs in foreground (keeps cell running so session stays alive)
- [ ] Test on a fresh Kaggle account end-to-end
- [ ] Total notebook runtime cold-to-ready: ≤ 7 min target
- [ ] `notebooks/README.md` explains usage

**Success criteria:**
- Run notebook → printed Cloudflare URL → `curl <url>/system_stats` returns ComfyUI JSON
- LoRA list at `<url>/object_info` includes `watercolor_style_lora_sdxl.safetensors`
- A test ComfyUI workflow submitted via `<url>/prompt` succeeds

**Why first:** every other phase depends on having a real engine to point at.

---

### Phase 2 — Project scaffolding — ½ day

**Goal:** an empty but well-formed Python project that lints, type-checks, and tests cleanly.

**Tasks:**
- [ ] `pyproject.toml` per `CLAUDE.md` § Tech Stack
- [ ] Directory layout from `ARCHITECTURE.md`
- [ ] ruff, mypy strict, pytest, pytest-asyncio, pytest-cov configured
- [ ] `import-linter` config enforcing layering rule
- [ ] Alembic skeleton in `aquarender/db/migrations/`
- [ ] `aquarender/cli.py` Click commands: `start`, `doctor`, `migrate`
- [ ] `.env.example` with keys from `CLAUDE.md` § Env Vars
- [ ] GitHub Actions: ruff + mypy + `pytest tests/unit`

**Success criteria:**
- `uv run pytest` runs (zero tests, suite green)
- `uv run ruff check .` clean
- `uv run mypy aquarender` clean
- `uv run aquarender --help` lists subcommands

---

### Phase 3 — Database layer — 1 day

**Goal:** SQLite schema with `presets`, `jobs`, `outputs`, `engine_sessions`. Builtin presets seeded.

**Tasks:**
- [ ] SQLAlchemy models per `DATABASE.md`
- [ ] Initial migration `001_initial_schema.py` — tables, indexes, CHECK constraints
- [ ] Seed 4 builtin presets in migration
- [ ] `db/repo.py`: `JobRepository`, `OutputRepository`, `PresetRepository`, `EngineSessionRepository`
- [ ] Pydantic models in `core/params.py` (`ResolvedParams` etc.)
- [ ] WAL mode, foreign keys, busy_timeout pragmas at connection
- [ ] Tests: full repo coverage; migration up + down

**Success criteria:**
- `uv run aquarender migrate` creates DB and seeds presets
- `sqlite3 aquarender.db ".schema"` matches `DATABASE.md`
- Repo tests ≥ 90% coverage

---

### Phase 4 — Core services (engine-independent) — 1 day

**Goal:** `PresetService`, `ImagePreprocessor`, `MetadataWriter`, slider translation working against fixtures.

**Tasks:**
- [ ] `core/presets.py`: `PresetService.{list,get,create,update,delete,export,import_,merge}`
- [ ] `core/preprocessor.py`: `ImagePreprocessor.{validate,enumerate_dir,extract_zip}`
- [ ] `core/metadata.py`: `MetadataWriter.write` producing PNG + JSON sidecar v2 (with `engine` block)
- [ ] `SLIDER_TO_PARAMS` table per `API.md`
- [ ] `AquaRenderError` hierarchy with stable `code` attributes
- [ ] structlog configured per `CLAUDE.md` § Logging
- [ ] Tests: 90%+ coverage

**Success criteria:**
- `PresetService.merge(preset, SliderOverrides(watercolor_strength="Strong"))` returns expected `ResolvedParams`
- `ImagePreprocessor` rejects 100×100 with `ImageTooSmallError`
- EXIF-rotated test fixture is correctly oriented
- Zip-bomb fixture raises `ZipTooLargeError`

---

### Phase 5 — Engine integration — 2 days

**Goal:** `RemoteComfyUIClient`, `TunnelHealthMonitor`, `KeepaliveTask`, `WorkflowBuilder` driving the live Kaggle notebook from Phase 1.

**Tasks:**
- [ ] `engine/client.py`: `RemoteComfyUIClient` with all methods from `API.md`
  - httpx async, 90s default timeout, 1Hz polling for `/history`
  - Error classification: `TunnelDownError` vs `EngineError` vs `GenerationTimeoutError`
  - Mapping ComfyUI `node_errors` → `LoraMissingError` / `CheckpointMissingError` / `ControlNetMissingError`
- [ ] `engine/workflows.py`: `WorkflowBuilder.build(image_ref, params, seed)` parameterizing the workflow JSON
- [ ] `workflows/img2img_controlnet_lora.json`: complete ComfyUI graph (CheckpointLoader → LoraLoader → CLIPTextEncode pos/neg → LoadImage → VAEEncode → ControlNetLoader → ControlNetApplyAdvanced → KSampler → VAEDecode → SaveImage)
- [ ] `engine/tunnel.py`: `TunnelHealthMonitor` background coroutine, 30s interval, 3-strikes-down logic
- [ ] `engine/keepalive.py`: `KeepaliveTask` — pings root every 4 min during active batches
- [ ] `FakeRemoteComfyUIClient` test fixture supporting `simulate_tunnel_down/up`
- [ ] Tests:
  - Unit tests against the fake client
  - Integration test against the live Phase 1 notebook (gated by env var)

**Success criteria:**
- `RemoteComfyUIClient.health()` against the live notebook returns correct GPU info
- A workflow submission produces a real watercolor PNG in ≤ 25s on P100
- Killing `cloudflared` on the remote → `TunnelHealthMonitor` emits `tunnel_down` within 90s
- Restarting tunnel → emits `tunnel_recovered`

---

### Phase 6 — JobOrchestrator — 1.5 days

**Goal:** Full job lifecycle: single, batch, pause-on-tunnel-drop, resume.

**Tasks:**
- [ ] `core/orchestrator.py`: `JobOrchestrator` with all methods from `API.md`
- [ ] `run_single_sync` / `run_batch_sync` wrappers using `asyncio.run`
- [ ] Per-image try/except: `TunnelDownError` → status `paused`, other errors → `failed`, batch continues
- [ ] Batch checkpoint: `outputs/.checkpoint.{batch_id}.json` after every successful image
- [ ] `resume(job_id)`: rebuild from checkpoint, skip already-completed
- [ ] `rebind_engine(new_client)`: swap client when user reconnects
- [ ] `KeepaliveTask` started/stopped with batch lifecycle
- [ ] Tests:
  - Happy path single + batch
  - Mid-batch tunnel drop → pause → reconnect → resume
  - Cancel during batch
  - Retry failed children
  - Failure path (one bad image of 10 → 9 succeed)

**Success criteria:**
- Single image flow works end-to-end against live notebook
- 10-image batch with one corrupt fixture: 9 succeed, 1 marked failed
- Batch with simulated mid-flight tunnel drop: pauses correctly, resumes after `rebind_engine`
- Resume does not re-generate already-completed outputs

---

### Phase 7 — Streamlit UI — 2 days

**Goal:** Usable UI covering all P0 features.

**Tasks:**
- [ ] `ui/app.py`: top-level Streamlit app, navigation
- [ ] `ui/pages/connect.py`: tunnel URL input, Connect button, live engine info display, Disconnect
- [ ] `ui/pages/single.py`: upload, preset selector, sliders, optional custom-LoRA field, Generate button, before/after viewer, download
- [ ] `ui/pages/batch.py`: folder/zip input, preset, sliders, output size, seed mode, Run, live progress, grid view, ZIP download, per-row Retry button
- [ ] `ui/pages/presets.py`: list, view, create-from-current, delete user presets, export, import
- [ ] `ui/deps.py`: `@st.cache_resource` orchestrator singleton; engine_connected flag in session_state
- [ ] Persistent "Engine status" indicator in app header (✅/⚠️/❌)
- [ ] Reconnect modal triggered by `tunnel_down` event
- [ ] Live progress polls `get_status()` every 1s during running

**Success criteria:**
- All Flow 1, 2, 3, 4 from `PRD.md` § User Flows work end-to-end against live Kaggle notebook
- Mid-batch tunnel drop: UI shows reconnect modal within 60s
- Pasting a wrong URL: friendly error, doesn't connect
- A non-technical user can complete Flow 2 (returning session) in < 60 seconds

---

### Phase 8 — Polish, docs, release — 1.5 days

**Goal:** ready for an external user to try it.

**Tasks:**
- [ ] `README.md`: 30-second pitch, "Open in Kaggle" badge, screenshots, troubleshooting, free-tier emphasis
- [ ] Tune all 4 builtin presets on a 20-image test corpus (5 portraits, 5 products, 5 landscapes, 5 children's-book candidates). Document tuning in `tests/fixtures/preset_tuning_2026_04.md`. Iterate until human quality score ≥ 4/5 on subject preservation and ≥ 4/5 on style fidelity.
- [ ] 60-second setup video / GIF
- [ ] `aquarender doctor` polished — every failure mode has actionable error
- [ ] Distribution: `pipx install aquarender` works on a fresh laptop
- [ ] CI green on Linux + macOS
- [ ] Tag `v0.1.0`, write changelog

**Success criteria:**
- Fresh laptop → `pipx install aquarender` → run notebook on Kaggle → paste URL → first watercolor in ≤ 15 minutes including Kaggle account creation
- All P0 acceptance criteria from `PRD.md` met
- All MVP success metrics from `PRD.md` hit on the test corpus

---

## Working principles

### 1. The notebook is product code
`notebooks/aquarender_kaggle.ipynb` is shipped, version-controlled, tested. Breaking it breaks the product. Don't treat it as scratch work.

### 2. Pipeline first, UI later
Build `core/` + `engine/` to a runnable CLI demo before opening Streamlit. Test:
```bash
uv run python -c "
from aquarender.engine.client import RemoteComfyUIClient
from aquarender.engine.workflows import WorkflowBuilder
# ... generate one image programmatically
"
```
If you can't generate from Python directly, you don't get to start on UI.

### 3. Layering is non-negotiable
`import-linter` enforces the layering rule in CI. If you find yourself wanting `streamlit` from `core/` or `httpx` from `core/`, stop and rethink.

### 4. Tunnel drops are a primary flow, not an error
Every code path that touches the remote handles `TunnelDownError` explicitly. Don't catch-all into "failed."

### 5. Determinism within session, drift across sessions
Same seed + same params + same LoRA + same Kaggle session = identical output. We document this. Don't promise more.

### 6. Errors are typed
No bare `Exception` or `ValueError` from `core/` or `engine/`. Every domain error is `AquaRenderError` with a `code`.

### 7. The DB is authoritative for state; the filesystem holds the bytes
Outputs survive DB loss (sidecar JSONs travel with them). Never duplicate state across DB and filesystem; pick one source of truth per concept.

### 8. Don't over-engineer for v2
SQLite is right for v1. Streamlit is right for v1. No queue, no worker pool, no FastAPI in v1.

### 9. Test what matters most where it matters most
- `core/`: 90% coverage
- `db/`: 85%
- `engine/`: 75% (mocking httpx is high-effort)
- `ui/`: 50% (smoke tests)

### 10. Commit small, often, with intent
Conventional Commits. Each commit leaves the project green (lint + types + unit tests). 3 hours without a commit = working too big.

### 11. No content moderation in our code
We don't filter prompts. We don't filter outputs. The user's engine is the user's engine.

### 12. When uncertain, choose boring
SQLite over Postgres. httpx over aiohttp. Click over Typer. Streamlit over Gradio. Pydantic over manual dicts.

---

## What "done" looks like

**v1 ships when:**

A user with a free Kaggle account, no GPU on their laptop, and zero ML knowledge can:
1. Install AquaRender locally with one command
2. Open our notebook in Kaggle and click Run
3. Wait ~5 minutes for setup
4. Paste the printed tunnel URL into AquaRender
5. Drop a folder of 20 photos
6. Pick "Soft Watercolor"
7. Click Run
8. Get back 20 stylistically-consistent watercolor paintings of recognizably the same subjects
9. In under 12 minutes of generation time
10. Without paying a cent
11. Without their laptop ever loading a model file

That's the bar. Everything else serves it.

---

## Quick reference

```bash
# After cloning
git clone <repo>
cd aquarender
uv sync
uv run aquarender migrate
uv run pytest tests/unit            # No engine needed
uv run aquarender doctor            # Verify local setup

# Open Kaggle, run notebooks/aquarender_kaggle.ipynb, copy tunnel URL

uv run aquarender start              # localhost:8501
# Paste URL → Connect → Generate

# During development
uv run pytest tests/unit              # fast iteration
uv run ruff check --fix .
uv run mypy aquarender
```

### When stuck
1. Conventions / patterns → `CLAUDE.md`
2. Component placement → `ARCHITECTURE.md` § Repository Layout + Components
3. API contract → `API.md`
4. Schema → `DATABASE.md`
5. Why? → `PRD.md`
6. Notebook broken? → re-run from scratch, check GPU is enabled in Kaggle settings, verify model URLs

---

**Now read the five docs in order, then begin Phase 1.**
