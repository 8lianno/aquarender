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
- **Cell 2** (setup): GPU check → clone ComfyUI → download FLUX.1-dev-fp8 (17 GB) + the Aquarell watercolor LoRA (171 MB) with `tqdm` progress bars → start ComfyUI on `127.0.0.1:8188` → wait until ready. ~7 min on first run, ~30 s on re-runs (files cached on the session disk).
- **Cell 3** (UI): `ipywidgets`-driven controls.
  - Pick **URL** or **Upload** for the input image.
  - Pick a **Style** (Soft Watercolor, Ink + Watercolor, Children's Book, Product Watercolor) and a **Strength** (Light / Medium / Strong — controls how loosely the model reinterprets the source).
  - Optionally set a **Seed** (0 = random).
  - Click **🎨 Generate watercolor** — the progress bar fills, the result renders inline, and a **📥 Download PNG** button appears.

Generations run ~30 s each on warm P100, ~50 s on T4. The output overwrites `/kaggle/working/aquarender_output.png` on each click; the download button hands you a versioned filename `aquarender_seed<N>.png`.

### Model lineage (why these defaults)

We iterated through three stacks. Saved here for honesty about what works:

1. **SDXL + watercolor LoRA + lineart ControlNet.** Photo-faithful but produced traced "stippled" output — every skin pore the lineart preprocessor caught became a dot. ([commit history](https://github.com/8lianno/aquarender/commits/main/notebooks/aquarender_kaggle.ipynb))
2. **FLUX.1-schnell, no LoRA, no ControlNet.** Cleaner output, dramatically simpler workflow — but schnell at 4 distilled steps produces "smooth digital illustration", not loose painterly watercolor.
3. **FLUX.1-dev + Aquarell V2 LoRA. ← current.** dev's full 20-step sampling + the LoRA's `AQUACOLTOK` style finally gives the loose watercolor washes, soft pastel hues, paper texture, and color bleeds we want.

Trade-off: dev's license is non-commercial. Outputs are yours for personal use. For commercial, swap cell 2 back to `Comfy-Org/flux1-schnell` (Apache 2.0) and drop steps to 4.

---

## Limits

- **9-hour hard cap** per Kaggle session.
- **5-minute idle timeout** if nothing's running. The Generate button itself counts as activity, so casual use is fine.
- **30 GPU-hours/week** of free quota.

---

## `scripts/oneshot.sh`

Standalone bash that drives ComfyUI's HTTP API directly (curl + jq, no Python). Useful for shell automation outside a notebook — e.g. once cell 2 of the Kaggle notebook has booted ComfyUI, you can `bash scripts/oneshot.sh` from a Kaggle terminal cell with `INPUT_IMAGE=… PROMPT=…` env vars.

See the file header for full env-var docs.
