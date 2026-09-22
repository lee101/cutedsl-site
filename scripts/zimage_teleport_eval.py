#!/usr/bin/env python3
"""Evaluate exact-prompt latent teleport replay for Z-Image upload generation.

For each prompt this writes:
  - full baseline image
  - teleport prime image, which populates the latent cache
  - one or more teleport replay images

The replay image is compared against the full baseline. With exact-prompt
teleport and deterministic settings, quality should be identical or very close
while server inference time should drop by skipping early denoising steps.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen

import numpy as np
from PIL import Image, ImageDraw, ImageFont


DEFAULT_PROMPTS = [
    "minecraft dirt block inventory icon, centered, crisp pixel game asset, plain background",
    "cinematic product photo of a translucent glass robot toy on a white seamless studio background",
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


def summarize(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    return {
        "min": min(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "max": max(values),
    }


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
    label_h = 48
    modes = ["baseline", "teleport_prime", "teleport_replay"]
    prompt_indices = sorted({row["prompt_index"] for row in image_rows})
    by_key = {(row["prompt_index"], row["mode"]): row for row in image_rows}
    font = load_font(14)
    small_font = load_font(12)

    sheet = Image.new(
        "RGB",
        (pad + len(modes) * (thumb_w + pad), pad + len(prompt_indices) * (thumb_h + label_h + pad)),
        "white",
    )
    draw = ImageDraw.Draw(sheet)
    for y_idx, prompt_index in enumerate(prompt_indices):
        y = pad + y_idx * (thumb_h + label_h + pad)
        for x_idx, mode in enumerate(modes):
            row = by_key.get((prompt_index, mode))
            if row is None:
                continue
            x = pad + x_idx * (thumb_w + pad)
            image = Image.open(row["local_path"]).convert("RGB")
            image.thumbnail((thumb_w, thumb_h), Image.Resampling.LANCZOS)
            sheet.paste(image, (x, y))
            step_label = row.get("effective_steps", row.get("requested_steps", ""))
            draw.text((x, y + thumb_h + 4), f"{step_label} steps {mode}", fill=(15, 23, 42), font=font)
            draw.text((x, y + thumb_h + 24), f"{row['server_s']:.2f}s server", fill=(71, 85, 105), font=small_font)
    sheet.save(output_path, quality=92)


def markdown_report(report: dict, output_dir: Path) -> str:
    lines = [
        "# Z-Image Latent Teleport Eval",
        "",
        f"- generated: `{report['timestamp']}`",
        f"- output: `{output_dir}`",
        f"- requested steps: `{report['steps']}`",
        f"- teleport start step: `{report.get('teleport_start_step')}`",
        f"- effective steps: `{report['effective_steps']}`",
        f"- size: `{report['width']}x{report['height']}`",
        f"- contact sheet: [contact_sheet.jpg](contact_sheet.jpg)",
        "",
        "## Latency",
        "",
        "| Mode | Runs | Server median (s) | Wall median (s) | Upload median (s) |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for mode, stats in report["summary"].items():
        lines.append(
            f"| {mode} | {stats['runs']} | {stats['server_s']['median']:.3f} | "
            f"{stats['wall_s']['median']:.3f} | {stats['upload_s']['median']:.3f} |"
        )
    lines.extend([
        "",
        "## Quality",
        "",
        "| Prompt | Replay server s | PSNR to baseline | MSE | Identical | Image |",
        "| --- | ---: | ---: | ---: | --- | --- |",
    ])
    for row in report["quality"]:
        psnr = "inf" if math.isinf(row["psnr_db"]) else f"{row['psnr_db']:.2f}"
        lines.append(
            f"| `{row['prompt'][:72]}` | {row['replay_server_s']:.3f} | {psnr} | "
            f"{row['mse']:.6f} | {row['identical']} | [{Path(row['replay_local_path']).name}]({Path(row['replay_local_path']).name}) |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8100")
    parser.add_argument("--secret", default="cutedsl2024")
    parser.add_argument("--output-dir", default="evals")
    parser.add_argument("--prompt", action="append", default=[])
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--teleport-start-step", type=int, default=None)
    parser.add_argument("--replays", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--low-priority", action="store_true")
    args = parser.parse_args()

    prompts = args.prompt or DEFAULT_PROMPTS
    stamp = now_slug()
    run_dir = Path(args.output_dir) / f"zimage_teleport_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    quality_rows: list[dict] = []

    def call(prompt_index: int, prompt: str, mode: str, save_name: str, teleport: bool) -> dict:
        params: dict[str, object] = {
            "prompt": prompt,
            "width": args.width,
            "height": args.height,
            "model": "zimage-turbo",
            "auto_lora": "false",
            "teleport": "true" if teleport else "false",
            "perf": "true",
            "secret": args.secret,
            "save_path": f"evals/{stamp}/{save_name}.webp",
            "num_inference_steps": args.steps,
            "low_priority": "true" if args.low_priority else "false",
        }
        if args.teleport_start_step is not None:
            params["teleport_start_step"] = args.teleport_start_step
        payload, wall_s = request_json(args.base_url, params, args.timeout)
        perf = payload.get("perf", {})
        image = fetch_image(payload["path"], args.timeout)
        local_path = run_dir / f"{save_name}.webp"
        image.save(local_path, format="WEBP", quality=92)
        row = {
            "prompt_index": prompt_index,
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
            "teleport_capture_step": perf.get("teleport_capture_step"),
            "teleport_resume_step": perf.get("teleport_resume_step"),
            "remote_path": payload["path"],
            "local_path": str(local_path),
            "response": payload,
        }
        rows.append(row)
        print(json.dumps({
            "prompt_index": prompt_index,
            "mode": mode,
            "server_s": row["server_s"],
            "wall_s": round(wall_s, 3),
            "teleport_cache_hit": row["teleport_cache_hit"],
            "local_path": str(local_path),
        }, sort_keys=True))
        return row

    for prompt_index, prompt in enumerate(prompts):
        safe = f"prompt{prompt_index:02d}"
        baseline = call(prompt_index, prompt, "baseline", f"{safe}_baseline_s{args.steps}", False)
        call(prompt_index, prompt, "teleport_prime", f"{safe}_prime_s{args.steps}", True)
        replay = None
        for replay_index in range(args.replays):
            replay = call(
                prompt_index,
                prompt,
                "teleport_replay",
                f"{safe}_replay{replay_index:02d}_s{args.steps}",
                True,
            )
        if replay is not None:
            metrics = image_metrics(
                Image.open(baseline["local_path"]).convert("RGB"),
                Image.open(replay["local_path"]).convert("RGB"),
            )
            quality_rows.append({
                "prompt_index": prompt_index,
                "prompt": prompt,
                "baseline_local_path": baseline["local_path"],
                "replay_local_path": replay["local_path"],
                "replay_server_s": replay["server_s"],
                **metrics,
            })

    summary = {}
    for mode in ("baseline", "teleport_prime", "teleport_replay"):
        mode_rows = [row for row in rows if row["mode"] == mode]
        if mode_rows:
            summary[mode] = {
                "runs": len(mode_rows),
                "wall_s": summarize([row["wall_s"] for row in mode_rows]),
                "server_s": summarize([row["server_s"] for row in mode_rows]),
                "upload_s": summarize([row["upload_s"] for row in mode_rows]),
            }

    report = {
        "timestamp": stamp,
        "base_url": args.base_url,
        "width": args.width,
        "height": args.height,
        "steps": args.steps,
        "effective_steps": sorted({row["effective_steps"] for row in rows}),
        "replays": args.replays,
        "teleport_start_step": args.teleport_start_step,
        "rows": rows,
        "quality": quality_rows,
        "summary": summary,
    }
    contact_sheet(rows, run_dir / "contact_sheet.jpg")
    (run_dir / "results.json").write_text(json.dumps(report, indent=2, allow_nan=True))
    (run_dir / "report.md").write_text(markdown_report(report, run_dir))
    print(run_dir / "report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
