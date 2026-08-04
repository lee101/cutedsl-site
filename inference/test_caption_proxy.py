import asyncio
import sys
from collections import namedtuple
from pathlib import Path

import httpx


sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402


class FakeResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"caption": "a test image"}


class RecordingClient:
    def __init__(self):
        self.calls = []

    async def post(self, path, **kwargs):
        self.calls.append((path, kwargs))
        return FakeResponse()


def test_caption_backend_headers_use_caption_specific_key(monkeypatch):
    monkeypatch.setattr(server, "CAPTION_BACKEND_API_KEY", "rotated-caption-key")

    assert server._caption_backend_headers() == {"secret": "rotated-caption-key"}


def test_caption_backend_headers_omit_empty_secret(monkeypatch):
    monkeypatch.setattr(server, "CAPTION_BACKEND_API_KEY", "")
    monkeypatch.setattr(server, "TG_API_KEY", "")

    assert server._caption_backend_headers() == {}


def test_configured_caption_key_prefers_backend_service_credential(monkeypatch):
    completed = namedtuple("Completed", "returncode stdout")
    monkeypatch.setenv("CAPTION_BACKEND_API_KEY", "stale-inherited-key")
    monkeypatch.setattr(
        server.subprocess,
        "run",
        lambda *_args, **_kwargs: completed(
            0,
            "NETWRCK_IMAGE_CAPTION_SECRET=rotated-service-key OTHER=value",
        ),
    )

    assert server._configured_caption_backend_api_key() == "rotated-service-key"


def test_configured_caption_key_falls_back_outside_systemd(monkeypatch):
    completed = namedtuple("Completed", "returncode stdout")
    monkeypatch.setenv("CAPTION_BACKEND_API_KEY", "explicit-key")
    monkeypatch.setattr(
        server.subprocess,
        "run",
        lambda *_args, **_kwargs: completed(1, ""),
    )

    assert server._configured_caption_backend_api_key() == "explicit-key"


def test_caption_auth_error_is_generic_and_does_not_leak_backend_details():
    request = httpx.Request("POST", "http://caption.internal/api/v1/image-caption")
    response = httpx.Response(401, request=request)
    upstream = httpx.HTTPStatusError("secret-value", request=request, response=response)

    error = server._caption_backend_error(upstream)

    assert error.status_code == 502
    assert error.detail == "Caption backend authentication failed"
    assert "secret-value" not in error.detail
    assert "caption.internal" not in error.detail


def test_caption_backend_client_error_remains_4xx():
    request = httpx.Request("POST", "http://caption.internal/api/v1/image-caption")
    response = httpx.Response(400, request=request)
    upstream = httpx.HTTPStatusError("bad image URL", request=request, response=response)

    error = server._caption_backend_error(upstream)

    assert error.status_code == 400
    assert error.detail == "Caption request rejected by backend"
    assert "caption.internal" not in error.detail


def test_caption_endpoint_sends_scoped_auth_and_form_data(monkeypatch):
    client = RecordingClient()
    monkeypatch.setattr(server, "tg_client", client)
    monkeypatch.setattr(server, "CAPTION_BACKEND_API_KEY", "rotated-caption-key")

    result = asyncio.run(server.caption_image(server.CaptionRequest(image_url="https://example.com/image.webp")))

    assert result == {"caption": "a test image"}
    assert client.calls == [
        (
            "/api/v1/image-caption",
            {
                "data": {"image_url": "https://example.com/image.webp", "fast_mode": "true"},
                "headers": {"secret": "rotated-caption-key"},
            },
        )
    ]
