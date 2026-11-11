"""Sweep candidate aesthetic suffixes and rank them with the aesthetic scorer."""

from __future__ import annotations

import json
import statistics as st
import sys

import httpx

from aesthetic_eval import PROMPTS

SERVER = "http://127.0.0.1:8100"
SEEDS = 2


def wait_for_server(client: httpx.Client, max_wait_s: int = 1800) -> bool:
    import time
    deadline = time.time() + max_wait_s
    while time.time() < deadline:
        try:
            if client.get(f"{SERVER}/healthz", timeout=5).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(10)
    return False


def post_resilient(client: httpx.Client, url: str, payload: dict) -> dict | None:
    for attempt in range(3):
        try:
            resp = client.post(url, json=payload, timeout=600)
            resp.raise_for_status()
            return resp.json()
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError):
            if not wait_for_server(client):
                return None
        except Exception:
            return None
    return None

VARIANTS = {
    "none": {"person": "", "scene": ""},
    "current": {
        "person": ", attractive and photogenic, natural flawless skin, sharp expressive eyes, flattering soft light, well-composed",
        "scene": ", beautiful atmospheric lighting, rich harmonious colors, intricate detail, striking composition",
    },
    "photo": {
        "person": ", a gorgeous photogenic subject with a symmetrical attractive face and glowing skin, professional photography with cinematic soft lighting and shallow depth of field",
        "scene": ", bathed in golden hour cinematic light, epic composition with crisp detail and vivid natural colors",
    },
    "artistic": {
        "person": ", stunningly beautiful, radiant, captured in dramatic painterly light with exquisite detail, award-winning portrait",
        "scene": ", breathtaking dramatic light and shadow, exquisite detail, award-winning landscape photography",
    },
}


def main() -> None:
    rows = []
    with httpx.Client() as client:
        for variant, suffixes in VARIANTS.items():
            for category, prompts in PROMPTS.items():
                for pi, prompt in enumerate(prompts):
                    for seed in range(SEEDS):
                        full = prompt + suffixes[category]
                        data = post_resilient(client, f"{SERVER}/generate_image", {
                            "prompt": full, "seed": seed,
                            "enhance_prompt": False, "score_aesthetic": True,
                            "quality_retry": True, "low_priority": True,
                        })
                        if data is None:
                            print(f"FAIL {variant} {category} {pi} {seed}", flush=True)
                            continue
                        rows.append({
                            "variant": variant, "category": category,
                            "prompt": prompt, "seed": seed,
                            "score": data.get("aesthetic_score"),
                            "warning": data.get("quality_warning"),
                        })
                        print(variant, category, pi, seed, rows[-1]["score"], flush=True)

    out = {"rows": rows, "summary": {}}
    for variant in VARIANTS:
        for category in PROMPTS:
            s = [r["score"] for r in rows
                 if r["variant"] == variant and r["category"] == category
                 and r["score"] is not None]
            if s:
                out["summary"][f"{variant}/{category}"] = {
                    "mean": round(st.mean(s), 3), "median": round(st.median(s), 3),
                    "min": round(min(s), 2), "max": round(max(s), 2), "n": len(s),
                }
    json.dump(out, open(sys.argv[1] if len(sys.argv) > 1 else "suffix_sweep.json", "w"), indent=2)
    print(json.dumps(out["summary"], indent=2))


if __name__ == "__main__":
    main()
