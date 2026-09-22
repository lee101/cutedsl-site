#!/usr/bin/env bash
set -euo pipefail

mkdir -p "${TMPDIR:-/tmp/cutedsl}" "${HF_HOME:-/models/hf}"

if [[ "${CUDA_DOCTOR_ON_START:-1}" == "1" ]]; then
  python3 /app/scripts/cuda_doctor.py --require-torch-cuda
fi

case "${CUTEDSL_MODE:-api}" in
  api)
    exec python3 -u server.py
    ;;
  runpod-worker)
    exec python3 -u runpod_lora_worker.py
    ;;
  *)
    exec "$@"
    ;;
esac
