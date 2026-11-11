"""Eval the freshly trained app_logo_maker / product_screenshots LoRAs.

Waits until the live server exposes the new fixtures (next restart), then for
each LoRA generates domain prompts at several scales plus a no-LoRA baseline,
scores CLIP prompt alignment + aesthetics, saves images + results.
"""

from __future__ import annotations

import base64
import io
import json
import time
from pathlib import Path

import httpx
from PIL import Image

from suffix_sweep import SERVER, post_resilient, wait_for_server

OUT = Path("/nvme0n1-disk/tmp/new_lora_eval")
SCALES = [0.8, 1.0, 1.2]
SEEDS = [0, 1]

SUITES = {
    "app_logo_maker": [
        "logo for a coffee shop called Bean There",
        "minimal logo for an AI startup, brain and circuit motif",
        "logo for a kids toy store, playful bear mascot",
        "logo for a fitness app, dynamic running figure",
    ],
    "product_screenshots": [
        "screenshot of a project management dashboard with kanban board",
        "screenshot of a music streaming app now-playing screen",
        "screenshot of an online banking app account overview",
        "screenshot of a travel booking website search results page",
    ],
}


def wait_for_fixture(client: httpx.Client, lora_id: str, max_wait_s: int = 48 * 3600) -> bool:
    deadline = time.time() + max_wait_s
    while time.time() < deadline:
        try:
            data = client.get(f"{SERVER}/loras", timeout=15).json()
            if any(l["id"] == lora_id for l in data.get("loras", [])):
                return True
        except Exception:
            pass
        time.sleep(60)
    return False


def main() -> None:
    from aesthetic_score import get_scorer

    scorer = get_scorer()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    with httpx.Client() as client:
        wait_for_server(client)
        if not wait_for_fixture(client, "app_logo_maker"):
            print("fixtures never appeared; giving up")
            return
        print("new fixtures live; running eval", flush=True)

        for lora_id, prompts in SUITES.items():
            for prompt in prompts:
                for seed in SEEDS:
                    configs = [("baseline", None)] + [(f"scale_{s}", s) for s in SCALES]
                    for tag, scale in configs:
                        payload = {
                            "prompt": prompt, "seed": seed, "enhance_prompt": False,
                            "quality_retry": False, "low_priority": True,
                        }
                        if scale is None:
                            payload["auto_lora"] = False
                        else:
                            payload.update({"lora_id": lora_id, "auto_lora": False,
                                            "lora_scale": scale})
                        data = post_resilient(client, f"{SERVER}/generate_image", payload)
                        if data is None:
                            print(f"FAIL {lora_id} {tag} {prompt[:30]}", flush=True)
                            continue
                        img = Image.open(io.BytesIO(base64.b64decode(data["image_base64"]))).convert("RGB")
                        emb, aes = scorer.embed_and_score([img])
                        clip = float(scorer.embed_texts([prompt])[0] @ emb[0])
                        rows.append({"lora": lora_id, "prompt": prompt, "seed": seed,
                                     "config": tag, "clip": round(clip, 4),
                                     "aesthetic": round(aes[0], 3)})
                        name = f"{lora_id}_{prompt[:28].replace(' ', '_')}_{tag}_s{seed}.webp"
                        (OUT / name).write_bytes(base64.b64decode(data["image_base64"]))
                        print(rows[-1], flush=True)

    (OUT / "results.json").write_text(json.dumps(rows, indent=2))
    import statistics as st
    for lora_id in SUITES:
        for tag in ["baseline"] + [f"scale_{s}" for s in SCALES]:
            sel = [r for r in rows if r["lora"] == lora_id and r["config"] == tag]
            if sel:
                print(lora_id, tag,
                      "clip", round(st.mean(r["clip"] for r in sel), 4),
                      "aes", round(st.mean(r["aesthetic"] for r in sel), 3), flush=True)


if __name__ == "__main__":
    main()
