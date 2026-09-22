"""Durable status store and artifact upload helpers for LoRA training jobs."""

from __future__ import annotations

import json
import os
import threading
import time
import zipfile
from pathlib import Path

_lock = threading.Lock()


def job_store_dir() -> Path:
    default_root = Path(__file__).resolve().parent / "trained_loras"
    root = os.getenv("TRAINING_JOB_STORE", os.path.join(os.getenv("TRAINED_LORA_ROOT", str(default_root)), "jobs"))
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    return path


def job_status_path(job_id: str) -> Path:
    safe = "".join(c for c in job_id if c.isalnum() or c in "._-")
    if not safe:
        raise ValueError("invalid job_id")
    return job_store_dir() / f"{safe}.json"


def load_jobs() -> dict[str, dict]:
    jobs: dict[str, dict] = {}
    root = job_store_dir()
    for path in root.glob("*.json"):
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue
        job_id = data.get("job_id") or path.stem
        if isinstance(job_id, str):
            jobs[job_id] = data
    return jobs


def save_job(job: dict) -> None:
    job_id = job.get("job_id")
    if not isinstance(job_id, str) or not job_id:
        return
    job["updated_at"] = time.time()
    path = job_status_path(job_id)
    tmp = path.with_suffix(".json.tmp")
    with _lock:
        tmp.write_text(json.dumps(job, sort_keys=True, indent=2))
        tmp.replace(path)


def update_job(jobs: dict[str, dict], job_id: str, **updates) -> dict:
    job = jobs.setdefault(job_id, {"job_id": job_id, "created_at": time.time()})
    job.update(updates)
    save_job(job)
    return job


def _content_type(path: Path) -> str:
    if path.suffix == ".json":
        return "application/json"
    if path.suffix == ".zip":
        return "application/zip"
    if path.suffix == ".safetensors":
        return "application/octet-stream"
    return "application/octet-stream"


def upload_training_artifacts(job_id: str, output_dir: str) -> dict[str, str]:
    """Upload trained adapter files to R2 and return public URLs.

    The single safetensors URL is what the inference path can consume directly.
    The zip is for reliable download/recovery of the full PEFT adapter folder.
    """
    from r2_upload import upload_bytes

    root = Path(output_dir)
    if not root.is_dir():
        raise FileNotFoundError(output_dir)

    urls: dict[str, str] = {}
    adapter = root / "adapter_model.safetensors"
    config = root / "adapter_config.json"

    if adapter.exists():
        urls["adapter_url"] = upload_bytes(
            f"loras/{job_id}/{adapter.name}",
            adapter.read_bytes(),
            _content_type(adapter),
        )
        urls["output_url"] = urls["adapter_url"]
    if config.exists():
        urls["config_url"] = upload_bytes(
            f"loras/{job_id}/{config.name}",
            config.read_bytes(),
            _content_type(config),
        )

    zip_path = root / f"{job_id}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in root.iterdir():
            if path == zip_path or not path.is_file():
                continue
            zf.write(path, path.name)
    urls["artifact_url"] = upload_bytes(
        f"loras/{job_id}/{zip_path.name}",
        zip_path.read_bytes(),
        _content_type(zip_path),
    )
    return urls
