import json

from codexexec_autofix import (
    format_event,
    is_actionable_inference_event,
    process_new_events,
)


def test_chronos_disabled_forecast_batch_is_not_actionable():
    event = {
        "status_code": 503,
        "path": "/forecast_batch",
        "error": "chronos2 disabled",
        "error_type": "HTTPException",
    }

    assert is_actionable_inference_event(event) is False


def test_image_5xx_remains_actionable_and_formats_prompt_metadata():
    event = {
        "request_id": "req-1",
        "status_code": 500,
        "method": "GET",
        "path": "/create_and_upload_image",
        "query": "prompt=pretty+girl+portrait&width=512&height=512&model=zimage-turbo&auto_lora=false&teleport=true&perf=true&secret=%3Credacted%3E",
        "prompt_len": 20,
        "prompt_words": 3,
        "prompt_sha256": "9cfc59d483ff9aa4",
        "error_type": "RuntimeError",
        "error": "boom",
        "traceback": ["Traceback...\n"],
    }

    assert is_actionable_inference_event(event) is True
    text = format_event(event, 1)
    assert "Prompt length: 20 chars / 3 words" in text
    assert "Prompt sha: 9cfc59d483ff9aa4" in text
    assert "width=512" in text
    assert "height=512" in text
    assert "model=zimage-turbo" in text
    assert "auto_lora=false" in text
    assert "teleport=true" in text
    assert "perf=true" in text


def test_process_new_events_skips_disabled_chronos_but_keeps_image_5xx(tmp_path, capsys):
    error_log = tmp_path / "errors.jsonl"
    state_path = tmp_path / "state"
    last_run_path = tmp_path / "last_run"
    chronos_event = {
        "status_code": 503,
        "path": "/forecast_batch",
        "error": "chronos2 disabled",
    }
    image_event = {
        "status_code": 500,
        "path": "/create_and_upload_image",
        "query": "prompt=x&width=512&height=512&model=zimage-turbo&auto_lora=false&teleport=false&perf=true",
        "prompt_len": 1,
        "prompt_words": 1,
        "prompt_sha256": "2d711642b726b044",
        "traceback": [],
    }
    error_log.write_text(
        json.dumps(chronos_event) + "\n" + json.dumps(image_event) + "\n",
        encoding="utf-8",
    )

    code = process_new_events(
        error_log=error_log,
        state_path=state_path,
        last_run_path=last_run_path,
        command="",
        dry_run=True,
        cooldown_seconds=0,
        max_events=8,
        kind="inference",
    )

    assert code == 0
    assert int(state_path.read_text()) == len(error_log.read_text())
    out = capsys.readouterr().out
    assert "Path: /create_and_upload_image" in out
    assert "Path: /forecast_batch" not in out
