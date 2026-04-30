# AquaRender — Product Requirements Document

**Version**: 2.0
**Date**: 2026-04-30
**Status**: Approved for MVP build
**Owner**: Ali Naserifar

---

## Executive Summary

AquaRender is a watercolor batch image transformer with **zero hosting cost and zero content censorship**. The user runs an open-source SDXL + watercolor LoRA + ControlNet pipeline on a free Kaggle GPU notebook, and a local Streamlit app on their laptop submits images to it through a Cloudflare tunnel. Nothing is downloaded to the user's laptop except a few hundred KB of Python code. Nothing flows through a corporate image-edit API that filters or watermarks output. Limited usage is free; heavy usage is also free, capped only by Kaggle's 30 GPU-hours/week.

---

## Problem Statement

### Current State

Three options exist today for someone who wants to convert a folder of photos into watercolor paintings:

1. **Pay-per-image SaaS** (Recraft, Midjourney, Adobe Generative Fill, Runway): $0.05–$0.50 per image, accumulating fast. **And every one of them runs a content filter** — the moment you swap to a more expressive LoRA or push the artistic direction, the API rejects the request or silently softens output.
2. **Generic AI image APIs** (Gemini Nano Banana, OpenAI image-edit, Adobe Firefly): free or cheap, but they are *not* the SDXL + LoRA stack. They run their own proprietary models with their own filters and their own aesthetic. There is no swapping in a watercolor LoRA. There is no swapping in *any* LoRA.
3. **Local ComfyUI installation**: full control and uncensored, but requires a 12GB+ NVIDIA GPU, a 12–20GB model download, and a non-trivial install. Out of reach for the target user.

### Impact

- A 100-image batch through a paid SaaS = $5–$50, every time.
- A 100-image batch through a content-filtered API = silently mediocre output and no way to fix it.
- A 100-image batch on a local install = impossible without a $400+ GPU.

### Root Cause

There is no free, uncensored, LoRA-driven, batch-capable watercolor pipeline accessible to people without high-end GPUs. Cloud APIs are censored. Local setups require hardware. We close the gap.

---

## Solution Overview

### Vision

> Drop a folder of photos in, get back a folder of watercolor paintings — same subjects, consistent style, your choice of LoRA, no filters, no fees, no GPU on your laptop.

### Value Proposition

> For creators who want LoRA-driven watercolor batches without paying per image and without API content filters, **AquaRender** is a thin local app that drives a free Kaggle-hosted ComfyUI engine. Unlike paid SaaS, it costs nothing per image. Unlike Gemini/OpenAI image APIs, it lets you swap any LoRA and runs without content moderation. Unlike a local ComfyUI install, it doesn't require a GPU on your laptop.

### Core Pipeline

```
Local laptop                 │   Free Kaggle Notebook (P100/T4 GPU)
                             │
Streamlit UI                 │   ComfyUI server
  → SQLite job state         │     ├─ SDXL Base 1.0
  → Image preprocessing      │     ├─ Watercolor LoRA (any)
  → Submit to remote engine ─┼─→  ├─ ControlNet (Lineart/Canny)
  → Download result          │     └─ img2img workflow
  → Write output + metadata  │
                             │   Cloudflare Tunnel exposes :8188
                             │   Models cached on Kaggle disk (free)
```

The user pastes the Kaggle tunnel URL into AquaRender once per session. Everything else is identical to having a local engine.

---

## Target Users

### Primary — "Sara, the Etsy seller"
- Macbook Air, no GPU. Wants 200 watercolor product shots without paying $0.20 each.
- Never installed ComfyUI. Will run a Kaggle notebook if shown a one-click "Open in Kaggle" button and a 60-second video.

### Primary — "Reza, the in-house designer"
- Knows ComfyUI, runs SD locally on a 3060 today. Wants a cleaner UI for batch jobs and the option to run on Kaggle when his GPU is busy.

### Internal — Ali (you)
- Wants the watercolor LoRA pipeline without the "is this prompt okay" battle that Gemini/Firefly fight every other request.

---

## Success Metrics

### MVP success (weeks 1–4)

