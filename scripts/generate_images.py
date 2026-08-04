#!/usr/bin/env python3
"""
Batch-generate images from prompts using the Z-Image API.
Converts to WebP q85, generates multiple sizes, stores in DB.

Resumable: tracks progress via DB — safe to restart at any time.
Runs until all prompts are generated or interrupted.

Usage:
    # Generate 1000 images (default)
    python scripts/generate_images.py --limit 1000

    # Generate ALL 1.7M images (long-running)
    python scripts/generate_images.py --limit 0

    # Generate specific sizes (landscape, portrait, square)
    python scripts/generate_images.py --limit 500 --width 1280 --height 720

    # Dry run — just count how many need generating
    python scripts/generate_images.py --dry-run

Requires:
    - Z-Image API running (INFERENCE_BACKEND_URL or default http://localhost:8100)
    - PostgreSQL with cutedsl database
    - /sdb-disk/cutedsl-images directory
"""

import argparse
import base64
import hashlib
import io
import json
import os
import signal
import sys
import time
import uuid
from collections import deque
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

import psycopg2
import requests
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "inference"))

from image_quality import bumpy_metrics, compact_prompt, detect_too_bumpy, retry_prompt

# Config
IMAGES_DIR = Path("/sdb-disk/cutedsl-images")
PROMPTS_FILE = IMAGES_DIR / "prompts.jsonl"
INFERENCE_URL = os.getenv("INFERENCE_BACKEND_URL", "http://localhost:8100")
FAL_KEY = os.getenv("FAL_KEY", "")
DB_DSN = os.getenv("DATABASE_URL", "postgres://cutedsl:cutedsl_pass_2026@localhost:5432/cutedsl?sslmode=disable")

# Backend: "local" (Z-Image via inference server) or "fal" (Flux Schnell via fal.ai)
BACKEND = os.getenv("GEN_BACKEND", "fal" if FAL_KEY else "local")

SIZES = {
    "originals": (1024, 1024),
    "medium": (512, 512),
    "thumbs": (256, 256),
}

WEBP_QUALITY = 85
SAVE_LATENTS = True

# Skip the legacy histogram detector (false-positives on white-background images)
LENIENT_QUALITY = os.getenv("LENIENT_QUALITY", "0") == "1"


def image_too_bumpy(img) -> bool:
    if not LENIENT_QUALITY:
        return detect_too_bumpy(img)
    m = bumpy_metrics(img)
    return (
        (m.entropy >= 7.45 and m.laplacian_ratio >= 0.30 and m.laplacian_abs_mean >= 15.0)
        or (m.laplacian_abs_mean >= 42.0 and m.laplacian_ratio >= 0.31)
    )

# Graceful shutdown
shutdown_requested = False

def handle_signal(signum, frame):
    global shutdown_requested
    print("\n[!] Shutdown requested, finishing current image...")
    shutdown_requested = True

signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)


