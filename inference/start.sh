#!/bin/bash
cd /nvme0n1-disk/code/cutedsl-site/inference
exec env \
    TMPDIR=/nvme0n1-disk/tmp \
    PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
    IMAGE_API_SECRET=cutedsl2024 \
    LOAD_CHRONOS=0 \
    PRELOAD_MODELS=1 \
    ZIMAGE_CPU_OFFLOAD=0 \
    ZIMAGE_COMPILE_MODE="" \
    ZIMAGE_DEFAULT_STEPS=4 \
    HF_HOME=/nvme0n1-disk/hf_cache \
    MODEL_IDLE_TIMEOUT=86400 \
    /nvme0n1-disk/code/.venv/bin/python -u server.py
