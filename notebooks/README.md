# Notebooks

Kaggle-hosted ComfyUI engines that AquaRender drives over a Cloudflare Tunnel.

## `aquarender_kaggle.ipynb` (primary)

1. Open https://kaggle.com → New Notebook → File → Import → paste the URL of this `.ipynb` (or upload it).
2. Settings → **Accelerator: GPU P100** (or T4 if P100 isn't available).
3. Settings → **Internet: On** (required to download models from HuggingFace).
4. Click **Run All**. First run takes ~5 min to download SDXL + LoRA + ControlNets (~13 GB).
5. Watch the last cell — it prints `✅ AquaRender engine ready` followed by a `https://*.trycloudflare.com` URL.
6. Copy that URL, switch back to AquaRender on your laptop, paste it in the **Connect** tab, click **Connect**.
7. Generate.

### Custom LoRAs

Upload your `.safetensors` to a Kaggle Dataset, then attach the dataset to this notebook (right pane → Add Data). Cell 6 symlinks any `*.safetensors` it finds under `/kaggle/input/` into ComfyUI's LoRA folder. After re-running cell 6 (or restarting the notebook), your LoRA shows up in AquaRender's "Available LoRAs" list and in the Custom LoRA field on the Single/Batch pages.

### Session limits

- 9 hours hard cap per session — long batches must be split.
- 5 minutes idle timeout — AquaRender's `KeepaliveTask` pings the engine every 4 minutes during batches to defeat this.
- 30 GPU-hours/week of free quota.

If the tunnel drops mid-batch, AquaRender pauses the batch. Restart the notebook, copy the new URL, paste in **Connect**, then click **Resume** on the Batch tab.
