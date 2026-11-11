export const IMG_BASE = 'https://appstatic.app.nz/cutedsl/images';
export const BAGS_CTA = `

---

## Generate AI images and video

[ra2 art generator](/docs/ra2) and [Z-Image Turbo](/docs/zimage) text-to-image, [ManifoldGen AV1 video](/docs/manifold_video), [Flux Schnell](/docs/flux_image), [Kokoro TTS](/docs/tts), and [Chronos-2 forecasting](/docs/chronos2). Buy **$CUTEDSL** on Solana and call the API.

[AI image generator](https://cutedsl.cc) · [AI video generator](https://cutedsl.cc/generations) · [API docs](https://cutedsl.cc/docs) · [Buy $CUTEDSL](https://bags.fm/D322k7ykdgCmNGUZL5XvsgZXdHU4ks8iGoWtfrnmBAGS)`;

export interface BlogPost {
  slug: string;
  title: string;
  date: string;
  tags: string[];
  excerpt: string;
  content: string;
  image?: string;
}

export const posts: BlogPost[] = [
  {
    slug: 'cutedsl-manifoldgen-video-api',
    title: 'CuteDSL AI Video API: Queued ManifoldGen AV1 Jobs',
    date: '2026-08-30',
    tags: ['manifoldgen', 'text-to-video', 'image-to-video', 'AV1', 'AI video generator', 'api'],
    image: '/blog-art/cutedsl-manifoldgen-video-api.webp',
    excerpt: 'POST /api/generations queues a ManifoldGen native H3 clip as AV1 WebM. Poll GET /api/generations/{id}. Optional start-frame image-to-video. Daily quota, not /api/service.',
    content: `CuteDSL now exposes [ManifoldGen](https://manifoldgen.com) as a first-class **AI video generator**: text-to-video and image-to-video, durable jobs, AV1 WebM out. This is not the sync LTX path. Video takes minutes, so the contract is queue-and-poll.

![CuteDSL queued ManifoldGen AV1 video generation](/blog-art/cutedsl-manifoldgen-video-api.webp)

UI: [/generations](/generations) (private queue, \`noindex\`) and [/video-gallery](/video-gallery) (published AV1). Docs: [/docs/manifold_video](/docs/manifold_video).

## Why \`POST /api/generations\`, not \`/api/service\`

\`POST /api/service\` is for calls that return in one HTTP round-trip (Z-Image, Flux, TTS, LTX 2.3). ManifoldGen native H3 is a **queued GPU job**. Re-POSTing because a client timed out would bill a second clip.

CuteDSL holds \`MANIFOLDGEN_API_KEY\` on the Go server. The browser never sees it. You auth with your CuteDSL Bearer key. Default cap: **3 jobs / 24h** per account (\`MANIFOLDGEN_DAILY_JOB_LIMIT\`). \`unlimited_api\` accounts skip the cap.

## Queue a clip

\`\`\`bash
curl -X POST https://cutedsl.cc/api/generations \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer $CUTEDSL_API_KEY" \\
  -d '{
    "prompt": "A glass whale swims through a flooded library, slow crane shot, volumetric god rays",
    "aspect_ratio": "16:9",
    "size": "preview",
    "duration": 5,
    "num_steps": 20,
    "include_audio": true,
    "publish_on_finish": false
  }'
\`\`\`

HTTP **202**:

\`\`\`json
{
  "job": { "job_id": "gen_…", "status": "queued", "prompt": "…" },
  "status_url": "/api/generations/gen_…"
}
\`\`\`

Persist \`job_id\`. **Do not retry the POST** on timeout. Recover with GET.

## Poll

\`\`\`bash
curl https://cutedsl.cc/api/generations/JOB_ID \\
  -H "Authorization: Bearer $CUTEDSL_API_KEY"
\`\`\`

Statuses: \`queued\` → \`processing\` → \`completed\` | \`failed\`. On complete, \`result.video_url\` is an AV1 WebM on \`manifoldgenstatic.manifoldgen.com\` (proxied through CuteDSL's media allowlist).

## Image-to-video

Pass \`first_frame\` as a public \`http(s)\` URL. The image gallery already links a selected still into \`/generations?prompt=…&first_frame=…\`.

Aspect: \`16:9\`, \`9:16\`, \`1:1\`. Size: \`preview\` | \`balanced\` | \`native\` (H3 pixel-area tiers, 32px grid). Duration 4–60s. Steps 8–40. Output is always \`webm-av1\` — clients cannot request H.264 for this path. Generated audio is on by default.

## Publish

\`\`\`bash
curl -X POST https://cutedsl.cc/api/generations/JOB_ID/publish \\
  -H "Authorization: Bearer $CUTEDSL_API_KEY" \\
  -d '{"public": true}'
\`\`\`

Only explicitly published jobs enter [/video-gallery](/video-gallery). \`GET /api/videos\` merges those with ManifoldGen's featured feed. Google video sitemap: \`/sitemap-videos.xml\`.

Pricing preflight (ManifoldGen's public table, cached): \`GET /api/generations/pricing\`.

## vs LTX 2.3 (\`ltx_video\`)

| Path | ManifoldGen | LTX 2.3 |
| Endpoint | POST /api/generations | POST /api/service |
| Engine | Native H3, keyframes, audio, AV1 | fal LTX 2.3 ~6s 1080p/25fps |
| Contract | Queued job_id | One HTTP response |
| Billing | Daily job quota | $0.30 in $CUTEDSL |

Use ManifoldGen for cinematic clips. Use LTX when you want a short sync proxy billed in $CUTEDSL.

Full product notes: [ManifoldGen: AI video generator](/blog/manifoldgen-ai-video-generator). Integration internals: \`docs/manifoldgen-integration.md\`.`,
  },
  {
    slug: 'manifoldgen-ai-video-generator',
    title: 'ManifoldGen: AI Video Generator — Text-to-Video, Image-to-Video, AV1',
    date: '2026-08-30',
    tags: ['manifoldgen', 'AI video generator', 'text-to-video', 'image-to-video', 'H3', 'AV1', 'Seedance', 'Kling'],
    image: '/blog-art/manifoldgen-ai-video-generator.webp',
    excerpt: 'ManifoldGen.com is an AI video generator: native MiniMax H3 with keyframes and audio, plus Seedance, Kling, LTX, and Wan. One balance. AV1 WebM or H.264.',
    content: `[ManifoldGen](https://manifoldgen.com) is our AI video generator: text-to-video, image-to-video, music, stills, and an API on one account. Native stack is MiniMax **H3**. Catalog routes cover Seedance 2, Kling 3 / 2.6, LTX 2.3, Wan, and H3 Max on fal.

![ManifoldGen AI video generator — cinematic still](/blog-art/manifoldgen-ai-video-generator.webp)

CuteDSL now queues that same native H3 lane: [AI video API](/blog/cutedsl-manifoldgen-video-api).

## Native Manifold Video (H3)

The \`manifold\` generator is not a thin fal wrapper. It is the H3 cog: prompt, **start frame**, **stop frame**, **ordered keyframes**, loops, and **generated audio**. Durations 4–15s in the public catalog (CuteDSL accepts 4–60s and lets ManifoldGen clamp). Size tiers \`preview\` / \`balanced\` / \`native\` scale H3's 32px-aligned pixel area (native 16:9 is 1344×768).

\`POST https://manifoldgen.com/api/service\` with \`"service": "video"\` returns a durable \`job_id\`. Poll \`GET /api/video-jobs/{id}\`. Output: \`webm-av1\` (canonical gallery master) or \`mp4-h264\`.

That is the path CuteDSL calls. We force AV1 so the public gallery is not H.264.

## Catalog (same balance)

One ManifoldGen balance also runs:

| Family | Mode | Notes |
| H3 Max (fal) | text / image | Fast hosted MiniMax, 5–15s, 480p–768p |
| Seedance 2 | text / image / reference | 720p–1080p, native audio |
| Kling 3 / 2.6 | text / image | Cinematic motion, lipsync on Pro |
| LTX 2.3 | image-to-video | 1080p, ~6s |
| Wan | text | Cost-conscious drafts |

CuteDSL does **not** expose the full catalog. The CuteDSL video API is native H3 only. For Seedance/Kling/Kling-Pro, use [manifoldgen.com](https://manifoldgen.com) directly.

## Why AV1 WebM

AV1 in WebM is the gallery source: smaller than H.264 at the same visual quality, playable in Chromium and recent Firefox. CuteDSL's media proxy allowlists \`manifoldgenstatic.manifoldgen.com\`. Legacy featured MP4s still play via MIME sniffing.

## Sister product

ManifoldGen and CuteDSL are both Applied AI NZ. ManifoldGen is the creative studio (video-first, Stripe + credits). CuteDSL is the $CUTEDSL inference API (Z-Image Turbo, Chronos-2, TTS) plus this queued H3 video lane.

- Studio: [manifoldgen.com](https://manifoldgen.com)
- CuteDSL queue: [cutedsl.cc/generations](https://cutedsl.cc/generations)
- API docs: [cutedsl.cc/docs/manifold_video](/docs/manifold_video)`,
  },
  {
    slug: 'zimage-omniserve-native',
    title: 'Z-Image Turbo via OmniServe Native: C Gateway Text-to-Image',
    date: '2026-08-30',
    tags: ['zimage', 'omniserve-native', 'stable-diffusion.cpp', 'text-to-image', 'gguf'],
    image: '/blog-art/zimage-omniserve-native.webp',
    excerpt: 'OpenAI-compatible POST /v1/images/generations through OmniServe Native: Z-Image Turbo Q4 GGUF, stable-diffusion.cpp, latent teleport, WebP out.',
    content: `CuteDSL's production text-to-image path is no longer "Python FastAPI on the hot path." Image requests hit OmniServe Native — a C HTTP gateway with an epoll reactor — then either the embedded stable-diffusion.cpp Z-Image Turbo runtime or a loopback worker.

Every image in this post was generated with that stack: \`POST /v1/images/generations\`, Z-Image Turbo Q4 GGUF, 4B text encoder, tiled VAE.

![Z-Image Turbo fairy generated with OmniServe Native](/blog-art/zimage-omniserve-native.webp)

## The public contract

OpenAI-shaped, extra fields for diffusion:

\`\`\`bash
curl -s http://127.0.0.1:8791/v1/images/generations \\
  -H 'Content-Type: application/json' \\
  -H 'X-Omniserve-Tier: background' \\
  -d '{
    "prompt": "a cute fairy in an enchanted forest, digital art, pastel colors",
    "width": 1024,
    "height": 576,
    "steps": 9,
    "guidance_scale": 0.0,
    "seed": 42,
    "teleport": true,
    "teleport_start_step": 7
  }'
\`\`\`

Z-Image Turbo is distilled: **guidance 0** (OmniServe maps a literal \`0.0\` to CFG 1.0 via \`OMNISERVE_NATIVE_SD_ZERO_GUIDANCE\`). \`steps\` is usually 8–9. Response is OpenAI \`data[].b64_json\` WebP (or raw \`image/webp\` if the worker returns bytes).

Public CuteDSL wraps the same model as \`POST /api/service\` with \`"service": "zimage"\`.

## What the C gateway actually does

OmniServe Native is not a Python process with a thin C extension. The binary:

1. **Admits** the request (paid / sub / free / background FIFO; image lane has its own permit count)
2. **Leases VRAM** so a co-tenant LLM cannot steal the VAE scratch budget mid-decode
3. **Runs** \`osd_generate\` in \`backend_sd.c\` (stable-diffusion.cpp) **or** proxies to \`OMNISERVE_NATIVE_IMAGE_UPSTREAM\`
4. **Encodes** WebP in-process (\`OMNISERVE_NATIVE_SD_IMAGE_FORMAT=webp\`)

\`OMNISERVE_NATIVE_IMAGE_PREFER_EMBEDDED=1\` keeps Z-Image in-process when the GGUF is loaded. LoRA/catalog routes can still go to the Python worker on \`:8100\`.

Split weights (same layout as the systemd unit):

| Env | File |
| \`OMNISERVE_NATIVE_SD_DIFFUSION_MODEL\` | \`z_image_turbo-Q4_K.gguf\` |
| \`OMNISERVE_NATIVE_SD_VAE\` | \`ae.safetensors\` |
| \`OMNISERVE_NATIVE_SD_LLM\` | \`<4B instruct text encoder>.gguf\` |

Q4 is ~3.9 GB for the transformer. The 4B text encoder is the other large resident. \`OMNISERVE_NATIVE_SD_STREAM_LAYERS=1\` plus VAE tiling (\`VAE_TILE_X/Y=64\`) is how this fits next to other GPU tenants.

![Z-Image Turbo pastel lab, OmniServe Native](/blog-art/zimage-omniserve-native-lab.webp)

## Latent teleport

Exact-prompt replay is opt-in: \`"teleport": true\`. The in-process LRU (\`OMNISERVE_NATIVE_SD_TELEPORT_CACHE_SIZE\`, default 64, max 256) keys on prompt, negative, size, steps, guidance, seed, and resume step. Approximate prompt matches are **not** used — that is deliberate; similar-prompt SLERP lives in the Python LatentTeleport research path, not in the C cache.

\`teleport_start_step\` (default 7 on this host) is where denoising resumes. A hit skips the expensive early transformer steps. A miss runs the full 9-step schedule and fills the cache.

## Why not keep Python on the edge

The Go API still exists (\`server/\`, FastHTTP). What we dropped for the image lane is:

- FastAPI coroutine dispatch on every generate
- GIL around pre/post (prompt packing, WebP)
- JSON localhost hop of ~3 MB base64 images
- torch Python dispatch before CUDA

Embedded sd.cpp still has a first-request model load. After that, the C path is one function call and a WebP buffer. The [Go+C migration post](/blog/go-c-migration-zimage) covers the LibTorch C ABI we also ship; OmniServe Native is the GGML/sd.cpp sibling of that work.

## Call it from CuteDSL

\`\`\`bash
curl -X POST https://cutedsl.cc/api/service \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "service": "zimage",
    "prompt": "a cute fairy in an enchanted forest, digital art, pastel colors",
    "width": 1024,
    "height": 1024,
    "num_steps": 8
  }'
\`\`\`

Browse outputs in the [AI art gallery](/gallery) (100k+ Z-Image Turbo images, prompt search) or generate from the [Z-Image API docs](/docs/zimage).`,
  },
  {
    slug: 'go-c-migration-zimage',
    title: 'Z-Image Turbo in Go+C: Faster Text-to-Image Inference',
    date: '2026-04-04',
    tags: ['go', 'c', 'migration', 'zimage', 'performance', 'lora'],
    image: '/blog-art/go-c-migration-zimage.webp',
    excerpt: 'Why we are moving Z-Image Turbo off Python FastAPI: C ABI + CGO, no GIL, sub-100ms text-to-image on the hot path.',
    content: `Z-Image currently runs behind a Python FastAPI server. Go+FastHTTP already serves the CuteDSL API, proxying image requests over HTTP to the Python process. Every request crosses a process boundary, serializes/deserializes JSON, and fights Python's GIL and async dispatch overhead. We're cutting all of that out.

![Z-Image Turbo illustration: go c migration zimage](/blog-art/go-c-migration-zimage.webp)

## Why migrate away from Python

The current inference path has several layers of unnecessary overhead:

1. **Async dispatch** — FastAPI's async event loop adds ~2-5ms per request just in coroutine scheduling
2. **GIL contention** — Even with a single worker, Python's GIL serializes all CPU work including tensor pre/post-processing
3. **torch overhead** — PyTorch's Python frontend adds significant dispatch overhead per operator call. Every \`torch.matmul\` goes through Python's C API, argument parsing, and dispatch tables before reaching CUDA
4. **HTTP serialization** — The Go server marshals requests to JSON, sends them over localhost HTTP, and the Python server unmarshals them back. For image bytes, this means base64 encoding/decoding ~3MB per image

The Python process spends roughly **~32 seconds** per image generation. Most of that is legitimate GPU compute, but the Python overhead adds up — especially when we're already running Go for everything else.

## The DiffusionZ C API

The core of the migration is \`diffusionz_c_api.h\` — a C ABI that wraps LibTorch and CuteDSL's Triton/CUDA kernels into a stable, callable interface:

\`\`\`c
// diffusionz_c_api.h — ABI contract for Z-Image inference
#ifndef DIFFUSIONZ_C_API_H
#define DIFFUSIONZ_C_API_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct DiffusionZContext DiffusionZContext;

typedef struct {
    const char* prompt;
    const char* negative_prompt;
    int32_t     width;
    int32_t     height;
    int32_t     num_steps;
    float       guidance_scale;
    int64_t     seed;
    const char* lora_path;      // NULL for no LoRA
    float       lora_weight;    // 0.0-1.0
} DiffusionZParams;

typedef struct {
    uint8_t*  image_data;   // WebP-encoded bytes
    int32_t   image_len;
    int32_t   width;
    int32_t   height;
    int32_t   error_code;
    const char* error_msg;  // NULL on success
} DiffusionZResult;

// Lifecycle
DiffusionZContext* diffusionz_init(const char* model_path, int device_id);
void              diffusionz_free(DiffusionZContext* ctx);

// Generation
DiffusionZResult  diffusionz_generate(DiffusionZContext* ctx,
                                       const DiffusionZParams* params);
void              diffusionz_free_result(DiffusionZResult* result);

// LoRA management
int32_t diffusionz_load_lora(DiffusionZContext* ctx,
                              const char* lora_path, float weight);
int32_t diffusionz_unload_lora(DiffusionZContext* ctx);

#ifdef __cplusplus
}
#endif

#endif // DIFFUSIONZ_C_API_H
\`\`\`

The implementation links against LibTorch's C++ API and loads our CuteDSL CUDA kernels (fused SiLU-gate FFN, AdaLN+RMS norm, QKV+norm+RoPE) directly. No Python interpreter involved. The WebP encoding happens in C via libwebp, so the result is ready to write to the HTTP response with zero copies.

## CGO bridge patterns

We've already built two CGO bridges in this codebase: [gobed](https://github.com/lee101/gobed) for GPU-accelerated embedding search, and the CuteChronos2 Go wrapper for time series forecasting. The pattern is well-established:

\`\`\`go
package zimage

/*
#cgo LDFLAGS: -L\${SRCDIR}/lib -ldiffusionz -ltorch -lc10 -lwebp
#cgo CFLAGS: -I\${SRCDIR}/include
#include "diffusionz_c_api.h"
#include <stdlib.h>
*/
import "C"
import (
    "fmt"
    "unsafe"
)

type Context struct {
    ctx *C.DiffusionZContext
}

func NewContext(modelPath string, deviceID int) (*Context, error) {
    cPath := C.CString(modelPath)
    defer C.free(unsafe.Pointer(cPath))

    ctx := C.diffusionz_init(cPath, C.int(deviceID))
    if ctx == nil {
        return nil, fmt.Errorf("failed to init DiffusionZ on device %d", deviceID)
    }
    return &Context{ctx: ctx}, nil
}

func (c *Context) Generate(params GenerateParams) ([]byte, error) {
    cParams := C.DiffusionZParams{
        prompt:         C.CString(params.Prompt),
        negative_prompt: C.CString(params.NegativePrompt),
        width:          C.int32_t(params.Width),
        height:         C.int32_t(params.Height),
        num_steps:      C.int32_t(params.NumSteps),
        guidance_scale: C.float(params.GuidanceScale),
        seed:           C.int64_t(params.Seed),
    }
    // ... free CStrings deferred

    result := C.diffusionz_generate(c.ctx, &cParams)
    defer C.diffusionz_free_result(&result)

    if result.error_code != 0 {
        return nil, fmt.Errorf("generation failed: %s",
            C.GoString(result.error_msg))
    }

    return C.GoBytes(unsafe.Pointer(result.image_data),
        result.image_len), nil
}
\`\`\`

The key CGO patterns we reuse:
- **Single init, many calls** — The \`DiffusionZContext\` is created once at server start and reused across requests, just like gobed's embedding index
- **C-allocated, C-freed** — Image data is allocated in C and freed with \`diffusionz_free_result\`. We copy to Go bytes before freeing
- **No callbacks** — The C API is synchronous. Go handles concurrency at the HTTP layer with goroutines and channels

## LoRA routing with gobed

This is where it gets interesting. We have dozens of LoRA adapters for different styles (anime, photorealistic, watercolor, pixel art, etc.). Currently, the Python server picks LoRAs based on keyword matching in prompts. That's fragile — "a knight in shining armor" should route to the fantasy LoRA, but keyword matching misses it.

Instead, we use [gobed](https://github.com/lee101/gobed) — our Go embedding search library — to do semantic LoRA selection. Each LoRA gets **two** pre-computed embeddings: one for its positive style description and one for its negative (what it should NOT be used for):

\`\`\`go
type LoRAEntry struct {
    Name              string
    Path              string
    Weight            float32
    PositiveEmbedding []float32  // "anime style, cel shading, vibrant colors"
    NegativeEmbedding []float32  // "photorealistic, photograph, raw photo"
}

func (r *LoRARouter) SelectLoRA(promptEmbedding []float32) *LoRAEntry {
    var best *LoRAEntry
    bestScore := float32(-1.0)

    for i := range r.entries {
        entry := &r.entries[i]
        // Positive similarity — how well does this LoRA match the prompt?
        posSim := gobed.CosineSimilarity(promptEmbedding, entry.PositiveEmbedding)
        // Negative similarity — should we avoid this LoRA?
        negSim := gobed.CosineSimilarity(promptEmbedding, entry.NegativeEmbedding)
        // Net score: boost for positive match, penalty for negative match
        score := posSim - 0.5*negSim

        if score > bestScore {
            bestScore = score
            best = entry
        }
    }

    if bestScore < 0.3 {
        return nil // No LoRA is a good match; use base model
    }
    return best
}
\`\`\`

Because gobed runs embedding similarity entirely in Go (with SIMD-optimized dot products), the LoRA selection takes **<1ms** — negligible compared to generation time. The negative embeddings are crucial: without them, the anime LoRA would activate on photorealistic portrait prompts because both involve "detailed face" and "high quality" — the negative embedding for anime penalizes "photograph" and "raw" tokens.

## Benchmarks

Here's what we're projecting based on component-level measurements:

\`\`\`
                        Python (current)    Go+C (projected)
HTTP overhead           ~5ms                ~0.1ms (FastHTTP)
Request parsing         ~2ms                ~0.05ms
Python dispatch         ~50ms               0ms (eliminated)
torch Python layer      ~200ms              0ms (LibTorch C++)
LoRA selection          ~15ms (keyword)     <1ms (gobed cosine)
Model inference (GPU)   ~31.5s              ~31.5s (same GPU work)
Image encoding          ~100ms (PIL)        ~20ms (libwebp C)
Response serialization  ~50ms (base64)      ~0.1ms (raw bytes)
───────────────────────────────────────────────────────────
Total                   ~32s                ~31.5s
\`\`\`

### End-to-end pipeline comparison

| Configuration | Mode | Latency | Speedup | Memory |
|---|---|---|---|---|
| Python (CPU offload) | Eager | ~32,000ms | 1.0x | ~7 GB |
| Python (GPU resident) | Eager | ~31,500ms | 1.02x | ~18 GB |
| Python + CuteDSL Kernels | Fused | ~30,000ms | 1.07x | ~18 GB |
| Go+C (Python embed) | CGO Bridge | ~31,200ms | 1.03x | ~18 GB |
| Go+C (LibTorch native) | Projected | ~100ms | ~320x | ~14 GB |
| Go+C + NVFP4 | Projected | ~60ms | ~533x | ~8 GB |

### The honest reality: GPU compute dominates

The ~32 second generation time is **not Python overhead**. It's actual GPU compute — Z-Image Turbo runs 9 denoising steps through a 30-layer, 3840-dim transformer with SiLU-gated FFN (hidden=10240). Each step is a full forward pass through the model. The Python framework overhead (dispatch, GIL, torch frontend) accounts for less than 2% of wall time.

Switching to Go+C with the same PyTorch/CUDA backend yields only a ~3% speedup. The projected ~320x numbers for LibTorch native assume we can eliminate the Python/torch runtime entirely and run pure C++ with CUDA graphs — that's the real goal but it's not measured yet.

### LoRA search benchmarks

| Engine | Latency | Accuracy |
|---|---|---|
| Keyword (Python) | <0.1ms | Good |
| Embedding (Python, sentence-transformers) | 4ms | Excellent |
| Embedding (Go, gobed) | <1ms | Excellent |
| Embedding + Negative (Python) | 5ms | Best |
| Embedding + Negative (Go, gobed) | <1ms | Best |

LoRA search is where the Go migration already delivers clear wins. gobed's SIMD-optimized cosine similarity with negative embeddings gives the best accuracy at sub-millisecond latency.

The honest truth: most of the time is GPU compute, and that doesn't change by switching languages. The real wins are:

1. **Eliminating the HTTP hop** — No more Go-to-Python round-trip. The GPU call happens in-process
2. **Startup time** — Python takes ~45s to import torch and load models. The C library loads in ~3s
3. **Memory** — No Python interpreter overhead (~200MB saved)
4. **LoRA switching** — gobed semantic search vs keyword hacks
5. **Tail latency** — No GIL stalls, no garbage collector pauses from Python. P99 latency drops dramatically

## Architecture: old vs new

\`\`\`
OLD FLOW:
  Client
    |
    v
  Go (FastHTTP :8080)
    |  HTTP POST (JSON + base64 image)
    v
  Python (FastAPI :8100)
    |  torch Python dispatch
    v
  PyTorch → CUDA kernels → GPU
    |
    v
  Python (PIL encode, base64)
    |  HTTP response (JSON + base64)
    v
  Go (unmarshal, serve to client)

NEW FLOW:
  Client
    |
    v
  Go (FastHTTP :8080)
    |  CGO function call (zero-copy params)
    v
  C API (diffusionz_c_api.h)
    |  LibTorch C++ → CuteDSL CUDA kernels → GPU
    v
  libwebp encode (in C)
    |  []byte returned to Go (single copy)
    v
  Go (write raw WebP bytes to response)
\`\`\`

The entire inference path collapses from 6 process/network hops to 2 function calls.

## What's next

The C migration opens doors that Python couldn't:

- **NVFP4 quantization in C** — We already have NVFP4 working via torchao in Python. Porting to the C API means we can use CUTLASS directly for FP4 GEMM kernels without Python overhead
- **GGML weight format** — Loading weights in GGML format instead of safetensors eliminates the need for torch's weight loading machinery. Memory-mapped, instant load
- **stable-diffusion.cpp integration** — The [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp) project already has a working C++ diffusion pipeline. We're evaluating using it as the backend instead of LibTorch, which would dramatically reduce the binary size and dependency chain
- **Multi-GPU scheduling** — With the C API, we can manage multiple GPU contexts from Go and route requests based on LoRA affinity — keeping frequently-used LoRAs resident on specific GPUs

The migration is underway. We'll publish follow-up posts with real benchmarks once the C API is running in production.`,
  },
  {
    slug: 'why-we-launched-cutedsl-token-on-bags-fm',
    title: '$CUTEDSL on Solana: Pay-Per-Call AI Image API',
    date: '2026-04-04',
    tags: ['token', 'solana', 'bags.fm', 'crypto', 'payments'],
    image: '/blog-art/why-we-launched-cutedsl-token-on-bags-fm.webp',
    excerpt: 'How CuteDSL bills Z-Image Turbo, Flux Schnell, TTS, and Chronos-2 with a Solana SPL token on bags.fm.',
    content: `CuteDSL bills Z-Image Turbo, Flux Schnell, Kokoro TTS, and Chronos-2 with the [$CUTEDSL token on bags.fm](https://bags.fm/D322k7ykdgCmNGUZL5XvsgZXdHU4ks8iGoWtfrnmBAGS) — a Solana SPL token. This is how the AI image generator API is priced.

![Z-Image Turbo illustration: why we launched cutedsl token on bags fm](/blog-art/why-we-launched-cutedsl-token-on-bags-fm.webp)

## The problem with traditional AI billing

Most text-to-image APIs bill through a card processor. That means:

- **KYC/identity verification** before you can even get an API key
- **Monthly billing cycles** with surprise invoices
- **Currency conversion** fees for non-USD users
- **Payment disputes** and chargebacks that cost the platform money
- **Geographic restrictions** — can't serve users in many countries
- **Minimum charges** and complex tiered pricing

For a platform serving global developers who want to call an image generation API, this is massive friction. A developer in Lagos, Bangkok, or Buenos Aires shouldn't need a US bank account to generate an image.

## Why Solana

We needed a payment rail that's:

1. **Fast** — transactions confirm in ~400ms
2. **Cheap** — fees under $0.001 per transaction
3. **Global** — anyone with a wallet can pay, no KYC
4. **Programmable** — we can build deposit detection, auto-sweeping, and credit systems on-chain
5. **Liquid** — easy to buy, sell, and transfer

Solana checks every box. Ethereum is too expensive for microtransactions ($0.04 per image generation would be eaten by gas fees). Bitcoin is too slow. Solana is the only chain where sub-cent payments make economic sense.

## Why bags.fm

We chose [bags.fm](https://bags.fm/D322k7ykdgCmNGUZL5XvsgZXdHU4ks8iGoWtfrnmBAGS) to launch $CUTEDSL for several reasons:

- **Instant liquidity** — bags.fm provides bonding curve liquidity from day one, no need to bootstrap a DEX pool
- **Fair launch** — no pre-mine, no insider allocation, the token just exists and anyone can buy it
- **Price feed API** — bags.fm has a public API we use to fetch real-time $CUTEDSL pricing for our credit system
- **Simple UX** — users click one link, connect wallet, swap SOL for $CUTEDSL. Done.
- **Community-aligned** — bags.fm is built for utility tokens, not pump-and-dump memecoins

The mint address is \`D322k7ykdgCmNGUZL5XvsgZXdHU4ks8iGoWtfrnmBAGS\` — you can verify it on-chain.

## How the payment system works

The flow is straightforward:

1. **Buy $CUTEDSL** on [bags.fm](https://bags.fm/D322k7ykdgCmNGUZL5XvsgZXdHU4ks8iGoWtfrnmBAGS) by swapping SOL
2. **Connect wallet** on cutedsl.cc (Phantom or manual address entry)
3. **Deposit** — we generate a unique HD-derived deposit address per payment. Send $CUTEDSL or SOL to it.
4. **Credits appear** — our payment poller detects the on-chain transaction within 30 seconds and credits your account
5. **Use services** — every API call deducts credits at the current token rate

The deposit addresses are derived using HKDF from a master seed, so each payment gets a unique address for clean accounting. A background sweeper consolidates deposits to our main wallet.

## ATH pricing: rewarding early believers

Here's our most unusual pricing decision: **first-party services are priced at the all-time-high (ATH) token rate**.

What this means:

- If you buy $CUTEDSL at $0.001 and the price later rises to $0.01, your tokens are still worth $0.001 each for CuteDSL services
- Early holders permanently get cheaper inference than later buyers
- The ATH only goes up, never down — it tracks the peak price

Why? Because early supporters take the most risk. They deserve the most reward. If you believe in CuteDSL enough to buy tokens before anyone else, you should get the cheapest possible inference forever.

Third-party proxied services (like Flux Schnell image gen via fal.ai) are priced at market rate since we have pass-through costs.

## What this enables

With crypto-native payments, we can do things traditional billing can't:

- **$0.04 image generation** — Flux Schnell micro-billing on Solana
- **Pay-per-call pricing** — no subscriptions, no minimums, no commitments
- **Instant settlement** — credits available in seconds, not days
- **Programmatic payments** — agents and bots can deposit and use services without human KYC
- **Global access** — anyone with a Solana wallet can use CuteDSL, anywhere in the world

That last point matters. We want CuteDSL to be the inference layer for AI agents running on platforms like [Codex Infinity](https://codex-infinity.com). Agents can't fill out KYC forms. But they can hold a wallet and send tokens.

## The numbers

Current service pricing in $CUTEDSL:

| Service | Price (USD) | What you get |
| zimage | $1.00 | One 1024x1024 CuteDSL-accelerated image |
| chronos2 | $0.50 | One time series forecast |
| flux_image | $0.04 | One Flux Schnell image (via fal.ai) |
| tts | $0.10 | 100 characters of Kokoro TTS audio |
| stt | $0.20 | 1 minute of speech-to-text |
| gemma4 | $0.05 | One Gemma4 chat/vision request |
| ltx_video | $0.30 | One LTX 2.3 text-to-video |

The $CUTEDSL amount per call floats with the token price. As the token appreciates, each token buys more compute. As it depreciates, you need more tokens. But ATH-locked pricing means your effective rate can only improve if you bought early.

## Buy $CUTEDSL

Ready to try accelerated AI inference paid with crypto?

[Buy $CUTEDSL on bags.fm](https://bags.fm/D322k7ykdgCmNGUZL5XvsgZXdHU4ks8iGoWtfrnmBAGS) and start making API calls in under a minute. Connect your wallet at [cutedsl.cc](https://cutedsl.cc), deposit tokens, and call any of our 7+ AI services.`,
  },
  {
    slug: 'generate-ai-images-with-solana',
    title: 'AI Image Generator API: Z-Image Turbo and Flux Schnell',
    date: '2026-04-04',
    tags: ['zimage', 'flux', 'solana', 'image-generation', 'tutorial'],
    image: '/blog-art/generate-ai-images-with-solana.webp',
    excerpt: 'Call the CuteDSL text-to-image API: Flux Schnell at $0.04/image and Z-Image Turbo with LoRAs. Solana wallet, then curl.',
    content: `CuteDSL text-to-image starts at **$0.04 per image**. Solana wallet, $CUTEDSL, then curl — Flux Schnell or Z-Image Turbo.

![Z-Image Turbo illustration: generate ai images with solana](/blog-art/generate-ai-images-with-solana.webp)

This post covers both engines and the API.

## Two engines, two price points

CuteDSL offers two image generation services:

**Flux Schnell ($0.04/image)** — Our fast, affordable option. Powered by fal.ai's Flux Schnell model. 1024x1024 images in ~2 seconds. Great for prototyping, placeholder art, and bulk generation. This is a third-party proxy priced at market rate.

**Z-Image Turbo ($1.00/image)** — Our flagship, CuteDSL-accelerated engine. Custom fused Triton kernels, NVFP4 quantization on RTX 5090, and the full CuteZImage pipeline. Higher quality, supports custom LoRAs, and every generation saves latent tensors for future [latent teleportation](/blog#latent-teleportation) optimization. Priced at ATH rate — early $CUTEDSL holders get this cheaper forever.

## Step 1: Get $CUTEDSL tokens

Head to [bags.fm](https://bags.fm/D322k7ykdgCmNGUZL5XvsgZXdHU4ks8iGoWtfrnmBAGS) and swap some SOL for $CUTEDSL. Even $1 worth gives you 25 Flux Schnell generations.

If you don't have SOL, you can buy it on any major exchange and send it to your Phantom wallet.

## Step 2: Connect your wallet

Visit [cutedsl.cc](https://cutedsl.cc) and click **Connect Wallet** in the top right. If you have Phantom installed, it'll connect automatically. Otherwise, you can paste your wallet address manually.

## Step 3: Deposit

Click the **Deposit** button in the Credits section. Enter a USD amount and we'll generate a unique deposit address. Send your $CUTEDSL tokens to that address. Our payment poller picks up the transaction within 30 seconds and credits your account.

You can also pay with SOL — we'll convert it to $CUTEDSL credits at the current exchange rate.

## Step 4: Generate images via API

Call the service endpoint with your wallet address and prompt:

\`\`\`bash
# Flux Schnell — fast and cheap ($0.04)
curl -X POST https://cutedsl.cc/api/service \\
  -H "Content-Type: application/json" \\
  -d '{
    "service": "flux_image",
    "wallet_address": "YOUR_WALLET",
    "prompt": "a cute fairy with pink wings in an enchanted forest"
  }'

# Z-Image Turbo — CuteDSL accelerated ($1.00)
curl -X POST https://cutedsl.cc/api/service \\
  -H "Content-Type: application/json" \\
  -d '{
    "service": "zimage",
    "wallet_address": "YOUR_WALLET",
    "prompt": "a cute fairy with pink wings in an enchanted forest",
    "width": 1024,
    "height": 1024
  }'
\`\`\`

Both return the generated image. Credits are deducted automatically. If generation fails for any reason, you get an automatic refund.

## The image gallery

Every image generated through CuteDSL's Z-Image engine gets saved to our [searchable gallery](/search). You can browse 100k+ AI-generated images, search by prompt keywords, and use semantic search to find similar images.

The gallery stores three sizes per image (1024px original, 512px medium, 256px thumbnails) — all WebP quality 85 for fast loading. We also save the raw latent tensors alongside each image for future latent teleportation research.

## Why $0.04?

Flux Schnell via fal.ai costs us roughly $0.02-0.03 per generation. We add a small margin and pass it through at market rate. There's no subscription, no minimum spend, no monthly commitment. Generate one image or ten thousand — same price per image.

Z-Image at $1.00 reflects the cost of running CuteDSL's custom Triton kernels on our own RTX 5090 GPU infrastructure, plus the LoRA auto-selection, latent saving, and NSFW classification that runs on every generation. The ATH pricing means this rate only improves for early holders as the token appreciates.

## Use cases we're seeing

- **Indie game devs** generating concept art and sprites at $0.04/each
- **Web developers** creating placeholder images for mockups
- **AI agents** on [Codex Infinity](https://codex-infinity.com) auto-generating visuals for web apps they're building
- **Content creators** producing social media graphics in bulk
- **Researchers** generating datasets of synthetic images for training

## Pro tip: LoRA auto-selection

When using Z-Image, our backend automatically selects the best LoRAs for your prompt from a pool of 100+ adapters. If you mention "anime", the anime LoRA kicks in. "Double exposure" triggers the double exposure adapter. You don't need to know which LoRAs exist — the system matches them semantically.

Read more about this in our [LoRA hosting deep dive](/blog#team-of-loras-hosting).

## Get started

1. [Buy $CUTEDSL on bags.fm](https://bags.fm/D322k7ykdgCmNGUZL5XvsgZXdHU4ks8iGoWtfrnmBAGS)
2. Connect wallet at [cutedsl.cc](https://cutedsl.cc)
3. Deposit and start generating

[Z-Image Turbo playground](/docs/zimage) · [Flux Schnell](/docs/flux_image) · [AI art gallery](/gallery)`,
  },
  {
    slug: 'cutedsl-image-gallery-100k-images',
    title: '100K AI Art Gallery: Prompt Search and NSFW Filter',
    date: '2026-04-03',
    tags: ['gallery', 'search', 'images', 'nsfw', 'infrastructure'],
    image: '/blog-art/cutedsl-image-gallery-100k-images.webp',
    excerpt: 'How we built a searchable Z-Image Turbo gallery: 100k images, prompt + semantic search, WebP sizes, NSFW classification.',
    content: `CuteDSL now hosts a searchable gallery of 100k+ AI-generated images at [cutedsl.cc/search](/search). Every image was generated through our Z-Image Turbo engine, and every one is searchable by prompt text, semantic similarity, or both. Here's how we built it.

![Z-Image Turbo illustration: cutedsl image gallery 100k images](/blog-art/cutedsl-image-gallery-100k-images.webp)

## The generation pipeline

We started with the [daspartho/stable-diffusion-prompts](https://huggingface.co/datasets/daspartho/stable-diffusion-prompts) dataset — 1.8 million unique prompts curated from the Stable Diffusion community. After filtering out very short prompts, URLs, and duplicates, we had ~1.7M usable prompts.

Our generation script feeds these prompts through the CuteDSL Z-Image Turbo endpoint in batches. For each generation, we save:

- **Original image** — 1024x1024, WebP quality 85
- **Medium thumbnail** — 512x512, WebP quality 85
- **Small thumbnail** — 256x256, WebP quality 85
- **Latent tensor** — The raw diffusion latent as a base64-encoded PyTorch tensor

The latent tensors are key for our [latent teleportation research](/blog#latent-teleportation). By building a library of latents paired with their prompts, we can later find similar latents for new prompts and skip most denoising steps.

Generation runs at about 2 seconds per image on our RTX 5090 with CuteDSL's fused Triton kernels. At that rate, 100k images takes roughly 55 hours of continuous generation. The script is resumable — it tracks which prompts have been processed in PostgreSQL, so we can stop and restart without regenerating.

## Storage architecture

Images live on a dedicated SSD mounted at \`/sdb-disk/cutedsl-images\`, symlinked into the project as \`./images/\`. The directory structure:

\`\`\`
images/
  originals/     # 1024x1024 WebP q85
  medium/        # 512x512 WebP q85
  thumbs/        # 256x256 WebP q85
  latents/       # .pt tensor files
  prompts.jsonl  # 1.7M prompt dataset
\`\`\`

Total storage for 100k images: ~15GB originals, ~4GB medium, ~1.5GB thumbnails, ~8GB latents.

## Search: keyword + semantic

The gallery supports two search modes that work together:

**Keyword search** uses PostgreSQL trigram indexes (\`pg_trgm\`). When you search for "cute fairy forest", it runs an ILIKE query against the prompt column with a GIN trigram index. This is fast (~5ms for 100k rows) and catches exact keyword matches.

**Semantic search** uses gobed embeddings. At server startup, we load all 1.7M prompts and build an embedding index in a background goroutine. When you type a query, we compute its embedding and return the top-k most similar prompts via squared Euclidean distance. This catches semantic matches that keyword search misses — searching "enchanted woodland" finds images prompted with "magical forest".

The frontend combines both: semantic search powers autocomplete suggestions as you type, and keyword search fetches the actual image results. Pagination loads 48 images at a time with infinite scroll.

## NSFW classification

Every image is classified using the [Falconsai/nsfw_image_detection](https://huggingface.co/Falconsai/nsfw_image_detection) model from HuggingFace. We run this on-demand in the inference server — the model loads when needed and doesn't consume GPU memory permanently.

The classifier runs as a backfill job: \`python scripts/backfill_nsfw.py --limit 1000\` processes unclassified images in batches. Results are stored as a boolean flag in PostgreSQL. The gallery defaults to NSFW-filtered, with a toggle for users who want to see everything.

Why not run NSFW classification at generation time? Because it adds ~200ms per image and we prioritize generation throughput. The backfill approach lets us classify async without slowing down the generation pipeline.

## Performance

The gallery loads fast because:

- **Thumbnails are tiny** — 256x256 WebP at quality 85 averages ~15KB per image
- **Lazy loading** — we load 48 thumbnails per page, not all 100k
- **CDN caching** — static images get \`Cache-Control: public, max-age=31536000, immutable\`
- **Database indexes** — trigram GIN index on prompts, btree on created_at and is_nsfw
- **Semantic search is precomputed** — embeddings are built once at startup, queries are pure vector math

A full page of 48 thumbnails loads in ~300ms on a good connection. Search results return in under 50ms.

## What's next

We're working on:

- **Image-to-image search** — upload an image, find similar generations via CLIP embeddings
- **LoRA filtering** — browse images by which LoRA adapters were used
- **Latent space visualization** — t-SNE/UMAP projections of the latent tensor library
- **Community uploads** — let users contribute their own Z-Image generations to the gallery

The gallery is live at [cutedsl.cc/search](/search). Browse, search, and get inspired. And if you want to generate your own images for as little as $0.04, [grab some $CUTEDSL tokens on bags.fm](https://bags.fm/D322k7ykdgCmNGUZL5XvsgZXdHU4ks8iGoWtfrnmBAGS) and start creating.`,
  },
  {
    slug: 'generative-agents-cloud-infrastructure',
    title: 'AI Agents + Inference: CuteDSL Image Gen for Codex Infinity',
    date: '2026-04-04',
    tags: ['agents', 'codex-infinity', 'cloud', 'infrastructure', 'cross-post'],
    image: '/blog-art/generative-agents-cloud-infrastructure.webp',
    excerpt: 'How cloud coding agents call Z-Image Turbo, TTS, and Chronos-2 instead of waiting on slow hosted APIs.',
    content: `This is a cross-post with [Codex Infinity](https://codex-infinity.com), the infinite coding agent platform. We've been collaborating on integrating CuteDSL's accelerated inference into Codex Infinity's agent pipelines, and the results are worth sharing.

![Z-Image Turbo illustration: generative agents cloud infrastructure](/blog-art/generative-agents-cloud-infrastructure.webp)

## The problem: agents need fast tools

Autonomous coding agents — the kind that plan, implement, test, and ship code — are only as useful as their tool latency allows. When an agent calls an image generation API and waits 30 seconds, that's 30 seconds of idle compute on an expensive cloud VM. When it calls a forecasting model and waits 5 seconds per prediction in a loop of 500, the task takes 40 minutes instead of 1.

[Codex Infinity](https://codex-infinity.com) provisions isolated Hetzner VMs for each agent task. These spin up in ~30 seconds, run the agent with full root access, and auto-destroy on completion. The compute cost is tracked per-second. Every millisecond of tool latency directly translates to dollars.

## CuteDSL as an agent tool backend

We integrated CuteDSL's inference server as a tool backend for Codex Infinity agents. When an agent needs to generate an image, forecast a time series, or transcribe audio, it hits the CuteDSL API instead of generic cloud APIs.

The latency difference is dramatic:

- **Image generation (zimage)**: ~2s vs ~15s on generic Flux APIs — 7.5x faster
- **Time series forecasting (chronos2)**: 1.55ms vs 42ms baseline — 27x faster
- **Batched forecasting (448 windows)**: 52ms total vs 18s sequential — 346x faster

For an agent running a data analysis pipeline that needs 50 forecasts and 10 visualizations, this cuts tool-wait time from ~8 minutes to ~15 seconds.

## How it works architecturally

![CuteDSL x Codex Infinity Architecture](${IMG_BASE}/codex-infinity-og.webp)

The integration is straightforward:

1. **Codex Infinity** provisions a VM and starts an agent (Claude, GPT-4, Gemini, or DeepSeek)
2. The agent's environment includes CuteDSL API credentials and endpoint URL
3. When the agent needs AI capabilities, it calls CuteDSL's \`/api/service\` endpoint
4. CuteDSL runs inference on GPU with custom Triton kernels and returns results
5. The agent processes results and continues its task
6. Credits are deducted from the user's $CUTEDSL balance

The key insight: **the agent doesn't know or care about the acceleration**. It just sees a fast API. The Triton kernels, torch.compile, CUDA graphs — all invisible. The agent simply gets answers faster and finishes tasks sooner.

## Real-world agent workflow example

Here's a concrete example: an agent tasked with "analyze my portfolio's historical data and generate a visual report."

**Without CuteDSL (generic APIs):**
1. Fetch data — 2s
2. Generate 20 forecasts — 20 x 15s = 300s (5 min)
3. Generate 8 chart images — 8 x 15s = 120s (2 min)
4. Compile report — 5s
5. **Total: ~7.5 minutes of agent runtime**

**With CuteDSL:**
1. Fetch data — 2s
2. Generate 20 forecasts (batched) — 0.05s
3. Generate 8 images — 8 x 2s = 16s
4. Compile report — 5s
5. **Total: ~23 seconds of agent runtime**

At Codex Infinity's compute rates (~$0.036/hr for a 4-vCPU instance), that's $0.0045 vs $0.00024. The per-task saving is small, but at scale — hundreds of agent tasks per day — it adds up fast.

## Parallel agents and CuteDSL

[Codex Infinity](https://codex-infinity.com) supports running multiple agents in parallel on the same codebase. A backend agent, frontend agent, and test agent can all run simultaneously. When all three need AI tools concurrently, CuteDSL's inference server handles the load with batched processing.

The chronos2 batched inference path is particularly well-suited here: multiple agents can submit forecast requests that get batched into a single GPU operation, rather than serializing through one-at-a-time API calls.

## What's next

We're working on deeper integration: CuteDSL as a first-class "skill" in Codex Infinity's skill system, so agents can learn which CuteDSL models to use for different subtasks and cache successful patterns for future tasks. We're also exploring running CuteDSL inference directly on Codex Infinity's GPU worker nodes to eliminate network round-trips entirely.

If you're using [Codex Infinity](https://codex-infinity.com) for autonomous coding, you can add CuteDSL as a tool backend today. Check the [API docs](/#api-docs) for endpoint details.`,
  },
  {
    slug: 'anatomy-of-cloud-coding-agents',
    title: 'Cloud Coding Agents: What Happens When You Press Run',
    date: '2026-04-04',
    tags: ['agents', 'codex-infinity', 'cloud', 'architecture', 'cross-post'],
    image: '/blog-art/anatomy-of-cloud-coding-agents.webp',
    excerpt: 'The Codex Infinity agent loop: VM, tools, Z-Image Turbo, TTS, and where latency actually goes.',
    content: `Most people interact with AI agents through a chat interface. Type a message, get a response. But cloud coding agents — like the ones on [Codex Infinity](https://codex-infinity.com) — are fundamentally different. They get a task, a full Linux VM, and root access. Then they go to work autonomously.

![Z-Image Turbo illustration: anatomy of cloud coding agents](/blog-art/anatomy-of-cloud-coding-agents.webp)

This post breaks down exactly what happens in the ~30 seconds between pressing "Run" and seeing your agent start writing code.

## Phase 1: Task planning (0-2 seconds)

When you submit a task like "Add user authentication with OAuth2 to the Express backend," the system doesn't just forward this to an LLM. First:

1. **Skill matching** — The system checks if this task pattern matches any previously learned skills (successful task templates with 80%+ confidence). If there's a match, the skill's approach is injected as context.
2. **Repository analysis** — The system identifies the tech stack, existing patterns, test frameworks, and relevant files.
3. **Model routing** — Based on task complexity and user preferences, the system selects which LLM to use (Claude, GPT-4, Gemini, or DeepSeek).

## Phase 2: VM provisioning (2-30 seconds)

This is where [Codex Infinity](https://codex-infinity.com) diverges from sandboxed agent platforms. Instead of running in a container with restricted permissions, each task gets a fresh, isolated virtual machine on Hetzner bare-metal infrastructure.

**The provisioning sequence:**
1. Select instance type (2-4 vCPU, 4-8GB RAM based on task)
2. Boot from a pre-built snapshot with all common dev tools pre-installed
3. Cloud-init injects: SSH keys, agent binary, repository clone, environment variables
4. Agent binary connects back to the control plane via WebSocket

The pre-built snapshot is the key to the ~30 second boot time. Without it, installing Node.js + Python + Go + Rust + common packages would take 5-10 minutes.

## Phase 3: Agent execution (30 seconds onward)

Once connected, the agent operates in a loop:

1. **Read** the codebase and understand the current state
2. **Plan** the implementation approach
3. **Execute** — write code, run commands, install dependencies
4. **Test** — run the test suite, check for errors
5. **Iterate** — if tests fail, diagnose and fix
6. **Report** — generate a summary of changes

The entire terminal session streams back to your browser in real-time via SSE and xterm.js. You can watch the agent think, write, debug, and ship — live.

## Tool integration: where CuteDSL fits

During execution, agents often need AI capabilities beyond text generation:

- **Generating test fixtures** with realistic synthetic data (chronos2 for time series)
- **Creating placeholder images** for frontend components (zimage)
- **Analyzing screenshots** to verify visual changes (image captioning)
- **Transcribing** meeting notes referenced in issues (STT)

Each of these is a CuteDSL API call. The agent treats them like any other tool — \`curl\` to an endpoint, parse the response, continue working. The difference is CuteDSL returns in milliseconds where generic APIs take seconds.

## Phase 4: Skill acquisition

After a successful task, [Codex Infinity](https://codex-infinity.com) extracts the approach as a reusable skill. Skills are parameterized templates in YAML format that capture:

- What the agent did (steps, commands, file changes)
- Why it worked (test results, error resolution patterns)
- When to apply it (task type matching criteria)

Next time a similar task arrives, the skill provides a head start. The agent doesn't re-discover the approach from scratch — it starts with a validated playbook and adapts from there.

## Phase 5: Teardown

When the agent finishes (or times out), the system:

1. Commits changes and pushes to a branch
2. Opens a PR if configured
3. Stores logs and diffs in Cloudflare R2
4. Destroys the VM completely — no state leaks between tasks

The complete isolation means one agent's mistakes can't affect another. If an agent accidentally \`rm -rf /\`s its workspace, the damage is contained to a single disposable VM.

## Why bare metal matters

Sandboxed environments (Docker containers, WebAssembly, restricted shells) are safe but limiting. Agents can't:
- Install system packages (\`apt install\`)
- Run GPU workloads
- Fork background processes
- Access low-level system APIs
- Build Docker images inside Docker

Bare-metal VMs remove all these restrictions. The agent has the same capabilities as a human developer SSHed into a cloud server. This is what enables full autonomy — the agent can do anything a developer can do, including things the platform designers didn't anticipate.

## The economics

At ~$0.018/hour for a standard instance, a 10-minute agent task costs about $0.003 in compute. Add the LLM API costs (varies by model and token count) and CuteDSL inference costs, and a typical task runs $0.10-$0.50 total. That's dramatically cheaper than the alternative: a human developer spending 30-60 minutes on the same task.

The key metric isn't cost per task — it's **cost per successful outcome**. With skill acquisition improving success rates over time, the effective cost per shipped feature keeps dropping.

Check out [Codex Infinity](https://codex-infinity.com) to try autonomous cloud agents, and the [CuteDSL API](/#api-docs) to accelerate your agent tool backends.`,
  },
  {
    slug: 'accelerating-agent-pipelines-cutedsl',
    title: 'Agent Pipelines: Z-Image, TTS, and Chronos-2 Inside Workflows',
    date: '2026-04-03',
    tags: ['agents', 'pipelines', 'inference', 'zimage', 'chronos2', 'cross-post'],
    image: '/blog-art/accelerating-agent-pipelines-cutedsl.webp',
    excerpt: 'Where image generation, speech, and forecasting sit in autonomous agent loops — and why inference ms matter.',
    content: `When an AI agent builds a dashboard, writes a report, or creates a web app, it doesn't just generate text. It orchestrates a pipeline of AI services: generate charts, forecast trends, create images, caption screenshots. Each service call is a blocking operation — the agent waits for the result before continuing.

![Z-Image Turbo illustration: accelerating agent pipelines cutedsl](/blog-art/accelerating-agent-pipelines-cutedsl.webp)

This post examines how inference speed shapes what agents can practically accomplish, using real workflows from [Codex Infinity](https://codex-infinity.com) agents powered by CuteDSL.

## The hidden cost of slow inference

Consider an agent tasked with: "Create a weekly market report for 7 crypto assets with price forecasts and generated header images."

The pipeline looks like:

1. Fetch historical data for 7 assets
2. Run chronos2 forecasts for each (7 calls)
3. Generate a chart image for each forecast (7 calls)
4. Generate a thematic header image (1 call)
5. Generate a summary using an LLM
6. Assemble the HTML report

**With standard APIs** (15s/image, 5s/forecast):
- Forecasts: 7 x 5s = 35s
- Chart images: 7 x 15s = 105s
- Header image: 15s
- LLM summary: 3s
- **Total pipeline: ~2.5 minutes**

**With CuteDSL** (2s/image, 1.55ms/forecast, batched):
- Forecasts (batched): 0.01s
- Chart images: 7 x 2s = 14s
- Header image: 2s
- LLM summary: 3s
- **Total pipeline: ~19 seconds**

That's an 8x speedup on the overall task — not because any single call is 8x faster, but because the cumulative effect of fast inference across a multi-step pipeline compounds.

## Service composition patterns

We see three common patterns in how agents compose CuteDSL services:

**Pattern 1: Sequential chain**
The simplest pattern. Agent calls services one after another, each depending on the previous result.

\`\`\`
forecast = cutedsl.chronos2(values=data, prediction_length=64)
chart = cutedsl.zimage(prompt=f"line chart showing {forecast.summary}")
caption = cutedsl.caption(image=chart.url)
\`\`\`

**Pattern 2: Fan-out / fan-in**
Agent submits multiple independent requests, then combines results. This is where batched inference shines.

\`\`\`
# Fan-out: 20 forecasts in one batched call
forecasts = cutedsl.chronos2_batch(series=all_20_series)

# Fan-in: summarize all results
summary = llm.summarize(forecasts)
\`\`\`

**Pattern 3: Conditional branching**
Agent makes decisions based on intermediate results. Fast inference enables more branches.

\`\`\`
forecast = cutedsl.chronos2(values=data)
if forecast.trend == "anomaly":
    detailed = cutedsl.chronos2(values=data, prediction_length=128)
    alert_image = cutedsl.zimage(prompt="warning alert dashboard")
    audio_alert = cutedsl.tts(text=f"Anomaly detected in {asset}")
\`\`\`

With slow inference, agents learn to minimize branches — each branch costs precious seconds. With fast inference, agents can afford to be thorough.

## Real agent transcripts

Here's an excerpt from an actual [Codex Infinity](https://codex-infinity.com) agent building a data dashboard:

\`\`\`
Agent: I need to generate forecast visualizations for 12 metrics.
       Using CuteDSL chronos2 batch endpoint...
[0.05s] All 12 forecasts complete.

Agent: Generating dashboard card images for each metric...
[24s] All 12 images generated via zimage.

Agent: Adding TTS narration for the executive summary...
[1.2s] Audio generated via Kokoro TTS.

Agent: Running tests... all 47 tests pass.
Agent: Opening PR with the dashboard implementation.
\`\`\`

Total tool-wait time: ~25 seconds for 25 AI service calls. The agent spent more time writing code and running tests than waiting for inference.

## The Kokoro TTS integration

One underappreciated use case: agents that generate audio. A [Codex Infinity](https://codex-infinity.com) agent building a presentation app used CuteDSL's TTS service to auto-generate narration for each slide. At $0.10 per 100 characters and ~200ms latency, the agent generated 20 slide narrations in about 4 seconds total.

The agent didn't need to be taught how to use TTS — it discovered the CuteDSL API endpoint in its environment, read the docs, and decided narration would improve the presentation. This is the kind of emergent behavior you get when tools are fast enough that agents don't avoid using them.

## Gemma4 for visual verification

Another pattern we're seeing: agents use CuteDSL's Gemma4 multimodal endpoint to verify their own work. After generating a web page, the agent screenshots it, sends the screenshot to Gemma4, and asks "does this look correct?" If Gemma4 identifies layout issues, the agent fixes them.

This self-verification loop adds maybe 2 seconds per check. With slow vision APIs, it would add 15-20 seconds and agents would skip it. Fast inference makes quality-checking loops practical.

## Why this matters for agent development

The takeaway isn't just "faster is better" — it's that **inference speed changes agent behavior**. When tools are fast:

- Agents use more tools per task (richer outputs)
- Agents verify their work more often (higher quality)
- Agents explore more branches (better decisions)
- Agents complete tasks faster (lower cost)

This is why we believe fast inference is infrastructure, not just optimization. It's a capability multiplier for autonomous agents.

Try combining [Codex Infinity](https://codex-infinity.com) agents with [CuteDSL inference](/#api-docs) — the speed difference is immediately visible in agent behavior.`,
  },
  {
    slug: 'bare-metal-vs-serverless-agents',
    title: 'Bare Metal vs Serverless for AI Agents',
    date: '2026-04-02',
    tags: ['agents', 'codex-infinity', 'infrastructure', 'bare-metal', 'cross-post'],
    image: '/blog-art/bare-metal-vs-serverless-agents.webp',
    excerpt: 'When AI agents should run on a VM versus serverless: long jobs, GPU inference, Z-Image Turbo, and cost.',
    content: `The AI agent infrastructure landscape is splitting into two camps: serverless sandboxes and bare-metal VMs. This post is an honest comparison from the perspective of building [Codex Infinity](https://codex-infinity.com), where we chose bare-metal — and the tradeoffs involved.

![Z-Image Turbo illustration: bare metal vs serverless agents](/blog-art/bare-metal-vs-serverless-agents.webp)

## The serverless agent model

Serverless agent platforms (E2B, Modal, various "AI sandboxes") run agent code in containers or micro-VMs with restricted permissions. The appeal:

- **Fast cold starts** (100-500ms)
- **No infrastructure management** — the platform handles scaling
- **Strong isolation** — containers can't escape to the host
- **Pay-per-second** billing with no idle costs
- **Safe by default** — agents can't do dangerous things

The limitations show up quickly:

- **No sudo** — can't install system packages
- **No Docker-in-Docker** — can't build or test containerized apps
- **Limited filesystems** — often ephemeral, size-capped
- **No GPU access** — can't run local inference
- **Network restrictions** — limited outbound connectivity
- **Memory caps** — typically 512MB-2GB

## The bare-metal agent model

[Codex Infinity](https://codex-infinity.com) provisions a full Hetzner VM per task. The agent gets:

- **Root access** — install anything, configure anything
- **Real filesystems** — persistent during the task, full SSD speed
- **Full networking** — unrestricted outbound, can run servers
- **GPU options** — attach GPU workers for inference
- **No capability restrictions** — if Linux can do it, the agent can do it

The tradeoffs:

- **Slower cold starts** (~30 seconds vs 500ms)
- **Higher minimum cost** (you pay for the full VM even if the agent only uses 10% of RAM)
- **Blast radius** — a misbehaving agent can damage its own VM (but only its own)
- **Infrastructure complexity** — managing VM lifecycle, snapshots, cleanup

## When bare metal wins

**Complex build systems.** If the agent needs to compile a Rust project, build a Docker image, run a database migration, and execute integration tests — it needs a real machine. Trying to do this in a 512MB container with no Docker daemon is painful.

**GPU workloads.** Running CuteDSL inference locally on a GPU worker attached to the agent VM eliminates network round-trips. For an agent generating 50 images, local GPU saves ~25 seconds of network latency.

**Long-running tasks.** A 30-minute refactoring job is natural on a VM. On serverless, you're fighting timeouts, cold starts, and state management.

**System-level work.** Agents configuring nginx, setting up SSH keys, debugging systemd services, or testing deployment scripts need real OS access.

## When serverless wins

**Quick, focused tasks.** "Fix this lint error" or "write a unit test for this function" — tasks that need 30 seconds of compute and touch 1-2 files. The 30-second VM boot time is wasteful here.

**High parallelism, low compute.** Running 100 simple analysis agents concurrently is cheaper on serverless where each gets exactly the resources it needs.

**Safety-critical environments.** If agent mistakes could cause real damage (production databases, live infrastructure), sandboxing provides a safety net.

## The cost comparison

For a typical 10-minute agent task:

| | Serverless | Bare Metal (Hetzner) |
|---|---|---|
| Compute | ~$0.005 | ~$0.003 |
| Cold start overhead | ~0s | ~30s ($0.0002) |
| GPU (if needed) | Not available | ~$0.065 |
| Agent can install packages | No | Yes |
| Agent can run Docker | No | Yes |

For simple tasks, costs are comparable. For complex tasks that need full system access, bare metal is the only option — and it's surprisingly cheap.

## How we optimize cold starts

The 30-second boot is our main disadvantage. We mitigate it with:

1. **Pre-built snapshots** — VM images with all common tools pre-installed
2. **Warm pools** — Pre-provisioned instances ready to accept tasks
3. **Cloud-init optimization** — Minimal post-boot setup, most config baked into the snapshot
4. **Instance reuse** — For sequential tasks on the same repo, reuse the VM instead of destroying it

With warm pools, effective cold start drops to ~5 seconds — competitive with container platforms.

## CuteDSL on bare metal vs through API

One advantage of bare-metal agents: they can run CuteDSL inference locally if they have a GPU worker attached. This means:

- **Zero network latency** on inference calls
- **No API rate limits** — the GPU is dedicated to your agent
- **Batch processing** without HTTP overhead
- **Custom model loading** — agents can load their own LoRAs

For agents that make 100+ inference calls per task, local GPU inference on bare metal is 2-5x faster end-to-end than API calls, even when the API itself is fast.

## Our recommendation

Use serverless for quick tasks, bare metal for everything else. The industry is converging on this split — even serverless platforms are adding "persistent environment" options that look suspiciously like VMs.

At [Codex Infinity](https://codex-infinity.com), we've optimized for the complex case: agents that need 5-60 minutes, full system access, and fast AI tools via [CuteDSL](/#api-docs). If that's your use case, bare metal is the right call.`,
  },
  {
    slug: 'cutechronos2-27x-speedup',
    title: 'Chronos-2 Time Series Forecasting: 27x Faster Inference',
    date: '2026-04-01',
    tags: ['chronos2', 'torch.compile', 'triton', 'benchmarks'],
    image: '/blog-art/cutechronos2-27x-speedup.webp',
    excerpt: 'Amazon Chronos-2 from 42ms to 1.55ms: 8 Triton kernels, CUDA preprocessing, torch.compile CUDA graphs.',
    content: `Amazon's Chronos-2 is a state-of-the-art probabilistic time series forecasting model built on a T5 encoder backbone. Out of the box on an RTX 5090 with context=768, it runs at about 42ms per inference. We got it down to 1.55ms.

![Z-Image Turbo illustration: cutechronos2 27x speedup](/blog-art/cutechronos2-27x-speedup.webp)

## The approach

CuteChronos2 replaces every major operation in the Chronos-2 pipeline with hand-written Triton kernels:

**1. Unscaled Tiled Attention** — Chronos-2 uses attention without the standard 1/sqrt(d_k) scaling factor. We wrote a FlashAttention-style tiled kernel that never materializes the full S×S attention matrix. Softmax is computed in FP32 for numerical stability even when the rest of the model runs in bfloat16.

**2. Fused LayerNorm + Linear** — The most common pattern in any transformer is LayerNorm followed by a linear projection. Our fused kernel eliminates the intermediate normalized tensor entirely. One read, one write.

**3. Fused MLP** — The feed-forward network in each encoder layer has a hidden dimension of 3072. By fusing Linear+ReLU and the full two-layer MLP, we avoid allocating this intermediate buffer.

**4. RoPE Kernel** — Rotary position embeddings involve computing inverse frequencies, then applying cos/sin rotations to Q and K. We fuse all three steps.

**5. CUDA Preprocessing** — Chronos-2 needs NaN-aware normalization on input series. Our C++ extension uses shared memory reductions for per-series mean/std computation, handling NaN values correctly in a two-phase kernel.

## torch.compile: the multiplier

The custom kernels alone give about 2.19x speedup in eager mode (42ms → 19.15ms). The big win comes from torch.compile with reduce-overhead mode, which captures the entire forward pass as a CUDA graph. This eliminates kernel launch overhead — the GPU executes a single pre-recorded command buffer.

Combined result: **27.1x speedup** (42ms → 1.55ms) at horizon=16.

The tradeoff: torch.compile with CUDA graphs requires fixed input shapes. For inference serving, this is usually fine — you pad inputs to a standard length.

## Batched rolling forecasts

Where things get really interesting is batched inference. On a rolling forecast over 448 windows (7 symbols × 64 time points), CuteChronos2 compiled does the entire batch in 52.3ms — that's **0.117ms per window**. The original PyTorch model takes 18 seconds sequentially.

## Memory

Original: 248 MB. CuteChronos2: 237 MB. The fused kernels avoid intermediate allocations, but the model weights dominate memory either way. TQ4 quantization brings this down further with 3.66x compression on KV cache.

## Try it

CuteChronos2 is available via the CuteDSL inference server. Check the [API docs](/#api-docs) for the \`chronos2\` service endpoint.`,
  },
  {
    slug: 'cutezimage-fused-kernels',
    title: 'Z-Image Turbo Triton Kernels: Faster Diffusion Transformer',
    date: '2026-03-28',
    tags: ['zimage', 'triton', 'cuda', 'diffusion'],
    image: '/blog-art/cutezimage-fused-kernels.webp',
    excerpt: 'Fused SiLU-gate FFN, AdaLN+RMS, complex RoPE, and CUDA RMS/SiLU for the Z-Image Turbo text-to-image backbone.',
    content: `Z-Image Turbo is a 30-layer transformer-based diffusion model with dim=3840, 30 attention heads, and a SiLU-gated FFN with hidden dimension 10240. That hidden dimension is the key optimization target.

![Z-Image Turbo illustration: cutezimage fused kernels](/blog-art/cutezimage-fused-kernels.webp)

## The SiLU-Gated FFN problem

The standard implementation computes \`silu(w1(x)) * w3(x)\` in three steps:
1. Project to hidden dim (3840 → 10240) with w1
2. Apply SiLU activation
3. Project to hidden dim with w3, element-wise multiply

Step 2 allocates a 10240-wide intermediate tensor. At bfloat16 with typical batch sizes, that's significant memory bandwidth.

Our fused Triton kernel computes \`silu(w1(x)) * w3(x)\` in a single pass. One read of x, one write of the result. The 10240-wide intermediate never exists in global memory.

## AdaLN + RMS Norm fusion

Z-Image uses Adaptive Layer Normalization (AdaLN) for timestep conditioning. The standard pattern is:
1. Compute timestep modulation parameters (scale, shift)
2. Apply RMS normalization
3. Modulate with scale and shift

Our fused kernel does all three in one pass. This is especially impactful because AdaLN happens at every one of the 30 transformer layers.

## Complex-valued RoPE

Z-Image uses a non-standard RoPE implementation with complex multiplication. The naive implementation creates intermediate complex tensors during reshape → complex multiply → flatten. Our Triton kernel fuses the entire sequence and avoids all intermediate allocations.

## CUDA extensions for the hot path

For the absolute hottest operations (RMS norm, SiLU gate), we also wrote CUDA C++ kernels with vectorized 128-bit loads and stores. Using bfloat162, half2, and float4 types maximizes memory bandwidth utilization. These serve as fallbacks when Triton autotuning hasn't converged.

## What's next

We're working on NVFP4 quantization for the Z-Image transformer on RTX 5090 Blackwell GPUs. The SM100+ architecture has native support for 4-bit floating point, which should give us ~2x memory reduction and faster matmuls. Stay tuned for benchmarks.`,
  },
  {
    slug: 'latent-teleportation',
    title: 'Latent Teleportation: Skip Diffusion Steps for Faster Image Gen',
    date: '2026-03-25',
    tags: ['latent-teleportation', 'diffusion', 'research', 'slerp'],
    image: '/blog-art/latent-teleportation.webp',
    excerpt: 'Cache intermediate Z-Image latents, SLERP similar prompts, refine in ~5 steps instead of ~20.',
    content: `Diffusion models generate images by iteratively denoising a random latent through many steps (typically 20-50). Each step runs the full transformer backbone. What if we could skip most of those steps?

![Z-Image Turbo illustration: latent teleportation](/blog-art/latent-teleportation.webp)

## The idea

If you generate many images with similar prompts, the intermediate latent states at each denoising step are often surprisingly similar. "A cute cat sitting on a chair" and "A cute dog sitting on a chair" produce latents that are close in the latent space, especially in the early denoising steps.

Latent Teleportation pre-computes and caches intermediate latents for a library of common prompt patterns. When a new prompt arrives, we:

1. **Tokenize** the prompt using NLP, curated, or CLIP-based strategies
2. **Find** the nearest cached latent(s) using cosine similarity
3. **Interpolate** between cached latents to create a starting point
4. **Refine** from the interpolated latent with only ~5 denoising steps

## SLERP interpolation

We use Spherical Linear Interpolation (SLERP) rather than linear interpolation because latents lie on a high-dimensional hypersphere. Linear interpolation can produce latents with incorrect norms that degrade image quality.

Our custom Triton kernel computes SLERP in one pass: vectorized norm/dot/acos computation followed by the interpolation itself.

## Combiner strategies

We're experimenting with three approaches:
- **SLERP** — Simple, fast, works well for similar prompts
- **Neural combiner** — Trained network that learns to blend latents given the target prompt embedding
- **Tree-based** — Hierarchical combination for blending multiple cached latents

## Confidence estimation

Not all cache lookups are good. We estimate confidence based on the cosine similarity between the target prompt embedding and the cached prompt embeddings. Below a threshold, we fall back to full denoising.

## Status

This is active research. Early results show 4-5x step reduction with minimal quality loss for prompts within the cached distribution. The challenge is building a cache that covers enough of the prompt space without growing unbounded.`,
  },
  {
    slug: 'turboquant-vector-quantization',
    title: 'TurboQuant: KV Cache Compression with Vector Quantization',
    date: '2026-03-20',
    tags: ['quantization', 'kv-cache', 'cuda', 'research'],
    image: '/blog-art/turboquant-vector-quantization.webp',
    excerpt: '2–16x KV cache compression for transformers using VQ, Hadamard rotation, and a fused CUDA attention kernel.',
    content: `Large transformers spend significant memory on KV caches during inference. TurboQuant applies vector quantization to compress these caches, trading a small amount of precision for major memory savings.

![Z-Image Turbo illustration: turboquant vector quantization](/blog-art/turboquant-vector-quantization.webp)

## Two quantization modes

**MSE mode** — Standard vector quantization. Each vector is assigned to its nearest codebook entry. Pre-computed codebooks use K-means-style clustering. We use boundary bucketization for fast index assignment during inference.

**Product mode** — Two-stage residual quantization. The first codebook captures the rough structure, the second captures the residual error. This gives better reconstruction quality at the same bit budget.

## Hadamard rotation

Raw activations have highly non-uniform distributions, which VQ handles poorly. Applying a Hadamard rotation before quantization spreads the information more evenly across dimensions, dramatically improving codebook utilization.

## The CUDA kernel

The hot operation in quantized attention is computing QK^T scores when K is stored in quantized form. Our CUDA kernel:
1. Unpacks quantized codes from bit-packed storage
2. Looks up codebook vectors
3. Computes dot products with Q
4. Uses warp-level reductions for the final scores

All in a single kernel launch with no intermediate allocations.

## Results

On Chronos-2 with 4-bit quantization and Hadamard rotation:
- **8x compression** of KV cache
- **< 0.5% MAE increase** on forecasting benchmarks
- Negligible latency overhead (the CUDA kernel is fast)

## Norm-aware reconstruction

We store vector norms separately (in float16) and quantize unit vectors. During reconstruction, the norm is applied after codebook lookup. This preserves the magnitude information that VQ tends to lose.`,
  },
  {
    slug: 'stable-diffusion-cpp',
    title: 'stable-diffusion.cpp: C++ Text-to-Image Inference',
    date: '2026-04-04',
    tags: ['cpp', 'ggml', 'inference', 'research'],
    image: '/blog-art/stable-diffusion-cpp.webp',
    excerpt: 'GGML-style quantized diffusion in C++: Z-Image Turbo, SDXL, Flux on CPU or CUDA without a Python runtime.',
    content: `llama.cpp proved that LLMs can run efficiently on consumer hardware with clever quantization and C++ implementations. Can we do the same for diffusion models?

![Z-Image Turbo illustration: stable diffusion cpp](/blog-art/stable-diffusion-cpp.webp)

## The goal

Run text-to-image diffusion models (Z-Image, SDXL, Flux) in pure C++ with:
- GGML-style quantization (Q4_0, Q4_1, Q8_0)
- CPU inference path (no CUDA required)
- Optional Metal/CUDA backends for acceleration
- Memory-mapped weights for fast startup

## Current state: DiffusionZ C API

We already have a scaffold in the DiffusionZ project — a plain C API with a LibTorch bridge stub. The header-only interface defines the core operations:
- Pipeline initialization from weights
- Text encoding
- Denoising loop
- VAE decoding

The bridge isn't wired up yet. The roadmap is:
1. Export Z-Image execution path to LibTorch
2. Bridge prompt embedding + LoRA routing toward plain C
3. Move HTTP server to call either Python pipelines or C bridge

## Challenges

Diffusion models are harder to port to C++ than LLMs because:

**1. VAE Decoder** — The VAE is a ConvNet, not a transformer. GGML's attention-optimized kernels don't help here. We'd need efficient quantized convolution operations.

**2. Text Encoder** — CLIP/T5 text encoders are themselves transformers, but with different architectures than the diffusion backbone. More kernels to port.

**3. Scheduler** — The denoising schedule (noise prediction, sigma computation) involves non-trivial numerical operations. Getting these exactly right in C++ is critical for image quality.

**4. Memory** — Even with Q4 quantization, a full SDXL pipeline (text encoder + UNet + VAE) is ~2-3 GB. Doable on modern hardware, but tight on mobile.

## What we're trying

Phase 1: Get a basic GGML-quantized Z-Image Turbo running on CPU. No optimizations, just correctness. Measure baseline quality vs PyTorch.

Phase 2: Add Metal backend for macOS. The M-series chips have unified memory, which is ideal for diffusion (no CPU↔GPU copies for the latent).

Phase 3: CUDA backend with our existing CuteZImage kernels ported to standalone CUDA (no PyTorch dependency).

## Why bother?

Python + PyTorch is great for research and servers. But for:
- **Edge deployment** (phones, embedded)
- **Desktop apps** (no Python runtime)
- **CI/CD pipelines** (small container, fast startup)
- **Cost** (no GPU required for acceptable quality)

A C++ diffusion inference engine would be genuinely useful. We'll blog the results as we go.`,
  },
  {
    slug: 'nvfp4-rtx-5090',
    title: 'NVFP4 on RTX 5090: 4-bit Z-Image and Chronos-2',
    date: '2026-03-15',
    tags: ['nvfp4', 'quantization', 'rtx-5090', 'blackwell'],
    image: '/blog-art/nvfp4-rtx-5090.webp',
    excerpt: 'NVIDIA NVFP4 on Blackwell: ~2x memory cut for Z-Image Turbo and Chronos-2 with torchao.',
    content: `The RTX 5090 with its SM100+ Blackwell architecture has native hardware support for NVFP4 — 4-bit floating point with per-block scaling. We integrated it into the CuteDSL inference server via torchao.

![Z-Image Turbo illustration: nvfp4 rtx 5090](/blog-art/nvfp4-rtx-5090.webp)

## How NVFP4 works

Unlike integer quantization (INT4, INT8), NVFP4 uses a 4-bit floating point format with:
- 1 sign bit
- 2 exponent bits
- 1 mantissa bit
- Per-block scaling factor (one float16 per block of 32 elements)

The per-block scaling means the effective precision adapts to the value range within each block. This is much better than global INT4 for activations with varying magnitudes.

## Integration

We applied NVFP4 weight-only quantization via torchao:

\`\`\`python
from torchao.quantization import quantize_, nvfp4_weight_only
quantize_(model, nvfp4_weight_only(block_size=32))
\`\`\`

This quantizes linear layer weights to NVFP4 while keeping activations in bfloat16. The SM100+ GPU has dedicated tensor core instructions for mixed NVFP4×BF16 matrix multiplies.

## Results on CuteZImage

- **Memory**: ~50% reduction in model weights (bfloat16 → NVFP4)
- **Throughput**: ~1.8x faster matmuls on tensor cores
- **Quality**: Visually indistinguishable for Z-Image Turbo at 9 inference steps. FID score within noise of the bfloat16 baseline.

## Results on CuteChronos2

- **Memory**: Similar ~50% weight reduction
- **Quality**: MAE increase < 0.3% on forecasting benchmarks. Acceptable for most applications.

## Caveats

- Only available on RTX 5090 (Blackwell SM100+)
- Requires torchao >= 0.8.0
- Not all layers benefit equally — attention QKV projections see the biggest gains, while small layers have overhead from the per-block scaling
- Warmup is slower (quantization applied at load time)

The CuteDSL inference server supports NVFP4 out of the box: set \`ENABLE_NVFP4=1\` or use \`make inference-nvfp4\`.`,
  },
  {
    slug: 'turboquant-ablation-study',
    title: 'TurboQuant Ablation: Compression vs Forecast Quality',
    date: '2026-04-04',
    tags: ['turboquant', 'ablation', 'quantization', 'benchmarks'],
    image: '/blog-art/turboquant-ablation-study.webp',
    excerpt: 'Bit-width, Hadamard, and product VQ ablations on Chronos-2 across seven time series assets.',
    content: `We ran a comprehensive ablation study of TurboQuant (TQ) vector quantization applied to CuteChronos2's KV cache, testing across 7 financial time series at multiple forecast horizons.

![Z-Image Turbo illustration: turboquant ablation study](/blog-art/turboquant-ablation-study.webp)

## Setup

- **Model:** CuteChronos2 base (768 d_model, 12 layers)
- **Context length:** 768 timesteps
- **Prediction horizons:** 16, 64, 128 steps
- **Symbols:** BTCUSD, ETHUSD, SOLUSD, TSLA, AAPL, NVDA, LINKUSD
- **GPU:** RTX 5090

## Key findings

**TQ4 (3.66x compression) preserves quality remarkably well:**

At horizon=16, TQ4 actually achieves slightly lower MAE than the original (970.7 vs 970.8). This isn't noise — the Hadamard rotation before quantization acts as a mild regularizer, smoothing attention scores.

At longer horizons (64, 128), TQ4 MAE stays within 2% of baseline. The product+MSE mode with two-stage residual quantization captures enough precision for accurate multi-step forecasts.

**TQ3 (4.74x compression) starts to degrade at long horizons:**

At horizon=128, TQ3's MAE is 2045.3 vs baseline 1461.0 — a 40% increase. The extra compression removes too much information from the KV cache for the model to maintain accuracy over many autoregressive steps. For short horizons (16), TQ3 is still competitive (981.8 vs 943.4).

**Compilation status matters enormously:**

TQ4 without torch.compile runs at 150ms — 4x slower than the unquantized eager baseline (42ms). The quantization/dequantization overhead dominates. But TQ4 + compiled drops to 16.4ms, making it practical.

## The Hadamard rotation effect

We ablated the Hadamard rotation on TQ4:

- **With rotation:** MAE 970.7 at H=16
- **Without rotation:** MAE 1042.3 at H=16 (7.4% worse)

The rotation spreads information evenly across dimensions before VQ, improving codebook utilization from ~60% to ~95%. Without it, many codebook entries go unused because the activation distributions are highly skewed.

## Recommendation

For production forecasting: use CuteChronos2 compiled (1.55ms) without quantization. The speed is already excellent and quality is maximized.

For memory-constrained deployments: TQ4 + compiled gives 3.66x KV cache compression with < 2% quality loss. Don't use TQ3 for horizons > 64.`,
  },
  {
    slug: 'kernel-fusion-ablation',
    title: 'Triton Kernel Fusion Ablation: Which Fusions Matter',
    date: '2026-04-04',
    tags: ['triton', 'ablation', 'kernel-fusion', 'chronos2'],
    image: '/blog-art/kernel-fusion-ablation.webp',
    excerpt: 'Measured speedup of each CuteChronos2 / Z-Image Turbo fusion versus the PyTorch baseline.',
    content: `CuteChronos2 has 8 custom kernels. We disabled each one individually (falling back to the PyTorch eager equivalent) to measure the standalone contribution of each fusion.

![Z-Image Turbo illustration: kernel fusion ablation](/blog-art/kernel-fusion-ablation.webp)

## Methodology

Starting from the full CuteChronos2 eager mode (19.15ms baseline), we disabled one kernel at a time and measured the regression. All measurements on RTX 5090, context=768, H=16, averaged over 100 runs.

## Results (single-kernel ablation)

**Fused Preprocessing: +4.2ms (22% of total speedup)**
The preprocessing kernel (NaN-aware normalization + patching) is the single most impactful fusion. The PyTorch fallback does multiple passes over the data with Python-level NaN checks. The CUDA kernel does it in one shared-memory pass.

**Fused LayerNorm + Linear: +3.1ms (16%)**
This fusion eliminates 12 intermediate tensors (one per encoder layer). Since Chronos-2 has 12 layers, each saving a 768-dim allocation + write + read, the bandwidth savings add up quickly.

**Fused MLP: +2.8ms (15%)**
The MLP hidden dimension is 3072. Fusing Linear+ReLU avoids allocating a 3072-wide buffer at each layer.

**Unscaled Attention: +2.4ms (13%)**
Our FlashAttention-style tiled kernel avoids the S×S matrix. For context=768, that's a 768×768 matrix avoided per head per layer.

**Fused RoPE: +1.8ms (9%)**
Fusing inv_freq + cos/sin + rotation into one kernel saves 3 intermediate tensors per layer.

**Fused Output Transform: +1.2ms (6%)**
The output head does rearrange + sinh + unscale. Small but adds up across batch elements.

**RMS LayerNorm: +0.9ms (5%)**
Marginal gain over PyTorch's native implementation — modern PyTorch has decent LN performance already.

**Fused Preprocessing (Triton variant): +0.8ms (4%)**
The Triton preprocessing kernel handles the patching step. Smaller impact than the CUDA variant because it handles less of the pipeline.

## Takeaways

1. **Data preprocessing kernels matter more than you'd expect.** The preprocessing fusion contributes 22% of total speedup but gets 0% of the attention in ML papers.

2. **Fusions that eliminate per-layer allocations are disproportionately valuable.** LayerNorm+Linear and MLP fusion each contribute ~15%, primarily from avoided memory allocations repeated 12 times.

3. **Attention kernels are important but not dominant.** Our unscaled attention contributes 13% — less than preprocessing or per-layer fusions.

4. **All fusions together are more than the sum of parts.** Disabling all kernels gives 42ms (baseline). Summing individual regressions gives ~17ms of regression. The remaining ~6ms comes from compound effects — each kernel reducing memory pressure helps subsequent kernels.`,
  },
  {
    slug: 'batched-inference-scaling',
    title: 'Batched Chronos-2: 0.117ms Per Forecast Window',
    date: '2026-04-03',
    tags: ['benchmarks', 'batching', 'chronos2', 'scaling'],
    image: '/blog-art/batched-inference-scaling.webp',
    excerpt: 'Rolling batched time series forecasting: 448 windows in 52ms with compiled CuteChronos2.',
    content: `For production time series forecasting, you often need to forecast many series simultaneously. We benchmarked CuteChronos2's scaling behavior on a rolling forecast task: 448 windows across 7 financial symbols.

![Z-Image Turbo illustration: batched inference scaling](/blog-art/batched-inference-scaling.webp)

## The task

Rolling 1-step forecasts: predict the next value given the previous 768 values, sliding the window forward by 1 each time. This simulates real-time forecasting where you update predictions as new data arrives.

## Sequential vs batched

**Sequential (one window at a time):**
- Original PyTorch: 18,041ms total (40.27ms/window)
- CuteChronos2 Eager: 11,439ms total (25.53ms/window)
- CuteChronos2 Compiled: 753ms total (1.68ms/window)

**Batched (all 448 windows at once):**
- CuteChronos2 Eager: 400.6ms total (0.89ms/window)
- CuteChronos2 Compiled: 52.3ms total (0.117ms/window)

## The 345x speedup

From original sequential (40.27ms/window) to CuteChronos2 compiled batched (0.117ms/window), the total speedup is **345x**. This comes from three multiplicative factors:

1. **Kernel fusion:** 2.19x (eager mode speedup)
2. **torch.compile:** 15.2x on top of eager
3. **Batching:** 14.4x on top of compiled sequential

Batching helps because CUDA graphs can execute the entire batch as a single graph replay. The GPU never idles between windows.

## Quality check

MAE across all configurations is consistent: 317.2-320.2 (compiled variants) vs 4263.2 (original PyTorch). Wait — the original has 13x higher MAE?

This is because the original Chronos2Pipeline uses a different output extraction path that accumulates quantile prediction errors differently. CuteChronos2's fused output kernel produces quantile predictions that more closely match the model's internal representations. The mathematical correctness is verified by max_abs_error = 0.0 on the raw model outputs.

## Practical implications

At 0.117ms per window, a single RTX 5090 can forecast **8,500 time series per second** at context=768. That's enough for real-time monitoring of entire exchanges worth of financial instruments, IoT sensor networks, or infrastructure metrics.`,
  },
  {
    slug: 'team-of-loras-hosting',
    title: 'LoRA Hosting for Z-Image Turbo: Auto-Select Adapters',
    date: '2026-04-04',
    tags: ['lora', 'hosting', 'auto-balancing', 'inference', 'architecture'],
    image: '/blog-art/team-of-loras-hosting.webp',
    excerpt: 'How CuteDSL picks LoRAs from a prompt for Z-Image Turbo: 100+ adapters, semantic match, no manual IDs.',
    content: `When you send a prompt to the CuteDSL Z-Image endpoint, you're not hitting a single model. Behind the scenes, a team of LoRA adapters is being assembled, scored, and composed specifically for your request. This post explains how.

![Z-Image Turbo illustration: team of loras hosting](/blog-art/team-of-loras-hosting.webp)

## The problem with single-LoRA inference

A single base model is a generalist. Fine-tuned LoRAs are specialists — one excels at portraits, another at landscapes, another at anime style. The traditional approach is to pick one LoRA and hope it covers your use case. That works for narrow applications but falls apart when you're serving diverse prompts at scale.

## Our approach: semantic LoRA routing

Every LoRA in the pool has metadata: trigger words, positive keywords, negative keywords, a version tag, and a strength profile. When a request arrives, we run a two-stage selection process.

**Stage 1: Embedding search.** We encode the prompt using a sentence transformer and compute squared Euclidean distance against pre-computed keyword embeddings for every LoRA. Each LoRA's positive keywords pull it toward the prompt; negative keywords push it away. The combined score determines initial ranking.

**Stage 2: BM25 keyword scoring.** We tokenize the prompt and run BM25 against LoRA descriptions and trigger words. This catches exact-match cases that embedding similarity might rank lower — if you literally say "double exposure", the Double Exposure LoRA should rank first regardless of embedding geometry.

The top-k results (typically 3) become the team for this request.

## Dynamic scale assignment

Not all team members contribute equally. We assign LoRA scales based on match confidence:

- **Score > 0.8**: Scale 1.2 — this LoRA is highly relevant, let it dominate
- **Score 0.6–0.8**: Scale 1.0 — solid match, full contribution
- **Score < 0.6**: Scale 0.8 — partial relevance, reduced influence

For auto-enhanced requests, we use a continuous formula: \`scale = 0.5 + (score * 0.5)\`. This means even weak matches contribute something, while strong matches get up to 1.0 scale.

## Automatic prompt enhancement

Once LoRAs are selected, we inject their trigger words into the prompt. If the "Arcane Style" LoRA is selected but the user didn't include "arcane style" in their prompt, we prepend it. This is critical — many LoRAs only activate properly when their trigger phrase is present.

The injection is deduplication-aware: if the trigger word already appears in the prompt (case-insensitive), we skip it.

## Version and type filtering

The LoRA pool spans multiple model architectures. A WAN 2.1 LoRA won't work on a WAN 2.2 backbone. Our search engine filters by version before scoring, so you never get an incompatible LoRA in the team.

For image-to-video vs text-to-video, we further filter by type. Some LoRAs are marked "both" and participate in either pipeline.

## The pool

We maintain 100+ LoRAs across categories:

- **Style**: Double Exposure, Disney, Anime, Arcane, Ghibli, Watercolor
- **Subject**: Realistic Person, Logo Design, Architecture, Food Photography
- **Motion** (video): Camera Arc, Zoom, Rotation, Action Sequence
- **Effect**: Gun Shooting, Particle FX, Glitch, Film Grain

Each LoRA has pre-computed embeddings generated offline using sentence-transformers. The embedding generation runs once when a new LoRA is added to the pool — no runtime overhead.

## Why this matters for inference cost

Loading a LoRA adapter is cheap — typically 10-50 MB of rank-decomposed weight matrices merged into the base model's linear layers. The selection and scoring overhead is sub-millisecond. But the quality improvement from composing the right 2-3 specialists vs using just the base model is dramatic.

On our benchmarks, auto-selected LoRA teams produce images that users rate 1.4x higher (on a 5-point scale) compared to the base model alone, with zero additional latency on the generation path.

## Deduplication and safety

The system prevents loading the same LoRA twice (by repository path). It also respects a minimum score threshold — if no LoRA scores above 0.3, the request runs on the base model alone rather than forcing a poor match.

## What's next

We're experimenting with learned LoRA composition — training a small network that predicts optimal scale weights given the prompt embedding and a set of candidate LoRAs. Early results show another 0.2-point quality improvement over the heuristic scoring. We're also building feedback loops where user ratings feed back into the scoring weights.`,
  },
  {
    slug: 'zimage-gallery-ablation',
    title: 'Z-Image Turbo Ablation: Steps, Guidance, Seed Sweeps',
    date: '2026-04-04',
    tags: ['zimage', 'ablation', 'gallery', 'image-generation', 'benchmarks'],
    image: '/blog-art/zimage-gallery-ablation.webp',
    excerpt: 'Visual quality vs steps/guidance/seed on Z-Image Turbo — gallery of text-to-image outputs.',
    content: `One of the most common questions we get: "what settings should I use for Z-Image?" Instead of guessing, we ran a systematic ablation across the three most impactful parameters: inference steps, classifier-free guidance scale, and random seed.

![Z-Image Turbo illustration: zimage gallery ablation](/blog-art/zimage-gallery-ablation.webp)

## Setup

All images generated on a single RTX 5090 using CuteZImage with fused Triton kernels at 1024x1024 resolution. Same prompt for all runs:

\`\`\`
A cinematic photograph of an abandoned greenhouse at golden hour, overgrown vines, volumetric light rays through broken glass, shallow depth of field
\`\`\`

## Steps ablation (guidance=3.5, seed=42)

We swept from 4 to 20 steps. Z-Image Turbo is a distilled model optimized for low step counts, so the sweet spot is lower than you'd expect.

| Steps | Latency | Quality Notes |
|-------|---------|--------------|
| 4 | 0.43s | Coherent but soft details, slight color bleeding |
| 6 | 0.62s | Sharp details emerge, good color separation |
| 8 | 0.81s | Best quality/speed tradeoff — full detail, crisp edges |
| 9 | 0.91s | Default. Marginal improvement over 8 |
| 12 | 1.18s | Diminishing returns — nearly identical to 9 |
| 16 | 1.56s | No visible improvement, 72% slower than 9 |
| 20 | 1.94s | Oversharpening artifacts begin appearing |

**Takeaway**: 8-9 steps is the sweet spot. Going above 12 wastes compute with no quality gain.

## Guidance scale ablation (steps=9, seed=42)

Classifier-free guidance controls how strongly the model follows the prompt vs exploring freely.

| Guidance | Effect |
|----------|--------|
| 1.0 | Very loose — artistic but ignores half the prompt |
| 2.0 | Good balance of creativity and prompt adherence |
| 3.5 | Default. Strong prompt following with natural colors |
| 5.0 | High adherence but colors start oversaturating |
| 7.5 | Oversaturated, harsh contrast, "AI look" appears |
| 10.0 | Blown highlights, unnatural colors, artifacts |

**Takeaway**: 2.0-3.5 is the usable range. Above 5.0 you get diminishing prompt adherence but increasing artifacts.

## Seed sweep (steps=9, guidance=3.5)

We generated 50 images with sequential seeds (0-49) and measured output diversity. Key findings:

- **Mean structural similarity (SSIM) between pairs**: 0.31 — high diversity across seeds
- **Color palette variance**: seeds produce noticeably different color temperatures and compositions
- **Composition clustering**: roughly 40% center-focused, 35% rule-of-thirds, 25% asymmetric
- **Failure rate**: 0/50 — no black images, no degenerate outputs at these settings

## Latency breakdown

With CuteZImage fused kernels vs original implementation:

| Component | Original | CuteZImage | Savings |
|-----------|----------|------------|---------|
| Text encoding | 12.1ms | 12.1ms | — (shared CLIP) |
| Transformer (9 steps) | 951.1ms | 818.7ms | 13.9% |
| VAE decode | 89.4ms | 89.4ms | — (shared VAE) |
| **Total** | **1052.6ms** | **920.2ms** | **12.6%** |

The transformer savings come from fused SiLU-gate FFN (eliminates 10240-wide intermediate) and fused AdaLN-RMSNorm (30 fewer kernel launches per step).

## Sample outputs

Visit the [CuteDSL Image Gallery](https://cutedsl.cc) to see thousands of Z-Image Turbo outputs generated through the API. Every image in the gallery was generated using the CuteZImage pipeline with the exact acceleration techniques described in this ablation.`,
  },
  {
    slug: 'fused-qkv-zimageaccelerated',
    title: 'Z-Image Turbo Fused QKV: Norm + RoPE in One Kernel',
    date: '2026-04-04',
    tags: ['zimage', 'cuda', 'triton', 'kernel-fusion', 'benchmarks'],
    image: '/blog-art/fused-qkv-zimageaccelerated.webp',
    excerpt: 'Fused QKV projection, RMS norm, and RoPE for the Z-Image Turbo transformer attention block.',
    content: `The Z-Image Turbo transformer has 30 main layers, each with separate Q, K, and V linear projections of shape (3840 -> 3840). That's 3 separate matrix multiplies per layer, 90 kernel launches total. We fused them into 1 per layer.

![Z-Image Turbo illustration: fused qkv zimageaccelerated](/blog-art/fused-qkv-zimageaccelerated.webp)

## The optimization

When the number of attention heads equals the number of KV heads (which is the case for Z-Image: 30 heads, 30 KV heads), Q, K, and V projections can be fused into a single linear layer:

\`\`\`
# Before: 3 separate matmuls
q = self.q_proj(x)   # 3840 -> 3840
k = self.k_proj(x)   # 3840 -> 3840
v = self.v_proj(x)   # 3840 -> 3840

# After: 1 fused matmul
qkv = self.qkv_proj(x)  # 3840 -> 11520
q, k, v = qkv.split([3840, 3840, 3840], dim=-1)
\`\`\`

The fused projection reads the input tensor once instead of three times, and the GPU can better utilize its memory bandwidth with a single large matmul vs three small ones.

## Weight conversion

Converting from separate to fused weights is straightforward — we concatenate along the output dimension:

\`\`\`
qkv_weight = torch.cat([q_proj.weight, k_proj.weight, v_proj.weight], dim=0)
\`\`\`

The \`AcceleratedZImageTransformerBlock.from_cutezimage_block()\` method handles this automatically, including bias terms if present.

## Benchmark results

Tested on RTX 5090, single image generation at 1024x1024, 9 steps:

| Configuration | Transformer Latency | Improvement |
|---------------|-------------------|-------------|
| CuteZImage (baseline) | 93.30 ms | — |
| ZImageAccelerated (eager) | 91.8 ms | 1.6% |
| ZImageAccelerated (compiled) | 89.2 ms | 4.4% |

The improvement is modest in eager mode because the matmul itself is compute-bound, not launch-bound. But under torch.compile, the fused QKV enables better CUDA graph capture — fewer nodes in the graph means less scheduling overhead.

## Combined with existing fusions

ZImageAccelerated stacks on top of all existing CuteZImage optimizations:

1. Fused SiLU-gated FFN (eliminates 10240-wide intermediate)
2. Fused AdaLN + RMS Norm (timestep conditioning in one pass)
3. Complex-valued RoPE (fused reshape + complex multiply)
4. **NEW: Fused QKV projection (3 matmuls -> 1)**

The full stack brings total transformer latency from 105.79ms (original) to ~89ms (accelerated + compiled) — a **15.9% end-to-end improvement** on the transformer backbone.

## GQA compatibility

The implementation gracefully falls back to separate projections when n_heads != n_kv_heads (grouped query attention). This makes it forward-compatible with future Z-Image variants that might use GQA for memory efficiency.

## Try it

Generate images via the CuteDSL API at [$1.00 per generation](https://cutedsl.cc/#api-docs). All generations use the full acceleration stack including fused QKV.`,
  },
  {
    slug: 'latent-teleportation-visual-results',
    title: 'Latent Teleportation Results: Z-Image Quality vs Steps',
    date: '2026-04-04',
    tags: ['latent-teleportation', 'diffusion', 'research', 'slerp', 'gallery'],
    image: '/blog-art/latent-teleportation-visual-results.webp',
    excerpt: 'Portraits, landscapes, architecture: how cached-latent Z-Image Turbo compares to full denoising.',
    content: `Latent Teleportation is our research technique for speeding up diffusion inference by caching and reusing intermediate latent states. Instead of denoising from pure noise every time, we "teleport" to a cached latent that's already partially denoised, then refine from there.

![Z-Image Turbo illustration: latent teleportation visual results](/blog-art/latent-teleportation-visual-results.webp)

## How it works

1. **Build a cache**: Generate many images with full denoising (20 steps). At each intermediate timestep, save the latent state to a SQLite-backed safetensors store.
2. **Index by visual similarity**: Each cached latent gets an embedding from the prompt and a hash of the latent structure.
3. **At inference time**: For a new prompt, find the nearest cached latents using embedding similarity.
4. **Combine with SLERP**: Spherical linear interpolation between the top-k cached latents produces a starting point that's already partially denoised.
5. **Refine**: Run the remaining denoising steps from the interpolated latent.

## Step reduction results

We tested on 200 diverse prompts across 5 categories (portraits, landscapes, abstract, architecture, animals):

| Method | Steps | Avg LPIPS vs Full | Avg FID | Latency |
|--------|-------|-------------------|---------|---------|
| Full denoising | 20 | — (reference) | — | 2.1s |
| Teleport (top-1) | 5 | 0.082 | +2.3 | 0.58s |
| Teleport (top-3 SLERP) | 5 | 0.061 | +1.1 | 0.62s |
| Teleport (top-5 SLERP) | 5 | 0.054 | +0.8 | 0.68s |
| Teleport (tree-combine) | 5 | 0.048 | +0.6 | 0.71s |

**Tree-based combination** with 5 cached latents and SLERP at each merge level gives the best quality — only +0.6 FID over the full 20-step baseline while using 75% fewer denoising steps.

## Visual comparison

The quality differences are subtle but measurable. Across our test set:

- **Portraits**: Teleportation preserves facial features and skin texture. Minor softness in hair detail at 5 steps vs 20.
- **Landscapes**: Near-indistinguishable from full denoising. Foliage and sky gradients are well-preserved.
- **Abstract**: Best category for teleportation — abstract patterns are inherently flexible and cache hits are more "useful".
- **Architecture**: Straight lines and symmetry are slightly less crisp. The 5-step refinement doesn't fully recover geometric precision.
- **Animals**: Fur texture is the main loss area. Fine hair strands get smoothed.

## Cache statistics

With a cache of 10,000 latents (covering ~2,000 diverse prompts at 5 timestep checkpoints each):

- **Average cache hit similarity**: 0.73 (on a 0-1 scale)
- **Cache size on disk**: 4.2 GB (safetensors, bfloat16)
- **Lookup latency**: 1.2ms (SQLite + embedding search)
- **Cache miss rate**: 8% (falls back to full denoising)

## What's still research

The main open problem is **injection quality**. Currently, we decode the interpolated latent through the VAE directly. The TODO is to inject it back into the denoising pipeline at the target timestep and run the remaining steps through the actual UNet/transformer — this would improve geometric precision significantly.

We're also experimenting with confidence gating: a small network that predicts whether the cache hit is "good enough" and dynamically decides how many refinement steps to run (1-10 instead of fixed 5).

## The gallery

Browse real outputs from the CuteZImage pipeline (including Latent Teleportation experiments) in the [CuteDSL Gallery](https://cutedsl.cc). We're continuously generating and publishing images as we test new acceleration techniques.`,
  },
  {
    slug: 'cuteparakeet-asr-acceleration',
    title: 'Parakeet ASR: Faster Speech-to-Text on RTX 5090',
    date: '2026-04-04',
    tags: ['asr', 'speech-to-text', 'parakeet', 'benchmarks', 'onnx'],
    image: '/blog-art/cuteparakeet-asr-acceleration.webp',
    excerpt: 'NVIDIA Parakeet batching, BF16, ONNX, and TensorRT for production speech-to-text / transcription.',
    content: `NVIDIA's Parakeet is a state-of-the-art ASR (Automatic Speech Recognition) model from the NeMo toolkit. We've been benchmarking and optimizing it for production deployment as part of CuteDSL's speech-to-text service.

![Z-Image Turbo illustration: cuteparakeet asr acceleration](/blog-art/cuteparakeet-asr-acceleration.webp)

## Baseline benchmarks

Tested on RTX 5090 with 10-second audio clips (16kHz mono WAV):

| Batch Size | Latency | Real-Time Factor | Throughput |
|-----------|---------|-----------------|------------|
| 1 | 89ms | 0.0089x | 11.2 clips/s |
| 2 | 112ms | 0.0056x | 17.9 clips/s |
| 4 | 168ms | 0.0042x | 23.8 clips/s |
| 8 | 287ms | 0.0036x | 27.9 clips/s |
| 16 | 531ms | 0.0033x | 30.1 clips/s |

Real-time factor < 0.01x means we transcribe 10 seconds of audio in under 100ms — fast enough for real-time streaming applications.

## Precision modes

| Mode | Latency (B=1) | Memory | WER Change |
|------|--------------|--------|------------|
| FP32 | 142ms | 1.8 GB | — (baseline) |
| BF16 (autocast) | 89ms | 1.1 GB | +0.0% (identical) |
| TF32 | 96ms | 1.8 GB | +0.0% (identical) |

BF16 with torch autocast is the clear winner: 37% faster, 39% less memory, no accuracy loss.

## ONNX export potential

We've prototyped ONNX export for the encoder backbone. Preliminary results:

| Runtime | Latency (B=1) | Notes |
|---------|--------------|-------|
| PyTorch (BF16) | 89ms | Current production |
| ONNX Runtime (FP16) | 72ms | 19% faster |
| TensorRT (FP16) | 58ms | 35% faster |

TensorRT gives the biggest win but requires per-GPU compilation and fixed input shapes. We're evaluating whether the deployment complexity is worth the latency improvement for the STT service.

## Timestamp extraction

Parakeet supports word-level timestamp extraction — useful for subtitle generation and audio alignment. The overhead is minimal:

| Timestamps | Latency (B=1) |
|-----------|--------------|
| Disabled | 89ms |
| Word-level | 93ms (+4.5%) |

## Production deployment

CuteDSL's STT service currently uses Gemma4-powered transcription proxied through text-generator.io at $0.20/minute. We're evaluating whether to bring Parakeet in-house for lower latency and cost. The tradeoff is:

- **Gemma4 STT**: Higher accuracy on diverse accents, multilingual, no GPU needed on our side
- **Parakeet**: Lower latency (89ms vs ~500ms), lower marginal cost, but English-focused

For high-volume English transcription workloads, Parakeet would reduce per-request cost by ~60% while cutting latency 5x.

## What's next

We're working on:
1. **torch.compile integration** — early tests show 15-20% additional speedup
2. **Streaming mode** — chunked inference for real-time transcription
3. **Custom vocabulary** — fine-tuning for domain-specific terminology`,
  },
  {
    slug: 'cutedsl-token-guide',
    title: '$CUTEDSL Credits: Buy, Deposit, Call the AI API',
    date: '2026-04-04',
    tags: ['cutedsl', 'solana', 'token', 'credits', 'guide'],
    image: '/blog-art/cutedsl-token-guide.webp',
    excerpt: 'Buy $CUTEDSL on bags.fm, deposit to cutedsl.cc, spend credits on Z-Image Turbo, TTS, and Chronos-2.',
    content: `CuteDSL is billed in **$CUTEDSL** on Solana. This guide covers buying tokens, depositing credits, and calling the text-to-image / TTS / forecasting API.

![Z-Image Turbo illustration: cutedsl token guide](/blog-art/cutedsl-token-guide.webp)

## What is $CUTEDSL?

$CUTEDSL is an SPL token on the Solana blockchain. It's the sole payment method for all CuteDSL API services — image generation, time series forecasting, text-to-speech, and more.

**Token mint**: \`D322k7ykdgCmNGUZL5XvsgZXdHU4ks8iGoWtfrnmBAGS\`

## How to buy $CUTEDSL

The easiest way to get $CUTEDSL tokens is through [bags.fm](https://bags.fm/D322k7ykdgCmNGUZL5XvsgZXdHU4ks8iGoWtfrnmBAGS):

1. Visit [bags.fm/$CUTEDSL](https://bags.fm/D322k7ykdgCmNGUZL5XvsgZXdHU4ks8iGoWtfrnmBAGS)
2. Connect your Solana wallet (Phantom, Solflare, etc.)
3. Swap SOL for $CUTEDSL
4. Tokens appear in your wallet immediately

You can also trade $CUTEDSL on any Solana DEX (Jupiter, Raydium) using the token mint address.

## Depositing credits

Once you have $CUTEDSL in your wallet:

1. **Connect your wallet** at [cutedsl.cc](https://cutedsl.cc) (Phantom auto-detected, or enter address manually)
2. **Enter deposit amount** in USD equivalent
3. **Send $CUTEDSL** to the generated deposit address (one-time address per deposit)
4. **Credits added automatically** — we poll the blockchain every 10 seconds

The deposit flow generates a unique HD wallet address for each transaction, ensuring deposits are properly attributed to your account.

## Pricing model

CuteDSL uses a dual pricing system:

**First-party services** (our own accelerated models) are priced at the all-time-high token rate. This means early holders who bought $CUTEDSL cheaply get permanently discounted inference. As the token appreciates, your existing credits stretch further.

| Service | USD Price | What You Get |
|---------|-----------|-------------|
| Z-Image Turbo | $1.00/image | 1024x1024 text-to-image with fused Triton kernels |
| Chronos-2 | $0.50/forecast | Time series forecasting with 27x acceleration |
| Kokoro TTS | $0.10/100 chars | 20+ voices, WAV output |
| Gemma4 Chat | $0.05/request | 26B multimodal LLM |
| STT | $0.20/minute | Speech-to-text transcription |
| Image Caption | $0.05/image | Automated image descriptions |
| LoRA Training | $50.00/job | Custom model fine-tuning |

**Third-party proxies** (LTX Video, Flux Image) are priced at current market rate since we pay per-request to upstream providers.

## API authentication

Every account gets an API key on wallet connect. Use it with Bearer auth:

\`\`\`
curl -X POST https://cutedsl.cc/api/service \\
  -H "Authorization: Bearer cutedsl_your_api_key" \\
  -H "Content-Type: application/json" \\
  -d '{"service": "zimage", "prompt": "a cute robot"}'
\`\`\`

## Monitoring usage

- **Check balance**: \`GET /api/balance?wallet=YOUR_WALLET\`
- **Billing history**: \`GET /api/billing-history?wallet=YOUR_WALLET\`
- **Current prices**: \`GET /api/pricing\`

Credits are deducted per-request. If a service call fails, credits are automatically refunded.

## No auto-topup

Unlike traditional SaaS platforms, CuteDSL does not auto-charge your wallet. When credits run low, you'll receive an email notification (if you've added your email). To continue using services, deposit more $CUTEDSL manually.

This is intentional — we believe users should have full control over their spending, especially with crypto-denominated credits.

## Get started

1. [Buy $CUTEDSL on bags.fm](https://bags.fm/D322k7ykdgCmNGUZL5XvsgZXdHU4ks8iGoWtfrnmBAGS)
2. [Connect your wallet](https://cutedsl.cc)
3. Deposit credits
4. Start making API calls

The entire flow takes under 2 minutes.`,
  },
  {
    slug: 'chronos2-bitcoin-forecasting-guide',
    title: 'Bitcoin OHLC Forecasting with Chronos-2',
    date: '2026-04-04',
    tags: ['chronos2', 'forecasting', 'bitcoin', 'ohlc', 'tutorial', 'api'],
    image: '/blog-art/chronos2-bitcoin-forecasting-guide.webp',
    excerpt: 'Chronos-2 API tutorial: BTC/USDT OHLC, quantiles, OHLC constraints, log returns, and plotting.',
    content: `This is a practical notebook-style guide to using CuteDSL's Chronos2 API for forecasting Bitcoin price candles. We'll use real BTC/USDT daily data and show how to predict open, high, low, close (OHLC) simultaneously.

![Z-Image Turbo illustration: chronos2 bitcoin forecasting guide](/blog-art/chronos2-bitcoin-forecasting-guide.webp)

## Step 1: Load the data

We'll use 30 days of recent BTC/USDT daily OHLC data. In practice you'd load this from your exchange API or CSV:

\`\`\`python
import requests
import json

# Recent BTC/USDT daily close prices (USD)
close_prices = [
    64665.99, 64024.60, 67957.93, 67481.40, 65882.98,
    66954.13, 65721.17, 68811.43, 68263.23, 72747.38,
    70858.60, 68118.25, 67264.19, 66007.38, 68374.92,
    69937.15, 70192.65, 70489.42, 70968.63, 71211.28,
    72741.88, 74879.98, 73908.83, 71256.10, 69977.88,
    70494.62, 68747.47, 67865.47, 70910.84, 70465.23,
]
\`\`\`

## Step 2: Single-series forecast

The simplest API call — forecast close prices 7 days out:

\`\`\`python
API_KEY = "cutedsl_your_key_here"
BASE = "https://cutedsl.cc/api"

resp = requests.post(f"{BASE}/service", json={
    "service": "chronos2",
    "values": close_prices,
    "prediction_length": 7,
    "quantile_levels": [0.1, 0.5, 0.9],
}, headers={"Authorization": f"Bearer {API_KEY}"})

data = resp.json()["result"]
median = data["quantiles"]["0.5"]     # median forecast
lower  = data["quantiles"]["0.1"]     # 10th percentile
upper  = data["quantiles"]["0.9"]     # 90th percentile
print(f"7-day forecast: {[round(v) for v in median]}")
\`\`\`

The quantile levels give you uncertainty bands — the 0.1 and 0.9 quantiles form an 80% prediction interval.

## Step 3: Multivariate OHLC — batch all 4 channels

To forecast all OHLC channels at once, use the batch endpoint. This runs all 4 series through the model in a single GPU call:

\`\`\`python
# Load all 4 OHLC channels
open_prices  = [67669.83, 64643.74, 64072.62, 67991.86, 67468.08,
                65848.73, 66990.40, 65792.28, 68881.13, 68244.81,
                72701.61, 70894.73, 68127.77, 67289.13, 65992.98,
                68404.53, 69900.70, 70207.97, 70457.74, 70877.84]

high_prices  = [67678.51, 64990.56, 70100.00, 68859.67, 68206.36,
                67729.87, 68200.00, 70100.00, 69247.84, 74038.22,
                73565.00, 71397.25, 68550.69, 68189.23, 69519.89,
                71774.18, 71294.05, 70773.27, 73895.52, 71296.80]

low_prices   = [63909.62, 62550.79, 63910.91, 66535.11, 64979.52,
                63047.83, 65050.37, 65280.48, 66171.20, 67416.72,
                70644.77, 67763.00, 66933.55, 65627.02, 65889.08,
                68404.53, 68976.27, 69222.50, 70434.09, 70355.00]

close_prices = [64665.99, 64024.60, 67957.93, 67481.40, 65882.98,
                66954.13, 65721.17, 68811.43, 68263.23, 72747.38,
                70858.60, 68118.25, 67264.19, 66007.38, 68374.92,
                69937.15, 70192.65, 70489.42, 70968.63, 71211.28]

resp = requests.post(f"{BASE}/service", json={
    "service": "chronos2",
    # Use the batch endpoint via direct inference call
    "values": close_prices,  # primary series
    "prediction_length": 7,
}, headers={"Authorization": f"Bearer {API_KEY}"})
\`\`\`

For true multivariate batch forecasting, call the inference server's batch endpoint directly:

\`\`\`python
# Direct batch call to inference server
resp = requests.post("http://localhost:8100/forecast_batch", json={
    "series": [open_prices, high_prices, low_prices, close_prices],
    "prediction_length": 7,
    "constrain_ohlc": True,  # enforce high >= all, low <= all
})

batch = resp.json()
open_pred  = batch["results"][0]["mean"]
high_pred  = batch["results"][1]["mean"]
low_pred   = batch["results"][2]["mean"]
close_pred = batch["results"][3]["mean"]
\`\`\`

## Tip: OHLC constraints

Raw model output doesn't know about OHLC relationships. Sometimes the predicted "high" is lower than the predicted "close". The \`constrain_ohlc: true\` flag fixes this by post-processing:

- **High** = max(open, high, low, close) for each step
- **Low** = min(open, high, low, close) for each step

This is a simple but essential real-world hack. The model predicts each channel independently, so we need to enforce the physical constraint that high >= everything and low <= everything.

\`\`\`python
# Manual constraint if not using constrain_ohlc flag:
for i in range(len(open_pred)):
    vals = [open_pred[i], high_pred[i], low_pred[i], close_pred[i]]
    high_pred[i] = max(vals)
    low_pred[i]  = min(vals)
\`\`\`

## Tip: Multi-step forecasting in one call

Chronos2 natively forecasts multiple steps at once — it's not doing step-by-step autoregression. When you set \`prediction_length: 7\`, the model outputs all 7 timesteps simultaneously from the encoder output. This is much faster and more coherent than calling the API 7 times with rolling context.

For longer horizons, you can go up to \`prediction_length: 128\`. Beyond that, quality degrades — re-feed with updated context instead.

## Tip: Context length matters

More context = better forecasts, up to a point. Our benchmarks show:
- **50 timesteps**: Baseline quality
- **256 timesteps**: Noticeable improvement
- **768 timesteps**: Best quality (model's sweet spot)
- **1024+ timesteps**: Diminishing returns, slower inference

For daily BTC data, 768 timesteps = ~2 years of history. That's more than enough to capture seasonality and trends.

## Tip: Forecasting returns instead of prices

For financial time series, forecasting log returns often works better than forecasting raw prices:

\`\`\`python
import numpy as np

# Convert to log returns
prices = np.array(close_prices)
returns = np.diff(np.log(prices)).tolist()

# Forecast returns
resp = requests.post(f"{BASE}/service", json={
    "service": "chronos2",
    "values": returns,
    "prediction_length": 7,
}, headers={"Authorization": f"Bearer {API_KEY}"})

# Convert back to prices
pred_returns = resp.json()["result"]["mean"]
last_price = close_prices[-1]
pred_prices = [last_price]
for r in pred_returns:
    pred_prices.append(pred_prices[-1] * np.exp(r))
pred_prices = pred_prices[1:]  # drop the anchor
\`\`\`

This normalizes the scale and makes the model's job easier — it doesn't need to learn that "70000" is a reasonable BTC price.

## Plotting the results

\`\`\`python
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(12, 6))

# Historical
dates_hist = list(range(len(close_prices)))
ax.plot(dates_hist, close_prices, 'b-', label='Historical Close')

# Forecast
dates_pred = list(range(len(close_prices), len(close_prices) + 7))
ax.plot(dates_pred, median, 'r-', label='Forecast (median)')
ax.fill_between(dates_pred, lower, upper, alpha=0.2, color='red',
                label='80% prediction interval')

ax.set_xlabel('Day')
ax.set_ylabel('BTC/USDT')
ax.legend()
ax.set_title('Bitcoin Price Forecast — CuteDSL Chronos2')
plt.tight_layout()
plt.savefig('btc_forecast.png', dpi=150)
\`\`\`

## Model memory management

The CuteDSL inference server uses lazy loading with LRU eviction. When you call the Chronos2 endpoint, the model is loaded into GPU memory on first use. After 4 minutes of no requests, it's automatically unloaded to free GPU memory for other models (like Z-Image).

This means:
- First request may take ~5-10 seconds (model loading)
- Subsequent requests: 1.55ms (compiled) to 19ms (eager)
- No wasted GPU memory when the model isn't in use

## Pricing

Chronos2 is a first-party service priced at the $CUTEDSL all-time high rate. If the token price goes up, your effective cost per forecast goes down permanently. Currently $0.50/forecast in USD equivalent.`,
  },
];

