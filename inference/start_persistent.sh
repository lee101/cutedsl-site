#!/bin/bash
# Start server fully detached from any parent process
cd /nvme0n1-disk/code/cutedsl-site/inference

terminate_existing() {
    local pids
    pids=$(pgrep -f "/nvme0n1-disk/code/.venv/bin/[p]ython -u server.py" || true)
    if [ -z "$pids" ]; then
        return
    fi

    echo "Stopping existing inference server PID(s): $pids"
    kill $pids 2>/dev/null || true
    for _ in $(seq 1 60); do
        if ! pgrep -f "/nvme0n1-disk/code/.venv/bin/[p]ython -u server.py" >/dev/null; then
            return
        fi
        sleep 1
    done

    pids=$(pgrep -f "/nvme0n1-disk/code/.venv/bin/[p]ython -u server.py" || true)
    if [ -n "$pids" ]; then
        echo "Force stopping existing inference server PID(s): $pids"
        kill -9 $pids 2>/dev/null || true
    fi
}

terminate_existing

# Use setsid + nohup + disown to fully detach
setsid nohup env \
    TMPDIR=/nvme0n1-disk/tmp \
    PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
    IMAGE_API_SECRET=cutedsl2024 \
    LOAD_CHRONOS="${LOAD_CHRONOS:-1}" \
    PRELOAD_MODELS=1 \
    ENABLE_NVFP4=0 \
    ZIMAGE_USE_CUTE=0 \
    ZIMAGE_CPU_OFFLOAD=0 \
    ZIMAGE_COMPILE_MODE="" \
    ZIMAGE_DEFAULT_STEPS=4 \
    LATENT_TELEPORT_ENABLED=1 \
    LATENT_TELEPORT_CACHE_DIR=/nvme0n1-disk/tmp/latentteleport-cache \
    LATENT_TELEPORT_START_STEP=2 \
    MAX_GPU_CONCURRENT=1 \
    LOW_PRIORITY_IDLE_SECONDS=5.0 \
    HF_HOME=/nvme0n1-disk/hf_cache \
    CHRONOS_MODEL_PATH="${CHRONOS_MODEL_PATH:-amazon/chronos-2}" \
    MODEL_IDLE_TIMEOUT=1800 \
    CUTEZIMAGE_CPU_OFFLOAD=0 \
    CUTEZIMAGE_ENABLE_ATTENTION_SLICING=0 \
    CUTEZIMAGE_ENABLE_VAE_SLICING=0 \
    TG_BACKEND_URL="http://localhost:9080" \
    TG_API_KEY="7C2JbFYUdEAGXSbO2fb0ATl0tacgEAKu" \
    /nvme0n1-disk/code/.venv/bin/python -u server.py \
    > /nvme0n1-disk/tmp/server_persistent.log 2>&1 < /dev/null &
disown $!
echo "Started PID: $!"
