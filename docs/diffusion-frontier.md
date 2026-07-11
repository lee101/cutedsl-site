# Diffusion Latency/Quality Frontier

## Goal and gates

The target is warm batch-1 image generation in at most one second while
retaining the useful quality of a 20-40 step reference. A result does not pass
because it is fast alone. Every candidate must record:

- end-to-end and server inference latency, including synchronization;
- physical model forward passes, resolution, seed, precision, and offload mode;
- peak allocated VRAM and cold model-load time;
- same-model retention versus a fixed-seed max-step reference;
- blind human ratings for prompt match, anatomy/text, artifacts, and preference;
- LoRA-on and LoRA-off correctness and latency when the backend claims LoRA support.

PSNR, SSIM, and LPIPS are retention checks only. They cannot rank unrelated
outputs from different models. Use the generated `review_manifest.json` for
cross-model preference, then compute a Pareto frontier from human rating versus
warm latency.

## Public model matrix

| Candidate | Native steps | Approx. Diffusers weights | 32 GB 5090 plan | License/runtime note |
| --- | ---: | ---: | --- | --- |
| Z-Image Turbo | 8 (20-step reference) | ~12.5 GiB | dedicated full-CUDA first; CuteZImage and compile ablations | current production baseline |
| FLUX.1 Schnell | 1-4 | ~31.5 GiB | FP8/FP4 or carefully staged encoders; BF16 is too tight with services resident | gated Apache-2.0 weights |
| Proteus v0.2/v0.4 | 20-40 | ~6.5 GiB single checkpoint | full CUDA; test LCM/Lightning/Hyper-SD adapters at 4-8 steps | GPL-3.0 model repositories |
| RealVisXL v4 | 20-40 | ~6.5 GiB fp16 components | full CUDA; same distilled-adapter sweep as Proteus | OpenRAIL++ |
| Krea-2 Turbo | 8 | ~33.3 GiB Diffusers components | staged Qwen conditioning + resident FP8 denoiser; 512 exact-resume hits pass 1 s, native 1024 does not | Krea 2 Community License; source Diffusers currently required |

The estimated Krea-2 Diffusers payload is transformer ~26.3 GB, Qwen3-VL text
encoder ~8.9 GB, and VAE ~0.5 GB. It does not fit fully resident on a 32 GB GPU.
Do not count a third-party quantized checkpoint as acceptable until fixed-seed
quality, prompt adherence, and LoRA behavior pass the same harness.

Cosmos3-Super-Text2Image is excluded from the one-second local frontier because
the cited 64B-class agentic system is the wrong scale for this hardware and
latency target. Its orchestration ideas can be studied independently without
putting it in the serving hot path.

## Commands

No command downloads weights unless `--allow-download` is explicit.

```bash
# Catalog and hardware/dependency/cache feasibility
/nvme0n1-disk/code/.venv/bin/python scripts/diffusion_frontier_eval.py --list-models
/nvme0n1-disk/code/.venv/bin/python scripts/diffusion_frontier_eval.py \
  --preflight --models zimage-turbo flux-schnell proteus-v0.2 proteus-v0.4 realvisxl-v4 krea2-turbo

# Current HTTP server, compact one-prompt sweep
/nvme0n1-disk/code/.venv/bin/python scripts/diffusion_frontier_eval.py \
  --models zimage-turbo --api-base-url http://127.0.0.1:8100 \
  --prompt 'a red fox standing in fresh snow, photorealistic, detailed fur' \
  --steps 4 8 20 --runs 2 --warmups 0 --width 512 --height 512

# Local SDXL candidate with a LoRA. The first run may download after review.
/nvme0n1-disk/code/.venv/bin/python scripts/diffusion_frontier_eval.py \
  --models realvisxl-v4 --allow-download --offload cuda \
  --steps 4 8 20 40 --lora /path/to/adapter.safetensors --lora-scale 0.8

# Scheduler-correct SDXL comparison: native DPM++ 2M Karras versus LCM and Hyper-SD.
# Every retention metric is anchored to native40, and prompt embeddings are cached
# unless --include-text-encode is passed.
HF_HOME=/vfast/data/.cache/huggingface \
  /nvme0n1-disk/code/.venv/bin/python scripts/sdxl_frontier_eval.py \
  --models realvisxl-v4 --allow-download

# Styled-LoRA compatibility is evaluated against a styled native40 reference.
/nvme0n1-disk/code/.venv/bin/python scripts/sdxl_frontier_eval.py \
  --models proteus-v0.2 --profiles native40 lcm4 \
  --style-lora TheLastBen/Papercut_SDXL \
  --style-lora-weight-name papercut.safetensors --style-lora-scale 0.8
```

