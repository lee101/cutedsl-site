#!/bin/bash
cd /nvme0n1-disk/code/cutedsl-site/inference
exec env \
    TMPDIR=/nvme0n1-disk/tmp \
    PYTHONPATH=/nvme0n1-disk/code/cutedsl \
    PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
    IMAGE_API_SECRET=cutedsl2024 \
    LOAD_CHRONOS=0 \
    PRELOAD_MODELS=1 \
    ENABLE_NVFP4=0 \
    ZIMAGE_USE_CUTE=0 \
    ZIMAGE_CPU_OFFLOAD=0 \
    ZIMAGE_COMPILE_MODE="" \
    ZIMAGE_DEFAULT_STEPS=8 \
    LATENT_TELEPORT_ENABLED=1 \
    LATENT_TELEPORT_CACHE_DIR=/nvme0n1-disk/tmp/latentteleport-cache \
    LATENT_TELEPORT_START_STEP=7 \
    MAX_GPU_CONCURRENT=1 \
    HF_HOME=/nvme0n1-disk/hf_cache \
    MODEL_IDLE_TIMEOUT=1800 \
    CUTEZIMAGE_CPU_OFFLOAD=0 \
    CUTEZIMAGE_ENABLE_ATTENTION_SLICING=0 \
    CUTEZIMAGE_ENABLE_VAE_SLICING=0 \
    TG_BACKEND_URL="http://localhost:9080" \
    TG_API_KEY="7C2JbFYUdEAGXSbO2fb0ATl0tacgEAKu" \
    CHRONOS_MODEL_PATH="amazon/chronos-2" \
    /nvme0n1-disk/code/.venv/bin/python -u server.py
