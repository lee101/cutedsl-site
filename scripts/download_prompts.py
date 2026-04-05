#!/usr/bin/env python3
"""Download prompt datasets from HuggingFace and save as newline-delimited text."""

import os
import json
from datasets import load_dataset

OUT_DIR = "/sdb-disk/cutedsl-images"
PROMPTS_FILE = os.path.join(OUT_DIR, "prompts.jsonl")

def download_sd_prompts():
    """Download daspartho/stable-diffusion-prompts (1.8M unique prompts from DiffusionDB)."""
    print("Downloading daspartho/stable-diffusion-prompts...")
    ds = load_dataset("daspartho/stable-diffusion-prompts", split="train")
    print(f"  Got {len(ds)} prompts")
    return ds

def clean_prompt(text: str) -> str:
    """Basic prompt cleaning."""
    text = text.strip()
    # Skip very short or very long prompts
    if len(text) < 10 or len(text) > 500:
        return ""
    # Skip prompts that are just URLs or paths
    if text.startswith("http") or "/" in text[:5]:
        return ""
    return text

def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    ds = download_sd_prompts()

    seen = set()
    count = 0
    with open(PROMPTS_FILE, "w") as f:
        for row in ds:
            prompt = clean_prompt(row.get("prompt", "") or row.get("text", ""))
            if not prompt:
                continue
            # Deduplicate
            key = prompt.lower().strip()
            if key in seen:
                continue
            seen.add(key)
            f.write(json.dumps({"prompt": prompt, "generated": False}) + "\n")
            count += 1
            if count % 100000 == 0:
                print(f"  Processed {count} unique prompts...")

    print(f"\nSaved {count} unique prompts to {PROMPTS_FILE}")

if __name__ == "__main__":
    main()
