"""Regression tests for POST /experimental/step_trace.

Production telemetry recorded a 503 "zimage not loaded" for
``/experimental/step_trace`` on a deployment where zimage is served by the
native fallback, so the in-process pipeline is intentionally cold. The route
also bypassed model admission, letting an idle unload or /admin/hold race the
trace, and accepted unvalidated dimensions, step counts, and sigma schedules.
"""

import asyncio
import contextlib
import sys
from pathlib import Path

import httpx
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402


@contextlib.asynccontextmanager
async def _unlimited_slot(_low_priority=False):
    yield


@pytest.fixture(autouse=True)
def _no_gpu(monkeypatch):
    monkeypatch.setattr(server, "LOAD_ZIMAGE", True)
    monkeypatch.setattr(server, "gpu_slot", _unlimited_slot)
    monkeypatch.setattr(server, "ZIMAGE_LOCAL_COLD_FALLBACK_ENABLED", True)
    monkeypatch.setattr(server, "IMAGE_API_SECRETS", set())
    monkeypatch.setattr(server, "_raise_if_zimage_cuda_unavailable", lambda: None)
    monkeypatch.setattr(server, "_reclaim_zimage_cold_load_headroom", lambda *_a, **_k: None)
    monkeypatch.setattr(server, "_zimage_memory_pressure_detail", lambda *_a, **_k: None)
    monkeypatch.setattr(server, "_schedule_cuda_process_restart", lambda: None)
    monkeypatch.setattr(server, "_unload_nsfw_classifier", lambda: None)
    monkeypatch.setattr(server, "_init_lora_engine", lambda: None)
    monkeypatch.setattr(server, "_deactivate_loras", lambda _pipe: None)
    monkeypatch.setattr(server, "_reset_zimage_scheduler", lambda _pipe: None)
    monkeypatch.setattr(server, "_make_pipeline_generator", lambda _pipe, _seed: None)
    monkeypatch.setattr(server, "_text_encoder_on_cpu", lambda: False)
    monkeypatch.setattr(
        server,
        "_prepare_zimage_prompt_embeddings",
        lambda _pipe, kwargs: (kwargs, {"enabled": False, "hit": False, "encode_ms": 0}),
    )
    monkeypatch.setattr(server, "nsfw_classifier", None)


class _FakeScheduler:
    def __init__(self, steps: int):
        self.sigmas = [1.0 - i / steps for i in range(steps)] + [0.0]


class _FakePipe:
    def __init__(self, steps: int):
        self.scheduler = _FakeScheduler(steps)
        self.calls = []
        self._offload_gpu_id = "cuda:0"

    def to(self, _device):
        raise AssertionError("offloaded pipelines must not be moved wholesale")

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        steps = kwargs["num_inference_steps"]
        callback = kwargs["callback_on_step_end"]
        for index in range(steps):
            callback(
                self,
                index,
                0.0,
                {
                    "latents": server.torch.zeros(1, 4, 8, 8),
                    "noise_pred": server.torch.ones(1, 4, 8, 8),
                },
            )
        return type("Result", (), {"images": [Image.new("RGB", (64, 64), (1, 2, 3))]})()


def _load_test_pipeline(monkeypatch, steps=2):
    pipe = _FakePipe(steps)
    loaded = []

    def _fake_load():
        loaded.append(True)
        server.zimage_pipeline = (pipe, None)

    monkeypatch.setattr(server, "_load_zimage", _fake_load)
    return pipe, loaded


def _request(prompt="a cat", **overrides):
    payload = {"prompt": prompt, "width": 512, "height": 512, "num_inference_steps": 2}
    payload.update(overrides)
    return server.StepTraceRequest(**payload)


