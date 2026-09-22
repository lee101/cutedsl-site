#!/usr/bin/env bash
set -euo pipefail

LOCAL_IMAGE="${CUTEDSL_INFERENCE_IMAGE:-cutedsl-inference:cuda12.8}"
REMOTE_IMAGE="${RUNPOD_LORA_DOCKER_IMAGE:-}"

if [[ -z "$REMOTE_IMAGE" ]]; then
  if [[ -z "${DOCKER_USERNAME:-}" ]]; then
    echo "Set RUNPOD_LORA_DOCKER_IMAGE or DOCKER_USERNAME." >&2
    exit 2
  fi
  REMOTE_IMAGE="${DOCKER_USERNAME}/cutedsl-inference:cuda12.8"
fi

docker image inspect "$LOCAL_IMAGE" >/dev/null
docker tag "$LOCAL_IMAGE" "$REMOTE_IMAGE"
docker push "$REMOTE_IMAGE"
echo "Pushed $REMOTE_IMAGE"