Krea-2 needs an isolated environment with a Diffusers revision that exports
`Krea2Pipeline`:

```bash
python -m venv /nvme0n1-disk/code/.venv-krea2
/nvme0n1-disk/code/.venv-krea2/bin/pip install \
  'git+https://github.com/huggingface/diffusers.git' 'transformers>=5.13' accelerate peft torch Pillow sentencepiece
/nvme0n1-disk/code/.venv-krea2/bin/python scripts/diffusion_frontier_eval.py \
  --preflight --models krea2-turbo

# The runner stages Qwen prompt embeddings first, frees Qwen, and then loads
# the transformer-only FP8 serving pipeline so both never compete for VRAM.
/nvme0n1-disk/code/.venv-krea2/bin/python scripts/diffusion_frontier_eval.py \
  --models krea2-turbo --offload cuda --quantization torchao-fp8wo \
  --cache-prompt-embeds --release-text-encoders
```

The local isolated environment currently uses Diffusers source commit
`284419b35267dea7d4435fd0ef1eaa132bf73efe` (`0.40.0.dev0`) and successfully
exports `Krea2Pipeline`, Transformers 5.13.0, and the deployment's PyTorch 2.11
CUDA 12.8 packages. Transformers 4.57.6 is not compatible with this snapshot:
it reads the current `rope_parameters` config as `rope_scaling=None` and fails
while constructing Qwen3-VL. Krea's community license also requires downstream
deployers to apply appropriate content filtering/review; model compatibility
does not remove that serving obligation.

Use FP8 weight-only as the first resident test. A local torchao 0.18.dev smoke
check accepted 1D, 2D, and 3D BF16 inputs with `Float8WeightOnlyConfig`, while
the dynamic-activation FP8 configuration asserted on multi-row inputs in this
runtime. `torchao-fp8dq` remains exposed for controlled compile experiments,
but it is not the recommended production path until the full transformer test
proves those shapes and output quality.

## Current local evidence (2026-07-10)

The initial shared production worker used vanilla Diffusers Z-Image BF16 with
model CPU offload and eager execution. A fixed-seed 512x512 smoke run measured:

| Steps | Server inference | PSNR to 20-step reference |
| ---: | ---: | ---: |
| 4 | 26.181 s | 20.40 dB |
| 8 | 25.139 s | 25.19 dB |
| 20 | 27.821 s | reference |

This is decisive evidence that the current bottleneck is component movement and
setup, not denoising forwards: sixteen additional steps cost only ~1.6 seconds
over the 4-step run. The next production experiment must be a dedicated
full-CUDA worker with prompt-embedding caching and no upload in the measured hot
path. The server now exposes a bounded CPU prompt-embedding LRU through
`prompt_embedding_cache` in `/health` and per-generation hit/encode timing; this
avoids repeating text-encoder/offload work across seeds and LoRA requests.
Exact-prompt latent replay remains useful for cache hits, but approximate
cross-prompt latent reuse stays experimental until a learned correction and
quality gate beat full generation.

On the next inference restart, the launch policy defaults to
`ZIMAGE_CPU_OFFLOAD=auto`: it selects full-CUDA only when at least 24,576 MiB is
free before model load, and otherwise retains safe model offload. Set
`ZIMAGE_CPU_OFFLOAD=1` to force the old shared-worker behavior. Frontier API
requests send `quality_retry=false`, ensuring a timing row contains exactly one
requested generation rather than a hidden artifact-triggered retry.

The first full-CUDA restart selected no offload with ~29.4 GiB free. The
resident Z-Image process used ~26.0 GiB, and a warm 8-step 1024x1024 denoising
loop ran at about 2.6 steps/s. End-to-end server time was still 14.8 seconds for
a unique prompt, confirming that the Qwen text encoder is now the primary hot
path rather than transformer offload. Repeated-prompt cache-hit measurements
belong in the frontier report; the next general optimization is a persistent or
quantized text encoder / prompt-embedding service, not fewer denoising steps.