| Metric | Target |
|--------|--------|
| Marginal cost per image | **$0.00** (hard) |
| Setup time from clone to first output | ≤ 15 min (incl. Kaggle account creation) |
| Single 1024px generation latency (P100, warm) | ≤ 20s |
| 50-image batch wall time (P100) | ≤ 18 min |
| Usable-output rate on test corpus | ≥ 70% |
| Batch consistency (stddev of style score 1–5) | ≤ 0.5 |
| Local laptop disk used by AquaRender | ≤ 200 MB |
| Local laptop GPU required | **None** |

### Product success (post-launch)

| Metric | Target |
|--------|--------|
| Batch completion rate | ≥ 95% |
| User-swapped LoRA at least once | ≥ 30% (proves differentiator) |
| Tunnel-disconnect recovery rate | ≥ 90% (resume on reconnect) |
| Free-tier retention at 30 days | ≥ 50% |

---

## Feature Requirements

### P0 — Must-Have

#### F-01: Connect to remote ComfyUI engine
The user pastes a Kaggle/Colab tunnel URL. AquaRender verifies it, lists available models/LoRAs/ControlNets on the remote, and stores the connection in session state.
- **Acceptance**:
  - [ ] Pastes URL, clicks Connect, sees green "Connected — P100 GPU, SDXL loaded" within 3s
  - [ ] Tunnel disconnect detected within 5s, UI shows reconnect prompt
  - [ ] Failed health check shows actionable error ("ComfyUI not running on remote", "URL unreachable", etc.)

#### F-02: Single-image img2img transformation
- **Acceptance**: 1024px output in ≤ 25s on warm P100; subject identity preserved (≥ 4/5 human score); output saved with sibling JSON metadata.

#### F-03: Folder/zip batch input
- **Acceptance**: Up to 100 images per batch in v1; non-images skipped with warning; per-image failure isolated; original filename preserved.

#### F-04: Watercolor presets
- 4 presets: `soft_watercolor`, `ink_watercolor`, `childrens_book`, `product_watercolor`.
- Each preset = deterministic combo of (LoRA name + weight, ControlNet model + strength, denoise, steps, CFG, prompt template).

#### F-05: Style strength + structure preservation sliders
- `Light/Medium/Strong` → numeric (denoise, lora_weight)
- `Low/Medium/High` → numeric (cn_strength)
- Override preset defaults; values recorded in metadata.

#### F-06: ControlNet structure preservation
- Lineart-Realistic SDXL primary; Canny SDXL fallback.
- ControlNet runs on the Kaggle remote, not locally.

#### F-07: Output preview + download
- Before/after slider for single image; thumbnail grid for batch; ZIP download for batch.

#### F-08: Per-image metadata logging
- JSON sidecar: input filename, full resolved params, seed, LoRA, ControlNet, model checkpoint, Kaggle session ID, timestamp, duration.

#### F-09: Custom LoRA loading (the differentiator)
- User can specify any LoRA filename present on the Kaggle remote.
- Built-in preset uses `ostris/watercolor_style_lora_sdxl`, but a "Custom LoRA" field lets users point at any LoRA they've uploaded to their Kaggle dataset.
- **This is the feature that makes the product valuable.** It's the reason we're not on Gemini.

#### F-10: Tunnel reconnect + resume
- If the Kaggle session times out mid-batch, AquaRender pauses the batch, prompts for new tunnel URL, and resumes from the next unprocessed image (using the SQLite checkpoint).

#### F-11: Kaggle notebook bootstrap
- We ship a one-click `aquarender_kaggle.ipynb` that:
  - Installs ComfyUI + dependencies
  - Downloads SDXL Base, watercolor LoRA, Lineart/Canny ControlNets to Kaggle disk
  - Starts ComfyUI on `:8188`
  - Starts Cloudflare Tunnel
  - Prints the public URL ready to paste into AquaRender

---

### P1 — Should-Have

#### F-12: Custom preset save/load
User saves slider+LoRA combos as named presets, exports as JSON.

#### F-13: Seed lock
Fixed seed across batch, or `seed = hash(filename)` mode for per-file determinism.

#### F-14: Before/after slider widget
Side-by-side draggable comparison for single-image preview.

