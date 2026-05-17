#!/usr/bin/env bash
set -euo pipefail

# Profile one local Z-Image API request with Nsight Systems.
# Usage:
#   scripts/nsight_zimage_api.sh "minecraft block dirt icon" [output_prefix]

PROMPT="${1:-minecraft block dirt menu zoomed in dirt block icon}"
OUT="${2:-/nvme0n1-disk/tmp/nsight-zimage-api-$(date -u +%Y%m%dT%H%M%SZ)}"
BASE_URL="${BASE_URL:-http://localhost:8100}"
SECRET="${IMAGE_API_SECRET:-cutedsl2024}"

if ! command -v nsys >/dev/null 2>&1; then
  echo "nsys not found in PATH" >&2
  exit 127
fi

nsys profile \
  --trace=cuda,nvtx,osrt \
  --sample=cpu \
  --force-overwrite=true \
  --output="${OUT}" \
  curl -sS -G "${BASE_URL}/create_and_upload_image" \
    --data-urlencode "prompt=${PROMPT}" \
    --data-urlencode "width=1024" \
    --data-urlencode "height=1024" \
    --data-urlencode "model=zimage-turbo" \
    --data-urlencode "auto_lora=false" \
    --data-urlencode "teleport=false" \
    --data-urlencode "perf=true" \
    --data-urlencode "secret=${SECRET}"

echo "Wrote ${OUT}.nsys-rep"
