"""Build LoRA training datasets from real web data (HF datasets-server API),
filter by aesthetic score, caption, index (CLIP embeds + scores), and upload
everything to R2.

Datasets:
  app_logo_maker      <- logo-wizard/modern-logo-dataset (real logo designs, SD captions)
  product_screenshots <- agentsea/wave-ui-25k (real web/app UI screenshots)

Usage:
  python build_lora_datasets.py [--only logos|screens] [--keep 160] [--fetch 400]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import time
import zipfile
from pathlib import Path

import httpx
import numpy as np
from PIL import Image

DS_API = "https://datasets-server.huggingface.co/rows"
SERVER = "http://127.0.0.1:8100"
DATASET_ROOT = Path(__file__).parent / "lora_datasets"

SPECS = {
    "app_logo_maker": {
        "hf_dataset": "logo-wizard/modern-logo-dataset",
        "trigger": "applogo",
        "caption_mode": "dataset_text",
        "min_side": 256,
    },
    "product_screenshots": {
        "hf_dataset": "agentsea/wave-ui-25k",
        "trigger": "prodshot",
        "caption_mode": "blip",
        "min_side": 512,
    },
}


def fetch_rows(client: httpx.Client, dataset: str, offset: int, length: int = 100) -> list[dict]:
    for attempt in range(3):
        try:
            resp = client.get(DS_API, params={
                "dataset": dataset, "config": "default", "split": "train",
                "offset": offset, "length": length,
            }, timeout=60)
            resp.raise_for_status()
            return resp.json().get("rows", [])
        except Exception as e:
            print(f"rows fetch retry {dataset}@{offset}: {e}", flush=True)
            time.sleep(5 * (attempt + 1))
    return []


def caption_blip(client: httpx.Client, img_bytes: bytes) -> str | None:
    try:
        resp = client.post(f"{SERVER}/caption_file",
                           files={"image_file": ("img.webp", img_bytes, "image/webp")},
                           timeout=60)
        resp.raise_for_status()
        data = resp.json()
        for key in ("caption", "text", "generated_text", "result"):
            if isinstance(data.get(key), str) and data[key].strip():
                return data[key].strip()
    except Exception:
        pass
    return None


def collect(name: str, spec: dict, fetch_n: int, keep_n: int) -> list[dict]:
    from aesthetic_score import get_scorer

    scorer = get_scorer()
    assert scorer is not None
    out_dir = DATASET_ROOT / name
    out_dir.mkdir(parents=True, exist_ok=True)

    candidates = []
    seen_hashes = set()
    with httpx.Client() as client:
        offset = 0
        while len(candidates) < fetch_n and offset < 20000:
            rows = fetch_rows(client, spec["hf_dataset"], offset)
            if not rows:
                break
            offset += len(rows)
            for row in rows:
                r = row.get("row", {})
                img_info = r.get("image") or {}
                src = img_info.get("src")
                if not src:
                    continue
                if min(img_info.get("width") or 0, img_info.get("height") or 0) < spec["min_side"]:
                    continue
                try:
                    img_bytes = client.get(src, timeout=60).content
                    digest = hashlib.sha1(img_bytes).hexdigest()
                    if digest in seen_hashes:
                        continue
                    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                except Exception:
                    continue
                seen_hashes.add(digest)
                candidates.append({"image": img, "row": r, "sha1": digest})
                if len(candidates) >= fetch_n:
                    break
            print(f"{name}: {len(candidates)} candidates (offset {offset})", flush=True)

        print(f"{name}: scoring {len(candidates)} candidates", flush=True)
        embeds_all, scores_all = [], []
        for i in range(0, len(candidates), 16):
            batch = [c["image"] for c in candidates[i:i + 16]]
            emb, scores = scorer.embed_and_score(batch)
            embeds_all.append(emb)
            scores_all.extend(scores)
        embeds_all = np.concatenate([e.numpy() for e in embeds_all]) if embeds_all else np.empty((0, 768))
        for c, s in zip(candidates, scores_all):
            c["score"] = s

        order = np.argsort(scores_all)[::-1][:keep_n]
        kept = [candidates[i] for i in order]
        kept_embeds = embeds_all[list(order)]

        index = []
        for i, c in enumerate(kept):
            img = c["image"]
            img.thumbnail((1024, 1024))
            fname = f"{i:04d}.webp"
            buf = io.BytesIO()
            img.save(buf, format="WEBP", quality=92)
            (out_dir / fname).write_bytes(buf.getvalue())

            if spec["caption_mode"] == "dataset_text":
                caption = (c["row"].get("text") or "a modern logo").strip()
            else:
                blip = caption_blip(client, buf.getvalue())
                platform = c["row"].get("platform") or "web"
                caption = blip or f"clean modern {platform} application interface"
                caption = f"{platform} app ui screenshot, {caption}"
            caption = f"{spec['trigger']}, {caption}"
            (out_dir / f"{i:04d}.txt").write_text(caption)
            index.append({
                "file": fname, "caption": caption, "score": round(c["score"], 3),
                "sha1": c["sha1"], "source": spec["hf_dataset"], "embed_index": i,
            })

    np.save(out_dir / "embeddings.npy", kept_embeds)
    (out_dir / "index.jsonl").write_text("\n".join(json.dumps(r) for r in index))
    scores = [r["score"] for r in index]
    print(f"{name}: kept {len(index)} images, score mean={np.mean(scores):.2f} "
          f"min={min(scores):.2f} max={max(scores):.2f}", flush=True)
    return index


def upload_dataset_to_r2(name: str) -> int:
    from r2_upload import upload_bytes

    out_dir = DATASET_ROOT / name
    count = 0
    for path in sorted(out_dir.iterdir()):
        if path.suffix not in (".webp", ".txt", ".jsonl", ".npy"):
            continue
        ctype = {"webp": "image/webp", "txt": "text/plain",
                 "jsonl": "application/jsonl", "npy": "application/octet-stream"}[path.suffix[1:]]
        upload_bytes(f"lora_datasets/{name}/{path.name}", path.read_bytes(), ctype)
        count += 1

    # run_remote_training.py sends this archive URL to the worker. Build and
    # upload it in the same workflow as the individual files so a newly
    # provisioned (and billed) RunPod never starts against a missing archive.
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(out_dir.iterdir()):
            if path.suffix in (".webp", ".png", ".jpg", ".jpeg", ".txt"):
                zf.writestr(path.name, path.read_bytes())
    upload_bytes(f"lora_datasets/{name}.zip", archive.getvalue(), "application/zip")
    print(f"{name}: uploaded {count} files and lora_datasets/{name}.zip to R2", flush=True)
    return count


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["logos", "screens"])
    ap.add_argument("--fetch", type=int, default=400)
    ap.add_argument("--keep", type=int, default=160)
    ap.add_argument("--no-upload", action="store_true")
    args = ap.parse_args()

    targets = {"logos": "app_logo_maker", "screens": "product_screenshots"}
    names = [targets[args.only]] if args.only else list(targets.values())
    for name in names:
        collect(name, SPECS[name], args.fetch, args.keep)
        if not args.no_upload:
            upload_dataset_to_r2(name)


if __name__ == "__main__":
    main()