#### F-15: Batch retry-failed
One-click retry of failed children with optional new seed.

#### F-16: Live progress with ETA
Per-image status, cumulative duration, ETA based on rolling average.

#### F-17: HuggingFace Space alternative engine
For users who don't want to run Kaggle, support connecting to a HuggingFace Space deployed with the same ComfyUI workflow. Same `engine` interface, different transport. Documented setup, not the default.

---

### P2 — Nice-to-Have

- F-18: LoRA browser — paste a Civitai URL, AquaRender tells the user the `wget` command to add it to their Kaggle session.
- F-19: Multiple-LoRA stacking with per-LoRA weights.
- F-20: Face preservation toggle (IP-Adapter on the remote).
- F-21: Upscaling pass (Real-ESRGAN on the remote).
- F-22: Tunnel auto-keepalive ping every 4 minutes (Kaggle idles after 5).

---

## Out of Scope (v1)

- ❌ **No paid APIs.** Not Replicate, not fal, not Stability, not Adobe, not Gemini, not OpenAI. Hard line.
- ❌ **No cloud-API image-edit shortcuts.** No Gemini Nano Banana fallback. No "for free tier we route to X." If the user can't connect to a Kaggle/Colab/HF engine, the app says so and doesn't generate.
- ❌ **No content moderation.** We pass prompts and images to the user's own ComfyUI instance unchanged. The user is responsible for what they generate on their own free GPU.
- ❌ **No model bundling.** The Kaggle notebook downloads models into the Kaggle session, not onto the user's laptop. Models never touch the user's disk.
- ❌ **No GPU on the user's laptop required.** CPU-only laptop is fully supported because all compute is remote.
- ❌ **No paid tier.** Not in v1. If we ever add one, it's separate product.
- ❌ Custom model training — too heavy.
- ❌ Mobile app, marketplace, multi-tenant cloud, video, text-to-image.

---

## User Flows

### Flow 1: First-time setup (15 min, one-time)
```
1. User installs AquaRender locally:
     pipx install aquarender   (or `uv tool install aquarender`)
2. User opens https://kaggle.com → New Notebook → "Import from URL" → pastes our notebook URL
3. User clicks "Run All" in Kaggle. Notebook:
     - Enables GPU (T4 or P100)
     - Installs ComfyUI + downloads models (~5 min)
     - Starts ComfyUI + Cloudflare Tunnel
     - Prints: "✅ AquaRender engine ready: https://abc-def.trycloudflare.com"
4. User runs locally:  aquarender start
5. User pastes the URL into "Engine URL" field, clicks Connect
6. Green check. User generates first watercolor.
```

### Flow 2: Returning session (30 sec)
```
1. User opens Kaggle → opens saved notebook → clicks "Run All" (or just "Restart and run all")
2. User runs `aquarender start` locally
3. User pastes the new tunnel URL (Cloudflare URLs change each session)
4. Connected. Generate.
```

### Flow 3: Batch with custom LoRA
```
1. User uploads their watercolor LoRA `.safetensors` to a Kaggle Dataset (one-time)
2. In their Kaggle notebook, the LoRA is now mounted at /kaggle/input/my-lora/
3. User in AquaRender selects "Custom LoRA" and types the filename
4. Runs batch. Outputs use their LoRA, no API filtering it.
```

### Flow 4: Mid-batch tunnel drop
```
1. Kaggle session disconnects mid-batch (it happens — 9hr session limit, idle timeout, etc.)
2. AquaRender detects within 5s, pauses batch, shows "Reconnect" dialog
3. User restarts the Kaggle notebook, pastes new URL
4. AquaRender resumes from image N+1 (where N = last successfully processed)
5. Outputs already on disk are not regenerated
```

---

## Non-Functional Requirements

### Performance
- Single 1024px image (warm P100): ≤ 20s generation + ≤ 2s network = ≤ 25s total
- 50-image batch (P100): ≤ 18 min wall clock
- UI responsiveness (non-generation): ≤ 200ms
- Tunnel health check: every 30s, < 200ms RTT

### Reliability
- Per-image failure rate: ≤ 5%
- Tunnel drop recovery: ≥ 90% of batches survive at least one disconnect
- Resume-from-checkpoint: 100%

