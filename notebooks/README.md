# Notebooks

## `aquarender_kaggle.ipynb` — the only path you need

Three cells. **Run All** once, then click **Generate** as many times as you like.

### Setup

1. On [kaggle.com](https://www.kaggle.com): **New Notebook → File → Import Notebook**, paste this URL or upload the `.ipynb`:
   ```
   https://github.com/8lianno/aquarender/blob/main/notebooks/aquarender_kaggle.ipynb
   ```
2. Right pane → **Settings**:
   - **Accelerator: GPU P100** (T4 also works)
   - **Internet: On** (needed to fetch SDXL + LoRA + ControlNet)
3. Click **Run All**.

### What happens

- **Cell 1** (markdown): the same instructions you're reading.
- **Cell 2** (setup): GPU check → clone ComfyUI → download ~13 GB of models with `tqdm` progress bars → start ComfyUI on `127.0.0.1:8188` → wait until ready. ~5 min on first run, ~30 s on re-runs (model files are cached on the Kaggle session disk).
- **Cell 3** (UI): `ipywidgets`-driven controls.
  - Pick **URL** or **Upload** for the input image.
  - Pick a **Style** (Soft Watercolor, Ink + Watercolor, Children's Book, Product Watercolor) and a **Strength** (Light / Medium / Strong).
  - Optionally set a **Seed** (0 = random).
  - Click **🎨 Generate watercolor** — the progress bar fills, the result renders inline, and a **📥 Download PNG** button appears.

Generations run ~25 s each on warm P100. The output overwrites `/kaggle/working/aquarender_output.png` on each click; the download button hands you a versioned filename `aquarender_seed<N>.png`.

### Custom LoRAs

Attach a Kaggle Dataset that contains your `.safetensors` (right pane → **+ Add Data**). Cell 2 symlinks any `*.safetensors` it finds under `/kaggle/input/` into ComfyUI's `loras/` folder. Re-run cell 2 to pick up new datasets without restarting.

(Built-in custom-LoRA selection in the UI is a small follow-up — for now, edit the `LoraLoader.lora_name` line in the `_build_workflow` function in cell 3.)

---

## Limits

- **9-hour hard cap** per Kaggle session.
- **5-minute idle timeout** if nothing's running. The Generate button itself counts as activity, so casual use is fine.
- **30 GPU-hours/week** of free quota.

---

## `scripts/oneshot.sh`

Standalone bash that drives ComfyUI's HTTP API directly (curl + jq, no Python). Useful for shell automation outside a notebook — e.g. once cell 2 of the Kaggle notebook has booted ComfyUI, you can `bash scripts/oneshot.sh` from a Kaggle terminal cell with `INPUT_IMAGE=… PROMPT=…` env vars.

See the file header for full env-var docs.
