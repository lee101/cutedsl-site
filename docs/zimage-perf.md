# Z-Image Performance Notes

## Current Production Shape

- Public route: `https://images.netwrck.com/create_and_upload_image`
- Local inference: `http://localhost:8100/create_and_upload_image`
- Default backend: vanilla diffusers Z-Image Turbo, `bfloat16`, no CPU offload.
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
