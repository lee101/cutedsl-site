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


JOB: dict = {}
JOB_ID = "unknown"
STATUS_PREFIX = os.getenv("LORA_TRAINING_STATUS_PREFIX", "cutedsl/training-jobs")


def configure_job(job: dict | None = None) -> None:
    global JOB, JOB_ID, STATUS_PREFIX
    JOB = job or _env_json("LORA_TRAINING_JOB_JSON_B64")
    JOB_ID = JOB.get("job_id") or os.getenv("LORA_TRAINING_JOB_ID") or "unknown"
    STATUS_PREFIX = JOB.get("status_prefix") or os.getenv("LORA_TRAINING_STATUS_PREFIX", "cutedsl/training-jobs")


configure_job()


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
    try:
        _upload_bytes(key, json.dumps(body, sort_keys=True).encode("utf-8"), "application/json")
    except Exception as e:
        print(f"status upload failed (non-fatal): {e}", flush=True)
    print(json.dumps({k: body.get(k) for k in ("job_id", "status", "progress", "loss", "error")}), flush=True)


def _download_dataset(workdir: Path) -> list[tuple[Path, str]]:
    import httpx

    dataset_dir = workdir / "dataset"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    captions = JOB.get("captions") or []

    zip_url = JOB.get("dataset_zip_url")
    if zip_url:
        import io as _io
        import zipfile
        with httpx.Client(timeout=httpx.Timeout(300.0, connect=30.0), follow_redirects=True) as client:
            for attempt in range(5):
                try:
                    r = client.get(zip_url)
                    r.raise_for_status()
                    break
                except Exception as e:
                    print(f"zip download attempt {attempt+1} failed: {e}", flush=True)
                    time.sleep(10 * (attempt + 1))
            else:
                raise RuntimeError("dataset zip download failed after retries")
        zipfile.ZipFile(_io.BytesIO(r.content)).extractall(dataset_dir)
        saved = []
        for img in sorted(dataset_dir.rglob("*")):
            if img.suffix.lower() not in (".webp", ".png", ".jpg", ".jpeg"):
                continue
            txt = img.with_suffix(".txt")
            saved.append((img, txt.read_text().strip() if txt.exists() else "a photo"))
        if not saved:
            raise RuntimeError("dataset zip contained no images")
        status(status="downloading_dataset", progress=0.1, image_count=len(saved))
        return saved

    image_urls = JOB.get("image_urls") or []
    saved: list[tuple[Path, str]] = []
    failed = 0
    with httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0), follow_redirects=True) as client:
        for i, url in enumerate(image_urls):
            r = None
            for attempt in range(3):
                try:
                    r = client.get(url)
                    r.raise_for_status()
                    break
                except Exception as e:
                    print(f"download {i} attempt {attempt+1} failed: {e}", flush=True)
                    time.sleep(3 * (attempt + 1))
                    r = None
            if r is None:
                failed += 1
                continue
            ct = r.headers.get("content-type", "").lower()
            ext = "png" if "png" in ct else "webp" if "webp" in ct else "jpg"
            path = dataset_dir / f"img_{i:04d}.{ext}"
            path.write_bytes(r.content)
            caption = captions[i] if i < len(captions) else "a photo"
            (dataset_dir / f"img_{i:04d}.txt").write_text(caption)
            saved.append((path, caption))
            if (i + 1) % 10 == 0 or i + 1 == len(image_urls):
                status(status="downloading_dataset", progress=0.02 + 0.08 * ((i + 1) / max(len(image_urls), 1)), image_count=len(saved))
    if not saved:
        raise RuntimeError("no images could be downloaded")
    if failed:
        print(f"skipped {failed} images after retries", flush=True)
    return saved


