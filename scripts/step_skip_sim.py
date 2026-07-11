"""Offline TeaCache-lite simulation from saved step traces.

Uses per-step latents/velocities captured by /experimental/step_trace to
simulate skipping transformer forwards: when the velocity change between
consecutive executed steps is below a threshold, the next step reuses a
linearly-extrapolated velocity instead of a real forward. The simulated
trajectory is integrated with the true sigma schedule, decoded with the
Z-Image VAE on CPU, and compared to the true final image with LPIPS/SSIM.

Usage:
  python scripts/step_skip_sim.py --taus 0.05 0.1 0.15 0.2 --limit 30
"""

import argparse
import glob
import json
import os

import numpy as np
import torch

OUT_DIR = os.getenv("ABLATION_DIR", "/nvme0n1-disk/tmp/early-exit-ablation")
TRACE_DIR = os.getenv("STEP_TRACE_DIR", "/nvme0n1-disk/tmp/step-trace")
MODEL = os.getenv("ZIMAGE_MODEL_PATH", "Tongyi-MAI/Z-Image-Turbo")

_vae = None


def get_vae():
    global _vae
    if _vae is None:
        from diffusers import AutoencoderKL
        _vae = AutoencoderKL.from_pretrained(MODEL, subfolder="vae", torch_dtype=torch.float32)
        _vae.eval()
    return _vae


def decode(latent: torch.Tensor):
    from PIL import Image
    vae = get_vae()
    lat = latent.float() / vae.config.scaling_factor + vae.config.shift_factor
    with torch.no_grad():
        img = vae.decode(lat).sample
    img = ((img[0].permute(1, 2, 0).clamp(-1, 1) + 1) * 127.5).round().byte().numpy()
    return Image.fromarray(img)


_lpips_net = None


def lpips_dist(a, b):
    global _lpips_net
    if _lpips_net is None:
        import lpips
        _lpips_net = lpips.LPIPS(net="alex", verbose=False).eval()
    def t(img):
        arr = np.asarray(img.resize((256, 256))).astype("float32") / 127.5 - 1
        return torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0)
    with torch.no_grad():
        return float(_lpips_net(t(a), t(b)).item())


def simulate(trace: dict, tau: float, max_consecutive_skips: int = 1):
    """Integrate the schedule, replacing forwards with extrapolated velocity
    when relative velocity change < tau. Returns (final_latent, n_skipped, skip_pattern)."""
    zs = [z.float() for z in trace["latents"]]
    vs = [v.float() for v in trace["noise_preds"]]
    sig = trace["sigmas"]
    n = len(vs)
    # initial latent: invert step 0: z0 = zs[0] - (sig[1]-sig[0])*vs[0]
    z = zs[0] - (sig[1] - sig[0]) * vs[0]
    used_vs = []
    skipped = []
    consec = 0
    for k in range(n):
        skip = False
        if len(used_vs) >= 2 and consec < max_consecutive_skips and k < n - 1:
            dv = (used_vs[-1] - used_vs[-2]).norm() / used_vs[-1].norm().clamp_min(1e-8)
            skip = float(dv) < tau
        if skip:
            v = 2 * used_vs[-1] - used_vs[-2]  # linear extrapolation
            consec += 1
        else:
            # "real" forward: reuse the recorded velocity for this step.
            # Approximation: the recorded v was computed on the true trajectory;
            # error from simulated-trajectory drift is not modeled, so treat
            # results as an upper bound on quality.
            v = vs[k]
            consec = 0
        used_vs.append(v)
        skipped.append(skip)
        z = z + (sig[k + 1] - sig[k]) * v
    return z, sum(skipped), skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--taus", type=float, nargs="+", default=[0.05, 0.1, 0.15, 0.2])
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--max-skips", type=int, default=2)
    args = ap.parse_args()

    from PIL import Image
    traces = sorted(glob.glob(os.path.join(TRACE_DIR, "*", "trace.pt")))[: args.limit]
    print(f"{len(traces)} traces")
    results = {tau: [] for tau in args.taus}
    for i, pt in enumerate(traces):
        d = torch.load(pt, map_location="cpu", weights_only=False)
        final_path = os.path.join(os.path.dirname(pt), "final.webp")
        if not os.path.exists(final_path):
            continue
        final_img = Image.open(final_path).convert("RGB")
        for tau in args.taus:
            z, nskip, pattern = simulate(d, tau, args.max_skips)
            if nskip == 0:
                results[tau].append({"lpips": 0.0, "skipped": 0, "prompt": d["prompt"][:50]})
                continue
            img = decode(z)
            lp = lpips_dist(img, final_img)
            results[tau].append({"lpips": lp, "skipped": nskip,
                                 "pattern": "".join("S" if s else "." for s in pattern),
                                 "prompt": d["prompt"][:50]})
        print(f"[{i+1}/{len(traces)}] " + " ".join(
            f"tau={t}:skip={results[t][-1]['skipped']},lpips={results[t][-1]['lpips']:.3f}"
            for t in args.taus), flush=True)

    print("\n=== summary (lpips vs true final; <=0.05 imperceptible) ===")
    n_steps = None
    for tau in args.taus:
        rows = results[tau]
        lps = [r["lpips"] for r in rows]
        sk = [r["skipped"] for r in rows]
        print(f"tau={tau}: mean skipped {np.mean(sk):.2f} steps, "
              f"median lpips {np.median(lps):.4f}, p90 {np.percentile(lps, 90):.4f}, "
              f"max {np.max(lps):.4f}, frac<=0.05 {np.mean([l <= 0.05 for l in lps])*100:.0f}%")
    out = os.path.join(OUT_DIR, "step_skip_sim.json")
    with open(out, "w") as f:
        json.dump({str(k): v for k, v in results.items()}, f, indent=1)
    print(f"-> {out}")


if __name__ == "__main__":
    main()
