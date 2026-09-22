# Z-Image Performance Notes

## Current Production Shape

- Public route: `https://images.netwrck.com/create_and_upload_image`
- Local inference: `http://localhost:8100/create_and_upload_image`
- Default backend in the shared worker: vanilla diffusers Z-Image Turbo,
  `bfloat16`, CPU offload enabled. Dedicated workers can use
  `ZIMAGE_CPU_OFFLOAD=0` or `auto` when enough VRAM is free.
- Default steps: `4`
- Exact-prompt latent teleport: opt-in with `teleport=true`
- Perf metadata: opt-in with `perf=true`. This only adds timing/cache fields
  to the JSON response; it does not change generation, model selection, LoRA,
  teleport, or upload behavior.
- Structured 5xx logging: `/nvme0n1-disk/tmp/cutedsl-inference-errors.jsonl`

## Measured Baseline

Latest harness report:

- Markdown: `/nvme0n1-disk/tmp/zimage-perf/zimage_perf_20260506T224324Z.md`
- JSON: `/nvme0n1-disk/tmp/zimage-perf/zimage_perf_20260506T224324Z.json`

Steady-state medians from that run:

| Mode | Server inference | Upload | Wall |
| --- | ---: | ---: | ---: |
| Full 4-step generation | `2.13s` | `1.36s` | `3.93s` |
| Exact-prompt teleport replay | `1.09s` | `1.30s` | `2.80s` |

Quality for exact-prompt teleport replay:

- `MSE=0`
- `MAE=0`
- `max_abs=0`
- `PSNR=inf`

The replay path is exactly matching the full deterministic output because it
stores the same mid-latent and full prompt embedding, then runs the same
remaining Z-Image denoising steps.

## Cache Behavior

The API now checks deterministic default output paths, not only explicit
`save_path`. Repeating the same prompt/size/seed can return the already-uploaded
R2 URL without GPU work or upload.

Observed public cached response for the original dirt block prompt:

- First cached check after restart: `0.92s`
- Second cached check: `0.21s`

## Benchmark Commands

Run a compact local benchmark:

```bash
/nvme0n1-disk/code/.venv/bin/python scripts/zimage_perf_harness.py \
  --runs 2 \
  --prompt 'minecraft block dirt menu zoomed in dirt block icon' \
  --prompt 'voxel grass block item icon, clean square menu tile, game inventory'
```

Run a single Nsight Systems curl profile:

```bash
scripts/nsight_zimage_api.sh 'minecraft block dirt menu zoomed in dirt block icon'
```

The Nsight wrapper profiles the client-side request path. For kernel-level
server profiling, run the server process under `nsys profile` or add NVTX ranges
inside the denoise/refine functions and profile the Python server directly.

Run reliability probes across prompt lengths and feature modes:

```bash
/nvme0n1-disk/code/.venv/bin/python scripts/zimage_reliability_probe.py \
  --base-url http://127.0.0.1:8100 \
  --attempts 2 \
  --width 512 \
  --height 512
```

Run a local visual step sweep. This writes a default 10-image set under the
gitignored `evals/` directory: 2 prompts × `4,8,12,16,20` steps, with the
20-step image treated as the local gold/reference for each prompt.

```bash
/nvme0n1-disk/code/.venv/bin/python scripts/zimage_step_eval.py \
  --base-url http://127.0.0.1:8100 \
  --steps 4,8,12,16,20
```

Run a first L2P pixel-space comparison from the sibling research checkout:

```bash
/nvme0n1-disk/code/.venv/bin/python scripts/zimage_l2p_eval.py \
  --repo-path ../T2I-L2P \
  --steps 20 \
  --vram-limit 16
```

Run exact-prompt latent teleport eval for the production upload path. This
uses full 20-step output as the reference, primes the latent cache, then
measures replay speed and image equality/PSNR under `evals/`.

```bash
/nvme0n1-disk/code/.venv/bin/python scripts/zimage_teleport_eval.py \
  --base-url http://127.0.0.1:8100 \
  --steps 20
```

