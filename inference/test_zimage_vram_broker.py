import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _broker_settings(monkeypatch):
    monkeypatch.setattr(server, "ZIMAGE_VRAM_BROKER_URL", "http://broker")
    monkeypatch.setattr(server, "ZIMAGE_DYNAMIC_BATCH_MAX_SIZE", 4)
    monkeypatch.setattr(server, "ZIMAGE_DYNAMIC_BATCH_MAX_PIXELS", 4 * 256 * 256)
    monkeypatch.setattr(server, "ZIMAGE_DYNAMIC_BATCH_RESERVE_MB", 512)
    monkeypatch.setattr(server, "ZIMAGE_DYNAMIC_BATCH_EXTRA_MB", 1024)
    monkeypatch.setattr(server, "_zimage_vram_broker_unreachable_until", 0.0)


def _requests(*, low_priority=False):
    return [
        server.ZImageRequest(
            prompt=f"prompt {index}",
            width=256,
            height=256,
            low_priority=low_priority,
        )
        for index in range(4)
    ]


def test_broker_grant_sets_capacity_and_releases_lease(monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/lease"):
            return _Response(
                {
                    "granted": True,
                    "lease_id": "lease-1",
                    "mb": 2560,
                    "expires_in_s": 60,
                }
            )
        return _Response({"released": True})

    monkeypatch.setattr(server.requests, "post", post)
    monkeypatch.setattr(
        server,
        "_cuda_free_mb",
        lambda: pytest.fail("a valid broker grant must replace CUDA headroom"),
    )

    assert server._zimage_batch_capacity(_requests(low_priority=True)) == 3
    assert calls[0][0] == "http://broker/v1/gpu/lease"
    assert calls[0][1]["json"] == {
        "owner": "zimage",
        "mb": 3584,
        "min_mb": 512,
        "tier": "background",
        "ttl_s": server.ZIMAGE_VRAM_BROKER_TTL_SECONDS,
    }
    assert calls[0][1]["timeout"] == 0.25
    assert calls[1][0] == "http://broker/v1/gpu/release"
    assert calls[1][1]["json"] == {"lease_id": "lease-1"}


def test_broker_denial_falls_back_to_cuda_capacity(monkeypatch):
    monkeypatch.setattr(
        server.requests,
        "post",
        lambda *_args, **_kwargs: _Response(
            {"granted": False, "mb": 0, "reason": "no headroom"}
        ),
    )
    monkeypatch.setattr(server, "_cuda_free_mb", lambda: 512)

    before = server._zimage_batch_runtime_snapshot()["broker_denials"]
    assert server._zimage_batch_capacity(_requests()) == 1
    assert server._zimage_batch_runtime_snapshot()["broker_denials"] == before + 1


def test_broker_unreachable_is_cached_and_fails_open(monkeypatch):
    calls = 0

    def post(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise TimeoutError("broker unavailable")

    monkeypatch.setattr(server.requests, "post", post)
    monkeypatch.setattr(server, "_cuda_free_mb", lambda: 8192)

    before = server._zimage_batch_runtime_snapshot()["broker_errors"]
    assert server._zimage_batch_capacity(_requests()) == 4
    assert server._zimage_batch_capacity(_requests()) == 4
    assert calls == 1
    assert server._zimage_batch_runtime_snapshot()["broker_errors"] == before + 1


def test_broker_lease_releases_when_chunk_raises(monkeypatch):
    calls = []

    def post(url, **_kwargs):
        calls.append(url)
        if url.endswith("/lease"):
            return _Response(
                {
                    "granted": True,
                    "lease_id": "lease-finally",
                    "mb": 3584,
                    "expires_in_s": 60,
                }
            )
        return _Response({"released": True})

    monkeypatch.setattr(server.requests, "post", post)

    with pytest.raises(RuntimeError, match="chunk failed"):
        with server._zimage_batch_allocation(_requests()):
            raise RuntimeError("chunk failed")

    assert calls == [
        "http://broker/v1/gpu/lease",
        "http://broker/v1/gpu/release",
    ]


def test_generation_holds_one_lease_per_chunk(monkeypatch):
    events = []

    def post(url, **kwargs):
        if url.endswith("/lease"):
            events.append(("lease", kwargs["json"]["mb"]))
            return _Response(
                {
                    "granted": True,
                    "lease_id": f"lease-{len(events)}",
                    "mb": 1536,
                    "expires_in_s": 60,
                }
            )
        events.append(("release", kwargs["json"]["lease_id"]))
        return _Response({"released": True})

    def generate(chunk):
        events.append(("generate", [req.prompt for req in chunk]))
        return [{"prompt": req.prompt} for req in chunk]

    monkeypatch.setattr(server.requests, "post", post)
    monkeypatch.setattr(server, "_generate_image_batch_sync", generate)
    monkeypatch.setattr(
        server,
        "_with_zimage_model_retry",
        lambda _operation_name, fn: fn(),
    )

    outputs = server._generate_image_batch_with_model_sync(_requests())

    assert [output["prompt"] for output in outputs] == [
        "prompt 0",
        "prompt 1",
        "prompt 2",
        "prompt 3",
    ]
    assert events == [
        ("lease", 3584),
        ("generate", ["prompt 0", "prompt 1"]),
        ("release", "lease-1"),
        ("lease", 1536),
        ("generate", ["prompt 2", "prompt 3"]),
        ("release", "lease-4"),
    ]
