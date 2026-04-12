#!/bin/bash
# Start server fully detached from any parent process
cd /nvme0n1-disk/code/cutedsl-site/inference

# Use setsid + nohup + disown to fully detach
setsid nohup env \
    TMPDIR=/nvme0n1-disk/tmp \
    PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
    IMAGE_API_SECRET=cutedsl2024 \
    LOAD_CHRONOS=0 \
    PRELOAD_MODELS=0 \
    ZIMAGE_CPU_OFFLOAD=0 \
    ZIMAGE_COMPILE_MODE="" \
    ZIMAGE_DEFAULT_STEPS=4 \
    HF_HOME=/nvme0n1-disk/hf_cache \
    MODEL_IDLE_TIMEOUT=10 \
    TG_BACKEND_URL="http://localhost:9080" \
    TG_API_KEY="7C2JbFYUdEAGXSbO2fb0ATl0tacgEAKu" \
    /nvme0n1-disk/code/.venv/bin/python -u server.py \
    > /nvme0n1-disk/tmp/server_persistent.log 2>&1 < /dev/null &
disown $!
echo "Started PID: $!"
