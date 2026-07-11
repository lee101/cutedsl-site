"""Early-exit ablation for Z-Image flow-matching diffusion.

Drives /experimental/step_trace on the resident inference server, then
computes per-step LPIPS of the x0-hat extrapolation against the full-schedule
final image. Finds, per prompt, the earliest step whose x0-hat is perceptually
indistinguishable from the final image, and calibrates a latent-delta
(dz_rel) threshold that predicts that exit point without decoding.

Usage:
  python scripts/early_exit_ablation.py trace --n 60 --steps 9 --size 512
  python scripts/early_exit_ablation.py analyze
  python scripts/early_exit_ablation.py knn
"""

import argparse
import json
import os
import sys
import time

import requests

API = os.getenv("INFERENCE_URL", "http://127.0.0.1:8100")
OUT_DIR = os.getenv("ABLATION_DIR", "/nvme0n1-disk/tmp/early-exit-ablation")
PROMPTS_JSONL = "/sdb-disk/cutedsl-images/prompts.jsonl"

HARD_PROMPTS = [
    "a glass teapot with a paper label that says TEA in serif letters, product photo",
    "portrait of an elderly astronaut, weathered skin, tears in his eyes, studio lighting",
    "pixel art inventory icon of a health potion, 16x16, plain black background",
    "dense city street at night in heavy rain, neon signs with readable text CUTE DSL",
    "close-up macro photo of a jumping spider on a dew-covered leaf",
    "minimalist logo of a fox head, flat vector, two colors",
]


def sample_prompts(n: int) -> list[str]:
    prompts = list(HARD_PROMPTS)
    need = n - len(prompts)
    if need > 0:
        stride = 1757539 // need
        with open(PROMPTS_JSONL) as f:
            for i, line in enumerate(f):
                if i % stride == 0 and len(prompts) < n:
                    p = json.loads(line)["prompt"].strip()
                    if 10 < len(p) < 500:
                        prompts.append(p)
                if len(prompts) >= n:
                    break
    return prompts[:n]


def cmd_trace(args):
    os.makedirs(OUT_DIR, exist_ok=True)
    prompts = sample_prompts(args.n)
    results = []
    for i, prompt in enumerate(prompts):
        t0 = time.time()
        try:
            r = requests.post(f"{API}/experimental/step_trace", json={
                "prompt": prompt,
                "width": args.size, "height": args.size,
                "seed": args.seed,
                "num_inference_steps": args.steps,
                "low_priority": False,
            }, timeout=600)
            r.raise_for_status()
            data = r.json()
            data["prompt"] = prompt
            results.append(data)
            print(f"[{i+1}/{len(prompts)}] {data['trace_id']} gen={data['gen_seconds']}s "
                  f"wall={time.time()-t0:.1f}s :: {prompt[:60]}", flush=True)
        except Exception as e:
            print(f"[{i+1}/{len(prompts)}] FAILED {e} :: {prompt[:60]}", flush=True)
    path = os.path.join(OUT_DIR, f"traces_{args.steps}steps_{args.size}px.json")
    with open(path, "w") as f:
        json.dump(results, f)
    print(f"wrote {len(results)} traces -> {path}")


def _load_traces(args):
    path = os.path.join(OUT_DIR, f"traces_{args.steps}steps_{args.size}px.json")
    with open(path) as f:
        return json.load(f)


def _lpips_model():
    import lpips
    import torch
    net = lpips.LPIPS(net="alex", verbose=False)
    net.eval()
    return net, torch.device("cpu")


def _img_tensor(path, size=256):
    import numpy as np
    import torch
    from PIL import Image
    img = Image.open(path).convert("RGB").resize((size, size), Image.LANCZOS)
    a = np.asarray(img).astype("float32") / 127.5 - 1.0
    return torch.from_numpy(a).permute(2, 0, 1).unsqueeze(0)


def _dx0_rel_from_trace(trace_dir: str) -> dict:
    """x0-hat relative movement per step, the signal the live callback uses."""
    import torch
    pt = os.path.join(trace_dir, "trace.pt")
    if not os.path.exists(pt):
        return {}
    d = torch.load(pt, map_location="cpu", weights_only=False)
    zs = [z.float() for z in d["latents"]]
    sig = d["sigmas"]
    x0s = {}
    for k in range(1, len(zs)):
        denom = sig[k + 1] - sig[k]
        if abs(denom) < 1e-9:
            continue
        v = (zs[k] - zs[k - 1]) / denom
        x0s[k] = zs[k] - sig[k + 1] * v
    out = {}
    ks = sorted(x0s)
    for a, b in zip(ks, ks[1:]):
        out[b] = float((x0s[b] - x0s[a]).norm() / x0s[b].norm().clamp_min(1e-8))
    return out


