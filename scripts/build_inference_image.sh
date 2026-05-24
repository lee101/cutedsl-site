#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODE_ROOT="$(cd "$ROOT/.." && pwd)"
IMAGE="${CUTEDSL_INFERENCE_IMAGE:-cutedsl-inference:cuda12.8}"
CUDA_IMAGE="${CUDA_IMAGE:-nvidia/cuda:12.8.1-cudnn-runtime-ubuntu22.04}"
BUILD_CONTEXT="$(mktemp -d)"
trap 'rm -rf "$BUILD_CONTEXT"' EXIT
export DOCKER_BUILDKIT="${DOCKER_BUILDKIT:-0}"

mkdir -p "$BUILD_CONTEXT/cutedsl-site" "$BUILD_CONTEXT/cutedsl"
rsync -a \
  --exclude '.git/' \
  --exclude '.runlogs/' \
  --exclude '.triton_cache/' \
  --exclude '__pycache__/' \
  --exclude 'frontend/node_modules/' \
  --exclude 'frontend/.next/' \
  --exclude 'frontend/out/' \
  --exclude 'inference/.aitune_cache/' \
  --exclude 'inference/.lora_cache/' \
  --exclude 'inference/lora_datasets/' \
  --exclude 'inference/trained_loras/' \
  --exclude 'screenshots/' \
  --exclude 'visualbench/' \
  "$ROOT/" "$BUILD_CONTEXT/cutedsl-site/"

if [[ -d "$CODE_ROOT/cutedsl" ]]; then
  for item in pyproject.toml cutechronos cutezimage latentteleport zimageaccelerated tubroquant; do
    if [[ -e "$CODE_ROOT/cutedsl/$item" ]]; then
      rsync -a \
        --exclude '__pycache__/' \
        --exclude '.pytest_cache/' \
        "$CODE_ROOT/cutedsl/$item" "$BUILD_CONTEXT/cutedsl/"
    fi
  done
fi

docker build \
  --pull \
  --build-arg "CUDA_IMAGE=${CUDA_IMAGE}" \
  -f "$BUILD_CONTEXT/cutedsl-site/inference/Dockerfile.cuda" \
  -t "$IMAGE" \
  "$BUILD_CONTEXT"

echo "Built $IMAGE"
