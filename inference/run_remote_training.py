"""Drive RunPod pod-backend LoRA training for the new datasets, sequentially.

Runs outside the inference server (local GPU has no headroom). Requires R2 +
RUNPOD_API_KEY env (source ~/.secretbashrc). Blocks until each job reaches a
terminal state; monitor thread terminates the pod. Final sweep kills any
leftover cutedsl-lora-* pods as a billing backstop.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import runpod_lora_manager as mgr

DATASET_ROOT = Path(__file__).parent / "lora_datasets"
R2_BASE = "https://appstatic.app.nz/cutedsl/uploads"

JOBS_FILE = Path("/nvme0n1-disk/tmp/remote_lora_jobs.json")

TRAIN = [
    {"dataset": "app_logo_maker", "num_steps": 800, "train_size": 512},
    {"dataset": "product_screenshots", "num_steps": 800, "train_size": 768},
]


def payload_for(dataset: str, num_steps: int, train_size: int) -> dict:
    index = [json.loads(l) for l in (DATASET_ROOT / dataset / "index.jsonl").read_text().splitlines()]
    return {
        "model": "zimage",
        "dataset_name": dataset,
        "dataset_zip_url": f"{R2_BASE}/lora_datasets/{dataset}.zip",
        "image_urls": [f"{R2_BASE}/lora_datasets/{dataset}/{r['file']}" for r in index],
        "captions": [r["caption"] for r in index],
        "lora_r": 16,
        "lora_alpha": 32,
        "learning_rate": 1e-4,
        "num_steps": num_steps,
        "batch_size": 1,
        "train_size": train_size,
    }


def sweep_leftover_pods() -> None:
    try:
        client = mgr.RunPodClient(mgr._runpod_key())
        pods = client.request("GET", "/pods") or []
        for pod in pods if isinstance(pods, list) else pods.get("pods", []):
            if str(pod.get("name", "")).startswith("cutedsl-lora-"):
                print("terminating leftover pod", pod.get("id"), pod.get("name"), flush=True)
                mgr.terminate_runpod_pod(pod.get("id"))
    except Exception as e:
        print("pod sweep failed:", e, flush=True)


def main() -> None:
    results = {}
    jobs: dict[str, dict] = {}
    for spec in TRAIN:
        job_id = str(uuid.uuid4())
        payload = payload_for(spec["dataset"], spec["num_steps"], spec["train_size"])
        print(f"starting {spec['dataset']} job {job_id} ({len(payload['image_urls'])} images)", flush=True)
        jobs[job_id] = {"job_id": job_id, "dataset_name": spec["dataset"],
                        "status": "queued", "created_at": time.time()}
        try:
            mgr.start_runpod_training(jobs, job_id, payload)
        except Exception as e:
            print(f"start failed for {spec['dataset']}: {e}", flush=True)
            results[spec["dataset"]] = {"status": "failed", "error": str(e)}
            continue

        while True:
            time.sleep(20)
            job = jobs.get(job_id, {})
            state = job.get("status")
            print(f"{spec['dataset']}: {state} progress={job.get('progress')} "
                  f"step={job.get('current_step')} loss={job.get('loss')}", flush=True)
            JOBS_FILE.write_text(json.dumps(jobs, default=str, indent=2))
            if state in {"completed", "failed"}:
                results[spec["dataset"]] = {k: job.get(k) for k in
                                            ("status", "error", "adapter_url", "output_url",
                                             "config_url", "zip_url", "runpod_cost_per_hr")}
                break

    sweep_leftover_pods()
    print(json.dumps(results, indent=2), flush=True)


if __name__ == "__main__":
    main()