def cmd_analyze(args):
    import torch
    traces = _load_traces(args)
    net, dev = _lpips_model()
    eps_levels = [0.02, 0.05, 0.10]
    rows = []
    for tr in traces:
        final = _img_tensor(tr["final_image"])
        lp = {}
        with torch.no_grad():
            for s in tr["steps"]:
                if "x0_image" not in s or not os.path.exists(s["x0_image"]):
                    continue
                lp[s["step"]] = float(net(_img_tensor(s["x0_image"]), final).item())
        row = {
            "trace_id": tr["trace_id"], "prompt": tr["prompt"],
            "lpips": lp, "dz_rel": {s["step"]: s.get("dz_rel") for s in tr["steps"]},
            "dx0_rel": _dx0_rel_from_trace(tr["dir"]),
            "ssim": {s["step"]: s.get("ssim_to_final") for s in tr["steps"]},
            "step_durations": tr.get("step_durations"),
        }
        for eps in eps_levels:
            exit_step = next((k for k in sorted(lp) if lp[k] <= eps), None)
            row[f"exit@{eps}"] = exit_step
        rows.append(row)
        print(f"{tr['trace_id']} exits={[row[f'exit@{e}'] for e in eps_levels]} "
              f"lpips={[round(lp.get(k, -1), 3) for k in sorted(lp)]}", flush=True)

    out = os.path.join(OUT_DIR, f"analysis_{args.steps}steps_{args.size}px.json")
    with open(out, "w") as f:
        json.dump(rows, f, indent=1)

    n_steps = args.steps
    print("\n=== summary ===")
    for eps in eps_levels:
        exits = [r[f"exit@{eps}"] for r in rows if r[f"exit@{eps}"] is not None]
        if not exits:
            continue
        import statistics
        saved = [n_steps - 1 - e for e in exits]
        print(f"eps={eps}: median exit step {statistics.median(exits)}, "
              f"mean steps saved {statistics.mean(saved):.2f}/{n_steps}, "
              f"min exit {min(exits)}, max exit {max(exits)}, n={len(exits)}")
    # calibrate the live-callback threshold: dx0_rel at each trace's exit step.
    # the callback exits when dx0_rel < tau, so tau must be BELOW the dx0_rel
    # of every step that still matters and ABOVE the dx0_rel at safe exits.
    for eps in eps_levels:
        cal = [r["dx0_rel"].get(r[f"exit@{eps}"]) for r in rows
               if r[f"exit@{eps}"] is not None]
        cal = sorted(c for c in cal if c)
        if cal:
            print(f"dx0_rel at eps={eps} exit: min={cal[0]:.4f} p25={cal[len(cal)//4]:.4f} "
                  f"median={cal[len(cal)//2]:.4f} p75={cal[3*len(cal)//4]:.4f} max={cal[-1]:.4f}")
    # simulate live thresholds: exit at first step with dx0_rel < tau (after min_steps),
    # report realized LPIPS and steps saved
    for tau in (0.05, 0.1, 0.15, 0.2, 0.3):
        lps, saved = [], []
        for r in rows:
            dx0 = r["dx0_rel"]
            lp = r["lpips"]
            if not dx0 or not lp:
                continue
            n = max(lp) + 1
            exit_k = next((k for k in sorted(dx0) if k + 1 >= 4 and dx0[k] < tau), None)
            if exit_k is None:
                lps.append(0.0)
                saved.append(0)
            else:
                lps.append(lp.get(exit_k, 0.0))
                saved.append(n - 1 - exit_k)
        if lps:
            import statistics
            lps_s = sorted(lps)
            print(f"tau={tau}: mean saved {statistics.mean(saved):.2f} steps, "
                  f"median lpips {lps_s[len(lps_s)//2]:.4f}, "
                  f"p90 {lps_s[int(len(lps_s)*0.9)]:.4f}, max {lps_s[-1]:.4f}, "
                  f"frac<=0.05 {sum(1 for l in lps if l <= 0.05)/len(lps)*100:.0f}%")
    print(f"analysis -> {out}")


def cmd_knn(args):
    import numpy as np
    import torch
    traces = _load_traces(args)
    with open(os.path.join(OUT_DIR, f"analysis_{args.steps}steps_{args.size}px.json")) as f:
        rows = {r["trace_id"]: r for r in json.load(f)}
    embs, ys = [], []
    for tr in traces:
        r = rows.get(tr["trace_id"])
        if not r or r.get("exit@0.05") is None:
            continue
        pt = os.path.join(tr["dir"], "trace.pt")
        if not os.path.exists(pt):
            continue
        d = torch.load(pt, map_location="cpu", weights_only=False)
        e = d.get("pooled_prompt_embedding")
        if e is None:
            continue
        embs.append(e.detach().numpy())
        ys.append(r["exit@0.05"])
    X = np.stack(embs)
    X = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-8)
    y = np.array(ys)
    sims = X @ X.T
    np.fill_diagonal(sims, -1)
    for k in (1, 3, 5):
        preds = []
        for i in range(len(y)):
            nn = np.argsort(-sims[i])[:k]
            preds.append(int(round(y[nn].mean())))
        preds = np.array(preds)
        mae = np.abs(preds - y).mean()
        safe = (preds >= y).mean()
        print(f"knn k={k}: MAE={mae:.2f} steps, pred>=true (safe) {safe*100:.0f}%")
    const = int(np.ceil(np.percentile(y, 90)))
    print(f"baselines: global P90 exit={const} (MAE={np.abs(const-y).mean():.2f}), "
          f"mean exit={y.mean():.2f}, std={y.std():.2f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("trace", "analyze", "knn"):
        p = sub.add_parser(name)
        p.add_argument("--n", type=int, default=60)
        p.add_argument("--steps", type=int, default=9)
        p.add_argument("--size", type=int, default=512)
        p.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    {"trace": cmd_trace, "analyze": cmd_analyze, "knn": cmd_knn}[args.cmd](args)
