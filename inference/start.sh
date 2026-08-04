#!/bin/bash
[ -f "$HOME/.secretbashrc" ] && . "$HOME/.secretbashrc"
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
. /nvme0n1-disk/code/cutedsl-site/inference/caption_backend_auth.sh
verify_caption_backend_auth || exit 1
if [ "${LOAD_ZIMAGE:-1}" = "1" ] && [[ "${DEVICE:-cuda}" == cuda* ]]; then
    /bin/bash /nvme0n1-disk/code/cutedsl-site/inference/wait_for_cuda.sh
fi
cd /nvme0n1-disk/code/cutedsl-site/inference
exec env \
    TMPDIR=/nvme0n1-disk/tmp \
    PYTHONPATH=/nvme0n1-disk/code/cutedsl \
    PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
    IMAGE_API_SECRET=cutedsl2024 \
    LOAD_CHRONOS=0 \
    PRELOAD_MODELS=1 \
    ENABLE_NVFP4=0 \
    ZIMAGE_USE_CUTE=1 \
    ZIMAGE_CPU_OFFLOAD="${ZIMAGE_CPU_OFFLOAD:-1}" \
    ZIMAGE_TEXT_ENCODER_DEVICE="${ZIMAGE_TEXT_ENCODER_DEVICE:-cpu}" \
    ZIMAGE_DIRECT_DEVICE_MAP="${ZIMAGE_DIRECT_DEVICE_MAP:-0}" \
    ZIMAGE_COMPILE_MODE="${ZIMAGE_COMPILE_MODE:-}" \
    ZIMAGE_DEFAULT_STEPS=8 \
    ZIMAGE_FAST_LORA_CPU_OFFLOAD=1 \
    LATENT_TELEPORT_ENABLED=1 \
    LATENT_TELEPORT_CACHE_DIR=/nvme0n1-disk/tmp/latentteleport-cache \
    LATENT_TELEPORT_START_STEP=7 \
    LATENT_TELEPORT_MAX_ENTRIES_PER_RESOLUTION="${LATENT_TELEPORT_MAX_ENTRIES_PER_RESOLUTION:-2048}" \
    LATENT_TELEPORT_MAX_GIB_PER_RESOLUTION="${LATENT_TELEPORT_MAX_GIB_PER_RESOLUTION:-8}" \
    LATENT_TELEPORT_PRUNE_INTERVAL_SECONDS="${LATENT_TELEPORT_PRUNE_INTERVAL_SECONDS:-60}" \
    MAX_GPU_CONCURRENT=1 \
    HF_HOME=/nvme0n1-disk/hf_cache \
    MODEL_IDLE_TIMEOUT=1800 \
    CUTEZIMAGE_CPU_OFFLOAD=1 \
    CUTEZIMAGE_ENABLE_ATTENTION_SLICING=0 \
    CUTEZIMAGE_ENABLE_VAE_SLICING=0 \
    TG_BACKEND_URL="http://localhost:9080" \
    TG_API_KEY="${TG_API_KEY:-}" \
    CAPTION_BACKEND_API_KEY="${CAPTION_BACKEND_API_KEY:-${NETWRCK_IMAGE_CAPTION_SECRET:-${TG_API_KEY:-}}}" \
    CHRONOS_MODEL_PATH="amazon/chronos-2" \
    /nvme0n1-disk/code/.venv/bin/python -u server.py
