#!/usr/bin/env python3
"""Unified production monitor and guarded Codex auto-repair dispatcher.

One invocation checks the hydrated frontend, browser-reported errors, Go/API
health and logs, inference readiness/errors, and (when due) a real production
image generation that must become retrievable and searchable in the gallery.
Systemd runs this as a oneshot timer; a process lock also protects manual runs.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import fcntl
import hashlib
import json
import logging
import io
import os
import re
import shlex
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        return


load_dotenv(REPO_DIR / ".env")
load_dotenv(SCRIPT_DIR / ".env")

LOG_DIR = Path(os.environ.get("CUTEDSL_MONITOR_LOG_DIR", SCRIPT_DIR / "logs"))
STATE_DIR = Path(os.environ.get("CUTEDSL_MONITOR_STATE_DIR", SCRIPT_DIR / "state"))
LOCK_DIR = Path(os.environ.get("CUTEDSL_MONITOR_LOCK_DIR", "/tmp/cutedsl-monitor"))
BROWSER_TMP_DIR = Path(os.environ.get("CUTEDSL_MONITOR_BROWSER_TMP_DIR", STATE_DIR / "browser-tmp"))
for directory in (LOG_DIR, STATE_DIR, LOCK_DIR, BROWSER_TMP_DIR):
    directory.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=os.environ.get("CUTEDSL_MONITOR_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_DIR / "monitor.log")],
)
logger = logging.getLogger("cutedsl-monitor")

STATE_FILE = STATE_DIR / "monitor_state.json"
FRONTEND_ERROR_LOG = Path(os.environ.get(
    "FRONTEND_ERROR_LOG_PATH", "/nvme0n1-disk/tmp/cutedsl-frontend-errors.jsonl"
))
INFERENCE_ERROR_LOG = Path(os.environ.get(
    "ERROR_LOG_PATH", "/nvme0n1-disk/tmp/cutedsl-inference-errors.jsonl"
))


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Incident:
    category: str
    source: str
    summary: str
    details: list[str]
    fingerprint: str
    occurrences: int = 1
    critical: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class State:
    def __init__(self, path: Path = STATE_FILE):
        self.path = path
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.data = loaded if isinstance(loaded, dict) else {}
        except (OSError, json.JSONDecodeError):
            self.data = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)


@contextlib.contextmanager
def exclusive_lock(path: Path) -> Iterator[bool]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        yield True
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()


def normalized(text: str) -> str:
    text = text.lower()
    text = re.sub(r"https?://[^\s]+", "<url>", text)
    text = re.sub(r"\b[0-9a-f]{8,}\b", "<hex>", text)
    text = re.sub(r"\b\d+\b", "<n>", text)
    return re.sub(r"\s+", " ", text).strip()[:500]


def fingerprint(*parts: str) -> str:
    material = "|".join(normalized(part) for part in parts)
    return hashlib.sha256(material.encode()).hexdigest()[:24]


# Browser telemetry is unauthenticated, so any field can be forged by anyone
# who can reach /api/frontend-error. Reports and logs render it as single-line
# printable data so a crafted message cannot fake a new report section or
# inject terminal escapes into operator-facing output.
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def scrub_telemetry(value: Any, limit: int = 2000) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(value)
    text = CONTROL_CHARS_RE.sub("", text)
    return " ".join(text.split())[:limit]


def tail_jsonl(path: Path, state: State, key: str) -> list[dict[str, Any]]:
    offsets = state.data.setdefault("offsets", {})
    if not path.exists():
        return []
    try:
        size = path.stat().st_size
        if key not in offsets:
            # A newly installed monitor establishes a baseline at EOF instead
            # of dispatching repairs for months-old, already-handled history.
            offset = 0 if os.environ.get("CUTEDSL_MONITOR_REPLAY_EXISTING") == "1" else size
            offsets[key] = offset
        else:
            offset = int(offsets.get(key, 0))
    except (OSError, TypeError, ValueError):
        return []
    if offset < 0 or offset > size:
        offset = 0
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(offset)
            for line in handle:
                try:
                    value = json.loads(line)
                    if isinstance(value, dict):
                        rows.append(value)
                except json.JSONDecodeError:
                    continue
            offsets[key] = handle.tell()
    except OSError:
        return []
    return rows


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 20,
) -> tuple[int, Any, dict[str, str]]:
    body = json.dumps(payload).encode() if payload is not None else None
    request_headers = {"User-Agent": "cutedsl-production-monitor/1.0", **(headers or {})}
    if body is not None:
        request_headers.setdefault("Content-Type", "application/json")
    request = Request(url, data=body, method=method, headers=request_headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            response_headers = {key.lower(): value for key, value in response.headers.items()}
            try:
                data: Any = json.loads(raw)
            except json.JSONDecodeError:
                data = raw.decode(errors="replace")[:2000]
            return response.status, data, response_headers
    except HTTPError as error:
        raw = error.read()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = raw.decode(errors="replace")[:2000]
        return error.code, data, {key.lower(): value for key, value in error.headers.items()}


def request_bytes(url: str, timeout: int = 30) -> tuple[int, bytes, str]:
    request = Request(url, headers={"User-Agent": "cutedsl-production-monitor/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, response.read(4096), response.headers.get("Content-Type", "")
    except HTTPError as error:
        return error.code, error.read(4096), error.headers.get("Content-Type", "")


def browser_failure_classification(scan: dict[str, Any]) -> tuple[str, str]:
    """Keep CDN/origin failures out of the frontend regression bucket."""
    status = int(scan.get("status") or 0)
    if status in {521, 522, 523, 524, 525, 526, 530}:
        return "backend", f"Public origin connectivity failed on {scan.get('path')}"
    return "frontend", f"Hydrated frontend check failed on {scan.get('path')}"


CF_ORIGIN_CONNECTIVITY_STATUSES = {521, 522, 523, 524, 525, 526, 530}
MONITOR_CHECK_VALUE = re.compile(r"([?&]monitor_check=)\d+")


def browser_incident_from_scan(scan: dict[str, Any]) -> Incident:
    errors = scan.get("errors") or []
    detail_lines = [json.dumps(error, sort_keys=True) for error in errors[:20]]
    if scan.get("navigationError"):
        detail_lines.append(f"navigation: {scan['navigationError']}")
    detail_lines.append(f"status={scan.get('status')} title={scan.get('title')!r}")
    category, summary = browser_failure_classification(scan)
    status = int(scan.get("status") or 0)
    # Cloudflare connectivity errors can be isolated edge-to-origin failures.
    # The independent public health probe retries and remains immediately
    # critical, while browser-only 52x failures must recur across monitor runs.
    # Strip the per-scan cache buster so those recurrences share a fingerprint.
    stable_details = MONITOR_CHECK_VALUE.sub(r"\1<timestamp>", "\n".join(detail_lines))
    return Incident(
        category=category,
        source="playwright",
        summary=summary,
        details=detail_lines,
        fingerprint=fingerprint("playwright", str(scan.get("path")), stable_details),
        critical=bool(
            scan.get("applicationError")
            or (status >= 500 and status not in CF_ORIGIN_CONNECTIVITY_STATUSES)
        ),
        metadata={"path": scan.get("path"), "viewport": scan.get("viewport")},
    )


def browser_incidents() -> list[Incident]:
    command = ["node", str(SCRIPT_DIR / "check_frontend.mjs")]
    # Playwright and Chromium allocate profiles, shared-memory files, and
    # artifacts below TMPDIR. Keep the production check operational when the
    # host's shared /tmp filesystem is full, and contain its temporary files in
    # monitor-owned state that is removed by Playwright on a clean shutdown.
    browser_env = os.environ.copy()
    browser_env["TMPDIR"] = str(BROWSER_TMP_DIR)
    try:
        process = subprocess.run(
            command,
            cwd=REPO_DIR,
            env=browser_env,
            capture_output=True,
            text=True,
            timeout=240,
            check=False,
        )
        report = json.loads(process.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as error:
        detail = str(error)
        return [Incident(
            category="frontend",
            source="browser_scanner",
            summary="Production browser scanner failed",
            details=[detail],
            fingerprint=fingerprint("browser_scanner", detail),
        )]

    latest = LOG_DIR / "frontend_latest.json"
    latest.write_text(json.dumps(report, indent=2), encoding="utf-8")
    incidents: list[Incident] = []
    if report.get("scannerError"):
        detail = str(report["scannerError"])
        incidents.append(Incident(
            category="frontend", source="browser_scanner",
            summary="Playwright could not scan production", details=[detail],
            fingerprint=fingerprint("browser_scanner", detail),
        ))
    for scan in report.get("scans", []):
        if scan.get("ok"):
            continue
        incidents.append(browser_incident_from_scan(scan))
    return incidents


FRONTEND_NOISE = [
    re.compile(
        r"^Object Not Found Matching Id:\d+,\s*"
        r"MethodName:(?:update,\s*ParamCount:4|simulateEvent,\s*ParamCount:\d+)$"
    ),
    re.compile(r"^test error$", re.I),
]


def frontend_log_incidents(state: State) -> list[Incident]:
    rows = tail_jsonl(FRONTEND_ERROR_LOG, state, "frontend_errors")
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        message = scrub_telemetry(row.get("message", "")).strip()
        if not message or row.get("level", "error") != "error":
            continue
        if any(pattern.search(message) for pattern in FRONTEND_NOISE):
            continue
        fp = fingerprint("frontend_log", message, scrub_telemetry(row.get("source", ""), 500), scrub_telemetry(row.get("stack", ""), 2000))
        groups.setdefault(fp, []).append(row)

    incidents: list[Incident] = []
    for fp, events in groups.items():
        event = events[-1]
        details = [
            f"occurrences={len(events)}",
            f"url={scrub_telemetry(event.get('url', ''))}",
            f"message={scrub_telemetry(event.get('message', ''))}",
            f"source={scrub_telemetry(event.get('source', ''), 500)}",
            f"fingerprint={scrub_telemetry(event.get('fingerprint', ''), 200)}",
            f"user_agent={scrub_telemetry(event.get('user_agent', ''), 500)}",
            f"stack={scrub_telemetry(event.get('stack', ''), 4000)}",
        ]
        incidents.append(Incident(
            category="frontend", source="frontend_error_log",
            summary=f"Browser-reported error: {scrub_telemetry(event.get('message', ''), 500)}",
            details=details, fingerprint=fp, occurrences=len(events),
        ))
    return incidents


def inference_health_ok(status: int, data: Any) -> bool:
    """Accept a ready lazy-loaded image worker without forcing GPU residency."""
    if status != 200 or not isinstance(data, dict) or data.get("status") != "ok":
        return False
    if (data.get("cuda") or {}).get("healthy") is not True:
        return False
    models = data.get("models") or {}
    return models.get("zimage") is True or models.get("zimage_enabled") is True


def request_health_json(url: str, *, timeout: int = 20) -> tuple[int, Any, dict[str, str]]:
    return request_json(url, timeout=timeout)


def health_failure(name: str, url: str) -> str | None:
    """Retry every failure (transport, 5xx, status "starting") with linear backoff;
    deploy restarts recover within seconds. Returns the last failure or None."""
    attempts = max(1, env_int("CUTEDSL_HEALTH_REQUEST_ATTEMPTS", 3))
    retry_seconds = max(0, env_int("CUTEDSL_HEALTH_RETRY_SECONDS", 10))
    detail = None
    for attempt in range(1, attempts + 1):
        try:
            status, data, _ = request_health_json(url, timeout=20)
            ok = status == 200
            if name.endswith("go"):
                ok = ok and isinstance(data, dict) and data.get("status") == "ok"
            else:
                ok = inference_health_ok(status, data)
            if ok:
                return None
            detail = f"{url} status={status} body={json.dumps(data)[:3000]}"
        except (URLError, TimeoutError, OSError, ValueError) as error:
            detail = f"{url} request failed: {error}"
        if attempt < attempts:
            logger.warning("health %s failed (attempt %d/%d): %s", name, attempt, attempts, detail[:300])
            if retry_seconds:
                time.sleep(retry_seconds * attempt)
    return detail


def service_uptime(service: str) -> float | None:
    try:
        value = subprocess.run(["systemctl", "show", service, "-p", "ActiveEnterTimestampMonotonic", "--value"],
                               capture_output=True, text=True, timeout=10, check=False).stdout.strip()
        started = int(value) / 1e6
        return float(Path("/proc/uptime").read_text().split()[0]) - started if started else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def restart_grace(state: State) -> bool:
    """Skip Go health for one scan after a restart; a crash loop is never excused twice."""
    uptime = service_uptime(os.environ.get("CUTEDSL_BACKEND_SERVICE", "cutedsl.service"))
    young = uptime is not None and uptime < env_int("CUTEDSL_RESTART_GRACE_SECONDS", 120) and not state.data.get("grace_used")
    state.data["grace_used"] = young
    if young:
        logger.info("backend uptime %.0fs; Go health deferred one scan", uptime)
    return young


def health_incidents(state: State | None = None) -> list[Incident]:
    checks = [
        ("public_go", os.environ.get("CUTEDSL_PUBLIC_HEALTH_URL", "https://cutedsl.cc/api/health")),
        ("local_go", os.environ.get("CUTEDSL_ORIGIN_HEALTH_URL", "http://127.0.0.1:8095/api/health")),
        ("inference", os.environ.get("CUTEDSL_INFERENCE_HEALTH_URL", "http://127.0.0.1:8100/healthz")),
    ]
    if state is not None and restart_grace(state):
        checks = [check for check in checks if not check[0].endswith("go")]
    incidents: list[Incident] = []
    for name, url in checks:
        detail = health_failure(name, url)
        if detail is None:
            continue
        # Stable per-endpoint fingerprint; must persist across scans before dispatch.
        incidents.append(Incident(
            category="inference" if name == "inference" else "backend",
            source=f"health:{name}",
            summary=f"{name} health check failed",
            details=[detail],
            fingerprint=fingerprint("health", name),
        ))
    return incidents


JOURNAL_KEEP = re.compile(
    r"panic:|runtime error:|fatal error:|Backend proxy error|frontend error log .*failed|"
    r"failed to (?:start|listen|connect|query|insert)|HTTP 5\d\d|status=5\d\d",
    re.I,
)
JOURNAL_DROP = re.compile(
    r"context canceled|deadline exceeded|broken pipe|client disconnected|connection reset|i/o timeout|"
    r"no such host|TLS handshake timeout|server closed|shutting down|database (?:is )?starting|"
    r"\b(?:HTTP |status=)(?:502|503|504)\b|\b429\b|rate.?limit|upstream",
    re.I,
)


def journal_incidents(state: State) -> list[Incident]:
    now = time.time()
    since = float(state.data.get("journal_since", now - env_int("CUTEDSL_JOURNAL_LOOKBACK_SECONDS", 600)))
    state.data["journal_since"] = now
    service = os.environ.get("CUTEDSL_BACKEND_SERVICE", "cutedsl.service")
    try:
        process = subprocess.run(
            ["journalctl", "-u", service, "--since", f"@{since:.0f}", "--no-pager", "-o", "cat"],
            capture_output=True, text=True, timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if process.returncode != 0:
        logger.warning("journal scan unavailable: %s", process.stderr.strip()[:500])
        return []
    lines = [line.strip() for line in process.stdout.splitlines() if JOURNAL_KEEP.search(line) and not JOURNAL_DROP.search(line)]
    if not lines:
        return []
    groups: dict[str, list[str]] = {}
    for line in lines:
        fp = fingerprint("backend_journal", line)
        groups.setdefault(fp, []).append(line)
    return [Incident(
        category="backend", source="systemd_journal",
        summary="Backend error found in cutedsl.service journal",
        details=values[-20:], fingerprint=fp, occurrences=len(values),
        critical=any("panic" in value.lower() or "fatal" in value.lower() for value in values),
    ) for fp, values in groups.items()]


def inference_log_incidents(state: State) -> list[Incident]:
    rows = tail_jsonl(INFERENCE_ERROR_LOG, state, "inference_errors")
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        try:
            status = int(row.get("status_code", 0))
        except (TypeError, ValueError):
            continue
        path = str(row.get("path", ""))
        error = str(row.get("error", ""))
        if status < 500:
            continue
        if path in {"/forecast", "/forecast_batch"} and error.lower().strip() == "chronos2 disabled":
            continue
        if status in (502, 503, 504) or JOURNAL_DROP.search(error):
            continue
        fp = fingerprint("inference_log", path, error, str(row.get("error_type", "")))
        groups.setdefault(fp, []).append(row)
    incidents: list[Incident] = []
    for fp, events in groups.items():
        event = events[-1]
        incidents.append(Incident(
            category="inference", source="inference_error_log",
            summary=f"Inference {event.get('status_code')} on {event.get('path')}",
            details=[json.dumps(event, sort_keys=True)[:8000]], fingerprint=fp,
            occurrences=len(events),
            critical=bool(re.search(r"panic|Traceback|CUDA error|illegal memory", json.dumps(event))),
        ))
    return incidents


def synthetic_due(state: State, force: bool) -> bool:
    if force:
        return True
    now = time.time()
    interval = env_int("CUTEDSL_SYNTHETIC_INTERVAL_SECONDS", 21600)
    retry = env_int("CUTEDSL_SYNTHETIC_RETRY_SECONDS", 900)
    last_ok = float(state.data.get("synthetic_last_ok", 0))
    last_attempt = float(state.data.get("synthetic_last_attempt", 0))
    return now - last_ok >= interval and now - last_attempt >= retry


def persist_canary_result(data: dict[str, Any], prompt: str, api_key: str) -> tuple[dict[str, Any], str]:
    """Persist a generated image when the deployed API only returns image bytes.

    Newer Go builds persist zimage responses themselves. The fallback keeps the
    canary useful across older/rollback binaries while still exercising the
    real inference, production DB index, image origin and gallery API.
    """
    saved = data.get("saved_image")
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    if not isinstance(saved, dict):
        saved = result.get("gallery_image") if isinstance(result, dict) else None
    if isinstance(saved, dict) and saved.get("id") and saved.get("file_path"):
        return saved, "api"

    encoded = result.get("image_base64") if isinstance(result, dict) else ""
    if not isinstance(encoded, str) or not encoded:
        raise RuntimeError("generation response contained neither a saved image nor image bytes")
    try:
        raw = base64.b64decode(encoded, validate=True)
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as image:
            image.verify()
            width, height = image.size
    except Exception as error:
        raise RuntimeError(f"generation returned invalid image bytes: {error}") from error

    image_id = str(uuid.uuid4())
    filename = f"{hashlib.sha1(prompt.encode()).hexdigest()[:16]}_{image_id[:8]}.webp"
    relative = f"originals/{filename}"
    images_dir = Path(os.environ.get("CUTEDSL_IMAGES_DIR", "/sdb-disk/cutedsl-images"))
    destination = images_dir / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(raw)

    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn:
        destination.unlink(missing_ok=True)
        raise RuntimeError("DATABASE_URL is unavailable for canary gallery indexing")
    try:
        import psycopg2
        connection = psycopg2.connect(dsn)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT id FROM users WHERE api_key = %s", (api_key,))
                row = cursor.fetchone()
                user_id = row[0] if row else ""
                cursor.execute(
                    """INSERT INTO generated_images
                       (id, prompt, width, height, file_path, thumb_path, med_path,
                        file_size, model, seed, steps, created_by_user_id, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'zimage', %s, %s, %s, NOW())""",
                    (
                        image_id, prompt, int(result.get("width") or width), int(result.get("height") or height),
                        relative, relative, relative, len(raw), int(result.get("seed") or 0), 8, user_id,
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
    except Exception as error:
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"failed to index canary image in production DB: {error}") from error

    return {
        "id": image_id, "prompt": prompt, "width": width, "height": height,
        "file_path": relative, "thumb_path": relative, "med_path": relative,
    }, "monitor"


def synthetic_incidents(state: State, force: bool = False) -> list[Incident]:
    if not synthetic_due(state, force):
        return []
    state.data["synthetic_last_attempt"] = time.time()
    api_key = os.environ.get("CUTEDSL_MONITOR_API_KEY", "").strip()
    if not api_key:
        logger.warning("real image canary skipped: CUTEDSL_MONITOR_API_KEY is not configured")
        return []

    marker = f"cutedslcanary{int(time.time())}{uuid.uuid4().hex[:6]}"
    prompt = (
        "A cheerful pink maintenance robot tending a glowing AI art studio, "
        f"soft cinematic light, polished illustration, production marker {marker}"
    )
    endpoint = os.environ.get("CUTEDSL_SYNTHETIC_SERVICE_URL", "https://cutedsl.cc/api/service")
    detail: list[str] = [f"endpoint={endpoint}", f"marker={marker}"]
    report: dict[str, Any] = {"checked_at": utc_now(), "marker": marker, "endpoint": endpoint}
    try:
        started = time.time()
        status, data, _ = request_json(
            endpoint,
            method="POST",
            payload={
                "service": "zimage", "prompt": prompt, "width": 512, "height": 512,
                "num_steps": 8, "seed": int(time.time()) % 2_000_000_000, "auto_lora": False,
            },
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=420,
        )
        report["generation_status"] = status
        report["generation_seconds"] = round(time.time() - started, 3)
        if status != 200 or not isinstance(data, dict):
            raise RuntimeError(f"generation status={status} body={json.dumps(data)[:1000]}")
        saved, persistence_mode = persist_canary_result(data, prompt, api_key)
        image_id = str(saved["id"])
        file_path = str(saved["file_path"])
        report.update({"image_id": image_id, "file_path": file_path, "persistence_mode": persistence_mode})

        image_url = "https://cutedsl.cc/images/" + quote(file_path, safe="/")
        image_status, prefix, content_type = request_bytes(image_url, timeout=30)
        report.update({"image_url": image_url, "image_status": image_status, "image_content_type": content_type})
        if image_status != 200 or not content_type.startswith("image/") or len(prefix) < 100:
            raise RuntimeError(f"persisted image unavailable: status={image_status} type={content_type}")

        indexed = False
        # Verify the persisted row by its indexed primary key while also
        # checking that the unique marker survived in the saved prompt. A broad
        # ILIKE scan is unnecessary here and can time out during shared-DB I/O
        # pressure even though generation and persistence succeeded.
        search_url = (
            "https://cutedsl.cc/api/images?id=" + quote(image_id)
            + "&q=" + quote(marker) + "&page=1&per_page=10"
        )
        for _ in range(6):
            search_status, search_data, _ = request_json(search_url, timeout=30)
            images = search_data.get("images", []) if isinstance(search_data, dict) else []
            if search_status == 200 and any(str(image.get("id")) == image_id for image in images if isinstance(image, dict)):
                indexed = True
                break
            time.sleep(2)
        report.update({"search_url": search_url, "indexed": indexed})
        if not indexed:
            raise RuntimeError("generated image was not returned by the production gallery search index")

        state.data["synthetic_last_ok"] = time.time()
        state.data["synthetic_last_image_id"] = image_id
        report["ok"] = True
        (LOG_DIR / f"synthetic_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        logger.info("real image canary passed in %.2fs: image=%s indexed=true", report["generation_seconds"], image_id)
        return []
    except (URLError, TimeoutError, OSError, ValueError, RuntimeError) as error:
        report.update({"ok": False, "error": str(error)})
        detail.append(str(error))
        (LOG_DIR / f"synthetic_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        return [Incident(
            category="synthetic", source="real_image_canary",
            summary="Real production image generation/indexing canary failed",
            details=detail, fingerprint=fingerprint("synthetic_image", str(error)), critical=True,
            metadata={"marker": marker},
        )]


def run_checks(state: State, *, force_synthetic: bool = False, skip_synthetic: bool = False,
               grace: bool = False) -> list[Incident]:
    incidents: list[Incident] = []
    incidents.extend(browser_incidents())
    incidents.extend(frontend_log_incidents(state))
    incidents.extend(health_incidents(state if grace else None))
    incidents.extend(journal_incidents(state))
    incidents.extend(inference_log_incidents(state))
    if not skip_synthetic:
        incidents.extend(synthetic_incidents(state, force=force_synthetic))
    return incidents


def incident_thresholds(state: State, incidents: list[Incident]) -> list[Incident]:
    now = time.time()
    threshold = env_int("CUTEDSL_MONITOR_FAILURE_THRESHOLD", 2)
    reset_after = env_int("CUTEDSL_MONITOR_FAILURE_RESET_SECONDS", 3600)
    dedupe_seconds = env_int("CUTEDSL_MONITOR_DEDUPE_SECONDS", 21600)
    failures = state.data.setdefault("failures", {})
    handled = state.data.setdefault("handled", {})
    eligible: list[Incident] = []
    min_hits = env_int("CUTEDSL_MONITOR_MIN_OCCURRENCES", 3)
    consecutive = env_int("CUTEDSL_MONITOR_CONSECUTIVE_SECONDS", 900)
    for incident in incidents:
        # count = consecutive scans (gap <= consecutive); hits = total occurrences in that window.
        entry = failures.get(incident.fingerprint, {})
        gap = now - float(entry.get("last_seen", 0))
        fresh = gap <= reset_after
        count = (int(entry.get("count", 0)) if gap <= consecutive else 0) + 1
        hits = (int(entry.get("hits", 0)) if fresh else 0) + max(1, incident.occurrences)
        failures[incident.fingerprint] = {
            "count": count, "hits": hits, "last_seen": now, "category": incident.category,
            "summary": incident.summary,
        }
        handled_at = float(handled.get(incident.fingerprint, 0))
        persistent = incident.critical or count >= threshold or hits >= min_hits
        if persistent and now - handled_at >= dedupe_seconds:
            eligible.append(incident)

    prune_before = now - 7 * 86400
    state.data["failures"] = {
        key: value for key, value in failures.items() if float(value.get("last_seen", 0)) >= prune_before
    }
    state.data["handled"] = {key: value for key, value in handled.items() if float(value) >= prune_before}
    return eligible


def reserve_agent_run(state: State, category: str) -> tuple[bool, str]:
    now = time.time()
    global_cooldown = env_int("CUTEDSL_MONITOR_GLOBAL_COOLDOWN_SECONDS", 3600)
    category_cooldown = env_int("CUTEDSL_MONITOR_CATEGORY_COOLDOWN_SECONDS", 10800)
    if now - float(state.data.get("last_agent_at", 0)) < global_cooldown:
        return False, "global cooldown active"
    category_last = state.data.setdefault("category_last_agent", {})
    if now - float(category_last.get(category, 0)) < category_cooldown:
        return False, f"{category} cooldown active"

    maximum = env_int("CUTEDSL_MONITOR_MAX_AGENT_RUNS_PER_DAY", 4)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    budget = state.data.get("agent_budget", {})
    if budget.get("date") != today:
        budget = {"date": today, "count": 0}
    if int(budget.get("count", 0)) >= maximum:
        return False, f"daily agent budget exhausted ({maximum})"
    budget["count"] = int(budget.get("count", 0)) + 1
    state.data["agent_budget"] = budget
    state.data["last_agent_at"] = now
    category_last[category] = now
    return True, "reserved"


def build_agent_prompt(incidents: list[Incident]) -> str:
    evidence = "\n\n---\n\n".join(
        "\n".join([
            f"Category: {incident.category}",
            f"Source: {incident.source}",
            f"Summary: {incident.summary}",
            f"Fingerprint: {incident.fingerprint}",
            "Evidence:",
            *[f"  {line}" for line in incident.details[:40]],
        ]) for incident in incidents[:12]
    )
    return f"""You are the autonomous production debugging and repair agent for CuteDSL.

