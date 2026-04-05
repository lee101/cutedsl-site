#!/usr/bin/env python3
"""
Backfill NSFW classification for generated images.
Loads the NSFW detector on-demand, classifies images, updates the database.

Usage:
    python scripts/backfill_nsfw.py [--limit 1000] [--batch-size 50] [--threshold 0.5]
"""

import argparse
import io
import os
import sys
import time
from pathlib import Path

import psycopg2
import requests
from PIL import Image

IMAGES_DIR = Path("/sdb-disk/cutedsl-images")
INFERENCE_URL = os.getenv("INFERENCE_BACKEND_URL", "http://localhost:8100")
DB_DSN = os.getenv("DATABASE_URL", "postgres://cutedsl:cutedsl_pass_2026@localhost:5432/cutedsl?sslmode=disable")


def get_db():
    return psycopg2.connect(DB_DSN)


def get_unclassified(conn, limit: int) -> list[dict]:
    """Get images that haven't been NSFW classified yet."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, file_path FROM generated_images
               WHERE is_nsfw IS NULL
               ORDER BY created_at DESC LIMIT %s""",
            (limit,),
        )
        return [{"id": row[0], "file_path": row[1]} for row in cur.fetchall()]


def classify_image(file_path: str) -> dict | None:
    """Send image to inference server for NSFW classification."""
    full_path = IMAGES_DIR / file_path
    if not full_path.exists():
        return None

    try:
        with open(full_path, "rb") as f:
            resp = requests.post(
                f"{INFERENCE_URL}/nsfw_detect_file",
                files={"image_file": (full_path.name, f, "image/webp")},
                params={"unload_after": "false"},  # keep loaded for batch
                timeout=30,
            )
        if resp.status_code == 200:
            return resp.json()
        print(f"  API error {resp.status_code}: {resp.text[:200]}")
        return None
    except Exception as e:
        print(f"  Request error: {e}")
        return None


def update_nsfw(conn, image_id: str, is_nsfw: bool):
    """Update the NSFW flag in the database."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE generated_images SET is_nsfw = %s WHERE id = %s",
            (is_nsfw, image_id),
        )
    conn.commit()


def unload_nsfw_model():
    """Tell inference server to unload the NSFW classifier."""
    try:
        requests.post(f"{INFERENCE_URL}/nsfw_unload", timeout=10)
        print("NSFW model unloaded from GPU")
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="Backfill NSFW classification")
    parser.add_argument("--limit", type=int, default=1000, help="Max images to process")
    parser.add_argument("--threshold", type=float, default=0.5, help="NSFW score threshold")
    args = parser.parse_args()

    conn = get_db()
    images = get_unclassified(conn, args.limit)
    print(f"Found {len(images)} unclassified images")

    if not images:
        print("Nothing to do")
        return

    nsfw_count = 0
    safe_count = 0
    failed = 0
    start = time.time()

    for i, img in enumerate(images):
        result = classify_image(img["file_path"])
        if result is None:
            failed += 1
            continue

        is_nsfw = result.get("nsfw_score", 0) > args.threshold
        update_nsfw(conn, img["id"], is_nsfw)

        if is_nsfw:
            nsfw_count += 1
        else:
            safe_count += 1

        if (i + 1) % 50 == 0:
            elapsed = time.time() - start
            rate = (i + 1) / elapsed
            print(f"  [{i+1}/{len(images)}] safe={safe_count} nsfw={nsfw_count} failed={failed} ({rate:.1f}/s)")

    # Unload model after batch
    unload_nsfw_model()

    elapsed = time.time() - start
    print(f"\nDone: {safe_count} safe, {nsfw_count} NSFW, {failed} failed in {elapsed:.1f}s")
    conn.close()


if __name__ == "__main__":
    main()
