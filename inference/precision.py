"""Per-GPU precision selection, NVFP4 filter fns, autotune result IO, pareto."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import torch

AUTOTUNE_DIR = Path(__file__).resolve().parent / "autotune"

DEFAULT_NVFP4_SKIP = [
    "embed",
    "embedder",
    "time_",
    "t_embedder",
    "cap_",
    "context_",
    "caption",
    "patch_",
    "pos_",
    "norm",
    "proj_out",
    "final_layer",
    "lm_head",
]

MIN_LINEAR_DIM = int(os.getenv("CUTEDSL_NVFP4_MIN_DIM", "1024"))


def gpu_slug(name: str | None = None) -> str:
    if name is None:
        name = torch.cuda.get_device_name(0)
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def autotune_path(slug: str | None = None) -> Path:
    return AUTOTUNE_DIR / f"{slug or gpu_slug()}.json"


def load_autotune(slug: str | None = None, path: str | Path | None = None) -> dict | None:
    p = Path(path) if path else autotune_path(slug)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except Exception:
        return None
    chosen = data.get("chosen")
    for cfg in data.get("configs", []):
        if cfg.get("name") == chosen:
            return {"gpu": data.get("gpu"), "config": cfg}
    return None


def _block_bounds(model: torch.nn.Module) -> tuple[int, int] | None:
    ids: set[int] = set()
    for name, _ in model.named_modules():
        m = re.search(r"(?:blocks|layers)\.(\d+)\b", name)
        if m:
            ids.add(int(m.group(1)))
    if not ids:
        return None
    return min(ids), max(ids)


def build_filter_fn(model, skip_patterns, skip_first_last: bool = True, min_dim: int = MIN_LINEAR_DIM):
    bounds = _block_bounds(model) if skip_first_last else None
    pats = [p.lower() for p in (skip_patterns or []) if p]

    def fn(mod, fqn: str) -> bool:
        if not isinstance(mod, torch.nn.Linear):
            return False
        if mod.in_features % 16 or mod.out_features % 16:
            return False
        if min(mod.in_features, mod.out_features) < min_dim:
            return False
        low = fqn.lower()
        if any(p in low for p in pats):
            return False
        if bounds is not None:
            m = re.search(r"(?:blocks|layers)\.(\d+)\b", low)
            if m and int(m.group(1)) in bounds:
                return False
        return True

    return fn


def apply_quant(model, mode: str, skip_patterns=None, skip_first_last: bool = True):
    if mode in ("none", "bf16"):
        return model
    from torchao.quantization import quantize_

    if mode == "nvfp4":
        from torchao.prototype.mx_formats import NVFP4WeightOnlyConfig

        quantize_(model, NVFP4WeightOnlyConfig(),
                  filter_fn=build_filter_fn(model, skip_patterns, skip_first_last))
    elif mode == "int8wo":
        from torchao.quantization import Int8WeightOnlyConfig

        quantize_(model, Int8WeightOnlyConfig())
    else:
        raise ValueError(f"unknown quant mode: {mode}")
    return model


def resolve_precision(env_nvfp4: str | None = None, skip_env: str | None = None) -> dict:
    """Returns {mode, skip_patterns, skip_first_last, source, capability, gpu[, config_name]}."""
    if env_nvfp4 is None:
        env_nvfp4 = os.getenv("ENABLE_NVFP4", "")
    if skip_env is None:
        skip_env = os.getenv("CUTEDSL_NVFP4_SKIP", "")
    env_skip = [s.strip() for s in skip_env.split(",") if s.strip()]

    if not torch.cuda.is_available():
        return {"mode": "bf16", "skip_patterns": [], "skip_first_last": False,
                "source": "no-cuda", "capability": None, "gpu": "cpu"}

    cap = tuple(torch.cuda.get_device_capability(0))
    gpu = torch.cuda.get_device_name(0)
    base = {"capability": cap, "gpu": gpu, "skip_first_last": True,
            "skip_patterns": env_skip or list(DEFAULT_NVFP4_SKIP)}

    if env_nvfp4 == "0":
        return {**base, "mode": "bf16", "source": "env"}
    if env_nvfp4 == "1":
        return {**base, "mode": "nvfp4", "source": "env"}
    if os.getenv("ENABLE_INT8WO", "") == "1":
        return {**base, "mode": "int8wo", "source": "env"}

    tuned = load_autotune(gpu_slug(gpu))
    if tuned:
        cfg = tuned["config"]
        mode = cfg.get("quant") or ("nvfp4" if cfg["name"].startswith("nvfp4")
                                    else "int8wo" if "int8" in cfg["name"] else "bf16")
        return {**base, "mode": mode,
                "skip_patterns": env_skip or cfg.get("skip_patterns", []),
                "skip_first_last": bool(cfg.get("skip_first_last", True)),
                "source": "autotune", "config_name": cfg["name"]}

    if cap[0] >= 10:
        return {**base, "mode": "nvfp4", "source": "heuristic"}
    return {**base, "mode": "bf16", "source": "heuristic"}


def pareto_frontier(points, latency_key: str = "latency_s", quality_key: str = "psnr") -> list[bool]:
    def q(p):
        v = p.get(quality_key)
        if isinstance(v, dict):
            v = v.get(quality_key)
        return v if v is not None else float("-inf")

    flags = []
    for p in points:
        dominated = any(
            o is not p
            and o[latency_key] <= p[latency_key]
            and q(o) >= q(p)
            and (o[latency_key] < p[latency_key] or q(o) > q(p))
            for o in points
        )
        flags.append(not dominated)
    return flags


def choose_config(results, psnr_min: float) -> str | None:
    if not results:
        return None
    ok = [r for r in results if (r.get("quality", {}).get("psnr") or float("-inf")) >= psnr_min]
    if not ok:
        ok = results
    return min(ok, key=lambda r: r["latency_s"])["name"]
