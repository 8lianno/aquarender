# AquaRender

Local-first watercolor batch image transformer. The Streamlit UI runs on your laptop; the GPU work runs on a free Kaggle notebook exposed over Cloudflare Tunnel. **No paid API. No content filter. No GPU on your laptop.**

## How it works

```
Your laptop (no GPU)        ↔  HTTPS / Cloudflare Tunnel  ↔   Free Kaggle notebook (P100/T4)
Streamlit + SQLite + 200 MB                                   ComfyUI + SDXL + watercolor LoRA + ControlNet
```

## Quick start

```bash
# 1. Install locally
pipx install aquarender                # or:  uv tool install aquarender

# 2. Verify setup
aquarender doctor

# 3. Open Kaggle, run notebooks/aquarender_kaggle.ipynb
#    (Settings → GPU P100 + Internet On + Run All)
#    Wait ~5 min for the printed `https://*.trycloudflare.com` URL.

# 4. Start the local app
aquarender start                       # http://localhost:8501

# 5. Paste the URL in the Connect tab → Generate
```

## Repo layout

| Dir | What lives here |
|-----|-----------------|
| `aquarender/ui/` | Streamlit pages (UI only — never touches HTTP or DB directly) |
| `aquarender/core/` | Pure Python: orchestration, presets, preprocessing, metadata |
| `aquarender/engine/` | Remote ComfyUI client, tunnel monitor, keepalive, workflow builder |
| `aquarender/db/` | SQLAlchemy models, repository pattern, Alembic migrations |
| `aquarender/presets/` | JSON preset files (built-in) |
| `workflows/` | The single ComfyUI workflow template (`img2img_controlnet_lora.json`) |
| `notebooks/` | The Kaggle engine notebook |
| `docs/` | PRD, ARCHITECTURE, API, DATABASE, PROMPT |

## Development

```bash
uv venv --python 3.11 .venv
uv pip install -e ".[dev]"
uv run aquarender migrate               # apply schema + seed builtins
uv run pytest tests/unit                # fast suite, no Kaggle needed
uv run ruff check --fix .
uv run mypy aquarender
```

End-to-end suite needs a live tunnel:

```bash
AQUARENDER_E2E_TUNNEL_URL=https://abc-def.trycloudflare.com uv run pytest tests/e2e
```

See [`CLAUDE.md`](./CLAUDE.md) for conventions and [`docs/PRD.md`](./docs/PRD.md) for the why.

## License

MIT.
