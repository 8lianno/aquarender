# Notebooks

Kaggle-hosted ComfyUI engines that AquaRender drives over a Cloudflare Tunnel,
plus a one-shot variant for quick demos.

## Importing into Kaggle

On [kaggle.com](https://www.kaggle.com): **New Notebook → File → Import Notebook**, then either:

- paste the GitHub URL of the `.ipynb` you want, e.g.
  `https://github.com/8lianno/aquarender/blob/main/notebooks/aquarender_kaggle.ipynb`, or
- download the file first ([raw link](https://raw.githubusercontent.com/8lianno/aquarender/main/notebooks/aquarender_kaggle.ipynb))
  and **Upload file**.

Then in the right pane → **Settings**:

- Accelerator: **GPU P100** (T4 also works)
- Internet: **On** (needed to fetch SDXL + LoRA + ControlNet from HuggingFace)

Click **Run All**.

---

## `aquarender_kaggle.ipynb` — full engine

Boots ComfyUI + Cloudflare Tunnel and prints a public URL you paste into the
local AquaRender Streamlit app's **Connect** tab. This is the path for normal
single-image and batch use.

1. Run All. First boot takes ~5 min downloading ~13 GB of models.
2. Watch the last cell — when it prints `✅ AquaRender engine ready` it follows
   with `https://*.trycloudflare.com`. Copy that.
3. Switch to AquaRender on your laptop, paste in **Connect**, click **Connect**.
4. Generate.

### Custom LoRAs

Upload your `.safetensors` to a Kaggle Dataset, then attach the dataset to this
notebook (right pane → Add Data). Cell 6 symlinks any `*.safetensors` it finds
under `/kaggle/input/` into ComfyUI's LoRA folder. After re-running cell 6 (or
restarting the notebook) your LoRA shows up in AquaRender's available list and
in the **Custom LoRA** field on Single / Batch pages.

### Session limits

- 9-hour hard cap per session — long batches must be split.
- 5-minute idle timeout — AquaRender's `KeepaliveTask` pings every 4 min during
  batches to defeat this.
- 30 GPU-hours / week of free quota.

If the tunnel drops mid-batch, AquaRender pauses the batch with a checkpoint.
Restart the notebook, copy the new URL, paste in **Connect**, click **Resume**
on the Batch tab — already-completed images aren't regenerated.

---

## `aquarender_oneshot.ipynb` — one-shot demo

Self-contained: edit `PROMPT` and `INPUT_IMAGE_URL` at the top, **Run All**, and
the last cell shows the watercolor inline. **No Cloudflare Tunnel, no local app
required** — generation happens entirely on the Kaggle box.

The actual generation cell writes a small `oneshot.sh` to disk and runs it —
pure `curl` + `jq` against ComfyUI's HTTP API, no Python deps. Same script
ships at [`scripts/oneshot.sh`](../scripts/oneshot.sh) for reuse outside a
notebook (e.g. shell loops, smoke tests, CI).

When to use which:

| You want… | Notebook |
|-----------|----------|
| Drop a folder, get a folder back, with a UI | `aquarender_kaggle.ipynb` + local Streamlit app |
| Generate one image right now, just to see it work | `aquarender_oneshot.ipynb` |
| Smoke-test a new LoRA without setting up the local app | `aquarender_oneshot.ipynb` |
| Drive ComfyUI from your own scripts on Kaggle | `scripts/oneshot.sh` after running cells 1–5 of either notebook |