Repository: /nvme0n1-disk/code/cutedsl-site
Production: https://cutedsl.cc/
Static origin: https://appstatic.app.nz/cutedsl/
Go origin health: http://127.0.0.1:8095/api/health
Inference readiness: http://127.0.0.1:8100/healthz
Frontend telemetry: {FRONTEND_ERROR_LOG}
Inference telemetry: {INFERENCE_ERROR_LOG}

The production monitor observed these debounced incidents:

{evidence}

Required workflow:
1. Inspect CLAUDE.md and the current git status/diff first. The worktree may contain unrelated user work: preserve it exactly and never stash, reset, revert, or mass-format it.
2. Reproduce the incident from the supplied evidence. Inspect the browser console/network with Playwright for frontend failures and the relevant systemd/inference logs for backend failures. Do not guess.
3. Identify the root cause and implement the smallest robust fix. Add a focused regression test for the actual failure mode.
4. Run focused tests plus the appropriate broad gates: Next production build/type validation for frontend changes, `cd server && go test ./...` for Go changes, and focused pytest/reliability checks for inference changes.
5. Deploy the fix. For frontend/static changes use `./deploy.sh`. If the Go binary or a managed backend changes, install/restart only the affected managed service with sudo; never start duplicate ad-hoc servers.
6. After deployment, retest the PUBLIC production URLs in a real headless browser and verify all referenced static assets return JavaScript/CSS rather than cached HTML errors. Check local and public health.
7. For inference/synthetic incidents, perform one real generation through the production service, verify its image URL, and confirm its saved image appears in `/api/images` search.
8. Keep iterating through fix, test, deploy, and post-deploy verification until production is healthy. If an external blocker is proven, document exact evidence and stop safely.