def get_db():
    conn = psycopg2.connect(DB_DSN)
    conn.autocommit = True
    # Ensure table exists (matches server/db.go schema)
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS generated_images (
                id TEXT PRIMARY KEY,
                prompt TEXT NOT NULL,
                width INTEGER NOT NULL DEFAULT 1024,
                height INTEGER NOT NULL DEFAULT 1024,
                file_path TEXT NOT NULL,
                thumb_path TEXT DEFAULT '',
                med_path TEXT DEFAULT '',
                file_size BIGINT DEFAULT 0,
                model TEXT DEFAULT 'zimage',
                seed BIGINT DEFAULT 0,
                steps INTEGER DEFAULT 9,
                is_nsfw BOOLEAN DEFAULT NULL,
                latent_path TEXT DEFAULT '',
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_images_created ON generated_images(created_at DESC);
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS generated_image_rejections (
                prompt_hash TEXT PRIMARY KEY,
                prompt TEXT NOT NULL,
                reason TEXT NOT NULL,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_image_rejections_updated
                ON generated_image_rejections(updated_at DESC);
        """)
    conn.autocommit = False
    return conn


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()[:16]


def load_all_prompts(prompts_file: Path = PROMPTS_FILE) -> list[str]:
    """Load all prompts from JSONL."""
    if not prompts_file.exists():
        print(f"ERROR: {prompts_file} not found. Run download_prompts.py first.")
        sys.exit(1)

    prompts = []
    with open(prompts_file) as f:
        for line in f:
            try:
                row = json.loads(line)
                prompts.append(row["prompt"])
            except (json.JSONDecodeError, KeyError):
                continue
    return prompts


def get_existing_hashes(conn) -> set:
    """Get prompt hashes already generated or rejected."""
    with conn.cursor() as cur:
        cur.execute("SELECT file_path FROM generated_images")
        paths = {row[0] for row in cur.fetchall()}
    hashes = set()
    for p in paths:
        fname = p.split("/")[-1] if "/" in p else p
        if "_" in fname:
            hashes.add(fname.split("_")[0])
    with conn.cursor() as cur:
        cur.execute("SELECT prompt_hash FROM generated_image_rejections")
        hashes.update(row[0] for row in cur.fetchall())
    return hashes


def record_rejection(conn, prompt: str, reason: str):
    """Record a prompt that should be skipped on future resumptions."""
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO generated_image_rejections (prompt_hash, prompt, reason, updated_at)
               VALUES (%s, %s, %s, NOW())
               ON CONFLICT (prompt_hash)
               DO UPDATE SET reason = EXCLUDED.reason, updated_at = NOW()""",
            (prompt_hash(prompt), prompt, reason),
        )
    conn.commit()


def seed_for_prompt(prompt: str, attempt: int = 0) -> int:
    return (int(hashlib.sha256(prompt.encode()).hexdigest()[:8], 16) + attempt) % (2**31)


def generate_image_local(prompt: str, width: int, height: int, steps: int, seed: int) -> dict | None:
    """Call local Z-Image API."""
    try:
        resp = requests.post(
            f"{INFERENCE_URL}/generate_image",
            json={
                "prompt": compact_prompt(prompt),
                "width": width,
                "height": height,
                "seed": seed,
                "num_inference_steps": steps,
                "guidance_scale": 0.0,
                "auto_lora": False,
                "low_priority": True,
                "quality_retry": not LENIENT_QUALITY,
            },
            timeout=360,
        )
        if resp.status_code == 200:
            return resp.json()
        print(f"  API {resp.status_code}: {resp.text[:100]}")
        return None
    except requests.exceptions.ConnectionError:
        print("  Connection refused — is inference server running?")
        return None
    except Exception as e:
        print(f"  Error: {e}")
        return None


def generate_image_fal(prompt: str, width: int, height: int, steps: int, seed: int) -> dict | None:
    """Call fal.ai Flux Schnell API. Returns dict compatible with local API response."""
    try:
        resp = requests.post(
            "https://fal.run/fal-ai/flux/schnell",
            headers={
                "Authorization": f"Key {FAL_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "prompt": compact_prompt(prompt),
                "image_size": {"width": width, "height": height},
                "num_inference_steps": min(steps, 4),  # Schnell is fast, 4 steps max
                "num_images": 1,
                "seed": seed,
                "enable_safety_checker": False,
            },
            timeout=60,
        )
        if resp.status_code == 200:
            data = resp.json()
            images = data.get("images", [])
            if not images:
                return None
            img_url = images[0].get("url", "")
            if not img_url:
                return None
            # Download the image
            img_resp = requests.get(img_url, timeout=30)
            if img_resp.status_code != 200:
                return None
            img_b64 = base64.b64encode(img_resp.content).decode()
            return {
                "image_base64": img_b64,
                "width": images[0].get("width", width),
                "height": images[0].get("height", height),
                "seed": data.get("seed", 0),
                "format": "png",
            }
        print(f"  fal.ai {resp.status_code}: {resp.text[:100]}")
        return None
    except Exception as e:
        print(f"  fal.ai error: {e}")
        return None


def generate_image(prompt: str, width: int, height: int, steps: int, seed: int) -> dict | None:
    """Generate image using configured backend."""
    if BACKEND == "fal":
        return generate_image_fal(prompt, width, height, steps, seed)
    return generate_image_local(prompt, width, height, steps, seed)


def decode_result_image(api_result: dict) -> Image.Image | None:
    """Decode an API image response into a PIL image."""
    img_b64 = api_result.get("image_base64")
    if not img_b64:
        return None
    try:
        img_bytes = base64.b64decode(img_b64)
        return Image.open(io.BytesIO(img_bytes)).convert("RGB")
    except Exception as e:
        print(f"  Decode failed: {e}")
        return None


def generate_image_with_quality_retry(prompt: str, width: int, height: int, steps: int) -> tuple[dict | None, str | None]:
    """Generate an image, retrying once if the result is bumpy."""
    saw_bumpy = False
    for attempt in range(2):
        attempt_prompt = prompt if attempt == 0 else retry_prompt(prompt)
        result = generate_image(
            attempt_prompt,
            width,
            height,
            steps,
            seed_for_prompt(prompt, attempt),
        )
        if not result:
            continue

        img = decode_result_image(result)
        if img is None:
            continue

        if not image_too_bumpy(img):
            if attempt > 0:
                result["prompt_retry_used"] = attempt_prompt
            return result, None

        saw_bumpy = True
        metrics = bumpy_metrics(img)
        print(
            "  Bumpy image detected "
            f"(lap_ratio={metrics.laplacian_ratio:.3f}, "
            f"lap_mean={metrics.laplacian_abs_mean:.1f}, "
            f"entropy={metrics.entropy:.2f})"
        )
        if attempt == 0:
            print("  Retrying once with shortened smooth prompt...")

    return None, "bumpy_image" if saw_bumpy else None


def _generate_image_worker(
    prompt: str, width: int, height: int, steps: int
) -> tuple[dict | None, str | None, Exception | None]:
    try:
        result, rejection_reason = generate_image_with_quality_retry(
            prompt, width, height, steps
        )
        return result, rejection_reason, None
    except Exception as exc:
        return None, None, exc


def iter_generation_results(
    prompts: list[str],
    width: int,
    height: int,
    steps: int,
    concurrency: int,
    on_submit: Callable[[int, str], None] | None = None,
) -> Iterator[
    tuple[int, str, tuple[dict | None, str | None, Exception | None]]
]:
    """Yield worker results in prompt order with bounded requests in flight."""
    if concurrency <= 1:
        for index, prompt in enumerate(prompts):
            if on_submit is not None:
                on_submit(index, prompt)
            yield index, prompt, _generate_image_worker(prompt, width, height, steps)
        return

    prompt_iter = iter(enumerate(prompts))
    in_flight: deque[tuple[int, str, Future]] = deque()
    executor = ThreadPoolExecutor(
        max_workers=concurrency, thread_name_prefix="image-generator"
    )
    try:
        # Keep one queued wave so serialized image/DB writes do not leave worker
        # slots empty between ordered results.
        for _ in range(concurrency * 2):
            try:
                index, prompt = next(prompt_iter)
            except StopIteration:
                break
            if on_submit is not None:
                on_submit(index, prompt)
            future = executor.submit(
                _generate_image_worker, prompt, width, height, steps
            )
            in_flight.append((index, prompt, future))

        while in_flight:
            index, prompt, future = in_flight.popleft()
            worker_result = future.result()
            try:
                next_index, next_prompt = next(prompt_iter)
            except StopIteration:
                pass
            else:
                if on_submit is not None:
                    on_submit(next_index, next_prompt)
                next_future = executor.submit(
                    _generate_image_worker, next_prompt, width, height, steps
                )
                in_flight.append((next_index, next_prompt, next_future))
            yield index, prompt, worker_result
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


def save_and_insert(api_result: dict, prompt: str, conn, model: str = "zimage") -> bool:
    """Decode image, save all sizes + latent, insert into DB. Returns True on success."""
    img_b64 = api_result.get("image_base64")
    if not img_b64:
        return False

    try:
        img_bytes = base64.b64decode(img_b64)
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    except Exception as e:
        print(f"  Decode failed: {e}")
        return False

    phash = prompt_hash(prompt)
    img_id = str(uuid.uuid4())
    fname = f"{phash}_{img_id[:8]}.webp"

    paths = {}
    file_size = 0

    for size_name, (w, h) in SIZES.items():
        out_dir = IMAGES_DIR / size_name
        out_dir.mkdir(parents=True, exist_ok=True)

        resized = img.copy()
        if resized.width != w or resized.height != h:
            resized = resized.resize((w, h), Image.LANCZOS)

        out_path = out_dir / fname
        resized.save(out_path, "WEBP", quality=WEBP_QUALITY)
        paths[size_name] = f"{size_name}/{fname}"

        if size_name == "originals":
            file_size = out_path.stat().st_size

    # Save latent
    latent_path = ""
    latent_b64 = api_result.get("latent_base64")
    if latent_b64 and SAVE_LATENTS:
        latent_dir = IMAGES_DIR / "latents"
        latent_dir.mkdir(parents=True, exist_ok=True)
        latent_fname = f"{phash}_{img_id[:8]}.pt"
        (latent_dir / latent_fname).write_bytes(base64.b64decode(latent_b64))
        latent_path = f"latents/{latent_fname}"

    # Insert into DB
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO generated_images
               (id, prompt, width, height, file_path, thumb_path, med_path, file_size, model, seed, steps, latent_path)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (id) DO NOTHING""",
            (img_id, prompt,
             api_result.get("width", img.width), api_result.get("height", img.height),
             paths.get("originals", ""), paths.get("thumbs", ""), paths.get("medium", ""),
             file_size, model, api_result.get("seed", 0),
             api_result.get("num_inference_steps", 9), latent_path),
        )
    conn.commit()
    return True


def trigger_reindex():
    server_url = os.getenv("GO_SERVER_URL", "http://localhost:8095")
    try:
        resp = requests.post(f"{server_url}/api/search/reindex", timeout=10)
        if resp.status_code == 202:
            print(f"[reindex] Triggered search index rebuild on {server_url}")
        else:
            print(f"[reindex] Reindex returned {resp.status_code} (manual restart may be needed)")
    except Exception as e:
        print(f"[reindex] Could not trigger reindex: {e}")


def estimate_storage(count: int) -> str:
    """Estimate storage needed for N images (3 sizes + latent)."""
    # Rough estimates: original ~80KB, medium ~25KB, thumb ~8KB, latent ~200KB
    per_image_kb = 80 + 25 + 8 + 200
    total_gb = (count * per_image_kb) / (1024 * 1024)
    return f"{total_gb:.1f} GB"


def main():
    parser = argparse.ArgumentParser(description="Bulk generate images from prompts")
    parser.add_argument("--limit", type=int, default=1000, help="Max images to generate (0 = all)")
    parser.add_argument("--width", type=int, default=1024, help="Image width")
    parser.add_argument("--height", type=int, default=1024, help="Image height")
    parser.add_argument("--steps", type=int, default=8, help="Inference steps (8 for Z-Image Turbo)")
    parser.add_argument("--offset", type=int, default=0, help="Skip first N prompts")
    parser.add_argument("--prompts-file", default=str(PROMPTS_FILE), help="JSONL prompts file")
    parser.add_argument("--dry-run", action="store_true", help="Just count pending, don't generate")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Number of image requests in flight (default: 1)",
    )
    args = parser.parse_args()
    if args.concurrency < 1:
        parser.error("--concurrency must be at least 1")

    print("=== CuteDSL Bulk Image Generator ===")
    print(f"Backend:   {BACKEND}" + (f" (fal.ai Flux Schnell)" if BACKEND == "fal" else f" ({INFERENCE_URL})"))
    print(f"Storage:   {IMAGES_DIR}")
    print(f"Size:      {args.width}x{args.height}, {args.steps} steps")
    print(f"Concurrency: {args.concurrency}")

    conn = get_db()

    # Load existing hashes for dedup
    existing = get_existing_hashes(conn)
    print(f"Already generated: {len(existing):,}")

    # Load prompts
    print(f"Loading prompts from {args.prompts_file}...")
    all_prompts = load_all_prompts(Path(args.prompts_file))
    print(f"Total prompts: {len(all_prompts):,}")

    # Filter to ungenerated
    pending = []
    for p in all_prompts:
        if prompt_hash(p) not in existing:
            pending.append(p)

    print(f"Pending: {len(pending):,}")
    print(f"Estimated storage: {estimate_storage(len(pending))}")

    if args.dry_run:
        print("(dry run — exiting)")
        return

    # Apply offset and limit
    if args.offset > 0:
        pending = pending[args.offset:]
        print(f"After offset={args.offset}: {len(pending):,} remaining")

    if args.limit > 0:
        pending = pending[:args.limit]

    print(f"Will generate: {len(pending):,} images")
    print()

    success = 0
    failed = 0
    last_reindex = 0
    consecutive_fails = 0
    start = time.time()

    def print_progress(index: int, prompt: str) -> None:
        short = (prompt[:70] + "...") if len(prompt) > 70 else prompt
        print(f"[{index+1:,}/{len(pending):,}] {short}")

    generation_results = iter_generation_results(
        pending,
        args.width,
        args.height,
        args.steps,
        args.concurrency,
        on_submit=print_progress,
    )
    for i, prompt, worker_result in generation_results:
        result, rejection_reason, worker_error = worker_result
        if worker_error is not None:
            print(f"  Worker error: {worker_error}")
        if result and save_and_insert(result, prompt, conn):
            success += 1
            consecutive_fails = 0
        else:
            failed += 1
            consecutive_fails += 1
            if rejection_reason:
                record_rejection(conn, prompt, rejection_reason)
                consecutive_fails = 0
                print(f"  Rejected prompt ({rejection_reason}); future runs will skip it.")

            # Back off if many consecutive failures (server might be down)
            if consecutive_fails >= 10:
                print(f"  [!] {consecutive_fails} consecutive failures, waiting 30s...")
                time.sleep(30)
            elif consecutive_fails >= 3:
                time.sleep(2)

        # Progress report every 100 images
        if (i + 1) % 100 == 0:
            elapsed = time.time() - start
            rate = success / max(elapsed, 1)
            eta_s = (len(pending) - i - 1) / max(rate, 0.01)
            eta_h = eta_s / 3600

            disk_used = sum(
                sum(f.stat().st_size for f in (IMAGES_DIR / d).iterdir() if f.is_file())
                for d in ["originals", "medium", "thumbs"]
                if (IMAGES_DIR / d).exists()
            ) / (1024**3)

            print(f"  --- {success:,} ok, {failed:,} fail | "
                  f"{rate:.1f} img/s | ETA {eta_h:.1f}h | disk {disk_used:.1f} GB ---")

        if success - last_reindex >= 2000:
            trigger_reindex()
            last_reindex = success

        if shutdown_requested:
            print("\n[!] Shutting down gracefully")
            generation_results.close()
            break

    elapsed = time.time() - start
    rate = success / max(elapsed, 1)
    print(f"\n=== Done ===")
    print(f"Generated: {success:,} | Failed: {failed:,}")
    print(f"Time: {elapsed:.0f}s ({rate:.1f} img/s)")
    print(f"Remaining: {len(pending) - success - failed:,}")

    # Trigger search index rebuild so new images become searchable immediately
    if success > 0:
        trigger_reindex()

    conn.close()


if __name__ == "__main__":
    main()
