# CuteDSL GPU Runtime

This service should run GPU inference in a CUDA container, not directly in a
mutable host Python environment. The host only owns the NVIDIA driver and Docker
GPU runtime; Python, PyTorch, Diffusers, Triton, and app dependencies live in the
image.

## Host preflight

Run this before deploying or after any driver change:

```bash
python scripts/cuda_doctor.py --check-docker
```

Healthy output requires:

- `nvidia-smi` succeeds on the host.
- `torch.cuda.is_available()` is true in the app environment.
- `docker run --gpus all ... nvidia-smi` succeeds.

If `nvidia-smi` reports an NVML driver/library mismatch, fix the host driver
first and reboot. A container cannot repair a broken host driver.

## NVIDIA Docker setup

Use the official NVIDIA Container Toolkit flow on Ubuntu/Debian:

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu22.04 nvidia-smi
```

For this host, Docker image layers live on NVMe storage. Keep the NVIDIA runtime
configured, but avoid Docker's `vfs` storage driver for CUDA images; it is slow
and space-heavy.

```json
{
  "data-root": "/nvme0n1-disk/docker",
  "storage-driver": "overlay2",
  "runtimes": {
    "nvidia": {
      "args": [],
      "path": "nvidia-container-runtime"
    }
  }
}
```

After changing `/etc/docker/daemon.json`, restart Docker and confirm:

```bash
docker info --format 'Driver={{.Driver}} DockerRootDir={{.DockerRootDir}}'
```

## Build and run

```bash
scripts/build_inference_image.sh
RUNPOD_LORA_DOCKER_IMAGE=your-registry/cutedsl-inference:cuda12.8 scripts/push_inference_image.sh
scripts/run_inference_docker.sh
curl -s http://127.0.0.1:8100/health
```

Defaults are intentionally conservative:

- `torch==2.8.0+cu128` in the CUDA image for reproducible installs.
- `PRELOAD_MODELS=0` to reduce boot and idle memory pressure.
- `MODEL_IDLE_TIMEOUT=300` so heavy models unload after idle periods.
- `--ipc=host` and CUDA allocator expandable segments for fewer allocation
  stalls and less fragmentation.

Set `RUNPOD_LORA_DOCKER_IMAGE` to the same pushed image tag before creating or
updating the RunPod endpoint.

## RunPod training

There are two supported remote training modes:

- `RUNPOD_LORA_BACKEND=serverless`: preferred for cost control. Configure a
  RunPod Serverless endpoint with `Active workers = 0`, short idle timeout, and
  the CUDA image from this repo running `CUTEDSL_MODE=runpod-worker` and
  `RUNPOD_SERVERLESS=1`.
- `RUNPOD_LORA_BACKEND=pod`: fallback for ad-hoc jobs. Pods are terminated on
  success, failure, boot timeout, or job timeout.

Serverless env needed on the endpoint:

```bash
CUTEDSL_MODE=runpod-worker
RUNPOD_SERVERLESS=1
R2_ENDPOINT_URL=...
R2_BUCKET=appstatic
R2_PUBLIC_BASE_URL=appstatic.app.nz
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
LORA_TRAINING_STATUS_PREFIX=cutedsl/training-jobs
```

API server env to submit jobs to that endpoint:

```bash
RUNPOD_LORA_TRAINING=1
RUNPOD_LORA_BACKEND=serverless
RUNPOD_LORA_ENDPOINT_ID=...
RUNPOD_LORA_TIMEOUT_SECONDS=7200
```
