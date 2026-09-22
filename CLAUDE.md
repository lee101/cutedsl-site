## Overview
Shared GPU inference defaults to MODEL_IDLE_TIMEOUT=20 seconds, with lazy reload on demand. Both forecast paths pin Chronos during execution. Install inference/systemd/cutedsl-chronos-idle.conf as a cutedsl-chronos.service drop-in to disable preloading and retain the timeout across deployment. Search embeddings already run on CPU. Unloading models does not destroy the process CUDA context.

CuteDSL Site - AI model acceleration and inference platform powered exclusively by $CUTEDSL token on Solana. Users connect their Solana wallet, deposit $CUTEDSL tokens, and use AI services with credits deducted based on current $CUTEDSL valuation.

## Architecture

### Frontend (Next.js)
- `frontend/` - Next.js 15 + React 19 + Tailwind CSS 4
- `/` - Home page: wallet connect, models, pricing, API docs, Applied AI NZ section
- `/evals` - Benchmarks and acceleration technique breakdowns (CuteChronos2, CuteZImage, Latent Teleportation, TurboQuant, NVFP4, stable-diffusion.cpp)
- `/blog` - Blog posts about each acceleration effort with deep dives
- Wallet connect (Phantom or manual address entry)
- Live $CUTEDSL pricing from backend API
- Deposit flow with Solana Pay URLs + SSE status updates
- Service pricing cards with live conversion

### Backend (Go + FastHTTP)
- `server/` - Go server with PostgreSQL database
- Crypto-only payment system (no Stripe) - $CUTEDSL token on Solana
- HD wallet derivation for unique deposit addresses per payment
- Price feeds from CoinGecko (SOL) and Bags API ($CUTEDSL)
- Background services: payment poller, sweeper, expired checkout cleaner
- AI service proxying with credit deduction and automatic refunds on failure

### Inference Server (Python + FastAPI)
- `inference/` - FastAPI server serving CuteDSL-accelerated models
- **zimage** - Z-Image Turbo text-to-image with CuteZImageTransformer (fused Triton kernels)
- **chronos2** - Chronos-2 time series forecasting with CuteChronos2Pipeline (24x speedup)
- **Kokoro TTS** - Text-to-Speech proxied to text-generator.io
- **STT** - Gemma4-powered speech-to-text proxied to text-generator.io
- **Gemma4 Chat** - Gemma4 26B multimodal LLM proxied to text-generator.io
- **Image Caption** - GitBase captioning proxied to text-generator.io
- NVFP4 quantization support for RTX 5090 (via torchao)
- torch.compile with reduce-overhead mode for max throughput
- Cooperative single-GPU handoff: image/Chronos cold loads synchronously sleep the managed text backend; `/admin/hold`, `/admin/unload`, and `/admin/release` keep diffusion from reloading during a Gemma boot/wake.

### Key Files
- `server/main.go` - Entry point, routes, static file serving
- `server/crypto.go` - $CUTEDSL payments, HD wallet, price feeds, Solana RPC
- `server/services.go` - AI service handlers, pricing, backend proxying
- `server/db.go` - PostgreSQL database (users, billing events, checkout intents)
- `server/models.go` - Data models
- `inference/server.py` - CuteDSL inference server (zimage, chronos2, proxy to text-generator.io)
- `frontend/app/page.tsx` - Main page with wallet connect, pricing, deposit UI

## Key Commands

### Development
```bash
# Install dependencies
make install

# Run inference server (port 8100 - AI models)
make inference

# Run inference with NVFP4 quantization (RTX 5090)
make inference-nvfp4

# Run backend (port 8080 - Go API)
make server

# Run frontend (port 3000)
make frontend

# Build everything
make build
```

### API Endpoints
- `POST /api/auth/wallet` - Register/login by wallet address
- `GET /api/balance?wallet=...` - Get $CUTEDSL balance
- `POST /api/crypto-checkout` - Create deposit intent
- `GET /api/crypto-checkout/:id` - Get checkout status
- `GET /api/crypto-checkout/:id/events` - SSE stream for payment status
- `GET /api/cute-price` - Current $CUTEDSL and SOL prices
- `GET /api/pricing` - All service pricing in USD and $CUTEDSL
- `POST /api/service` - Use an AI service (deducts credits)
- `GET /api/billing-history?wallet=...` - Transaction history
- `GET /api/uploads/presign?filename=&content_type=&dataset=` - Presigned R2 PUT URL (Bearer API key) for direct browser/CLI uploads; returns `upload_url` + `public_url`. Frontend helper: `frontend/lib/uploads.ts`, UI widget: `frontend/lib/media-upload-field.tsx` (drag/drop, mic recording, examples)

