#!/usr/bin/env python3
"""Homepage animation smoothness bench.

Measures requestAnimationFrame cadence and browser long tasks for the homepage
at desktop and mobile viewport sizes. This complements Lighthouse: Lighthouse
is good for page-load metrics, while this catches steady-state animation jank.

Usage:
    python scripts/homepage_fps_bench.py http://localhost:3000
    python scripts/homepage_fps_bench.py https://cutedsl.cc --seconds 8
"""
import argparse
import statistics
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

VIEWPORTS = {
    "desktop": {"width": 1440, "height": 900},
    "mobile": {"width": 390, "height": 844},
}


def percentile(values, pct):
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((pct / 100) * (len(ordered) - 1)))
    return ordered[index]


def measure(page, seconds):
    return page.evaluate(
        """async (seconds) => {
          const longTasks = [];
          let observer = null;
          if ('PerformanceObserver' in window) {
            try {
              observer = new PerformanceObserver((list) => {
                for (const entry of list.getEntries()) longTasks.push(entry.duration);
              });
              observer.observe({ type: 'longtask', buffered: true });
            } catch (_) {}
          }

          const deltas = [];
          let last = performance.now();
          const end = last + seconds * 1000;
          await new Promise((resolve) => {
            function tick(now) {
              deltas.push(now - last);
              last = now;
              if (now >= end) resolve();
              else requestAnimationFrame(tick);
            }
            requestAnimationFrame(tick);
          });
          if (observer) observer.disconnect();
          return { deltas: deltas.slice(1), longTasks };
        }""",
        seconds,
    )


def main():
    parser = argparse.ArgumentParser(description="Measure homepage RAF cadence.")
    parser.add_argument("base", nargs="?", default="https://cutedsl.cc")
    parser.add_argument("--seconds", type=float, default=5)
    args = parser.parse_args()
    base = args.base.rstrip("/")

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = Path(__file__).parent.parent / "screenshots" / ts / "fps"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []

    print(f"[fps] base={base} seconds={args.seconds} out={out_dir}")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for name, viewport in VIEWPORTS.items():
          context = browser.new_context(viewport=viewport, device_scale_factor=1)
          page = context.new_page()
          page.goto(base + "/", wait_until="networkidle", timeout=30000)
          page.wait_for_timeout(1000)
          data = measure(page, args.seconds)
          deltas = data["deltas"]
          long_tasks = data["longTasks"]
          avg_delta = statistics.mean(deltas) if deltas else 0
          avg_fps = 1000 / avg_delta if avg_delta else 0
          p95_delta = percentile(deltas, 95)
          dropped = sum(1 for delta in deltas if delta > 34)
          long_total = sum(long_tasks)
          row = {
              "viewport": name,
              "avg_fps": avg_fps,
              "p95_frame_ms": p95_delta,
              "dropped_frames": dropped,
              "long_tasks": len(long_tasks),
              "long_task_ms": long_total,
          }
          rows.append(row)
          print(
              f"  {name}: avg={avg_fps:.1f}fps p95={p95_delta:.1f}ms "
              f"dropped>{dropped} longTasks={len(long_tasks)} longMs={long_total:.0f}"
          )
          context.close()
        browser.close()

    lines = [
        "# Homepage FPS Bench",
        f"base: `{base}`",
        f"timestamp: `{ts}`",
        "",
        "| viewport | avg fps | p95 frame ms | dropped frames >34ms | long tasks | long task ms |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['viewport']} | {row['avg_fps']:.1f} | {row['p95_frame_ms']:.1f} "
            f"| {row['dropped_frames']} | {row['long_tasks']} | {row['long_task_ms']:.0f} |"
        )
    summary = out_dir / "summary.md"
    summary.write_text("\n".join(lines) + "\n")
    print(f"[fps] summary -> {summary}")


if __name__ == "__main__":
    main()
