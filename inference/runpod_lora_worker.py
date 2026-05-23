"""One-shot RunPod LoRA training worker.

This file is intentionally standalone: the manager base64-encodes it into a
fresh RunPod pod so the pod does not need this repository pre-mounted.
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys
import time
import traceback
import zipfile
from pathlib import Path


def _env_json(name: str) -> dict:
    value = os.getenv(name, "")
    if not value:
        return {}
    return json.loads(base64.b64decode(value).decode("utf-8"))


JOB = _env_json("LORA_TRAINING_JOB_JSON_B64")
JOB_ID = JOB.get("job_id") or os.getenv("LORA_TRAINING_JOB_ID") or "unknown"
STATUS_PREFIX = os.getenv("LORA_TRAINING_STATUS_PREFIX", "cutedsl/training-jobs")


def _s3_client():
    import boto3

    endpoint = os.getenv("R2_ENDPOINT_URL") or os.getenv("R2_ENDPOINT")
    return boto3.session.Session().client("s3", endpoint_url=endpoint)


def _bucket() -> str:
    return os.getenv("R2_BUCKET", "appstatic")


def _public_base() -> str:
    return os.getenv("R2_PUBLIC_BASE_URL") or os.getenv("R2_PUBLIC_HOST", "appstatic.app.nz")


def _upload_bytes(key: str, data: bytes, content_type: str) -> str:
    _s3_client().put_object(
        Bucket=_bucket(),
        Key=key,
        Body=data,
        ACL="public-read",
        ContentType=content_type,
    )
    return f"https://{_public_base()}/{key}"


def status(**updates) -> None:
    body = {
        "job_id": JOB_ID,
        "backend": "runpod",
        "updated_at": time.time(),
        **updates,
    }
    key = f"{STATUS_PREFIX}/{JOB_ID}.json"
    _upload_bytes(key, json.dumps(body, sort_keys=True).encode("utf-8"), "application/json")
    print(json.dumps({k: body.get(k) for k in ("job_id", "status", "progress", "loss", "error")}), flush=True)


def _download_dataset(workdir: Path) -> list[tuple[Path, str]]:
    import httpx

    dataset_dir = workdir / "dataset"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    image_urls = JOB.get("image_urls") or []
    captions = JOB.get("captions") or []
    saved: list[tuple[Path, str]] = []
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        for i, url in enumerate(image_urls):
            r = client.get(url)
            r.raise_for_status()
            ct = r.headers.get("content-type", "").lower()
            ext = "png" if "png" in ct else "webp" if "webp" in ct else "jpg"
            path = dataset_dir / f"img_{i:04d}.{ext}"
            path.write_bytes(r.content)
            caption = captions[i] if i < len(captions) else "a photo"
            (dataset_dir / f"img_{i:04d}.txt").write_text(caption)
            saved.append((path, caption))
            status(status="downloading_dataset", progress=0.02 + 0.08 * ((i + 1) / max(len(image_urls), 1)), image_count=len(saved))
    if not saved:
        raise RuntimeError("no images could be downloaded")
    return saved


def _train_zimage(workdir: Path, dataset: list[tuple[Path, str]]) -> Path:
    import gc
    import numpy as np
    import torch
    from diffusers import ZImagePipeline
    from peft import LoraConfig, get_peft_model
    from PIL import Image as PILImage

    device = os.getenv("DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
    dtype_name = os.getenv("DTYPE", "bfloat16")
    dtype = getattr(torch, dtype_name, torch.bfloat16)

    status(status="loading_model", progress=0.1, image_count=len(dataset))
    pipe = ZImagePipeline.from_pretrained(
        os.getenv("ZIMAGE_MODEL_PATH", "Tongyi-MAI/Z-Image-Turbo"),
        torch_dtype=dtype,
    )
    for name in ("transformer", "vae", "text_encoder"):
        comp = getattr(pipe, name, None)
        if comp is not None:
            comp.to(device)

    transformer = pipe.transformer
    vae = pipe.vae
    for p in transformer.parameters():
        p.requires_grad = False
    for p in vae.parameters():
        p.requires_grad = False

    status(status="preparing_lora", progress=0.18)
    transformer = get_peft_model(
        transformer,
        LoraConfig(
            r=int(JOB.get("lora_r") or 16),
            lora_alpha=int(JOB.get("lora_alpha") or 32),
            target_modules=["to_q", "to_k", "to_v"],
            lora_dropout=0.0,
            bias="none",
        ),
    )
    pipe.transformer = transformer
    transformer.train()
    trainable = [p for p in transformer.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(trainable, lr=float(JOB.get("learning_rate") or 1e-4))

    prompt_cache: dict[str, object] = {}
    with torch.no_grad():
        for caption in sorted({cap for _, cap in dataset}):
            try:
                prompt_cache[caption] = pipe._encode_prompt(prompt=[caption], device=device, max_sequence_length=256)
            except Exception:
                prompt_cache[caption] = None

    train_size = int(os.getenv("LORA_TRAIN_SIZE", "384"))
    latents: list[tuple[torch.Tensor, str]] = []
    status(status="encoding_dataset", progress=0.25)
    with torch.no_grad():
        for path, caption in dataset:
            image = PILImage.open(path).convert("RGB").resize((train_size, train_size))
            arr = np.asarray(image, dtype=np.float32) / 127.5 - 1.0
            tensor = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0).to(device, dtype=dtype)
            latent = vae.encode(tensor).latent_dist.sample() * vae.config.scaling_factor
            latents.append((latent.detach(), caption))
            del tensor
    if not latents:
        raise RuntimeError("no latents could be encoded")

    total_steps = min(int(JOB.get("num_steps") or 500), int(os.getenv("LORA_MAX_STEPS", "5000")))
    successful_steps = 0
    last_loss = None
    status(status="training", progress=0.3)
    for step in range(total_steps):
        latent, caption = latents[step % len(latents)]
        prompt_embeds = prompt_cache.get(caption)
        if prompt_embeds is None:
            continue
        try:
            t_sample = torch.rand(1, device=device).to(dtype)
            timestep = t_sample.expand(1)
            noise = torch.randn_like(latent)
            x_t = (1.0 - t_sample) * noise + t_sample * latent
            target = latent - noise
            x_in = x_t.unsqueeze(2)
            out = transformer(list(x_in.unbind(0)), timestep, prompt_embeds, return_dict=False)[0]
            pred = torch.stack(out, dim=0).squeeze(2)
            loss = torch.nn.functional.mse_loss(pred.float(), target.float())
            loss.backward()
            optimizer.step()
            optimizer.zero_grad()
            successful_steps += 1
            last_loss = float(loss.item())
            if step % 5 == 0 or step == total_steps - 1:
                status(status="training", progress=0.3 + 0.62 * ((step + 1) / total_steps), loss=last_loss, successful_steps=successful_steps)
            del loss, pred, out, x_t, noise, target, x_in
        except torch.cuda.OutOfMemoryError:
            optimizer.zero_grad(set_to_none=True)
            torch.cuda.empty_cache()
            gc.collect()
    if successful_steps == 0:
        raise RuntimeError("no training steps succeeded")

    out_dir = workdir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    transformer.save_pretrained(out_dir)
    status(status="uploading_artifacts", progress=0.95, loss=last_loss, successful_steps=successful_steps)
    return out_dir


def _upload_artifacts(out_dir: Path) -> dict[str, str]:
    urls: dict[str, str] = {}
    adapter = out_dir / "adapter_model.safetensors"
    config = out_dir / "adapter_config.json"
    if adapter.exists():
        urls["adapter_url"] = _upload_bytes(f"cutedsl/loras/{JOB_ID}/{adapter.name}", adapter.read_bytes(), "application/octet-stream")
        urls["output_url"] = urls["adapter_url"]
    if config.exists():
        urls["config_url"] = _upload_bytes(f"cutedsl/loras/{JOB_ID}/{config.name}", config.read_bytes(), "application/json")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in out_dir.iterdir():
            if path.is_file():
                zf.write(path, path.name)
    urls["artifact_url"] = _upload_bytes(f"cutedsl/loras/{JOB_ID}/{JOB_ID}.zip", buf.getvalue(), "application/zip")
    return urls


def main() -> int:
    workdir = Path(os.getenv("LORA_WORKDIR", "/workspace/cutedsl-lora-worker"))
    workdir.mkdir(parents=True, exist_ok=True)
    status(status="starting", progress=0.0)
    try:
        if JOB.get("model", "zimage") != "zimage":
            raise RuntimeError("RunPod worker currently supports zimage LoRA training")
        dataset = _download_dataset(workdir)
        out_dir = _train_zimage(workdir, dataset)
        urls = _upload_artifacts(out_dir)
        status(status="completed", progress=1.0, **urls)
        return 0
    except Exception as exc:
        status(status="failed", progress=1.0, error=str(exc), traceback=traceback.format_exc()[-4000:])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
