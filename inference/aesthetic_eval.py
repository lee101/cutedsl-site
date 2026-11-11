"""A/B eval: baseline vs enhanced prompts, ranked by the aesthetic scorer.

Usage:
  python aesthetic_eval.py [--server http://127.0.0.1:8100] [--out DIR]
      [--seeds 2] [--best-of 1] [--save-images]
"""

from __future__ import annotations

import argparse
import base64
import json
import statistics
import time
from pathlib import Path

import httpx

PROMPTS = {
    "person": [
        "a woman reading a book in a cozy cafe",
        "portrait of an old fisherman",
        "a young man playing guitar on a rooftop at dusk",
        "an elf queen in a silver gown",
        "a chef plating a dish in a busy kitchen",
        "two friends laughing at a street market",
    ],
    "scene": [
        "misty mountain lake at sunrise",
        "a narrow tokyo alley in the rain at night",
        "an ancient library with towering shelves",
        "a lighthouse on a cliff during a storm",
        "rolling lavender fields under a summer sky",
        "a futuristic city skyline at golden hour",
    ],
}


def generate(client: httpx.Client, server: str, prompt: str, seed: int,
             enhance: bool, best_of: int) -> dict:
    t0 = time.time()
    resp = client.post(f"{server}/generate_image", json={
        "prompt": prompt,
        "seed": seed,
        "enhance_prompt": enhance,
        "best_of": best_of,
        "score_aesthetic": True,
        "quality_retry": best_of <= 1,
        "low_priority": True,
    }, timeout=600)
    resp.raise_for_status()
    data = resp.json()
    data["wall_time_s"] = round(time.time() - t0, 2)
    return data


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:8100")
    ap.add_argument("--out", default="aesthetic_eval_results")
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--best-of", type=int, default=1)
    ap.add_argument("--save-images", action="store_true")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    with httpx.Client() as client:
        for category, prompts in PROMPTS.items():
            for pi, prompt in enumerate(prompts):
                for seed in range(args.seeds):
                    for enhance in (False, True):
                        try:
                            data = generate(client, args.server, prompt, seed,
                                            enhance, args.best_of)
                        except Exception as e:
                            print(f"FAIL {category}/{pi} seed={seed} enhance={enhance}: {e}")
                            continue
                        row = {
                            "category": category,
                            "prompt": prompt,
                            "prompt_used": data.get("prompt_used"),
                            "seed": seed,
                            "enhance": enhance,
                            "best_of": args.best_of,
                            "aesthetic_score": data.get("aesthetic_score"),
                            "quality_warning": data.get("quality_warning"),
                            "inference_time_ms": data.get("inference_time_ms"),
                            "wall_time_s": data.get("wall_time_s"),
                            "lora": (data.get("lora") or {}).get("lora_id"),
                            "best_of_meta": data.get("best_of"),
                        }
                        rows.append(row)
                        print(f"{category}/{pi} seed={seed} enhance={int(enhance)} "
                              f"score={row['aesthetic_score']} {row['wall_time_s']}s")
                        if args.save_images:
                            name = f"{category}_{pi}_s{seed}_e{int(enhance)}.webp"
                            (out_dir / name).write_bytes(
                                base64.b64decode(data["image_base64"]))

    summary = {}
    for enhance in (False, True):
        scores = [r["aesthetic_score"] for r in rows
                  if r["enhance"] is enhance and r["aesthetic_score"] is not None]
        if scores:
            summary["enhanced" if enhance else "baseline"] = {
                "n": len(scores),
                "mean": round(statistics.mean(scores), 3),
                "median": round(statistics.median(scores), 3),
                "min": round(min(scores), 3),
                "max": round(max(scores), 3),
            }
    wins = 0
    pairs = 0
    for r in rows:
        if not r["enhance"] or r["aesthetic_score"] is None:
            continue
        base = next((b for b in rows if not b["enhance"]
                     and b["prompt"] == r["prompt"] and b["seed"] == r["seed"]
                     and b["aesthetic_score"] is not None), None)
        if base:
            pairs += 1
            wins += r["aesthetic_score"] > base["aesthetic_score"]
    if pairs:
        summary["enhanced_win_rate"] = round(wins / pairs, 3)

    result = {"summary": summary, "rows": rows}
    (out_dir / "results.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