After warming the 512x512 shape and reusing prompt embeddings, a two-repeat
frontier against a true 20-step reference measured:

| Steps | Median server | Median wall | SSIM to 20-step | PSNR to 20-step |
| ---: | ---: | ---: | ---: | ---: |
| 4 | 0.556 s | 0.856 s | 0.756 | 17.42 dB |
| 8 | 0.953 s | 1.041 s | 0.872 | 22.97 dB |
| 20 | 2.264 s | 2.344 s | reference | reference |

This proves the 4-step latency goal on the RTX 5090 and puts 8 steps within
measurement noise of one second, but it does **not** prove 20-step-quality at
that latency. Four-step pixel/structural retention is weak; eight steps is the
current candidate to validate over the full prompt set and blind review. Cold
load was 717.7 seconds under severe shared-NVMe contention and must be improved
with direct-to-device loading before this mode is operationally comfortable.
The no-offload loader now requests `device_map=cuda` so future cold starts place
checkpoint shards directly on the GPU. It retains CPU-then-CUDA and model-
offload fallbacks for incompatible Diffusers builds or memory pressure.

The first live pixel-art LoRA check exposed a false-positive activation:
Kohya's joint `attention_qkv` names resolved 0/150 modules. CuteLoRAs now splits
joint QKV output factors into `to_q`, `to_k`, and `to_v`, maps output/FFN names,
and rejects zero-parameter activation. The actual cached adapter resolves
210/210 expanded factors against the vanilla Diffusers Z-Image transformer.
This mapping is unit/integration tested; live visual verification follows the
next restart with the corrected open-source package.

That restart has now exercised both fixes. Direct-device-map loading completed
in 240.7 seconds, versus 717.7 seconds for the earlier CPU-staged load under
heavy storage contention. Health reports `zimage_load_strategy=direct-device-map`.
The first real `needle_felting` adapter activation applied 240 parameters; its
cold activation took 27.2 seconds while the next activation took 72.3 ms. A
later fresh-worker activation was 105.8 ms warm. A fixed raw-prompt/seed 512px
LoRA-off/on check returned the requested adapter metadata and a clearly changed
output: the adapter produced an explicitly needle-felt fox with coarse textile
fibers and a knitted bow, while the base output remained a smoother plush
figurine. Artifacts are in `/nvme0n1-disk/tmp/zimage-lora-verification/`.
Those two calls ran behind gallery work and cold 512px postprocessing, so their
HTTP latency is not a valid steady-state LoRA benchmark.

Later direct-device-map starts ranged from 97.5 to 399.2 seconds, and one start
under extreme shared storage/swap pressure took 1,010.2 seconds. Direct loading
reduces the usual case but does not make cold starts predictable on this host.
The production requirement is therefore a resident warmed worker plus health-
gated rollout; benchmark latency must never be conflated with cold recovery.

The full default four-prompt/two-repeat 512x512 gate produced:

| Steps | Runs | Median server | Median wall | Median SSIM | Minimum SSIM | Server <=1 s |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 4 | 8 | 0.572 s | 0.654 s | 0.738 | 0.527 | 8/8 |
| 8 | 8 | 0.935 s | 1.011 s | 0.806 | 0.638 | 8/8 |
| 20 | 8 | 2.243 s | 2.317 s | reference | reference | 0/8 |

Icons retained structure best; the elderly-astronaut portrait and teapot with
rendered text were the weakest 4/8-step categories. This rejects the hypothesis
that fast Z-Image alone already has 20-step-equivalent quality across the eval.
Eight steps is the current latency candidate, while distilled SDXL and other
model families must be compared on the same prompts and blind review.

### RealVisXL v4 distilled gate

The scheduler-aware 1024x1024 RealVisXL v4 run used cached prompt embeddings,
full-CUDA fp16, two repeats per prompt, a native DPM++ 2M Karras 40-step
reference, the official LCM-LoRA SDXL adapter with `LCMScheduler`, and the
official Hyper-SDXL 4-step adapter with trailing `DDIMScheduler`:

| Profile | Runs | Median wall | Maximum wall | Median SSIM to native40 | Minimum SSIM | <=1 s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| native20 | 8 | 3.464 s | 3.965 s | 0.756 | 0.670 | 0/8 |
| native40 | 8 | 6.272 s | 7.085 s | reference | reference | 0/8 |
| LCM4 | 8 | 0.898 s | 0.940 s | 0.535 | 0.432 | 8/8 |
| LCM8 | 8 | 1.487 s | 1.496 s | 0.514 | 0.442 | 0/8 |
| Hyper4 | 8 | 0.890 s | 1.033 s | 0.514 | 0.431 | 7/8 |

