#!/usr/bin/env python3
"""Visual screenshot bench for cutedsl-site.

Walks every advertised route at desktop + mobile widths and saves PNGs to
./screenshots/<timestamp>/<viewport>/<route>.png so we can review visually.

Usage:
    python scripts/screenshot_bench.py                    # against https://cutedsl.cc
    python scripts/screenshot_bench.py http://localhost:3000
"""
import os
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROUTES = [
    "/",
    "/blog",
    "/evals",
    "/search",
    "/lora-trainer",
    "/docs",
    "/docs/zimage",
    "/docs/chronos2",
    "/docs/tts",
    "/docs/stt",
    "/docs/lora_training",
    "/docs/ltx_video",
    "/api-docs",
    "/api-docs/zimage",
    "/api-docs/chronos2",
    "/api-docs/tts",
    "/api-docs/stt",
    "/api-docs/gemma4",
    "/api-docs/caption",
    "/api-docs/flux_image",
    "/api-docs/ltx_video",
    "/api-docs/lora_training",
]

VIEWPORTS = {
    "desktop": {"width": 1440, "height": 900},
    "mobile": {"width": 390, "height": 844},
}


def slug(route: str) -> str:
    s = route.strip("/").replace("/", "_") or "home"
    return s


def main():
    base = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "https://cutedsl.cc"
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_root = Path(__file__).parent.parent / "screenshots" / ts
    out_root.mkdir(parents=True, exist_ok=True)
    print(f"[bench] base={base} out={out_root}")

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for vname, vp in VIEWPORTS.items():
            ctx = browser.new_context(viewport=vp, device_scale_factor=1)
            page = ctx.new_page()
            (out_root / vname).mkdir(exist_ok=True)
            for route in ROUTES:
                url = base + route
                fname = out_root / vname / f"{slug(route)}.png"
                t0 = time.time()
                try:
                    resp = page.goto(url, wait_until="networkidle", timeout=20000)
                    status = resp.status if resp else 0
                    page.wait_for_timeout(500)  # let fonts/images settle
                    page.screenshot(path=str(fname), full_page=True)
                    dt = (time.time() - t0) * 1000
                    print(f"  [{vname}] {status} {route}  {dt:.0f}ms  -> {fname.name}")
                    results.append((vname, route, status, str(fname)))
                except Exception as e:
                    print(f"  [{vname}] ERR {route}: {e}")
                    results.append((vname, route, 0, f"ERROR: {e}"))
            ctx.close()
        browser.close()

    # Write summary markdown
    md = ["# Screenshot bench", f"base: `{base}`", f"timestamp: `{ts}`", ""]
    md.append("| viewport | route | status | file |")
    md.append("|---|---|---|---|")
    for v, r, s, f in results:
        md.append(f"| {v} | `{r}` | {s} | `{Path(f).name}` |")
    (out_root / "summary.md").write_text("\n".join(md))
    print(f"[bench] summary -> {out_root}/summary.md")


if __name__ == "__main__":
    main()
