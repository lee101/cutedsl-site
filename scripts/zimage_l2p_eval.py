#!/usr/bin/env python3
"""Run the L2P Z-Image pixel-space pipeline into local eval artifacts.

This uses the sibling T2I-L2P checkout by default:
  ../T2I-L2P

The pipeline is separate from the production diffusers/CuteZImage path and
loads the published zhen-nan/L2P merged 1K pixel-space DiT plus the official
Z-Image-Turbo tokenizer/text encoder.
"""

from __future__ import annotations

import argparse
import importlib.machinery
import json
import sys
import time
import types
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from PIL import Image


DEFAULT_PROMPTS = [
    "minecraft dirt block inventory icon, centered, crisp pixel game asset, plain background",
]


def install_l2p_import_shims() -> None:
    """Provide tiny shims for optional T2I-L2P import-time dependencies.

    The L2P inference path imports the whole diffsynth core package, including
    data-loader helpers and a ModelScope downloader. This eval uses only local
    paths plus Hugging Face downloads resolved before pipeline creation, so a
    full torchvision/modelscope install is unnecessary.
    """
    try:
        import torchvision  # noqa: F401
    except ModuleNotFoundError:
        from PIL import Image as PILImage

        functional = types.ModuleType("torchvision.transforms.functional")
        functional.__spec__ = importlib.machinery.ModuleSpec(
            "torchvision.transforms.functional",
            loader=None,
        )

        def resize(image, size, interpolation=None):
            height, width = size
            resampling = getattr(PILImage, "Resampling", PILImage).BILINEAR
            return image.resize((width, height), resampling)

        def center_crop(image, output_size):
            target_height, target_width = output_size
            width, height = image.size
            left = max(0, int(round((width - target_width) / 2.0)))
            top = max(0, int(round((height - target_height) / 2.0)))
            return image.crop((left, top, left + target_width, top + target_height))

        functional.resize = resize
        functional.center_crop = center_crop

        transforms = types.ModuleType("torchvision.transforms")
        transforms.__spec__ = importlib.machinery.ModuleSpec("torchvision.transforms", loader=None)
        transforms.functional = functional
        transforms.InterpolationMode = types.SimpleNamespace(BILINEAR="bilinear")

        torchvision = types.ModuleType("torchvision")
        torchvision.__spec__ = importlib.machinery.ModuleSpec("torchvision", loader=None, is_package=True)
        torchvision.transforms = transforms
        sys.modules["torchvision"] = torchvision
        sys.modules["torchvision.transforms"] = transforms
        sys.modules["torchvision.transforms.functional"] = functional

    try:
        import modelscope  # noqa: F401
    except ModuleNotFoundError:
        modelscope = types.ModuleType("modelscope")
        modelscope.__spec__ = importlib.machinery.ModuleSpec("modelscope", loader=None, is_package=True)

        def snapshot_download(model_id, *args, **kwargs):
            from huggingface_hub import snapshot_download as hf_snapshot_download

            allow_patterns = kwargs.pop("allow_file_pattern", None)
            ignore_patterns = kwargs.pop("ignore_file_pattern", None)
            kwargs.pop("local_files_only", None)
            return hf_snapshot_download(
                repo_id=model_id,
                allow_patterns=allow_patterns,
                ignore_patterns=ignore_patterns,
                *args,
                **kwargs,
            )

        modelscope.snapshot_download = snapshot_download
        sys.modules["modelscope"] = modelscope


def now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def parse_steps(raw: str) -> list[int]:
    steps = []
    for part in raw.split(","):
        value = int(part.strip())
        if value <= 0:
            raise argparse.ArgumentTypeError("steps must be positive integers")
        steps.append(value)
    return sorted(set(steps))


def image_metrics(reference: Image.Image, candidate: Image.Image) -> dict[str, float]:
    ref = np.asarray(reference.convert("RGB"), dtype=np.float32)
    cand = np.asarray(candidate.convert("RGB"), dtype=np.float32)
    delta = ref - cand
    mse = float(np.mean(delta * delta))
    mae = float(np.mean(np.abs(delta)))
    psnr = float("inf") if mse == 0.0 else float(20.0 * np.log10(255.0 / np.sqrt(mse)))
    return {"mse": mse, "mae": mae, "psnr": psnr}


