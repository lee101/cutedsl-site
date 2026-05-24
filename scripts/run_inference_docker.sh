#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${CUTEDSL_INFERENCE_IMAGE:-cutedsl-inference:cuda12.8}"
NAME="${CUTEDSL_INFERENCE_CONTAINER:-cutedsl-inference}"
PORT="${INFERENCE_PORT:-8100}"
HF_HOME="${HF_HOME:-/nvme0n1-disk/hf_cache}"
TMPDIR_HOST="${TMPDIR_HOST:-/nvme0n1-disk/tmp}"

docker rm -f "$NAME" >/dev/null 2>&1 || true

exec docker run \
  --name "$NAME" \
  --gpus all \
  --restart unless-stopped \
  --ipc=host \
  --ulimit memlock=-1 \
  --ulimit stack=67108864 \
  -p "${PORT}:8100" \
  -v "${HF_HOME}:/models/hf" \
  -v "${TMPDIR_HOST}:/tmp/cutedsl" \
  --env-file "${ROOT}/.env" \
  -e INFERENCE_PORT=8100 \
  -e HF_HOME=/models/hf \
  -e TMPDIR=/tmp/cutedsl \
  -e DEVICE="${DEVICE:-cuda}" \
  -e DTYPE="${DTYPE:-bfloat16}" \
  -e LOAD_ZIMAGE="${LOAD_ZIMAGE:-1}" \
  -e LOAD_CHRONOS="${LOAD_CHRONOS:-1}" \
  -e PRELOAD_MODELS="${PRELOAD_MODELS:-0}" \
  -e MODEL_IDLE_TIMEOUT="${MODEL_IDLE_TIMEOUT:-300}" \
  "$IMAGE"
