#!/usr/bin/env python3
"""Search-engine latency/quality bench for the CuteDSL image search stack.

Exercises the three real search surfaces the /search and /gallery pages hit:
  - /api/search           — semantic prompt search (gobed-ranked prompts)
  - /api/images/semantic  — semantic image search (ranked images)
  - /api/images           — trigram / browse pagination (no-query default)

For each surface it fires a representative query set concurrently and reports
latency percentiles plus a coverage signal (how many queries returned results),
so a regression in either speed or recall shows up. Stdlib-only — runs on a
fresh host with no wrk/oha/npm.

Usage:
    python scripts/search_engine_bench.py https://cutedsl.cc
    python scripts/search_engine_bench.py http://127.0.0.1:8095 --repeats 5 --concurrency 8
    python scripts/search_engine_bench.py --queries fairy "cyberpunk city" "watercolor cat"
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Representative spread: single words, multi-word styles, and long descriptive
# prompts — the kinds of queries the gallery search box actually receives.
DEFAULT_QUERIES = [
    "fairy",
    "dragon",
    "cyberpunk city",
    "watercolor cat",
    "fantasy landscape",
    "anime girl with pink hair",
    "galaxy nebula space art",
    "cozy cottage in the forest at sunset",
    "robot samurai neon",
    "underwater mermaid kingdom",
]


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, round((pct / 100) * (len(ordered) - 1)))
    return ordered[idx]


def fetch(url: str, timeout: float) -> tuple[int, float, int]:
    """Return (status, latency_ms, result_count). result_count is -1 if unknown."""
    start = time.perf_counter()
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 CuteDSLSearchBench/1.0",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        body = exc.read()
        status = exc.code
    except (urllib.error.URLError, TimeoutError) as exc:
        return 0, (time.perf_counter() - start) * 1000, -1
    latency_ms = (time.perf_counter() - start) * 1000
    count = -1
    try:
        data = json.loads(body)
        if isinstance(data, dict):
            for key in ("images", "results"):
                if isinstance(data.get(key), list):
                    count = len(data[key])
                    break
    except (ValueError, TypeError):
        pass
    return status, latency_ms, count


def build_urls(base: str, surface: str, queries: list[str], top_k: int) -> list[str]:
    if surface == "prompt_semantic":
        return [
            f"{base}/api/search?q={urllib.parse.quote(q)}&top_k={top_k}" for q in queries
        ]
    if surface == "image_semantic":
        return [
            f"{base}/api/images/semantic?q={urllib.parse.quote(q)}&top_k={top_k}"
            for q in queries
        ]
    if surface == "browse":
        # No-query browse pagination — what the gallery loads by default.
        return [
            f"{base}/api/images?page={p}&per_page={top_k}&skip_total=true"
            for p in range(1, len(queries) + 1)
        ]
    raise ValueError(surface)


def bench_surface(
    base: str,
    surface: str,
    queries: list[str],
    top_k: int,
    repeats: int,
    concurrency: int,
    timeout: float,
) -> dict:
    urls = build_urls(base, surface, queries, top_k) * repeats
    latencies: list[float] = []
    statuses: dict[int, int] = {}
    counts: list[int] = []
    empty = 0
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(fetch, url, timeout) for url in urls]
        for fut in concurrent.futures.as_completed(futures):
            status, latency_ms, count = fut.result()
            latencies.append(latency_ms)
            statuses[status] = statuses.get(status, 0) + 1
            if count >= 0:
                counts.append(count)
                if count == 0:
                    empty += 1
    elapsed = time.perf_counter() - started
    return {
        "surface": surface,
        "requests": len(urls),
        "concurrency": concurrency,
        "rps": len(urls) / elapsed if elapsed else 0,
        "avg_ms": statistics.mean(latencies) if latencies else 0,
        "p50_ms": percentile(latencies, 50),
        "p95_ms": percentile(latencies, 95),
        "p99_ms": percentile(latencies, 99),
        "max_ms": max(latencies) if latencies else 0,
        "avg_results": statistics.mean(counts) if counts else 0,
        "empty_responses": empty,
        "statuses": statuses,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark the CuteDSL image search engine.")
    parser.add_argument("base", nargs="?", default="https://cutedsl.cc")
    parser.add_argument("--queries", nargs="+", default=DEFAULT_QUERIES)
    parser.add_argument("--top-k", type=int, default=48)
    parser.add_argument("--repeats", type=int, default=5,
                        help="How many times to replay the query set per surface.")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument(
        "--surfaces",
        nargs="+",
        default=["prompt_semantic", "image_semantic", "browse"],
        choices=["prompt_semantic", "image_semantic", "browse"],
    )
    args = parser.parse_args()

    base = args.base.rstrip("/")
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = Path(__file__).parent.parent / "screenshots" / ts / "search-bench"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"[search-bench] base={base} queries={len(args.queries)} "
        f"repeats={args.repeats} concurrency={args.concurrency} top_k={args.top_k}"
    )
    rows = []
    for surface in args.surfaces:
        row = bench_surface(
            base, surface, args.queries, args.top_k,
            args.repeats, args.concurrency, args.timeout,
        )
        rows.append(row)
        print(
            f"  {surface:16s}: rps={row['rps']:.1f} avg={row['avg_ms']:.1f}ms "
            f"p50={row['p50_ms']:.1f} p95={row['p95_ms']:.1f}ms p99={row['p99_ms']:.1f}ms "
            f"avg_results={row['avg_results']:.0f} empty={row['empty_responses']} "
            f"status={row['statuses']}"
        )
        if any(s == 0 or s >= 400 for s in row["statuses"]):
            print("    warning: errors/timeouts present — latency is partly measuring failures")
        if row["empty_responses"]:
            print(f"    warning: {row['empty_responses']} responses returned 0 results (recall gap?)")

    (out_dir / "results.json").write_text(json.dumps(rows, indent=2) + "\n")
    lines = [
        "# Search Engine Bench",
        f"base: `{base}`",
        f"timestamp: `{ts}`",
        f"queries: {len(args.queries)} × {args.repeats} repeats, top_k={args.top_k}, concurrency={args.concurrency}",
        "",
        "| surface | rps | avg ms | p50 ms | p95 ms | p99 ms | max ms | avg results | empty | statuses |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| `{row['surface']}` | {row['rps']:.1f} | {row['avg_ms']:.1f} | {row['p50_ms']:.1f} "
            f"| {row['p95_ms']:.1f} | {row['p99_ms']:.1f} | {row['max_ms']:.1f} "
            f"| {row['avg_results']:.0f} | {row['empty_responses']} | `{row['statuses']}` |"
        )
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n")
    print(f"[search-bench] summary -> {out_dir / 'summary.md'}")


if __name__ == "__main__":
    main()
