#!/usr/bin/env python3
"""Lighthouse benchmark for cutedsl-site.

Runs Lighthouse on every route and reports Core Web Vitals + category scores
(Performance, SEO, Accessibility, Best Practices).

Usage:
    python scripts/lighthouse_bench.py                    # against https://cutedsl.cc
    python scripts/lighthouse_bench.py http://localhost:3000

Output:
    ./screenshots/<timestamp>/lighthouse/summary.md  — markdown table
    ./screenshots/<timestamp>/lighthouse/<slug>.json — raw Lighthouse JSON
"""
import json
import os
import subprocess
import sys
import time
import argparse
from pathlib import Path

ROUTES = [
    "/",
    "/gallery",
    "/blog",
    "/evals",
    "/search",
    "/docs",
    "/docs/zimage",
    "/docs/chronos2",
    "/docs/tts",
    "/docs/stt",
    "/docs/gemma4",
    "/docs/caption",
    "/docs/flux_image",
    "/docs/ltx_video",
    "/docs/lora_training",
]


def slug(route: str) -> str:
    s = route.strip("/").replace("/", "_") or "home"
    return s


def discover_chrome_path() -> str | None:
    """Find a local Chrome executable, preferring Playwright's pinned Chromium."""
    if os.environ.get("CHROME_PATH"):
        return os.environ["CHROME_PATH"]

    repo = Path(__file__).parent.parent
    candidates = [
        ["node", "-e", "const {chromium}=require('./frontend/node_modules/playwright'); console.log(chromium.executablePath())"],
        ["node", "-e", "const {chromium}=require('./frontend/node_modules/@playwright/test'); console.log(chromium.executablePath())"],
    ]
    for cmd in candidates:
        try:
            result = subprocess.run(cmd, cwd=repo, check=True, capture_output=True, text=True, timeout=10)
            path = result.stdout.strip()
            if path and Path(path).exists():
                return path
        except Exception:
            pass

    for name in ("chromium", "chromium-browser", "google-chrome", "chrome"):
        try:
            result = subprocess.run(["which", name], check=True, capture_output=True, text=True, timeout=5)
            path = result.stdout.strip()
            if path:
                return path
        except Exception:
            pass
    return None


def run_lighthouse(url: str, out_json: Path, chrome_path: str | None) -> dict | None:
    cmd = [
        "npx", "--yes", "lighthouse",
        url,
        "--output=json",
        f"--output-path={out_json}",
        "--chrome-flags=--headless --no-sandbox --disable-gpu",
        "--quiet",
        "--only-categories=performance,seo,accessibility,best-practices",
    ]
    env = os.environ.copy()
    repo = Path(__file__).parent.parent
    bench_tmp = repo / ".perf-tmp"
    bench_tmp.mkdir(exist_ok=True)
    env.setdefault("TMPDIR", str(bench_tmp))
    env.setdefault("npm_config_cache", str(bench_tmp / "npm-cache"))
    if chrome_path:
        env["CHROME_PATH"] = chrome_path
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120, env=env)
        with open(out_json) as f:
            return json.load(f)
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT {url}")
        return None
    except subprocess.CalledProcessError as e:
        print(f"  ERROR {url}: {e.stderr.decode()[:200]}")
        return None
    except Exception as e:
        print(f"  ERROR {url}: {e}")
        return None


def extract_metrics(data: dict) -> dict:
    cats = data.get("categories", {})
    audits = data.get("audits", {})

    def score(cat_key):
        s = cats.get(cat_key, {}).get("score")
        return round(s * 100) if s is not None else "—"

    def metric(audit_key, decimals=1):
        a = audits.get(audit_key, {})
        v = a.get("numericValue")
        if v is None:
            return "—"
        if decimals == 0:
            return str(round(v))
        return f"{v:.{decimals}f}"

    return {
        "perf": score("performance"),
        "seo": score("seo"),
        "a11y": score("accessibility"),
        "bp": score("best-practices"),
        # Core Web Vitals
        "lcp_ms": metric("largest-contentful-paint", 0),
        "cls": metric("cumulative-layout-shift", 3),
        "tbt_ms": metric("total-blocking-time", 0),
        "fcp_ms": metric("first-contentful-paint", 0),
        "si_ms": metric("speed-index", 0),
    }


def main():
    parser = argparse.ArgumentParser(description="Run Lighthouse on CuteDSL routes.")
    parser.add_argument("base", nargs="?", default="https://cutedsl.cc")
    parser.add_argument("--routes", nargs="+", default=ROUTES, help="Routes to audit, e.g. --routes / /account /docs")
    args = parser.parse_args()

    base = args.base.rstrip("/")
    routes = args.routes
    chrome_path = discover_chrome_path()
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = Path(__file__).parent.parent / "screenshots" / ts / "lighthouse"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[lighthouse] base={base} out={out_dir}")
    if chrome_path:
        print(f"[lighthouse] chrome={chrome_path}")
    else:
        print("[lighthouse] chrome=not found; set CHROME_PATH if Lighthouse fails")

    rows = []
    for route in routes:
        url = base + route
        out_json = out_dir / f"{slug(route)}.json"
        print(f"  auditing {route} ...")
        t0 = time.time()
        data = run_lighthouse(url, out_json, chrome_path)
        dt = time.time() - t0
        if data:
            m = extract_metrics(data)
            print(f"    perf={m['perf']} seo={m['seo']} a11y={m['a11y']} | LCP={m['lcp_ms']}ms CLS={m['cls']} TBT={m['tbt_ms']}ms  ({dt:.1f}s)")
            rows.append((route, m))
        else:
            rows.append((route, None))

    # Markdown summary
    header = "| Route | Perf | SEO | A11y | BP | LCP (ms) | CLS | TBT (ms) | FCP (ms) | SI (ms) |"
    sep    = "|-------|------|-----|------|----|----------|-----|----------|----------|---------|"
    lines = ["# Lighthouse Benchmark", f"base: `{base}`", f"timestamp: `{ts}`", "", header, sep]
    for route, m in rows:
        if m:
            lines.append(
                f"| `{route}` | {m['perf']} | {m['seo']} | {m['a11y']} | {m['bp']} "
                f"| {m['lcp_ms']} | {m['cls']} | {m['tbt_ms']} | {m['fcp_ms']} | {m['si_ms']} |"
            )
        else:
            lines.append(f"| `{route}` | — | — | — | — | — | — | — | — | — |")

    summary = out_dir / "summary.md"
    summary.write_text("\n".join(lines) + "\n")
    print(f"\n[lighthouse] summary -> {summary}")


if __name__ == "__main__":
    main()
