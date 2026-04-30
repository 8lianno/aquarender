# Notebooks

## `aquarender_kaggle.ipynb` — the only path you need

Three cells. **Run All** once, then click **Generate** as many times as you like. Auto-detects Kaggle vs Colab and uses the right paths (`/kaggle/working/` or `/content/`).

### On Kaggle

1. [kaggle.com](https://www.kaggle.com) → **New Notebook → File → Import Notebook**. Paste:
   ```
   https://github.com/8lianno/aquarender/blob/main/notebooks/aquarender_kaggle.ipynb
   ```
2. Right pane → **Settings**:
   - **Accelerator: GPU P100** (T4 also works)
   - **Internet: On** (needed to fetch SDXL + LoRA + ControlNet)
3. **Run All**.

### On Google Colab

1. Open https://colab.research.google.com/github/8lianno/aquarender/blob/main/notebooks/aquarender_kaggle.ipynb in your browser. Colab opens it directly from GitHub.
2. Top menu → **Runtime → Change runtime type** → Hardware accelerator: **T4 GPU** (or higher if your account has it). Internet is on by default.
3. **Runtime → Run all** (or `Ctrl/Cmd + F9`).

Same notebook, same UI, same generation. Cell 2 detects which environment it's in and points its scratch paths at the right disk.

### What happens

- **Cell 1** (markdown): the same instructions you're reading.
- **Cell 2** (setup): GPU check → clone ComfyUI → download the FLUX.1-schnell-fp8 checkpoint (17 GB, single bundled file) with a `tqdm` progress bar → start ComfyUI on `127.0.0.1:8188` → wait until ready. ~6 min on first run, ~30 s on re-runs (the checkpoint is cached on the session disk).
- **Cell 3** (UI): `ipywidgets`-driven controls.
  - Pick **URL** or **Upload** for the input image.
  - Pick a **Style** (Soft Watercolor, Ink + Watercolor, Children's Book, Product Watercolor) and a **Strength** (Light / Medium / Strong — controls how loosely the model reinterprets the source).
  - Optionally set a **Seed** (0 = random).
  - Click **🎨 Generate watercolor** — the progress bar fills, the result renders inline, and a **📥 Download PNG** button appears.

Generations run ~6 s each on warm P100, ~10 s on T4 (4-step distilled schnell). The output overwrites `/kaggle/working/aquarender_output.png` on each click; the download button hands you a versioned filename `aquarender_seed<N>.png`.

### Why FLUX

We started with SDXL + a watercolor LoRA + a lineart ControlNet — the SDXL stack was producing photo-faithful traced output (skin pores stippled into the result), not loose painterly watercolor. FLUX.1-schnell handles painterly aesthetics in its base model with no LoRA assistance, so the workflow simplifies to a single img2img pass and the output is dramatically more painterly. We pay for it with a 17 GB download (vs 13 GB) and ~12 GB VRAM during sampling.

---

## Limits

- **9-hour hard cap** per Kaggle session.
- **5-minute idle timeout** if nothing's running. The Generate button itself counts as activity, so casual use is fine.
- **30 GPU-hours/week** of free quota.

---

## `scripts/oneshot.sh`

Standalone bash that drives ComfyUI's HTTP API directly (curl + jq, no Python). Useful for shell automation outside a notebook — e.g. once cell 2 of the Kaggle notebook has booted ComfyUI, you can `bash scripts/oneshot.sh` from a Kaggle terminal cell with `INPUT_IMAGE=… PROMPT=…` env vars.

See the file header for full env-var docs.
