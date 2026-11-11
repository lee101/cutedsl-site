"""Generate a diverse probe set at several step counts, upload to R2
(images.netwrck.com backend), and index aesthetic scores + CLIP embeddings.

Finds categories/prompts that degrade at few-step inference vs 20-step —
candidates for LoRA training or per-category step bumps.

Usage:
  python quality_probe.py [--server http://127.0.0.1:8100] [--steps 4 8 20]
      [--out /nvme0n1-disk/tmp/quality_probe] [--limit N] [--report-only]
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import statistics as st
from collections import defaultdict
from pathlib import Path

import httpx
import numpy as np
from PIL import Image

PROMPT_BANK = {
    "portrait_woman": [
        "a woman smiling at an outdoor cafe",
        "closeup portrait of a woman with freckles",
        "a businesswoman giving a presentation",
        "a woman hiking on a mountain trail",
        "an elderly woman knitting by a window",
        "a female astronaut inside a space station",
        "a woman dancing flamenco in a red dress",
        "a nurse at work in a bright hospital ward",
    ],
    "portrait_man": [
        "a man laughing with friends at a barbecue",
        "closeup portrait of a bearded fisherman",
        "a male chef tasting soup in a kitchen",
        "an old man playing chess in a park",
        "a rock climber resting on a cliff ledge",
        "a firefighter after a long shift",
        "a violinist performing on stage",
        "a farmer standing in a wheat field at dawn",
    ],
    "groups": [
        "three friends taking a selfie at a concert",
        "a family having a picnic under a tree",
        "a soccer team celebrating a goal",
        "coworkers brainstorming around a whiteboard",
        "a wedding party posing for photos",
        "children playing tag in a schoolyard",
        "a band performing in a small club",
        "tourists watching a street performer",
    ],
    "hands_detail": [
        "hands kneading bread dough on a floured table",
        "a potter shaping clay on a wheel, hands closeup",
        "hands playing piano, closeup",
        "a jeweler holding a ring with tweezers, macro",
        "two people shaking hands in an office",
        "a child's hands holding a ladybug",
        "hands typing on a mechanical keyboard",
        "an artist's paint-stained hands holding brushes",
    ],
    "anime": [
        "anime girl with silver hair in a cherry blossom garden",
        "anime boy hero with a glowing sword",
        "anime style cozy ramen shop interior at night",
        "chibi cat wizard casting a spell, anime style",
        "anime mecha robot standing in a ruined city",
        "anime schoolgirl running late with toast in mouth",
        "anime knight in ornate armor under moonlight",
        "anime style magical library with floating books",
    ],
    "fantasy": [
        "an elf queen on a crystal throne",
        "a dragon perched on a castle tower at sunset",
        "a wizard's study filled with glowing potions",
        "a dwarf blacksmith forging a magic axe",
        "a fairy village built into giant mushrooms",
        "a paladin facing a shadow demon in a cathedral",
        "a mermaid on a rock in a stormy sea",
        "a phoenix rising from embers in a dark forest",
    ],
    "scifi": [
        "a cyberpunk street market in neon rain",
        "a starship bridge with holographic displays",
        "an alien desert with two suns and a lone rover",
        "a robot bartender serving drinks to androids",
        "a space elevator seen from ground level",
        "an astronaut discovering ancient ruins on mars",
        "a megacity with flying cars at dusk",
        "a cryogenic lab with frosted glass pods",
    ],
    "animals": [
        "a red fox in fresh snow",
        "a golden retriever puppy chasing a ball",
        "a hummingbird hovering at a flower",
        "an octopus changing colors on a reef",
        "a lion pride resting under an acacia tree",
        "a barn owl in flight at twilight",
        "a tabby cat sleeping in a sunbeam",
        "an elephant calf playing in a river",
    ],
    "landscape": [
        "misty mountain lake at sunrise",
        "rolling tuscan hills with cypress trees",
        "a black sand beach with basalt columns",
        "northern lights over a frozen fjord",
        "a slot canyon with light beams",
        "terraced rice fields in morning fog",
        "a desert dune sea under the milky way",
        "a waterfall in a mossy rainforest gorge",
    ],
    "cityscape": [
        "a narrow tokyo alley in the rain at night",
        "paris rooftops at golden hour",
        "a venetian canal with gondolas at dawn",
        "times square in a snowstorm",
        "an old european square with a street market",
        "hong kong harbor skyline at blue hour",
        "a quiet suburban street in autumn",
        "an istanbul bazaar with hanging lamps",
    ],
    "interior_food": [
        "a cozy cabin interior with a fireplace",
        "a minimalist scandinavian living room",
        "an ornate baroque ballroom",
        "a sushi platter on black slate",
        "a rustic breakfast table with pancakes and berries",
        "a barista pouring latte art",
        "a chocolate cake slice with molten center",
        "a greenhouse dining room full of plants",
    ],
    "vehicles_architecture": [
        "a vintage red convertible on a coastal road",
        "a steam locomotive crossing a stone viaduct",
        "a sailboat racing in strong wind",
        "a futuristic bullet train at a station",
        "a gothic cathedral facade in detail",
        "a modern glass museum by a lake",
        "an ancient roman aqueduct at sunset",
        "a treehouse hotel in a redwood forest",
    ],
}


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:56]


def _wait_for_server(client: httpx.Client, server: str, max_wait_s: int = 1800) -> bool:
    import time
    deadline = time.time() + max_wait_s
    while time.time() < deadline:
        try:
            if client.get(f"{server}/healthz", timeout=5).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(10)
    return False


def generate_rows(args) -> list[dict]:
    rows = []
    todo = [(cat, p) for cat, prompts in PROMPT_BANK.items() for p in prompts]
    if args.limit:
        todo = todo[: args.limit]
    with httpx.Client() as client:
        for i, (cat, prompt) in enumerate(todo):
            for steps in args.steps:
                save_path = f"quality_probe/{cat}/{slugify(prompt)}_s{steps}.webp"
                url = None
                for attempt in range(3):
                    try:
                        resp = client.get(f"{args.server}/create_and_upload_image", params={
                            "prompt": prompt,
                            "save_path": save_path,
                            "num_inference_steps": steps,
                            "teleport": False,
                            "low_priority": True,
                            "secret": os.getenv("IMAGE_API_SECRET", ""),
                        }, timeout=900)
                        resp.raise_for_status()
                        url = resp.json()["path"]
                        break
                    except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
                        print(f"retry {cat} s{steps}: {e}", flush=True)
                        if not _wait_for_server(client, args.server):
                            break
                    except Exception as e:
                        print(f"FAIL {cat} s{steps}: {prompt[:40]}: {e}", flush=True)
                        break
                if url is None:
                    continue
                rows.append({"category": cat, "prompt": prompt, "steps": steps, "url": url})
                print(f"[{i+1}/{len(todo)}] {cat} s{steps} {url}", flush=True)
    return rows


def index_rows(rows: list[dict], out_dir: Path) -> np.ndarray:
    from aesthetic_score import get_scorer

    scorer = get_scorer()
    assert scorer is not None, "aesthetic scorer unavailable"
    embeds = []
    with httpx.Client() as client:
        for batch_start in range(0, len(rows), 8):
            batch = rows[batch_start:batch_start + 8]
            images, ok = [], []
            for r in batch:
                try:
                    img_bytes = client.get(r["url"], timeout=60).content
                    images.append(Image.open(io.BytesIO(img_bytes)).convert("RGB"))
                    ok.append(r)
                except Exception as e:
                    print(f"fetch fail {r['url']}: {e}", flush=True)
                    r["score"] = None
            if not images:
                continue
            emb, scores = scorer.embed_and_score(images)
            for r, s, e in zip(ok, scores, emb):
                r["score"] = round(s, 3)
                r["embed_index"] = len(embeds)
                embeds.append(e.numpy())
            print(f"indexed {batch_start + len(batch)}/{len(rows)}", flush=True)
    return np.stack(embeds) if embeds else np.empty((0, 768), dtype=np.float32)


def report(rows: list[dict], steps_list: list[int]) -> dict:
    ref = max(steps_list)
    by_cat_steps = defaultdict(list)
    for r in rows:
        if r.get("score") is not None:
            by_cat_steps[(r["category"], r["steps"])].append(r["score"])

    cats = sorted({c for c, _ in by_cat_steps})
    summary = {}
    for cat in cats:
        entry = {}
        for steps in steps_list:
            s = by_cat_steps.get((cat, steps), [])
            if s:
                entry[f"s{steps}"] = round(st.mean(s), 3)
        for steps in steps_list:
            if steps != ref and f"s{steps}" in entry and f"s{ref}" in entry:
                entry[f"gap_s{steps}"] = round(entry[f"s{ref}"] - entry[f"s{steps}"], 3)
        summary[cat] = entry

    by_prompt = defaultdict(dict)
    for r in rows:
        if r.get("score") is not None:
            by_prompt[(r["category"], r["prompt"])][r["steps"]] = r["score"]
    worst = sorted(
        (
            {"category": c, "prompt": p,
             "gap": round(scores[ref] - scores[s], 3), "steps": s,
             "few_step_score": scores[s], "ref_score": scores[ref]}
            for (c, p), scores in by_prompt.items()
            for s in steps_list if s != ref and s in scores and ref in scores
        ),
        key=lambda x: -x["gap"],
    )[:20]

    low = sorted((r for r in rows if r.get("score") is not None),
                 key=lambda r: r["score"])[:20]
    return {
        "per_category": summary,
        "worst_degradation": worst,
        "lowest_scores": [
            {k: r[k] for k in ("category", "prompt", "steps", "score", "url")} for r in low
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:8100")
    ap.add_argument("--steps", type=int, nargs="+", default=[4, 8, 20])
    ap.add_argument("--out", default="/nvme0n1-disk/tmp/quality_probe")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path = out_dir / "index.jsonl"

    if args.report_only and index_path.exists():
        rows = [json.loads(line) for line in index_path.read_text().splitlines()]
    else:
        rows = generate_rows(args)
        embeds = index_rows(rows, out_dir)
        np.save(out_dir / "embeddings.npy", embeds)
        index_path.write_text("\n".join(json.dumps(r) for r in rows))

    rep = report(rows, sorted(args.steps))
    (out_dir / "report.json").write_text(json.dumps(rep, indent=2))
    print(json.dumps(rep["per_category"], indent=2))
    print("\nworst degradation:")
    for w in rep["worst_degradation"][:10]:
        print(f"  gap={w['gap']:+.2f} s{w['steps']} {w['category']}: {w['prompt'][:60]}")


if __name__ == "__main__":
    main()