def resolve_l2p_paths(main_model_path: str | None, zimage_dir: str | None) -> tuple[str, list[str], str]:
    from huggingface_hub import hf_hub_download, snapshot_download

    if main_model_path:
        main_model = main_model_path
    else:
        main_model = hf_hub_download(repo_id="zhen-nan/L2P", filename="model-1k-merge.safetensors")

    if zimage_dir:
        z_dir = Path(zimage_dir)
    else:
        z_dir = Path(snapshot_download(
            repo_id="Tongyi-MAI/Z-Image-Turbo",
            allow_patterns=["text_encoder/*", "tokenizer/*"],
        ))

    text_encoder_paths = sorted(str(path) for path in (z_dir / "text_encoder").glob("model-*.safetensors"))
    tokenizer_path = str(z_dir / "tokenizer")
    if not text_encoder_paths:
        raise FileNotFoundError(f"no text_encoder/model-*.safetensors found under {z_dir}")
    if not Path(tokenizer_path).exists():
        raise FileNotFoundError(f"tokenizer directory not found under {z_dir}")
    return main_model, text_encoder_paths, tokenizer_path


@torch.no_grad()
def run_l2p_steps(
    pipe,
    *,
    prompt: str,
    negative_prompt: str,
    cfg_scale: float,
    height: int,
    width: int,
    seed: int,
    rand_device: str,
    num_inference_steps: int,
    start_step: int = 0,
    start_latents: torch.Tensor | None = None,
    cached_inputs: dict | None = None,
    capture_step: int | None = None,
) -> tuple[Image.Image, dict, dict | None]:
    """Run L2P with optional exact-prompt latent replay.

    L2P uses pixel-space tensors as latents. This mirrors
    diffsynth.pipelines.z_image_L2P.ZImagePipeline.__call__, but exposes the
    intermediate tensor after a denoising step so a second call can resume from
    the next step. It is exact-prompt replay, not cross-prompt visual-unit
    teleportation.
    """
    from tqdm import tqdm

    pipe.scheduler.set_timesteps(num_inference_steps, denoising_strength=1.0)
    captured: dict | None = None

    if cached_inputs is None:
        inputs_posi = {"prompt": prompt}
        inputs_nega = {"negative_prompt": negative_prompt}
        inputs_shared = {
            "cfg_scale": cfg_scale,
            "input_image": None,
            "denoising_strength": 1.0,
            "height": height,
            "width": width,
            "seed": seed,
            "rand_device": rand_device,
            "num_inference_steps": num_inference_steps,
        }
        for unit in pipe.units:
            inputs_shared, inputs_posi, inputs_nega = pipe.unit_runner(unit, pipe, inputs_shared, inputs_posi, inputs_nega)
    else:
        inputs_shared = dict(cached_inputs["inputs_shared"])
        inputs_posi = dict(cached_inputs["inputs_posi"])
        inputs_nega = dict(cached_inputs["inputs_nega"])

    if start_latents is not None:
        inputs_shared["latents"] = start_latents.to(device=pipe.device, dtype=torch.float32)

    pipe.load_models_to_device(pipe.in_iteration_models)
    models = {name: getattr(pipe, name) for name in pipe.in_iteration_models}
    timesteps = pipe.scheduler.timesteps[start_step:]
    for offset, timestep in enumerate(tqdm(timesteps, disable=True)):
        progress_id = start_step + offset
        timestep = timestep.unsqueeze(0).to(dtype=pipe.torch_dtype, device=pipe.device)
        noise_pred = pipe.cfg_guided_model_fn(
            pipe.model_fn,
            cfg_scale,
            inputs_shared,
            inputs_posi,
            inputs_nega,
            **models,
            timestep=timestep,
            progress_id=progress_id,
        )
        inputs_shared["latents"] = pipe.step(
            pipe.scheduler,
            progress_id=progress_id,
            noise_pred=noise_pred.float(),
            **inputs_shared,
        )
        if capture_step is not None and progress_id == capture_step:
            captured = {
                "latents": inputs_shared["latents"].detach().clone().cpu(),
                "resume_step": progress_id + 1,
                "inputs_shared": dict(inputs_shared),
                "inputs_posi": dict(inputs_posi),
                "inputs_nega": dict(inputs_nega),
            }

    image = pipe.pixel_output_to_image(inputs_shared["latents"])
    pipe.load_models_to_device([])
    return image, inputs_shared, captured


