"""Instruction-following / composition eval + per-LoRA strength tuning.

Each scene has a prompt and contrast groups: the image's CLIP embedding must be
closer to the target phrasing than to every distractor (count errors, missing
subjects, wrong style). Reports contrast accuracy, CLIPScore, and aesthetic
score; optionally sweeps lora_scale per LoRA to find the strength that keeps
instructions intact while adding style.

Usage:
  python instruction_eval.py [--seeds 2] [--enhance both|on|off]
      [--lora-sweep anime_serenity ...] [--scales 0.6 0.8 1.0 1.2]
      [--out /nvme0n1-disk/tmp/instruction_eval]
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import statistics as st
from pathlib import Path

import httpx
from PIL import Image

from suffix_sweep import SERVER, post_resilient, wait_for_server

SCENES = [
    {
        "id": "pelican_bike",
        "prompt": "a pelican riding a bicycle along a beach boardwalk",
        "contrasts": [
            ["a pelican riding a bicycle", "a pelican standing on the beach", "an empty bicycle on a boardwalk"],
            ["a bird on a bicycle", "a person on a bicycle"],
        ],
    },
    {
        "id": "two_girls_hug",
        "prompt": "two beautiful girls hugging in a sunlit park",
        "contrasts": [
            ["two girls hugging", "one girl standing alone", "a large group of people"],
            ["people embracing warmly", "people standing apart"],
        ],
    },
    {
        "id": "three_girls_anime",
        "prompt": "three girls anime style walking to school together",
        "contrasts": [
            ["three anime girls", "one anime girl", "two anime girls"],
            ["anime illustration", "a photorealistic photograph"],
        ],
    },
    {
        "id": "red_cube_blue_sphere",
        "prompt": "a red cube stacked on top of a blue sphere, studio product photo",
        "contrasts": [
            ["a red cube on top of a blue sphere", "a blue cube on top of a red sphere"],
            ["stacked geometric shapes", "scattered geometric shapes"],
        ],
    },
    {
        "id": "cat_astronaut_mars",
        "prompt": "a cat wearing an astronaut helmet standing on mars, oil painting style",
        "contrasts": [
            ["a cat in an astronaut helmet", "a dog in an astronaut helmet", "a cat without a helmet"],
            ["an oil painting", "a photograph"],
        ],
    },
    {
        "id": "chef_juggling",
        "prompt": "a chef juggling three oranges in a busy restaurant kitchen",
        "contrasts": [
            ["a chef juggling oranges", "a chef chopping vegetables"],
            ["oranges in the air", "oranges on a table"],
        ],
    },
    {
        "id": "knight_dragon_tea",
        "prompt": "a knight and a dragon having tea together at a small table, watercolor",
        "contrasts": [
            ["a knight and a dragon at a table", "a knight fighting a dragon"],
            ["a watercolor painting", "a 3d render"],
        ],
    },
    {
        "id": "robot_flowers",
        "prompt": "a rusty robot carefully watering a bed of pink tulips",
        "contrasts": [
            ["a robot watering flowers", "a robot crushing flowers", "a garden with no robot"],
            ["pink tulips", "yellow sunflowers"],
        ],
    },
    {
        "id": "two_dogs_one_cat",
        "prompt": "two golden retrievers and one black cat sitting on a porch",
        "contrasts": [
            ["two dogs and a cat", "one dog and two cats", "three dogs"],
            ["a black cat", "a white cat"],
        ],
    },
    {
        "id": "girl_red_umbrella",
        "prompt": "a girl in a yellow raincoat holding a red umbrella crossing a rainy street",
        "contrasts": [
            ["a yellow raincoat and a red umbrella", "a red raincoat and a yellow umbrella"],
            ["a rainy street scene", "a sunny street scene"],
        ],
    },
]


def decode(b64: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")


def eval_image(scorer, image: Image.Image, scene: dict) -> dict:
    img_emb, aesthetic = scorer.embed_and_score([image])
    img_emb = img_emb[0]
    checks, passed = 0, 0
    details = []
    for group in scene["contrasts"]:
        text_emb = scorer.embed_texts(group)
        sims = (text_emb @ img_emb).tolist()
        ok = all(sims[0] > s for s in sims[1:])
        checks += 1
        passed += ok
        details.append({"target": group[0], "sims": [round(s, 4) for s in sims], "pass": ok})
    prompt_emb = scorer.embed_texts([scene["prompt"]])[0]
    return {
        "clip_score": round(float(prompt_emb @ img_emb), 4),
        "aesthetic": round(aesthetic[0], 3),
        "contrast_pass": passed,
        "contrast_total": checks,
        "checks": details,
    }


def run_config(client, scorer, scene, seed, *, enhance=None, lora_id=None,
               lora_scale=None, save_dir: Path | None = None, tag="") -> dict | None:
    payload = {
        "prompt": scene["prompt"], "seed": seed, "score_aesthetic": False,
        "quality_retry": False, "low_priority": True,
    }
    if enhance is not None:
        payload["enhance_prompt"] = enhance
    if lora_id is not None:
        payload["lora_id"] = lora_id
        payload["auto_lora"] = False
        payload["lora_scale"] = lora_scale if lora_scale is not None else 1.0
    data = post_resilient(client, f"{SERVER}/generate_image", payload)
    if data is None:
        return None
    image = decode(data["image_base64"])
    result = eval_image(scorer, image, scene)
    result.update({"scene": scene["id"], "seed": seed, "lora": (data.get("lora") or {}).get("lora_id"),
                   "prompt_used": data.get("prompt_used")})
    if save_dir:
        (save_dir / f"{scene['id']}_{tag}_s{seed}.webp").write_bytes(
            base64.b64decode(data["image_base64"]))
    return result


def summarize(rows: list[dict]) -> dict:
    if not rows:
        return {}
    return {
        "n": len(rows),
        "contrast_acc": round(sum(r["contrast_pass"] for r in rows)
                              / max(1, sum(r["contrast_total"] for r in rows)), 3),
        "clip_score_mean": round(st.mean(r["clip_score"] for r in rows), 4),
        "aesthetic_mean": round(st.mean(r["aesthetic"] for r in rows), 3),
    }


def main() -> None:
    from aesthetic_score import get_scorer

    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--enhance", choices=["both", "on", "off"], default="both")
    ap.add_argument("--lora-sweep", nargs="*", default=[])
    ap.add_argument("--scales", type=float, nargs="*", default=[0.6, 0.8, 1.0, 1.2])
    ap.add_argument("--out", default="/nvme0n1-disk/tmp/instruction_eval")
    ap.add_argument("--save-images", action="store_true")
    args = ap.parse_args()

    scorer = get_scorer()
    assert scorer is not None
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    save_dir = out_dir if args.save_images else None

    results = {"configs": {}, "lora_sweep": {}}
    with httpx.Client() as client:
        wait_for_server(client)

        enhance_modes = {"both": [False, True], "on": [True], "off": [False]}[args.enhance]
        for enhance in enhance_modes:
            key = f"enhance_{'on' if enhance else 'off'}"
            rows = []
            for scene in SCENES:
                for seed in range(args.seeds):
                    r = run_config(client, scorer, scene, seed, enhance=enhance,
                                   save_dir=save_dir, tag=key)
                    if r:
                        rows.append(r)
                        print(f"{key} {scene['id']} s{seed} "
                              f"pass={r['contrast_pass']}/{r['contrast_total']} "
                              f"clip={r['clip_score']} aes={r['aesthetic']}", flush=True)
            results["configs"][key] = {"summary": summarize(rows), "rows": rows}

        for lora_id in args.lora_sweep:
            sweep = {}
            for scale in args.scales:
                rows = []
                for scene in SCENES:
                    for seed in range(args.seeds):
                        r = run_config(client, scorer, scene, seed, enhance=False,
                                       lora_id=lora_id, lora_scale=scale,
                                       save_dir=save_dir, tag=f"{lora_id}_{scale}")
                        if r:
                            rows.append(r)
                sweep[str(scale)] = {"summary": summarize(rows), "rows": rows}
                print(f"lora {lora_id} scale {scale}: {sweep[str(scale)]['summary']}", flush=True)
            results["lora_sweep"][lora_id] = sweep

    (out_dir / "results.json").write_text(json.dumps(results, indent=2))
    for key, cfg in results["configs"].items():
        print(key, cfg["summary"])
    for lora_id, sweep in results["lora_sweep"].items():
        for scale, cfg in sweep.items():
            print(lora_id, scale, cfg["summary"])


if __name__ == "__main__":
    main()
