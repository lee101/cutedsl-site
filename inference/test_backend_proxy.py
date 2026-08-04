import asyncio
import sys
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError


sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402


class FakeResponse:
    status_code = 200
    content = b"RIFF-test-wav"

    def raise_for_status(self):
        return None

    def json(self):
        return {"text": "transcript"}


class RecordingClient:
    def __init__(self):
        self.calls = []

    async def post(self, path, **kwargs):
        self.calls.append((path, kwargs))
        return FakeResponse()


@pytest.mark.parametrize("length", [1, 80, 12_000])
def test_tts_text_accepts_short_medium_and_long_inputs(length):
    request = server.TTSRequest(text="x" * length)
    assert len(request.text) == length


@pytest.mark.parametrize("text", ["", " ", "\n\t"])
def test_tts_text_rejects_empty_or_whitespace_only_inputs(text):
    with pytest.raises(ValidationError, match="text"):
        server.TTSRequest(text=text)


def test_tg_backend_headers_fall_back_to_scoped_caption_key(monkeypatch):
    monkeypatch.setattr(server, "TG_API_KEY", "")
    monkeypatch.setattr(server, "CAPTION_BACKEND_API_KEY", "partner-key")
    assert server._tg_backend_headers() == {"secret": "partner-key"}


def test_tts_and_stt_send_scoped_backend_auth(monkeypatch):
    client = RecordingClient()
    monkeypatch.setattr(server, "tg_client", client)
    monkeypatch.setattr(server, "TG_API_KEY", "partner-key")

    asyncio.run(server.synthesize(server.TTSRequest(text="Hello")))
    asyncio.run(server.transcribe(server.STTRequest(audio_url="https://example.com/audio.wav")))

    assert [call[0] for call in client.calls] == [
        "/api/v1/generate_speech",
        "/api/v1/audio-extraction",
    ]
    assert all(call[1]["headers"] == {"secret": "partner-key"} for call in client.calls)


def test_backend_auth_error_is_generic_and_does_not_leak_upstream_details():
    request = httpx.Request("POST", "http://backend.internal/api/v1/generate_speech")
    response = httpx.Response(401, request=request)
    upstream = httpx.HTTPStatusError("secret-value", request=request, response=response)

    error = server._tg_backend_error("TTS", upstream)

    assert error.status_code == 502
    assert error.detail == "TTS backend authentication failed"
    assert "secret-value" not in error.detail
    assert "backend.internal" not in error.detail
