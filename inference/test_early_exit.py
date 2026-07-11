"""Unit tests for early-exit and no-op-step-skip callback logic.

Pure tests over _run_zimage_capture_multi with a fake pipe that mimics the
diffusers Z-Image denoising loop contract (interrupt + callback semantics).
"""

import os
import sys
import types

import pytest
import torch

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("LOAD_ZIMAGE", "0")
os.environ.setdefault("PRELOAD_MODELS", "0")

import server


class FakePipe:
    def __init__(self, sigmas, velocity=None):
        self.scheduler = types.SimpleNamespace(sigmas=torch.tensor(sigmas))
        self._sigmas = sigmas
        self._interrupt = False
        self.executed_steps = 0
        self.velocity = velocity

    @property
    def interrupt(self):
        return self._interrupt

    def __call__(self, callback_on_step_end=None, callback_on_step_end_tensor_inputs=None, **kw):
        n = len(self._sigmas) - 1
        self._interrupt = False
        self._num_timesteps = n
        torch.manual_seed(0)
        z = torch.randn(1, 4, 8, 8)
        v = self.velocity if self.velocity is not None else torch.randn_like(z)
        for i in range(n):
            if self._interrupt:
                continue
            self.executed_steps += 1
            z = z + (self._sigmas[i + 1] - self._sigmas[i]) * v
            if callback_on_step_end is not None:
                out = callback_on_step_end(self, i, None, {"latents": z})
                z = out.pop("latents", z)
        return types.SimpleNamespace(images=[z], latents=z)


def test_noop_terminal_step_skipped(monkeypatch):
    monkeypatch.setattr(server, "ZIMAGE_SKIP_NOOP_STEPS", True)
    pipe = FakePipe([1.0, 0.5, 0.25, 0.0, 0.0])
    exit_info = {}
    result, captured = server._run_zimage_capture_multi(
        pipe, {}, capture_steps=(3,), timing_out={}, exit_info=exit_info)
    assert pipe.executed_steps == 3
    assert exit_info["noop_steps_skipped"] == 1
    assert 3 in captured  # capture fulfilled with the (identical) latent


def test_noop_skip_bitwise_identical(monkeypatch):
    sig = [1.0, 0.5, 0.25, 0.0, 0.0]
    monkeypatch.setattr(server, "ZIMAGE_SKIP_NOOP_STEPS", False)
    full, _ = server._run_zimage_capture_multi(FakePipe(sig), {}, (), timing_out={})
    monkeypatch.setattr(server, "ZIMAGE_SKIP_NOOP_STEPS", True)
    skipped, _ = server._run_zimage_capture_multi(FakePipe(sig), {}, (), timing_out={})
    assert torch.equal(full.latents, skipped.latents)


def test_early_exit_constant_velocity(monkeypatch):
    monkeypatch.setattr(server, "ZIMAGE_SKIP_NOOP_STEPS", False)
    sig = [1.0, 0.8, 0.6, 0.4, 0.2, 0.0]
    torch.manual_seed(1)
    v = torch.randn(1, 4, 8, 8)
    exit_info = {}
    result, _ = server._run_zimage_capture_multi(
        FakePipe(sig, velocity=v), {}, (), timing_out={},
        early_exit=0.01, early_exit_min_steps=3, exit_info=exit_info)
    # constant velocity => x0-hat identical every step => exits at min_steps
    assert exit_info["exited_after_step"] == 3
    # exit latent must equal the exact final latent (linear flow)
    full, _ = server._run_zimage_capture_multi(
        FakePipe(sig, velocity=v), {}, (), timing_out={})
    assert torch.allclose(result.latents, full.latents, atol=1e-5)


def test_early_exit_not_triggered_below_min_steps(monkeypatch):
    monkeypatch.setattr(server, "ZIMAGE_SKIP_NOOP_STEPS", False)
    sig = [1.0, 0.8, 0.6, 0.4, 0.2, 0.0]
    torch.manual_seed(1)
    v = torch.randn(1, 4, 8, 8)
    exit_info = {}
    pipe = FakePipe(sig, velocity=v)
    server._run_zimage_capture_multi(
        pipe, {}, (), timing_out={},
        early_exit=0.01, early_exit_min_steps=99, exit_info=exit_info)
    assert not exit_info
    assert pipe.executed_steps == 5


def test_early_exit_noisy_velocity_no_trigger(monkeypatch):
    monkeypatch.setattr(server, "ZIMAGE_SKIP_NOOP_STEPS", False)

    class NoisyPipe(FakePipe):
        def __call__(self, callback_on_step_end=None, **kw):
            n = len(self._sigmas) - 1
            self._interrupt = False
            self._num_timesteps = n
            torch.manual_seed(0)
            z = torch.randn(1, 4, 8, 8)
            for i in range(n):
                if self._interrupt:
                    continue
                self.executed_steps += 1
                z = z + (self._sigmas[i + 1] - self._sigmas[i]) * torch.randn_like(z)
                if callback_on_step_end is not None:
                    out = callback_on_step_end(self, i, None, {"latents": z})
                    z = out.pop("latents", z)
            return types.SimpleNamespace(images=[z], latents=z)

    exit_info = {}
    pipe = NoisyPipe([1.0, 0.8, 0.6, 0.4, 0.2, 0.0])
    server._run_zimage_capture_multi(
        pipe, {}, (), timing_out={},
        early_exit=0.001, early_exit_min_steps=2, exit_info=exit_info)
    assert not exit_info
    assert pipe.executed_steps == 5


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
