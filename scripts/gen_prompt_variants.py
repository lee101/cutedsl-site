#!/usr/bin/env python
"""Expand the cutedsl prompt corpus with variants for 10x art generation.

Reads existing prompts.jsonl (and optional external prompt datasets), produces
SFW-biased style/medium/lighting/mood variants of base prompts, dedups against
everything already present, and appends the new unique prompts back to
prompts.jsonl. generate_images.py then picks them up (it dedups by prompt hash,
so this is safe to re-run).

Then: run generate_images.py to render them, and re-run the app.nz art importer
+ score_art_nsfw.py so the new art is moderated and indexed.

Usage:
  python scripts/gen_prompt_variants.py --target 6000000          # ~10x of 650k
  python scripts/gen_prompt_variants.py --multiplier 4 --dataset extra.txt
  python scripts/gen_prompt_variants.py --dry-run
"""
import argparse
import json
import os
import random
import sys
from pathlib import Path

IMAGES_DIR = Path(os.environ.get("IMAGES_DIR", "/sdb-disk/cutedsl-images"))
PROMPTS_FILE = IMAGES_DIR / "prompts.jsonl"

# SFW-biased modifier banks. Variants combine a base prompt with a few of these.
STYLES = [
    "digital painting", "oil painting", "watercolor", "concept art", "3d render",
    "octane render", "unreal engine", "studio ghibli style", "pixel art",
    "low poly", "isometric", "line art", "vaporwave", "synthwave", "art nouveau",
    "impressionist", "cyberpunk", "steampunk", "papercut", "claymation",
    "matte painting", "cel shaded", "ukiyo-e", "charcoal sketch", "gouache",
]
LIGHTING = [
    "golden hour", "soft studio lighting", "dramatic rim light", "volumetric light",
    "bioluminescent glow", "neon lights", "moonlight", "backlit", "overcast",
    "candlelight", "sunbeams", "aurora", "foggy morning light",
]
MOOD = [
    "serene", "epic", "dreamy", "cozy", "mysterious", "vibrant", "minimalist",
    "whimsical", "melancholic", "ethereal", "playful", "majestic",
]
DETAIL = [
    "highly detailed", "4k", "ultra detailed", "sharp focus", "intricate",
    "cinematic composition", "bokeh", "wide angle", "macro", "depth of field",
]

# Light NSFW guard so we bias toward generating SFW art (full moderation runs
# afterward in app.nz). Substring-conservative single tokens only.
NSFW_TOKENS = {
    "nsfw", "nude", "naked", "explicit", "sex", "porn", "anal", "boobs", "nipple",
    "nipples", "hentai", "erotic", "fetish", "bdsm", "lewd", "cum", "penis",
    "vagina", "blowjob", "choke", "choked", "strangle", "rape", "loli", "shota",
    "gore", "incest",
}


def is_sfw(text: str) -> bool:
    toks = set(t.strip(".,!?\"'()[]") for t in text.lower().split())
    return toks.isdisjoint(NSFW_TOKENS)


def load_existing() -> tuple[list[str], set[str]]:
    prompts, seen = [], set()
    if PROMPTS_FILE.exists():
        with open(PROMPTS_FILE) as f:
            for line in f:
                try:
                    p = json.loads(line)["prompt"]
                except (json.JSONDecodeError, KeyError):
                    continue
                norm = p.strip().lower()
                if norm and norm not in seen:
                    seen.add(norm)
                    prompts.append(p.strip())
    return prompts, seen


def load_dataset(path: str) -> list[str]:
    out = []
    p = Path(path)
    if not p.exists():
        print(f"WARN: dataset {path} not found", file=sys.stderr)
        return out
    with open(p) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("{"):
                try:
                    line = json.loads(line).get("prompt", "")
                except json.JSONDecodeError:
                    continue
            if line:
                out.append(line)
    return out


def variant(base: str, rng: random.Random) -> str:
    parts = [base.strip().rstrip(",.")]
    if rng.random() < 0.85:
        parts.append(rng.choice(STYLES))
    if rng.random() < 0.6:
        parts.append(rng.choice(LIGHTING))
    if rng.random() < 0.5:
        parts.append(rng.choice(MOOD) + " mood")
    if rng.random() < 0.7:
        parts.append(rng.choice(DETAIL))
    return ", ".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=0,
                    help="absolute total prompt count to reach (overrides --multiplier)")
    ap.add_argument("--multiplier", type=float, default=10.0,
                    help="grow corpus to N x its current size")
    ap.add_argument("--dataset", action="append", default=[],
                    help="extra prompt file(s) (txt or jsonl) to use as variant bases")
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--max-attempts-mult", type=int, default=40)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    bases, seen = load_existing()
    print(f"existing unique prompts: {len(bases):,}")
    for ds in args.dataset:
        extra = load_dataset(ds)
        print(f"dataset {ds}: {len(extra):,} prompts")
        for p in extra:
            norm = p.strip().lower()
            if norm and norm not in seen and is_sfw(p):
                seen.add(norm)
                bases.append(p.strip())

    if not bases:
        print("ERROR: no base prompts; run download_prompts.py first", file=sys.stderr)
        sys.exit(1)

    target = args.target if args.target > 0 else int(len(seen) * args.multiplier)
    need = max(0, target - len(seen))
    print(f"target total={target:,} need new={need:,}")
    if need == 0 or args.dry_run:
        return

    rng = random.Random(args.seed)
    new = []
    attempts = 0
    max_attempts = need * args.max_attempts_mult
    while len(new) < need and attempts < max_attempts:
        attempts += 1
        v = variant(rng.choice(bases), rng)
        norm = v.lower()
        if norm in seen or not is_sfw(v):
            continue
        seen.add(norm)
        new.append(v)

    print(f"generated {len(new):,} new unique variants in {attempts:,} attempts")
    PROMPTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PROMPTS_FILE, "a") as f:
        for v in new:
            f.write(json.dumps({"prompt": v, "generated": False}) + "\n")
    print(f"appended to {PROMPTS_FILE}; total now ~{len(seen):,}")
    print("next: python scripts/generate_images.py --limit 0")


if __name__ == "__main__":
    main()