LCM4 is the first 1024x1024 profile to pass the physical end-to-end one-second
gate on every measured row. Hyper4 is competitive but missed once. Retention
is not monotonic with distilled step count: LCM8 was slower and did not improve
median SSIM. Visual inspection found useful fox and portrait structure in both
four-step profiles. Native40 rendered the teapot's `TEA` label most faithfully;
LCM4 floated the text on the glass and LCM8 often removed it. All profiles,
including native40, turned the pixel-art inventory-icon prompt into a repeating
grass texture, so that prompt is a base-model adherence failure rather than an
acceleration-only regression. The generated blind-review files still require
an independent rater; this visual inspection was not blind.

Artifacts: `/nvme0n1-disk/tmp/frontier-sdxl-realvis/sdxl_frontier_20260710T112236Z/`.

### Proteus v0.4 distilled gate

The identical 1024x1024 matrix on Proteus v0.4 produced:

| Profile | Runs | Median wall | Maximum wall | Median SSIM to native40 | Minimum SSIM | <=1 s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| native20 | 8 | 3.187 s | 3.314 s | 0.726 | 0.531 | 0/8 |
| native40 | 8 | 6.151 s | 6.422 s | reference | reference | 0/8 |
| LCM4 | 8 | 0.893 s | 0.958 s | 0.449 | 0.276 | 8/8 |
| LCM8 | 8 | 1.489 s | 1.569 s | 0.431 | 0.316 | 0/8 |
| Hyper4 | 8 | 0.896 s | 1.075 s | 0.482 | 0.405 | 6/8 |

Proteus repeats the RealVis latency result: LCM4 is the only strict 8/8 pass,
while LCM8 costs about 1.49 seconds without better median retention. Hyper4
retains more of the native40 structure than LCM4 and looked closer to the
native model on the fox, astronaut texture, and labeled teapot, but both teapot
runs crossed one second. Native20/native40 supplied the most detailed portrait
and the clearest `TEA` plaque. The inventory-icon failure again appears as a
green repeating texture across every profile. Blind independent ratings remain
pending.

Artifacts: `/nvme0n1-disk/tmp/frontier-sdxl-proteus-v04/sdxl_frontier_20260710T113946Z/`.

### Proteus v0.2 focused gate

Because v0.4 showed native20 and LCM8 were dominated, the v0.2 window compared
only native40 and the two viable four-step profiles:

| Profile | Runs | Median wall | Maximum wall | Median SSIM to native40 | Minimum SSIM | <=1 s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| native40 | 8 | 6.124 s | 6.393 s | reference | reference | 0/8 |
| LCM4 | 8 | 0.879 s | 0.903 s | 0.594 | 0.509 | 8/8 |
| Hyper4 | 8 | 0.886 s | 0.957 s | 0.505 | 0.383 | 8/8 |

Proteus v0.2 + LCM4 is the strongest measured strict-latency candidate so far:
it is faster and retains substantially more native40 structure than v0.4 LCM4
or RealVis LCM4. It is also the only profile that turned the inventory request
into a centered isometric grass block, although the background remained green
rather than plain. Hyper4 kept more fine portrait/fox detail and produced a more
label-like teapot treatment, but its inventory output repeated grass bands and
its retention was lower. LCM4's teapot displayed readable `TEA` directly on the
glass rather than on the requested label. These observations are labeled-sheet
inspection, not independent blind ratings.

Artifacts: `/nvme0n1-disk/tmp/frontier-sdxl-proteus-v02/sdxl_frontier_20260710T115648Z/`.

The SDXL runner also loads and fuses a second style adapter alongside the
acceleration adapter. A local no-network Proteus v0.2 check successfully fused
`lcm-sdxl` plus the documented Papercut SDXL adapter at scale 0.8 under
`LCMScheduler`. This validates adapter composition/loading; a GPU visual and
latency row is still required before calling that specific styled profile
quality-verified.

An official Hyper-SDXL 8-step profile is cataloged as `hyper8`. It can be
tested with a compiled, fused UNet while keeping native40 uncompiled as the
quality anchor:

