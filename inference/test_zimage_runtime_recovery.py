import contextlib
import asyncio
import base64
import io
import sys
import types
from pathlib import Path

import pytest
from PIL import Image
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


def _native_image_document(width=512, height=512, **row_overrides):
    output = io.BytesIO()
    Image.new("RGB", (width, height), (36, 72, 108)).save(output, format="WEBP")
    row = {
        "b64_json": base64.b64encode(output.getvalue()).decode(),
        "format": "webp",
        "inference_time_ms": 123,
    }
    row.update(row_overrides)
    return {"model": "z_image_turbo-Q4_K", "data": [row]}


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


def test_active_peer_hold_routes_cold_generate_request_to_native_fallback(monkeypatch):
    manager = server.ModelManager()
    manager.hold(3600)
    native_calls = []

    class FakeBatcher:
        async def submit(self, req):
            return server._generate_image_batch_with_model_sync([req])[0]

    monkeypatch.setattr(server, "model_manager", manager)
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_URL", "http://native")
    monkeypatch.setattr(server, "zimage_dynamic_batcher", FakeBatcher())
    monkeypatch.setattr(
        server,
        "_generate_image_native_sync",
        lambda req: native_calls.append(req.prompt) or {"backend": "omniserve-native"},
    )
    monkeypatch.setattr(
        server,
        "_with_zimage_model_retry",
        lambda *_args: pytest.fail("an active peer hold must not enter the local BF16 loader"),
    )

    result = server.asyncio.run(
        server._submit_zimage_request(server.ZImageRequest(prompt="held fallback request"))
    )

    assert result == {"backend": "omniserve-native"}
    assert native_calls == ["held fallback request"]
    assert manager._admitted == {}
    assert manager.hold_remaining() > 0


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


@pytest.mark.parametrize(
    "prompt",
    [
        "gallery prompt with an embedded NUL\x00and trailing bytes",
        "gallery prompt with a binary control\x01byte",
        "gallery prompt with DEL\x7fbyte",
    ],
)
def test_zimage_request_rejects_controls_that_are_unsafe_for_native_c_strings(prompt):
    with pytest.raises(Exception) as exc_info:
        server.ZImageRequest(prompt=prompt)

    assert "unsupported control characters" in str(exc_info.value)


def test_zimage_request_allows_multiline_prompt_whitespace():
    prompt = "first line\nsecond line\twith detail\r\n"

    assert server.ZImageRequest(prompt=prompt).prompt == prompt


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


@pytest.mark.parametrize("host", ["0177.0.0.1", "127.000.000.001"])
def test_remote_image_url_rejects_noncanonical_ipv4_before_dns(monkeypatch, host):
    monkeypatch.setattr(
        server.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: pytest.fail("invalid numeric host must not reach DNS"),
    )

    with pytest.raises(server.HTTPException) as exc_info:
        server._validate_remote_image_url(f"http://{host}/image.png")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "image_url has an invalid IPv4 address"


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


def test_load_remote_image_rejects_non_image_payload(monkeypatch):
    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/html"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        server.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(server.socket.AF_INET, server.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )
    monkeypatch.setattr(server.requests, "get", lambda *_args, **_kwargs: FakeResponse())

    with pytest.raises(server.HTTPException) as exc_info:
        server._load_remote_image("https://example.com/not-an-image")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "image_url did not return an image"


def test_load_remote_image_revalidates_redirect_target(monkeypatch):
    class FakeRedirect:
        status_code = 302
        headers = {"location": "http://127.0.0.1/private.png"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        server.socket,
        "getaddrinfo",
        lambda host, *_args, **_kwargs: [
            (server.socket.AF_INET, server.socket.SOCK_STREAM, 6, "", (
                "93.184.216.34" if host == "example.com" else "127.0.0.1", 0
            ))
        ],
    )
    monkeypatch.setattr(server.requests, "get", lambda *_args, **_kwargs: FakeRedirect())

    with pytest.raises(server.HTTPException) as exc_info:
        server._load_remote_image("https://example.com/image.png")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "image_url must resolve to a public address"


def test_nsfw_route_turns_malformed_numeric_url_into_client_error(monkeypatch):
    monkeypatch.setattr(
        server.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: pytest.fail("invalid numeric host must not reach DNS"),
    )

    with pytest.raises(server.HTTPException) as exc_info:
        asyncio.run(server.nsfw_detect(server.NSFWRequest(image_url="http://0177.0.0.1/x")))

    assert exc_info.value.status_code == 400