Sweep exact replay from a later cached latent:

```bash
/nvme0n1-disk/code/.venv/bin/python scripts/zimage_teleport_eval.py \
  --base-url http://127.0.0.1:8100 \
  --steps 20 \
  --teleport-start-step 16
```

Run the experimental nearest-latent cache-miss path:

```bash
/nvme0n1-disk/code/.venv/bin/python scripts/zimage_approx_teleport_eval.py \
  --base-url http://127.0.0.1:8100 \
  --steps 20 \
  --start-step 16 \
  --min-similarity 0.0
```

Latest small live check:

- Report: `evals/zimage_teleport_20260525T222050Z/report.md`
- Requested steps: `20`
- Server-reported effective steps: `8` because the live inference process had
  not yet reloaded the new upload-route `num_inference_steps` parameter.
- Baseline server inference: `19.716s`
- Exact teleport replay server inference: `16.979s`
- Replay cache hit: `true`
- Replay quality versus baseline: `MSE=0`, `PSNR=inf`

Restart the inference service before treating a `--steps 20` teleport run as a
true 20-step measurement.

Verified true 20-step check after reloading the inference process:

- Report: `evals/zimage_teleport_20260525T222932Z/report.md`
- Runtime mode: vanilla diffusers fallback (`zimage_use_cute=false`) because
  the CuteZImage reload hung during post-checkpoint initialization.
- Requested steps: `20`
- Server-reported effective steps: `20`
- Baseline server inference: `41.758s`
- Exact teleport replay server inference: `26.864s`
- Replay cache hit: `true`
- Replay quality versus baseline: `MSE=0`, `PSNR=inf`

This proves exact-prompt teleport replay preserves deterministic 20-step output
and skips enough denoising to cut server inference by about `36%` in the
vanilla fallback path. The same eval should be rerun on a healthy CuteZImage
reload before using the absolute latency numbers for production.

Later exact replay checks with configurable `teleport_start_step`:

- `evals/zimage_teleport_20260525T231012Z/report.md`
  - start step: `16` (4 refinement steps)
  - baseline server inference: `33.827s`
  - exact replay server inference: `16.979s`
  - quality: `MSE=0`, `PSNR=inf`
- `evals/zimage_teleport_20260525T231417Z/report.md`
  - start step: `19` (1 refinement step)
  - baseline server inference: `19.892s`
  - exact replay server inference: `15.391s`
  - quality: `MSE=0`, `PSNR=inf`

Interpretation: exact cached replay remains pixel-exact even when resuming very
late, but the vanilla fallback has a roughly `15s` floor at 512px because
prompt setup, offload/onload, VAE decode, encoding, and upload overhead dominate
after most denoising is skipped.

Approximate nearest-latent replay was tested as a cache-miss accelerator:

- `evals/zimage_approx_teleport_20260525T230533Z/report.md`
  - start step: default `7`
  - target full server inference: `20.462s`
  - approximate replay server inference: `23.442s`
  - quality: `PSNR=14.63`, visually retained the source red block instead of
    the target orange block
- `evals/zimage_approx_teleport_20260525T231203Z/report.md`
  - start step: `16`
  - target full server inference: `20.378s`
  - approximate replay server inference: `22.309s`
  - quality: `PSNR=14.46`, same source-color failure

Conclusion for approximate teleport: nearest cached latents by pooled Z-Image
text embedding are not production-usable yet. They were slower than warmed
20-step full generation in these smoke runs and failed the visual target. Keep
the endpoint path opt-in behind `teleport_approx=true` while experimenting with
better cache selection or a trained latent delta/forecaster.

No-offload vanilla diffusers was tested by restarting with
`ZIMAGE_CPU_OFFLOAD=0` while leaving `askfelix` and `text-generator.io`
resident:

- partial report: `evals/zimage_teleport_20260525T231903Z/`
- full 20-step baseline at `512x512`: `13.616s` server inference
- warmed offload comparison from nearby runs: about `19.9-20.5s`
- result: no-offload is a clear base-generation speed win when it fits
- caveat: with the resident `text-generator.io` process using about `8.4 GB`,
  no-offload left only tens of MB free, so prompt-embedding capture/replay OOMed
  and exact teleport could not be used safely

