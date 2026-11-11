"""Rebuild product_screenshots captions from wave-ui-25k metadata (hash-matched)."""
import hashlib, io, json, time
from pathlib import Path
import httpx

DS = "agentsea/wave-ui-25k"
API = "https://datasets-server.huggingface.co/rows"
ds_dir = Path(__file__).parent / "lora_datasets" / "product_screenshots"

index = [json.loads(l) for l in (ds_dir / "index.jsonl").read_text().splitlines()]
by_sha = {r["sha1"]: r for r in index}
found = {}
with httpx.Client() as client:
    offset = 0
    while len(found) < len(by_sha) and offset < 600:
        for attempt in range(3):
            try:
                rows = client.get(API, params={"dataset": DS, "config": "default",
                                               "split": "train", "offset": offset,
                                               "length": 100}, timeout=60).json().get("rows", [])
                break
            except Exception as e:
                print("retry", offset, e); time.sleep(5)
        else:
            rows = []
        if not rows:
            break
        for row in rows:
            r = row["row"]
            src = (r.get("image") or {}).get("src")
            if not src:
                continue
            try:
                digest = hashlib.sha1(client.get(src, timeout=60).content).hexdigest()
            except Exception:
                continue
            if digest in by_sha and digest not in found:
                found[digest] = r
        offset += 100
        print(f"offset {offset}: matched {len(found)}/{len(by_sha)}", flush=True)

updated = 0
for sha, r in found.items():
    entry = by_sha[sha]
    platform = r.get("platform") or "web"
    bits = [b for b in (r.get("name"), r.get("purpose")) if b]
    detail = ", ".join(bits)[:160]
    caption = f"prodshot, {platform} app ui screenshot"
    if detail:
        caption += f", interface featuring {detail}"
    if (r.get("language") or "English") != "English":
        caption += f", {r['language']} language"
    entry["caption"] = caption
    (ds_dir / entry["file"].replace(".webp", ".txt")).write_text(caption)
    updated += 1
(ds_dir / "index.jsonl").write_text("\n".join(json.dumps(r) for r in index))
print("updated", updated, "captions")
