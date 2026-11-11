"""Precision pareto benchmark. Writes inference/autotune/<gpu_slug>.json.

Run: python -m inference.precision_bench  (or cd inference && python precision_bench.py)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import precision

MODEL_PATH = os.getenv("ZIMAGE_MODEL_PATH", "Tongyi-MAI/Z-Image-Turbo")
DEVICE = os.getenv("DEVICE", "cuda")
STEPS = int(os.getenv("ZIMAGE_DEFAULT_STEPS", "4"))
GUIDANCE = float(os.getenv("ZIMAGE_DEFAULT_GUIDANCE", "0.0"))
WIDTH = int(os.getenv("BENCH_WIDTH", "1024"))
HEIGHT = int(os.getenv("BENCH_HEIGHT", "1024"))
PSNR_MIN = float(os.getenv("CUTEDSL_BENCH_PSNR_MIN", "32"))
BASELINE_PSNR = 99.0

PROMPTS = [
    "a red sports car on a coastal road at sunset",
    "portrait of an elderly fisherman with a weathered face, dramatic lighting",
    "a futuristic city skyline with flying vehicles at night",
    "a bowl of steaming ramen, food photography, shallow depth of field",
    "a snow leopard on a rocky cliff, wildlife photograph",
    "watercolor painting of a lavender field in provence",
    "an astronaut planting a flag on a red desert planet",
    "macro photo of a dew drop on a spider web at dawn",
]
SEEDS = [1000 + i for i in range(len(PROMPTS))]


def build_configs(cap: tuple[int, int]) -> list[dict]:
    cfgs = [{"name": "bf16", "quant": "none", "skip_patterns": [], "skip_first_last": False}]
    if cap[0] >= 10:
        cfgs += [
            {"name": "nvfp4-all", "quant": "nvfp4", "skip_patterns": [], "skip_first_last": False},
            {"name": "nvfp4-skip-first-last", "quant": "nvfp4", "skip_patterns": [], "skip_first_last": True},
            {"name": "nvfp4-skip-first-last-emb", "quant": "nvfp4",
             "skip_patterns": list(precision.DEFAULT_NVFP4_SKIP), "skip_first_last": True},
        ]
    else:
        cfgs.append({"name": "int8wo", "quant": "int8wo", "skip_patterns": [], "skip_first_last": False})
    return cfgs


def load_pipe(cfg: dict):
    from diffusers import ZImagePipeline

    pipe = ZImagePipeline.from_pretrained(MODEL_PATH, torch_dtype=torch.bfloat16)
    if cfg["quant"] != "none":
        for comp_name in ("transformer", "text_encoder"):
            comp = getattr(pipe, comp_name, None)
            if comp is not None:
                precision.apply_quant(comp, cfg["quant"], cfg["skip_patterns"], cfg["skip_first_last"])
    pipe.to(DEVICE)
    return pipe


def gen(pipe, prompt: str, seed: int):
    captured = {}

    def _cb(_p, i, _t, kw):  # noqa: ANN001
        if i == STEPS - 1 and "latents" in kw:
            captured["final"] = kw["latents"].detach().float().cpu()
        return kw

    g = torch.Generator(device=DEVICE).manual_seed(seed)
    kwargs = dict(prompt=prompt, width=WIDTH, height=HEIGHT,
                  num_inference_steps=STEPS, guidance_scale=GUIDANCE, generator=g)
    try:
        out = pipe(**kwargs, callback_on_step_end=_cb,
                   callback_on_step_end_tensor_inputs=["latents"])
    except TypeError:
        out = pipe(**kwargs)
    return out.images[0], captured.get("final")


def run_config(cfg: dict):
    pipe = load_pipe(cfg)
    gen(pipe, "warmup", 0)
    torch.cuda.synchronize()
    images, latents, total = [], [], 0.0
    for prompt, seed in zip(PROMPTS, SEEDS):
        t0 = time.time()
        img, lat = gen(pipe, prompt, seed)
        torch.cuda.synchronize()
        total += time.time() - t0
        images.append(img)
        latents.append(lat)
    del pipe
    torch.cuda.empty_cache()
    return images, latents, total / len(PROMPTS)


def img_psnr(a, b) -> float:
    x = np.asarray(a, dtype=np.float64)
    y = np.asarray(b, dtype=np.float64)
    mse = float(((x - y) ** 2).mean())
    if mse == 0:
        return BASELINE_PSNR
    return min(BASELINE_PSNR, 20 * math.log10(255.0) - 10 * math.log10(mse))


def clip_score(images, prompts) -> float | None:
    try:
        import open_clip

        model, _, preprocess = open_clip.create_model_and_transforms("ViT-B-32", pretrained="openai")
        tok = open_clip.get_tokenizer("ViT-B-32")
        model = model.to(DEVICE).eval()
        with torch.no_grad():
            ims = torch.stack([preprocess(im) for im in images]).to(DEVICE)
            txt = tok(prompts).to(DEVICE)
            fi = model.encode_image(ims)
            ft = model.encode_text(txt)
            fi = fi / fi.norm(dim=-1, keepdim=True)
            ft = ft / ft.norm(dim=-1, keepdim=True)
            score = float((fi * ft).sum(-1).mean())
        del model
        torch.cuda.empty_cache()
        return round(score, 4)
    except Exception as e:
        print(f"clip score unavailable: {e}", flush=True)
        return None


def quality_vs_baseline(images, latents, base_images, base_latents) -> dict:
    psnrs = [img_psnr(a, b) for a, b in zip(images, base_images)]
    mses = [float(((a - b) ** 2).mean()) for a, b in zip(latents, base_latents)
            if a is not None and b is not None]
    return {
        "latent_mse": round(sum(mses) / len(mses), 6) if mses else None,
        "psnr": round(sum(psnrs) / len(psnrs), 2),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    ap.add_argument("--save-images", default="")
    args = ap.parse_args()

    if not torch.cuda.is_available():
        print("CUDA required for precision_bench", flush=True)
        sys.exit(1)

    cap = tuple(torch.cuda.get_device_capability(0))
    gpu = torch.cuda.get_device_name(0)
    slug = precision.gpu_slug(gpu)
    print(f"gpu={gpu} cap={cap} slug={slug} steps={STEPS} {WIDTH}x{HEIGHT} psnr_min={PSNR_MIN}", flush=True)

    base_images = base_latents = None
    results = []
    for cfg in build_configs(cap):
        print(f"[run] {cfg['name']}", flush=True)
        try:
            images, latents, latency = run_config(cfg)
        except Exception as e:
            print(f"[skip] {cfg['name']}: {type(e).__name__}: {e}", flush=True)
            torch.cuda.empty_cache()
            continue

        if cfg["name"] == "bf16":
            base_images, base_latents = images, latents
            quality = {"latent_mse": 0.0, "psnr": BASELINE_PSNR}
        elif base_images is not None:
            quality = quality_vs_baseline(images, latents, base_images, base_latents)
        else:
            quality = {"latent_mse": None, "psnr": None}

        c = clip_score(images, PROMPTS)
        if c is not None:
            quality["clip"] = c

        if args.save_images:
            d = os.path.join(args.save_images, cfg["name"])
            os.makedirs(d, exist_ok=True)
            for i, im in enumerate(images):
                im.save(os.path.join(d, f"{i}.webp"), quality=95)

        results.append({**cfg, "latency_s": round(latency, 4), "quality": quality})
        print(f"[done] {cfg['name']}: latency={latency:.3f}s quality={quality}", flush=True)

    if not results:
        print("no configs succeeded", flush=True)
        sys.exit(1)

    points = [{"latency_s": r["latency_s"],
               "psnr": r["quality"]["psnr"] if r["quality"]["psnr"] is not None else float("-inf")}
              for r in results]
    for r, flag in zip(results, precision.pareto_frontier(points)):
        r["pareto"] = flag

    scored = [r for r in results if r["quality"]["psnr"] is not None]
    chosen = precision.choose_config(scored or results, PSNR_MIN)

    out_path = args.out or str(precision.autotune_path(slug))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    payload = {"gpu": gpu, "gpu_slug": slug, "capability": list(cap),
               "steps": STEPS, "width": WIDTH, "height": HEIGHT,
               "psnr_min": PSNR_MIN, "configs": results, "chosen": chosen,
               "created_at": time.time()}
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"chosen={chosen} -> {out_path}", flush=True)


if __name__ == "__main__":
    main()
