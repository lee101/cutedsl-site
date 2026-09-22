#!/usr/bin/env python3
"""Fail-fast CUDA/runtime diagnostics for host and container launches."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys


def run(cmd: list[str], timeout: int = 20) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, check=False)
    except FileNotFoundError:
        return 127, f"{cmd[0]} not found"
    except subprocess.TimeoutExpired:
        return 124, f"{' '.join(cmd)} timed out"
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out.strip()


def check_nvidia_smi() -> tuple[bool, str]:
    code, out = run(["nvidia-smi"])
    return code == 0, out


def check_torch_cuda() -> tuple[bool, dict]:
    try:
        import torch

        available = bool(torch.cuda.is_available())
        info = {
            "torch": torch.__version__,
            "cuda_runtime": torch.version.cuda,
            "available": available,
            "device_count": torch.cuda.device_count() if available else 0,
            "device_name": torch.cuda.get_device_name(0) if available else "",
        }
        if available:
            x = torch.ones((1,), device="cuda")
            info["smoke_sum"] = float((x + 1).sum().item())
        return available, info
    except Exception as exc:
        return False, {"error": f"{type(exc).__name__}: {exc}"}


def check_docker_gpu(image: str) -> tuple[bool, str]:
    if not shutil.which("docker"):
        return False, "docker not found"
    code, out = run(["docker", "run", "--rm", "--gpus", "all", image, "nvidia-smi"], timeout=120)
    return code == 0, out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docker-image", default="nvidia/cuda:12.8.1-base-ubuntu22.04")
    parser.add_argument("--check-docker", action="store_true")
    parser.add_argument("--require-torch-cuda", action="store_true")
    args = parser.parse_args()

    ok = True
    smi_ok, smi_out = check_nvidia_smi()
    print(json.dumps({"check": "nvidia-smi", "ok": smi_ok, "output": smi_out[-2000:]}, indent=2))
    ok = ok and smi_ok

    torch_ok, torch_info = check_torch_cuda()
    print(json.dumps({"check": "torch-cuda", "ok": torch_ok, **torch_info}, indent=2))
    if args.require_torch_cuda:
        ok = ok and torch_ok

    if args.check_docker:
        docker_ok, docker_out = check_docker_gpu(args.docker_image)
        print(json.dumps({"check": "docker-gpu", "ok": docker_ok, "output": docker_out[-2000:]}, indent=2))
        ok = ok and docker_ok

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