def _filter_texture_dataset(dataset: list[tuple[Path, str]]) -> list[tuple[Path, str]]:
    """Reject visible-seam examples before a texture LoRA can learn them."""
    if JOB.get("dataset_mode", "standard") != "texture":
        return dataset
    import math
    import numpy as np
    from PIL import Image as PILImage

    threshold = float(JOB.get("min_tileability") or 0.72)
    accepted: list[tuple[Path, str]] = []
    scores: list[float] = []
    for path, caption in dataset:
        rgb = np.asarray(PILImage.open(path).convert("RGB"), dtype=np.float32) / 255.0
        axis_scores = []
        for axis in (0, 1):
            delta = np.abs(np.diff(rgb, axis=axis))
            ordinary = float(np.mean(delta)) + 1e-6
            if axis == 0:
                wrap = np.abs(rgb[0] - rgb[-1])
                first = rgb[1] - rgb[0]
                last = rgb[-1] - rgb[-2]
            else:
                wrap = np.abs(rgb[:, 0] - rgb[:, -1])
                first = rgb[:, 1] - rgb[:, 0]
                last = rgb[:, -1] - rgb[:, -2]
            ratio = float(np.mean(wrap)) / ordinary
            colour_score = math.exp(-max(0.0, ratio - 1.5))
            ordinary_grad = float(np.mean(np.abs(np.diff(delta, axis=axis)))) + 1e-6
            grad_ratio = float(np.mean(np.abs(first - last))) / ordinary_grad
            gradient_score = math.exp(-max(0.0, grad_ratio - 2.0) * 0.5)
            axis_scores.extend((colour_score, gradient_score))
        values = np.maximum(np.asarray(axis_scores, dtype=np.float64), 1e-9)
        score = float(np.prod(values) ** 0.25) * (0.8 + 0.2 * float(np.min(values)))
        scores.append(score)
        if score >= threshold:
            tile_caption = caption if "seamless" in caption.lower() else f"seamless tileable texture, {caption}"
            accepted.append((path, tile_caption))
    status(
        status="verifying_dataset",
        progress=0.1,
        checked=len(dataset),
        accepted=len(accepted),
        mean_tileability=(sum(scores) / len(scores)) if scores else 0,
        min_tileability=threshold,
    )
    if len(accepted) < 2:
        raise RuntimeError("texture training needs at least two tiles that pass the tileability gate")
    return accepted


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

    transformer = pipe.transformer
    vae = pipe.vae
    for p in transformer.parameters():
        p.requires_grad = False
    for p in vae.parameters():
        p.requires_grad = False

    def _free():
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    # Stage components on GPU one at a time — full pipeline does not fit
    # smaller pods. Text encode first, then drop the encoder before training.
    status(status="encoding_prompts", progress=0.14)
    text_encoder = getattr(pipe, "text_encoder", None)
    if text_encoder is not None:
        text_encoder.to(device)
    prompt_cache: dict[str, object] = {}
    first_encode_error = None
    with torch.no_grad():
        for caption in sorted({cap for _, cap in dataset}):
            try:
                prompt_cache[caption] = pipe._encode_prompt(prompt=[caption], device=device, max_sequence_length=256)
            except Exception as e:
                if first_encode_error is None:
                    first_encode_error = f"{type(e).__name__}: {e}"
                prompt_cache[caption] = None
    if all(v is None for v in prompt_cache.values()):
        raise RuntimeError(f"all caption encodes failed; first error: {first_encode_error}")
    if text_encoder is not None:
        text_encoder.to("cpu")
    _free()

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

    train_size = int(os.getenv("LORA_TRAIN_SIZE", "384"))
    latents: list[tuple[torch.Tensor, str]] = []
    status(status="encoding_dataset", progress=0.25)
    vae.to(device)
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
    vae.to("cpu")
    _free()
    transformer.to(device)

    total_steps = min(int(JOB.get("num_steps") or 500), int(os.getenv("LORA_MAX_STEPS", "5000")))
    successful_steps = 0
    last_loss = None
    first_step_error = None
    status(status="training", progress=0.3)
    for step in range(total_steps):
        latent, caption = latents[step % len(latents)]
        prompt_embeds = prompt_cache.get(caption)
        if prompt_embeds is None:
            continue
        try:
            train_latent = latent
            if JOB.get("dataset_mode", "standard") == "texture":
                shift_y = int(torch.randint(0, latent.shape[-2], (1,)).item())
                shift_x = int(torch.randint(0, latent.shape[-1], (1,)).item())
                train_latent = torch.roll(latent, shifts=(shift_y, shift_x), dims=(-2, -1))
            t_sample = torch.rand(1, device=device).to(dtype)
            timestep = t_sample.expand(1)
            noise = torch.randn_like(train_latent)
            x_t = (1.0 - t_sample) * noise + t_sample * train_latent
            target = train_latent - noise
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
        except torch.cuda.OutOfMemoryError as e:
            if first_step_error is None:
                first_step_error = f"OOM: {e}"
            optimizer.zero_grad(set_to_none=True)
            torch.cuda.empty_cache()
            gc.collect()
    if successful_steps == 0:
        raise RuntimeError(f"no training steps succeeded; first step error: {first_step_error}")

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


def run_training() -> dict:
    workdir = Path(os.getenv("LORA_WORKDIR", "/workspace/cutedsl-lora-worker"))
    workdir.mkdir(parents=True, exist_ok=True)
    status(status="starting", progress=0.0)
    try:
        if JOB.get("model", "zimage") != "zimage":
            raise RuntimeError("RunPod worker currently supports zimage LoRA training")
        dataset = _download_dataset(workdir)
        dataset = _filter_texture_dataset(dataset)
        out_dir = _train_zimage(workdir, dataset)
        urls = _upload_artifacts(out_dir)
        status(status="completed", progress=1.0, **urls)
        return {"job_id": JOB_ID, "status": "completed", "progress": 1.0, **urls}
    except Exception as exc:
        error = str(exc)
        trace = traceback.format_exc()[-4000:]
        status(status="failed", progress=1.0, error=error, traceback=trace)
        return {"job_id": JOB_ID, "status": "failed", "progress": 1.0, "error": error, "traceback": trace}


def handler(event) -> dict:
    configure_job((event or {}).get("input") or {})
    return run_training()


def main() -> int:
    result = run_training()
    return 0 if result.get("status") == "completed" else 1


if __name__ == "__main__":
    if os.getenv("RUNPOD_SERVERLESS", "0") == "1":
        import runpod

        runpod.serverless.start({"handler": handler})
    else:
        raise SystemExit(main())