```bash
python scripts/sdxl_frontier_eval.py --models proteus-v0.2 \
  --profiles native40 hyper8 --compile max-autotune --compile-fullgraph
```

This is a pending experiment, not part of the measured table above.

### FLUX.1 Schnell resident FP8 and exact resume

The component-only FLUX snapshot is 31.5 GiB. BF16 model CPU offload could not
move the complete transformer onto this GPU even at 512px: the process had
28.50 GiB allocated and 29.09 GiB total GPU usage, while unrelated resident
services consumed another ~2.2 GiB. Both 1024px and 512px attempts failed before
the first denoiser forward. Sequential submodule offload produced the 512px
quality reference in 41.449 seconds for four steps.

Transformer FP8 weight-only quantization then loaded in 16.31 seconds with
direct CUDA placement. After caching the prompt embeddings and releasing both
text encoders/tokenizers, the measured 512px result was:

| Profile | Physical steps | Wall | Peak allocated VRAM | SSIM |
| --- | ---: | ---: | ---: | ---: |
| full FP8 | 4 | 1.086 s | 23,577.5 MiB | 0.936 to BF16 |
| exact resume after 3 cached steps | 1 | 0.306 s | 23,577.7 MiB | 1.000 to full FP8 |

The resumed WEBP was pixel-identical to the full FP8 output (MAE/MSE 0). This
validates the original-sigma-tail implementation for an exact same-prompt/seed
cache hit. It is not a cross-prompt quality claim and the cache-prime cost is
not hidden in the 0.306-second row. FP8 versus sequential-BF16 retained SSIM
0.9359 and PSNR 29.96 dB; labeled visual inspection found the composition and
fine fur/lighting strongly preserved with small local detail shifts.

Artifacts:
`/nvme0n1-disk/tmp/frontier-flux-bf16-reference-512-sequential/diffusion_frontier_20260710T125813Z/`
and
`/nvme0n1-disk/tmp/frontier-flux-fp8wo-512/diffusion_frontier_20260710T130028Z/`.

A native-1024 follow-up was intentionally stopped before inference. Its newly
evicted/fragmented HDD snapshot needed 5.6 minutes for the two transformer
shards and 9.1 minutes for only the first of three T5 shards. This is a storage
placement failure, not a 1024 latency row. Frequently restarted FLUX/Krea
workers need their snapshots on NVMe; the production design remains a resident
warm worker with text conditioning off the request hot path.

### Krea-2 Turbo resident FP8 and exact resume

Krea-2 required Transformers 5.13.0 because the current text-encoder config
uses `rope_parameters`; Transformers 4.57.6 failed before loading weights. A
second constraint appeared on the 32 GB GPU: the BF16 4B Qwen encoder and FP8
13B denoiser together left about 35 MiB free and could OOM during prompt
encoding. The open-source runner now handles this deterministically by loading
Qwen alone, retaining prompt embeddings on CPU, releasing Qwen, and loading a
final pipeline with `text_encoder=None` and `tokenizer=None`.

With staged conditioning, direct-CUDA TorchAO FP8 weight-only, one warmup, and
the four default prompts, the measured frontier was:

| Resolution | Profile | Physical steps | N | Median wall | Max wall | Peak allocated VRAM | Exact to full |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 512 | full FP8 | 8 | 1 | 3.824 s | 3.824 s | 14,705 MiB | reference |
| 512 | resume after 7 cached steps | 1 | 1 | 0.521 s | 0.521 s | 14,705 MiB | yes |
| 1024 | full FP8 | 8 | 4 | 13.507 s | 13.524 s | 22,124 MiB | reference |
| 1024 | resume after 7 cached steps | 1 | 4 | 1.843 s | 1.870 s | 22,124 MiB | yes |

All resumed WEBPs were pixel-identical to their corresponding full FP8 output.
The 512 exact-cache hit passes the one-second target; neither full Krea nor the
1024 one-step tail does. Prime cost remains explicit and is not included in a
resume-hit row.

A same-prompt/seed sequential-offload BF16 1024 reference took 107.307 seconds.
FP8 retained SSIM 0.9563 and PSNR 32.45 dB to that reference. Labeled visual
inspection found the same composition and high prompt adherence: the four FP8
outputs rendered detailed fox fur, a centered grass block, natural portrait
texture, and an exactly readable `TEA` label. This supports FP8 quality
retention for the tested seed; independent blind ratings are still required
before cross-model preference claims.

