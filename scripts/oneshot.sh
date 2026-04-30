#!/usr/bin/env bash
# One-shot watercolor generation against a running ComfyUI server.
#
# Run this on the Kaggle box (or anywhere ComfyUI is reachable). Driven entirely
# by env vars; pure curl + jq, no Python deps. Useful for a smoke test, a quick
# demo, or batch jobs from a shell loop without spinning up the local Streamlit
# UI.
#
# Required: an already-running ComfyUI with SDXL + watercolor LoRA + ControlNet
# loaded (the notebooks/aquarender_kaggle.ipynb cells 2–9 do this).
#
# Required env vars:
#   INPUT_IMAGE   path to a local image readable by ComfyUI's /upload/image
#
# Optional env vars (defaults shown):
#   COMFY_URL     http://127.0.0.1:8188
#   OUTPUT        /tmp/aquarender_oneshot.png
#   PROMPT        "watercolor painting, soft brushstrokes, paper texture, gentle color bleed, hand-painted"
#   NEGATIVE      "photo, photograph, photorealistic, 3d render, harsh edges, oversaturated, low quality, blurry"
#   CHECKPOINT    sd_xl_base_1.0.safetensors
#   LORA_NAME     watercolor_style_lora_sdxl.safetensors
#   LORA_WEIGHT   0.8
#   CN_NAME       diffusers_xl_lineart_full.safetensors
#   CN_STRENGTH   0.85
#   STEPS         28
#   CFG           5.5
#   DENOISE       0.5
#   SAMPLER       dpmpp_2m_sde
#   SCHEDULER     karras
#   SEED          (random)
#   POLL_INTERVAL 1
#   TIMEOUT_S     180
#
# Exit codes: 0 = success, 1 = bad config, 2 = upload/queue failed,
# 3 = generation timeout, 4 = fetch failed.

set -euo pipefail

COMFY_URL="${COMFY_URL:-http://127.0.0.1:8188}"
OUTPUT="${OUTPUT:-/tmp/aquarender_oneshot.png}"
PROMPT="${PROMPT:-watercolor painting, soft brushstrokes, paper texture, gentle color bleed, hand-painted}"
NEGATIVE="${NEGATIVE:-photo, photograph, photorealistic, 3d render, harsh edges, oversaturated, low quality, blurry}"
CHECKPOINT="${CHECKPOINT:-sd_xl_base_1.0.safetensors}"
LORA_NAME="${LORA_NAME:-watercolor_style_lora_sdxl.safetensors}"
LORA_WEIGHT="${LORA_WEIGHT:-0.8}"
CN_NAME="${CN_NAME:-diffusers_xl_lineart_full.safetensors}"
CN_STRENGTH="${CN_STRENGTH:-0.85}"
STEPS="${STEPS:-28}"
CFG="${CFG:-5.5}"
DENOISE="${DENOISE:-0.5}"
SAMPLER="${SAMPLER:-dpmpp_2m_sde}"
SCHEDULER="${SCHEDULER:-karras}"
SEED="${SEED:-$((RANDOM * RANDOM))}"
POLL_INTERVAL="${POLL_INTERVAL:-1}"
TIMEOUT_S="${TIMEOUT_S:-180}"
CLIENT_ID="aquarender-oneshot-$$"

if [[ -z "${INPUT_IMAGE:-}" ]]; then
  echo "✗ INPUT_IMAGE is required (path to a local image)" >&2
  exit 1
fi
if [[ ! -f "$INPUT_IMAGE" ]]; then
  echo "✗ INPUT_IMAGE not readable: $INPUT_IMAGE" >&2
  exit 1
fi
for dep in curl jq; do
  if ! command -v "$dep" >/dev/null 2>&1; then
    echo "✗ missing dependency: $dep" >&2
    exit 1
  fi
done

echo "→ engine: $COMFY_URL"
echo "→ input:  $INPUT_IMAGE"
echo "→ seed:   $SEED"

# 1. Verify ComfyUI is reachable
if ! curl -sf "${COMFY_URL}/system_stats" >/dev/null; then
  echo "✗ ComfyUI not reachable at ${COMFY_URL}" >&2
  exit 2
fi

# 2. Upload input image
echo "→ uploading…"
UPLOAD_JSON=$(curl -sf -X POST \
  -F "image=@${INPUT_IMAGE}" \
  -F "type=input" \
  -F "overwrite=true" \
  "${COMFY_URL}/upload/image") || { echo "✗ upload failed" >&2; exit 2; }

IMAGE_NAME=$(echo "$UPLOAD_JSON" | jq -r '.name')
[[ -n "$IMAGE_NAME" && "$IMAGE_NAME" != "null" ]] || { echo "✗ upload returned no name: $UPLOAD_JSON" >&2; exit 2; }