Do not commit, push, open a PR, rotate secrets, or delete production/user data. Do not claim success from a local build alone.
"""


def run_agent(incidents: list[Incident]) -> tuple[int, Path]:
    model = os.environ.get("CUTEDSL_MONITOR_AGENT_MODEL", "gpt-6.1-terra")
    reasoning = os.environ.get("CUTEDSL_MONITOR_AGENT_REASONING", "high")
    timeout = env_int("CUTEDSL_MONITOR_AGENT_TIMEOUT_SECONDS", 10800)
    command = [
        os.environ.get("CUTEDSL_MONITOR_CODEX_BIN", "codex"), "exec",
        "-C", str(REPO_DIR), "-m", model, "-c", f"model_reasoning_effort={reasoning}",
        "-s", "danger-full-access", "--dangerously-bypass-approvals-and-sandbox",
    ]
    for related in (
        "/nvme0n1-disk/code/cutedsl", "/nvme0n1-disk/code/omniserve-native",
        "/nvme0n1-disk/code/text-generator.io", "/nvme0n1-disk/code/netwrck",
    ):
        if Path(related).is_dir():
            command.extend(["--add-dir", related])
    command.append("-")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = LOG_DIR / f"agent_{stamp}.log"
    prompt = build_agent_prompt(incidents)
    logger.warning("launching %s/%s repair agent for %d incident(s): %s", model, reasoning, len(incidents), log_path)
    with log_path.open("w", encoding="utf-8") as log_handle:
        log_handle.write("Command: " + " ".join(shlex.quote(part) for part in command[:-1]) + " -\n\n")
        log_handle.flush()
        try:
            process = subprocess.run(
                command, cwd=REPO_DIR, input=prompt, text=True,
                stdout=log_handle, stderr=subprocess.STDOUT, timeout=timeout, check=False,
            )
            return process.returncode, log_path
        except subprocess.TimeoutExpired:
            log_handle.write(f"\nAgent timed out after {timeout}s\n")
            return 124, log_path
        except OSError as error:
            log_handle.write(f"\nAgent launch failed: {error}\n")
            return 127, log_path


def write_incident_report(incidents: list[Incident], prefix: str = "incidents") -> Path | None:
    if not incidents:
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = LOG_DIR / f"{prefix}_{stamp}.json"
    path.write_text(json.dumps({"captured_at": utc_now(), "incidents": [asdict(item) for item in incidents]}, indent=2), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="CuteDSL production monitor and auto-fixer")
    parser.add_argument("--verify-only", action="store_true", help="run checks but never dispatch an agent")
    parser.add_argument("--dry-run-agent", action="store_true", help="show eligible incidents without launching Codex")
    parser.add_argument("--force-synthetic", action="store_true", help="run a real image/index canary now")
    parser.add_argument("--skip-synthetic", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    with exclusive_lock(LOCK_DIR / "monitor.lock") as acquired:
        if not acquired:
            logger.info("another CuteDSL monitor/repair run is active; exiting cleanly")
            return 0

        state = State()
        logger.info("monitor check starting (verify_only=%s force_synthetic=%s)", args.verify_only, args.force_synthetic)
        incidents = run_checks(
            state, force_synthetic=args.force_synthetic, skip_synthetic=args.skip_synthetic,
            grace=not args.verify_only,
        )
        report_path = write_incident_report(incidents)
        eligible = incident_thresholds(state, incidents)
        state.save()

        if args.json:
            print(json.dumps({
                "checked_at": utc_now(), "incidents": [asdict(item) for item in incidents],
                "eligible": [item.fingerprint for item in eligible], "report": str(report_path or ""),
            }, indent=2))
        if not incidents:
            logger.info("all production checks passed")
            return 0
        logger.warning("detected %d incident(s), %d eligible after debounce/dedupe", len(incidents), len(eligible))
        if args.verify_only or not eligible:
            return 1 if args.verify_only else 0
        if args.dry_run_agent:
            logger.warning("dry-run: would launch repair agent for %s", ", ".join(item.summary for item in eligible))
            return 0

        primary_category = eligible[0].category if len({item.category for item in eligible}) == 1 else "multi"
        reserved, reason = reserve_agent_run(state, primary_category)
        state.save()
        if not reserved:
            logger.info("repair dispatch skipped: %s", reason)
            return 0

        returncode, agent_log = run_agent(eligible)
        logger.info("repair agent finished rc=%d log=%s; running independent post-repair checks", returncode, agent_log)
        force_post_synthetic = any(item.category in {"inference", "synthetic"} for item in eligible)
        post_incidents = run_checks(state, force_synthetic=force_post_synthetic, skip_synthetic=False)
        write_incident_report(post_incidents, prefix="post_repair")

        relevant_categories = {item.category for item in eligible}
        remaining = [item for item in post_incidents if item.category in relevant_categories]
        if returncode == 0 and not remaining:
            handled = state.data.setdefault("handled", {})
            for item in eligible:
                handled[item.fingerprint] = time.time()
            logger.info("post-repair verification passed for %s", ", ".join(sorted(relevant_categories)))
        else:
            logger.error("post-repair verification failed: agent_rc=%d remaining=%d", returncode, len(remaining))
        state.save()
        return 0 if returncode == 0 and not remaining else 1


if __name__ == "__main__":
    raise SystemExit(main())
