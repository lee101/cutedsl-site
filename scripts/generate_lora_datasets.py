"""Generate per-LoRA image datasets into the gallery index.

Routes prompts from prompts.jsonl to each LoRA via the cuteloras router, then generates
batched per-LoRA (one weight swap per batch, not per image). Images stored webp q85 in
all three gallery sizes, latents saved for teleport training, DB rows tagged
model="zimage:<lora_id>".

Usage:
    PYTHONPATH=/nvme0n1-disk/code/cutedsl python scripts/generate_lora_datasets.py \
        --per-lora 50 --loras anime_serenity mecha_klein   # or omit --loras for all
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "inference"))

import requests

from generate_images import (
    INFERENCE_URL,
    compact_prompt,
    get_db,
    get_existing_hashes,
    load_all_prompts,
    prompt_hash,
    save_and_insert,
    seed_for_prompt,
)


def route_prompts(loras, prompts, per_lora, existing, min_score=0.6):
    """Assign top-matching prompts to each LoRA using the cuteloras router scores."""
    from cuteloras import LoRARecord, LoRARegistry
    from cuteloras.router import LoRARouter

    registry = LoRARegistry()
    for lora in loras:
        registry.add(LoRARecord(
            id=lora.id, name=lora.name, trigger_word=lora.trigger_word,
            template=lora.template or "{prompt}", keywords=lora.keywords,
            negative_keywords=lora.negative_keywords, is_adult=lora.is_adult,
        ))
    router = LoRARouter(registry, embedding_model=None)

    assignments = {lora.id: [] for lora in loras}
    for prompt in prompts:
        if prompt_hash(f"{prompt}") in existing:
            continue
        results = router.search(prompt, top_k=1, allow_adult=True)
        if not results or results[0].score < min_score:
            continue
        lora_id = results[0].record.id
        if len(assignments[lora_id]) < per_lora:
            assignments[lora_id].append(prompt)
        if all(len(v) >= per_lora for v in assignments.values()):
            break
    return assignments


def generate_with_lora(prompt, lora_id, width, height, steps, seed):
    try:
        resp = requests.post(
            f"{INFERENCE_URL}/generate_image",
            json={
                "prompt": compact_prompt(prompt),
                "width": width,
                "height": height,
                "seed": seed,
                "num_inference_steps": steps,
                "lora_id": lora_id,
                "auto_lora": False,
                "low_priority": True,
            },
            timeout=360,
        )
        if resp.status_code == 200:
            return resp.json()
        print(f"  API {resp.status_code}: {resp.text[:100]}")
    except Exception as e:
        print(f"  Error: {e}")
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-lora", type=int, default=50)
    parser.add_argument("--loras", nargs="*", default=None)
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--steps", type=int, default=9)
    parser.add_argument("--min-score", type=float, default=0.6)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from lora_fixtures import get_all_zimage_loras

    loras = get_all_zimage_loras()
    if args.loras:
        loras = [l for l in loras if l.id in set(args.loras)]
    if not loras:
        print("no matching loras")
        sys.exit(1)

    conn = get_db()
    existing = get_existing_hashes(conn)
    prompts = load_all_prompts()
    print(f"routing {len(prompts)} prompts across {len(loras)} loras...")
    assignments = route_prompts(loras, prompts, args.per_lora, existing, args.min_score)

    total = sum(len(v) for v in assignments.values())
    print(f"assigned {total} prompts: " +
          ", ".join(f"{k}={len(v)}" for k, v in sorted(assignments.items(), key=lambda x: -len(x[1])) if v))
    if args.dry_run:
        return

    done = failed = 0
    start = time.time()
    for lora_id, lora_prompts in assignments.items():
        if not lora_prompts:
            continue
        print(f"\n=== {lora_id} ({len(lora_prompts)} prompts) ===")
        for prompt in lora_prompts:
            result = generate_with_lora(prompt, lora_id, args.width, args.height,
                                        args.steps, seed_for_prompt(prompt))
            if result and not result.get("lora"):
                print(f"  server did not apply lora {lora_id}, skipping batch")
                failed += len(lora_prompts)
                break
            if result and save_and_insert(result, prompt, conn, model=f"zimage:{lora_id}"):
                done += 1
            else:
                failed += 1
            if done and done % 20 == 0:
                rate = done / (time.time() - start)
                print(f"  {done}/{total} done ({rate:.2f} img/s, {failed} failed)")

    print(f"\nfinished: {done} generated, {failed} failed in {time.time() - start:.0f}s")


if __name__ == "__main__":
    main()
