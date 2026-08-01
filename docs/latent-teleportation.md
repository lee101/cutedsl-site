# Latent Teleportation

Speculative and cache-guided acceleration of diffusion samplers: drafting the
next few latents cheaply, then letting the big model correct them. The full
write-up is the paper in `cutedsl/paper/latent_teleportation.pdf`; this page is
the operational summary, including which parts we recommend deploying and which
we do not.

## The idea

Speculative decoding sped up language models by exploiting a hardware accident:
decoding one token reads the entire weight matrix, so checking five drafted
tokens in one wider batch costs about what checking one costs. A cheap drafter
proposes, the real model verifies, and because verification is exact the output
distribution is unchanged.

Diffusion sampling looks like it should admit the same trick. It is iterative,
each iteration is one pass over a large transformer, and the latents trace a
smooth curve rather than a sequence of discrete symbols — if anything easier to
extrapolate than text.

Three mechanisms were built:

- **Speculative latent walking.** The big model takes one real step, a small
  FiLM-conditioned CNN drafts the next `k` from the trajectory's momentum, and a
  gap interpolator teleports the draft endpoint onto where the big model would
  plausibly have landed. Both networks are zero-initialised residuals, so at
  initialisation they are exactly a momentum extrapolator.
- **Confidence-gated Taylor forecasting.** A first-order Taylor step in the
  step index, `x + k*(x - x_prev)`, with a gate that tracks recent prediction
  error and spends more real steps when the forecast looks unreliable. This is
  the CG-Taylor / TaylorSeer line.
- **k-NN latent teleportation.** A cache of previously refined trajectories,
  indexed by prompt embedding and by "visual unit" fragments. A new prompt
  retrieves its nearest neighbours, combines their latents at an injection
  timestep, and runs only the remaining steps — starting from where similar
  generations ended up rather than from noise.

## What the measurements say

Measured on an RTX 5090, Z-Image Turbo, 512x512, 16-step schedule, bf16.

**The trajectory is genuinely forecastable.** A first-order momentum step
predicts the next latent with relL2 = 0.205 at mid-trajectory, where relL2 is
error divided by how far the latent actually moved — so 1.0 is the score of
predicting no movement at all. A scalar affine predictor scores ~0.88, i.e.
nearly useless, which tells us the predictability is directional rather than a
matter of step size.

**The call reduction is real.** Drafting at `k=3` runs 5 real denoiser calls out
of 16, a 3.2x reduction.

**None of it becomes wall-clock time.**

| draft k | real steps | call reduction | speedup (spec) | speedup (taylor) | speedup (skip) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 9 | 1.8x | 1.02x | 1.08x | 1.03x |
| 2 | 6 | 2.7x | 1.03x | 1.03x | 1.04x |
| 3 | 5 | 3.2x | 1.04x | 1.09x | 1.10x |

The `skip` column is the diagnostic. That arm throws away 3.2x of the denoiser
calls and corrects nothing — its output is noise, 8.9 dB PSNR — and it still only
reaches 1.10x. No drafting scheme can beat that bound, so at this operating
point roughly 90% of measured time is not the denoiser. The timed region wraps
text encoding and VAE decode, and at 512x512 on an already-distilled Turbo model
those fixed costs dominate. Amdahl, on schedule.

## Recommendations

1. **Do not deploy the learned walker.** At `k=1` it is beaten on both axes by
   the three-line training-free Taylor step: 1.02x / 18.9 dB against 1.08x /
   20.8 dB. It wins on the metric it was trained for (relL2) and loses on the
   metric that matters.
2. **If you draft, use Taylor at `k=1`.** Best measured speed/quality point, no
   checkpoint, no training data, no per-model fitting.
3. **Skip the final scheduler step unconditionally.** It moves the latent by
   approximately zero — free and exact. It also makes relL2 divide by nothing,
   which is how we found it (the cell reports 5.5e9).
4. **Fix the harness before claiming any acceleration.** Warm up before timing,
   and time the sampling loop separately from text encode and VAE decode.
5. **Re-measure where the denoiser dominates** — higher resolution, longer
   schedules, or batch > 1 — before concluding the approach does or does not
   work. The predictability result says the signal exists; the end-to-end result
   says this harness cannot see it.

## A correction worth repeating

Our first reading of these runs reported **1.5x**. It was wrong, and generically
so: the harness times the baseline arm first with no warm-up, so prompt 0's
baseline absorbed CUDA context creation and kernel autotuning — 140.6 s against a
28.3 s median for identical work. Speedup is computed per prompt as
`t_baseline / t_method` and then averaged, so that one contaminated row
contributed a spurious 3.79x and carried the mean. Corrected, it is 1.04x.

Any benchmark that times a cold arm first and averages ratios will do this.
`cutedsl/scripts/paper_analysis.py` now excludes rows whose baseline exceeds
twice the median and reports what it dropped, and every number in the paper is
generated by it rather than typed.

## Quality metrics

PSNR ranks these arms correctly but calibrates them badly. A drafted trajectory
that lands on a different but equally plausible image is penalised as heavily as
one that lands on mush: the drafted images are coherent photographs that differ
compositionally from the baseline, while the skip arm's output is noise. Same
caveat as [the diffusion frontier](./diffusion-frontier.md) — PSNR/SSIM/LPIPS are
retention checks, not quality rankings. A perceptual or preference judge is
needed for the real comparison, and has not yet been run.

## Where this fits

CuteDSL's fused sm_120 kernels for the Z-Image transformer (fused QKV+RoPE,
QK-norm, RMS norm, SiLU-gated FFN, AdaLN) make each step cheaper; latent
teleportation tries to make steps fewer. Given the Amdahl result above, the
kernel work is currently the better investment at this operating point, and the
two are complementary rather than competing.

Serving integration — admission control, VRAM lease brokering between co-tenant
models, and a C request path that relays image bytes without re-encoding — lives
in `omniserve-native`.
