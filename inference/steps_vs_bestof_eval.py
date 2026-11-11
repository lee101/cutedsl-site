"""Same-latency config eval: 8 steps x1 vs 4 steps x2 with aesthetic rerank."""

from __future__ import annotations

import json
import statistics as st
import sys

import httpx

from quality_probe import PROMPT_BANK
from suffix_sweep import post_resilient, wait_for_server, SERVER

CONFIGS = {
    "s8_x1": {"num_inference_steps": 8, "best_of": 1},
    "s6_x1": {"num_inference_steps": 6, "best_of": 1},
    "s5_x1": {"num_inference_steps": 5, "best_of": 1},
}
SEEDS = [7, 17, 27]


def main() -> None:
    prompts = [(cat, ps[i], seed)
               for cat, ps in PROMPT_BANK.items() for i in (0, 4) for seed in SEEDS]
    rows = []
    with httpx.Client() as client:
        wait_for_server(client)
        for name, cfg in CONFIGS.items():
            for cat, prompt, seed in prompts:
                data = post_resilient(client, f"{SERVER}/generate_image", {
                    "prompt": prompt, "seed": seed,
                    "enhance_prompt": False, "score_aesthetic": True,
                    "quality_retry": False, "low_priority": True, **cfg,
                })
                if data is None:
                    print(f"FAIL {name} {cat}", flush=True)
                    continue
                score = data.get("aesthetic_score")
                if score is None and data.get("best_of"):
                    scores = [s for s in data["best_of"].get("scores", []) if s]
                    score = max(scores) if scores else None
                rows.append({
                    "config": name, "category": cat, "prompt": prompt,
                    "score": score, "ms": data.get("inference_time_ms"),
                })
                print(name, cat, score, data.get("inference_time_ms"), "ms", flush=True)

    summary = {}
    for name in CONFIGS:
        s = [r["score"] for r in rows if r["config"] == name and r["score"] is not None]
        ms = [r["ms"] for r in rows if r["config"] == name and r["ms"]]
        if s:
            summary[name] = {"n": len(s), "mean": round(st.mean(s), 3),
                             "median": round(st.median(s), 3),
                             "min": round(min(s), 2), "max": round(max(s), 2),
                             "mean_ms": int(st.mean(ms)) if ms else None}
    out = sys.argv[1] if len(sys.argv) > 1 else "steps_vs_bestof.json"
    json.dump({"summary": summary, "rows": rows}, open(out, "w"), indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
