#!/usr/bin/env python3
"""Start one tiny RunPod LoRA training job and wait for a terminal status.

This is intentionally conservative: one RTX 4090 by default, one image,
and one training step. Pod-mode jobs request termination in the cleanup path;
serverless jobs rely on the endpoint scaling settings.
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "inference"))

from runpod_lora_manager import (  # noqa: E402
    refresh_runpod_status,
    start_runpod_training,
    terminate_runpod_pod,
)
from training_store import load_jobs  # noqa: E402


def main() -> int:
    os.environ.setdefault("RUNPOD_LORA_TRAINING", "1")
    os.environ.setdefault("RUNPOD_LORA_GPU_TYPE_IDS", "NVIDIA GeForce RTX 4090,NVIDIA GeForce RTX 3090,NVIDIA RTX A5000,NVIDIA L4")
    os.environ.setdefault("RUNPOD_LORA_MAX_HOURLY_USD", "0.85")
    os.environ.setdefault("RUNPOD_LORA_TIMEOUT_SECONDS", "1800")
    os.environ.setdefault("LORA_TRAIN_SIZE", "128")
    os.environ.setdefault("RUNPOD_LORA_DTYPE", "bfloat16")

    job_id = f"smoke-{uuid.uuid4()}"
    jobs = load_jobs()
    pod_id = ""
    payload = {
        "model": "zimage",
        "dataset_name": "runpod-smoke",
        "image_urls": [os.getenv("RUNPOD_LORA_SMOKE_IMAGE_URL", "https://picsum.photos/seed/cutedsl-runpod-smoke/512/512")],
        "captions": ["a small cute watercolor mascot"],
        "lora_r": 4,
        "lora_alpha": 8,
        "learning_rate": 1e-4,
        "num_steps": 1,
        "batch_size": 1,
    }

    try:
        job = start_runpod_training(jobs, job_id, payload)
        backend = job.get("runpod_backend", "pod")
        pod_id = job.get("runpod_pod_id", "")
        print(
            f"started job={job_id} backend={backend} "
            f"pod={pod_id} endpoint={job.get('runpod_endpoint_id', '')} "
            f"cost_per_hr={job.get('runpod_cost_per_hr')}",
            flush=True,
        )
        deadline = time.time() + float(os.getenv("RUNPOD_LORA_SMOKE_WAIT_SECONDS", "1800"))
        last_status = ""
        while time.time() < deadline:
            time.sleep(float(os.getenv("RUNPOD_LORA_SMOKE_POLL_SECONDS", "15")))
            job = refresh_runpod_status(jobs, job_id)
            status = str(job.get("status", "unknown"))
            if status != last_status or status in {"training", "uploading_artifacts"}:
                print(
                    f"status={status} progress={job.get('progress')} "
                    f"loss={job.get('loss')} output_url={job.get('output_url', '')}",
                    flush=True,
                )
                last_status = status
            if status in {"completed", "failed"}:
                if status == "failed":
                    print(f"error={job.get('error')}", flush=True)
                    return 1
                return 0
        print("timed out waiting for RunPod smoke job", flush=True)
        return 2
    finally:
        if pod_id:
            terminate_runpod_pod(pod_id)
            print(f"termination requested for pod={pod_id}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
