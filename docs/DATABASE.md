# AquaRender — Database Schema

**Version**: 2.0
**Date**: 2026-04-30
**Database**: SQLite 3.40+ (single-file, local on user's laptop)
**ORM**: SQLAlchemy 2.0 + Alembic

---

## Overview

The database lives on the user's laptop next to the AquaRender install. It tracks:

1. **Presets** — both built-in and user-created
2. **Jobs** — every generation request (single, batch, or batch child)
3. **Outputs** — successful generations with full reproducibility metadata
4. **Engine sessions** — which Kaggle/Colab/HF tunnel produced each output (NEW in v2)

The architectural shift to a remote engine adds one concept to the schema: every output is tagged with the **engine session** that generated it. This matters because:
- Reproducibility is per-session (same Kaggle session + same seed = same output; different sessions may drift slightly due to different GPU classes)
- Debugging "this batch came out weird" requires knowing which engine ran it
- Future analytics ("most-used engine type") become possible

The filesystem holds the actual image bytes and JSON sidecars; the database holds queryable structured state. **Database is authoritative for status; filesystem is authoritative for bytes.**

---

## Entity-Relationship Diagram

```
┌─────────────┐       ┌────────────────────┐       ┌─────────────┐
│   presets   │       │       jobs         │       │   outputs   │
├─────────────┤       ├────────────────────┤       ├─────────────┤
│ id (PK)     │◀──────│ preset_id (FK)     │◀──────│ job_id (FK) │
│ name        │  1:N  │ id (PK)            │  1:1  │ id (PK)     │
│ description │       │ parent_job_id      │  ┌───▶│ engine_session_id (FK)
│ params_json │       │   (self FK)        │  │    │ input_path  │
│ is_builtin  │       │ kind               │  │    │ output_path │
│ created_at  │       │ status             │  │    │ params_json │
│ updated_at  │       │ overrides_json     │  │    │ seed        │
└─────────────┘       │ engine_session_id  │──┘    │ duration_ms │
                      │ input_count        │       │ width       │
                      │ success_count      │       │ height      │
                      │ failure_count      │       │ file_size   │
                      │ paused_at_index    │       │ created_at  │
                      │ started_at         │       └──────┬──────┘
                      │ finished_at        │              │
                      │ error_message      │              │
                      │ created_at         │              │
                      └──────────┬─────────┘              │
                                 │                        │
                                 ▼                        ▼
                       ┌──────────────────────────────────────┐
                       │       engine_sessions                │
                       ├──────────────────────────────────────┤
                       │ id (PK)                              │
                       │ tunnel_url                           │
                       │ engine_type     ('kaggle','colab',   │
                       │                  'hf-space','local') │
                       │ gpu_name                             │
                       │ comfyui_version                      │
                       │ first_seen_at                        │
                       │ last_seen_at                         │
                       │ disconnected_at                      │
                       └──────────────────────────────────────┘
```

### Cardinality

- One **preset** has many **jobs**.
- One **batch job** has many **child jobs** (`parent_job_id` self-reference).
- One **job** has zero or one **output** (zero if failed/cancelled/paused).
- One **engine session** has many **jobs** and many **outputs**.

---

## Table Definitions

### `presets`

Stores both built-in and user-defined presets. Built-in presets seeded at install; user presets mutable.

```sql
CREATE TABLE presets (
    id              TEXT PRIMARY KEY,           -- 'soft_watercolor', 'user_my_v2'
    name            TEXT NOT NULL,
    description     TEXT,
    params_json     TEXT NOT NULL,              -- Validated as ResolvedParams
    is_builtin      INTEGER NOT NULL DEFAULT 0, -- 0/1
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (is_builtin IN (0, 1)),
    CHECK (id GLOB '[a-z]*' AND length(id) <= 64)
);

CREATE INDEX idx_presets_is_builtin ON presets(is_builtin);
```

**Built-in seeds** (created in initial migration):

| id | name | description |
|----|------|-------------|
| `soft_watercolor` | Soft Watercolor | Portraits, lifestyle, weddings — gentle wash, high preservation |
| `ink_watercolor` | Ink + Watercolor | Architecture, urban scenes — clean ink + soft color |
| `childrens_book` | Children's Book | Characters, animals — looser, warmer, illustrative |
| `product_watercolor` | Product Watercolor | Ecommerce — preserve shape, clean background |

---

### `engine_sessions` (NEW in v2)

Each time the user pastes a tunnel URL and successfully connects, a new row is created. The session row is updated as we periodically re-check health and finally marked disconnected.

```sql
CREATE TABLE engine_sessions (
    id                TEXT PRIMARY KEY,                  -- UUIDv4
    tunnel_url        TEXT NOT NULL,
    engine_type       TEXT NOT NULL,                     -- 'kaggle' | 'colab' | 'hf-space' | 'local' | 'unknown'
    gpu_name          TEXT,                              -- e.g. 'Tesla P100-PCIE-16GB'
    comfyui_version   TEXT,
    first_seen_at     TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at      TEXT NOT NULL DEFAULT (datetime('now')),
    disconnected_at   TEXT,                              -- NULL while active

    CHECK (engine_type IN ('kaggle', 'colab', 'hf-space', 'local', 'unknown'))
);

CREATE INDEX idx_engine_sessions_active ON engine_sessions(disconnected_at)
    WHERE disconnected_at IS NULL;
CREATE INDEX idx_engine_sessions_first_seen ON engine_sessions(first_seen_at DESC);
```

**Notes:**
- `engine_type` inferred heuristically from the tunnel URL (`*.trycloudflare.com` → unknown remote; `*.ngrok-free.app` → unknown remote; URL structure plus `/system_stats` response can hint at Kaggle vs Colab — best-effort classification).
- `last_seen_at` updated by `TunnelHealthMonitor` on successful pings.
- `disconnected_at` set when health monitor declares the tunnel dead.
- Sessions are **append-only**; we never delete them. They're audit trail.

---

### `jobs`

Every transformation request creates a job row. Batches additionally create one child job per input image, linked via `parent_job_id`.

```sql
CREATE TABLE jobs (
    id                  TEXT PRIMARY KEY,           -- UUIDv4
    parent_job_id       TEXT,                        -- NULL for top-level
    preset_id           TEXT NOT NULL,
    engine_session_id   TEXT,                        -- NEW v2; NULL if job created before connection
    kind                TEXT NOT NULL,               -- 'single' | 'batch' | 'batch_item'
    status              TEXT NOT NULL,               -- queued|running|paused|success|failed|cancelled
    overrides_json      TEXT,                        -- Slider override numerics
    input_count         INTEGER NOT NULL DEFAULT 1,
    success_count       INTEGER NOT NULL DEFAULT 0,
    failure_count       INTEGER NOT NULL DEFAULT 0,
    paused_at_index     INTEGER,                     -- NEW v2: for batch resume
    started_at          TEXT,
    finished_at         TEXT,
    error_message       TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),

    FOREIGN KEY (parent_job_id)        REFERENCES jobs(id)              ON DELETE CASCADE,
    FOREIGN KEY (preset_id)            REFERENCES presets(id),
    FOREIGN KEY (engine_session_id)    REFERENCES engine_sessions(id),

    CHECK (kind IN ('single', 'batch', 'batch_item')),
    CHECK (status IN ('queued', 'running', 'paused', 'success', 'failed', 'cancelled')),
    CHECK (
        (kind IN ('single', 'batch') AND parent_job_id IS NULL) OR
        (kind = 'batch_item' AND parent_job_id IS NOT NULL)
    )
);

CREATE INDEX idx_jobs_status            ON jobs(status);
CREATE INDEX idx_jobs_kind              ON jobs(kind);
CREATE INDEX idx_jobs_parent_job_id     ON jobs(parent_job_id);
CREATE INDEX idx_jobs_preset_id         ON jobs(preset_id);
CREATE INDEX idx_jobs_engine_session_id ON jobs(engine_session_id);
CREATE INDEX idx_jobs_created_at        ON jobs(created_at DESC);
CREATE INDEX idx_jobs_status_kind       ON jobs(status, kind);
```

**Status state machine (v2 — adds `paused`):**

```
       queued  ──┐
                 ▼
              running ──── tunnel drop ───▶  paused
                 │                              │
                 │                              │  user reconnects
                 │                              │  + clicks Resume
                 │                              ▼
                 │                           running
                 ▼
       ┌───────┬──────────┬──────────┐
       │       │          │          │
    success failed   cancelled  (terminal)
```

**Key columns:**
- `engine_session_id`: which tunnel session was active when this job ran. For batches that span sessions (paused → reconnected → resumed), each `batch_item` child can have a *different* session ID — that's intentional, it tells you exactly which images came from which GPU.
- `paused_at_index`: for batches, the 0-indexed position of the next unprocessed image. Used by resume.
- `error_message`: short, user-facing. Stack traces go to logs, not DB.

---

### `outputs`

One row per successful generation. Failed jobs produce no `outputs` row.

```sql
CREATE TABLE outputs (
    id                 TEXT PRIMARY KEY,
    job_id             TEXT NOT NULL UNIQUE,
    engine_session_id  TEXT NOT NULL,                 -- NEW v2: required
    input_path         TEXT NOT NULL,
    output_path        TEXT NOT NULL,
    params_json        TEXT NOT NULL,                 -- Resolved params used
    seed               INTEGER NOT NULL,
    duration_ms        INTEGER NOT NULL,              -- Wall-clock incl. network
    width              INTEGER NOT NULL,
    height             INTEGER NOT NULL,
    file_size_bytes    INTEGER NOT NULL,
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),

    FOREIGN KEY (job_id)            REFERENCES jobs(id)              ON DELETE CASCADE,
    FOREIGN KEY (engine_session_id) REFERENCES engine_sessions(id)
);

CREATE INDEX idx_outputs_job_id            ON outputs(job_id);
CREATE INDEX idx_outputs_engine_session_id ON outputs(engine_session_id);
CREATE INDEX idx_outputs_created_at        ON outputs(created_at DESC);
```

**Notes:**
- `engine_session_id` is **required** on outputs — a successful generation always came from some engine session.
- `params_json`: the *frozen, resolved* params actually used. For exact regeneration.
- `duration_ms`: includes network round-trip. For pure-GPU time, subtract typical network RTT.

---

### `alembic_version`

Standard Alembic migration tracking. Single row.

```sql
CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY);
```

---

## Resolved Params Schema (`presets.params_json`, `outputs.params_json`)

Validated by Pydantic on every read.

```json
{
  "schema_version": 1,
  "model": {
    "checkpoint": "sd_xl_base_1.0.safetensors"
  },
  "lora": {
    "name": "watercolor_style_lora_sdxl.safetensors",
    "weight": 0.85
  },
  "controlnet": {
    "model": "diffusers_xl_lineart_full.safetensors",
    "preprocessor": "lineart_realistic",
    "strength": 0.80,
    "start_percent": 0.0,
    "end_percent": 1.0
  },
  "sampler": {
    "name": "dpmpp_2m_sde",
    "scheduler": "karras",
    "steps": 28,
    "cfg": 5.5,
    "denoise": 0.50
  },
  "prompt": {
    "positive": "watercolor painting, soft brushstrokes, paper texture, gentle color bleed, hand-painted",
    "negative": "photo, photograph, photorealistic, 3d render, oil painting, harsh edges, oversaturated, low quality, blurry"
  },
  "output": {
    "width": 1024,
    "height": 1024,
    "format": "png"
  }
}
```

### Pydantic models

```python
from pydantic import BaseModel, Field
from typing import Literal

class ModelParams(BaseModel):
    checkpoint: str

class LoraParams(BaseModel):
    name: str
    weight: float = Field(ge=0.0, le=2.0)

class ControlNetParams(BaseModel):
    model: str
    preprocessor: Literal["lineart_realistic", "canny", "depth_midas"]
    strength: float = Field(ge=0.0, le=1.0)
    start_percent: float = Field(ge=0.0, le=1.0, default=0.0)
    end_percent: float = Field(ge=0.0, le=1.0, default=1.0)

class SamplerParams(BaseModel):
    name: str
    scheduler: str
    steps: int = Field(ge=1, le=150)
    cfg: float = Field(ge=1.0, le=30.0)
    denoise: float = Field(ge=0.0, le=1.0)

class PromptParams(BaseModel):
    positive: str
    negative: str = ""

class OutputParams(BaseModel):
    width: int = Field(ge=256, le=2048)
    height: int = Field(ge=256, le=2048)
    format: Literal["png", "webp"] = "png"

class ResolvedParams(BaseModel):
    schema_version: int = 1
    model: ModelParams
    lora: LoraParams
    controlnet: ControlNetParams
    sampler: SamplerParams
    prompt: PromptParams
    output: OutputParams
```

---

## Metadata JSON Sidecar Schema

Every successful output writes a sibling `.json`. **Denormalized** so it's portable.

`outputs/2026-04-30/IMG_2341_watercolor.json`:

```json
{
  "metadata_version": 2,
  "input_file": "IMG_2341.jpg",
  "input_path": "inputs/wedding_batch/IMG_2341.jpg",
  "output_file": "IMG_2341_watercolor.png",
  "output_path": "outputs/2026-04-30/IMG_2341_watercolor.png",
  "preset_id": "soft_watercolor",
  "preset_name": "Soft Watercolor",
  "params": { /* full ResolvedParams */ },
  "seed": 391247,
  "duration_ms": 23410,
  "width": 1024,
  "height": 1024,
  "file_size_bytes": 1842734,
  "job_id": "0d3b2a91-4e2e-4a0e-9e8a-b62a5ad7e1d9",
  "batch_id": "f9c1c3f4-1234-5678-9abc-def012345678",
  "engine": {
    "session_id": "4f3a-...",
    "type": "kaggle",
    "gpu": "Tesla P100-PCIE-16GB",
    "comfyui_version": "0.3.10",
    "tunnel_url_at_time": "https://abc-def.trycloudflare.com"
  },
  "aquarender_version": "0.1.0",
  "created_at": "2026-04-30T14:32:11Z",
  "status": "success"
}
```

---

## Common Queries

### Q1 — Recent batches with status
```sql
SELECT id, preset_id, status, input_count, success_count, failure_count,
       started_at, finished_at,
       CAST((julianday(COALESCE(finished_at, datetime('now'))) - julianday(started_at)) * 86400 AS INTEGER) AS duration_s
FROM jobs WHERE kind = 'batch'
ORDER BY created_at DESC LIMIT 20;
```

### Q2 — Find a paused batch ready to resume
```sql
SELECT id, preset_id, paused_at_index, input_count
FROM jobs
WHERE kind = 'batch' AND status = 'paused'
ORDER BY created_at DESC;
```

### Q3 — Per-engine generation time stats
```sql
SELECT
    es.engine_type,
    es.gpu_name,
    COUNT(o.id) AS images,
    AVG(o.duration_ms) AS avg_ms,
    MIN(o.duration_ms) AS min_ms,
    MAX(o.duration_ms) AS max_ms
FROM outputs o
JOIN engine_sessions es ON es.id = o.engine_session_id
WHERE o.created_at >= datetime('now', '-7 days')
GROUP BY es.engine_type, es.gpu_name
ORDER BY images DESC;
```

### Q4 — Outputs from a specific engine session (debug)
```sql
SELECT o.input_path, o.output_path, o.duration_ms, j.status
FROM outputs o
JOIN jobs j ON j.id = o.job_id
WHERE o.engine_session_id = :session_id
ORDER BY o.created_at;
```

### Q5 — Failed children of a batch
```sql
SELECT id, error_message, created_at
FROM jobs
WHERE parent_job_id = :batch_id AND status = 'failed'
ORDER BY created_at;
```

### Q6 — Most-used LoRAs (parsed from output params)
```sql
-- Requires JSON1 (built into modern SQLite)
SELECT
    json_extract(params_json, '$.lora.name') AS lora_name,
    COUNT(*) AS uses
FROM outputs
WHERE created_at >= datetime('now', '-30 days')
GROUP BY lora_name
ORDER BY uses DESC;
```

---

## Indexing Strategy

| Index | Purpose |
|-------|---------|
| `idx_jobs_status` | "Show in-flight jobs" |
| `idx_jobs_kind` | Filter top-level vs child |
| `idx_jobs_parent_job_id` | Children-of-batch lookups |
| `idx_jobs_preset_id` | Preset usage analytics |
| `idx_jobs_engine_session_id` | "Which session ran this?" |
| `idx_jobs_created_at` | Recent jobs (UI list) |
| `idx_jobs_status_kind` | "Show running batches" composite |
| `idx_outputs_job_id` | Join from jobs |
| `idx_outputs_engine_session_id` | Per-session output stats |
| `idx_outputs_created_at` | Gallery view |
| `idx_engine_sessions_active` | Partial index on currently-connected sessions |
| `idx_engine_sessions_first_seen` | Session history |

---

## Migrations

Alembic-managed. Version table is `alembic_version`.

### History

| Version | Name | Description |
|---------|------|-------------|
| 001 | `initial_schema` | All tables, indexes, builtin presets |
| 002 | `add_engine_sessions` | (only if v1 ever shipped) |

For v2-from-scratch, everything is in `001`.

### Commands

```bash
uv run aquarender migrate              # alembic upgrade head
uv run alembic revision -m "..." --autogenerate
uv run alembic downgrade -1            # dev only
```

---

## SQLite Pragmas

Set at connection time:

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
```

WAL is necessary because the UI polls job status (read) while the orchestrator writes — without WAL, readers block writers.

---

## Backup & Recovery

### Backup
```bash
sqlite3 aquarender.db ".backup aquarender.db.bak"
```
The DB is small (megabytes for thousands of jobs); full file copy is fine.

### Recovery without the DB
Every output PNG has a sibling `.json` with full params and engine info. A `aquarender rebuild-db --from-outputs ./outputs/` command (P2) reconstructs the DB from sidecars.

---

## Performance

- SQLite write throughput on consumer SSD: ≥ 10K inserts/sec. We write 2 rows per image (job + output). DB is **never the bottleneck** vs ~20s remote generation.
- WAL mode required for concurrent UI reads + orchestrator writes.
- Single connection per process; no pool needed.

---

## Schema Evolution Rules

1. Additive changes only between minor versions (new nullable cols, new tables).
2. Bump `metadata_version` and `schema_version` in JSON when changing JSON shape.
3. Always Alembic `--autogenerate` then review.
4. Test migrations on a copy of real data before shipping.

---

## Related Documents

- [`PRD.md`](./PRD.md) — features driving the schema
- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — how engine sessions integrate
- [`API.md`](./API.md) — request/response shapes that map to these tables
- [`CLAUDE.md`](./CLAUDE.md) — DB commands and conventions
