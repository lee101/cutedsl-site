import importlib.util
from pathlib import Path


def _load_probe_module():
    path = Path(__file__).with_name("zimage_reliability_probe.py")
    spec = importlib.util.spec_from_file_location("zimage_reliability_probe", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_reliability_probe_covers_prompt_lengths_and_modes():
    probe = _load_probe_module()

    prompt_labels = {label for label, _prompt in probe.PROMPTS}
    modes = {mode for mode, _auto_lora, _teleport in probe.MODES}

    assert {"short", "medium", "long", "very_long"} <= prompt_labels
    assert {"base", "teleport", "auto_lora", "auto_lora_teleport"} <= modes


def test_reliability_probe_can_run_as_low_priority(monkeypatch, tmp_path):
    probe = _load_probe_module()
    requested_urls = []

    monkeypatch.setattr(probe, "PROMPTS", [("short", "tiny prompt")])
    monkeypatch.setattr(probe, "MODES", [("base", False, False)])
    monkeypatch.setattr(probe, "now_slug", lambda: "20260624T000000Z")

    def fake_request_json(url, _timeout, _user_agent):
        requested_urls.append(url)
        return 200, {"path": "https://example.com/image.webp", "perf": {"inference_time_ms": 1}}, 0.1

    monkeypatch.setattr(probe, "request_json", fake_request_json)

    assert probe.main([
        "--base-url", "http://127.0.0.1:8100",
        "--output-dir", str(tmp_path),
        "--low-priority",
    ]) == 0

    assert "low_priority=true" in requested_urls[0]


def test_request_json_records_socket_timeout(monkeypatch):
    probe = _load_probe_module()

    def timeout(*_args, **_kwargs):
        raise TimeoutError("cold model load")

    monkeypatch.setattr(probe, "urlopen", timeout)
    status, payload, elapsed = probe.request_json(
        "http://127.0.0.1:8100/create_and_upload_image",
        timeout=0.01,
        user_agent="test",
    )

    assert status == 0
    assert "cold model load" in payload
    assert elapsed >= 0
