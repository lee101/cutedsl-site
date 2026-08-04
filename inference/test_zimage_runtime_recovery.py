import contextlib
import sys
import types
from pathlib import Path

import pytest
from starlette.requests import Request


sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402


@pytest.fixture(autouse=True)
def _assume_healthy_cuda_preflight(monkeypatch):
    """Unit recovery tests use fakes and must not depend on the host GPU."""
    monkeypatch.setattr(server, "_cuda_unavailable_detail", lambda **_kwargs: None)
    monkeypatch.setattr(server, "_schedule_cuda_process_restart", lambda: None)
    monkeypatch.setattr(server, "COEXISTING_TEXT_SLEEP_URL", "")
    # The production singleton intentionally coordinates with the live text
    # adapter. Tests must never mutate a service running on localhost.
    monkeypatch.setattr(server.model_manager, "_coexisting_text_sleep", None)


def _fake_request(path: str = "/generate_image", query_string: bytes = b"") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
            "query_string": query_string,
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 8100),
            "scheme": "http",
        }
    )


def test_model_manager_hold_rejects_new_gpu_admission(monkeypatch):
    manager = server.ModelManager(
        lambda _model: pytest.fail("held admission must fail before cross-service work")
    )
    manager.hold(30)

    with pytest.raises(server.HTTPException) as exc:
        manager.ensure_loaded("zimage")

    assert exc.value.status_code == 503
    assert manager.hold_remaining() > 0
    manager.release_hold()
    assert manager.hold_remaining() == 0


def test_admin_hold_refuses_active_admission_without_pausing_or_unloading(monkeypatch):
    manager = server.ModelManager()
    manager._loaded.add("zimage")
    manager._last_access["zimage"] = server.time.time()
    unloads = []
    monkeypatch.setattr(server, "model_manager", manager)
    monkeypatch.setattr(manager, "force_unload", lambda *_args: unloads.append(True) or [])

    with manager.reserve("zimage"):
        with pytest.raises(server.HTTPException) as exc_info:
            server.admin_hold(600)

        assert exc_info.value.status_code == 409
        assert exc_info.value.headers == {"Retry-After": "2"}
        assert manager.hold_remaining() == 0
        assert unloads == []


def test_admin_unload_cannot_bypass_rejected_hold(monkeypatch):
    manager = server.ModelManager()
    unloads = []
    monkeypatch.setattr(server, "model_manager", manager)
    monkeypatch.setattr(manager, "force_unload", lambda *_args: unloads.append(True) or [])

    with pytest.raises(server.HTTPException) as exc_info:
        server.admin_unload()

    assert exc_info.value.status_code == 409
    assert exc_info.value.headers == {"Retry-After": "2"}
    assert manager.hold_remaining() == 0
    assert unloads == []


