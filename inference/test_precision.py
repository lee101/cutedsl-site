import json
import os
import sys

import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import precision


def test_gpu_slug():
    assert precision.gpu_slug("NVIDIA GeForce RTX 5090") == "nvidia-geforce-rtx-5090"
    assert precision.gpu_slug("NVIDIA GeForce RTX 3090 Ti") == "nvidia-geforce-rtx-3090-ti"


def test_pareto_frontier():
    pts = [
        {"latency_s": 1.0, "psnr": 99.0},
        {"latency_s": 0.5, "psnr": 40.0},
        {"latency_s": 0.6, "psnr": 35.0},
        {"latency_s": 0.4, "psnr": 20.0},
    ]
    assert precision.pareto_frontier(pts) == [True, True, False, True]


def test_choose_config():
    results = [
        {"name": "bf16", "latency_s": 1.0, "quality": {"psnr": 99.0}},
        {"name": "nvfp4-all", "latency_s": 0.5, "quality": {"psnr": 28.0}},
        {"name": "nvfp4-skip", "latency_s": 0.6, "quality": {"psnr": 35.0}},
    ]
    assert precision.choose_config(results, 32.0) == "nvfp4-skip"
    assert precision.choose_config(results, 50.0) == "bf16"
    assert precision.choose_config(results, 10.0) == "nvfp4-all"


class _Blk(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.qkv = torch.nn.Linear(2048, 2048)
        self.norm_out = torch.nn.Linear(2048, 2048)


class _M(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.blocks = torch.nn.ModuleList([_Blk() for _ in range(4)])
        self.time_embed = torch.nn.Linear(2048, 2048)
        self.small = torch.nn.Linear(64, 64)
        self.odd = torch.nn.Linear(2048, 2050)


def test_filter_fn():
    m = _M()
    fn = precision.build_filter_fn(m, precision.DEFAULT_NVFP4_SKIP, skip_first_last=True)
    assert fn(m.blocks[1].qkv, "blocks.1.qkv")
    assert fn(m.blocks[2].qkv, "blocks.2.qkv")
    assert not fn(m.blocks[0].qkv, "blocks.0.qkv")
    assert not fn(m.blocks[3].qkv, "blocks.3.qkv")
    assert not fn(m.time_embed, "time_embed")
    assert not fn(m.blocks[1].norm_out, "blocks.1.norm_out")
    assert not fn(m.small, "small")
    assert not fn(m.odd, "odd")

    fn_all = precision.build_filter_fn(m, [], skip_first_last=False)
    assert fn_all(m.blocks[0].qkv, "blocks.0.qkv")
    assert fn_all(m.blocks[1].norm_out, "blocks.1.norm_out")


def test_load_autotune(tmp_path):
    p = tmp_path / "gpu.json"
    p.write_text(json.dumps({
        "gpu": "NVIDIA GeForce RTX 5090",
        "configs": [
            {"name": "bf16", "quant": "none", "skip_patterns": [], "skip_first_last": False},
            {"name": "nvfp4-skip-first-last-emb", "quant": "nvfp4",
             "skip_patterns": ["embed"], "skip_first_last": True},
        ],
        "chosen": "nvfp4-skip-first-last-emb",
    }))
    tuned = precision.load_autotune(path=p)
    assert tuned["config"]["name"] == "nvfp4-skip-first-last-emb"
    assert tuned["config"]["skip_patterns"] == ["embed"]
    assert precision.load_autotune(path=tmp_path / "missing.json") is None


def test_resolve_precision_env_off(monkeypatch):
    if not torch.cuda.is_available():
        p = precision.resolve_precision(env_nvfp4="0")
        assert p["mode"] == "bf16"
        return
    p = precision.resolve_precision(env_nvfp4="0")
    assert p["mode"] == "bf16" and p["source"] == "env"
    p = precision.resolve_precision(env_nvfp4="1", skip_env="foo,bar")
    assert p["mode"] == "nvfp4" and p["skip_patterns"] == ["foo", "bar"]