Artifacts:
`/nvme0n1-disk/tmp/frontier-krea-fp8wo-512-staged/diffusion_frontier_20260710T141939Z/`,
`/nvme0n1-disk/tmp/frontier-krea-fp8wo-1024/diffusion_frontier_20260710T141442Z/`,
and
`/nvme0n1-disk/tmp/frontier-krea-bf16-reference-1024-sequential/diffusion_frontier_20260710T141701Z/`.

## Early-exit ablation (2026-07-11)

The Z-Image pipeline forces `scheduler.sigma_min = 0`, so the shifted flow-match
schedule ends `[..., 0.3, 0.0, 0.0]` and the final requested step integrates
sigma 0 -> 0: a transformer forward that cannot change the latent. Eight
requested steps perform seven useful forwards. The server now interrupts the
loop when the next sigma is zero (`ZIMAGE_SKIP_NOOP_STEPS=1`); this is
bitwise-identical output for one fewer forward (~12.5% of denoise compute).

Threshold-based early exit uses the x0-hat prediction, not raw latent motion.
On this schedule the per-step latent delta grows (0.09 -> 0.34 relative L2 on a
512px fox trace) because late sigma jumps are large, so "stop when the latent
stops moving" never fires. The denoised prediction x0-hat = z - sigma_next * v
stabilizes monotonically; v is recovered exactly from consecutive latents as
dz/dsigma (verified to float epsilon against `FlowMatchEulerDiscreteScheduler`).
When the relative x0-hat movement stays below a threshold for two consecutive
steps, the callback overwrites the latent with x0-hat (one Euler jump to
sigma=0) and interrupts the loop.

A 60-prompt fixed-seed 512px ablation (9 requested steps, 8 effective; LPIPS
AlexNet at 256px against the full-schedule final) measured oracle exits and
live-threshold behavior:

| Rule | Threshold | Mean forwards saved | Median LPIPS | p90 | Max | <=0.05 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| oracle eps=0.05 | — | 2.88 / 8 | — | — | 0.05 | 100% |
| single-hit | 0.10 | 1.48 | 0.000 | 0.020 | 0.205 | 97% |
| single-hit | 0.15 | 2.55 | 0.018 | 0.061 | 0.205 | 85% |
| 2-consecutive | 0.12 | 1.08 | 0.000 | 0.020 | 0.123 | 97% |
| 2-consecutive | 0.15 | 1.57 | 0.000 | 0.031 | 0.123 | 95% |

Exit steps vary strongly per prompt (oracle exit range 2-6 of 8), confirming
per-prompt imperceptible-distance variation. Flat, slowly-decaying dx0 curves
(high-texture landscape/hair prompts) are the tail risk; the two-consecutive
hysteresis rule halves the worst case. The tail images are not artifacts — they
are the same composition with less late-stage micro-detail.

Two negative results worth recording. First, TeaCache-style mid-schedule
velocity-extrapolation skipping barely triggers on this already-distilled
schedule: at tolerance 0.15 the offline simulation (recorded velocities, upper
bound on quality) skipped under one step on average — the redundancy lives at
the schedule tail, which x0-hat exit already captures. Second, KNN over pooled
Qwen prompt embeddings (n=60) predicts the oracle exit step no better than a
global constant (MAE 0.87 vs 0.88 steps). The in-flight dx0 signal is strictly
more informative. The server now appends every generation's dx0 curve to
`/nvme0n1-disk/tmp/dx0-corpus.jsonl` (`DX0_LOG=1`), so a large corpus accrues
passively; revisit learned/KNN exit prediction at n~10k.

Production configuration (`start_persistent.sh`): `ZIMAGE_EARLY_EXIT=0.12`,
`ZIMAGE_EARLY_EXIT_MIN_STEPS=5`, `ZIMAGE_EARLY_EXIT_CONSECUTIVE=2`, no-op skip
on. Expected ~2 fewer forwards of 8 requested (~25% denoise latency) with p90
LPIPS ~0.02 and worst case ~0.12 on ~3-5% of prompts, backstopped by the
existing artifact quality-retry. Per-request `early_exit=0` disables; threshold
exits do not write the exact-replay teleport cache (approximate latents must
not poison it), while no-op skips still do. The
`/experimental/step_trace` endpoint captures per-step latents, velocities,
sigmas, x0-hat decodes, and pooled prompt embeddings for future ablations, and
accepts custom `sigmas` for schedule sweeps. Tooling:
`scripts/early_exit_ablation.py` (trace/analyze/knn) and
`scripts/step_skip_sim.py`; unit tests in `inference/test_early_exit.py`.

