#!/usr/bin/env python3
"""AITune ahead-of-time optimization experiment for Z-Image pipeline.

Strategy
--------
- **Exclude** CuteZImageTransformer (already Triton-optimized + LoRA-patched at runtime)
- **Tune** text_encoder (Qwen3) and VAE decoder with TensorRT
- **LoRA-safe**: LoRAs only modify transformer weights; TRT engines cover the
  non-transformer parts and are valid across all LoRAs

The transformer is called ~4 times per image (one per denoising step) and is
already heavily optimized with fused Triton kernels + torch.compile.  The
text_encoder and VAE are each called once per image and currently run as plain
PyTorch — good TRT candidates.

Usage
-----
    # Phase 1: profile the pipeline and tune text_encoder + VAE
    python aitune_experiment.py --tune

    # Phase 2: benchmark tuned vs baseline latency
    python aitune_experiment.py --benchmark

    # Phase 3: image quality comparison (SSIM / PSNR with fixed seeds)
    python aitune_experiment.py --quality-check

    # Run all phases
    python aitune_experiment.py --all
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import torch

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CUTEDSL_ROOT = REPO_ROOT / "cutedsl"
INFERENCE_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(CUTEDSL_ROOT))
sys.path.insert(0, str(INFERENCE_DIR))

ZIMAGE_MODEL_PATH = os.getenv("ZIMAGE_MODEL_PATH", "Tongyi-MAI/Z-Image-Turbo")
AITUNE_CACHE_DIR = Path(os.getenv("AITUNE_CACHE_DIR", str(INFERENCE_DIR / ".aitune_cache")))
DEVICE = os.getenv("DEVICE", "cuda")
DTYPE = torch.bfloat16

# Quality benchmark prompts (fixed seeds → deterministic outputs)
BENCH_PROMPTS = [
    ("anime fairy cute winged fairy glowing dust", 42),
    ("photorealistic portrait of a woman, golden hour lighting", 1337),
    ("cyberpunk city at night, neon reflections on wet street", 7),
    ("oil painting of mountains and a lake, impressionist style", 99),
    ("cute fluffy cat wearing a tiny hat, studio photo", 2024),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_gpu():
    if torch.cuda.is_available():
        torch.cuda.synchronize()
        torch.cuda.empty_cache()
        gc.collect()


def _peak_vram_mb() -> float:
    if not torch.cuda.is_available():
        return 0.0
    torch.cuda.synchronize()
    return torch.cuda.max_memory_allocated() / (1024 ** 2)


def _time_inference(pipe, prompt: str, seed: int, steps: int = 4, n: int = 3) -> tuple[float, Any]:
    """Return (mean_latency_ms, last_image)."""
    latencies = []
    image = None
    torch.cuda.reset_peak_memory_stats()
    for i in range(n):
        gen = torch.Generator(device=DEVICE).manual_seed(seed)
        t0 = time.perf_counter()
        result = pipe(
            prompt=prompt,
            width=1024,
            height=1024,
            num_inference_steps=steps,
            guidance_scale=0.0,
            generator=gen,
        )
        torch.cuda.synchronize()
        latencies.append((time.perf_counter() - t0) * 1000)
        image = result.images[0]
    mean_ms = sum(latencies[1:]) / max(1, len(latencies) - 1)  # skip first (warmup)
    return mean_ms, image


def _image_to_tensor(img) -> torch.Tensor:
    """PIL Image → (C, H, W) uint8 tensor."""
    import numpy as np
    arr = np.array(img)
    return torch.from_numpy(arr).permute(2, 0, 1)


def _ssim(t1: torch.Tensor, t2: torch.Tensor, window_size: int = 11) -> float:
    """Simplified SSIM on (C, H, W) uint8 tensors."""
    import torch.nn.functional as F

    C1, C2 = 6.5025, 58.5225  # (0.01*255)^2, (0.03*255)^2
    x = t1.float().unsqueeze(0)  # (1, C, H, W)
    y = t2.float().unsqueeze(0)

    # Gaussian kernel
    coords = torch.arange(window_size, dtype=torch.float32) - window_size // 2
    g = torch.exp(-(coords ** 2) / (2 * 1.5 ** 2))
    g /= g.sum()
    kernel = g.outer(g).unsqueeze(0).unsqueeze(0)
    kernel = kernel.repeat(t1.shape[0], 1, 1, 1)  # (C, 1, W, W)
    pad = window_size // 2

    mu1 = F.conv2d(x, kernel, padding=pad, groups=t1.shape[0])
    mu2 = F.conv2d(y, kernel, padding=pad, groups=t1.shape[0])
    mu1_sq, mu2_sq, mu1_mu2 = mu1 ** 2, mu2 ** 2, mu1 * mu2
    sig1 = F.conv2d(x * x, kernel, padding=pad, groups=t1.shape[0]) - mu1_sq
    sig2 = F.conv2d(y * y, kernel, padding=pad, groups=t1.shape[0]) - mu2_sq
    sig12 = F.conv2d(x * y, kernel, padding=pad, groups=t1.shape[0]) - mu1_mu2

    num = (2 * mu1_mu2 + C1) * (2 * sig12 + C2)
    den = (mu1_sq + mu2_sq + C1) * (sig1 + sig2 + C2)
    return (num / den).mean().item()


def _psnr(t1: torch.Tensor, t2: torch.Tensor) -> float:
    mse = (t1.float() - t2.float()).pow(2).mean().item()
    if mse < 1e-10:
        return float("inf")
    return 10.0 * torch.tensor(255.0 ** 2 / mse).log10().item()


# ---------------------------------------------------------------------------
# Pipeline loading
# ---------------------------------------------------------------------------

def _load_baseline_pipeline(cpu_offload: bool = True):
    """Load Z-Image with CuteZImage (our standard accelerated path).

    Uses compile_mode="default" (kernel fusion, no CUDA graphs) for the
    standalone benchmark — CUDA graphs require the exact same call signature
    every iteration and can fail during recording when the pipeline scheduler
    returns Python lists as intermediate outputs.
    """
    from cutezimage.pipeline import get_zimage_pipelines
    print("[load] Loading CuteZImage baseline pipeline...")
    t0 = time.time()
    text2img, _ = get_zimage_pipelines(
        model_path=ZIMAGE_MODEL_PATH,
        torch_dtype=DTYPE,
        use_cute=True,
        compile_mode="default",   # avoid reduce-overhead CUDA graph crash
        device=DEVICE,
        enable_cpu_offload=cpu_offload,
    )
    print(f"[load] Pipeline ready in {time.time() - t0:.1f}s")

    # Warmup (triggers torch.compile graph capture)
    print("[load] Warmup...")
    t0 = time.time()
    text2img(
        prompt="warmup",
        width=512, height=512,
        num_inference_steps=1,
        guidance_scale=0.0,
        generator=torch.Generator(device=DEVICE).manual_seed(0),
    )
    print(f"[load] Warmup done in {time.time() - t0:.1f}s")
    return text2img


def _load_vanilla_pipeline(cpu_offload: bool = True):
    """Load vanilla diffusers ZImagePipeline (no CuteZImage) for AITune inspection."""
    from diffusers import ZImagePipeline
    print("[load] Loading vanilla diffusers pipeline (for AITune inspection)...")
    t0 = time.time()
    pipe = ZImagePipeline.from_pretrained(ZIMAGE_MODEL_PATH, torch_dtype=DTYPE)
    if cpu_offload and torch.cuda.is_available():
        pipe.enable_model_cpu_offload()
    else:
        pipe.to(DEVICE)
    print(f"[load] Vanilla pipeline ready in {time.time() - t0:.1f}s")
    return pipe


# ---------------------------------------------------------------------------
# Module filtering: what to tune with AITune
# ---------------------------------------------------------------------------

def _is_transformer(module: torch.nn.Module, name: str) -> bool:
    """True if module is the Z-Image transformer (exclude from AITune)."""
    from cutezimage.model import CuteZImageTransformer
    if isinstance(module, CuteZImageTransformer):
        return True
    cls_name = type(module).__name__.lower()
    # Also exclude diffusers transformer variants
    return "transformer" in cls_name and "block" not in cls_name


def _filter_modules(modules_info, pipe):
    """Return only text_encoder and VAE modules from inspect result."""
    all_modules = modules_info.get_modules()
    print(f"\n[inspect] All tunable modules found: {len(all_modules)}")

    safe_modules = []
    for mod in all_modules:
        name = getattr(mod, "name", str(mod))
        module_obj = getattr(mod, "module", None)
        if module_obj is None:
            continue
        if _is_transformer(module_obj, name):
            print(f"  [skip] {name} — custom Triton kernels, LoRA-patched at runtime")
            continue
        # Keep text_encoder and VAE
        safe_modules.append(mod)
        print(f"  [tune] {name} — {type(module_obj).__name__}")

    print(f"[inspect] Selected {len(safe_modules)} modules for AITune\n")
    return safe_modules


# ---------------------------------------------------------------------------
# Phase 1: Tune
# ---------------------------------------------------------------------------

def run_tune(args):
    """Profile pipeline, select non-transformer modules, tune with AITune/TRT."""
    import aitune.torch as ait

    AITUNE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Use vanilla pipeline for AITune (no custom Triton ops → traceable)
    # Disable cpu_offload so AITune can profile on-GPU (requires full VRAM)
    pipe = _load_vanilla_pipeline(cpu_offload=False)

    # Prepare input data for profiling
    input_data = [{"prompt": p} for p, _ in BENCH_PROMPTS[:2]]

    def _infer(prompt: str):
        return pipe(
            prompt=prompt,
            width=1024, height=1024,
            num_inference_steps=4,
            guidance_scale=0.0,
            generator=torch.Generator(device=DEVICE).manual_seed(42),
        )

    print("[tune] Running AITune inspection (profiling pipeline)...")
    modules_info = ait.inspect(pipe, input_data, inference_function=_infer)
    modules_info.describe()

    # Filter out transformer (already custom-optimized)
    selected = _filter_modules(modules_info, pipe)

    if not selected:
        print("[tune] No modules selected for tuning — all are already custom-optimized.")
        return

    print(f"[tune] Wrapping {len(selected)} modules...")
    pipe = ait.wrap(pipe, selected)

    print("[tune] Running AITune tuning (this may take several minutes)...")
    t0 = time.time()
    ait.tune(pipe, input_data)
    print(f"[tune] Tuning complete in {time.time() - t0:.1f}s")

    save_path = str(AITUNE_CACHE_DIR / "zimage_tuned.ait")
    ait.save(pipe, save_path)
    print(f"[tune] Saved tuned engines to {save_path}")


# ---------------------------------------------------------------------------
# Phase 2: Benchmark
# ---------------------------------------------------------------------------

def run_benchmark(args):
    """Compare latency: CuteZImage baseline vs vanilla+AITune vs CuteZImage+AITune."""
    import aitune.torch as ait

    results = {}

    prompt, seed = BENCH_PROMPTS[0]
    n_runs = 5

    # --- Baseline: CuteZImage (our Triton path) ---
    print("\n=== Baseline: CuteZImage (Triton + torch.compile) ===")
    baseline_pipe = _load_baseline_pipeline()
    _reset_gpu()
    ms, _ = _time_inference(baseline_pipe, prompt, seed, n=n_runs)
    results["cutezimage_baseline"] = {"mean_latency_ms": ms, "peak_vram_mb": _peak_vram_mb()}
    print(f"  Latency: {ms:.0f} ms  |  Peak VRAM: {_peak_vram_mb():.0f} MB")
    del baseline_pipe
    _reset_gpu()

    # --- Vanilla: standard diffusers (no AITune) ---
    print("\n=== Vanilla diffusers (no AITune) ===")
    vanilla_pipe = _load_vanilla_pipeline()
    # Short warmup
    vanilla_pipe(prompt="warmup", width=512, height=512, num_inference_steps=1, guidance_scale=0.0)
    _reset_gpu()
    ms, _ = _time_inference(vanilla_pipe, prompt, seed, n=n_runs)
    results["vanilla_no_aitune"] = {"mean_latency_ms": ms, "peak_vram_mb": _peak_vram_mb()}
    print(f"  Latency: {ms:.0f} ms  |  Peak VRAM: {_peak_vram_mb():.0f} MB")

    # --- Vanilla + AITune ---
    save_path = str(AITUNE_CACHE_DIR / "zimage_tuned.ait")
    if Path(save_path).exists():
        print("\n=== Vanilla diffusers + AITune TRT ===")
        ait.load(vanilla_pipe, save_path)
        # Warmup tuned pipeline
        vanilla_pipe(prompt="warmup", width=512, height=512, num_inference_steps=1, guidance_scale=0.0)
        _reset_gpu()
        ms, _ = _time_inference(vanilla_pipe, prompt, seed, n=n_runs)
        results["vanilla_aitune"] = {"mean_latency_ms": ms, "peak_vram_mb": _peak_vram_mb()}
        print(f"  Latency: {ms:.0f} ms  |  Peak VRAM: {_peak_vram_mb():.0f} MB")
    else:
        print("\n[benchmark] No AITune checkpoint found. Run --tune first.")

    del vanilla_pipe
    _reset_gpu()

    # Print summary table
    print("\n" + "=" * 60)
    print("BENCHMARK SUMMARY")
    print("=" * 60)
    baseline_ms = results.get("cutezimage_baseline", {}).get("mean_latency_ms", float("nan"))
    for key, r in results.items():
        ms = r["mean_latency_ms"]
        speedup = baseline_ms / ms if ms > 0 else float("nan")
        print(f"  {key:<30s}  {ms:7.0f} ms   {speedup:.2f}x vs baseline")
    print("=" * 60)

    out_path = AITUNE_CACHE_DIR / "benchmark_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n[benchmark] Results saved to {out_path}")


# ---------------------------------------------------------------------------
# Phase 3: Quality check
# ---------------------------------------------------------------------------

def run_quality_check(args):
    """Generate images with baseline and AITune pipeline; compare SSIM/PSNR."""
    import aitune.torch as ait

    save_path = str(AITUNE_CACHE_DIR / "zimage_tuned.ait")
    if not Path(save_path).exists():
        print("[quality] No AITune checkpoint found. Run --tune first.")
        return

    out_dir = AITUNE_CACHE_DIR / "quality_images"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load baseline
    print("\n=== Quality check: generating baseline images ===")
    baseline_pipe = _load_baseline_pipeline()
    baseline_images = {}
    for prompt, seed in BENCH_PROMPTS:
        _, img = _time_inference(baseline_pipe, prompt, seed, n=1)
        label = prompt[:30].replace(" ", "_")
        img.save(out_dir / f"baseline_{label}_{seed}.png")
        baseline_images[(prompt, seed)] = _image_to_tensor(img)
        print(f"  [baseline] {prompt[:40]}")
    del baseline_pipe
    _reset_gpu()

    # Load vanilla + AITune
    print("\n=== Quality check: generating AITune images ===")
    vanilla_pipe = _load_vanilla_pipeline()
    ait.load(vanilla_pipe, save_path)
    vanilla_pipe(prompt="warmup", width=512, height=512, num_inference_steps=1, guidance_scale=0.0)

    quality_results = []
    for prompt, seed in BENCH_PROMPTS:
        _, img = _time_inference(vanilla_pipe, prompt, seed, n=1)
        label = prompt[:30].replace(" ", "_")
        img.save(out_dir / f"aitune_{label}_{seed}.png")
        aitune_tensor = _image_to_tensor(img)
        baseline_tensor = baseline_images[(prompt, seed)]

        ssim_val = _ssim(baseline_tensor, aitune_tensor)
        psnr_val = _psnr(baseline_tensor, aitune_tensor)
        quality_results.append({
            "prompt": prompt,
            "seed": seed,
            "ssim": ssim_val,
            "psnr_db": psnr_val,
        })
        print(f"  [quality] {prompt[:40]!r}  SSIM={ssim_val:.4f}  PSNR={psnr_val:.1f}dB")

    print("\n" + "=" * 60)
    print("QUALITY SUMMARY  (baseline vs AITune-tuned pipeline)")
    print("=" * 60)
    mean_ssim = sum(r["ssim"] for r in quality_results) / len(quality_results)
    mean_psnr = sum(r["psnr_db"] for r in quality_results if r["psnr_db"] != float("inf")) / len(quality_results)
    print(f"  Mean SSIM : {mean_ssim:.4f}  (1.0 = identical)")
    print(f"  Mean PSNR : {mean_psnr:.1f} dB  (>30 dB = high similarity)")
    print(f"  Images saved to: {out_dir}")
    print("=" * 60)

    out_path = AITUNE_CACHE_DIR / "quality_results.json"
    with open(out_path, "w") as f:
        json.dump(quality_results, f, indent=2)
    print(f"\n[quality] Results saved to {out_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global ZIMAGE_MODEL_PATH, AITUNE_CACHE_DIR  # noqa: PLW0603
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tune", action="store_true", help="Profile pipeline and tune with AITune/TRT")
    parser.add_argument("--benchmark", action="store_true", help="Latency benchmark: baseline vs AITune")
    parser.add_argument("--quality-check", action="store_true", help="Image quality comparison (SSIM/PSNR)")
    parser.add_argument("--all", action="store_true", help="Run all phases sequentially")
    parser.add_argument("--model-path", default=ZIMAGE_MODEL_PATH, help="Z-Image model path")
    parser.add_argument("--output-dir", default=str(AITUNE_CACHE_DIR), help="Where to save tuned engines")
    parser.add_argument("--steps", type=int, default=4, help="Denoising steps for benchmark")
    args = parser.parse_args()

    ZIMAGE_MODEL_PATH = args.model_path
    AITUNE_CACHE_DIR = Path(args.output_dir)

    if args.all or args.tune:
        run_tune(args)

    if args.all or args.benchmark:
        run_benchmark(args)

    if args.all or args.quality_check:
        run_quality_check(args)

    if not any([args.tune, args.benchmark, args.quality_check, args.all]):
        parser.print_help()


if __name__ == "__main__":
    main()
