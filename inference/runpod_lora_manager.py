"""RunPod-backed LoRA training launcher and status bridge."""

from __future__ import annotations

import base64
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from training_store import update_job


class RunPodConfigError(RuntimeError):
    pass


def runpod_enabled() -> bool:
    return os.getenv("RUNPOD_LORA_TRAINING", "0") == "1"


def _runpod_key() -> str:
    key = os.getenv("RUNPOD_API_KEY", "").strip()
    if key:
        return key
    for candidate in (
        "/nvme0n1-disk/code/env_real.py",
        "/nvme0n1-disk/code/stock-prediction/env_real.py",
    ):
        path = Path(candidate)
        if not path.exists():
            continue
        text = path.read_text(errors="replace")
        for line in text.splitlines():
            if "RUNPOD_API_KEY" not in line or "os.getenv" in line:
                continue
            if "=" in line:
                value = line.split("=", 1)[1].strip().strip("'\"")
                if value and "your_" not in value.lower() and "placeholder" not in value.lower():
                    return value
    return ""


def _r2_env() -> dict[str, str]:
    env = {
        "R2_ENDPOINT_URL": os.getenv("R2_ENDPOINT_URL") or os.getenv("R2_ENDPOINT") or "",
        "R2_BUCKET": os.getenv("R2_BUCKET", "appstatic"),
        "R2_PUBLIC_BASE_URL": os.getenv("R2_PUBLIC_BASE_URL") or os.getenv("R2_PUBLIC_HOST", "appstatic.app.nz"),
        "AWS_ACCESS_KEY_ID": os.getenv("AWS_ACCESS_KEY_ID") or os.getenv("CLOUDFLARE_R2_ACCESS_KEY_ID") or os.getenv("R2_ACCESS_KEY") or "",
        "AWS_SECRET_ACCESS_KEY": os.getenv("AWS_SECRET_ACCESS_KEY") or os.getenv("CLOUDFLARE_R2_SECRET_ACCESS_KEY") or os.getenv("R2_SECRET_KEY") or "",
    }
    # Best-effort fallback for the stock env file without printing or exporting secrets.
    if not env["AWS_ACCESS_KEY_ID"] or not env["AWS_SECRET_ACCESS_KEY"]:
        stock = Path("/nvme0n1-disk/code/stock-prediction/env_real.py")
        if stock.exists():
            values: dict[str, str] = {}
            for line in stock.read_text(errors="replace").splitlines():
                if "=" not in line or "os.getenv" in line:
                    continue
                key, raw = line.split("=", 1)
                key = key.strip()
                raw = raw.strip().strip("'\"")
                if key in {"R2_ENDPOINT", "R2_BUCKET", "R2_ACCESS_KEY", "R2_SECRET_KEY"}:
                    values[key] = raw
            env["R2_ENDPOINT_URL"] = env["R2_ENDPOINT_URL"] or values.get("R2_ENDPOINT", "")
            env["R2_BUCKET"] = env["R2_BUCKET"] or values.get("R2_BUCKET", "appstatic")
            env["AWS_ACCESS_KEY_ID"] = env["AWS_ACCESS_KEY_ID"] or values.get("R2_ACCESS_KEY", "")
            env["AWS_SECRET_ACCESS_KEY"] = env["AWS_SECRET_ACCESS_KEY"] or values.get("R2_SECRET_KEY", "")
    missing = [k for k in ("R2_ENDPOINT_URL", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY") if not env.get(k)]
    if missing:
        raise RunPodConfigError(f"missing R2 settings for RunPod worker: {', '.join(missing)}")
    return env


class RunPodClient:
    base_url = "https://rest.runpod.io/v1"

    def __init__(self, api_key: str):
        if not api_key:
            raise RunPodConfigError("RUNPOD_API_KEY is not configured")
        self.api_key = api_key

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        data = None
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base_url + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                payload = resp.read()
                if not payload:
                    return {}
                return json.loads(payload)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"RunPod API {method} {path} failed: HTTP {exc.code} {detail}") from exc

    def validate(self) -> None:
        self.request("GET", "/pods")


def _worker_script_b64() -> str:
    path = Path(__file__).with_name("runpod_lora_worker.py")
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _bootstrap_command() -> str:
    return (
        "set -euo pipefail\n"
        "python -m pip install --upgrade pip\n"
        "python -m pip install --no-cache-dir diffusers transformers accelerate peft safetensors boto3 httpx pillow numpy\n"
        "mkdir -p /workspace/cutedsl-lora-worker\n"
        "python - <<'PY'\n"
        "import base64, os, pathlib\n"
        "path = pathlib.Path('/workspace/cutedsl-lora-worker/runpod_lora_worker.py')\n"
        "path.write_bytes(base64.b64decode(os.environ['LORA_WORKER_SCRIPT_B64']))\n"
        "PY\n"
        "python /workspace/cutedsl-lora-worker/runpod_lora_worker.py\n"
    )


def start_runpod_training(jobs: dict[str, dict], job_id: str, payload: dict[str, Any]) -> dict:
    key = _runpod_key()
    client = RunPodClient(key)
    client.validate()

    status_prefix = os.getenv("LORA_TRAINING_STATUS_PREFIX", "cutedsl/training-jobs")
    job_payload = {**payload, "job_id": job_id}
    env = {
        **_r2_env(),
        "LORA_TRAINING_JOB_ID": job_id,
        "LORA_TRAINING_JOB_JSON_B64": base64.b64encode(json.dumps(job_payload).encode("utf-8")).decode("ascii"),
        "LORA_TRAINING_STATUS_PREFIX": status_prefix,
        "LORA_WORKER_SCRIPT_B64": _worker_script_b64(),
        "LORA_TRAIN_SIZE": os.getenv("LORA_TRAIN_SIZE", "384"),
        "DTYPE": os.getenv("RUNPOD_LORA_DTYPE", os.getenv("DTYPE", "bfloat16")),
        "ZIMAGE_MODEL_PATH": os.getenv("ZIMAGE_MODEL_PATH", "Tongyi-MAI/Z-Image-Turbo"),
    }

    body = {
        "name": f"cutedsl-lora-{job_id[:8]}",
        "imageName": os.getenv("RUNPOD_LORA_IMAGE", "runpod/pytorch:2.8.0-py3.11-cuda12.8-cudnn-devel-ubuntu22.04"),
        "computeType": "GPU",
        "cloudType": os.getenv("RUNPOD_LORA_CLOUD_TYPE", "COMMUNITY"),
        "gpuTypeIds": [g.strip() for g in os.getenv("RUNPOD_LORA_GPU_TYPE_IDS", "NVIDIA GeForce RTX 4090,NVIDIA GeForce RTX 3090,NVIDIA RTX A5000,NVIDIA L4").split(",") if g.strip()],
        "gpuTypePriority": "availability",
        "dataCenterPriority": "availability",
        "gpuCount": int(os.getenv("RUNPOD_LORA_GPU_COUNT", "1")),
        "containerDiskInGb": int(os.getenv("RUNPOD_LORA_CONTAINER_DISK_GB", "90")),
        "volumeInGb": int(os.getenv("RUNPOD_LORA_VOLUME_GB", "0")),
        "dockerEntrypoint": ["/bin/bash", "-lc"],
        "dockerStartCmd": [_bootstrap_command()],
        "env": env,
    }
    pod = client.request("POST", "/pods", body)
    pod_id = pod.get("id")
    if not pod_id:
        raise RuntimeError(f"RunPod did not return a pod id: {pod}")

    try:
        cost = float(pod.get("costPerHr") or pod.get("adjustedCostPerHr") or 0)
    except Exception:
        cost = 0.0
    max_hourly = float(os.getenv("RUNPOD_LORA_MAX_HOURLY_USD", "0.85"))
    if cost and cost > max_hourly:
        client.request("DELETE", f"/pods/{pod_id}")
        raise RuntimeError(f"RunPod pod cost ${cost:.2f}/hr exceeds RUNPOD_LORA_MAX_HOURLY_USD=${max_hourly:.2f}/hr")

    job = update_job(
        jobs,
        job_id,
        backend="runpod",
        runpod_pod_id=pod_id,
        status="starting",
        progress=0.0,
        status_key=f"{status_prefix}/{job_id}.json",
        runpod_cost_per_hr=cost,
    )
    threading.Thread(target=monitor_runpod_training, args=(jobs, job_id), daemon=True).start()
    return job


def _get_status_from_r2(status_key: str) -> dict[str, Any] | None:
    import boto3

    env = _r2_env()
    client = boto3.session.Session().client("s3", endpoint_url=env["R2_ENDPOINT_URL"])
    try:
        obj = client.get_object(Bucket=env["R2_BUCKET"], Key=status_key)
    except Exception:
        return None
    return json.loads(obj["Body"].read())


def refresh_runpod_status(jobs: dict[str, dict], job_id: str) -> dict:
    job = jobs.get(job_id)
    if not job or job.get("backend") != "runpod":
        return job or {}
    remote = _get_status_from_r2(job.get("status_key", ""))
    if remote:
        update_job(jobs, job_id, **remote, worker_seen_at=time.time())
    return jobs.get(job_id, {})


def terminate_runpod_pod(pod_id: str) -> None:
    if not pod_id:
        return
    try:
        RunPodClient(_runpod_key()).request("DELETE", f"/pods/{pod_id}")
    except Exception:
        pass


def monitor_runpod_training(jobs: dict[str, dict], job_id: str) -> None:
    timeout = float(os.getenv("RUNPOD_LORA_TIMEOUT_SECONDS", "7200"))
    boot_timeout = float(os.getenv("RUNPOD_LORA_BOOT_TIMEOUT_SECONDS", "600"))
    started = time.time()
    pod_id = ""
    while time.time() - started < timeout:
        time.sleep(float(os.getenv("RUNPOD_LORA_POLL_SECONDS", "10")))
        job = refresh_runpod_status(jobs, job_id)
        pod_id = job.get("runpod_pod_id", pod_id)
        if job.get("status") in {"completed", "failed"}:
            terminate_runpod_pod(pod_id)
            update_job(jobs, job_id, runpod_pod_terminated=True)
            return
        if pod_id and time.time() - started > boot_timeout and not job.get("worker_seen_at"):
            try:
                pod = RunPodClient(_runpod_key()).request("GET", f"/pods/{pod_id}")
            except Exception:
                pod = {}
            if not pod.get("runtime"):
                terminate_runpod_pod(pod_id)
                update_job(
                    jobs,
                    job_id,
                    status="failed",
                    progress=1.0,
                    error="RunPod pod was rented but did not start a runtime before boot timeout; pod termination requested",
                    runpod_pod_terminated=True,
                )
                return
    job = jobs.get(job_id, {})
    pod_id = job.get("runpod_pod_id", pod_id)
    terminate_runpod_pod(pod_id)
    update_job(jobs, job_id, status="failed", error="RunPod training timed out; pod termination requested", runpod_pod_terminated=True)
