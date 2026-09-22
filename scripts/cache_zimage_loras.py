#!/usr/bin/env python3
"""Download the Z-Image LoRA catalog into inference/.lora_cache."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "inference"))

from lora_fixtures import LoRAMetadata, get_all_zimage_loras  # noqa: E402

CACHE_DIR = ROOT / "inference" / ".lora_cache"


def cache_path_for(lora: LoRAMetadata) -> Path:
    filename = urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(lora.url).path))
    return CACHE_DIR / filename


def validate_safetensors(path: Path) -> tuple[bool, str]:
    try:
        from safetensors import safe_open
    except ImportError:
        return True, "validation skipped: safetensors package unavailable"

    try:
        with safe_open(str(path), framework="pt") as sf:
            next(iter(sf.keys()))
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


def download_one(lora: LoRAMetadata, validate: bool) -> dict:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = cache_path_for(lora)
    if target.exists() and target.stat().st_size > 0:
        valid, detail = validate_safetensors(target) if validate else (True, "cached")
        return {"id": lora.id, "path": str(target), "status": "cached" if valid else "invalid", "detail": detail}

    fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".part", dir=str(CACHE_DIR))
    os.close(fd)
    tmp_path = Path(tmp_name)

    try:
        request = urllib.request.Request(lora.url, headers={"User-Agent": "cutedsl-zimage-cache/1.0"})
        with urllib.request.urlopen(request, timeout=90) as response, tmp_path.open("wb") as out:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        tmp_path.replace(target)
        valid, detail = validate_safetensors(target) if validate else (True, "downloaded")
        return {"id": lora.id, "path": str(target), "status": "downloaded" if valid else "invalid", "detail": detail}
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        return {"id": lora.id, "path": str(target), "status": "error", "detail": str(exc)}


def select_loras(ids: list[str] | None, missing_only: bool) -> list[LoRAMetadata]:
    loras = get_all_zimage_loras()
    if ids:
        wanted = set(ids)
        loras = [lora for lora in loras if lora.id in wanted]
        missing = wanted - {lora.id for lora in loras}
        if missing:
            raise SystemExit(f"unknown lora ids: {', '.join(sorted(missing))}")
    if missing_only:
        loras = [lora for lora in loras if not cache_path_for(lora).exists()]
    return loras


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", nargs="*", help="Specific LoRA ids to download.")
    parser.add_argument("--missing-only", action="store_true", help="Skip files already present in the cache.")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--no-validate", action="store_true")
    args = parser.parse_args()

    loras = select_loras(args.ids, args.missing_only)
    print(f"cache_dir={CACHE_DIR}")
    print(f"selected={len(loras)}")

    failures = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(download_one, lora, not args.no_validate) for lora in loras]
        for future in as_completed(futures):
            result = future.result()
            print(f"{result['status']}\t{result['id']}\t{result['path']}\t{result['detail']}")
            if result["status"] in {"error", "invalid"}:
                failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