### Services Available
| Service | Price | Backend | Description |
|---------|-------|---------|-------------|
| zimage | $1.00/gen | CuteDSL inference | Z-Image Turbo text-to-image |
| chronos2 | $0.002/forecast | CuteDSL inference | Chronos-2 time series forecasting |
| tts | $0.10/100chars | text-generator.io proxy | Kokoro TTS (20+ voices) |
| stt | $0.20/min | text-generator.io proxy | Gemma4 audio transcription |
| gemma4 | $0.05/req | text-generator.io proxy | Gemma4 26B chat/vision |
| caption | $0.05/image | text-generator.io proxy | GitBase image captioning |
| ltx_video | $0.30/video | fal.ai proxy | LTX 2.3 text-to-video |
| video_generate | from $0.08/video | OpenPaths + local AV1 | Text/image-to-video with AV1 R2 publishing |
| h3_video | $2.688/GPU-hour | app.nz Cog | MiniMax H3 T2V/I2V, loop conditioning, audio, AV1; metered per execution |
| flux_image | $0.04/image | fal.ai proxy | Flux Schnell fast image gen |

### Pricing Model
- **First-party services** (zimage, chronos2, TTS, etc): Priced at ATH token rate — early holders get cheaper rates forever
- **Third-party proxies** (ltx_video, flux_image): Priced at current market rate
- **?test=true**: Append to homepage URL to run e2e API tests in browser

## Environment Variables
See `.env` for all configuration. Key vars:
- `SOLANA_PRIVATE_KEY`, `SOL_ADDR`, `HD_WALLET_SEED` - Solana wallet
- `HELIUS_API_KEY` - Solana RPC (high rate limit)
- `BAGS_API_KEY` - $CUTEDSL price feed
- `FAL_KEY` - fal.ai API key for LTX video and Flux image
- `OPENPATHS_API_KEY`, `OPENPATHS_BASE_URL` - OpenPaths video model routing
- `APPNZ_API_KEY`, `APPNZ_BASE_URL` - app.nz API credentials for the shared MiniMax H3 Cog
- `H3_VIDEO_PRICE_USD_PER_GPU_HOUR` - downstream H3 reference rate (default $2.688, app.nz rate plus 20%); completed jobs settle from app.nz's actual `costMicros`
- `R2_PUBLIC_HOST` - public host for optimized AV1 results (keep `appstatic.app.nz` until `cutedslstatic.cutedsl.cc` DNS/custom-domain setup is live)
- `VIDEO_GENERATE_PRICE_USD` - fallback price for OpenPaths video models; known models use the per-model table in `server/services.go`
- `CUTE_TOKEN_MINT` - $CUTEDSL SPL token address
- `INFERENCE_BACKEND_URL` - CuteDSL inference server URL
- `TG_BACKEND_URL` - omniserve-native gateway for TTS/STT/Gemma4/Caption (`http://127.0.0.1:8791`; it fans out to the text-generator compat worker on :9083 and the ASR router on :9096). The old direct :9080 worker no longer runs. Auth is the `secret` header from `TG_API_KEY`, which must match `NETWRCK_PARTNER_SECRET` in `/etc/netwrck-image-caption.env`
- `ZIMAGE_TEXT_ENCODER_DEVICE` / `ZIMAGE_TEXT_ENCODER_QUANT` - keep the Qwen3 text encoder GPU-resident with weight-only quant (`int8wo` ~4 GB and fastest, `nvfp4` ~2.2 GB and the current prod setting). This host's CPU is AVX2-only, so a CPU-pinned encoder costs ~5 s per uncached prompt vs ~0.1-0.6 s on GPU. Placement is reported at `/health` → `models.text_encoder`
- `LATENT_TELEPORT_APPROX_DEFAULT` - allow `/generate_image` to resume from a *similar* prompt's cached latent (per-request override: `teleport_approx`, `teleport_approx_min_sim`). Off by default: ~2x faster but it is a quality trade, not a transparent cache hit
- `COEXISTING_TEXT_SLEEP_URL` - managed text adapter sleep endpoint (default `http://127.0.0.1:8300/backend/sleep`)
- `PRELOAD_DELAY_SECONDS` - cancellable delay before background model preload (default `1`), allowing socket bind failures to abort before touching GPU state
- `INFERENCE_WAIT_FOR_EXISTING_SERVER` - keep a systemd-managed standby quiet when another local instance already owns the inference port (default `1`)
- `INFERENCE_EXISTING_SERVER_POLL_SECONDS` - standby port polling interval (default `5` seconds)
- `COEXISTING_TEXT_SLEEP_TIMEOUT` - maximum seconds to wait for the text backend to release GPU residency (default 120)
- `ENABLE_NVFP4` - Enable NVFP4 quantization for RTX 5090
- `*_PRICE_USD` - Service pricing in USD