def test_admin_unload_is_allowed_after_successful_hold(monkeypatch):
    manager = server.ModelManager()
    unloads = []
    monkeypatch.setattr(server, "model_manager", manager)
    monkeypatch.setattr(server.torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(manager, "force_unload", lambda *_args: unloads.append(True) or [])

    manager.hold(30)
    response = server.admin_unload()

    assert response["loaded"] == []
    assert response["hold_seconds_remaining"] > 0
    assert unloads == [True]


@pytest.mark.parametrize("prompt_len", [153, 208, 297, 4096])
def test_queued_prompt_reservation_blocks_peer_hold(monkeypatch, prompt_len):
    manager = server.ModelManager()

    class FakeBatcher:
        async def submit(self, req):
            remaining, busy = manager.try_hold(600)
            assert remaining is None
            assert busy == {"zimage": 1}
            return {"prompt_len": len(req.prompt)}

    monkeypatch.setattr(server, "model_manager", manager)
    monkeypatch.setattr(server, "zimage_dynamic_batcher", FakeBatcher())

    result = server.asyncio.run(
        server._submit_zimage_request(server.ZImageRequest(prompt="x" * prompt_len))
    )

    assert result == {"prompt_len": prompt_len}
    assert manager._admitted == {}


def test_model_cold_load_sleeps_text_backend_before_taking_manager_lock(monkeypatch):
    events = []

    def probe_lock(model):
        acquired = manager._lock.acquire(blocking=False)
        if acquired:
            manager._lock.release()
        events.append((model, acquired))
        return True

    manager = server.ModelManager(probe_lock)

    manager.ensure_loaded("test-model")

    # The non-blocking acquire proves the network handshake ran without the
    # manager lock held.
    assert events == [("test-model", True)]


def test_model_use_coordinates_even_when_pipeline_is_already_loaded(monkeypatch):
    events = []
    manager = server.ModelManager(lambda model: events.append(model) or True)
    manager._loaded.add("zimage")
    manager._last_access["zimage"] = server.time.time()
    monkeypatch.setattr(manager, "_reset_idle_timer", lambda: None)

    with manager.use("zimage"):
        assert manager._in_use["zimage"] == 1

    assert events == ["zimage"]


def test_model_use_detects_admin_unload_before_pin(monkeypatch):
    manager = server.ModelManager()

    def unload_between_ensure_and_pin(_model, **_kwargs):
        manager._loaded.add("zimage")
        manager.force_unload("zimage")

    monkeypatch.setattr(manager, "ensure_loaded", unload_between_ensure_and_pin)
    with pytest.raises(server.HTTPException, match="unloaded before inference"):
        with manager.use("zimage"):
            pytest.fail("unloaded pipeline must never be entered")


def test_model_cold_load_defers_while_text_inference_is_active(monkeypatch):
    class BusyResponse:
        status_code = 409

    monkeypatch.setattr(server, "COEXISTING_TEXT_SLEEP_URL", "http://text/backend/sleep")
    monkeypatch.setattr(server.requests, "post", lambda *_args, **_kwargs: BusyResponse())

    with pytest.raises(server.HTTPException) as exc:
        server._sleep_coexisting_text_backend("zimage")

    assert exc.value.status_code == 503
    assert exc.value.headers["Retry-After"] == "5"


def test_existing_server_guard_waits_without_loading_models(monkeypatch):
    probes = iter([True, True, False])
    sleeps = []
    monkeypatch.setenv("INFERENCE_WAIT_FOR_EXISTING_SERVER", "1")
    monkeypatch.setenv("INFERENCE_EXISTING_SERVER_POLL_SECONDS", "0.25")
    monkeypatch.setattr(server, "_local_port_has_listener", lambda _port: next(probes))
    monkeypatch.setattr(server.time, "sleep", lambda seconds: sleeps.append(seconds))

    assert server._wait_for_existing_local_server(8100) is True
    assert sleeps == [0.25]


def test_cancelled_delayed_preload_never_touches_model_manager(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "PRELOAD_DELAY_SECONDS", 60)
    monkeypatch.setattr(server.model_manager, "ensure_loaded", lambda model: calls.append(model))

    async def cancel_before_delay_expires():
        task = server.asyncio.create_task(server._preload_model_after_startup("zimage"))
        await server.asyncio.sleep(0)
        task.cancel()
        with pytest.raises(server.asyncio.CancelledError):
            await task

    server.asyncio.run(cancel_before_delay_expires())

    assert calls == []


def test_latent_cache_key_is_versioned_and_runtime_specific(monkeypatch):
    monkeypatch.setattr(server, "ZIMAGE_LATENT_CACHE_VERSION", "v2")
    monkeypatch.setattr(server, "ZIMAGE_MODEL_PATH", "model-a")
    monkeypatch.setattr(server, "PRECISION", {"mode": "bf16"})
    monkeypatch.setattr(server, "ZIMAGE_USE_CUTE", False)

    first = server._latent_teleport_unit("prompt", 512, 512, 8, 42)
    same = server._latent_teleport_unit("prompt", 512, 512, 8, 42)
    monkeypatch.setattr(server, "ZIMAGE_LATENT_CACHE_VERSION", "v3")
    changed = server._latent_teleport_unit("prompt", 512, 512, 8, 42)

    assert first.unit_id == same.unit_id
    assert first.unit_id != changed.unit_id


def test_latent_cache_is_constructed_with_bounded_retention(monkeypatch):
    import latentteleport.cache as cache_module

    captured = {}

    class FakeCache:
        def __init__(self, cache_dir, resolution, **kwargs):
            captured.update(cache_dir=cache_dir, resolution=resolution, **kwargs)
            self.resolution = resolution

    monkeypatch.setattr(cache_module, "LatentCache", FakeCache)
    monkeypatch.setattr(server, "latent_teleport_cache", None)
    monkeypatch.setattr(server, "LATENT_TELEPORT_CACHE_DIR", "/tmp/teleport")
    monkeypatch.setattr(server, "LATENT_TELEPORT_MAX_ENTRIES_PER_RESOLUTION", 123)
    monkeypatch.setattr(server, "LATENT_TELEPORT_MAX_GIB_PER_RESOLUTION", 1.5)
    monkeypatch.setattr(server, "LATENT_TELEPORT_PRUNE_INTERVAL_SECONDS", 7.0)

    cache = server._get_latent_teleport_cache(640, 384)

    assert cache.resolution == (384, 640)
    assert captured == {
        "cache_dir": "/tmp/teleport",
        "resolution": (384, 640),
        "max_entries": 123,
        "max_bytes": int(1.5 * 1024**3),
        "prune_interval_s": 7.0,
    }


@pytest.mark.parametrize(
    "setting,value",
    [
        ("DTYPE_STR", "float16"),
        ("ZIMAGE_EARLY_EXIT", 0.25),
        ("ZIMAGE_EARLY_EXIT_MIN_STEPS", 6),
        ("ZIMAGE_EARLY_EXIT_CONSECUTIVE", 3),
        ("ZIMAGE_SKIP_NOOP_STEPS", False),
    ],
)
def test_latent_cache_key_changes_with_generation_runtime(monkeypatch, setting, value):
    monkeypatch.setattr(server, "ZIMAGE_LATENT_CACHE_VERSION", "v3")
    monkeypatch.setattr(server, "ZIMAGE_MODEL_PATH", "model-a")
    monkeypatch.setattr(server, "PRECISION", {"mode": "bf16"})
    monkeypatch.setattr(server, "ZIMAGE_USE_CUTE", False)
    monkeypatch.setattr(server, "_get_zimage_compile_mode", lambda: "default")

    before = server._latent_teleport_unit("prompt", 512, 512, 9, 42)
    monkeypatch.setattr(server, setting, value)
    after = server._latent_teleport_unit("prompt", 512, 512, 9, 42)

    assert before.unit_id != after.unit_id


def test_latent_cache_key_changes_when_compile_mode_downgrades(monkeypatch):
    compile_mode = "default"
    monkeypatch.setattr(server, "ZIMAGE_LATENT_CACHE_VERSION", "v3")
    monkeypatch.setattr(server, "_get_zimage_compile_mode", lambda: compile_mode)

    before = server._latent_teleport_unit("prompt", 512, 512, 9, 42)
    compile_mode = None
    after = server._latent_teleport_unit("prompt", 512, 512, 9, 42)

    assert before.unit_id != after.unit_id


def test_prompt_embedding_cache_reuses_conditioning_across_seeds(monkeypatch):
    class FakeTransformer:
        dtype = server.torch.bfloat16

    class FakePipe:
        transformer = FakeTransformer()

        def __init__(self):
            self.calls = 0

        def encode_prompt(self, **_kwargs):
            self.calls += 1
            return [server.torch.arange(8, dtype=server.torch.bfloat16).reshape(2, 4)], None

    pipe = FakePipe()
    monkeypatch.setattr(server, "DEVICE", "cpu")
    monkeypatch.setattr(server, "ZIMAGE_PROMPT_CACHE_SIZE", 2)
    server._clear_zimage_prompt_cache()
    first, first_meta = server._prepare_zimage_prompt_embeddings(
        pipe,
        {"prompt": "same prompt", "guidance_scale": 0.0, "seed": 1},
    )
    second, second_meta = server._prepare_zimage_prompt_embeddings(
        pipe,
        {"prompt": "same prompt", "guidance_scale": 0.0, "seed": 2},
    )

    assert pipe.calls == 1
    assert first_meta["hit"] is False
    assert second_meta["hit"] is True
    assert first["prompt"] is None
    assert second["prompt"] is None
    assert server.torch.equal(first["prompt_embeds"][0], second["prompt_embeds"][0])
    assert server._zimage_prompt_cache_snapshot()["hits"] == 1
    assert server._zimage_prompt_cache_snapshot()["misses"] == 1


def test_prompt_embedding_cache_encodes_without_autograd(monkeypatch):
    class FakeTransformer:
        dtype = server.torch.float32

    class FakePipe:
        transformer = FakeTransformer()

        def encode_prompt(self, **_kwargs):
            assert not server.torch.is_grad_enabled()
            source = server.torch.ones(2, 4, requires_grad=True)
            return [source * 2], None

    monkeypatch.setattr(server, "DEVICE", "cpu")
    monkeypatch.setattr(server, "ZIMAGE_PROMPT_CACHE_SIZE", 2)
    server._clear_zimage_prompt_cache()

    prepared, _meta = server._prepare_zimage_prompt_embeddings(
        FakePipe(),
        {"prompt": "graph-free prompt", "guidance_scale": 0.0},
    )

    assert not prepared["prompt_embeds"][0].requires_grad
    assert prepared["prompt_embeds"][0].grad_fn is None


def test_prompt_embedding_cache_is_lru_bounded(monkeypatch):
    class FakeTransformer:
        dtype = server.torch.float32

    class FakePipe:
        transformer = FakeTransformer()

        def encode_prompt(self, prompt, **_kwargs):
            return [server.torch.tensor([[len(prompt)]], dtype=server.torch.float32)], None

    monkeypatch.setattr(server, "DEVICE", "cpu")
    monkeypatch.setattr(server, "ZIMAGE_PROMPT_CACHE_SIZE", 2)
    server._clear_zimage_prompt_cache()
    for prompt in ("one", "two", "three"):
        server._prepare_zimage_prompt_embeddings(FakePipe(), {"prompt": prompt, "guidance_scale": 0.0})

    assert server._zimage_prompt_cache_snapshot()["entries"] == 2


def test_pipeline_stage_timing_observes_physical_steps():
    class Result:
        images = []

    class FakePipe:
        def __call__(self, callback_on_step_end=None, **_kwargs):
            for step in range(3):
                callback_on_step_end(self, step, step, {"latents": server.torch.ones(1)})
            return Result()

    timing = {}
    _result, captured = server._run_zimage_capture_multi(FakePipe(), {}, (1,), timing)

    assert set(captured) == {1}
    assert timing["physical_steps_observed"] == 3
    assert timing["pipeline_ms"] >= timing["denoise_through_last_step_ms"]
    assert timing["postprocess_after_last_step_ms"] >= 0


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


@pytest.mark.parametrize("prompt", ["", "   ", "\n\t"])
def test_zimage_request_rejects_blank_prompts(prompt):
    with pytest.raises(Exception) as exc_info:
        server.ZImageRequest(prompt=prompt)

    assert "prompt" in str(exc_info.value)
    assert "empty" in str(exc_info.value) or "at least 1 character" in str(exc_info.value)


def test_benchmark_mode_disables_quality_retry(monkeypatch):
    calls = []
    monkeypatch.setattr(
        server,
        "_generate_image_once_sync",
        lambda req: calls.append(req) or {"prompt_used": req.prompt},
    )

    result = server._generate_image_sync(
        server.ZImageRequest(prompt="  concise benchmark prompt  ", quality_retry=False, enhance_prompt=False)
    )

    assert len(calls) == 1
    assert result["prompt_used"] == "concise benchmark prompt"


@pytest.mark.parametrize("prompt", ["", "   ", "\n\t"])
def test_require_nonempty_prompt_returns_client_error(prompt):
    with pytest.raises(server.HTTPException) as exc_info:
        server._require_nonempty_prompt(prompt)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "prompt must not be empty"


def test_style_transfer_bad_image_url_fails_before_model_load(monkeypatch):
    class FailIfUsedModelManager:
        def is_loaded(self, _model_name):
            raise AssertionError("model manager should not be touched for invalid image_url")

        @contextlib.contextmanager
        def use(self, _model_name):
            raise AssertionError("model manager should not be touched for invalid image_url")
            yield

    monkeypatch.setattr(server, "model_manager", FailIfUsedModelManager())
    monkeypatch.setattr(
        server.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(server.socket.gaierror("no host")),
    )

    with pytest.raises(server.HTTPException) as exc_info:
        server._style_transfer_and_upload_with_model_sync("test", "https://x/y.jpg", "")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "image_url host could not be resolved"


def test_remote_image_url_rejects_private_addresses(monkeypatch):
    monkeypatch.setattr(
        server.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(server.socket.AF_INET, server.socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))],
    )

    with pytest.raises(server.HTTPException) as exc_info:
        server._validate_remote_image_url("http://localhost/image.png")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "image_url must resolve to a public address"


