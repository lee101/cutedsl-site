#!/bin/bash
# Start server fully detached from any parent process
[ -f $HOME/.secretbashrc ] && . $HOME/.secretbashrc
credentials_file="${CUTEDSL_INFERENCE_ENV_FILE:-/etc/netwrck-image-caption.env}"
if [ -r "$credentials_file" ]; then
    set -a
    . "$credentials_file"
    set +a
fi
if [ -z "${CAPTION_BACKEND_API_KEY:-}" ] && command -v systemctl >/dev/null 2>&1; then
    for setting in $(systemctl show text-generator-inference.service --property=Environment --value 2>/dev/null); do
        case "$setting" in
            NETWRCK_IMAGE_CAPTION_SECRET=*)
                CAPTION_BACKEND_API_KEY=${setting#NETWRCK_IMAGE_CAPTION_SECRET=}
                export CAPTION_BACKEND_API_KEY
                break
                ;;
        esac
    done
fi
cd /nvme0n1-disk/code/cutedsl-site/inference

terminate_existing() {
    local pids
    pids=$(find_inference_server_pids)
    if [ -z "$pids" ]; then
        return
    fi

    echo "Stopping existing inference server PID(s): $pids"
    kill $pids 2>/dev/null || true
    for _ in $(seq 1 60); do
        local running=""
        local pid
        for pid in $pids; do
            kill -0 "$pid" 2>/dev/null && running="$running $pid"
        done
        if [ -z "$running" ]; then
            return
        fi
        sleep 1
    done

    if [ -n "$running" ]; then
        echo "Force stopping existing inference server PID(s):$running"
        kill -9 $running 2>/dev/null || true
    fi

    pids=$(find_inference_server_pids)
    if [ -n "$pids" ]; then
        echo "Unable to stop existing inference server PID(s): $pids" >&2
        ps -fp $pids >&2 || true
        return 1
    fi

    pids=$(find_ambiguous_python_server_pids)
    if [ -n "$pids" ]; then
        echo "Refusing to start with ambiguous python server.py PID(s) still running: $pids" >&2
        ps -fp $pids >&2 || true
        return 1
    fi
}

find_inference_server_pids() {
    local pid cwd cmd port
    for proc in /proc/[0-9]*; do
        pid=${proc##*/}
        [ "$pid" = "$$" ] && continue
        cmd=$(tr '\0' ' ' 2>/dev/null < "$proc/cmdline" || true)
        case "$cmd" in
            *"python"*server.py*)
                cwd=$(readlink "$proc/cwd" 2>/dev/null || true)
                if [ "$cwd" = "/nvme0n1-disk/code/cutedsl-site/inference" ]; then
                    port=$(tr '\0' '\n' 2>/dev/null < "$proc/environ" | awk -F= '$1 == "INFERENCE_PORT" {print $2; exit}')
                    if [ -z "$port" ] || [ "$port" = "8100" ]; then
                        printf '%s\n' "$pid"
                    fi
                fi
                ;;
        esac
    done
}

find_ambiguous_python_server_pids() {
    local pid cwd cmd
    for proc in /proc/[0-9]*; do
        pid=${proc##*/}
        [ "$pid" = "$$" ] && continue
        cmd=$(tr '\0' ' ' 2>/dev/null < "$proc/cmdline" || true)
        if [ "$cmd" = "python server.py " ] || [ "$cmd" = "python server.py" ]; then
            cwd=$(readlink "$proc/cwd" 2>/dev/null || true)
            [ "$cwd" = "/nvme0n1-disk/code/cutedsl-site/inference" ] || printf '%s\n' "$pid"
        fi
    done
}

terminate_existing || exit 1

# Use setsid + nohup + disown to fully detach
setsid nohup env \
    TMPDIR=/nvme0n1-disk/tmp \
    PYTHONPATH=/nvme0n1-disk/code/cutedsl \
    PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
    IMAGE_API_SECRET=cutedsl2024 \
    IMAGE_API_SECRETS="cutedsl2024,${NETWRCK_API_KEY:-}" \
    LOAD_CHRONOS="${LOAD_CHRONOS:-0}" \
    PRELOAD_MODELS="${PRELOAD_MODELS:-1}" \
    ENABLE_NVFP4="${ENABLE_NVFP4:-0}" \
    ZIMAGE_USE_CUTE="${ZIMAGE_USE_CUTE:-0}" \
    ZIMAGE_CPU_OFFLOAD="${ZIMAGE_CPU_OFFLOAD:-auto}" \
    ZIMAGE_NO_OFFLOAD_MIN_FREE_MB="${ZIMAGE_NO_OFFLOAD_MIN_FREE_MB:-24576}" \
    ZIMAGE_DIRECT_DEVICE_MAP="${ZIMAGE_DIRECT_DEVICE_MAP:-1}" \
    ZIMAGE_EARLY_EXIT="${ZIMAGE_EARLY_EXIT:-0.12}" \
    ZIMAGE_EARLY_EXIT_MIN_STEPS="${ZIMAGE_EARLY_EXIT_MIN_STEPS:-5}" \
    ZIMAGE_EARLY_EXIT_CONSECUTIVE="${ZIMAGE_EARLY_EXIT_CONSECUTIVE:-2}" \
    ZIMAGE_SKIP_NOOP_STEPS="${ZIMAGE_SKIP_NOOP_STEPS:-1}" \
    DX0_LOG="${DX0_LOG:-1}" \
    ZIMAGE_COMPILE_MODE="${ZIMAGE_COMPILE_MODE:-}" \
    ZIMAGE_SKIP_WARMUP="${ZIMAGE_SKIP_WARMUP:-1}" \
    ZIMAGE_DEFAULT_STEPS=8 \
    ZIMAGE_FAST_LORA_CPU_OFFLOAD=1 \
    LATENT_TELEPORT_ENABLED=1 \
    LATENT_TELEPORT_CACHE_DIR=/nvme0n1-disk/tmp/latentteleport-cache \
    LATENT_TELEPORT_START_STEP=7 \
    ZIMAGE_PROMPT_CACHE_SIZE="${ZIMAGE_PROMPT_CACHE_SIZE:-64}" \
    MAX_GPU_CONCURRENT=1 \
    LOW_PRIORITY_IDLE_SECONDS=5.0 \
    HF_HOME=/nvme0n1-disk/hf_cache \
    CHRONOS_MODEL_PATH="${CHRONOS_MODEL_PATH:-amazon/chronos-2}" \
    MODEL_IDLE_TIMEOUT=1800 \
    CUTEZIMAGE_CPU_OFFLOAD=1 \
    CUTEZIMAGE_SEQUENTIAL_CPU_OFFLOAD="${CUTEZIMAGE_SEQUENTIAL_CPU_OFFLOAD:-0}" \
    CUTEZIMAGE_ENABLE_ATTENTION_SLICING=0 \
    CUTEZIMAGE_ENABLE_VAE_SLICING=0 \
    TG_BACKEND_URL="http://localhost:9080" \
    TG_API_KEY="${TG_API_KEY:-}" \
    CAPTION_BACKEND_API_KEY="${CAPTION_BACKEND_API_KEY:-${NETWRCK_IMAGE_CAPTION_SECRET:-${TG_API_KEY:-}}}" \
    /nvme0n1-disk/code/.venv/bin/python -u server.py \
    > /nvme0n1-disk/tmp/server_persistent.log 2>&1 < /dev/null &
disown $!
echo "Started PID: $!"
