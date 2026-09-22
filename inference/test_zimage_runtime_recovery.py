import contextlib
import sys
import types
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402


def test_cudagraph_list_assertion_detection(monkeypatch):
    exc = AssertionError("<class 'list'>")

    monkeypatch.setattr(
        server.traceback,
        "format_exception",
        lambda *_args: [
            "File torch/_inductor/cudagraph_trees.py, line 1092, in __init__\n",
            "node = CUDAGraphNode(...)\n",
            "AssertionError: <class 'list'>\n",
        ],
    )

    assert server._is_zimage_cudagraph_list_assertion(exc)


def test_cudagraph_list_assertion_detection_ignores_unrelated_assertions(monkeypatch):
    exc = AssertionError("<class 'list'>")

    monkeypatch.setattr(
        server.traceback,
        "format_exception",
        lambda *_args: ["AssertionError: <class 'list'>\n"],
    )

    assert not server._is_zimage_cudagraph_list_assertion(exc)


def test_zimage_compile_mode_downgrades_without_changing_generation_inputs(monkeypatch):
    resets = []
    monkeypatch.setattr(server.torch._dynamo, "reset", lambda: resets.append(True))

    with server._zimage_compile_mode_lock:
        server._zimage_compile_mode = "reduce-overhead"
    assert server._downgrade_zimage_compile_mode("test")
    assert server._get_zimage_compile_mode() == "default"

    assert server._downgrade_zimage_compile_mode("test")
    assert server._get_zimage_compile_mode() is None
    assert resets == [True, True]


def test_zimage_retry_recovers_from_cudagraph_assertion(monkeypatch):
    class FakeModelManager:
        @contextlib.contextmanager
        def use(self, _model_name):
            yield

    calls = []
    recoveries = []
    monkeypatch.setattr(server, "model_manager", FakeModelManager())
    monkeypatch.setattr(server, "zimage_pipeline", (object(), None))
    monkeypatch.setattr(server, "_is_cuda_oom", lambda _exc: False)
    monkeypatch.setattr(server, "_is_zimage_cudagraph_list_assertion", lambda _exc: True)
    monkeypatch.setattr(server, "_downgrade_zimage_compile_mode", lambda _reason: True)
    monkeypatch.setattr(server, "_recover_from_zimage_runtime_fault", lambda reason: recoveries.append(reason))

    def fn():
        calls.append(True)
        if len(calls) == 1:
            raise AssertionError("<class 'list'>")
        return {"ok": True}

    assert server._with_zimage_model_retry("generate_image", fn) == {"ok": True}
    assert len(calls) == 2
    assert recoveries == ["torch inductor CUDA graph assertion"]


def test_force_unload_clears_cutezimage_pipeline_cache(monkeypatch):
    clear_calls = []
    fake_pipeline = types.ModuleType("cutezimage.pipeline")
    fake_pipeline.clear_pipeline_caches = lambda: clear_calls.append(True)
    fake_package = types.ModuleType("cutezimage")
    fake_package.__path__ = []

    monkeypatch.setitem(sys.modules, "cutezimage", fake_package)
    monkeypatch.setitem(sys.modules, "cutezimage.pipeline", fake_pipeline)
    monkeypatch.setattr(server.torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(server, "zimage_pipeline", (object(), None))

    manager = server.ModelManager()
    manager._loaded.add("zimage")
    manager._last_access["zimage"] = 1.0

    assert manager.force_unload("zimage") == ["zimage"]
    assert server.zimage_pipeline is None
    assert clear_calls == [True]


def test_pipeline_generator_matches_cpu_execution_device():
    class FakePipe:
        _execution_device = "cpu"

    generator = server._make_pipeline_generator(FakePipe(), 123)

    assert str(generator.device) == "cpu"
    assert generator.initial_seed() == 123


def test_pipeline_generator_uses_pipe_device_when_execution_device_missing():
    class FakePipe:
        device = "cpu"

        @property
        def _execution_device(self):
            raise RuntimeError("offload hook not initialized")

    generator = server._make_pipeline_generator(FakePipe(), 456)

    assert str(generator.device) == "cpu"
    assert generator.initial_seed() == 456


def test_load_zimage_falls_back_to_cpu_offload_after_cuda_move_failure(monkeypatch):
    class FakeComponent:
        def to(self, _device):
            raise RuntimeError("CUDA out of memory")

    class FakeScheduler:
        _step_index = None
        sigmas = [1, 0]

        def step(self):
            return None

    class FakeZImagePipeline:
        def __init__(self):
            self.transformer = FakeComponent()
            self.vae = FakeComponent()
            self.text_encoder = FakeComponent()
            self.scheduler = FakeScheduler()
            self.components = {
                "transformer": self.transformer,
                "vae": self.vae,
                "text_encoder": self.text_encoder,
                "scheduler": self.scheduler,
            }
            self.offload_enabled = False

        @classmethod
        def from_pretrained(cls, *_args, **_kwargs):
            return cls()

        def enable_model_cpu_offload(self):
            self.offload_enabled = True

    class FakeImg2ImgPipeline:
        def __init__(self, **components):
            self.components = components

    try:
        import diffusers
    except Exception as exc:  # pragma: no cover - test environment dependency
        pytest.skip(f"diffusers unavailable: {exc}")

    monkeypatch.setattr(diffusers, "ZImagePipeline", FakeZImagePipeline)
    monkeypatch.setattr(diffusers, "ZImageImg2ImgPipeline", FakeImg2ImgPipeline)
    monkeypatch.setattr(server, "ENABLE_NVFP4", False)
    monkeypatch.setattr(server, "ZIMAGE_USE_CUTE", False)
    monkeypatch.setattr(server, "AITUNE_ENGINES_PATH", "")
    monkeypatch.setattr(server, "_zimage_cpu_offload_enabled", lambda: False)
    monkeypatch.setenv("ZIMAGE_SKIP_WARMUP", "1")
    monkeypatch.setattr(server, "zimage_pipeline", None)

    server._load_zimage()

    text2img_pipe, _img2img_pipe = server.zimage_pipeline
    assert text2img_pipe.offload_enabled
