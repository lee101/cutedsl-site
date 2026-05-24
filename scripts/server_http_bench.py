#!/usr/bin/env python3
"""Small HTTP latency bench for live CuteDSL endpoints.

Uses only the Python standard library so it works on fresh hosts without wrk,
oha, autocannon, or npm installs.

Usage:
    python scripts/server_http_bench.py https://cutedsl.cc --requests 100 --concurrency 8
    python scripts/server_http_bench.py http://127.0.0.1:8095 --paths /api/health /api/images/count
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_PATHS = [
    "/api/health",
    "/api/pricing",
    "/api/images/count",
    "/api/images?page=1&per_page=72&skip_total=true",
    "/api/search?q=fairy&top_k=24",
]


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, round((pct / 100) * (len(ordered) - 1)))
    return ordered[idx]


def fetch(url: str, timeout: float) -> tuple[int, float, int]:
    start = time.perf_counter()
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 CuteDSLPerfBench/1.0",
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return resp.status, (time.perf_counter() - start) * 1000, len(body)
    except urllib.error.HTTPError as exc:
        body = exc.read()
        return exc.code, (time.perf_counter() - start) * 1000, len(body)


def bench_url(url: str, requests: int, concurrency: int, timeout: float) -> dict:
    latencies: list[float] = []
    statuses: dict[int, int] = {}
    bytes_total = 0
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(fetch, url, timeout) for _ in range(requests)]
        for fut in concurrent.futures.as_completed(futures):
            status, latency_ms, size = fut.result()
            latencies.append(latency_ms)
            statuses[status] = statuses.get(status, 0) + 1
            bytes_total += size
    elapsed = time.perf_counter() - started
    return {
        "url": url,
        "requests": requests,
        "concurrency": concurrency,
        "rps": requests / elapsed if elapsed else 0,
        "avg_ms": statistics.mean(latencies) if latencies else 0,
        "p50_ms": percentile(latencies, 50),
        "p95_ms": percentile(latencies, 95),
        "p99_ms": percentile(latencies, 99),
        "max_ms": max(latencies) if latencies else 0,
        "statuses": statuses,
        "bytes": bytes_total,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark CuteDSL HTTP endpoints.")
    parser.add_argument("base", nargs="?", default="https://cutedsl.cc")
    parser.add_argument("--paths", nargs="+", default=DEFAULT_PATHS)
    parser.add_argument("--requests", type=int, default=40)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=15)
    args = parser.parse_args()

    base = args.base.rstrip("/")
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = Path(__file__).parent.parent / "screenshots" / ts / "server-bench"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    print(f"[server-bench] base={base} requests={args.requests} concurrency={args.concurrency}")
    for path in args.paths:
        url = base + (path if path.startswith("/") else f"/{path}")
        row = bench_url(url, args.requests, args.concurrency, args.timeout)
        rows.append(row)
        print(
            f"  {path}: rps={row['rps']:.1f} avg={row['avg_ms']:.1f}ms "
            f"p95={row['p95_ms']:.1f}ms p99={row['p99_ms']:.1f}ms status={row['statuses']}"
        )
        if any(status >= 400 for status in row["statuses"]):
            print(f"    warning: non-2xx/3xx responses mean this row is measuring rejection behavior")

    (out_dir / "results.json").write_text(json.dumps(rows, indent=2) + "\n")
    lines = [
        "# Server HTTP Bench",
        f"base: `{base}`",
        f"timestamp: `{ts}`",
        "",
        "| path | rps | avg ms | p50 ms | p95 ms | p99 ms | max ms | statuses |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        path = row["url"].replace(base, "") or "/"
        lines.append(
            f"| `{path}` | {row['rps']:.1f} | {row['avg_ms']:.1f} | {row['p50_ms']:.1f} "
            f"| {row['p95_ms']:.1f} | {row['p99_ms']:.1f} | {row['max_ms']:.1f} | `{row['statuses']}` |"
        )
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n")
    print(f"[server-bench] summary -> {out_dir / 'summary.md'}")


if __name__ == "__main__":
    main()
