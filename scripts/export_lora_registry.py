"""Export site LoRA fixtures to a cuteloras registry JSON.

Usage: python scripts/export_lora_registry.py [--output inference/lora_registry.json]
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "inference"))

from lora_fixtures import get_all_zimage_loras

LORA_CACHE = os.path.join(os.path.dirname(__file__), "..", "inference", ".lora_cache")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=os.path.join(os.path.dirname(__file__), "..", "inference", "lora_registry.json"))
    args = parser.parse_args()

    from urllib.parse import unquote

    records = []
    for lora in get_all_zimage_loras():
        filename = unquote(lora.url.split("/")[-1].split("?")[0])
        local = os.path.abspath(os.path.join(LORA_CACHE, filename))
        records.append({
            "id": lora.id,
            "name": lora.name,
            "base_model": "zimage",
            "path": local if os.path.exists(local) else None,
            "url": lora.url,
            "trigger_word": lora.trigger_word,
            "template": lora.template or "{prompt}",
            "keywords": lora.keywords,
            "negative_keywords": lora.negative_keywords,
            "is_adult": lora.is_adult,
            "scale": lora.scale,
        })

    with open(args.output, "w") as f:
        json.dump(records, f, indent=2)
    cached = sum(1 for r in records if r["path"])
    print(f"wrote {len(records)} records ({cached} locally cached) to {args.output}")


if __name__ == "__main__":
    main()
