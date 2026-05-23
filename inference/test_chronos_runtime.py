import torch
import pytest

pytest.importorskip("uvicorn")
import server


def test_chronos_runtime_falls_back_to_cpu_when_cuda_unavailable(monkeypatch):
    monkeypatch.setattr(server, "DEVICE", "cuda")
    monkeypatch.setattr(server, "DTYPE", torch.bfloat16)
    monkeypatch.setattr(server.torch.cuda, "is_available", lambda: False)

    assert server._chronos_device_dtype() == ("cpu", torch.float32)


def test_chronos_runtime_uses_configured_device_when_available(monkeypatch):
    monkeypatch.setattr(server, "DEVICE", "cuda")
    monkeypatch.setattr(server, "DTYPE", torch.bfloat16)
    monkeypatch.setattr(server.torch.cuda, "is_available", lambda: True)

    assert server._chronos_device_dtype() == ("cuda", torch.bfloat16)
