#!/usr/bin/env python3
"""
Filter prompts dataset to remove unsafe/inappropriate content.
Creates a cleaned prompts file, preserving the original.

Usage:
    python scripts/filter_prompts.py [--dry-run]
"""

import json
import re
import sys
from pathlib import Path

IMAGES_DIR = Path("/sdb-disk/cutedsl-images")
PROMPTS_FILE = IMAGES_DIR / "prompts.jsonl"
FILTERED_FILE = IMAGES_DIR / "prompts_filtered.jsonl"

# Child safety - absolute blocks, no exceptions
CHILD_SAFETY_WORDS = {
    # Age markers
    "1yo", "2yo", "3yo", "4yo", "5yo", "6yo", "7yo", "8yo", "9yo",
    "10yo", "11yo", "12yo", "13yo", "14yo", "15yo", "16yo", "17yo", "18yo",
    "1 year old", "2 year old", "3 year old", "4 year old", "5 year old",
    "6 year old", "7 year old", "8 year old", "9 year old",
    "10 year old", "11 year old", "12 year old", "13 year old",
    "14 year old", "15 year old", "16 year old", "17 year old",
    # Direct terms
    "child", "children", "childs", "underage", "minors",
    "loli", "shota", "shotacon", "lolicon",
    "schoolgirl", "schoolboy", "pre teen", "preteen",
    "daycare", "little girl", "little boy",
    "baby", "infant", "toddler",
    "teen girl", "teen boy", "teenage girl", "teenage boy",
}

# Explicit sexual/violent content - block these in prompts
EXPLICIT_WORDS = {
    # Sexual
    "nsfw", "nude", "nudity", "naked", "topless", "bottomless",
    "penis", "vagina", "cock", "dick", "pussy",
    "sex", "sexual", "erotic", "porn", "pornographic", "xxx",
    "hentai", "futanari", "futa", "girlcock", "dickgirl",
    "orgasm", "masturbat", "cum", "cumshot",
    "breasts", "boobs", "tits", "nipple",
    "bondage", "bdsm", "hogtied", "ballgag",
    "lingerie", "thong", "panties", "seethrough",
    "brothel", "slut", "whore",
    # Violence/gore
    "gore", "gory", "torture", "tortured",
    "rape", "raped", "raping",
    "murdered", "slaughtered", "massacred", "butchered",
    "executed", "assassinated",
    "slave", "slavery",
    # Other harmful
    "hitler", "nazi", "swastika",
    "suicide", "self harm", "self-harm",
}

# Compile patterns - match as whole words where possible
def _build_patterns():
    """Build compiled regex patterns for fast matching."""
    patterns = []

    # Child safety: exact substring match (these are always bad in any context)
    for word in CHILD_SAFETY_WORDS:
        patterns.append((re.compile(r'\b' + re.escape(word) + r'\b', re.IGNORECASE), "child_safety"))

    # Explicit content: whole word match
    for word in EXPLICIT_WORDS:
        # Some words like "masturbat" are prefix matches
        if word.endswith("t") and word in ("masturbat",):
            patterns.append((re.compile(r'\b' + re.escape(word), re.IGNORECASE), "explicit"))
        else:
            patterns.append((re.compile(r'\b' + re.escape(word) + r'\b', re.IGNORECASE), "explicit"))

    return patterns


def is_blocked(prompt: str, patterns: list) -> str | None:
    """Check if prompt contains blocked content. Returns category or None."""
    prompt_lower = prompt.lower()

    # Quick pre-check with simple string matching for speed
    for word in CHILD_SAFETY_WORDS:
        if word in prompt_lower:
            return "child_safety"

    # Regex check for explicit content
    for pattern, category in patterns:
        if pattern.search(prompt):
            return category

    return None


def main():
    dry_run = "--dry-run" in sys.argv

    if not PROMPTS_FILE.exists():
        print(f"ERROR: {PROMPTS_FILE} not found")
        sys.exit(1)

    patterns = _build_patterns()

    total = 0
    kept = 0
    blocked_child = 0
    blocked_explicit = 0

    print(f"Filtering {PROMPTS_FILE}...")
    print(f"Child safety terms: {len(CHILD_SAFETY_WORDS)}")
    print(f"Explicit terms: {len(EXPLICIT_WORDS)}")
    print()

    out_f = None if dry_run else open(FILTERED_FILE, "w")

    with open(PROMPTS_FILE) as f:
        for line in f:
            total += 1
            try:
                row = json.loads(line)
                prompt = row.get("prompt", "")
            except (json.JSONDecodeError, KeyError):
                continue

            category = is_blocked(prompt, patterns)
            if category == "child_safety":
                blocked_child += 1
                continue
            elif category == "explicit":
                blocked_explicit += 1
                continue

            kept += 1
            if out_f:
                out_f.write(json.dumps({"prompt": prompt, "generated": False}) + "\n")

            if total % 200000 == 0:
                print(f"  Processed {total:,}: kept {kept:,}, blocked {blocked_child + blocked_explicit:,} "
                      f"(child={blocked_child:,}, explicit={blocked_explicit:,})")

    if out_f:
        out_f.close()

    pct_removed = ((blocked_child + blocked_explicit) / total * 100) if total > 0 else 0

    print()
    print(f"=== Filter Results ===")
    print(f"Total prompts:    {total:,}")
    print(f"Kept:             {kept:,}")
    print(f"Blocked (child):  {blocked_child:,}")
    print(f"Blocked (explicit): {blocked_explicit:,}")
    print(f"Removed:          {pct_removed:.1f}%")

    if not dry_run:
        # Replace original with filtered version
        backup = IMAGES_DIR / "prompts_unfiltered.jsonl"
        PROMPTS_FILE.rename(backup)
        FILTERED_FILE.rename(PROMPTS_FILE)
        print(f"\nOriginal backed up to: {backup}")
        print(f"Filtered file now at:  {PROMPTS_FILE}")
    else:
        print(f"\n(dry run — no files modified)")


if __name__ == "__main__":
    main()
