"""Poll R2 for the running logo job, terminate its pod on completion, then run
and babysit the screenshots job the same way. No reliance on manager threads.
"""

from __future__ import annotations

import json
import time
import uuid

import runpod_lora_manager as mgr
from run_remote_training import payload_for, sweep_leftover_pods

CURRENT = {"job_id": "4722c6c2-4b3b-4ab3-83f9-05e29d7af892",
           "pod_id": "3o1irdmwnfos0t", "dataset": "app_logo_maker"}
NEXT = {"dataset": "product_screenshots", "num_steps": 800, "train_size": 768}
POLL = 30
TIMEOUT = 3 * 3600


def wait_terminal(job_id: str, pod_id: str, dataset: str) -> dict:
    started = time.time()
    last = {}
    while time.time() - started < TIMEOUT:
        st = mgr._get_status_from_r2(f"cutedsl/training-jobs/{job_id}.json") or {}
        if st != last:
            print(dataset, {k: st.get(k) for k in ("status", "progress", "loss", "error")}, flush=True)
            last = st
        if st.get("status") in {"completed", "failed"}:
            mgr.terminate_runpod_pod(pod_id)
            print(f"{dataset}: pod {pod_id} terminated", flush=True)
            return st
        time.sleep(POLL)
    mgr.terminate_runpod_pod(pod_id)
    return {"status": "failed", "error": "babysitter timeout"}


def start_pod_job(dataset: str, num_steps: int, train_size: int) -> tuple[str, str]:
    job_id = str(uuid.uuid4())
    jobs: dict[str, dict] = {job_id: {"job_id": job_id, "dataset_name": dataset}}
    payload = payload_for(dataset, num_steps, train_size)
    job = mgr._start_runpod_pod_training(jobs, job_id, payload)
    return job_id, job["runpod_pod_id"]


def main() -> None:
    results = {}
    results[CURRENT["dataset"]] = wait_terminal(CURRENT["job_id"], CURRENT["pod_id"], CURRENT["dataset"])

    job_id, pod_id = start_pod_job(NEXT["dataset"], NEXT["num_steps"], NEXT["train_size"])
    print(f"started {NEXT['dataset']} job {job_id} pod {pod_id}", flush=True)
    results[NEXT["dataset"]] = wait_terminal(job_id, pod_id, NEXT["dataset"])

    sweep_leftover_pods()
    print(json.dumps(results, indent=2, default=str), flush=True)


if __name__ == "__main__":
    main()