Recommendation: use no-offload vanilla Z-Image for a dedicated image worker or
when enough VRAM is free; keep CPU offload on for the shared worker that runs
beside text generation. The server now reports `zimage_cpu_offload` in `/health`
and guards teleport replay/cache embedding capture when free CUDA memory is too
low, so no-offload experiments fail back to full generation instead of returning
500s.

Deployment knob:

- `ZIMAGE_CPU_OFFLOAD=1`: safe shared-worker mode; lower peak VRAM, higher
  latency.
- `ZIMAGE_CPU_OFFLOAD=0`: fastest base-generation mode; requires enough free
  VRAM for transformer + text encoder + VAE plus request headroom.
- `ZIMAGE_CPU_OFFLOAD=auto`: choose no-offload only when free CUDA memory is at
  least `ZIMAGE_NO_OFFLOAD_MIN_FREE_MB` (default `24576` MB), otherwise use
  CPU offload. If the no-offload `.to(cuda)` load still fails, the server
  falls back to CPU offload and reports the effective mode in `/health`.

Use `ZIMAGE_CPU_OFFLOAD=auto` for a worker that might run dedicated sometimes
and shared other times. Keep `ZIMAGE_CPU_OFFLOAD=1` for the current always-shared
worker beside `text-generator.io`.

Run the L2P pixel-space runner with exact-prompt replay enabled. This is an
experimental measurement path for combining L2P with latent replay; it is not
cross-prompt visual-unit teleportation yet.

```bash
/nvme0n1-disk/code/.venv/bin/python scripts/zimage_l2p_eval.py \
  --repo-path ../T2I-L2P \
  --steps 20 \
  --teleport \
  --vram-limit 16
```

Latest L2P smoke:

- Report: `evals/zimage_l2p_20260525T225802Z/report.md`
- Runtime mode: disk-backed VRAM management for the L2P DiT, with resident
  `askfelix` and `text-generator.io` GPU processes left running.
- Size/steps: `256x256`, `4` steps
- Baseline L2P wall time: `56.915s`
- Exact replay from step 2 wall time: `28.188s`
- Replay quality versus baseline: `MSE=0`, `PSNR=inf`

This proves L2P exact-prompt replay is viable and deterministic, but it is not
currently a production speed win under disk offload. Re-test L2P full-CUDA on a
dedicated GPU window before comparing it against the production 4-20 step
Z-Image path.

Run slow pytest coverage for live GPU generation:

```bash
cd inference
RUN_SLOW_ZIMAGE_TESTS=1 INFERENCE_TEST_URL=http://127.0.0.1:8100 \
  /nvme0n1-disk/code/.venv/bin/python -m pytest test_server.py -k 'prompt_lengths or teleport_replay' -v
```

Bridge 5xx logs to CodexExec:

```bash
./monitoring/cutedsl_inference_autofix_monitor.sh
```

The monitor reads the structured error JSONL and passes a focused autofix prompt
to `codex exec` on stdin. It is intentionally separate from the inference
process so failures never spawn code agents inline with user traffic. It is
rate-limited to one agent run every 3 hours by default; see
`monitoring/README.md`.

## Next Targets

1. Add NVTX ranges around text encoding, transformer denoise steps, VAE decode,
   WebP encode, and R2 upload.
2. Profile first replay after restart separately from steady-state replay; the
   first replay still pays CUDA/kernel warmup.
3. Test async upload only behind an explicit flag. It can cut wall time by about
   `1.3s`, but clients may fetch before R2 propagation completes.
4. Revisit CuteZImage conversion hangs and NVFP4 in a sidecar process, not the
   live production process.
5. Explore a non-exact approximate teleport mode only with quality gates:
   require `SSIM >= 0.99`, `PSNR >= 40dB`, and manual sample review before
   making it default.
