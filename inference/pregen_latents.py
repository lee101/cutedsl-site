"""Warm the LatentCache with single-word latents. Resumable + idempotent.

Run: python -m inference.pregen_latents [--limit N] [--once]
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import sys
import time

import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "cutedsl")))

import precision
from latentteleport.cache import LatentCache
from latentteleport.tokenizer import CuratedTokenizer, VisualUnit

MODEL_PATH = os.getenv("ZIMAGE_MODEL_PATH", "Tongyi-MAI/Z-Image-Turbo")
DEVICE = os.getenv("DEVICE", "cuda")
STEPS = int(os.getenv("ZIMAGE_DEFAULT_STEPS", "4"))
GUIDANCE = float(os.getenv("ZIMAGE_DEFAULT_GUIDANCE", "0.0"))
WIDTH = int(os.getenv("ZIMAGE_DEFAULT_WIDTH", "1024"))
HEIGHT = int(os.getenv("ZIMAGE_DEFAULT_HEIGHT", "1024"))
CACHE_DIR = os.getenv("LATENT_TELEPORT_CACHE_DIR", "/nvme0n1-disk/tmp/latentteleport-cache")
START_STEP = int(os.getenv("LATENT_TELEPORT_START_STEP", "2"))
SLEEP_S = float(os.getenv("PREGEN_SLEEP_S", "2"))
PROMPTS_JSONL = os.getenv("PROMPTS_JSONL", "/sdb-disk/cutedsl-images/prompts.jsonl")
TOP_WORDS = int(os.getenv("PREGEN_TOP_WORDS", "2000"))
SCAN_LINES = int(os.getenv("PREGEN_SCAN_LINES", "200000"))
IMAGE_DIR = os.getenv("PREGEN_IMAGE_DIR", "")
RESCAN_SLEEP_S = float(os.getenv("PREGEN_RESCAN_SLEEP_S", "300"))

STOPWORDS = {
    "the", "and", "with", "for", "art", "highly", "detailed", "very", "style",
    "quality", "resolution", "trending", "artstation", "octane", "render",
    "realistic", "photorealistic", "concept", "digital", "illustration",
    "artgerm", "greg", "rutkowski", "mucha", "unreal", "engine", "sharp",
    "focus", "intricate", "elegant", "smooth", "his", "her", "this", "that",
    "from", "into", "over", "under", "are", "was", "has", "have", "not",
}


def top_prompt_words(path: str, n: int) -> list[str]:
    counts: collections.Counter[str] = collections.Counter()
    try:
        with open(path) as f:
            for i, line in enumerate(f):
                if i >= SCAN_LINES:
                    break
                try:
                    obj = json.loads(line)
                    prompt = obj.get("prompt", "") if isinstance(obj, dict) else str(obj)
                except Exception:
                    continue
                for w in re.findall(r"[a-z]{3,}", prompt.lower()):
                    if w not in STOPWORDS:
                        counts[w] += 1
    except (FileNotFoundError, OSError):
        return []
    return [w for w, _ in counts.most_common(n)]


def build_vocab() -> list[str]:
    tok = CuratedTokenizer()
    vocab = list(dict.fromkeys(tok._vocab))
    for w in top_prompt_words(PROMPTS_JSONL, TOP_WORDS):
        if w not in vocab:
            vocab.append(w)
    return vocab


def word_seed(word: str) -> int:
    return int(hashlib.md5(word.encode()).hexdigest()[:8], 16) % (2**31)


def exact_prompt_unit(prompt: str, seed: int) -> VisualUnit:
    key = f"{prompt}|{WIDTH}x{HEIGHT}|steps={STEPS}|seed={seed}|guidance={GUIDANCE}"
    return VisualUnit.from_text(key)


def load_pipe():
    from diffusers import ZImagePipeline

    pipe = ZImagePipeline.from_pretrained(MODEL_PATH, torch_dtype=torch.bfloat16)
    p = precision.resolve_precision()
    print(f"precision: mode={p['mode']} source={p['source']} gpu={p['gpu']}", flush=True)
    if p["mode"] != "bf16":
        for comp_name in ("transformer", "text_encoder"):
            comp = getattr(pipe, comp_name, None)
            if comp is not None:
                precision.apply_quant(comp, p["mode"], p["skip_patterns"], p["skip_first_last"])
    pipe.to(DEVICE)
    return pipe


def generate_word(pipe, cache: LatentCache, word: str) -> bool:
    seed = word_seed(word)
    cap_step = max(0, min(START_STEP - 1, STEPS - 2))
    capture_steps = sorted({cap_step, STEPS - 1})
    captured: dict[int, torch.Tensor] = {}

    def _cb(_p, i, _t, kw):  # noqa: ANN001
        if i in capture_steps and "latents" in kw:
            captured[i] = kw["latents"].detach().clone().cpu()
        return kw

    g = torch.Generator(device=DEVICE).manual_seed(seed)
    kwargs = dict(prompt=word, width=WIDTH, height=HEIGHT,
                  num_inference_steps=STEPS, guidance_scale=GUIDANCE, generator=g)
    t0 = time.time()
    try:
        result = pipe(**kwargs, callback_on_step_end=_cb,
                      callback_on_step_end_tensor_inputs=["latents"])
    except TypeError:
        result = pipe(**kwargs)
    if not captured:
        print(f"[skip] {word}: no latents captured", flush=True)
        return False

    emb = None
    try:
        text_emb, _ = pipe.encode_prompt(
            prompt=word, negative_prompt=None,
            do_classifier_free_guidance=False, device=DEVICE,
        )
        emb = text_emb[0].detach().cpu() if isinstance(text_emb, list) else text_emb.detach().cpu()
    except Exception as e:
        print(f"[warn] {word}: embedding capture failed: {e}", flush=True)

    meta = {"prompt": word, "seed": seed, "steps": STEPS,
            "width": WIDTH, "height": HEIGHT, "guidance": GUIDANCE, "mode": "pregen_word"}
    unit = VisualUnit.from_text(word)
    cache.store_latents(unit, captured, text_embedding=emb, metadata=meta)
    cache.store_latents(exact_prompt_unit(word, seed), captured, text_embedding=emb, metadata=meta)
    cache.record_prompt(word, unit, [unit], seed=seed, width=WIDTH, height=HEIGHT,
                        steps=STEPS, metadata={"mode": "pregen_word"})

    if IMAGE_DIR:
        try:
            os.makedirs(IMAGE_DIR, exist_ok=True)
            result.images[0].save(os.path.join(IMAGE_DIR, f"{unit.unit_id}_{word[:40]}.webp"), quality=90)
        except Exception as e:
            print(f"[warn] {word}: image save failed: {e}", flush=True)

    print(f"[gen] {word}: {time.time() - t0:.2f}s steps={capture_steps} unit={unit.unit_id}", flush=True)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    cache = LatentCache(CACHE_DIR, resolution=(HEIGHT, WIDTH))
    print(f"cache: {CACHE_DIR} {cache.stats()}", flush=True)
    pipe = load_pipe()

    done = 0
    while True:
        vocab = build_vocab()
        pending = [w for w in vocab if not cache.has_unit(VisualUnit.from_text(w))]
        print(f"vocab={len(vocab)} pending={len(pending)}", flush=True)
        for word in pending:
            if args.limit and done >= args.limit:
                print(f"limit {args.limit} reached, cache: {cache.stats()}", flush=True)
                return
            try:
                if generate_word(pipe, cache, word):
                    done += 1
            except Exception as e:
                print(f"[error] {word}: {type(e).__name__}: {e}", flush=True)
                torch.cuda.empty_cache()
            time.sleep(SLEEP_S)
        if args.once or (args.limit and done >= args.limit):
            break
        print(f"pass complete ({done} generated), rescanning in {RESCAN_SLEEP_S:.0f}s", flush=True)
        time.sleep(RESCAN_SLEEP_S)

    print(f"done: {done} generated, cache: {cache.stats()}", flush=True)


if __name__ == "__main__":
    main()