def _post(payload):
    async def run():
        transport = httpx.ASGITransport(app=server.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/experimental/step_trace", json=payload)

    return asyncio.run(run())


def test_cold_pipeline_is_lazily_loaded_under_the_model_manager(monkeypatch, tmp_path):
    """The reported failure: native-served deployments keep the local pipeline cold."""
    manager = server.ModelManager()
    pipe, loaded = _load_test_pipeline(monkeypatch)
    monkeypatch.setattr(server, "model_manager", manager)
    monkeypatch.setattr(server, "zimage_pipeline", None)
    monkeypatch.setattr(server, "STEP_TRACE_DIR", str(tmp_path))

    result = server._step_trace_sync(
        _request(decode_x0=False, save_tensors=False)
    )

    assert loaded == [True]
    assert manager.is_loaded("zimage")
    assert result["gen_seconds"] >= 0
    assert [row["step"] for row in result["steps"]] == [0, 1]
    assert result["steps"][0]["sigma"] == 1.0
    assert pipe.calls


def test_trace_keeps_the_model_pinned_for_the_whole_run(monkeypatch, tmp_path):
    """An idle unload or admin drop must not land between load and trace."""
    manager = server.ModelManager()
    _load_test_pipeline(monkeypatch)
    monkeypatch.setattr(server, "model_manager", manager)
    monkeypatch.setattr(server, "zimage_pipeline", None)
    monkeypatch.setattr(server, "STEP_TRACE_DIR", str(tmp_path))

    observed = {}

    def _fake_run(_req):
        observed["in_use"] = manager._in_use.get("zimage", 0)
        return {"ok": True}

    monkeypatch.setattr(server, "_step_trace_run", _fake_run)

    assert server._step_trace_sync(_request()) == {"ok": True}
    assert observed["in_use"] == 1
    assert manager._in_use.get("zimage", 0) == 0


def test_long_prompts_are_accepted_across_lengths(monkeypatch, tmp_path):
    """Prompt length is not silently bounded by the trace route."""
    _load_test_pipeline(monkeypatch)
    monkeypatch.setattr(server, "model_manager", server.ModelManager())
    monkeypatch.setattr(server, "zimage_pipeline", None)
    monkeypatch.setattr(server, "STEP_TRACE_DIR", str(tmp_path))

    for length in (1, 200, 4000, 30000):
        result = server._step_trace_sync(
            _request(prompt="x" * length, decode_x0=False, save_tensors=False)
        )
        assert result["steps"]


@pytest.mark.parametrize("steps", [0, -1, 101])
def test_step_count_is_bounded(steps):
    with pytest.raises(ValueError):
        _request(num_inference_steps=steps)


@pytest.mark.parametrize("dimension", [dict(width=0), dict(height=16), dict(width=8192)])
def test_dimensions_are_bounded(dimension):
    with pytest.raises(ValueError):
        _request(**dimension)


def test_whitespace_prompt_is_rejected():
    with pytest.raises(ValueError):
        _request(prompt="   \n\t ")


def test_control_characters_are_rejected():
    with pytest.raises(ValueError):
        _request(prompt="a cat\x00in snow")


@pytest.mark.parametrize(
    "sigmas",
    [
        [1.1, 0.5],
        [0.0, 0.0],
        [1.0, float("nan")],
    ],
)
def test_invalid_sigma_schedules_are_rejected(sigmas):
    with pytest.raises(ValueError):
        _request(sigmas=sigmas, num_inference_steps=len(sigmas))


def test_sigmas_must_match_step_count(monkeypatch):
    monkeypatch.setattr(server, "_step_trace_sync", lambda _req: pytest.fail("must not run"))
    response = _post(
        {"prompt": "a cat", "num_inference_steps": 4, "sigmas": [1.0, 0.5, 0.0]}
    )
    assert response.status_code == 400
    assert "sigmas length" in response.json()["detail"]


def test_endpoint_waits_for_admission_instead_of_racing_the_gpu(monkeypatch):
    manager = server.ModelManager()
    manager.hold(30)
    monkeypatch.setattr(server, "model_manager", manager)
    monkeypatch.setattr(server, "_step_trace_sync", lambda _req: pytest.fail("must not run"))

    response = _post({"prompt": "a cat"})

    assert response.status_code == 503
    assert response.headers["retry-after"]


def test_endpoint_runs_after_admission(monkeypatch):
    manager = server.ModelManager()
    seen = []

    def _fake_run(_req):
        seen.append(manager._in_use.get("zimage", 0))
        return {"trace_id": "t", "steps": []}

    monkeypatch.setattr(server, "model_manager", manager)
    monkeypatch.setattr(server, "_step_trace_sync", lambda req: _fake_run(req))

    response = _post({"prompt": "a cat", "low_priority": False})

    assert response.status_code == 200
    assert response.json()["trace_id"] == "t"
    assert seen == [0]  # endpoint reservation is not the retry wrapper's pin


def test_disabled_model_returns_capability_error(monkeypatch):
    monkeypatch.setattr(server, "LOAD_ZIMAGE", False)
    response = _post({"prompt": "a cat"})
    assert response.status_code == 503
    assert response.json()["detail"] == "zimage disabled"


def test_native_primary_deployment_does_not_cold_load_a_duplicate_pipeline(monkeypatch):
    """The production policy must win over the trace route's lazy load."""
    manager = server.ModelManager()
    pipe, loaded = _load_test_pipeline(monkeypatch)
    monkeypatch.setattr(server, "model_manager", manager)
    monkeypatch.setattr(server, "zimage_pipeline", None)
    monkeypatch.setattr(server, "ZIMAGE_LOCAL_COLD_FALLBACK_ENABLED", False)
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_URL", "http://127.0.0.1:8791")

    with pytest.raises(server.HTTPException) as exc:
        server._step_trace_sync(_request(decode_x0=False, save_tensors=False))

    assert exc.value.status_code == 503
    assert exc.value.headers["Retry-After"] == "60"
    assert "ZIMAGE_LOCAL_COLD_FALLBACK_ENABLED=0" in exc.value.detail
    assert loaded == []
    assert not manager.is_loaded("zimage")


def test_resident_pipeline_is_traced_even_when_cold_loads_are_disabled(monkeypatch, tmp_path):
    """A resident pipeline (preload, or a prior operator load) keeps working."""
    manager = server.ModelManager()
    pipe, _loaded = _load_test_pipeline(monkeypatch)
    server._load_zimage()
    manager._loaded.add("zimage")
    monkeypatch.setattr(server, "model_manager", manager)
    monkeypatch.setattr(server, "ZIMAGE_LOCAL_COLD_FALLBACK_ENABLED", False)
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_URL", "http://127.0.0.1:8791")
    monkeypatch.setattr(server, "STEP_TRACE_DIR", str(tmp_path))

    result = server._step_trace_sync(_request(decode_x0=False, save_tensors=False))

    assert [row["step"] for row in result["steps"]] == [0, 1]


def test_standalone_deployment_lazily_loads_without_a_native_backend(monkeypatch, tmp_path):
    manager = server.ModelManager()
    _pipe, loaded = _load_test_pipeline(monkeypatch)
    monkeypatch.setattr(server, "model_manager", manager)
    monkeypatch.setattr(server, "zimage_pipeline", None)
    monkeypatch.setattr(server, "ZIMAGE_LOCAL_COLD_FALLBACK_ENABLED", False)
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_URL", "")
    monkeypatch.setattr(server, "STEP_TRACE_DIR", str(tmp_path))

    result = server._step_trace_sync(_request(decode_x0=False, save_tensors=False))

    assert loaded == [True]
    assert result["steps"]
