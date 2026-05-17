#!/usr/bin/env python3
"""Probe Z-Image upload reliability across prompt lengths and feature modes."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PROMPTS = [
    ("short", "pretty girl portrait"),
    ("medium", "cinematic watercolor fox in a misty forest with soft rim light and coherent detail"),
    ("long", " ".join(["clean detailed product photo of a futuristic smartphone on a white seamless background"] * 12)),
    ("very_long", " ".join(["high quality coherent fantasy landscape with mountains, river, castle, atmospheric light"] * 28)),
]

MODES = [
    ("base", False, False),
    ("teleport", False, True),
    ("auto_lora", True, False),
    ("auto_lora_teleport", True, True),
]


def now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def request_json(url: str, timeout: float) -> tuple[int, dict | str, float]:
    started = time.perf_counter()
    req = Request(url, headers={"accept": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                payload: dict | str = json.loads(body)
            except json.JSONDecodeError:
                payload = body
            return resp.status, payload, time.perf_counter() - started
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = body
        return e.code, payload, time.perf_counter() - started
    except URLError as e:
        return 0, repr(e), time.perf_counter() - started


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8100")
    parser.add_argument("--secret", default="cutedsl2024")
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--attempts", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--output-dir", default="/nvme0n1-disk/tmp/zimage-reliability")
    parser.add_argument("--no-secret", action="store_true", help="omit secret for public-edge checks")
    args = parser.parse_args()

    stamp = now_slug()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    endpoint = f"{args.base_url.rstrip('/')}/create_and_upload_image"

    for attempt in range(args.attempts):
        for prompt_label, prompt in PROMPTS:
            for mode, auto_lora, teleport in MODES:
                save_path = f"reliability/{stamp}_{attempt}_{prompt_label}_{mode}.webp"
                params = {
                    "prompt": prompt,
                    "width": args.width,
                    "height": args.height,
                    "model": "zimage-turbo",
                    "auto_lora": str(auto_lora).lower(),
                    "teleport": str(teleport).lower(),
                    "perf": "true",
                    "save_path": save_path,
                }
                if not args.no_secret:
                    params["secret"] = args.secret

                status, payload, wall_s = request_json(f"{endpoint}?{urlencode(params)}", args.timeout)
                perf = payload.get("perf", {}) if isinstance(payload, dict) else {}
                row = {
                    "attempt": attempt,
                    "prompt_label": prompt_label,
                    "prompt_len": len(prompt),
                    "prompt_words": len(prompt.split()),
                    "mode": mode,
                    "auto_lora": auto_lora,
                    "teleport": teleport,
                    "status": status,
                    "ok": 200 <= status < 300,
                    "wall_s": round(wall_s, 3),
                    "server_ms": perf.get("inference_time_ms"),
                    "upload_ms": perf.get("upload_time_ms"),
                    "teleport_method": perf.get("teleport_method"),
                    "teleport_cache_hit": perf.get("teleport_cache_hit"),
                    "lora": perf.get("lora"),
                    "path": payload.get("path") if isinstance(payload, dict) else "",
                    "error": payload if status < 200 or status >= 300 else "",
                }
                rows.append(row)
                print(json.dumps(row, sort_keys=True))

    report = {
        "timestamp": stamp,
        "base_url": args.base_url,
        "width": args.width,
        "height": args.height,
        "attempts": args.attempts,
        "rows": rows,
        "failures": [row for row in rows if not row["ok"]],
    }
    json_path = output_dir / f"zimage_reliability_{stamp}.json"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True))
    print(json_path)
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
