# Z-Image L2P Evaluation Plan

## What Was Cloned

- `/nvme0n1-disk/code/z-image-6b-pixel-space`
  - Hugging Face Space for `multimodalart/z-image-6b-pixel-space`.
  - Commit inspected: `37b081d`.
- `/nvme0n1-disk/code/T2I-L2P`
  - Upstream research repo `TencentYoutuResearch/T2I-L2P`.
  - Commit inspected: `c5d57bd`.

## Current Read

L2P is not a scheduler swap for the existing production Z-Image pipeline.
It is a separate pixel-space DiT pipeline:

- It loads `zhen-nan/L2P/model-1k-merge.safetensors` for the pixel-space DiT.
- It reuses Z-Image-Turbo's tokenizer and text encoder.
- It outputs pixels directly from `ZImageDiT.local_decoder`, so there is no VAE
  decode step to optimize or compare in isolation.
- The demo defaults to `30` steps and `cfg_scale=2.0`; our speed target should
  first test `4,8,12,16,20` and treat `20` as the local gold/reference set.

## Eval Commands

Existing production/CuteZImage step sweep, writing 10 local images by default:

```bash
/nvme0n1-disk/code/.venv/bin/python scripts/zimage_step_eval.py \
  --base-url http://127.0.0.1:8100 \
  --steps 4,8,12,16,20
```

L2P pixel-space eval against the sibling checkout:

```bash
/nvme0n1-disk/code/.venv/bin/python scripts/zimage_l2p_eval.py \
  --repo-path ../T2I-L2P \
  --steps 20 \
  --vram-limit 16
```

L2P exact-prompt replay eval:

```bash
/nvme0n1-disk/code/.venv/bin/python scripts/zimage_l2p_eval.py \
  --repo-path ../T2I-L2P \
  --steps 20 \
  --teleport \
  --vram-limit 16
```

Both write to `evals/`, which is intentionally gitignored.

## Latent Teleport Integration Notes

The existing production latent teleport path is exact-prompt replay:

- Full generation captures an intermediate latent and full text embedding.
- Replay starts from the cached latent at the next denoising step.
- Quality should match the deterministic full output for the same prompt, seed,
  size, and step count.

That same exact-prompt idea maps cleanly to L2P because L2P's denoising state is
already a pixel-space tensor. The local `scripts/zimage_l2p_eval.py --teleport`
helper mirrors the L2P denoise loop, captures `inputs_shared["latents"]` after a
step, and replays from `resume_step` with the cached prompt embeddings and
noise state.

Cross-prompt visual-unit teleportation is a separate next step. It needs
L2P-specific cache storage because L2P latents are `(1, 3, H, W)` pixel tensors,
not Z-Image latent tensors, and the quality threshold should be judged against
the 20-step L2P output rather than the current VAE-based Z-Image output.

The production latent-space nearest-neighbor version is now exposed only for
evals with `teleport_approx=true`. The first cache-miss smoke tests were not
good enough to promote: red-clay source -> orange-clay target kept the source
red block, with `PSNR ~= 14.5dB`, and was slower than warmed full generation.
That suggests L2P should not inherit simple nearest-latent teleport directly;
if we revisit approximate L2P teleport, use a trained delta/forecaster or a
stricter visual-unit cache instead of pooled text-embedding nearest neighbor.

## L2P Loader Notes

The local venv did not include `torchvision` or `modelscope`, but the L2P
inference path only imports those through broad package initializers. The eval
script now provides small import shims for those two packages instead of
installing a large matching `torchvision` build into the shared environment.

On the current shared 32 GB GPU, full CUDA loading of L2P OOMs while
`text-generator.io` is resident. The successful path uses T2I-L2P disk-backed
VRAM management for the L2P DiT only, plus a local module-map fix for
`diffsynth.models.z_image_dit_L2P.ZImageDiT`. The text encoder stays on the
normal loader path because the upstream disk wrapper breaks on its embedding
module.

One additional eval-local patch is needed for disk offload: hydrate
`x_pad_token` and `cap_pad_token` from the safetensors file because they are
root parameters, not child modules, and replace the model function's
`next(dit.parameters())` dtype lookup with `pipe.torch_dtype`.

## LoRA Compatibility Notes

Current production LoRA support applies native Z-Image LoRA weights directly to
the existing transformer. That patcher is not reusable unchanged for L2P:

- Production code expects the active model at `pipe.transformer`; L2P uses
  `pipe.dit`.
- Production direct mapping targets CuteZImage names like `q_proj`; L2P layer
  names are closer to native Z-Image keys such as `attention.to_q`.
- The published L2P inference checkpoint is a merged pixel-space model, not the
  original latent-space base, so even a successful key mapping needs visual
  validation. It may apply mechanically but still fail stylistically.

Practical next step: benchmark base L2P first. If it is fast and close enough at
20 steps, add a separate experimental L2P LoRA patcher that maps native keys to
`pipe.dit.layers[N].attention.to_q/to_k/to_v/to_out.0` and
`pipe.dit.layers[N].feed_forward.w1/w2/w3`, gated behind a non-production flag.

## Measured Teleport Replay

One constrained production-path run was captured under:

`evals/zimage_teleport_20260525T222050Z/`

The request asked for 20 steps, but the live server reported `perf.steps=8`,
which means that process had not yet picked up the new upload-route
`num_inference_steps` parameter. Effective 8-step numbers from that run:

| Mode | Server inference | Wall |
| --- | ---: | ---: |
| baseline | `19.716s` | `45.497s` |
| teleport prime | `22.431s` | `24.118s` |
| teleport replay | `16.979s` | `18.553s` |

Replay quality against the baseline was exact for this prompt:
`MSE=0`, `MAE=0`, `PSNR=inf`.

True 20-step teleport replay should be rerun after the inference service is
restarted or reloaded with the current `inference/server.py`.

A true 20-step run was then captured under:

`evals/zimage_teleport_20260525T222932Z/`

This used the vanilla diffusers fallback (`zimage_use_cute=false`) because the
CuteZImage reload hung during post-checkpoint initialization.

| Mode | Server inference | Wall |
| --- | ---: | ---: |
| baseline | `41.758s` | `43.337s` |
| teleport prime | `33.798s` | `35.504s` |
| teleport replay | `26.864s` | `28.448s` |

The replay was an exact cache hit at 20 steps and matched baseline pixels:
`MSE=0`, `MAE=0`, `PSNR=inf`.

## Measured L2P Replay

First completed L2P smoke run:

`evals/zimage_l2p_20260525T225802Z/`

Environment:

- size: `256x256`
- steps: `4`
- prompt: `minecraft dirt block inventory icon, centered, crisp pixel game asset, plain background`
- L2P DiT mode: disk-backed VRAM management with `--vram-limit 16`
- resident GPU load during eval: `askfelix` plus `text-generator.io`

| Mode | Wall |
| --- | ---: |
| baseline L2P 4-step | `56.915s` |
| exact replay from step 2 | `28.188s` |

Replay quality against the baseline was exact: `MSE=0`, `MAE=0`, `PSNR=inf`.

Interpretation: L2P exact-prompt teleport works mechanically and cuts the
remaining denoising time roughly in half for the smoke case, but L2P is not
faster than the current production Z-Image path under this shared-GPU/offload
configuration. A fair latency comparison needs either a dedicated GPU window or
an upstream-safe full-CUDA load with the text-generator service stopped.
