#!/usr/bin/env python3
"""Benchmark Z-Image API latency and exact-prompt teleport quality.

The harness calls the running inference server, compares full generation against
teleport replay for fixed prompts, and writes JSON plus Markdown summaries.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import statistics
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.parse import urlencode
from urllib.request import urlopen

import numpy as np
from PIL import Image


DEFAULT_PROMPTS = [
    "minecraft block dirt menu zoomed in dirt block icon",
    "pixel art stone block inventory icon, centered, simple game UI asset",
    "voxel grass block item icon, clean square menu tile, game inventory",
]


@dataclass
class ImageMetrics:
    mse: float
    mae: float
    max_abs: float
    psnr_db: float


def now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def request_json(base_url: str, params: dict[str, object], timeout: float) -> tuple[dict, float]:
    url = f"{base_url.rstrip('/')}/create_and_upload_image?{urlencode(params)}"
    started = time.perf_counter()
    with urlopen(url, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload, time.perf_counter() - started


def fetch_image(url: str, timeout: float) -> Image.Image:
    try:
        with urlopen(url, timeout=timeout) as resp:
            return Image.open(io.BytesIO(resp.read())).convert("RGB")
    except Exception:
        # R2 public URLs can be temporarily blocked by policy/CDN. The harness
        # usually runs next to the inference service, so use the configured S3
        # client as a reliable fallback for quality checks.
        parsed = urlparse(url)
        key = parsed.path.lstrip("/")
        r2_bucket_path = "cutedsl/uploads"
        r2_bucket = "appstatic"
        prefix = f"{r2_bucket_path}/"
        if not key.startswith(prefix):
            raise
        try:
            import sys

            inference_dir = Path(__file__).resolve().parents[1] / "inference"
            sys.path.insert(0, str(inference_dir))
            from r2_upload import R2_BUCKET, R2_BUCKET_PATH, _get_s3_client

            r2_bucket = R2_BUCKET
            prefix = f"{R2_BUCKET_PATH}/"
            if not key.startswith(prefix):
                raise
            client = _get_s3_client()
        except Exception:
            import boto3

            endpoint = "https://f76d25b8b86cfa5638f43016510d8f77.r2.cloudflarestorage.com"
            client = boto3.session.Session().client("s3", endpoint_url=endpoint)
            if not key.startswith(f"{r2_bucket_path}/"):
                raise
        obj = client.get_object(Bucket=r2_bucket, Key=key)
        return Image.open(io.BytesIO(obj["Body"].read())).convert("RGB")


def compare_images(a: Image.Image, b: Image.Image) -> ImageMetrics:
    arr_a = np.asarray(a, dtype=np.float32)
    arr_b = np.asarray(b, dtype=np.float32)
    diff = arr_a - arr_b
    mse = float(np.mean(diff * diff))
    mae = float(np.mean(np.abs(diff)))
    max_abs = float(np.max(np.abs(diff)))
    psnr = float("inf") if mse == 0 else float(20 * math.log10(255.0 / math.sqrt(mse)))
    return ImageMetrics(mse=mse, mae=mae, max_abs=max_abs, psnr_db=psnr)


def nvidia_memory() -> dict[str, int] | None:
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=5,
        ).strip()
    except Exception:
        return None
    if not out:
        return None
    used, total = [int(part.strip()) for part in out.splitlines()[0].split(",")[:2]]
    return {"used_mib": used, "total_mib": total}


def summarize(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values)
    p95_idx = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * 0.95)))
    return {
        "min": min(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p95": ordered[p95_idx],
        "max": max(values),
    }


def markdown_report(results: dict) -> str:
    lines = [
        "# Z-Image Perf Harness",
        f"timestamp: `{results['timestamp']}`",
        f"base_url: `{results['base_url']}`",
        "",
        "## Summary",
        "",
        "| Mode | Runs | Wall median (s) | Server median (s) | Upload median (s) |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for mode in ("baseline", "teleport_prime", "teleport_replay"):
        stats = results["summary"].get(mode, {})
        if not stats:
            continue
        lines.append(
            f"| {mode} | {stats['runs']} | {stats['wall_s']['median']:.3f} | "
            f"{stats['server_s']['median']:.3f} | {stats['upload_s']['median']:.3f} |"
        )

    lines.extend([
        "",
        "## Quality",
        "",
        "| Prompt | MSE | MAE | Max abs | PSNR dB | Identical |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ])
    for row in results["quality"]:
        psnr = "inf" if math.isinf(row["psnr_db"]) else f"{row['psnr_db']:.2f}"
        lines.append(
            f"| `{row['prompt'][:80]}` | {row['mse']:.6f} | {row['mae']:.6f} | "
            f"{row['max_abs']:.1f} | {psnr} | {row['identical']} |"
        )

    lines.extend([
        "",
        "## Runs",
        "",
        "| Prompt | Mode | Wall s | Server s | Upload s | URL |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ])
    for row in results["runs"]:
        lines.append(
            f"| `{row['prompt'][:60]}` | {row['mode']} | {row['wall_s']:.3f} | "
            f"{row.get('server_s', 0):.3f} | {row.get('upload_s', 0):.3f} | "
            f"[image]({row['path']}) |"
        )

    if results.get("gpu_memory"):
        mem = results["gpu_memory"]
        lines.extend([
            "",
            "## GPU Memory",
            "",
            f"- used: `{mem['used_mib']} MiB`",
            f"- total: `{mem['total_mib']} MiB`",
        ])

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8100")
    parser.add_argument("--secret", default="cutedsl2024")
    parser.add_argument("--prompt", action="append", default=[])
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--runs", type=int, default=2, help="Steady-state replay runs per prompt")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--output-dir", default="/nvme0n1-disk/tmp/zimage-perf")
    args = parser.parse_args()

    prompts = args.prompt or DEFAULT_PROMPTS
    stamp = now_slug()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results: dict = {
        "timestamp": stamp,
        "base_url": args.base_url,
        "width": args.width,
        "height": args.height,
        "runs": [],
        "quality": [],
        "summary": {},
        "gpu_memory": nvidia_memory(),
    }

    def call(prompt: str, mode: str, save_path: str, teleport: bool) -> dict:
        payload, wall_s = request_json(
            args.base_url,
            {
                "prompt": prompt,
                "width": args.width,
                "height": args.height,
                "model": "zimage-turbo",
                "auto_lora": "false",
                "secret": args.secret,
                "save_path": save_path,
                "teleport": "true" if teleport else "false",
                "perf": "true",
            },
            args.timeout,
        )
        perf = payload.get("perf", {})
        row = {
            "prompt": prompt,
            "mode": mode,
            "wall_s": wall_s,
            "server_s": perf.get("inference_time_ms", 0) / 1000.0,
            "upload_s": perf.get("upload_time_ms", 0) / 1000.0,
            "encode_s": perf.get("encode_time_ms", 0) / 1000.0,
            "path": payload["path"],
            "response": payload,
        }
        results["runs"].append(row)
        return row

    for idx, prompt in enumerate(prompts):
        safe = f"{idx:02d}_{abs(hash(prompt)) % 1_000_000}_{stamp}"
        baseline = call(prompt, "baseline", f"zimage_perf/{safe}_baseline.webp", False)
        prime = call(prompt, "teleport_prime", f"zimage_perf/{safe}_prime.webp", True)
        replay_rows = [
            call(prompt, "teleport_replay", f"zimage_perf/{safe}_replay_{run}.webp", True)
            for run in range(args.runs)
        ]

        base_img = fetch_image(baseline["path"], args.timeout)
        replay_img = fetch_image(replay_rows[-1]["path"], args.timeout)
        metrics = compare_images(base_img, replay_img)
        results["quality"].append(
            {
                "prompt": prompt,
                "mse": metrics.mse,
                "mae": metrics.mae,
                "max_abs": metrics.max_abs,
                "psnr_db": metrics.psnr_db,
                "identical": metrics.mse == 0.0,
                "baseline_path": baseline["path"],
                "replay_path": replay_rows[-1]["path"],
            }
        )

    for mode in ("baseline", "teleport_prime", "teleport_replay"):
        rows = [row for row in results["runs"] if row["mode"] == mode]
        if rows:
            results["summary"][mode] = {
                "runs": len(rows),
                "wall_s": summarize([row["wall_s"] for row in rows]),
                "server_s": summarize([row["server_s"] for row in rows]),
                "upload_s": summarize([row["upload_s"] for row in rows]),
            }

    json_path = output_dir / f"zimage_perf_{stamp}.json"
    md_path = output_dir / f"zimage_perf_{stamp}.md"
    json_path.write_text(json.dumps(results, indent=2, allow_nan=True))
    md_path.write_text(markdown_report(results))
    print(md_path)
    print(json_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