### Security & privacy
- All processing on the user's own Kaggle session (their account, their compute, their disk).
- Cloudflare Tunnel uses ephemeral URLs (`*.trycloudflare.com`) — no auth in v1; users should not paste tunnel URLs publicly.
- P1: optional shared-secret token in tunnel header so only the user's AquaRender app talks to their engine.
- No telemetry. No phone-home. No analytics on what users generate.

### Compatibility
- Local: Python 3.11+ on macOS/Linux/Windows. **No GPU required locally.** ~200MB total install.
- Remote: Any environment running ComfyUI 0.3+ with Cloudflare Tunnel — Kaggle (primary), Colab (secondary), HuggingFace Space (alternative), local ComfyUI (power users).

---

## Technical Constraints

- **Free tier only.** No path in v1 requires payment.
- **Open-source models only.** SDXL Base 1.0, public watercolor LoRAs, public ControlNets. No proprietary API in the generation path.
- **No content moderation in the app code.** We don't filter prompts. We don't filter images. The remote engine is the user's; what they do on it is their business.
- **Models live on the remote.** Local laptop disk usage ≤ 200MB.
- **Reproducible.** Same seed + same params + same LoRA file = same output (within fp32 tolerances on the same GPU class).

---

## Timeline

| Phase | Deliverables | Duration |
|-------|--------------|----------|
| Phase 1: Kaggle notebook + tunnel client | `aquarender_kaggle.ipynb` boots ComfyUI on P100, exposes via Cloudflare Tunnel; Python client connects | 4 days |
| Phase 2: Engine + core services | RemoteComfyUIClient, PresetService, ImagePreprocessor, MetadataWriter | 4 days |
| Phase 3: JobOrchestrator + DB | Job lifecycle, batch, resume-from-checkpoint, SQLite | 3 days |
| Phase 4: Streamlit UI | Connect tab, single tab, batch tab, presets tab | 5 days |
| Phase 5: Polish + release | Doctor command, docs, demo video, packaging | 4 days |

**Total: 4 weeks.**

---

## Risks & Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Cloudflare blocks/rate-limits free tunnels | High | Low | Document `ngrok` and `bore` as alternates; tunnel client supports any of three |
| Kaggle changes free GPU policy | High | Low | Notebook is portable to Colab + HF Space + local ComfyUI; tunnel client is engine-agnostic |
| Kaggle session 9hr / idle timeout breaks long batches | High | High | Batches > 9hr split into chunks; resume-from-checkpoint; keepalive ping P2 |
| Model downloads exceed Kaggle disk | Medium | Low | SDXL+LoRA+CN < 15GB; Kaggle has ~70GB free; we monitor |
| First-run UX confuses non-technical users | High | High | One-click "Open in Kaggle" badge in README; 60s setup video; clear error messages |
| Public tunnel URL leaks → strangers use user's GPU | Low | Medium | P1 shared-secret header; document "don't paste your tunnel URL anywhere public" |
| ComfyUI version drift between releases | Medium | Medium | Notebook pins ComfyUI commit; documented upgrade path |

---

## Open Questions

| Question | Decision |
|----------|----------|
| Kaggle vs Colab as the documented primary? | **Kaggle** — 30hr/week guaranteed, P100 typical, 70GB disk. Colab is "best effort" per Google's own docs. |
| Cloudflare Tunnel vs ngrok vs bore? | **Cloudflare** primary (stable, free, no signup); ngrok and bore as alternates if Cloudflare is blocked in user's region. |
| Should we host a public demo Space? | **No** in v1 — encourages free-rider abuse and content the user community has to defend. v2 maybe. |
| HuggingFace Space as P1 alternative? | **Yes** — same ComfyUI engine, different transport. Helpful for users in regions where Kaggle is slow. |

---

## Related Documents

- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — system design and Kaggle/tunnel topology
- [`API.md`](./API.md) — internal Python API and remote ComfyUI surface
- [`DATABASE.md`](./DATABASE.md) — SQLite schema
- [`CLAUDE.md`](./CLAUDE.md) — development guide
- [`PROMPT.md`](./PROMPT.md) — agentic-coding kickoff
