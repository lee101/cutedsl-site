#!/usr/bin/env python3
"""Generate local visual evals for Z-Image step-count sweeps.

Default output is 2 prompts x 5 step counts = 10 images in evals/<timestamp>/.
The highest configured step count is treated as the visual gold/reference for
each prompt and lower-step outputs get lightweight pixel metrics against it.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import math
import statistics
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
from PIL import Image, ImageDraw, ImageFont


DEFAULT_PROMPTS = [
    "minecraft dirt block inventory icon, centered, crisp pixel game asset, plain background",
    "cinematic product photo of a translucent glass robot toy on a white seamless studio background",
]


@dataclass
class EvalImage:
    prompt_index: int
    prompt: str
    step: int
    seed: int
    wall_s: float
    inference_ms: int
    width: int
    height: int
    image_path: Path
    response: dict
    mse_to_gold: float | None = None
    mae_to_gold: float | None = None
    psnr_to_gold_db: float | None = None


def now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def parse_steps(raw: str) -> list[int]:
    steps = []
    for part in raw.split(","):
        value = int(part.strip())
        if value <= 0:
            raise argparse.ArgumentTypeError("steps must be positive integers")
        steps.append(value)
    return sorted(set(steps))


def post_json(base_url: str, payload: dict, timeout: float) -> tuple[dict, float]:
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}/generate_image",
        data=body,
        headers={"content-type": "application/json", "accept": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    with urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data, time.perf_counter() - started


def decode_webp(image_base64: str) -> bytes:
    return base64.b64decode(image_base64)


def image_metrics(candidate: Path, gold: Path) -> tuple[float, float, float]:
    cand = np.asarray(Image.open(candidate).convert("RGB"), dtype=np.float32)
    ref = np.asarray(Image.open(gold).convert("RGB"), dtype=np.float32)
    diff = cand - ref
    mse = float(np.mean(diff * diff))
    mae = float(np.mean(np.abs(diff)))
    psnr = float("inf") if mse == 0 else float(20 * math.log10(255.0 / math.sqrt(mse)))
    return mse, mae, psnr


def summary(values: list[float]) -> dict[str, float]:
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


def contact_sheet(rows: list[EvalImage], steps: list[int], output_path: Path) -> None:
    if not rows:
        return
    first = Image.open(rows[0].image_path).convert("RGB")
    thumb_w = 240
    thumb_h = max(1, round(first.height * (thumb_w / first.width)))
    label_h = 44
    pad = 12
    font = load_font(15)
    small_font = load_font(12)

    by_prompt: dict[int, list[EvalImage]] = {}
    for row in rows:
        by_prompt.setdefault(row.prompt_index, []).append(row)

    sheet_w = pad + len(steps) * (thumb_w + pad)
    sheet_h = pad + len(by_prompt) * (thumb_h + label_h + pad)
    sheet = Image.new("RGB", (sheet_w, sheet_h), "white")
    draw = ImageDraw.Draw(sheet)

    for row_idx, prompt_index in enumerate(sorted(by_prompt)):
        prompt_rows = {row.step: row for row in by_prompt[prompt_index]}
        y = pad + row_idx * (thumb_h + label_h + pad)
        for col_idx, step in enumerate(steps):
            row = prompt_rows.get(step)
            if row is None:
                continue
            x = pad + col_idx * (thumb_w + pad)
            image = Image.open(row.image_path).convert("RGB")
            image.thumbnail((thumb_w, thumb_h), Image.Resampling.LANCZOS)
            sheet.paste(image, (x, y))
            draw.text((x, y + thumb_h + 4), f"{step} steps, {row.inference_ms / 1000:.2f}s", fill=(15, 23, 42), font=font)
            metric = "" if row.psnr_to_gold_db is None else f"PSNR {row.psnr_to_gold_db:.1f} dB"
            draw.text((x, y + thumb_h + 24), metric, fill=(71, 85, 105), font=small_font)

    sheet.save(output_path, quality=92)


def markdown_report(rows: list[EvalImage], steps: list[int], output_dir: Path, contact_path: Path) -> str:
    lines = [
        "# Z-Image Step Eval",
        "",
        f"- generated: `{now_slug()}`",
        f"- output: `{output_dir}`",
        f"- steps: `{','.join(str(step) for step in steps)}`",
        f"- gold/reference step: `{max(steps)}`",
        f"- contact sheet: [{contact_path.name}]({contact_path.name})",
        "",
        "## Latency",
        "",
        "| Step | Runs | Inference median (s) | Wall median (s) |",
        "| ---: | ---: | ---: | ---: |",
    ]
    for step in steps:
        step_rows = [row for row in rows if row.step == step]
        inf_s = [row.inference_ms / 1000.0 for row in step_rows]
        wall_s = [row.wall_s for row in step_rows]
        lines.append(
            f"| {step} | {len(step_rows)} | {summary(inf_s).get('median', 0):.3f} | "
            f"{summary(wall_s).get('median', 0):.3f} |"
        )

    lines.extend([
        "",
        "## Images",
        "",
        "| Prompt | Step | Inference s | PSNR to gold | Image |",
        "| --- | ---: | ---: | ---: | --- |",
    ])
    for row in rows:
        psnr = "" if row.psnr_to_gold_db is None else ("inf" if math.isinf(row.psnr_to_gold_db) else f"{row.psnr_to_gold_db:.2f}")
        prompt = row.prompt[:72].replace("|", "\\|")
        rel = row.image_path.name
        lines.append(
            f"| `{prompt}` | {row.step} | {row.inference_ms / 1000:.3f} | {psnr} | "
            f"[{rel}]({rel}) |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8100")
    parser.add_argument("--output-dir", default="evals")
    parser.add_argument("--steps", type=parse_steps, default=parse_steps("4,8,12,16,20"))
    parser.add_argument("--prompt", action="append", default=[])
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--auto-lora", action="store_true", help="enable existing auto LoRA selection")
    parser.add_argument("--lora-id", default=None, help="explicit LoRA id to test")
    parser.add_argument("--low-priority", action="store_true")
    args = parser.parse_args()

    prompts = args.prompt or DEFAULT_PROMPTS
    run_dir = Path(args.output_dir) / f"zimage_steps_{now_slug()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    rows: list[EvalImage] = []

    for prompt_index, prompt in enumerate(prompts):
        seed = args.seed + prompt_index
        for step in args.steps:
            payload = {
                "prompt": prompt,
                "width": args.width,
                "height": args.height,
                "seed": seed,
                "num_inference_steps": step,
                "guidance_scale": 0.0,
                "auto_lora": args.auto_lora,
                "lora_id": args.lora_id,
                "low_priority": args.low_priority,
            }
            response, wall_s = post_json(args.base_url, payload, args.timeout)
            image_bytes = decode_webp(response["image_base64"])
            image_path = run_dir / f"prompt{prompt_index:02d}_step{step:02d}_seed{seed}.webp"
            image_path.write_bytes(image_bytes)
            row = EvalImage(
                prompt_index=prompt_index,
                prompt=prompt,
                step=step,
                seed=seed,
                wall_s=wall_s,
                inference_ms=int(response.get("inference_time_ms", 0)),
                width=int(response.get("width", args.width)),
                height=int(response.get("height", args.height)),
                image_path=image_path,
                response=response,
            )
            rows.append(row)
            print(json.dumps({
                "prompt_index": prompt_index,
                "step": step,
                "seed": seed,
                "wall_s": round(wall_s, 3),
                "inference_ms": row.inference_ms,
                "image": str(image_path),
            }, sort_keys=True))

    gold_step = max(args.steps)
    for prompt_index in range(len(prompts)):
        gold_rows = [row for row in rows if row.prompt_index == prompt_index and row.step == gold_step]
        if not gold_rows:
            continue
        gold = gold_rows[0].image_path
        for row in rows:
            if row.prompt_index != prompt_index or row.step == gold_step:
                continue
            row.mse_to_gold, row.mae_to_gold, row.psnr_to_gold_db = image_metrics(row.image_path, gold)

    contact_path = run_dir / "contact_sheet.jpg"
    contact_sheet(rows, args.steps, contact_path)

    report = {
        "base_url": args.base_url,
        "width": args.width,
        "height": args.height,
        "seed": args.seed,
        "steps": args.steps,
        "gold_step": gold_step,
        "prompts": prompts,
        "rows": [
            {
                "prompt_index": row.prompt_index,
                "prompt": row.prompt,
                "step": row.step,
                "seed": row.seed,
                "wall_s": row.wall_s,
                "inference_ms": row.inference_ms,
                "width": row.width,
                "height": row.height,
                "image_path": str(row.image_path),
                "mse_to_gold": row.mse_to_gold,
                "mae_to_gold": row.mae_to_gold,
                "psnr_to_gold_db": row.psnr_to_gold_db,
                "lora": row.response.get("lora"),
                "quality_retry": row.response.get("quality_retry"),
                "quality_warning": row.response.get("quality_warning"),
            }
            for row in rows
        ],
    }
    (run_dir / "results.json").write_text(json.dumps(report, indent=2, allow_nan=True))
    (run_dir / "report.md").write_text(markdown_report(rows, args.steps, run_dir, contact_path))
    print(run_dir / "report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
