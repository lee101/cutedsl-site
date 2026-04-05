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
from pathlib import Path

import psycopg2
import requests
from PIL import Image

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
    conn.autocommit = False
    return conn


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()[:16]


def load_all_prompts() -> list[str]:
    """Load all prompts from JSONL."""
    if not PROMPTS_FILE.exists():
        print(f"ERROR: {PROMPTS_FILE} not found. Run download_prompts.py first.")
        sys.exit(1)

    prompts = []
    with open(PROMPTS_FILE) as f:
        for line in f:
            try:
                row = json.loads(line)
                prompts.append(row["prompt"])
            except (json.JSONDecodeError, KeyError):
                continue
    return prompts


def get_existing_hashes(conn) -> set:
    """Get prompt hashes already in DB."""
    with conn.cursor() as cur:
        cur.execute("SELECT file_path FROM generated_images")
        paths = {row[0] for row in cur.fetchall()}
    hashes = set()
    for p in paths:
        fname = p.split("/")[-1] if "/" in p else p
        if "_" in fname:
            hashes.add(fname.split("_")[0])
    return hashes


def generate_image_local(prompt: str, width: int, height: int, steps: int) -> dict | None:
    """Call local Z-Image API."""
    try:
        resp = requests.post(
            f"{INFERENCE_URL}/generate_image",
            json={
                "prompt": prompt,
                "width": width,
                "height": height,
                "num_inference_steps": steps,
                "guidance_scale": 0.0,
                "auto_lora": False,
            },
            timeout=180,
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


def generate_image_fal(prompt: str, width: int, height: int, steps: int) -> dict | None:
    """Call fal.ai Flux Schnell API. Returns dict compatible with local API response."""
    try:
        resp = requests.post(
            "https://fal.run/fal-ai/flux/schnell",
            headers={
                "Authorization": f"Key {FAL_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "prompt": prompt,
                "image_size": {"width": width, "height": height},
                "num_inference_steps": min(steps, 4),  # Schnell is fast, 4 steps max
                "num_images": 1,
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


def generate_image(prompt: str, width: int, height: int, steps: int) -> dict | None:
    """Generate image using configured backend."""
    if BACKEND == "fal":
        return generate_image_fal(prompt, width, height, steps)
    return generate_image_local(prompt, width, height, steps)


def save_and_insert(api_result: dict, prompt: str, conn) -> bool:
    """Decode image, save all sizes + latent, insert into DB. Returns True on success."""
    img_b64 = api_result.get("image_base64")
    if not img_b64:
        return False

    try:
        img_bytes = base64.b64decode(img_b64)
        img = Image.open(io.BytesIO(img_bytes))
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
             file_size, "zimage", api_result.get("seed", 0),
             api_result.get("num_inference_steps", 9), latent_path),
        )
    conn.commit()
    return True


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
    parser.add_argument("--steps", type=int, default=4, help="Inference steps (4 for Z-Image Turbo)")
    parser.add_argument("--offset", type=int, default=0, help="Skip first N prompts")
    parser.add_argument("--dry-run", action="store_true", help="Just count pending, don't generate")
    args = parser.parse_args()

    print("=== CuteDSL Bulk Image Generator ===")
    print(f"Backend:   {BACKEND}" + (f" (fal.ai Flux Schnell)" if BACKEND == "fal" else f" ({INFERENCE_URL})"))
    print(f"Storage:   {IMAGES_DIR}")
    print(f"Size:      {args.width}x{args.height}, {args.steps} steps")

    conn = get_db()

    # Load existing hashes for dedup
    existing = get_existing_hashes(conn)
    print(f"Already generated: {len(existing):,}")

    # Load prompts
    print("Loading prompts...")
    all_prompts = load_all_prompts()
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
    consecutive_fails = 0
    start = time.time()

    for i, prompt in enumerate(pending):
        if shutdown_requested:
            print("\n[!] Shutting down gracefully")
            break

        short = (prompt[:70] + "...") if len(prompt) > 70 else prompt
        print(f"[{i+1:,}/{len(pending):,}] {short}")

        result = generate_image(prompt, args.width, args.height, args.steps)
        if result and save_and_insert(result, prompt, conn):
            success += 1
            consecutive_fails = 0
        else:
            failed += 1
            consecutive_fails += 1

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

    elapsed = time.time() - start
    rate = success / max(elapsed, 1)
    print(f"\n=== Done ===")
    print(f"Generated: {success:,} | Failed: {failed:,}")
    print(f"Time: {elapsed:.0f}s ({rate:.1f} img/s)")
    print(f"Remaining: {len(pending) - success - failed:,}")

    conn.close()


if __name__ == "__main__":
    main()