## Deployment recommendation

The current strict one-second winner is **Proteus v0.2 + LCM4 at 1024**:
8/8 runs passed, median wall time was 0.879 seconds, maximum was 0.903
seconds, and median same-model SSIM to native40 was 0.594. It is the default
quality/latency candidate for a native-resolution endpoint. Proteus v0.2
Hyper4 is a useful stylistic alternative (0.886-second median, 0.957-second
maximum), but retained less structure on this fixed suite.

Use resident **Z-Image 4-step at 512** when flexible Z-Image LoRAs and minimum
latency matter: its four-prompt median wall time is 0.654 seconds and all eight
runs passed, but its median SSIM to the 20-step reference is only 0.738 and the
hard portrait/text prompts are visibly weaker. Z-Image 8-step improves
retention but misses the strict wall target at a 1.011-second median.

Treat **FLUX FP8** and **Krea-2 FP8** as premium/cache-backed routes, not the
default one-second path. FLUX full-4 at 512 narrowly misses at 1.086 seconds,
while an exact one-step cache hit takes 0.306 seconds. Krea has the strongest
labeled prompt adherence in this small inspection but takes 3.824 seconds at
512 and 13.507 seconds at 1024; only its 512 exact-cache hit passes at 0.521
seconds. Cross-model preference remains provisional until the opaque review
manifests receive independent ratings.

Operationally, keep one warmed worker per selected family, place large model
snapshots on NVMe, persist prompt embeddings outside the denoiser worker, and
key exact latent caches by model/revision, quantization, adapter state, prompt,
seed, resolution, schedule, and capture step. Any approximate cross-prompt
teleport must remain behind a calibrated confidence gate and exact/full
fallback.

## Experiment order

1. Z-Image full-CUDA dedicated worker: eager versus compile, 4/8/20 steps, with
   text-encoder and VAE timing separated. This tests whether one second is even
   close before inventing a new sampler.
2. SDXL full-CUDA candidates: Proteus v0.2/v0.4 and RealVisXL v4 with native
   20/40-step references, then LCM/Lightning/Hyper-SD 4/8-step adapters. These
   fit comfortably and are the most realistic one-second route.
3. FLUX Schnell: test official BF16 only as a quality reference, then official
   FP8/FP4 exports or a reproducibly converted quantized transformer. Keep text
   encoders off the hot path via embedding caches.
4. Krea-2 Turbo: keep staged Qwen conditioning and resident FP8 as the
   memory-safe implementation. Treat full 8-step and native-1024 results as
   quality options, not one-second candidates; only 512 exact-cache hits pass.
5. Apply generic exact latent resume to each Diffusers family. Cross-prompt
   teleportation requires trained latent-delta prediction and must fall back
   when its calibrated confidence gate fails.

`diffusion_frontier.flow_resume` now provides the exact-cache primitive for
flow-matching pipelines: capture FLUX/Krea packed latents through the normal
Diffusers callback, then resume with the untouched tail of the original linear
sigma schedule. It deliberately does not call a newly spaced N-step schedule
"resume," and it does not claim that a latent from another prompt is exact.
The latter remains the learned/certified teleport experiment.

Proprietary RA1 routing, prompts, and product behavior remain in `netwrck`.
Only generic model adapters, metrics, caching, LoRA swapping, and kernels belong
in the open-source `cutedsl` package.

## Primary references

- [RealVisXL v4 model card](https://huggingface.co/SG161222/RealVisXL_V4.0)
- [Official Diffusers LCM-LoRA guide](https://huggingface.co/docs/diffusers/main/using-diffusers/inference_with_lcm_lora)
- [ByteDance Hyper-SD repository and SDXL scheduler recipe](https://huggingface.co/ByteDance/Hyper-SD)
- [FLUX.1 Schnell model card](https://huggingface.co/black-forest-labs/FLUX.1-schnell)
- [Krea-2 Turbo model card](https://huggingface.co/krea/Krea-2-Turbo)
- [Diffusers torchao quantization guide](https://huggingface.co/docs/diffusers/main/en/quantization/torchao)