def test_nsfw_classifier_uses_dedicated_cpu_device_under_cuda_pressure(monkeypatch):
    calls = []

    class FakeClassifier:
        model = object()

    monkeypatch.setattr(server, "nsfw_classifier", None)
    monkeypatch.setattr(server, "nsfw_lock", None)
    monkeypatch.setattr(server, "NSFW_DEVICE", "cpu")
    monkeypatch.setattr(server.torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(server.torch, "compile", lambda model, **_kwargs: model)
    monkeypatch.setitem(
        sys.modules,
        "transformers",
        types.SimpleNamespace(
            pipeline=lambda task, **kwargs: (
                calls.append((task, kwargs)) or FakeClassifier()
            )
        ),
    )

    classifier = server._load_nsfw_classifier()

    assert isinstance(classifier, FakeClassifier)
    assert calls == [("image-classification", {
        "model": "Falconsai/nsfw_image_detection",
        "device": "cpu",
    })]
    server._unload_nsfw_classifier()


def test_caption_route_rejects_malformed_numeric_url_before_backend(monkeypatch):
    monkeypatch.setattr(
        server.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: pytest.fail("invalid numeric host must not reach DNS"),
    )

    class FailIfCalledClient:
        async def post(self, *_args, **_kwargs):
            pytest.fail("invalid image_url must not reach the caption backend")

    monkeypatch.setattr(server, "tg_client", FailIfCalledClient())

    with pytest.raises(server.HTTPException) as exc_info:
        asyncio.run(
            server.caption_image(
                server.CaptionRequest(image_url="http://127.000.000.001/x")
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "image_url has an invalid IPv4 address"


@pytest.mark.parametrize("route, request_type", [
    (server.nsfw_detect, server.NSFWRequest),
    (server.aesthetic_score, server.AestheticRequest),
])
def test_image_analysis_routes_require_configured_secret(monkeypatch, route, request_type):
    monkeypatch.setattr(server, "IMAGE_API_SECRETS", {"expected"})

    with pytest.raises(server.HTTPException) as exc_info:
        asyncio.run(route(request_type(image_base64="unused"), secret="wrong"))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "invalid secret"


@pytest.mark.parametrize("route, request_type", [
    (server.nsfw_detect, server.NSFWRequest),
    (server.aesthetic_score, server.AestheticRequest),
])
def test_image_analysis_routes_reject_invalid_base64_images(route, request_type):
    invalid_image = base64.b64encode(b"not an image").decode()

    with pytest.raises(server.HTTPException) as exc_info:
        asyncio.run(route(request_type(image_base64=invalid_image)))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "image_base64 did not contain a valid image"


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


@pytest.mark.parametrize("save_path", [
    "../static/_next/chunk.js",
    "../../static/_next/chunk.js",
    "x/../..//_next/chunk.js",
    "folder\\..\\chunk.js",
    "folder/\x00chunk.webp",
])
def test_save_path_rejects_traversal_and_control_input(save_path):
    with pytest.raises(server.HTTPException) as exc_info:
        server._validated_save_path(save_path)

    assert exc_info.value.status_code == 400


def test_save_path_preserves_normal_relative_object_path():
    assert server._validated_save_path("reliability/a friendly image.webp") == (
        "reliability/a+friendly+image.webp"
    )


@pytest.mark.parametrize("prompt_len", [9, 4096])
def test_create_and_upload_rejects_traversal_before_generation(prompt_len, monkeypatch):
    monkeypatch.setattr(
        server,
        "check_if_blob_exists",
        lambda _path: pytest.fail("invalid save_path must fail before storage access"),
    )
    monkeypatch.setattr(
        server.model_manager,
        "reserve",
        lambda _model: pytest.fail("invalid save_path must fail before GPU admission"),
    )

    with pytest.raises(server.HTTPException) as exc_info:
        asyncio.run(server.create_and_upload_image(
            request=_fake_request(path="/create_and_upload_image"),
            prompt="x" * prompt_len,
            save_path="../static/_next/chunk.js",
        ))

    assert exc_info.value.status_code == 400
    assert "without traversal" in exc_info.value.detail


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


@pytest.mark.parametrize("prompt_len", [17, 44, 159, 165, 1024, 4096])
def test_cold_image_batch_uses_native_fallback_under_memory_pressure(monkeypatch, prompt_len):
    class FakeModelManager:
        def is_loaded(self, _model_name):
            return False

    requests = [server.ZImageRequest(prompt="x" * prompt_len, quality_retry=False)]
    calls = []
    monkeypatch.setattr(server, "model_manager", FakeModelManager())
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_URL", "http://native")
    monkeypatch.setattr(server, "ZIMAGE_LOAD_MIN_FREE_MB", 9216)
    monkeypatch.setattr(server, "_cuda_free_mb", lambda: 512)
    monkeypatch.setattr(
        server,
        "_generate_image_native_sync",
        lambda req: calls.append(req.prompt) or {"backend": "omniserve-native"},
    )
    monkeypatch.setattr(
        server,
        "_with_zimage_model_retry",
        lambda *_args: pytest.fail("low-headroom cold load must not enter the BF16 loader"),
    )

    assert server._generate_image_batch_with_model_sync(requests) == [
        {"backend": "omniserve-native"}
    ]
    assert [len(prompt) for prompt in calls] == [prompt_len]


def test_warm_image_batch_keeps_local_pipeline_despite_low_global_memory(monkeypatch):
    class FakeModelManager:
        def is_loaded(self, _model_name):
            return True

    req = server.ZImageRequest(prompt="warm model", quality_retry=False)
    monkeypatch.setattr(server, "model_manager", FakeModelManager())
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_URL", "http://native")
    monkeypatch.setattr(server, "_cuda_free_mb", lambda: 128)
    monkeypatch.setattr(
        server,
        "_generate_image_native_sync",
        lambda _req: pytest.fail("a warm local pipeline must not be rerouted"),
    )
    monkeypatch.setattr(
        server,
        "_with_zimage_model_retry",
        lambda operation, fn: {"operation": operation},
    )

    assert server._generate_image_batch_with_model_sync([req]) == {
        "operation": "generate_image_batch"
    }


def test_native_failure_uses_local_cold_loader_only_with_explicit_opt_in(monkeypatch):
    class FakeModelManager:
        def is_loaded(self, _model_name):
            return False

    req = server.ZImageRequest(prompt="native unavailable", quality_retry=False)
    monkeypatch.setattr(server, "model_manager", FakeModelManager())
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_URL", "http://native")
    monkeypatch.setattr(server, "ZIMAGE_LOCAL_COLD_FALLBACK_ENABLED", True)
    monkeypatch.setattr(server, "_cuda_free_mb", lambda: 12288)
    monkeypatch.setattr(
        server,
        "_generate_image_native_sync",
        lambda _req: (_ for _ in ()).throw(server.HTTPException(503, "native down")),
    )
    monkeypatch.setattr(
        server,
        "_with_zimage_model_retry",
        lambda operation, _fn: [{"operation": operation, "backend": "local"}],
    )

    assert server._generate_image_batch_with_model_sync([req]) == [
        {"operation": "generate_image_batch", "backend": "local"}
    ]


def test_native_admission_timeout_does_not_start_local_cold_loader(monkeypatch):
    class FakeModelManager:
        def is_loaded(self, _model_name):
            return False

    req = server.ZImageRequest(prompt="native capacity timeout", quality_retry=False)
    native_error = server.HTTPException(503, "native fallback returned HTTP 503: admission timeout; retry")
    monkeypatch.setattr(server, "model_manager", FakeModelManager())
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_URL", "http://native")
    monkeypatch.setattr(server, "ZIMAGE_LOCAL_COLD_FALLBACK_ENABLED", False)
    monkeypatch.setattr(
        server,
        "_generate_image_native_sync",
        lambda _req: (_ for _ in ()).throw(native_error),
    )
    monkeypatch.setattr(
        server,
        "_with_zimage_model_retry",
        lambda *_args: pytest.fail("native capacity failure must not start the BF16 loader"),
    )

    with pytest.raises(server.HTTPException) as exc_info:
        server._generate_image_batch_with_model_sync([req])

    assert exc_info.value is native_error


def test_native_fallback_retries_transient_lazy_init_and_validates_image(monkeypatch):
    class FakeResponse:
        def __init__(self, status_code, document):
            self.status_code = status_code
            self._document = document

        def json(self):
            return self._document

    responses = iter([
        FakeResponse(500, {"error": {"message": "image generation failed"}}),
        FakeResponse(200, _native_image_document()),
    ])
    calls = []
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_URL", "http://native")
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_RETRIES", 1)
    monkeypatch.setattr(server, "IMAGE_API_SECRET", "test-secret")
    monkeypatch.setattr(server.time, "sleep", lambda _seconds: None)
    cleanup_calls = []
    monkeypatch.setattr(server, "_clear_torch_cuda_caches", lambda: cleanup_calls.append(True))
    monkeypatch.setattr(server, "_cuda_free_mb", lambda: 2048 + 1024 * len(cleanup_calls))

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return next(responses)

    monkeypatch.setattr(server.requests, "post", post)
    payload = {
        "prompt": "test",
        "width": 512,
        "height": 512,
        "steps": 8,
        "seed": 7,
    }

    result = server._call_native_zimage(payload)

    assert result["width"] == 512
    assert result["height"] == 512
    assert result["format"] == "webp"
    assert result["inference_time_ms"] == 123
    assert len(calls) == 2
    assert calls[0][0] == "http://native/v1/images/generations"
    assert calls[0][1]["json"] == payload
    assert calls[0][1]["headers"]["Authorization"] == "Bearer test-secret"
    assert calls[0][1]["headers"]["X-Omniserve-Tier"] == "paid"
    assert cleanup_calls == [True]


@pytest.mark.parametrize("prompt_len", [1, 147, 1024, 4096])
def test_native_fallback_waits_for_route_readiness_404(monkeypatch, prompt_len):
    """A native listener can return generic 404 while its image route starts."""
    responses = iter([
        types.SimpleNamespace(
            status_code=404,
            json=lambda: {"error": {"message": "not found"}},
        ),
        types.SimpleNamespace(
            status_code=200,
            json=lambda: _native_image_document(width=512, height=512),
        ),
    ])
    sleeps = []
    clock = iter([10.0])
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_URL", "http://native")
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_RESTART_GRACE_SECONDS", 30.0)
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_RESTART_POLL_SECONDS", 2.0)
    monkeypatch.setattr(server.time, "monotonic", lambda: next(clock, 10.0))
    monkeypatch.setattr(server.time, "sleep", sleeps.append)
    monkeypatch.setattr(server.requests, "post", lambda *_args, **_kwargs: next(responses))

    result = server._call_native_zimage({
        "prompt": "x" * prompt_len,
        "width": 512,
        "height": 512,
    })

    assert result["backend"] == "omniserve-native"
    assert sleeps == [2.0]


def test_native_fallback_does_not_retry_unrelated_404(monkeypatch):
    response = types.SimpleNamespace(
        status_code=404,
        json=lambda: {"error": {"message": "unknown model"}},
    )
    calls = []
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_URL", "http://native")
    monkeypatch.setattr(server.requests, "post", lambda *_args, **_kwargs: calls.append(True) or response)

    with pytest.raises(server.HTTPException) as exc_info:
        server._call_native_zimage({"prompt": "test", "width": 512, "height": 512})

    assert exc_info.value.status_code == 502
    assert len(calls) == 1


@pytest.mark.parametrize("prompt_len", [13, 80, 1024, 4096])
@pytest.mark.parametrize("body", ["error code: 502\n", "<html>private upstream body</html>"])
def test_native_gateway_failure_keeps_safe_diagnostic_and_request(monkeypatch, prompt_len, body):
    def invalid_json():
        raise ValueError("not JSON")

    response = types.SimpleNamespace(status_code=502, text=body, json=invalid_json)
    calls = []
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_URL", "http://native")
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_RETRIES", 1)
    monkeypatch.setattr(server, "_clear_torch_cuda_caches", lambda: None)
    monkeypatch.setattr(server, "_cuda_free_mb", lambda: 19000)
    monkeypatch.setattr(server.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(server.requests, "post", lambda _url, **kw: calls.append(kw) or response)
    payload = dict(prompt="x" * prompt_len, width=1024, height=1024, steps=8,
                   seed=42, teleport=False, _omniserve_tier="background")
    with pytest.raises(server.HTTPException) as exc_info:
        server._call_native_zimage(payload)

    assert exc_info.value.status_code == 503
    assert exc_info.value.headers == {"Retry-After": "5"}
    assert ("upstream gateway unavailable" in exc_info.value.detail) == body.startswith("error code:")
    assert "private upstream body" not in exc_info.value.detail
    assert len(calls) == 2
    for call in calls:
        assert call["json"] == {k: v for k, v in payload.items() if k != "_omniserve_tier"}
        assert call["headers"]["X-Omniserve-Tier"] == "background"


def test_native_fallback_preserves_bounded_backend_error_detail(monkeypatch):
    class FakeResponse:
        status_code = 500

        @staticmethod
        def json():
            return {"error": {"message": "  VAE   decode failed " + "x" * 400}}

    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_URL", "http://native")
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_RETRIES", 0)
    monkeypatch.setattr(server.requests, "post", lambda *_args, **_kwargs: FakeResponse())

    with pytest.raises(server.HTTPException) as exc_info:
        server._call_native_zimage({"width": 1024, "height": 1024})

    detail = exc_info.value.detail
    assert detail.startswith("native fallback returned HTTP 500: VAE decode failed ")
    assert len(detail) <= len("native fallback returned HTTP 500: ") + 240


@pytest.mark.parametrize("prompt_len", [13, 80, 1024, 4096])
@pytest.mark.parametrize("warm", [False, True])
@pytest.mark.parametrize("tier", ["paid", "background"])
def test_native_capacity_reclaims_cold_cache_before_waiting(monkeypatch, prompt_len, warm, tier):
    events = []
    calls = []
    payload = {
        "prompt": "x" * prompt_len, "width": 1152, "height": 832,
        "steps": 9, "seed": 42, "teleport": True,
        "lora_id": "pixel_art", "lora_scale": 0.75, "_omniserve_tier": tier,
    }
    document = _native_image_document(width=1152, height=832)

    def post(_url, **kwargs):
        events.append("request")
        calls.append(kwargs["json"].copy())
        if len(calls) <= 2:
            return types.SimpleNamespace(status_code=503, json=lambda: {"error": {"message":
                "image generation needs at least 4096 MB free GPU memory; managed GPU capacity is busy"}})
        return types.SimpleNamespace(status_code=200, json=lambda: document)

    monkeypatch.setattr(server.requests, "post", post)
    monkeypatch.setattr(server.model_manager, "is_loaded", lambda _name: warm)
    monkeypatch.setattr(server, "_clear_torch_cuda_caches", lambda: events.append("cleanup"))
    monkeypatch.setattr(server.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(server.time, "sleep", lambda _seconds: events.append("sleep"))
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_RETRIES", 0)
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_HEADROOM_GRACE_SECONDS", 5.0)
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_BACKGROUND_HEADROOM_GRACE_SECONDS", 5.0)

    result = server._call_native_zimage(payload)

    expected_events = ["request"] + ([] if warm else ["cleanup"])
    assert events == expected_events + ["sleep", "request", "sleep", "request"]
    assert calls == [{k: v for k, v in payload.items() if k != "_omniserve_tier"}] * 3
    assert result["image_bytes"] == base64.b64decode(document["data"][0]["b64_json"])


def test_native_fallback_waits_for_managed_gpu_headroom(monkeypatch):
    class FakeResponse:
        def __init__(self, status_code, document):
            self.status_code = status_code
            self._document = document

        def json(self):
            return self._document

    responses = iter([
        FakeResponse(503, {"error": {"message": (
            "image generation needs at least 4096 MB free GPU memory; "
            "only 1209 MB is free"
        )}}),
        FakeResponse(503, {"error": {"message": (
            "image generation needs at least 4096 MB free GPU memory; "
            "only 2061 MB is free"
        )}}),
        FakeResponse(200, _native_image_document(width=1024, height=1024)),
    ])
    clock = iter([10.0, 12.0])
    sleeps = []
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_URL", "http://native")
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_RETRIES", 0)
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_HEADROOM_GRACE_SECONDS", 30.0)
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_HEADROOM_POLL_SECONDS", 2.0)
    monkeypatch.setattr(server.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(server.time, "sleep", sleeps.append)
    monkeypatch.setattr(
        server.requests,
        "post",
        lambda *_args, **_kwargs: next(responses),
    )

    result = server._call_native_zimage({
        "prompt": "capacity recovery probe",
        "width": 1024,
        "height": 1024,
    })

    assert result["backend"] == "omniserve-native"
    assert sleeps == [2.0, 2.0]


@pytest.mark.parametrize("prompt_len", [11, 186, 194, 4096])
def test_background_native_capacity_is_retryable_backpressure(monkeypatch, prompt_len):
    class FakeResponse:
        status_code = 503

        @staticmethod
        def json():
            return {"error": {"message": (
                "image generation needs at least 4096 MB free GPU memory; "
                "only 717 MB is free"
            )}}

    calls = []
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_URL", "http://native")
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_RETRIES", 0)
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_BACKGROUND_HEADROOM_GRACE_SECONDS", 0.0)
    monkeypatch.setattr(
        server.requests,
        "post",
        lambda url, **kwargs: calls.append((url, kwargs)) or FakeResponse(),
    )
    payload = {
        "prompt": "x" * prompt_len,
        "width": 1024,
        "height": 1024,
        "_omniserve_tier": "background",
    }

    with pytest.raises(server.HTTPException) as exc_info:
        server._call_native_zimage(payload)

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers == {"Retry-After": "15"}
    assert calls[0][1]["headers"]["X-Omniserve-Tier"] == "background"
    assert calls[0][1]["json"]["prompt"] == "x" * prompt_len
    assert "_omniserve_tier" not in calls[0][1]["json"]


@pytest.mark.parametrize("prompt_len", [12, 74, 166, 4096])
def test_background_native_admission_timeout_is_retryable_backpressure(
    monkeypatch, prompt_len
):
    class FakeResponse:
        status_code = 503

        @staticmethod
        def json():
            return {"error": {"message": "admission timeout; retry"}}

    calls = []
    sleeps = []
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_URL", "http://native")
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_RETRIES", 1)
    monkeypatch.setattr(server.time, "sleep", sleeps.append)
    monkeypatch.setattr(
        server.requests,
        "post",
        lambda url, **kwargs: calls.append((url, kwargs)) or FakeResponse(),
    )

    with pytest.raises(server.HTTPException) as exc_info:
        server._call_native_zimage({
            "prompt": "x" * prompt_len,
            "width": 1024,
            "height": 1024,
            "steps": 8,
            "teleport": False,
            "_omniserve_tier": "background",
        })

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers == {"Retry-After": "15"}
    assert len(calls) == 1
    assert sleeps == []
    assert calls[0][1]["headers"]["X-Omniserve-Tier"] == "background"
    assert calls[0][1]["json"]["prompt"] == "x" * prompt_len
    assert "_omniserve_tier" not in calls[0][1]["json"]


@pytest.mark.parametrize("prompt_len", [24, 136, 512, 4096])
@pytest.mark.parametrize("tier,expected_status", [("background", 429), ("paid", 503)])
def test_native_read_timeout_does_not_duplicate_generation(
    monkeypatch, prompt_len, tier, expected_status
):
    calls = []
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_URL", "http://native")
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_RETRIES", 3)

    def post(_url, **kwargs):
        calls.append(kwargs)
        raise server.requests.ReadTimeout("native request still queued")

    monkeypatch.setattr(server.requests, "post", post)
    with pytest.raises(server.HTTPException) as exc_info:
        server._call_native_zimage({
            "prompt": "x" * prompt_len,
            "width": 1024,
            "height": 1024,
            "steps": 8,
            "teleport": False,
            "_omniserve_tier": tier,
        })

    assert exc_info.value.status_code == expected_status
    assert exc_info.value.headers == {"Retry-After": "15"}
    assert len(calls) == 1
    assert calls[0]["json"]["prompt"] == "x" * prompt_len
    assert calls[0]["headers"]["X-Omniserve-Tier"] == tier


@pytest.mark.parametrize("prompt_len", [24, 136, 512, 4096])
@pytest.mark.parametrize("admission", [
    {"slots": 8, "used_slots": 8, "waiting": {}},
    {"slots": 8, "used_slots": 4, "waiting": {"paid": 1}},
])
def test_background_native_queue_preflight_returns_backpressure(
    monkeypatch, prompt_len, admission
):
    calls = []
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_URL", "http://127.0.0.1:8791")
    monkeypatch.setattr(server.requests, "get", lambda *_args, **_kwargs: types.SimpleNamespace(
        status_code=200, json=lambda: {"admission": admission}
    ))
    monkeypatch.setattr(server.requests, "post", lambda *_args, **_kwargs: calls.append(True))

    with pytest.raises(server.HTTPException) as exc_info:
        server._call_native_zimage({
            "prompt": "x" * prompt_len,
            "width": 1024,
            "height": 1024,
            "_omniserve_tier": "background",
        })

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers == {"Retry-After": "15"}
    assert calls == []


def test_native_background_preflight_fails_open_without_status(monkeypatch):
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_URL", "http://127.0.0.1:8791")
    def status_unavailable(*_args, **_kwargs):
        raise server.requests.ConnectionError("status unavailable")

    monkeypatch.setattr(server.requests, "get", status_unavailable)
    calls = []
    monkeypatch.setattr(server.requests, "post", lambda *_args, **_kwargs: (
        calls.append(True) or types.SimpleNamespace(
            status_code=200, json=lambda: _native_image_document(width=512, height=512)
        )
    ))

    result = server._call_native_zimage({
        "prompt": "a red fox", "width": 512, "height": 512,
        "_omniserve_tier": "background",
    })

    assert result["width"] == 512
    assert calls == [True]


def test_native_fallback_waits_through_repeated_opaque_generation_failures(monkeypatch):
    class FakeResponse:
        def __init__(self, status_code, document):
            self.status_code = status_code
            self._document = document

        def json(self):
            return self._document

    responses = iter([
        FakeResponse(500, {"error": {"message": "image generation failed"}}),
        FakeResponse(500, {"error": {"message": "image generation failed"}}),
        FakeResponse(200, _native_image_document(width=1024, height=1024)),
    ])
    clock = iter([10.0, 12.0])
    sleeps = []
    cleanup_calls = []
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_URL", "http://native")
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_RETRIES", 0)
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_GENERATION_FAILURE_GRACE_SECONDS", 30.0)
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_GENERATION_FAILURE_POLL_SECONDS", 2.0)
    monkeypatch.setattr(server.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(server.time, "sleep", sleeps.append)
    monkeypatch.setattr(server, "_clear_torch_cuda_caches", lambda: cleanup_calls.append(True))
    monkeypatch.setattr(
        server.requests,
        "post",
        lambda *_args, **_kwargs: next(responses),
    )

    result = server._call_native_zimage({
        "prompt": "shared GPU recovery probe",
        "width": 1024,
        "height": 1024,
    })

    assert result["backend"] == "omniserve-native"
    assert sleeps == [2.0, 2.0]
    assert cleanup_calls == [True, True]


@pytest.mark.parametrize("prompt_len", [5, 161, 1024, 4096])
def test_fal_fallback_preserves_prompt_dimensions_steps_and_seed(monkeypatch, prompt_len):
    seen = []
    document = _native_image_document(width=1024, height=1024)
    image_url = "data:image/webp;base64," + document["data"][0]["b64_json"]

    def subscribe(endpoint, *, arguments, **kwargs):
        seen.append((endpoint, arguments, kwargs))
        return {"images": [{"url": image_url}], "seed": arguments["seed"]}

    monkeypatch.setitem(sys.modules, "fal_client", types.SimpleNamespace(subscribe=subscribe))
    prompt = "x" * prompt_len
    result = server._call_fal_zimage({
        "prompt": prompt,
        "width": 1024,
        "height": 1024,
        "steps": 8,
        "seed": 12345,
        "teleport": True,
    })

    endpoint, arguments, kwargs = seen[0]
    assert endpoint == "fal-ai/z-image/turbo"
    assert arguments["prompt"] == prompt
    assert arguments["image_size"] == {"width": 1024, "height": 1024}
    assert arguments["num_inference_steps"] == 8
    assert arguments["seed"] == 12345
    assert arguments["sync_mode"] is True
    assert arguments["enable_prompt_expansion"] is False
    assert kwargs["client_timeout"] == server.ZIMAGE_FAL_FALLBACK_TIMEOUT_SECONDS
    assert result["backend"] == "fal"
    assert result["teleport"]["method"] == "remote_full_generation"
    assert result["teleport"]["cache_hit"] is False


def test_fal_fallback_preserves_lora_url_and_effective_scale(monkeypatch):
    seen = []
    document = _native_image_document()
    image_url = "data:image/webp;base64," + document["data"][0]["b64_json"]
    monkeypatch.setitem(
        sys.modules,
        "fal_client",
        types.SimpleNamespace(
            subscribe=lambda endpoint, *, arguments, **_kwargs: (
                seen.append((endpoint, arguments)) or {"images": [{"url": image_url}]}
            )
        ),
    )
    lora = types.SimpleNamespace(
        id="pixel_art",
        url="https://assets.example/pixel-art.safetensors",
        scale=0.75,
    )

    result = server._call_fal_zimage({
        "prompt": "pixel art castle",
        "width": 512,
        "height": 512,
        "steps": 8,
        "seed": 7,
        "lora_scale": 0.6,
    }, lora)

    assert seen == [("fal-ai/z-image/turbo/lora", {
        "prompt": "pixel art castle",
        "image_size": {"width": 512, "height": 512},
        "num_inference_steps": 8,
        "seed": 7,
        "sync_mode": True,
        "num_images": 1,
        "enable_safety_checker": False,
        "output_format": "webp",
        "enable_prompt_expansion": False,
        "loras": [{
            "path": "https://assets.example/pixel-art.safetensors",
            "scale": 0.6,
        }],
    })]
    assert result["model"] == "fal-ai/z-image/turbo/lora"


def test_native_failure_opens_circuit_and_avoids_repeated_cuda_failures(monkeypatch):
    native_calls = []
    remote_calls = []
    monkeypatch.setattr(server, "ZIMAGE_FAL_FALLBACK_ENABLED", True)
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FAILURE_COOLDOWN_SECONDS", 60.0)
    monkeypatch.setattr(
        server,
        "_call_native_zimage",
        lambda payload: native_calls.append(payload) or (_ for _ in ()).throw(
            server.HTTPException(503, "native CUDA exhausted")
        ),
    )
    monkeypatch.setattr(
        server,
        "_call_fal_zimage",
        lambda payload, lora=None: remote_calls.append((payload, lora)) or {"backend": "fal"},
    )
    monkeypatch.setattr(server, "_native_fallback_disabled_until", 0.0)
    payload = {"prompt": "test", "width": 512, "height": 512, "steps": 8}

    assert server._call_resilient_zimage(payload) == {"backend": "fal"}
    assert server._call_resilient_zimage(payload) == {"backend": "fal"}

    assert native_calls == [payload]
    assert remote_calls == [(payload, None), (payload, None)]


def test_native_connection_refusal_retries_then_uses_remote_fallback(monkeypatch):
    native_calls = []
    remote_calls = []
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_URL", "http://127.0.0.1:8791")
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_RETRIES", 1)
    monkeypatch.setattr(server, "ZIMAGE_FAL_FALLBACK_ENABLED", True)
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FAILURE_COOLDOWN_SECONDS", 30.0)
    monkeypatch.setattr(server.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        server.requests,
        "post",
        lambda url, **_kwargs: native_calls.append(url) or (_ for _ in ()).throw(
            server.requests.ConnectionError("[Errno 111] Connection refused")
        ),
    )
    monkeypatch.setattr(
        server,
        "_call_fal_zimage",
        lambda payload, lora=None: remote_calls.append((payload, lora)) or {"backend": "fal"},
    )
    monkeypatch.setattr(server, "_native_fallback_disabled_until", 0.0)
    payload = {"prompt": "test", "width": 512, "height": 512, "steps": 8}

    assert server._call_resilient_zimage(payload) == {"backend": "fal"}
    assert native_calls == [
        "http://127.0.0.1:8791/v1/images/generations",
        "http://127.0.0.1:8791/v1/images/generations",
    ]
    assert remote_calls == [(payload, None)]
    assert server._native_fallback_disabled_until > 0.0


def test_native_connection_refusal_waits_through_managed_restart(monkeypatch):
    calls = []
    sleeps = []
    clock = iter([10.0, 11.0])
    document = _native_image_document()

    def post(*_args, **_kwargs):
        calls.append(True)
        if len(calls) < 3:
            raise server.requests.ConnectionError("service restarting")
        return types.SimpleNamespace(
            status_code=200,
            json=lambda: document,
        )

    monkeypatch.setattr(server.requests, "post", post)
    monkeypatch.setattr(server.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(server.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_RETRIES", 0)
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_RESTART_GRACE_SECONDS", 150.0)
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_RESTART_POLL_SECONDS", 2.0)
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_URL", "http://127.0.0.1:8791")

    result = server._call_native_zimage({"width": 512, "height": 512})

    assert result["backend"] == "omniserve-native"
    assert len(calls) == 3
    assert sleeps == [2.0, 2.0]


@pytest.mark.parametrize("prompt_len", [11, 114, 1024, 4096])
def test_background_native_connection_refusal_is_immediate_backpressure(
    monkeypatch, prompt_len
):
    calls = []
    sleeps = []
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_URL", "http://127.0.0.1:8791")
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_RETRIES", 1)
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_RESTART_GRACE_SECONDS", 150.0)
    monkeypatch.setattr(server.time, "sleep", sleeps.append)
    monkeypatch.setattr(
        server.requests,
        "post",
        lambda url, **kwargs: calls.append((url, kwargs)) or (_ for _ in ()).throw(
            server.requests.ConnectionError("[Errno 111] Connection refused")
        ),
    )

    with pytest.raises(server.HTTPException) as exc_info:
        server._call_native_zimage({
            "prompt": "x" * prompt_len,
            "width": 1024,
            "height": 1024,
            "steps": 8,
            "teleport": False,
            "_omniserve_tier": "background",
        })

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == "native fallback is restarting"
    assert exc_info.value.headers == {"Retry-After": "15"}
    assert len(calls) == 1
    assert calls[0][1]["headers"]["X-Omniserve-Tier"] == "background"
    assert calls[0][1]["json"]["prompt"] == "x" * prompt_len
    assert sleeps == []


def test_remote_fallback_is_not_used_without_explicit_opt_in(monkeypatch):
    monkeypatch.setattr(server, "ZIMAGE_FAL_FALLBACK_ENABLED", False)
    monkeypatch.setattr(server, "_call_native_zimage", lambda _payload: {"backend": "native"})
    monkeypatch.setattr(
        server,
        "_call_fal_zimage",
        lambda *_args, **_kwargs: pytest.fail("metered fallback must remain opt-in"),
    )

    assert server._call_resilient_zimage({}) == {"backend": "native"}


def test_native_payload_preserves_steps_teleport_and_auto_lora(monkeypatch):
    fake_lora = types.SimpleNamespace(
        id="pixel_art",
        name="Pixel Art",
        url="https://assets.example/TartarusPixel_pixelart_pixels.safetensors",
        scale=0.75,
    )
    monkeypatch.setattr(server, "lora_engine", object())
    monkeypatch.setattr(
        server,
        "_resolve_lora",
        lambda req: (fake_lora, f"pixel art, {req.prompt}"),
    )
    req = server.ZImageRequest(
        prompt="stone inventory icon",
        width=530,
        height=517,
        seed=42,
        num_inference_steps=8,
        auto_lora=True,
        teleport=True,
    )

    payload, selected = server._native_zimage_request(req, req.prompt)

    assert selected is fake_lora
    assert payload == {
        "model": "zimage-turbo",
        "prompt": "pixel art, stone inventory icon",
        "width": 512,
        "height": 512,
        "steps": 8,
        "guidance_scale": server.ZIMAGE_DEFAULT_GUIDANCE,
        "seed": 42,
        "teleport": False,
        "response_format": "b64_json",
        "_omniserve_tier": "paid",
        "lora_id": "pixel_art",
        "lora_filename": "TartarusPixel_pixelart_pixels.safetensors",
        "lora_scale": 0.75,
    }


@pytest.mark.parametrize("prompt_len", [34, 41, 256, 1024, 4096])
def test_native_payload_preserves_short_through_very_long_prompts(monkeypatch, prompt_len):
    prompt = "x" * prompt_len
    monkeypatch.setattr(server, "lora_engine", object())
    monkeypatch.setattr(server, "_resolve_lora", lambda req: (None, req.prompt))

    payload, selected = server._native_zimage_request(
        server.ZImageRequest(prompt=prompt, auto_lora=True, teleport=True),
        prompt,
    )

    assert selected is None
    assert payload["prompt"] == prompt
    assert len(payload["prompt"]) == prompt_len
    assert payload["teleport"] is True
    assert payload["_omniserve_tier"] == "paid"


def test_native_payload_marks_low_priority_request_as_background(monkeypatch):
    monkeypatch.setattr(server, "lora_engine", object())
    monkeypatch.setattr(server, "_resolve_lora", lambda req: (None, req.prompt))

    payload, selected = server._native_zimage_request(
        server.ZImageRequest(prompt="gallery farm", low_priority=True),
        "gallery farm",
    )

    assert selected is None
    assert payload["_omniserve_tier"] == "background"


def test_training_routes_require_image_api_secret_before_work(monkeypatch):
    monkeypatch.setattr(server, "IMAGE_API_SECRETS", {"expected-secret"})

    with pytest.raises(server.HTTPException) as exc_info:
        server.start_training(
            server.LoRATrainRequest(model="zimage", dataset_name="dataset"),
            secret="wrong-secret",
        )

    assert exc_info.value.status_code == 403


@pytest.mark.parametrize("model", ["zimage", "chronos2"])
def test_production_worker_rejects_local_gpu_training_as_nonretryable_conflict_without_starting_thread(
    monkeypatch, model
):
    monkeypatch.setattr(server, "IMAGE_API_SECRETS", set())
    monkeypatch.setattr(server, "LOCAL_GPU_TRAINING_ENABLED", False)
    jobs_before = set(server.training_jobs)

    with pytest.raises(server.HTTPException) as exc_info:
        server.start_training(
            server.LoRATrainRequest(model=model, dataset_name="dataset"),
        )

    assert exc_info.value.status_code == 409
    assert "inference-only worker" in exc_info.value.detail
    assert exc_info.value.headers is None
    assert set(server.training_jobs) == jobs_before


def test_local_training_wrapper_always_reclaims_cuda_cache(monkeypatch):
    cleanup_calls = []
    monkeypatch.setattr(server, "_clear_torch_cuda_caches", lambda: cleanup_calls.append(True))

    def fail(_job_id, _req):
        raise RuntimeError("training failed")

    with pytest.raises(RuntimeError, match="training failed"):
        server._run_local_training_serialized(
            fail,
            "job-id",
            server.LoRATrainRequest(model="zimage", dataset_name="dataset"),
        )

    assert cleanup_calls == [True]


@pytest.mark.parametrize("prompt_len", [21, 80, 1024, 4096])
@pytest.mark.parametrize("auto_lora,teleport", [(False, False), (False, True), (True, False), (True, True)])
def test_native_upload_perf_is_reporting_only(monkeypatch, prompt_len, auto_lora, teleport):
    seen_payloads = []
    native_document = _native_image_document(
        teleport={"method": "exact_prompt_latent_replay", "cache_hit": True}
    )
    encoded = native_document["data"][0]["b64_json"]
    image_bytes = base64.b64decode(encoded)
    monkeypatch.setattr(server, "lora_engine", object())
    monkeypatch.setattr(server, "_resolve_lora", lambda req: (None, req.prompt))
    monkeypatch.setattr(server, "check_if_blob_exists", lambda _path: False)
    monkeypatch.setattr(
        server,
        "_call_native_zimage",
        lambda payload: seen_payloads.append(dict(payload)) or {
            "encoded": encoded,
            "image_bytes": image_bytes,
            "format": "webp",
            "width": 512,
            "height": 512,
            "inference_time_ms": 123,
            "teleport": {"method": "exact_prompt_latent_replay", "cache_hit": True},
            "model": "z_image_turbo-Q4_K",
        },
    )
    monkeypatch.setattr(
        server,
        "upload_bytes",
        lambda path, data, content_type: f"https://images/{path}?{content_type}&{len(data)}",
    )

    result = server._generate_and_upload_native_sync(
        "x" * prompt_len,
        512,
        512,
        "tests/native.webp",
        auto_lora,
        None,
        True,
        8,
        teleport=teleport,
    )

    without_perf = server._generate_and_upload_native_sync(
        "x" * prompt_len, 512, 512, "tests/native.webp", auto_lora, None,
        False, 8, teleport=teleport,
    )
    assert seen_payloads[0] == seen_payloads[1]
    assert without_perf == {key: value for key, value in result.items() if key != "perf"}
    assert "perf" not in seen_payloads[0]
    assert result["perf"]["backend"] == "omniserve-native"
    assert result["perf"]["inference_time_ms"] == 123
    if teleport:
        assert result["perf"]["teleport_cache_hit"] is True
        assert result["teleport"]["method"] == "exact_prompt_latent_replay"
    else:
        assert "teleport" not in result


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


def test_zimage_batch_oom_uses_native_fallback_without_reloading_local_model(monkeypatch):
    class FakeModelManager:
        def __init__(self):
            self.loaded = True
            self.use_calls = 0

        def is_loaded(self, _model_name):
            return self.loaded

        @contextlib.contextmanager
        def use(self, _model_name):
            self.use_calls += 1
            yield

    class FakeCudaOOM(RuntimeError):
        pass

    manager = FakeModelManager()
    recoveries = []
    request = server.ZImageRequest(prompt="fallback after OOM")
    monkeypatch.setattr(server, "model_manager", manager)
    monkeypatch.setattr(server, "zimage_pipeline", (object(), None))
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_URL", "http://native.test")
    monkeypatch.setattr(server, "_is_cuda_oom", lambda exc: isinstance(exc, FakeCudaOOM))
    monkeypatch.setattr(
        server,
        "_generate_image_batch_sync",
        lambda _reqs: (_ for _ in ()).throw(FakeCudaOOM("CUDA out of memory")),
    )

    def recover():
        recoveries.append(True)
        manager.loaded = False

    monkeypatch.setattr(server, "_recover_from_cuda_oom", recover)
    monkeypatch.setattr(
        server,
        "_generate_image_native_sync",
        lambda req: {"backend": "native", "prompt": req.prompt},
    )

    assert server._generate_image_batch_with_model_sync([request]) == [
        {"backend": "native", "prompt": "fallback after OOM"}
    ]
    assert recoveries == [True]
    assert manager.use_calls == 1


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


@pytest.mark.parametrize("prompt_len", [22, 80, 1024, 4096])
@pytest.mark.parametrize("upload", [False, True])
@pytest.mark.parametrize("status,detail", [
    (503, "native fallback returned HTTP 503: image generation needs at least 4096 MB free GPU memory; managed GPU capacity is busy"),
    (503, "native fallback returned HTTP 500: image generation failed"),
    (503, "native fallback response failed validation (ConnectionError)"),
    (429, "native fallback is restarting"),
    (502, "native fallback returned HTTP 400: invalid dimensions"),
    (502, "native fallback returned HTTP 400: invalid floral prompt"),
    (502, "native fallback returned HTTP 403: lora access denied"),
])
def test_native_infrastructure_failure_does_not_remove_lora(
    monkeypatch, prompt_len, upload, status, detail
):
    prompt = "x" * prompt_len
    lora = types.SimpleNamespace(id="pixel_art", name="Pixel Art")
    payload = {"prompt": prompt, "lora_id": lora.id, "lora_scale": 0.75}
    failure = server.HTTPException(status, detail, headers={"Retry-After": "5"})
    calls = []

    def fail(request, selected=None):
        calls.append((dict(request), selected))
        raise failure

    monkeypatch.setattr(server, "_native_zimage_request", lambda *_args: (payload, lora))
    monkeypatch.setattr(server, "_call_resilient_zimage", fail)
    monkeypatch.setattr(server, "check_if_blob_exists", lambda _path: False)
    monkeypatch.setattr(server, "upload_bytes", lambda *_args, **_kwargs: pytest.fail("no image to upload"))
    with pytest.raises(server.HTTPException) as caught:
        if upload:
            server._generate_and_upload_native_sync(
                prompt, 1024, 1024, "test.webp", True, None, False, 9,
                teleport=True,
            )
        else:
            server._generate_image_native_once_sync(server.ZImageRequest(prompt=prompt), prompt)

    assert caught.value is failure
    assert calls == [(payload, lora)]
    assert payload["lora_id"] == "pixel_art"
    assert payload["prompt"] == prompt


@pytest.mark.parametrize("upload", [False, True])
def test_native_explicit_invalid_lora_can_still_fall_back(monkeypatch, upload):
    lora = types.SimpleNamespace(id="missing", name="Missing")
    payload = {"prompt": "pixel art fox", "lora_id": lora.id, "lora_filename": "missing.safetensors", "lora_scale": 1}
    calls = []

    def generate(request, selected=None):
        calls.append(dict(request))
        if selected:
            raise server.HTTPException(502, "native fallback returned HTTP 400: unknown lora_id")
        return {"encoded": "image", "image_bytes": b"image", "format": "webp", "width": 1024,
                "height": 1024, "inference_time_ms": 1, "teleport": None, "model": "zimage"}

    monkeypatch.setattr(server, "_native_zimage_request", lambda *_args: (payload, lora))
    monkeypatch.setattr(server, "_call_resilient_zimage", generate)
    monkeypatch.setattr(server, "check_if_blob_exists", lambda _path: False)
    monkeypatch.setattr(server, "upload_bytes", lambda *_args, **_kwargs: "https://example.com/test.webp")
    if upload:
        server._generate_and_upload_native_sync("pixel art fox", 1024, 1024, "test.webp", True, None, False, 9, teleport=True)
    else:
        server._generate_image_native_once_sync(server.ZImageRequest(prompt="pixel art fox"), "pixel art fox")
    assert len(calls) == 2
    assert calls[0]["lora_id"] == "missing"
    assert not any(key.startswith("lora_") for key in calls[1])


@pytest.mark.parametrize("first_failure,last_failure", [
    ("headroom", "generation"), ("headroom", "restart"),
    ("generation", "headroom"), ("generation", "restart"),
    ("restart", "headroom"), ("restart", "generation"),
])
@pytest.mark.parametrize("started", [0.0, 10.0])
def test_native_recovery_types_share_one_grace_origin(
    monkeypatch, first_failure, last_failure, started
):
    clock = iter([started, started + 6.0])
    calls = []
    sleeps = []

    def post(*_args, **_kwargs):
        calls.append(True)
        failure = first_failure if len(calls) == 1 else last_failure
        if failure == "headroom":
            return types.SimpleNamespace(status_code=503, json=lambda: {"error": {"message":
                "image generation needs at least 4096 MB free GPU memory; managed GPU capacity is busy"}})
        if failure == "restart":
            raise server.requests.ConnectionError("restarting")
        return types.SimpleNamespace(status_code=500, json=lambda: {"error": {"message": "image generation failed"}})

    monkeypatch.setattr(server.requests, "post", post)
    monkeypatch.setattr(server.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(server.time, "sleep", sleeps.append)
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_RETRIES", 0)
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_HEADROOM_GRACE_SECONDS", 5.0)
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_GENERATION_FAILURE_GRACE_SECONDS", 5.0)
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_RESTART_GRACE_SECONDS", 5.0)
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_HEADROOM_POLL_SECONDS", 2.0)
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_GENERATION_FAILURE_POLL_SECONDS", 2.0)
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_RESTART_POLL_SECONDS", 2.0)
    monkeypatch.setattr(server, "_clear_torch_cuda_caches", lambda: None)
    with pytest.raises(server.HTTPException) as caught:
        server._call_native_zimage({"prompt": "a small woodland cabin", "width": 1024, "height": 1024})
    assert caught.value.status_code == (429 if last_failure in {"headroom", "generation"} else 503)
    assert len(calls) == 2
    assert sleeps == [2.0]


@pytest.mark.parametrize("prompt_len", [21, 80, 1024, 4096])
@pytest.mark.parametrize("tier", ["paid", "background"])
@pytest.mark.parametrize("failure_status,message", [
    (503, "image generation needs at least 4096 MB free GPU memory; managed GPU capacity is busy"),
    (500, "image generation failed"),
])
def test_exhausted_capacity_grace_does_not_start_generic_retry(
    monkeypatch, prompt_len, tier, failure_status, message
):
    clock = [0.0]
    calls = []
    payload = {"prompt": "x" * prompt_len, "width": 1024, "height": 1024,
               "steps": 9, "seed": 42, "teleport": True,
               "lora_id": "pixel_art", "lora_scale": 0.75, "_omniserve_tier": tier}

    def post(_url, **kwargs):
        calls.append(dict(kwargs["json"]))
        return types.SimpleNamespace(status_code=failure_status,
                                     json=lambda: {"error": {"message": message}})

    monkeypatch.setattr(server.requests, "post", post)
    monkeypatch.setattr(server.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(server.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay))
    monkeypatch.setattr(server, "_clear_torch_cuda_caches", lambda: None)
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_FALLBACK_RETRIES", 3)
    for name in ("HEADROOM", "BACKGROUND_HEADROOM", "GENERATION_FAILURE"):
        monkeypatch.setattr(server, f"ZIMAGE_NATIVE_{name}_GRACE_SECONDS", 2.0)
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_HEADROOM_POLL_SECONDS", 2.0)
    monkeypatch.setattr(server, "ZIMAGE_NATIVE_GENERATION_FAILURE_POLL_SECONDS", 2.0)

    with pytest.raises(server.HTTPException) as caught:
        server._call_native_zimage(payload)

    assert caught.value.status_code == 429
    assert caught.value.headers == {"Retry-After": "15"}
    assert clock[0] == 2.0
    expected = {k: v for k, v in payload.items() if k != "_omniserve_tier"}
    assert calls == [expected, expected]


@pytest.mark.parametrize('prompt_len', [19, 87, 125, 1024, 4096])
@pytest.mark.parametrize('fmt,mime', [('WEBP', 'image/webp'), ('PNG', 'image/png'), ('JPEG', 'image/jpeg')])
def test_native_binary_overflow_preserves_image_and_request(monkeypatch, prompt_len, fmt, mime):
    output = io.BytesIO()
    Image.new('RGB', (512, 512), (36, 72, 108)).save(output, format=fmt)
    body = output.getvalue()
    response = server.requests.Response()
    response.status_code = 200
    response.headers['Content-Type'] = mime + '; charset=binary'
    response._content = body
    calls = []
    monkeypatch.setattr(server.requests, 'post', lambda *a, **kw: calls.append(kw) or response)
    payload = dict(prompt='x' * prompt_len, width=512, height=512, steps=8,
                   teleport=True, response_format='b64_json', _omniserve_tier='background')
    result = server._call_native_zimage(payload)
    assert len(calls) == 1
    assert calls[0]['json'] == {k: v for k, v in payload.items() if not k.startswith('_')}
    assert calls[0]['headers']['X-Omniserve-Tier'] == 'background'
    assert result['image_bytes'] == body
    assert base64.b64decode(result['encoded']) == body
    assert result['format'] == fmt.lower()
    assert result['teleport'] is None  # No invented cache-hit metadata.
    assert result['model'] is None


@pytest.mark.parametrize('failure', ['html', 'empty', 'corrupt', 'truncated', 'dimensions', 'oversize'])
def test_native_invalid_overflow_is_bounded_and_retryable(monkeypatch, failure):
    output = io.BytesIO()
    Image.new('RGB', (512, 512), (36, 72, 108)).save(output, format='PNG')
    body = output.getvalue()
    mime = 'image/png'
    if failure == 'html':
        body, mime = b'<html>upstream unavailable</html>', 'text/html'
    elif failure == 'empty':
        body = b''
    elif failure == 'corrupt':
        body = b'not an image'
    elif failure == 'truncated':
        body = body[:60]  # A readable header, but incomplete pixel data.
    elif failure == 'oversize':
        monkeypatch.setattr(server, 'REMOTE_IMAGE_MAX_BYTES', len(body) - 1)
    response = server.requests.Response()
    response.status_code = 200
    response.headers['Content-Type'] = mime
    response._content = body
    calls = []
    monkeypatch.setattr(server.requests, 'post', lambda *a, **kw: calls.append(kw) or response)
    monkeypatch.setattr(server, 'ZIMAGE_NATIVE_FALLBACK_RETRIES', 1)
    monkeypatch.setattr(server.time, 'sleep', lambda _: None)
    with pytest.raises(server.HTTPException) as exc:
        server._call_native_zimage(dict(prompt='fox', width=1024 if failure == 'dimensions' else 512, height=512))
    assert exc.value.status_code == 503
    assert exc.value.headers == {'Retry-After': '5'}
    assert len(calls) == 2