def install_l2p_model_fn_dtype_patch(pipe) -> None:
    from einops import rearrange

    def model_fn_z_image_l2p_eval(
        dit,
        latents=None,
        timestep=None,
        prompt_embeds=None,
        use_gradient_checkpointing=False,
        use_gradient_checkpointing_offload=False,
        **kwargs,
    ):
        latents = [rearrange(latents.to(pipe.torch_dtype), "B C H W -> C B H W")]
        timestep = (1000 - timestep) / 1000
        model_output = dit(
            latents,
            timestep,
            prompt_embeds,
            patch_size=16,
            use_gradient_checkpointing=use_gradient_checkpointing,
            use_gradient_checkpointing_offload=use_gradient_checkpointing_offload,
        )[0][0]
        return rearrange(-model_output, "C B H W -> B C H W")

    pipe.model_fn = model_fn_z_image_l2p_eval


def hydrate_l2p_root_parameters(pipe, main_model: str) -> None:
    from safetensors import safe_open

    with safe_open(main_model, framework="pt", device="cpu") as tensors:
        for name in ("x_pad_token", "cap_pad_token"):
            value = tensors.get_tensor(name).to(device=pipe.device, dtype=pipe.torch_dtype)
            setattr(pipe.dit, name, torch.nn.Parameter(value))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-path", default="../T2I-L2P", help="sibling T2I-L2P checkout")
    parser.add_argument("--output-dir", default="evals")
    parser.add_argument("--main-model-path", default=None, help="local model-1k-merge.safetensors")
    parser.add_argument("--zimage-dir", default=None, help="local Tongyi-MAI/Z-Image-Turbo snapshot")
    parser.add_argument("--prompt", action="append", default=[])
    parser.add_argument("--steps", type=parse_steps, default=parse_steps("20"))
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--cfg-scale", type=float, default=2.0)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dtype", choices=["bfloat16", "float16", "float32"], default="bfloat16")
    parser.add_argument("--vram-limit", type=float, default=None)
    parser.add_argument("--no-disk-offload", action="store_true", help="disable T2I-L2P disk-backed VRAM management for the L2P DiT")
    parser.add_argument("--teleport", action="store_true", help="also run exact-prompt L2P latent replay")
    parser.add_argument("--teleport-capture-step", type=int, default=None, help="step index to capture; default is about one third through")
    parser.add_argument("--teleport-replays", type=int, default=1)
    args = parser.parse_args()

    repo_path = Path(args.repo_path).resolve()
    if not repo_path.exists():
        raise FileNotFoundError(f"T2I-L2P repo not found: {repo_path}")
    sys.path.insert(0, str(repo_path))

    install_l2p_import_shims()

    from diffsynth.configs import VRAM_MANAGEMENT_MODULE_MAPS
    from diffsynth.pipelines.z_image_L2P import ModelConfig, ZImagePipeline

    VRAM_MANAGEMENT_MODULE_MAPS.setdefault(
        "diffsynth.models.z_image_dit_L2P.ZImageDiT",
        {
            "torch.nn.Linear": "diffsynth.core.vram.layers.AutoWrappedLinear",
            "torch.nn.Conv2d": "diffsynth.core.vram.layers.AutoWrappedModule",
            "torch.nn.ConvTranspose2d": "diffsynth.core.vram.layers.AutoWrappedModule",
            "torch.nn.Embedding": "diffsynth.core.vram.layers.AutoWrappedModule",
            "torch.nn.RMSNorm": "diffsynth.core.vram.layers.AutoWrappedModule",
        },
    )

    dtype = {
        "bfloat16": torch.bfloat16,
        "float16": torch.float16,
        "float32": torch.float32,
    }[args.dtype]

    run_dir = Path(args.output_dir) / f"zimage_l2p_{now_slug()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    prompts = args.prompt or DEFAULT_PROMPTS

    main_model, text_encoder_paths, tokenizer_path = resolve_l2p_paths(args.main_model_path, args.zimage_dir)
    use_disk_offload = args.vram_limit is not None and not args.no_disk_offload
    dit_config_kwargs = {}
    if use_disk_offload:
        dit_config_kwargs = {
            "offload_dtype": "disk",
            "offload_device": "disk",
            "onload_dtype": "disk",
            "onload_device": "disk",
            "preparing_dtype": dtype,
            "preparing_device": args.device,
            "computation_dtype": dtype,
            "computation_device": args.device,
        }

    load_t0 = time.perf_counter()
    pipe = ZImagePipeline.from_pretrained(
        torch_dtype=dtype,
        device=args.device,
        model_configs=[
            ModelConfig(path=[main_model], **dit_config_kwargs),
            ModelConfig(path=text_encoder_paths),
        ],
        tokenizer_config=ModelConfig(path=tokenizer_path),
        vram_limit=args.vram_limit,
    )
    if use_disk_offload:
        hydrate_l2p_root_parameters(pipe, main_model)
        install_l2p_model_fn_dtype_patch(pipe)
    load_s = time.perf_counter() - load_t0

    rows = []
    for prompt_index, prompt in enumerate(prompts):
        seed = args.seed + prompt_index
        for step in args.steps:
            started = time.perf_counter()
            capture_step = None
            if args.teleport:
                requested_capture = args.teleport_capture_step
                capture_step = requested_capture if requested_capture is not None else max(0, min(step - 2, round(step * 0.35)))
            image, _inputs, captured = run_l2p_steps(
                pipe,
                prompt=prompt,
                negative_prompt="",
                cfg_scale=args.cfg_scale,
                height=args.height,
                width=args.width,
                seed=seed,
                rand_device=args.device,
                num_inference_steps=step,
                capture_step=capture_step,
            )
            elapsed = time.perf_counter() - started
            image_path = run_dir / f"l2p_prompt{prompt_index:02d}_step{step:02d}_seed{seed}.png"
            image.save(image_path)
            row = {
                "prompt_index": prompt_index,
                "prompt": prompt,
                "step": step,
                "seed": seed,
                "wall_s": elapsed,
                "image_path": str(image_path),
            }
            rows.append(row)
            print(json.dumps(row, sort_keys=True))

            if args.teleport and captured is not None:
                prime_path = run_dir / f"l2p_prompt{prompt_index:02d}_step{step:02d}_prime_capture{capture_step}_seed{seed}.png"
                image.save(prime_path)
                for replay_idx in range(args.teleport_replays):
                    replay_started = time.perf_counter()
                    replay_image, _replay_inputs, _ = run_l2p_steps(
                        pipe,
                        prompt=prompt,
                        negative_prompt="",
                        cfg_scale=args.cfg_scale,
                        height=args.height,
                        width=args.width,
                        seed=seed,
                        rand_device=args.device,
                        num_inference_steps=step,
                        start_step=int(captured["resume_step"]),
                        start_latents=captured["latents"],
                        cached_inputs=captured,
                    )
                    replay_elapsed = time.perf_counter() - replay_started
                    replay_path = run_dir / (
                        f"l2p_prompt{prompt_index:02d}_step{step:02d}_replay{replay_idx:02d}"
                        f"_from{captured['resume_step']}_seed{seed}.png"
                    )
                    replay_image.save(replay_path)
                    replay_row = {
                        "prompt_index": prompt_index,
                        "prompt": prompt,
                        "step": step,
                        "seed": seed,
                        "wall_s": replay_elapsed,
                        "image_path": str(replay_path),
                        "mode": "teleport_replay",
                        "capture_step": capture_step,
                        "resume_step": captured["resume_step"],
                        "refinement_steps": step - int(captured["resume_step"]),
                        **image_metrics(image, replay_image),
                    }
                    rows.append(replay_row)
                    print(json.dumps(replay_row, sort_keys=True))

    report = {
        "repo_path": str(repo_path),
        "main_model": main_model,
        "text_encoder_paths": text_encoder_paths,
        "tokenizer_path": tokenizer_path,
        "load_s": load_s,
        "width": args.width,
        "height": args.height,
        "cfg_scale": args.cfg_scale,
        "device": args.device,
        "dtype": args.dtype,
        "disk_offload": use_disk_offload,
        "steps": args.steps,
        "teleport": args.teleport,
        "rows": rows,
    }
    (run_dir / "results.json").write_text(json.dumps(report, indent=2))
    (run_dir / "report.md").write_text(
        "# Z-Image L2P Eval\n\n"
        f"- repo: `{repo_path}`\n"
        f"- load time: `{load_s:.3f}s`\n"
        f"- cfg scale: `{args.cfg_scale}`\n"
        f"- size: `{args.width}x{args.height}`\n\n"
        f"- disk offload: `{use_disk_offload}`\n"
        f"- teleport: `{args.teleport}`\n\n"
        "| Mode | Prompt | Step | Wall s | MSE | PSNR | Image |\n"
        "| --- | --- | ---: | ---: | ---: | ---: | --- |\n"
        + "\n".join(
            f"| `{row.get('mode', 'baseline')}` | `{row['prompt'][:72]}` | {row['step']} | "
            f"{row['wall_s']:.3f} | {row.get('mse', '')} | {row.get('psnr', '')} | "
            f"[{Path(row['image_path']).name}]({Path(row['image_path']).name}) |"
            for row in rows
        )
        + "\n"
    )
    print(run_dir / "report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
