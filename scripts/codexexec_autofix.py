#!/usr/bin/env python3
"""Bridge structured inference errors to a CodexExec-style autofix command.

Set CODEXEXEC_CMD to the command that should receive an autofix prompt on
stdin. The command is intentionally external so the inference server never
spawns a code agent from the request path.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import time
from pathlib import Path


DEFAULT_ERROR_LOG = "/nvme0n1-disk/tmp/cutedsl-inference-errors.jsonl"
DEFAULT_STATE = "/nvme0n1-disk/tmp/cutedsl-codexexec-autofix.state"
DEFAULT_LAST_RUN = "/nvme0n1-disk/tmp/cutedsl-codexexec-autofix-last-run"
DEFAULT_COOLDOWN_SECONDS = 10800

EXPECTED_DISABLED_MODEL_ERRORS = {
    ("chronos2", "chronos2 disabled"),
}


def load_offset(path: Path) -> int:
    try:
        return int(path.read_text().strip() or "0")
    except Exception:
        return 0


def save_offset(path: Path, offset: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(offset))


def load_timestamp(path: Path) -> float:
    try:
        return float(path.read_text().strip() or "0")
    except Exception:
        return 0.0


def save_timestamp(path: Path, timestamp: float):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(int(timestamp)))


def format_event(event: dict, index: int) -> str:
    return "\n".join([
        f"Failure event #{index}",
        f"Request ID: {event.get('request_id', '')}",
        f"Status: {event.get('status_code', '')}",
        f"Method: {event.get('method', '')}",
        f"Path: {event.get('path', '')}",
        f"Query: {event.get('query', '')}",
        f"Prompt length: {event.get('prompt_len', '')} chars / {event.get('prompt_words', '')} words",
        f"Prompt sha: {event.get('prompt_sha') or event.get('prompt_sha256', '')}",
        f"Error type: {event.get('error_type', '')}",
        f"Error: {event.get('error', '')}",
        "",
        "Traceback:",
        "".join(event.get("traceback", [])),
    ])


def is_expected_disabled_model_event(event: dict) -> bool:
    """Return True for deployment-expected disabled-model 5xx responses.

    The image inference process intentionally starts with LOAD_CHRONOS=0 to
    reserve GPU memory for Z-Image. A local direct call to /forecast or
    /forecast_batch therefore returns 503, but that is configuration state,
    not an image endpoint regression and should not launch an image autofix.
    """
    error = str(event.get("error", "")).strip().lower()
    path = str(event.get("path", ""))
    if path not in {"/forecast", "/forecast_batch"}:
        return False
    return ("chronos2", error) in EXPECTED_DISABLED_MODEL_ERRORS


def is_actionable_inference_event(event: dict) -> bool:
    try:
        status_code = int(event.get("status_code", 0))
    except (TypeError, ValueError):
        return False
    if status_code < 500:
        return False
    if is_expected_disabled_model_event(event):
        return False
    return True


def build_inference_prompt(events: list[dict]) -> str:
    event_text = "\n\n---\n\n".join(format_event(event, idx) for idx, event in enumerate(events, 1))
    return "\n".join([
        "Autofix and harden the CuteDSL image inference endpoint.",
        "",
        "Primary repository: /nvme0n1-disk/code/cutedsl-site",
        "Related repository, if relevant: /nvme0n1-disk/code/cutedsl",
        "Production endpoint to verify: https://images.netwrck.com/create_and_upload_image",
        "Local inference endpoint: http://127.0.0.1:8100/create_and_upload_image",
        "Structured error log: /nvme0n1-disk/tmp/cutedsl-inference-errors.jsonl",
        "Server log: /nvme0n1-disk/tmp/server_persistent.log",
        "",
        "Recent 5xx event(s):",
        "",
        event_text,
        "",
        "Required workflow:",
        "1. Reproduce the failure locally using the logged path/query when possible; include teleport, auto_lora, perf, width, height, and model parameters from the event.",
        "2. Inspect the code and logs thoroughly enough to identify the root cause, not just the surface traceback.",
        "3. Patch a robust fix in the relevant repo. Do not revert unrelated dirty work.",
        "4. Add or update focused tests for the failure mode, including prompt-length coverage where relevant.",
        "5. Run syntax checks and focused tests. If pytest or another dependency is unavailable, say exactly what blocked it.",
        "6. Re-run the reliability probe across short, medium, long, and very long prompts, with base, teleport, auto_lora, and auto_lora_teleport modes.",
        "7. Re-benchmark latency and verify teleport remains fast. Treat perf=true as reporting-only unless code proves otherwise.",
        "8. Check that quality is not degraded: compare generated outputs or quality metrics where the repo provides tooling, and avoid changing generation semantics unnecessarily.",
        "9. Redeploy/restart carefully. Avoid overlapping inference server processes and verify GPU memory after restart.",
        "10. Retest the deployed public endpoint, not only localhost, before declaring the fix complete.",
        "",
        "Keep iterating until the endpoint is reliable or a concrete external blocker is proven.",
    ])


def format_frontend_event(event: dict, index: int) -> str:
    return "\n".join([
        f"Frontend error event #{index}",
        f"Request ID: {event.get('request_id', '')}",
        f"Timestamp: {event.get('timestamp', '')}",
        f"URL: {event.get('url', '')}",
        f"Referrer: {event.get('referrer', '')}",
        f"Message: {event.get('message', '')}",
        f"Name: {event.get('name', '')}",
        f"Source: {event.get('source', '')}",
        f"Line/Column: {event.get('lineno', '')}:{event.get('colno', '')}",
        f"Component: {event.get('component', '')}",
        f"Fingerprint: {event.get('fingerprint', '')}",
        f"User agent: {event.get('user_agent', '')}",
        f"Language: {event.get('language', '')}",
        f"Timezone: {event.get('timezone', '')}",
        f"Viewport: {event.get('viewport', '')}",
        f"Screen: {event.get('screen', '')}",
        f"Connection: {event.get('connection', '')}",
        f"App version: {event.get('app_version', '')}",
        f"Build ID: {event.get('build_id', '')}",
        "",
        "Stack:",
        str(event.get("stack", "")),
    ])


def build_frontend_prompt(events: list[dict]) -> str:
    event_text = "\n\n---\n\n".join(format_frontend_event(event, idx) for idx, event in enumerate(events, 1))
    return "\n".join([
        "Autofix and harden CuteDSL frontend errors.",
        "",
        "Primary repository: /nvme0n1-disk/code/cutedsl-site",
        "Frontend app: /nvme0n1-disk/code/cutedsl-site/frontend",
        "Go API/static server: /nvme0n1-disk/code/cutedsl-site/server",
        "Frontend error log: /nvme0n1-disk/tmp/cutedsl-frontend-errors.jsonl",
        "Production site to verify: https://cutedsl.cc/",
        "Static asset origin: https://appstatic.app.nz/cutedsl/",
        "",
        "Recent browser error event(s):",
        "",
        event_text,
        "",
        "Required workflow:",
        "1. Reproduce the browser error locally or against production using the logged URL, browser context, and stack/source details.",
        "2. Inspect the relevant React/Next code and Go static/API server code. Identify the root cause before patching.",
        "3. Patch a robust fix without reverting unrelated dirty work.",
        "4. Add focused frontend or server tests for the failure mode. Include browser/environment edge cases when relevant.",
        "5. Run type checks/build/lint or the closest focused checks available in this repo. State exact blockers if dependencies or services are unavailable.",
        "6. Verify the client-side error reporter still records real errors and does not send non-error logs.",
        "7. Rebuild and redeploy carefully if the fix affects production assets or server behavior.",
        "8. Retest the deployed production URL and confirm the error no longer appears in the frontend error log.",
        "",
        "Keep iterating until the frontend error is fixed or a concrete external blocker is proven.",
    ])


def build_prompt(events: list[dict], kind: str) -> str:
    if kind == "frontend":
        return build_frontend_prompt(events)
    return build_inference_prompt(events)


def run_autofix(command: str, events: list[dict], dry_run: bool, kind: str) -> int:
    prompt = build_prompt(events, kind)
    if dry_run:
        print(prompt)
        return 0
    if not command:
        print("CODEXEXEC_CMD is not set; cannot launch autofix command", flush=True)
        return 2
    proc = subprocess.run(
        shlex.split(command),
        input=prompt,
        text=True,
        timeout=None,
        check=False,
    )
    return proc.returncode


def process_new_events(
    error_log: Path,
    state_path: Path,
    last_run_path: Path,
    command: str,
    dry_run: bool,
    cooldown_seconds: int,
    max_events: int,
    kind: str,
) -> int:
    offset = load_offset(state_path)
    if not error_log.exists():
        return 0
    events: list[dict] = []
    with error_log.open("r", encoding="utf-8") as f:
        f.seek(offset)
        while True:
            line = f.readline()
            if not line:
                break
            offset = f.tell()
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if kind == "frontend":
                if event.get("level", "error") != "error":
                    continue
            else:
                if not is_actionable_inference_event(event):
                    continue
            events.append(event)
    save_offset(state_path, offset)
    if not events:
        return 0

    if max_events > 0 and len(events) > max_events:
        events = events[-max_events:]

    now = time.time()
    last_run = load_timestamp(last_run_path)
    remaining = int(cooldown_seconds - (now - last_run))
    if remaining > 0:
        print(f"Autofix cooldown active; skipped {len(events)} new 5xx event(s), {remaining}s remaining", flush=True)
        return 0

    if not dry_run:
        save_timestamp(last_run_path, now)
    return run_autofix(command, events, dry_run, kind)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--error-log", default=os.getenv("ERROR_LOG_PATH", DEFAULT_ERROR_LOG))
    parser.add_argument("--state", default=DEFAULT_STATE)
    parser.add_argument("--last-run-state", default=DEFAULT_LAST_RUN)
    parser.add_argument("--command", default=os.getenv("CODEXEXEC_CMD", ""))
    parser.add_argument("--cooldown-seconds", type=int, default=int(os.getenv("CODEXEXEC_COOLDOWN_SECONDS", DEFAULT_COOLDOWN_SECONDS)))
    parser.add_argument("--max-events", type=int, default=8)
    parser.add_argument("--kind", choices=("inference", "frontend"), default="inference")
    parser.add_argument("--interval", type=float, default=10.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    error_log = Path(args.error_log)
    state = Path(args.state)
    last_run_state = Path(args.last_run_state)
    while True:
        code = process_new_events(
            error_log,
            state,
            last_run_state,
            args.command,
            args.dry_run,
            args.cooldown_seconds,
            args.max_events,
            args.kind,
        )
        if args.once:
            return code
        if code not in (0,):
            return code
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
