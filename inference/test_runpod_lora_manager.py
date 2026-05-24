import json
import os
import time

import pytest

import runpod_lora_manager as rpm
from training_store import load_jobs, update_job


def test_r2_env_maps_cloudflare_names(monkeypatch):
    monkeypatch.setenv("R2_ENDPOINT", "https://example.r2.cloudflarestorage.com")
    monkeypatch.setenv("R2_BUCKET", "bucket")
    monkeypatch.setenv("R2_PUBLIC_HOST", "cdn.example.com")
    monkeypatch.setenv("CLOUDFLARE_R2_ACCESS_KEY_ID", "access")
    monkeypatch.setenv("CLOUDFLARE_R2_SECRET_ACCESS_KEY", "secret")

    env = rpm._r2_env()

    assert env["R2_ENDPOINT_URL"] == "https://example.r2.cloudflarestorage.com"
    assert env["R2_BUCKET"] == "bucket"
    assert env["R2_PUBLIC_BASE_URL"] == "cdn.example.com"
    assert env["AWS_ACCESS_KEY_ID"] == "access"
    assert env["AWS_SECRET_ACCESS_KEY"] == "secret"


def test_training_store_persists_status(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAINING_JOB_STORE", str(tmp_path))
    jobs = load_jobs()

    update_job(jobs, "job-1", status="queued", progress=0.25)

    stored = json.loads((tmp_path / "job-1.json").read_text())
    assert stored["status"] == "queued"
    assert stored["progress"] == 0.25
    assert load_jobs()["job-1"]["status"] == "queued"


def test_monitor_terminates_pod_without_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAINING_JOB_STORE", str(tmp_path))
    monkeypatch.setenv("RUNPOD_LORA_POLL_SECONDS", "0.01")
    monkeypatch.setenv("RUNPOD_LORA_BOOT_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setenv("RUNPOD_LORA_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("R2_ENDPOINT", "https://example.r2.cloudflarestorage.com")
    monkeypatch.setenv("CLOUDFLARE_R2_ACCESS_KEY_ID", "access")
    monkeypatch.setenv("CLOUDFLARE_R2_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("RUNPOD_API_KEY", "key")

    jobs = {}
    update_job(
        jobs,
        "job-timeout",
        status="starting",
        progress=0.0,
        backend="runpod",
        runpod_pod_id="pod-1",
        status_key="cutedsl/training-jobs/job-timeout.json",
        created_at=time.time(),
    )
    terminated = []

    monkeypatch.setattr(rpm, "_get_status_from_r2", lambda _key: None)
    monkeypatch.setattr(rpm, "terminate_runpod_pod", lambda pod_id: terminated.append(pod_id))

    class FakeClient:
        def __init__(self, _key):
            pass

        def request(self, method, path, body=None):
            assert method == "GET"
            assert path == "/pods/pod-1"
            return {"runtime": None}

    monkeypatch.setattr(rpm, "RunPodClient", FakeClient)

    rpm.monitor_runpod_training(jobs, "job-timeout")

    assert terminated == ["pod-1"]
    assert jobs["job-timeout"]["status"] == "failed"
    assert "did not start a runtime" in jobs["job-timeout"]["error"]


def test_start_runpod_training_uses_serverless_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAINING_JOB_STORE", str(tmp_path))
    monkeypatch.setenv("RUNPOD_API_KEY", "key")
    monkeypatch.setenv("RUNPOD_LORA_BACKEND", "serverless")
    monkeypatch.setenv("RUNPOD_LORA_ENDPOINT_ID", "endpoint-1")
    monkeypatch.setattr(rpm, "_r2_env", lambda: {"R2_ENDPOINT_URL": "https://r2", "R2_BUCKET": "bucket"})

    started_threads = []

    class FakeThread:
        def __init__(self, target, args, daemon):
            self.target = target
            self.args = args
            self.daemon = daemon

        def start(self):
            started_threads.append(self.args)

    class FakeServerlessClient:
        def __init__(self, _key):
            pass

        def run(self, endpoint_id, payload):
            assert endpoint_id == "endpoint-1"
            assert payload["job_id"] == "job-serverless"
            assert payload["status_prefix"] == "cutedsl/training-jobs"
            return {"id": "rp-job-1"}

    monkeypatch.setattr(rpm.threading, "Thread", FakeThread)
    monkeypatch.setattr(rpm, "RunPodServerlessClient", FakeServerlessClient)

    jobs = {}
    job = rpm.start_runpod_training(jobs, "job-serverless", {"model": "zimage", "image_urls": ["https://example/image.jpg"]})

    assert job["runpod_backend"] == "serverless"
    assert job["runpod_endpoint_id"] == "endpoint-1"
    assert job["runpod_job_id"] == "rp-job-1"
    assert job["runpod_zero_scale"] is True
    assert started_threads and started_threads[0][1] == "job-serverless"


def test_refresh_serverless_completed_status(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAINING_JOB_STORE", str(tmp_path))
    monkeypatch.setenv("RUNPOD_API_KEY", "key")
    monkeypatch.setattr(rpm, "_get_status_from_r2", lambda _key: None)

    class FakeServerlessClient:
        def __init__(self, _key):
            pass

        def status(self, endpoint_id, runpod_job_id):
            assert endpoint_id == "endpoint-1"
            assert runpod_job_id == "rp-job-1"
            return {
                "status": "COMPLETED",
                "output": {
                    "adapter_url": "https://cdn.example/adapter.safetensors",
                    "artifact_url": "https://cdn.example/job.zip",
                },
            }

    monkeypatch.setattr(rpm, "RunPodServerlessClient", FakeServerlessClient)
    jobs = {}
    update_job(
        jobs,
        "job-serverless",
        backend="runpod",
        runpod_backend="serverless",
        runpod_endpoint_id="endpoint-1",
        runpod_job_id="rp-job-1",
        status_key="cutedsl/training-jobs/job-serverless.json",
        status="running",
    )

    job = rpm.refresh_runpod_status(jobs, "job-serverless")

    assert job["status"] == "completed"
    assert job["progress"] == 1.0
    assert job["adapter_url"] == "https://cdn.example/adapter.safetensors"