def test_load_remote_image_decodes_valid_image(monkeypatch):
    image = server.Image.new("RGB", (3, 2), (10, 20, 30))
    buf = server.io.BytesIO()
    image.save(buf, format="PNG")
    image_bytes = buf.getvalue()

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "image/png"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def iter_content(self, chunk_size):
            yield image_bytes[:chunk_size]
            yield image_bytes[chunk_size:]

    monkeypatch.setattr(
        server.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(server.socket.AF_INET, server.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )
    monkeypatch.setattr(server.requests, "get", lambda *_args, **_kwargs: FakeResponse())

    loaded = server._load_remote_image("https://example.com/image.png")

    assert loaded.mode == "RGB"
    assert loaded.size == (3, 2)


def test_request_prompt_info_prefers_remembered_body_prompt_over_query():
    request = _fake_request(query_string=b"prompt=")
    server._remember_request_prompt(request, "body prompt with words")

    info = server._request_prompt_info(request)

    assert info["prompt_len"] == len("body prompt with words")
    assert info["prompt_words"] == 4
    assert info["prompt_sha256"]


def test_sanitize_query_redacts_prompt_and_secret_but_keeps_inference_params():
    sanitized = server._sanitize_query(
        b"prompt=private+words&secret=hunter2&width=512&teleport=true&auto_lora=false&perf=true"
    )

    assert "private" not in sanitized
    assert "hunter2" not in sanitized
    assert "prompt=%3Credacted%3E" in sanitized
    assert "secret=%3Credacted%3E" in sanitized
    assert "width=512" in sanitized
    assert "teleport=true" in sanitized
    assert "auto_lora=false" in sanitized
    assert "perf=true" in sanitized


def test_error_event_includes_reproducible_inference_params(monkeypatch):
    request = _fake_request()
    request.state.request_id = "request-1"
    server._remember_request_prompt(request, "safe prompt")
    server._remember_request_inference_params(
        request,
        model="zimage-turbo",
        width=512,
        height=768,
        num_inference_steps=9,
        auto_lora=True,
        teleport=False,
        perf=True,
    )
    events = []
    monkeypatch.setattr(server, "_write_error_event", events.append)

    server._log_request_error(request, RuntimeError("failed"), 500)

    assert events[0]["inference"] == {
        "model": "zimage-turbo",
        "width": 512,
        "height": 768,
        "num_inference_steps": 9,
        "auto_lora": True,
        "teleport": False,
        "perf": True,
    }


def test_zimage_retry_recovers_from_cudagraph_assertion(monkeypatch):
    class FakeModelManager:
        def is_loaded(self, _model_name):
            return True

        @contextlib.contextmanager
        def use(self, _model_name):
            yield

    calls = []
    recoveries = []
    monkeypatch.setattr(server, "model_manager", FakeModelManager())
    monkeypatch.setattr(server, "zimage_pipeline", (object(), None))
    monkeypatch.setattr(server, "_cuda_free_mb", lambda: 12000)
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


@pytest.mark.parametrize(
    "message",
    [
        "CUDA error: unspecified launch failure",
        "CUDA error: an illegal memory access was encountered",
        "CUDA error: device-side assert triggered",
        "CUDA error: driver shutting down",
    ],
)
def test_fatal_cuda_errors_are_classified_as_process_poisoning(message):
    assert server._is_fatal_cuda_error(RuntimeError(message)) is True


def test_cuda_cleanup_never_masks_fatal_runtime_error(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "_cuda_runtime_fault", None)
    monkeypatch.setattr(server, "_cuda_runtime_fault_at", None)
    monkeypatch.setattr(server.torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(
        server.torch.cuda,
        "synchronize",
        lambda: (_ for _ in ()).throw(RuntimeError("CUDA error: unspecified launch failure")),
    )
    monkeypatch.setattr(server.torch.cuda, "empty_cache", lambda: calls.append("empty_cache"))

    server._clear_torch_cuda_caches()

    assert calls == []
    assert "unspecified launch failure" in server._cuda_runtime_fault


@pytest.mark.parametrize("prompt_len", [11, 49, 59, 63, 64, 83, 240, 4096])
def test_fatal_cuda_error_fails_fast_with_503_for_all_prompt_lengths(monkeypatch, prompt_len):
    class FakeModelManager:
        def __init__(self):
            self.use_calls = 0
            self.unloads = []

        def is_loaded(self, _model_name):
            return True

        @contextlib.contextmanager
        def use(self, _model_name):
            self.use_calls += 1
            yield

        def force_unload(self, model_name):
            self.unloads.append(model_name)
            return [model_name]

    manager = FakeModelManager()
    restarts = []
    prompt = "x" * prompt_len
    monkeypatch.setattr(server, "model_manager", manager)
    monkeypatch.setattr(server, "zimage_pipeline", (object(), None))
    monkeypatch.setattr(server, "_cuda_runtime_fault", None)
    monkeypatch.setattr(server, "_cuda_runtime_fault_at", None)
    monkeypatch.setattr(server, "_cuda_free_mb", lambda: 12000)
    monkeypatch.setattr(server, "_schedule_cuda_process_restart", lambda: restarts.append(True))

    with pytest.raises(server.HTTPException) as exc_info:
        server._with_zimage_model_retry(
            "generate_image",
            lambda: (_ for _ in ()).throw(
                RuntimeError(f"CUDA error: unspecified launch failure ({len(prompt)} chars)")
            ),
        )

    assert manager.use_calls == 1
    assert manager.unloads == ["zimage"]
    assert restarts == [True]
    assert exc_info.value.status_code == 503
    assert exc_info.value.headers == {"Retry-After": "30"}
    assert "process restart required" in exc_info.value.detail


def test_cuda_unavailable_preflight_returns_retryable_503(monkeypatch):
    restarts = []
    monkeypatch.setattr(server, "_cuda_unavailable_detail", lambda **_kwargs: "CUDA device is unavailable")
    monkeypatch.setattr(server, "ZIMAGE_REQUIRE_CUDA_READY", True)
    monkeypatch.setattr(server, "LOAD_ZIMAGE", True)
    monkeypatch.setattr(server, "DEVICE", "cuda")
    monkeypatch.setattr(server, "_schedule_cuda_process_restart", lambda: restarts.append(True))

    with pytest.raises(server.HTTPException) as exc_info:
        server._raise_if_zimage_cuda_unavailable()

    assert restarts == [True]
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "CUDA device is unavailable"
    assert exc_info.value.headers == {"Retry-After": "30"}


@pytest.mark.parametrize("prompt_len", [61, 99, 4096, 16384])
def test_cuda_unavailable_restarts_worker_for_all_prompt_lengths(monkeypatch, prompt_len):
    restarts = []
    monkeypatch.setattr(server, "_cuda_unavailable_detail", lambda **_kwargs: "CUDA device is unavailable")
    monkeypatch.setattr(server, "ZIMAGE_REQUIRE_CUDA_READY", True)
    monkeypatch.setattr(server, "LOAD_ZIMAGE", True)
    monkeypatch.setattr(server, "DEVICE", "cuda")
    monkeypatch.setattr(server, "_schedule_cuda_process_restart", lambda: restarts.append(prompt_len))

    with pytest.raises(server.HTTPException) as exc_info:
        server._with_zimage_model_retry(
            "generate_image",
            lambda: {"prompt": "x" * prompt_len},
        )

    assert exc_info.value.status_code == 503
    assert restarts == [prompt_len]


def test_cuda_required_worker_refuses_degraded_startup(monkeypatch):
    monkeypatch.setattr(server, "ZIMAGE_REQUIRE_CUDA_READY", True)
    monkeypatch.setattr(server, "LOAD_ZIMAGE", True)
    monkeypatch.setattr(server, "DEVICE", "cuda")

    with pytest.raises(RuntimeError, match="CUDA startup check failed"):
        server._require_zimage_cuda_at_startup("CUDA device is unavailable")


@pytest.mark.parametrize(
    "require_cuda,load_zimage,device",
    [(False, True, "cuda"), (True, False, "cuda"), (True, True, "cpu")],
)
def test_cuda_startup_requirement_can_be_intentionally_disabled(
    monkeypatch, require_cuda, load_zimage, device
):
    monkeypatch.setattr(server, "ZIMAGE_REQUIRE_CUDA_READY", require_cuda)
    monkeypatch.setattr(server, "LOAD_ZIMAGE", load_zimage)
    monkeypatch.setattr(server, "DEVICE", device)

    server._require_zimage_cuda_at_startup("CUDA device is unavailable")


def test_healthz_is_not_ready_when_cuda_is_unavailable(monkeypatch):
    restarts = []
    monkeypatch.setattr(server, "_cuda_runtime_fault_at", None)
    monkeypatch.setattr(server, "_cuda_unavailable_detail", lambda **_kwargs: "CUDA device is unavailable")
    monkeypatch.setattr(server, "ZIMAGE_REQUIRE_CUDA_READY", True)
    monkeypatch.setattr(server, "LOAD_ZIMAGE", True)
    monkeypatch.setattr(server, "DEVICE", "cuda")
    monkeypatch.setattr(server, "_schedule_cuda_process_restart", lambda: restarts.append(True))

    response = server.health(_fake_request(path="/healthz"))
    payload = server.json.loads(response.body)

    assert restarts == [True]
    assert response.status_code == 503
    assert response.headers["retry-after"] == "30"
    assert payload["status"] == "degraded"
    assert payload["cuda"]["healthy"] is False


def test_liveness_health_does_not_restart_cuda_worker(monkeypatch):
    restarts = []
    monkeypatch.setattr(server, "_cuda_runtime_fault_at", None)
    monkeypatch.setattr(server, "_cuda_unavailable_detail", lambda **_kwargs: "CUDA device is unavailable")
    monkeypatch.setattr(server, "ZIMAGE_REQUIRE_CUDA_READY", True)
    monkeypatch.setattr(server, "LOAD_ZIMAGE", True)
    monkeypatch.setattr(server, "DEVICE", "cuda")
    monkeypatch.setattr(server, "_schedule_cuda_process_restart", lambda: restarts.append(True))

    response = server.health(_fake_request(path="/health"))

    assert response.status_code == 200
    assert restarts == []


@pytest.mark.parametrize(
    "prompt",
    [
        "great snakesnake breadwinners",
        " ".join(["high quality coherent fantasy landscape with mountains and atmospheric light"] * 40),
    ],
)
def test_zimage_retry_rejects_cold_load_when_cuda_headroom_is_low(monkeypatch, prompt):
    class FakeModelManager:
        def __init__(self):
            self.unloads = []

        def is_loaded(self, _model_name):
            return False

        def force_unload(self, model_name):
            self.unloads.append(model_name)
            return []

        @contextlib.contextmanager
        def use(self, _model_name):
            raise AssertionError("model load should be skipped under memory pressure")
            yield

    manager = FakeModelManager()
    monkeypatch.setattr(server, "model_manager", manager)
    monkeypatch.setattr(server, "_cuda_free_mb", lambda: 512)
    monkeypatch.setattr(server, "ZIMAGE_LOAD_MIN_FREE_MB", 9216)

    with pytest.raises(server.HTTPException) as exc_info:
        server._with_zimage_model_retry("create_and_upload_image_teleport", lambda: {"prompt": prompt})

    assert exc_info.value.status_code == 503
    assert "needs at least 9216 MB free CUDA memory" in exc_info.value.detail
    assert exc_info.value.headers == {"Retry-After": "10"}
    assert manager.unloads == ["zimage"]


@pytest.mark.parametrize("prompt_len", [53, 66, 91, 97, 98, 104, 135, 136, 4096])
def test_zimage_retry_reclaims_stale_cuda_cache_before_cold_load(monkeypatch, prompt_len):
    class FakeModelManager:
        def __init__(self):
            self.unloads = []
            self.use_calls = 0

        def is_loaded(self, _model_name):
            return False

        def force_unload(self, model_name):
            self.unloads.append(model_name)
            return []

        @contextlib.contextmanager
        def use(self, _model_name):
            self.use_calls += 1
            yield

    manager = FakeModelManager()
    free_values = iter([51, 51, 12288, 12288])
    calls = []
    monkeypatch.setattr(server, "model_manager", manager)
    monkeypatch.setattr(server, "zimage_pipeline", (object(), None))
    monkeypatch.setattr(server, "_cuda_free_mb", lambda: next(free_values, 12288))
    monkeypatch.setattr(server, "ZIMAGE_LOAD_MIN_FREE_MB", 9216)

    result = server._with_zimage_model_retry(
        "generate_image",
        lambda: calls.append("x" * prompt_len) or {"ok": True},
    )

    assert result == {"ok": True}
    assert [len(prompt) for prompt in calls] == [prompt_len]
    assert manager.unloads == ["zimage"]
    assert manager.use_calls == 1


@pytest.mark.parametrize("prompt_len", [55, 93, 133, 171, 156, 194, 4096])
def test_zimage_retry_runs_loaded_pipeline_despite_low_global_cuda_headroom(monkeypatch, prompt_len):
    class FakeModelManager:
        def is_loaded(self, _model_name):
            return True

        @contextlib.contextmanager
        def use(self, _model_name):
            yield

    calls = []
    monkeypatch.setattr(server, "model_manager", FakeModelManager())
    monkeypatch.setattr(server, "zimage_pipeline", (object(), None))
    monkeypatch.setattr(server, "_cuda_free_mb", lambda: 128)

    result = server._with_zimage_model_retry(
        "generate_image",
        lambda: calls.append("x" * prompt_len) or {"ok": True},
    )

    assert result == {"ok": True}
    assert [len(prompt) for prompt in calls] == [prompt_len]


def test_zimage_oom_recovery_waits_for_headroom_before_retry(monkeypatch):
    class FakeModelManager:
        def is_loaded(self, _model_name):
            return False

        @contextlib.contextmanager
        def use(self, _model_name):
            yield

    class FakeCudaOOM(RuntimeError):
        pass

    calls = []
    recoveries = []
    monkeypatch.setattr(server, "model_manager", FakeModelManager())
    monkeypatch.setattr(server, "zimage_pipeline", (object(), None))
    monkeypatch.setattr(server, "_cuda_free_mb", lambda: 12000)
    monkeypatch.setattr(server, "_is_cuda_oom", lambda exc: isinstance(exc, FakeCudaOOM))
    monkeypatch.setattr(server, "_recover_from_cuda_oom", lambda: recoveries.append(True))
    monkeypatch.setattr(server, "_wait_for_zimage_memory_headroom", lambda *_args: True)

    def fn():
        calls.append(True)
        if len(calls) == 1:
            raise FakeCudaOOM("CUDA out of memory")
        return {"ok": True}

    assert server._with_zimage_model_retry("create_and_upload_image_teleport", fn) == {"ok": True}
    assert len(calls) == 2
    assert recoveries == [True]


def test_zimage_oom_recovery_detaches_tensor_holding_traceback_before_cleanup(monkeypatch):
    class FakeModelManager:
        def is_loaded(self, _model_name):
            return True

        @contextlib.contextmanager
        def use(self, _model_name):
            yield

    class FakeCudaOOM(RuntimeError):
        pass

    error = FakeCudaOOM("CUDA out of memory")
    cleanup_tracebacks = []
    calls = []
    monkeypatch.setattr(server, "model_manager", FakeModelManager())
    monkeypatch.setattr(server, "zimage_pipeline", (object(), None))
    monkeypatch.setattr(server, "_is_cuda_oom", lambda exc: isinstance(exc, FakeCudaOOM))
    monkeypatch.setattr(
        server,
        "_recover_from_cuda_oom",
        lambda: cleanup_tracebacks.append(error.__traceback__),
    )
    monkeypatch.setattr(server, "_wait_for_zimage_memory_headroom", lambda *_args: True)

    def fn():
        calls.append(True)
        if len(calls) == 1:
            raise error
        return {"ok": True}

    assert server._with_zimage_model_retry("generate_image", fn) == {"ok": True}
    assert cleanup_tracebacks == [None]


def test_zimage_oom_recovery_stops_when_headroom_never_returns(monkeypatch):
    class FakeModelManager:
        def is_loaded(self, _model_name):
            return False

        @contextlib.contextmanager
        def use(self, _model_name):
            yield

    class FakeCudaOOM(RuntimeError):
        pass

    calls = []
    monkeypatch.setattr(server, "model_manager", FakeModelManager())
    monkeypatch.setattr(server, "zimage_pipeline", (object(), None))
    free_values = [12000, 512]
    monkeypatch.setattr(server, "_cuda_free_mb", lambda: free_values.pop(0) if free_values else 512)
    monkeypatch.setattr(server, "_is_cuda_oom", lambda exc: isinstance(exc, FakeCudaOOM))
    monkeypatch.setattr(server, "_recover_from_cuda_oom", lambda: None)
    monkeypatch.setattr(server, "_wait_for_zimage_memory_headroom", lambda *_args: False)
    monkeypatch.setattr(server, "ZIMAGE_LOAD_MIN_FREE_MB", 9216)

    def fn():
        calls.append(True)
        raise FakeCudaOOM("CUDA out of memory")

    with pytest.raises(server.HTTPException) as exc_info:
        server._with_zimage_model_retry("create_and_upload_image_teleport", fn)

    assert len(calls) == 1
    assert exc_info.value.status_code == 503
    assert "failed after CUDA OOM recovery" in exc_info.value.detail
    assert "only 512 MB is free" in exc_info.value.detail


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


def test_force_unload_clears_partial_zimage_state_after_failed_load(monkeypatch):
    clear_calls = []
    fake_pipeline = types.ModuleType("cutezimage.pipeline")
    fake_pipeline.clear_pipeline_caches = lambda: clear_calls.append(True)
    fake_package = types.ModuleType("cutezimage")
    fake_package.__path__ = []

    monkeypatch.setitem(sys.modules, "cutezimage", fake_package)
    monkeypatch.setitem(sys.modules, "cutezimage.pipeline", fake_pipeline)
    monkeypatch.setattr(server, "_clear_torch_cuda_caches", lambda: None)
    monkeypatch.setattr(server, "zimage_pipeline", (object(), None))

    manager = server.ModelManager()

    assert manager.force_unload("zimage") == []
    assert server.zimage_pipeline is None
    assert clear_calls == [True]


def test_failed_zimage_load_clears_partial_state(monkeypatch):
    clear_calls = []
    cache_clears = []

    fake_pipeline = types.ModuleType("cutezimage.pipeline")
    fake_pipeline.clear_pipeline_caches = lambda: clear_calls.append(True)
    fake_package = types.ModuleType("cutezimage")
    fake_package.__path__ = []

    monkeypatch.setitem(sys.modules, "cutezimage", fake_package)
    monkeypatch.setitem(sys.modules, "cutezimage.pipeline", fake_pipeline)
    monkeypatch.setattr(server, "_clear_torch_cuda_caches", lambda: cache_clears.append(True))
    monkeypatch.setattr(server, "_load_zimage", lambda: (_ for _ in ()).throw(RuntimeError("load failed")))
    monkeypatch.setattr(server, "_init_lora_engine", lambda: None)
    monkeypatch.setattr(server, "zimage_pipeline", (object(), None))

    manager = server.ModelManager()

    with pytest.raises(RuntimeError, match="load failed"):
        manager.ensure_loaded("zimage")

    assert not manager.is_loaded("zimage")
    assert server.zimage_pipeline is None
    assert clear_calls == [True]
    assert cache_clears == [True]


def test_resolve_lora_skips_prompt_mutation_when_nvfp4_enabled(monkeypatch):
    req = server.ZImageRequest(prompt="cute robot", auto_lora=True, lora_id="some-lora")

    monkeypatch.setattr(server, "ENABLE_NVFP4", True)
    monkeypatch.setattr(server, "lora_engine", object())

    lora, final_prompt = server._resolve_lora(req)

    assert lora is None
    assert final_prompt == "cute robot"


def test_pipeline_generator_matches_cpu_execution_device():
    class FakePipe:
        _execution_device = "cpu"

    generator = server._make_pipeline_generator(FakePipe(), 123)

    assert str(generator.device) == "cpu"
    assert generator.initial_seed() == 123


def test_cpu_offload_excludes_pinned_text_encoder_from_cuda_hooks(monkeypatch):
    class FakeEncoder:
        def __init__(self):
            self.moves = []

        def to(self, device, **kwargs):
            self.moves.append((device, kwargs))
            return self

    class FakePipe:
        def __init__(self):
            self.text_encoder = FakeEncoder()
            self.encoder_seen_during_offload = object()

        def enable_model_cpu_offload(self):
            self.encoder_seen_during_offload = self.text_encoder

    pipe = FakePipe()
    encoder = pipe.text_encoder

    server._enable_zimage_model_cpu_offload(pipe, keep_text_encoder_cpu=True)

    assert pipe.encoder_seen_during_offload is None
    assert pipe.text_encoder is encoder
    assert encoder.moves == [("cpu", {"dtype": server.torch.float32})]


def test_auto_offload_accounts_for_quantized_text_encoder_headroom(monkeypatch):
    monkeypatch.setenv("ZIMAGE_CPU_OFFLOAD", "auto")
    monkeypatch.setattr(server, "ZIMAGE_NO_OFFLOAD_MIN_FREE_MB", 24576)
    monkeypatch.setattr(server, "_cuda_free_mb", lambda: 19200)

    monkeypatch.setattr(server, "ZIMAGE_TEXT_ENCODER_QUANT", "")
    assert server._resolve_zimage_cpu_offload() is True

    monkeypatch.setattr(server, "ZIMAGE_TEXT_ENCODER_QUANT", "nvfp4")
    assert server._resolve_zimage_cpu_offload() is False


def test_load_zimage_rechecks_auto_offload_after_slow_cpu_checkpoint_load(monkeypatch):
    class FakeComponent:
        def __init__(self):
            self.moves = []

        def to(self, *_args, **_kwargs):
            self.moves.append((_args, _kwargs))
            if _args and str(_args[0]).startswith("cuda"):
                raise AssertionError("components must not move directly to CUDA after headroom drops")
            return self

    class FakeScheduler:
        _step_index = None
        sigmas = [1]

        def step(self, *_args, **_kwargs):
            return None

    class FakeZImagePipeline:
        hf_device_map = None

        def __init__(self):
            self.transformer = FakeComponent()
            self.vae = FakeComponent()
            self.text_encoder = FakeComponent()
            self.scheduler = FakeScheduler()
            self.components = {}
            self.offload_calls = 0

        @classmethod
        def from_pretrained(cls, *_args, **_kwargs):
            return cls()

        def enable_model_cpu_offload(self):
            self.offload_calls += 1

    class FakeImg2ImgPipeline:
        def __init__(self, **_kwargs):
            pass

    try:
        import diffusers
    except Exception as exc:  # pragma: no cover - test environment dependency
        pytest.skip(f"diffusers unavailable: {exc}")

    decisions = iter([False, True])
    monkeypatch.setattr(diffusers, "ZImagePipeline", FakeZImagePipeline)
    monkeypatch.setattr(diffusers, "ZImageImg2ImgPipeline", FakeImg2ImgPipeline)
    monkeypatch.setattr(server, "ENABLE_NVFP4", False)
    monkeypatch.setattr(server, "PRECISION", {"mode": "bf16"})
    monkeypatch.setattr(server, "ZIMAGE_USE_CUTE", False)
    monkeypatch.setattr(server, "ZIMAGE_DIRECT_DEVICE_MAP", False)
    monkeypatch.setattr(server, "ZIMAGE_TEXT_ENCODER_DEVICE", None)
    monkeypatch.setattr(server, "AITUNE_ENGINES_PATH", "")
    monkeypatch.setattr(server, "_resolve_zimage_cpu_offload", lambda: next(decisions))
    monkeypatch.setenv("ZIMAGE_SKIP_WARMUP", "1")
    monkeypatch.setattr(server, "zimage_pipeline", None)

    server._load_zimage()

    pipe, _img2img = server.zimage_pipeline
    assert pipe.offload_calls == 1
    assert server._zimage_effective_cpu_offload is True
    assert server._zimage_load_strategy == "cpu-model-offload-after-load"


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
    monkeypatch.setattr(server, "PRECISION", {"mode": "bf16"})
    monkeypatch.setattr(server, "ZIMAGE_USE_CUTE", False)
    monkeypatch.setattr(server, "AITUNE_ENGINES_PATH", "")
    monkeypatch.setattr(server, "_resolve_zimage_cpu_offload", lambda: False)
    monkeypatch.setenv("ZIMAGE_SKIP_WARMUP", "1")
    monkeypatch.setattr(server, "zimage_pipeline", None)

    server._load_zimage()

    text2img_pipe, _img2img_pipe = server.zimage_pipeline
    assert text2img_pipe.offload_enabled
    assert server._zimage_load_strategy == "cpu-model-offload-fallback"


def test_no_offload_requests_direct_device_map(monkeypatch):
    observed = []

    class FakeScheduler:
        def step(self):
            return None

    class FakePipeline:
        hf_device_map = {"": "cuda"}

        def __init__(self):
            self.transformer = types.SimpleNamespace()
            self.vae = types.SimpleNamespace()
            self.text_encoder = types.SimpleNamespace()
            self.scheduler = FakeScheduler()
            self.components = {
                "transformer": self.transformer,
                "vae": self.vae,
                "text_encoder": self.text_encoder,
                "scheduler": self.scheduler,
            }

        @classmethod
        def from_pretrained(cls, *_args, **kwargs):
            observed.append(kwargs)
            return cls()

    class FakeImg2Img:
        def __init__(self, **_components):
            pass

    import diffusers

    monkeypatch.setattr(diffusers, "ZImagePipeline", FakePipeline)
    monkeypatch.setattr(diffusers, "ZImageImg2ImgPipeline", FakeImg2Img)
    monkeypatch.setattr(server, "PRECISION", {"mode": "bf16"})
    monkeypatch.setattr(server, "ENABLE_NVFP4", False)
    monkeypatch.setattr(server, "ZIMAGE_USE_CUTE", False)
    monkeypatch.setattr(server, "AITUNE_ENGINES_PATH", "")
    monkeypatch.setattr(server, "_resolve_zimage_cpu_offload", lambda: False)
    monkeypatch.setenv("ZIMAGE_SKIP_WARMUP", "1")

    server._load_zimage()

    assert observed[0]["device_map"] == server.DEVICE
    assert server._zimage_load_strategy == "direct-device-map"
def test_auto_offload_threshold_cannot_drop_below_full_cuda_safety_floor():
    assert server.ZIMAGE_NO_OFFLOAD_MIN_FREE_MB >= 24576
