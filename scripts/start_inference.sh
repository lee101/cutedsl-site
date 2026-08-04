#!/bin/bash
# Start the CuteDSL inference server with Z-Image model
set -e

cd /nvme0n1-disk/code/cutedsl-site/inference

export HF_HOME=/nvme0n1-disk/hf_cache
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"
export LOAD_ZIMAGE="${LOAD_ZIMAGE:-1}"
export LOAD_CHRONOS="${LOAD_CHRONOS:-0}"
export PRELOAD_MODELS="${PRELOAD_MODELS:-0}"
export ENABLE_NVFP4="${ENABLE_NVFP4:-0}"
export ZIMAGE_CPU_OFFLOAD="${ZIMAGE_CPU_OFFLOAD:-auto}"
export ZIMAGE_TEXT_ENCODER_DEVICE="${ZIMAGE_TEXT_ENCODER_DEVICE:-cpu}"
export ZIMAGE_NO_OFFLOAD_MIN_FREE_MB="${ZIMAGE_NO_OFFLOAD_MIN_FREE_MB:-24576}"
export ZIMAGE_SKIP_WARMUP="${ZIMAGE_SKIP_WARMUP:-1}"
export ZIMAGE_COMPILE_MODE="${ZIMAGE_COMPILE_MODE:-}"
export ZIMAGE_DEFAULT_STEPS="${ZIMAGE_DEFAULT_STEPS:-8}"
export ZIMAGE_PROMPT_CACHE_SIZE="${ZIMAGE_PROMPT_CACHE_SIZE:-64}"
export MAX_GPU_CONCURRENT="${MAX_GPU_CONCURRENT:-1}"
export MODEL_IDLE_TIMEOUT="${MODEL_IDLE_TIMEOUT:-90}"
export BATCH_WINDOW_MS="${BATCH_WINDOW_MS:-25}"

if [ "$LOAD_ZIMAGE" = "1" ] && [[ "${DEVICE:-cuda}" == cuda* ]]; then
    /bin/bash /nvme0n1-disk/code/cutedsl-site/inference/wait_for_cuda.sh
fi

echo "Starting CuteDSL inference server..."
echo "GPU: $(nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader 2>/dev/null)"
echo "Low-GPU mode: PRELOAD_MODELS=$PRELOAD_MODELS ENABLE_NVFP4=$ENABLE_NVFP4 ZIMAGE_CPU_OFFLOAD=$ZIMAGE_CPU_OFFLOAD MAX_GPU_CONCURRENT=$MAX_GPU_CONCURRENT MODEL_IDLE_TIMEOUT=$MODEL_IDLE_TIMEOUT"

exec /nvme0n1-disk/code/.venv/bin/python -u server.py
