#!/bin/bash
# Start the CuteDSL inference server with Z-Image model
set -e

cd /nvme0n1-disk/code/cutedsl-site/inference

export HF_HOME=/nvme0n1-disk/hf_cache
export LOAD_ZIMAGE=1
export LOAD_CHRONOS=0
export PRELOAD_MODELS=1
export ZIMAGE_CPU_OFFLOAD=1
export ZIMAGE_COMPILE_MODE=""

echo "Starting CuteDSL inference server..."
echo "GPU: $(nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader 2>/dev/null)"

exec /nvme0n1-disk/code/.venv/bin/python -u server.py
