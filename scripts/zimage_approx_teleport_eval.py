#!/usr/bin/env python3
"""Evaluate approximate nearest-latent teleport for Z-Image upload generation.

This measures the experimental cache-miss path:
  1. prime cache with a source prompt
  2. generate a full target baseline
  3. generate target again by refining the nearest cached source latent

The approximate replay is expected to be faster than a full 20-step target
generation, but unlike exact-prompt replay it is not guaranteed to match pixels.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen

import numpy as np
from PIL import Image, ImageDraw, ImageFont


DEFAULT_PAIRS = [
    (
        "minecraft dirt block inventory icon, centered, crisp pixel game asset, plain background",
        "minecraft grass block inventory icon, centered, crisp pixel game asset, plain background",
    ),
    (
        "cinematic product photo of a translucent glass robot toy on a white seamless studio background",
        "cinematic product photo of a blue translucent glass robot toy on a white seamless studio background",
    ),
]


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
        parsed = urlparse(url)
        key = parsed.path.lstrip("/")
        inference_dir = Path(__file__).resolve().parents[1] / "inference"
        import sys

        sys.path.insert(0, str(inference_dir))
        from r2_upload import R2_BUCKET, R2_BUCKET_PATH, _get_s3_client

        prefix = f"{R2_BUCKET_PATH}/"
        if not key.startswith(prefix):
            raise
        obj = _get_s3_client().get_object(Bucket=R2_BUCKET, Key=key)
        return Image.open(io.BytesIO(obj["Body"].read())).convert("RGB")


def image_metrics(a: Image.Image, b: Image.Image) -> dict[str, float | bool]:
    arr_a = np.asarray(a, dtype=np.float32)
    arr_b = np.asarray(b, dtype=np.float32)
    diff = arr_a - arr_b
    mse = float(np.mean(diff * diff))
    mae = float(np.mean(np.abs(diff)))
    max_abs = float(np.max(np.abs(diff)))
    psnr = float("inf") if mse == 0 else float(20 * math.log10(255.0 / math.sqrt(mse)))
    return {"mse": mse, "mae": mae, "max_abs": max_abs, "psnr_db": psnr, "identical": mse == 0.0}


def load_font(size: int):
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ):
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def contact_sheet(rows: list[dict], output_path: Path) -> None:
    image_rows = [row for row in rows if row.get("local_path")]
    if not image_rows:
        return
    first = Image.open(image_rows[0]["local_path"]).convert("RGB")
    thumb_w = 240
    thumb_h = max(1, round(first.height * (thumb_w / first.width)))
    pad = 12
    label_h = 64
    modes = ["source_prime", "target_baseline", "target_approx"]
    pair_indices = sorted({row["pair_index"] for row in image_rows})
    by_key = {(row["pair_index"], row["mode"]): row for row in image_rows}
    font = load_font(14)
    small_font = load_font(12)

    sheet = Image.new(
        "RGB",
        (pad + len(modes) * (thumb_w + pad), pad + len(pair_indices) * (thumb_h + label_h + pad)),
        "white",
    )
    draw = ImageDraw.Draw(sheet)
    for y_idx, pair_index in enumerate(pair_indices):
        y = pad + y_idx * (thumb_h + label_h + pad)
        for x_idx, mode in enumerate(modes):
            row = by_key.get((pair_index, mode))
            if row is None:
                continue
            x = pad + x_idx * (thumb_w + pad)
            image = Image.open(row["local_path"]).convert("RGB")
            image.thumbnail((thumb_w, thumb_h), Image.Resampling.LANCZOS)
            sheet.paste(image, (x, y))
            draw.text((x, y + thumb_h + 4), mode, fill=(15, 23, 42), font=font)
            draw.text((x, y + thumb_h + 24), f"{row['server_s']:.2f}s server", fill=(71, 85, 105), font=small_font)
            sim = row.get("teleport_approx_similarity")
            if sim is not None:
                draw.text((x, y + thumb_h + 42), f"sim {sim:.3f}", fill=(71, 85, 105), font=small_font)
    sheet.save(output_path, quality=92)


def markdown_report(report: dict, output_dir: Path) -> str:
    lines = [
        "# Z-Image Approximate Latent Teleport Eval",
        "",
        f"- generated: `{report['timestamp']}`",
        f"- output: `{output_dir}`",
        f"- steps: `{report['steps']}`",
        f"- start step: `{report['start_step']}`",
        f"- size: `{report['width']}x{report['height']}`",
        f"- min similarity: `{report['min_similarity']}`",
        f"- contact sheet: [contact_sheet.jpg](contact_sheet.jpg)",
        "",
        "| Pair | Source prime s | Target full s | Target approx s | Approx hit | Similarity | PSNR | MSE | Image |",
        "| ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | --- |",
    ]
    for row in report["quality"]:
        psnr = "inf" if math.isinf(row["psnr_db"]) else f"{row['psnr_db']:.2f}"
        sim = row.get("teleport_approx_similarity")
        sim_text = "" if sim is None else f"{sim:.3f}"
        lines.append(
            f"| {row['pair_index']} | {row['source_server_s']:.3f} | {row['baseline_server_s']:.3f} | "
            f"{row['approx_server_s']:.3f} | {row['teleport_approx_cache_hit']} | {sim_text} | "
            f"{psnr} | {row['mse']:.6f} | [{Path(row['approx_local_path']).name}]({Path(row['approx_local_path']).name}) |"
        )
    return "\n".join(lines) + "\n"


def parse_pair(raw: str) -> tuple[str, str]:
    if "||" not in raw:
        raise argparse.ArgumentTypeError("pairs must use 'source || target'")
    source, target = raw.split("||", 1)
    source = source.strip()
    target = target.strip()
    if not source or not target:
        raise argparse.ArgumentTypeError("source and target prompts must be non-empty")
    return source, target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8100")
    parser.add_argument("--secret", default="cutedsl2024")
    parser.add_argument("--output-dir", default="evals")
    parser.add_argument("--pair", action="append", type=parse_pair, default=[])
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--start-step", type=int, default=None)
    parser.add_argument("--min-similarity", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--low-priority", action="store_true")
    args = parser.parse_args()

    pairs = args.pair or DEFAULT_PAIRS
    stamp = now_slug()
    run_dir = Path(args.output_dir) / f"zimage_approx_teleport_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    quality_rows: list[dict] = []

    def call(pair_index: int, prompt: str, mode: str, save_name: str, teleport: bool, approx: bool) -> dict:
        params: dict[str, object] = {
            "prompt": prompt,
            "width": args.width,
            "height": args.height,
            "model": "zimage-turbo",
            "auto_lora": "false",
            "teleport": "true" if teleport else "false",
            "teleport_approx": "true" if approx else "false",
            "teleport_approx_min_sim": args.min_similarity,
            "perf": "true",
            "secret": args.secret,
            "save_path": f"evals/{stamp}/{save_name}.webp",
            "num_inference_steps": args.steps,
            "low_priority": "true" if args.low_priority else "false",
        }
        if args.start_step is not None:
            params["teleport_start_step"] = args.start_step
        payload, wall_s = request_json(args.base_url, params, args.timeout)
        perf = payload.get("perf", {})
        image = fetch_image(payload["path"], args.timeout)
        local_path = run_dir / f"{save_name}.webp"
        image.save(local_path, format="WEBP", quality=92)
        row = {
            "pair_index": pair_index,
            "prompt": prompt,
            "mode": mode,
            "requested_steps": args.steps,
            "effective_steps": perf.get("steps", args.steps),
            "wall_s": wall_s,
            "server_s": perf.get("inference_time_ms", 0) / 1000.0,
            "upload_s": perf.get("upload_time_ms", 0) / 1000.0,
            "encode_s": perf.get("encode_time_ms", 0) / 1000.0,
            "teleport_method": perf.get("teleport_method"),
            "teleport_cache_hit": perf.get("teleport_cache_hit"),
            "teleport_approx_cache_hit": perf.get("teleport_approx_cache_hit"),
            "teleport_approx_similarity": perf.get("teleport_approx_similarity"),
            "teleport_approx_source": perf.get("teleport_approx_source"),
            "teleport_capture_step": perf.get("teleport_capture_step"),
            "teleport_resume_step": perf.get("teleport_resume_step"),
            "remote_path": payload["path"],
            "local_path": str(local_path),
            "response": payload,
        }
        rows.append(row)
        print(json.dumps({
            "pair_index": pair_index,
            "mode": mode,
            "method": row["teleport_method"],
            "server_s": row["server_s"],
            "wall_s": round(wall_s, 3),
            "approx_hit": row["teleport_approx_cache_hit"],
            "approx_similarity": row["teleport_approx_similarity"],
            "local_path": str(local_path),
        }, sort_keys=True))
        return row

    for pair_index, (source_prompt, target_prompt) in enumerate(pairs):
        safe = f"pair{pair_index:02d}"
        source = call(pair_index, source_prompt, "source_prime", f"{safe}_source_prime_s{args.steps}", True, False)
        baseline = call(pair_index, target_prompt, "target_baseline", f"{safe}_target_baseline_s{args.steps}", False, False)
        approx = call(pair_index, target_prompt, "target_approx", f"{safe}_target_approx_s{args.steps}", True, True)
        metrics = image_metrics(
            Image.open(baseline["local_path"]).convert("RGB"),
            Image.open(approx["local_path"]).convert("RGB"),
        )
        quality_rows.append({
            "pair_index": pair_index,
            "source_prompt": source_prompt,
            "target_prompt": target_prompt,
            "source_server_s": source["server_s"],
            "baseline_server_s": baseline["server_s"],
            "approx_server_s": approx["server_s"],
            "baseline_local_path": baseline["local_path"],
            "approx_local_path": approx["local_path"],
            "teleport_method": approx["teleport_method"],
            "teleport_approx_cache_hit": approx["teleport_approx_cache_hit"],
            "teleport_approx_similarity": approx["teleport_approx_similarity"],
            "teleport_approx_source": approx["teleport_approx_source"],
            **metrics,
        })

    report = {
        "timestamp": stamp,
        "base_url": args.base_url,
        "width": args.width,
        "height": args.height,
        "steps": args.steps,
        "start_step": args.start_step,
        "min_similarity": args.min_similarity,
        "rows": rows,
        "quality": quality_rows,
    }
    contact_sheet(rows, run_dir / "contact_sheet.jpg")
    (run_dir / "results.json").write_text(json.dumps(report, indent=2, allow_nan=True))
    (run_dir / "report.md").write_text(markdown_report(report, run_dir))
    print(run_dir / "report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