# 3. Build workflow JSON via jq (handles all string escaping correctly)
WORKFLOW=$(jq -n \
  --arg ckpt "$CHECKPOINT" \
  --arg lora "$LORA_NAME" \
  --argjson lora_w "$LORA_WEIGHT" \
  --arg cn "$CN_NAME" \
  --argjson cn_s "$CN_STRENGTH" \
  --arg image "$IMAGE_NAME" \
  --arg pos "$PROMPT" \
  --arg neg "$NEGATIVE" \
  --argjson seed "$SEED" \
  --argjson steps "$STEPS" \
  --argjson cfg "$CFG" \
  --argjson denoise "$DENOISE" \
  --arg sampler "$SAMPLER" \
  --arg scheduler "$SCHEDULER" \
  --arg client_id "$CLIENT_ID" \
  '{
    "prompt": {
      "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": $ckpt}},
      "2": {"class_type": "LoraLoader", "inputs": {"lora_name": $lora, "strength_model": $lora_w, "strength_clip": $lora_w, "model": ["1", 0], "clip": ["1", 1]}},
      "3": {"class_type": "CLIPTextEncode", "inputs": {"text": $pos, "clip": ["2", 1]}},
      "4": {"class_type": "CLIPTextEncode", "inputs": {"text": $neg, "clip": ["2", 1]}},
      "5": {"class_type": "LoadImage", "inputs": {"image": $image}},
      "6": {"class_type": "VAEEncode", "inputs": {"pixels": ["5", 0], "vae": ["1", 2]}},
      "7": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": $cn}},
      "10": {"class_type": "ControlNetApplyAdvanced", "inputs": {"positive": ["3", 0], "negative": ["4", 0], "control_net": ["7", 0], "image": ["5", 0], "strength": $cn_s, "start_percent": 0.0, "end_percent": 1.0}},
      "8": {"class_type": "KSampler", "inputs": {"model": ["2", 0], "positive": ["10", 0], "negative": ["10", 1], "latent_image": ["6", 0], "seed": $seed, "steps": $steps, "cfg": $cfg, "sampler_name": $sampler, "scheduler": $scheduler, "denoise": $denoise}},
      "11": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["1", 2]}},
      "9": {"class_type": "SaveImage", "inputs": {"images": ["11", 0], "filename_prefix": "aquarender_oneshot"}}
    },
    "client_id": $client_id
  }')

echo "→ submitting workflow…"
QUEUE_JSON=$(curl -sf -X POST -H 'Content-Type: application/json' \
  -d "$WORKFLOW" "${COMFY_URL}/prompt") || { echo "✗ /prompt rejected the workflow" >&2; exit 2; }

NODE_ERRORS=$(echo "$QUEUE_JSON" | jq -c '.node_errors // {}')
if [[ "$NODE_ERRORS" != "{}" ]]; then
  echo "✗ ComfyUI node errors: $NODE_ERRORS" >&2
  exit 2
fi
PROMPT_ID=$(echo "$QUEUE_JSON" | jq -r '.prompt_id')
echo "→ prompt_id: $PROMPT_ID"

# 4. Poll /history until done (or timeout)
DEADLINE=$(( $(date +%s) + TIMEOUT_S ))
while :; do
  if (( $(date +%s) > DEADLINE )); then
    echo "✗ generation exceeded ${TIMEOUT_S}s" >&2
    curl -sf -X POST "${COMFY_URL}/interrupt" >/dev/null || true
    exit 3
  fi
  HIST_JSON=$(curl -sf "${COMFY_URL}/history/${PROMPT_ID}" || true)
  COMPLETED=$(echo "$HIST_JSON" | jq -r --arg id "$PROMPT_ID" '.[$id].status.completed // false')
  if [[ "$COMPLETED" == "true" ]]; then
    STATUS=$(echo "$HIST_JSON" | jq -r --arg id "$PROMPT_ID" '.[$id].status.status_str // ""')
    if [[ "$STATUS" == "error" ]]; then
      echo "✗ ComfyUI reported an execution error" >&2
      echo "$HIST_JSON" | jq -r --arg id "$PROMPT_ID" '.[$id].status.messages // []' >&2
      exit 2
    fi
    break
  fi
  sleep "$POLL_INTERVAL"
done
echo "→ generation complete"

# 5. Fetch output bytes
OUT_FILENAME=$(echo "$HIST_JSON" | jq -r --arg id "$PROMPT_ID" '.[$id].outputs."9".images[0].filename')
OUT_SUBFOLDER=$(echo "$HIST_JSON" | jq -r --arg id "$PROMPT_ID" '.[$id].outputs."9".images[0].subfolder // ""')
OUT_TYPE=$(echo "$HIST_JSON" | jq -r --arg id "$PROMPT_ID" '.[$id].outputs."9".images[0].type // "output"')

if [[ -z "$OUT_FILENAME" || "$OUT_FILENAME" == "null" ]]; then
  echo "✗ no output filename in /history response" >&2
  exit 4
fi

curl -sfG "${COMFY_URL}/view" \
  --data-urlencode "filename=${OUT_FILENAME}" \
  --data-urlencode "subfolder=${OUT_SUBFOLDER}" \
  --data-urlencode "type=${OUT_TYPE}" \
  -o "$OUTPUT" || { echo "✗ /view fetch failed" >&2; exit 4; }

echo "→ saved → $OUTPUT (seed=$SEED)"