## Image Gallery & Search
- `/search` page — browse/search 100k+ AI-generated images
- Images stored on `/sdb-disk/cutedsl-images` (symlinked as `./images/`)
- Three sizes: originals (1024x1024), medium (512x512), thumbs (256x256), all WebP q85
- Latent tensors saved alongside images in `latents/` for future latent teleportation
- NSFW classifier: `Falconsai/nsfw_image_detection` via HuggingFace, loaded on-demand in inference server (not kept in GPU memory permanently)
- Prompts from `daspartho/stable-diffusion-prompts` (1.8M prompts) stored in `/sdb-disk/cutedsl-images/prompts.jsonl`

### Gallery Scripts
```bash
# Download prompt dataset
python scripts/download_prompts.py

# Generate images from prompts (requires inference server running)
python scripts/generate_images.py --limit 1000

# Backfill NSFW classification
python scripts/backfill_nsfw.py --limit 1000
```

## CuteDSL Framework (`../cutedsl`)

The CuteDSL framework accelerates ML models through custom Triton/CUDA kernels with torch.compile integration. It maintains output equivalence (max abs error < 1e-4) while achieving 1.3x-27x speedups.

### Architecture
- **Multi-tier backend selection**: CUTLASS → Triton → SDPA → PyTorch (automatic fallback)
- **Environment overrides**: `CUTECHRONOS_RMS_BACKEND`, `CUTECHRONOS_ATTENTION_BACKEND`, `CUTECHRONOS_FUSED_QKV`
- **torch.compile**: `reduce-overhead` mode for CUDA graph caching, `fullgraph=False` for graceful graph breaks

### Modules

**CuteChronos2** (`cutechronos/`) — Amazon Chronos-2 time series forecasting
- Encoder-only transformer (12 layers, 768 d_model, 12 heads)
- 8 custom Triton kernels: unscaled tiled attention, fused LayerNorm+Linear, fused MLP, RoPE, fused preprocessing, fused output, RMS LayerNorm
- CUDA C++ extension for NaN-aware preprocessing with shared memory reductions
- Results: 42ms → 1.55ms (**27.1x speedup**) on RTX 5090, context=768

**CuteZImage** (`cutezimage/`) — Z-Image Turbo text-to-image diffusion
- 30-layer transformer (dim=3840, 30 heads, SiLU-gated FFN hidden=10240)
- 5 Triton kernels: fused SiLU-gate FFN, AdaLN+RMS norm, QKV+norm+RoPE, complex RoPE, RMS norm
- 3 CUDA C++ kernels for RMS norm, SiLU gate (vectorized bfloat162/float4)
- `from_diffusers()` weight loading from HuggingFace

**TurboQuant** (`turboquant/`) ��� Vector quantization for KV cache compression
- MSE and product quantizers with Hadamard rotation
- 3.66x-8x compression with <2% quality loss

**LatentTeleport** (`latentteleport/`) — Latent caching and refinement
- Pre-caches intermediate diffusion latents, SLERP interpolation
- Reduces denoising steps from ~20 to ~5 for similar prompts

**CuteParakeet** (`cuteparakeet/`) — Nvidia Parakeet ASR acceleration

### Key Design Patterns
- Every custom kernel has a pure PyTorch fallback
- FP32 variance computation for numerical stability despite BF16 inputs
- `.reshape()` instead of `.contiguous().view()` to avoid copies
- In-place residual adds under `torch.inference_mode()`
- Cached position_ids via `register_buffer()`

## Related Projects
- `../cutedsl` - CuteDSL ML acceleration framework (cutechronos, cutezimage, etc.)
- `../netwrck` - Reference for LoRA auto-balancing, NSFW detection, image search patterns
- `../text-generator.io` - Text-Generator.io inference server (TTS, STT, Gemma4, captioning)
- `../codex-infinity-site` - Reference for crypto payment patterns
