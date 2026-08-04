#!/bin/bash
# Keep the long-lived Python process from caching a boot-time CUDA failure.
set -u

timeout_seconds="${CUDA_STARTUP_WAIT_SECONDS:-120}"
poll_seconds="${CUDA_STARTUP_POLL_SECONDS:-2}"
python_bin="${CUDA_PROBE_PYTHON:-/nvme0n1-disk/code/.venv/bin/python}"
deadline=$((SECONDS + timeout_seconds))

while true; do
    if nvidia-smi --query-gpu=name --format=csv,noheader >/dev/null 2>&1 \
        && "$python_bin" -c 'import torch; assert torch.cuda.is_available(); torch.cuda.mem_get_info()' >/dev/null 2>&1; then
        exit 0
    fi
    if (( SECONDS >= deadline )); then
        echo "CUDA did not become usable within ${timeout_seconds}s" >&2
        exit 1
    fi
    sleep "$poll_seconds"
done
