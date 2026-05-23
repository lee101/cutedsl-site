"""CuteDSL Inference Server.

Serves CuteDSL-accelerated models (zimage, chronos2) directly and proxies
TTS, STT, captioning, and gemma4 requests to a text-generator.io backend.

Optimized for RTX 5090 with NVFP4 quantization support.
"""

import asyncio
import base64
import io
import json
import logging
import os
import threading
import time
import uuid
import hashlib
import contextlib
import traceback
from contextlib import asynccontextmanager
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse

import httpx
import torch
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from PIL import Image
from pydantic import BaseModel

from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from image_quality import bumpy_metrics, compact_prompt, detect_too_bumpy, retry_prompt
from training_store import load_jobs, save_job, update_job, upload_training_artifacts
from runpod_lora_manager import refresh_runpod_status, runpod_enabled, start_runpod_training

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("cutedsl-inference")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

IMAGE_API_SECRET = os.getenv("IMAGE_API_SECRET", "")
ERROR_LOG_PATH = os.getenv("ERROR_LOG_PATH", "/nvme0n1-disk/tmp/cutedsl-inference-errors.jsonl")

DEVICE = os.getenv("DEVICE", "cuda")
DTYPE_STR = os.getenv("DTYPE", "bfloat16")
DTYPE_MAP = {
    "bfloat16": torch.bfloat16,
    "float16": torch.float16,
    "float32": torch.float32,
    "float8_e4m3fn": getattr(torch, "float8_e4m3fn", torch.bfloat16),
}
DTYPE = DTYPE_MAP.get(DTYPE_STR, torch.bfloat16)


def _chronos_device_dtype() -> tuple[str, torch.dtype]:
    """Chronos2 is small enough to fall back to CPU when local CUDA is unhealthy."""
    if DEVICE.startswith("cuda"):
        try:
            if torch.cuda.is_available():
                return DEVICE, DTYPE
        except Exception:
            pass
        logger.warning("Chronos2 CUDA unavailable; falling back to CPU float32")
        return "cpu", torch.float32
    return DEVICE, DTYPE

# NVFP4 quantization (RTX 5090 Blackwell) - uses torchao NVFP4InferenceConfig
# Block size is fixed at 16 in the NVFP4 spec (float4_e2m1fn_x2 + float8_e4m3fn scales)
ENABLE_NVFP4 = os.getenv("ENABLE_NVFP4", "0") == "1"

# AITune: ahead-of-time TensorRT optimization for text_encoder + VAE.
# Run inference/aitune_experiment.py --tune first to generate the engine file.
# Only applies to the vanilla (non-CuteZImage) pipeline path.
AITUNE_ENGINES_PATH = os.getenv("AITUNE_ENGINES_PATH", "")

# Model paths
ZIMAGE_MODEL_PATH = os.getenv("ZIMAGE_MODEL_PATH", "Tongyi-MAI/Z-Image-Turbo")
CHRONOS_MODEL_PATH = os.getenv("CHRONOS_MODEL_PATH", "amazon/chronos-bolt-base")
ZIMAGE_COMPILE_MODE = os.getenv("ZIMAGE_COMPILE_MODE", "reduce-overhead") or None
CHRONOS_COMPILE_MODE = os.getenv("CHRONOS_COMPILE_MODE", "reduce-overhead") or None

# Text-generator.io backend for TTS, STT, captioning, gemma4
TG_BACKEND_URL = os.getenv("TG_BACKEND_URL", "http://localhost:9080")
TG_API_KEY = os.getenv("TG_API_KEY", "")

# Which models to load on startup
LOAD_ZIMAGE = os.getenv("LOAD_ZIMAGE", "1") == "1"
LOAD_CHRONOS = os.getenv("LOAD_CHRONOS", "1") == "1"
ZIMAGE_USE_CUTE = os.getenv("ZIMAGE_USE_CUTE", "1") == "1"

# Inference defaults
ZIMAGE_DEFAULT_STEPS = int(os.getenv("ZIMAGE_DEFAULT_STEPS", "4"))
ZIMAGE_DEFAULT_GUIDANCE = float(os.getenv("ZIMAGE_DEFAULT_GUIDANCE", "0.0"))
ZIMAGE_DEFAULT_WIDTH = int(os.getenv("ZIMAGE_DEFAULT_WIDTH", "1024"))
ZIMAGE_DEFAULT_HEIGHT = int(os.getenv("ZIMAGE_DEFAULT_HEIGHT", "1024"))
LATENT_TELEPORT_ENABLED = os.getenv("LATENT_TELEPORT_ENABLED", "0") == "1"
LATENT_TELEPORT_CACHE_DIR = os.getenv("LATENT_TELEPORT_CACHE_DIR", "/nvme0n1-disk/tmp/latentteleport-cache")
LATENT_TELEPORT_START_STEP = int(os.getenv("LATENT_TELEPORT_START_STEP", "2"))

# ---------------------------------------------------------------------------
# Model memory manager — lazy load, LRU eviction, idle unload
# ---------------------------------------------------------------------------

MODEL_IDLE_TIMEOUT = int(os.getenv("MODEL_IDLE_TIMEOUT", "3600"))  # 1 hour default for batch generation
BATCH_WINDOW_MS = int(os.getenv("BATCH_WINDOW_MS", "50"))  # ms to wait for batching

zimage_pipeline = None
chronos_pipeline = None
tg_client: httpx.AsyncClient = None

# GPU inference gate — limits concurrent GPU work and lets public requests
# jump ahead of background dataset generation between inference calls.
MAX_GPU_CONCURRENT = int(os.getenv("MAX_GPU_CONCURRENT", "2"))
LOW_PRIORITY_IDLE_SECONDS = float(os.getenv("LOW_PRIORITY_IDLE_SECONDS", "5.0"))
gpu_semaphore = None

# LoRA search engine (lazy init)
lora_engine = None
latent_teleport_cache = None


class PriorityGPUSemaphore:
    def __init__(self, limit: int):
        self.limit = max(1, limit)
        self.active = 0
        self.active_high = 0
        self.active_low = 0
        self.waiting_high = 0
        self.waiting_low = 0
        self.last_high_priority_at = 0.0
        self._condition = asyncio.Condition()

    def high_priority(self):
        return _PriorityGPUReservation(self, high_priority=True)

    def low_priority(self):
        return _PriorityGPUReservation(self, high_priority=False)

    async def __aenter__(self):
        await self._acquire(high_priority=True)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self._release(high_priority=True)

    async def _acquire(self, high_priority: bool):
        async with self._condition:
            if high_priority:
                self.waiting_high += 1
                self.last_high_priority_at = time.time()
            else:
                self.waiting_low += 1
            try:
                while True:
                    idle_remaining = 0.0
                    if not high_priority and LOW_PRIORITY_IDLE_SECONDS > 0:
                        idle_remaining = LOW_PRIORITY_IDLE_SECONDS - (time.time() - self.last_high_priority_at)
                    can_start = (
                        self.active < self.limit
                        and (high_priority or self.waiting_high == 0)
                        and (high_priority or idle_remaining <= 0)
                    )
                    if can_start:
                        break
                    if idle_remaining > 0 and not high_priority and self.active < self.limit and self.waiting_high == 0:
                        try:
                            await asyncio.wait_for(self._condition.wait(), timeout=idle_remaining)
                        except asyncio.TimeoutError:
                            pass
                    else:
                        await self._condition.wait()
                self.active += 1
                if high_priority:
                    self.active_high += 1
                else:
                    self.active_low += 1
            finally:
                if high_priority:
                    self.waiting_high = max(0, self.waiting_high - 1)
                else:
                    self.waiting_low = max(0, self.waiting_low - 1)

    async def _release(self, high_priority: bool):
        async with self._condition:
            self.active = max(0, self.active - 1)
            if high_priority:
                self.active_high = max(0, self.active_high - 1)
                self.last_high_priority_at = time.time()
            else:
                self.active_low = max(0, self.active_low - 1)
            self._condition.notify_all()

    def snapshot(self) -> dict:
        return {
            "limit": self.limit,
            "active": self.active,
            "active_high": self.active_high,
            "active_low": self.active_low,
            "waiting_high": self.waiting_high,
            "waiting_low": self.waiting_low,
            "low_priority_idle_seconds": LOW_PRIORITY_IDLE_SECONDS,
            "seconds_since_high_priority": round(time.time() - self.last_high_priority_at, 3) if self.last_high_priority_at else None,
        }


class _PriorityGPUReservation:
    def __init__(self, gate: PriorityGPUSemaphore, high_priority: bool):
        self.gate = gate
        self.high_priority = high_priority

    async def __aenter__(self):
        await self.gate._acquire(self.high_priority)
        return self.gate

    async def __aexit__(self, exc_type, exc, tb):
        await self.gate._release(self.high_priority)


def gpu_slot(low_priority: bool = False):
    if gpu_semaphore is None:
        raise RuntimeError("GPU semaphore not initialized")
    return gpu_semaphore.low_priority() if low_priority else gpu_semaphore.high_priority()


class ModelManager:
    """LRU model manager with idle timeout and lazy loading.

    Only keeps the most recently used model in GPU memory. If no requests
    arrive for MODEL_IDLE_TIMEOUT seconds, all models are unloaded.
    Requests are batched within a BATCH_WINDOW_MS window to avoid thrashing.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._last_access: dict[str, float] = {}  # model -> last use time
        self._loaded: set[str] = set()
        self._in_use: dict[str, int] = {}  # model -> active request refcount
        self._idle_timer: threading.Timer | None = None
        self._batch_queues: dict[str, list] = {}  # model -> [(request, future)]

    @contextlib.contextmanager
    def use(self, model_name: str):
        """Context manager: ensure model is loaded and pin it for the duration."""
        self.ensure_loaded(model_name)
        with self._lock:
            self._in_use[model_name] = self._in_use.get(model_name, 0) + 1
        try:
            yield
        finally:
            with self._lock:
                self._in_use[model_name] = max(0, self._in_use.get(model_name, 0) - 1)
                self._last_access[model_name] = time.time()
            self._reset_idle_timer()

    def touch(self, model_name: str):
        """Mark model as recently used and reset idle timer."""
        self._last_access[model_name] = time.time()
        self._reset_idle_timer()

    def _reset_idle_timer(self):
        if self._idle_timer:
            self._idle_timer.cancel()
        self._idle_timer = threading.Timer(MODEL_IDLE_TIMEOUT, self._unload_idle)
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def _unload_idle(self):
        """Unload all models after idle timeout."""
        now = time.time()
        with self._lock:
            stale = [m for m in list(self._loaded)
                     if self._in_use.get(m, 0) == 0
                     and now - self._last_access.get(m, 0) >= MODEL_IDLE_TIMEOUT - 0.5]
            # If anything is still in-use, reschedule a check for later
            if any(self._in_use.get(m, 0) > 0 for m in self._loaded):
                if self._idle_timer:
                    self._idle_timer.cancel()
                self._idle_timer = threading.Timer(MODEL_IDLE_TIMEOUT, self._unload_idle)
                self._idle_timer.daemon = True
                self._idle_timer.start()
            for model_name in stale:
                logger.info("Unloading idle model: %s (idle %.0fs)",
                            model_name, now - self._last_access.get(model_name, 0))
                self._drop_locked(model_name)
            if not self._loaded and torch.cuda.is_available():
                import gc
                gc.collect()
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
                # Release the cuBLAS workspace pool — the caching allocator
                # otherwise pins ~600 MB-1 GB across the lifetime of the proc.
                try:
                    torch._C._cuda_clearCublasWorkspaces()
                except Exception:
                    pass
                free, total = torch.cuda.mem_get_info()
                logger.info("All models unloaded → %.2f GB free / %.2f GB total",
                            free / 1e9, total / 1e9)

    def _drop_locked(self, model_name: str):
        """Caller must hold self._lock."""
        global zimage_pipeline, chronos_pipeline
        if model_name == "zimage":
            zimage_pipeline = None
            # Active LoRA metadata must be cleared with the pipeline. We avoid
            # caching full transformer weights because that doubles GPU memory.
            _active_lora_cache.clear()
        elif model_name == "chronos2":
            chronos_pipeline = None
        self._loaded.discard(model_name)
        self._last_access.pop(model_name, None)

    def force_unload(self, model_name: str | None = None) -> list[str]:
        """Immediately unload a model (or all) and free GPU cache."""
        global nsfw_classifier
        import gc
        with self._lock:
            targets = [model_name] if model_name else list(self._loaded)
            dropped = []
            for m in targets:
                if self._in_use.get(m, 0) > 0:
                    logger.info("Skip force-unload of %s: in_use=%d", m, self._in_use[m])
                    continue
                if m in self._loaded:
                    logger.info("Force unloading model: %s", m)
                    self._drop_locked(m)
                    dropped.append(m)
            if not self._loaded and self._idle_timer:
                self._idle_timer.cancel()
                self._idle_timer = None
        if model_name is None:
            nsfw_classifier = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
        return dropped

    def ensure_loaded(self, model_name: str):
        """Ensure model is loaded (lazy load if needed). Evicts other models if needed."""
        global zimage_pipeline, chronos_pipeline
        with self._lock:
            if model_name in self._loaded:
                self.touch(model_name)
                return

            # Evict least recently used model to make room
            if self._loaded:
                oldest = min(self._loaded, key=lambda m: self._last_access.get(m, 0))
                if oldest != model_name:
                    logger.info("Evicting %s to load %s", oldest, model_name)
                    if oldest == "zimage":
                        zimage_pipeline = None
                    elif oldest == "chronos2":
                        chronos_pipeline = None
                    self._loaded.discard(oldest)
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()

            # Load requested model
            logger.info("Loading model: %s", model_name)
            if model_name == "zimage":
                _load_zimage()
                _init_lora_engine()
            elif model_name == "chronos2":
                _load_chronos()

            self._loaded.add(model_name)
            self.touch(model_name)

    def is_loaded(self, model_name: str) -> bool:
        return model_name in self._loaded


model_manager = ModelManager()

# NSFW classifier (lazy loaded to save GPU memory)
nsfw_classifier = None
nsfw_lock = None


def _apply_nvfp4_quantization(model: torch.nn.Module) -> torch.nn.Module:
    """Apply NVFP4 quantization for RTX 5090 Blackwell architecture.

    NVFP4 uses 4-bit floating point with per-block scaling, giving ~2x
    memory reduction and faster matmuls on SM100+ GPUs.

    Uses torchao's NVFP4InferenceConfig (prototype.mx_formats) with the
    DYNAMIC mm_config for hardware-accelerated FP4 matmuls.
    """
    if not ENABLE_NVFP4:
        return model

    try:
        from torchao.quantization import quantize_
        from torchao.prototype.mx_formats import NVFP4WeightOnlyConfig

        logger.info("Applying NVFP4 weight-only quantization...")
        quantize_(model, NVFP4WeightOnlyConfig())
        logger.info("NVFP4 quantization applied successfully")
    except ImportError:
        logger.warning(
            "torchao not available for NVFP4 quantization. "
            "Install with: pip install torchao"
        )
    except Exception as e:
        logger.warning("NVFP4 quantization failed (may not be supported on this GPU): %s", e)

    return model


def _optimize_for_inference():
    """Apply global PyTorch inference optimizations for 5090."""
    if torch.cuda.is_available():
        # Enable TF32 for faster matmuls on Ampere+
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
        # Enable flash SDP for attention
        torch.backends.cuda.enable_flash_sdp(True)
        torch.backends.cuda.enable_mem_efficient_sdp(True)
        # CUDA graphs friendly settings
        torch.backends.cudnn.benchmark = True

        gpu_name = torch.cuda.get_device_name(0)
        gpu_mem = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        logger.info("GPU: %s (%.1f GB)", gpu_name, gpu_mem)


def _load_zimage():
    """Load and optimize the Z-Image pipeline.

    Memory layout (bf16): transformer 12.3 GB + text_encoder (Qwen3) 8.0 GB
    + vae 0.2 GB = 20.5 GB. To hit a 10 GB VRAM budget we apply two techniques:

    1. NVFP4 weight-only quantization (ENABLE_NVFP4=1) shrinks the transformer
       and text encoder ~4× → ~5 GB total weights.
    2. Sequential CPU offload (ZIMAGE_CPU_OFFLOAD=1) keeps only the active
       component on GPU at a time, so peak is max(text_encoder, transformer)
       not their sum.

    NVFP4 only swaps stock nn.Linear modules, so when ENABLE_NVFP4=1 we use
    the vanilla diffusers pipeline (use_cute=False). The CuteZImage Triton
    kernels expect plain Linear weights and won't accept NVFP4 tensor
    subclasses. The trained PEFT LoRAs are saved against this same vanilla
    base so they load cleanly on top.
    """
    global zimage_pipeline

    import sys
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "cutedsl")))

    logger.info(
        "Loading Z-Image from %s (NVFP4=%s, CuteZImage=%s)...",
        ZIMAGE_MODEL_PATH,
        ENABLE_NVFP4,
        ZIMAGE_USE_CUTE,
    )
    t0 = time.time()

    enable_offload = os.getenv("ZIMAGE_CPU_OFFLOAD", "1") == "1"
    skip_warmup = os.getenv("ZIMAGE_SKIP_WARMUP", "0") == "1" or ENABLE_NVFP4

    if ENABLE_NVFP4 or not ZIMAGE_USE_CUTE:
        # Vanilla diffusers path. This is required for NVFP4 because torchao
        # swaps stock nn.Linear modules; it is also useful as a production
        # fallback when CuteZImage conversion/compilation is being benchmarked.
        from diffusers import ZImagePipeline, ZImageImg2ImgPipeline
        text2img_pipe = ZImagePipeline.from_pretrained(
            ZIMAGE_MODEL_PATH,
            torch_dtype=DTYPE,
        )

        if ENABLE_NVFP4:
            # Quantize the heavyweights BEFORE moving to GPU so peak load memory
            # stays low. NVFP4 weight-only swaps the .weight tensor in-place.
            if hasattr(text2img_pipe, "transformer") and text2img_pipe.transformer is not None:
                logger.info("NVFP4: quantizing transformer (%.1f GB → ~%.1f GB)",
                            sum(p.numel() for p in text2img_pipe.transformer.parameters()) * 2 / 1e9,
                            sum(p.numel() for p in text2img_pipe.transformer.parameters()) * 0.5 / 1e9)
                _apply_nvfp4_quantization(text2img_pipe.transformer)
            if hasattr(text2img_pipe, "text_encoder") and text2img_pipe.text_encoder is not None:
                logger.info("NVFP4: quantizing text encoder (Qwen3, %.1f GB → ~%.1f GB)",
                            sum(p.numel() for p in text2img_pipe.text_encoder.parameters()) * 2 / 1e9,
                            sum(p.numel() for p in text2img_pipe.text_encoder.parameters()) * 0.5 / 1e9)
                _apply_nvfp4_quantization(text2img_pipe.text_encoder)

        if enable_offload and not ENABLE_NVFP4 and hasattr(text2img_pipe, "enable_model_cpu_offload"):
            text2img_pipe.enable_model_cpu_offload()
        else:
            # NVFP4 already shrinks weights substantially, and no-offload is
            # also the low-latency path on 24 GB+ GPUs for 1024px generation.
            # Accelerate's CPU offload breaks NVFP4 tensor subclasses, so keep
            # those components resident on the target device.
            try:
                for comp_name in ("transformer", "vae", "text_encoder"):
                    comp = getattr(text2img_pipe, comp_name, None)
                    if comp is not None:
                        comp.to(DEVICE)
            except Exception as e:
                logger.warning("Z-Image component .to(%s) failed: %s", DEVICE, e)

        img2img_pipe = ZImageImg2ImgPipeline(**text2img_pipe.components)

        # Defensive: wrap scheduler.step so sigma_idx never overruns. The
        # vanilla FlowMatchEulerDiscreteScheduler can race its _step_index
        # past sigmas length under some Z-Image timestep configurations,
        # producing IndexError. Clamping is harmless because the final
        # iteration uses sigmas[-1] anyway via the existing min() at line 502.
        sched = text2img_pipe.scheduler
        _orig_step = sched.step
        def _safe_step(self_sched, *args, **kwargs):  # noqa: ANN001
            if self_sched._step_index is not None and self_sched._step_index >= len(self_sched.sigmas):
                self_sched._step_index = len(self_sched.sigmas) - 1
            return _orig_step(*args, **kwargs)
        import types
        sched.step = types.MethodType(_safe_step, sched)
    else:
        # Default fast path: cute-accelerated kernels
        from cutezimage.pipeline import get_zimage_pipelines
        text2img_pipe, img2img_pipe = get_zimage_pipelines(
            model_path=ZIMAGE_MODEL_PATH,
            torch_dtype=DTYPE,
            use_cute=True,
            compile_mode=ZIMAGE_COMPILE_MODE,
            device=DEVICE,
            enable_cpu_offload=enable_offload,
        )

    zimage_pipeline = (text2img_pipe, img2img_pipe)
    logger.info("Z-Image loaded in %.1fs", time.time() - t0)

    # Optional: load AITune TRT engines for text_encoder + VAE.
    # Only applies to vanilla (non-CuteZImage) paths since CuteZImage already
    # uses fused Triton kernels for the transformer.  LoRA-safe: LoRAs only
    # modify transformer weights, which AITune does not touch.
    if AITUNE_ENGINES_PATH and not ENABLE_NVFP4:
        try:
            import aitune.torch as ait
            logger.info("Loading AITune engines from %s...", AITUNE_ENGINES_PATH)
            ait.load(text2img_pipe, AITUNE_ENGINES_PATH)
            logger.info("AITune engines loaded (text_encoder + VAE via TRT)")
        except Exception as e:
            logger.warning("AITune engine load failed (non-fatal, using PyTorch): %s", e)

    if skip_warmup:
        logger.info("Z-Image warmup skipped (NVFP4 or ZIMAGE_SKIP_WARMUP=1)")
        return

    logger.info("Z-Image warmup...")
    try:
        _ = text2img_pipe(
            prompt="warmup",
            width=512, height=512,
            num_inference_steps=1,
            guidance_scale=0.0,
            generator=torch.Generator(device=DEVICE).manual_seed(0),
        )
        logger.info("Z-Image warmup complete")
    except Exception as e:
        logger.warning("Z-Image warmup failed (non-fatal): %s", e)


def _load_chronos():
    """Load and optimize the Chronos2 pipeline."""
    global chronos_pipeline

    import sys
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "cutedsl")))

    from cutechronos.pipeline import CuteChronos2Pipeline

    logger.info("Loading Chronos2 from %s...", CHRONOS_MODEL_PATH)
    t0 = time.time()
    chronos_device, chronos_dtype = _chronos_device_dtype()

    chronos_pipeline = CuteChronos2Pipeline.from_pretrained(
        CHRONOS_MODEL_PATH,
        device=chronos_device,
        dtype=chronos_dtype,
        use_cute=True,
        compile_mode=CHRONOS_COMPILE_MODE if chronos_device.startswith("cuda") else None,
    )

    # Apply NVFP4 to model weights
    if ENABLE_NVFP4:
        _apply_nvfp4_quantization(chronos_pipeline.model)

    logger.info("Chronos2 loaded in %.1fs", time.time() - t0)

    # Warmup
    logger.info("Chronos2 warmup...")
    try:
        dummy = torch.randn(1, 64, device=chronos_device)
        chronos_pipeline.predict(dummy, prediction_length=16)
        logger.info("Chronos2 warmup complete")
    except Exception as e:
        logger.warning("Chronos2 warmup failed (non-fatal): %s", e)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global tg_client, gpu_semaphore
    _optimize_for_inference()

    gpu_semaphore = PriorityGPUSemaphore(MAX_GPU_CONCURRENT)

    tg_client = httpx.AsyncClient(
        base_url=TG_BACKEND_URL,
        timeout=httpx.Timeout(180.0, connect=10.0),
        headers={"secret": TG_API_KEY} if TG_API_KEY else {},
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
    )

    # Lazy load models on first request via model_manager.
    # Optionally warm them in a background executor so the HTTP socket comes up
    # immediately after restarts instead of making nginx wait on checkpoint load.
    if os.getenv("PRELOAD_MODELS", "0") == "1":
        loop = asyncio.get_running_loop()
        if LOAD_ZIMAGE:
            loop.run_in_executor(None, model_manager.ensure_loaded, "zimage")
        if LOAD_CHRONOS:
            loop.run_in_executor(None, model_manager.ensure_loaded, "chronos2")

    logger.info("CuteDSL Inference Server ready")
    yield

    await tg_client.aclose()
    logger.info("Shutdown complete")


app = FastAPI(title="CuteDSL Inference Server", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=1000)


def _sanitize_query(query_string: bytes) -> str:
    pairs = []
    for key, value in parse_qsl(query_string.decode("utf-8", errors="replace"), keep_blank_values=True):
        if key.lower() in {"secret", "api_key", "key", "token"}:
            value = "<redacted>"
        pairs.append((key, value))
    return urlencode(pairs)


def _request_prompt_info(request: Request) -> dict:
    prompt = request.query_params.get("prompt", "")
    return {
        "prompt_len": len(prompt),
        "prompt_words": len(prompt.split()) if prompt else 0,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16] if prompt else "",
    }


def _write_error_event(event: dict):
    try:
        os.makedirs(os.path.dirname(ERROR_LOG_PATH), exist_ok=True)
        with open(ERROR_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, sort_keys=True, default=str) + "\n")
    except Exception as e:
        logger.warning("failed to write error event: %s", e)


def _log_request_error(request: Request, exc: Exception, status_code: int, detail: str | None = None):
    request_id = getattr(request.state, "request_id", "")
    event = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "request_id": request_id,
        "status_code": status_code,
        "method": request.method,
        "path": request.url.path,
        "query": _sanitize_query(request.scope.get("query_string", b"")),
        "client": request.client.host if request.client else "",
        "error_type": type(exc).__name__,
        "error": detail or str(exc),
        **_request_prompt_info(request),
    }
    if status_code >= 500:
        event["traceback"] = traceback.format_exception(type(exc), exc, exc.__traceback__)
    _write_error_event(event)
    logger.error(
        "request failed request_id=%s status=%d path=%s prompt_len=%s error=%s: %s",
        request_id,
        status_code,
        request.url.path,
        event["prompt_len"],
        type(exc).__name__,
        detail or str(exc),
        exc_info=status_code >= 500,
    )


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request.state.request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    response = await call_next(request)
    response.headers["x-request-id"] = request.state.request_id
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code >= 500:
        _log_request_error(request, exc, exc.status_code, detail=str(exc.detail))
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "request_id": getattr(request.state, "request_id", "")},
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    _log_request_error(request, exc, 500)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error", "request_id": getattr(request.state, "request_id", "")},
    )


def _check_secret(secret: str = ""):
    if IMAGE_API_SECRET and secret != IMAGE_API_SECRET:
        raise HTTPException(403, "invalid secret")


def _require_http_url(value: str, field_name: str = "url"):
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(400, f"{field_name} must be an http(s) URL")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.post("/admin/unload")
def admin_unload(model: str | None = None):
    """Force-unload a model (or all) and free GPU memory immediately."""
    before = 0
    after = 0
    if torch.cuda.is_available():
        before = torch.cuda.memory_reserved() // (1024 * 1024)
    dropped = model_manager.force_unload(model)
    if torch.cuda.is_available():
        after = torch.cuda.memory_reserved() // (1024 * 1024)
    return {
        "dropped": dropped,
        "loaded": sorted(model_manager._loaded),
        "reserved_mib_before": before,
        "reserved_mib_after": after,
    }


@app.get("/health")
@app.get("/healthz")
def health():
    gpu_queue = gpu_semaphore.snapshot() if gpu_semaphore is not None else {}
    return {
        "status": "ok",
        "models": {
            "zimage": model_manager.is_loaded("zimage"),
            "chronos2": model_manager.is_loaded("chronos2"),
            "zimage_enabled": LOAD_ZIMAGE,
            "chronos2_enabled": LOAD_CHRONOS,
            "nsfw": nsfw_classifier is not None,
        },
        "gpu_queue": gpu_queue,
        "nvfp4": ENABLE_NVFP4,
        "zimage_use_cute": ZIMAGE_USE_CUTE,
        "latent_teleport": {
            "enabled": LATENT_TELEPORT_ENABLED,
            "cache_dir": LATENT_TELEPORT_CACHE_DIR,
            "start_step": LATENT_TELEPORT_START_STEP,
        },
        "device": DEVICE,
        "dtype": DTYPE_STR,
    }


# ---------------------------------------------------------------------------
# LoRA search engine
# ---------------------------------------------------------------------------

def _init_lora_engine():
    global lora_engine
    try:
        from lora_search import get_lora_search_engine
        lora_engine = get_lora_search_engine()
        logger.info("LoRA search engine initialized (%d styles)",
                     len(lora_engine._keyword_map))
    except Exception as e:
        logger.warning("LoRA search engine init failed (non-fatal): %s", e)


# ---------------------------------------------------------------------------
# NSFW Detection (lazy loaded — not kept in GPU memory permanently)
# ---------------------------------------------------------------------------

def _load_nsfw_classifier():
    """Load NSFW classifier on demand. Unloads after idle timeout."""
    global nsfw_classifier, nsfw_lock
    import threading

    if nsfw_lock is None:
        nsfw_lock = threading.Lock()

    with nsfw_lock:
        if nsfw_classifier is not None:
            return nsfw_classifier

        from transformers import pipeline as hf_pipeline

        logger.info("Loading NSFW classifier (Falconsai/nsfw_image_detection)...")
        t0 = time.time()
        nsfw_classifier = hf_pipeline(
            "image-classification",
            model="Falconsai/nsfw_image_detection",
            device=DEVICE if torch.cuda.is_available() else "cpu",
        )
        # Compile for faster inference
        try:
            nsfw_classifier.model = torch.compile(nsfw_classifier.model, mode="reduce-overhead")
            logger.info("NSFW classifier compiled with torch.compile")
        except Exception as e:
            logger.warning("NSFW classifier torch.compile failed (non-fatal): %s", e)

        logger.info("NSFW classifier loaded in %.1fs", time.time() - t0)
        return nsfw_classifier


def _unload_nsfw_classifier():
    """Free NSFW classifier from GPU memory."""
    global nsfw_classifier
    if nsfw_classifier is not None:
        del nsfw_classifier
        nsfw_classifier = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("NSFW classifier unloaded (GPU memory freed)")


def _classify_nsfw_sync(image) -> dict:
    """Classify a PIL image as NSFW or not."""
    classifier = _load_nsfw_classifier()
    results = classifier(image)
    # Returns list of [{"label": "nsfw"/"normal", "score": 0.99}, ...]
    nsfw_score = 0.0
    normal_score = 0.0
    for r in results:
        if r["label"] == "nsfw":
            nsfw_score = r["score"]
        elif r["label"] == "normal":
            normal_score = r["score"]
    return {
        "is_nsfw": nsfw_score > 0.5,
        "nsfw_score": round(nsfw_score, 4),
        "normal_score": round(normal_score, 4),
    }


class NSFWRequest(BaseModel):
    image_url: Optional[str] = None
    image_base64: Optional[str] = None
    unload_after: bool = True  # free GPU memory after classification


@app.post("/nsfw_detect")
async def nsfw_detect(req: NSFWRequest):
    """Classify an image as NSFW or not. Model loads on demand and unloads after."""
    from PIL import Image as PILImage

    if req.image_base64:
        img_bytes = base64.b64decode(req.image_base64)
        image = PILImage.open(io.BytesIO(img_bytes)).convert("RGB")
    elif req.image_url:
        import httpx as hx
        async with hx.AsyncClient() as client:
            resp = await client.get(req.image_url, timeout=30)
            resp.raise_for_status()
        image = PILImage.open(io.BytesIO(resp.content)).convert("RGB")
    else:
        raise HTTPException(400, "image_url or image_base64 required")

    async with gpu_semaphore:
        result = await asyncio.get_event_loop().run_in_executor(
            None, _classify_nsfw_sync, image
        )

    if req.unload_after:
        _unload_nsfw_classifier()

    return result


@app.post("/nsfw_detect_file")
async def nsfw_detect_file(
    image_file: UploadFile = File(...),
    unload_after: bool = True,
):
    """Classify an uploaded image as NSFW or not."""
    from PIL import Image as PILImage

    content = await image_file.read()
    image = PILImage.open(io.BytesIO(content)).convert("RGB")

    async with gpu_semaphore:
        result = await asyncio.get_event_loop().run_in_executor(
            None, _classify_nsfw_sync, image
        )

    if unload_after:
        _unload_nsfw_classifier()

    return result


@app.post("/nsfw_unload")
def nsfw_unload():
    """Explicitly unload the NSFW classifier to free GPU memory."""
    _unload_nsfw_classifier()
    return {"status": "unloaded"}


# ---------------------------------------------------------------------------
# Z-Image (text-to-image) with auto LoRA selection
# ---------------------------------------------------------------------------

class ZImageRequest(BaseModel):
    prompt: str
    width: int = ZIMAGE_DEFAULT_WIDTH
    height: int = ZIMAGE_DEFAULT_HEIGHT
    seed: int = 0
    num_inference_steps: int = ZIMAGE_DEFAULT_STEPS
    guidance_scale: float = ZIMAGE_DEFAULT_GUIDANCE
    lora_id: Optional[str] = None
    auto_lora: bool = True
    lora_scale: float = 1.0
    low_priority: bool = False


_lora_cache_dir = os.path.join(os.path.dirname(__file__), ".lora_cache")


def _download_lora(url: str) -> str:
    """Download LoRA weights to local cache, return local path."""
    os.makedirs(_lora_cache_dir, exist_ok=True)
    from urllib.parse import unquote
    filename = unquote(url.split("/")[-1])
    local_path = os.path.join(_lora_cache_dir, filename)
    if os.path.exists(local_path):
        return local_path
    import urllib.request
    logger.info("downloading LoRA: %s", url)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp:
        with open(local_path, "wb") as f:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
    logger.info("cached LoRA at %s (%d bytes)", local_path, os.path.getsize(local_path))
    return local_path


def _apply_lora_weights_direct(transformer, lora_path: str, scale: float = 1.0):
    """Apply Z-Image LoRA weights directly to transformer parameters.

    Z-Image LoRAs use keys like: diffusion_model.layers.N.attention.to_q.lora_A/B.weight
    Our CuteZImageTransformer uses: main_blocks[N].attn.q_proj etc.
    """
    from safetensors import safe_open

    key_map = {
        "attention.to_q": "q_proj",
        "attention.to_k": "k_proj",
        "attention.to_v": "v_proj",
        "attention.to_out.0": "o_proj",
        "feed_forward.w1": "feed_forward.w1",
        "feed_forward.w2": "feed_forward.w2",
        "feed_forward.w3": "feed_forward.w3",
        "adaLN_modulation.0": "adaLN_modulation.1",
    }

    with safe_open(lora_path, framework="pt", device="cpu") as sf:
        applied = 0
        for key in sf.keys():
            if not key.startswith("diffusion_model.layers."):
                continue
            parts = key.replace("diffusion_model.layers.", "").split(".")
            layer_idx = int(parts[0])
            rest = ".".join(parts[1:])

            is_lora_a = rest.endswith(".lora_A.weight")
            is_lora_b = rest.endswith(".lora_B.weight")
            if not (is_lora_a or is_lora_b):
                continue

            module_key = rest.replace(".lora_A.weight", "").replace(".lora_B.weight", "")
            mapped = key_map.get(module_key)
            if not mapped:
                continue

            if layer_idx >= len(transformer.layers):
                continue

            block = transformer.layers[layer_idx]
            param_parts = mapped.split(".")
            target = block
            for p in param_parts:
                target = getattr(target, p, None)
                if target is None:
                    break
            if target is None:
                continue

            target_device = target.weight.device
            target_dtype = target.weight.dtype
            with torch.no_grad():
                if is_lora_b:
                    lora_a_key = key.replace("lora_B", "lora_A")
                    lora_weight = sf.get_tensor(key).to(device=target_device, dtype=target_dtype)
                    lora_a = sf.get_tensor(lora_a_key).to(device=target_device, dtype=target_dtype)
                    delta = (lora_weight @ lora_a) * scale
                    target.weight.add_(delta.to(device=target_device, dtype=target_dtype))
                    applied += 1

    logger.info("applied %d LoRA layers from %s (scale=%.2f)", applied, os.path.basename(lora_path), scale)
    return applied > 0


_active_lora_cache: dict[int, list[tuple[str, float]]] = {}


def _restore_original_weights(transformer):
    """Undo directly-applied LoRA weights after generation."""
    cache_key = id(transformer)
    active = _active_lora_cache.pop(cache_key, [])
    if not active:
        return
    for lora_path, scale in reversed(active):
        try:
            _apply_lora_weights_direct(transformer, lora_path, scale=-scale)
        except Exception as e:
            logger.warning("LoRA restore failed for %s: %s", os.path.basename(lora_path), e)


def _detect_lora_format(path: str) -> str:
    """Detect if LoRA is zimage-native or sdxl-kohya format."""
    from safetensors import safe_open
    with safe_open(path, framework="pt") as sf:
        keys = list(sf.keys())[:128]
        if any(k.startswith("diffusion_model") for k in keys):
            return "zimage-native"
        return "sdxl-kohya"


def _load_lora_onto_pipe(pipe, lora_url: str, lora_scale: float = 1.0):
    """Load Z-Image LoRA weights onto pipeline transformer."""
    if lora_url.startswith("http"):
        local_path = _download_lora(lora_url)
    else:
        local_path = lora_url

    fmt = _detect_lora_format(local_path)

    if fmt == "sdxl-kohya":
        # Use diffusers native loader for SDXL/Kohya format LoRAs
        logger.info("loading sdxl-kohya format LoRA: %s", os.path.basename(local_path))
        return

    transformer = pipe.transformer
    _apply_lora_weights_direct(transformer, local_path, scale=lora_scale)
    _active_lora_cache.setdefault(id(transformer), []).append((local_path, lora_scale))


def _effective_lora_scale(lora, requested_scale: float | None = None) -> float:
    if requested_scale is not None and requested_scale != 1.0:
        return requested_scale
    return getattr(lora, "scale", 1.0) or 1.0


def _reset_zimage_scheduler(pipe):
    """Reset scheduler mutable state leaked by some diffusers Z-Image calls."""
    sched = getattr(pipe, "scheduler", None)
    if sched is not None:
        try:
            sched._step_index = None
            sched._begin_index = None
        except Exception:
            pass


def _resolve_lora(req: ZImageRequest):
    """Resolve LoRA from explicit ID or auto-select from prompt."""
    if not lora_engine:
        return None, req.prompt

    from lora_fixtures import get_lora_by_id, apply_lora_template

    if req.lora_id:
        lora = get_lora_by_id(req.lora_id)
        if lora:
            return lora, apply_lora_template(lora, req.prompt)
        logger.warning("lora_id '%s' not found, proceeding without LoRA", req.lora_id)
        return None, req.prompt

    if req.auto_lora:
        lora = lora_engine.select_best(req.prompt)
        if lora:
            final_prompt = apply_lora_template(lora, req.prompt)
            logger.info("auto-selected lora: %s (trigger=%s)", lora.id, lora.trigger_word)
            return lora, final_prompt

    return None, req.prompt


def _generate_image_once_sync(req: ZImageRequest):
    """Synchronous GPU work for one image generation attempt."""
    # Unload NSFW if loaded to avoid device conflicts
    if nsfw_classifier is not None:
        _unload_nsfw_classifier()

    text2img_pipe, _ = zimage_pipeline

    # Ensure pipeline is on GPU (may have been displaced by NSFW model)
    if hasattr(text2img_pipe, 'to') and not hasattr(text2img_pipe, '_offload_gpu_id'):
        try:
            text2img_pipe.to(DEVICE)
        except Exception:
            pass

    lora, final_prompt = _resolve_lora(req)

    width = (req.width // 64) * 64 or 1024
    height = (req.height // 64) * 64 or 1024

    t0 = time.time()
    generator = torch.Generator(device=DEVICE).manual_seed(req.seed)

    # Reset the scheduler state between calls — the vanilla diffusers
    # ZImagePipeline doesn't always re-init step_index, so a leaked _step_index
    # from the previous call causes IndexError on sigmas[N+1].
    _reset_zimage_scheduler(text2img_pipe)

    pipe_kwargs = dict(
        prompt=final_prompt,
        width=width,
        height=height,
        num_inference_steps=req.num_inference_steps,
        guidance_scale=req.guidance_scale,
        generator=generator,
    )

    if lora:
        try:
            _load_lora_onto_pipe(text2img_pipe, lora.url, lora_scale=_effective_lora_scale(lora, req.lora_scale))
            try:
                result = text2img_pipe(**pipe_kwargs)
            finally:
                _restore_original_weights(text2img_pipe.transformer)
        except Exception as e:
            logger.warning("LoRA load failed (%s), generating without: %s", lora.id, e)
            _restore_original_weights(text2img_pipe.transformer)
            result = text2img_pipe(**pipe_kwargs)
            lora = None
    else:
        result = text2img_pipe(**pipe_kwargs)

    image = result.images[0]
    elapsed = time.time() - t0

    buf = io.BytesIO()
    image.save(buf, format="WEBP", quality=90)
    img_bytes = buf.getvalue()
    img_b64 = base64.b64encode(img_bytes).decode()

    lora_info = {"lora_id": lora.id, "lora_name": lora.name} if lora else None
    logger.info("zimage: %dx%d in %.2fs (steps=%d, lora=%s)",
                width, height, elapsed, req.num_inference_steps,
                lora.id if lora else "none")

    return {
        "image_base64": img_b64,
        "format": "webp",
        "width": width,
        "height": height,
        "inference_time_ms": int(elapsed * 1000),
        "seed": req.seed,
        "prompt_used": final_prompt,
        "lora": lora_info,
    }


def _copy_zimage_request(req: ZImageRequest, prompt: str) -> ZImageRequest:
    if hasattr(req, "model_copy"):
        return req.model_copy(update={"prompt": prompt})
    return req.copy(update={"prompt": prompt})


def _generate_image_sync(req: ZImageRequest):
    """Generate an image and retry once if deterministic quality checks fail."""
    first_prompt = compact_prompt(req.prompt)
    prompts = [first_prompt, retry_prompt(first_prompt)]

    last_result = None
    for attempt, prompt in enumerate(prompts):
        attempt_req = _copy_zimage_request(req, prompt)
        attempt_req.seed = req.seed + attempt
        result = _generate_image_once_sync(attempt_req)
        last_result = result

        try:
            image = Image.open(io.BytesIO(base64.b64decode(result["image_base64"]))).convert("RGB")
        except Exception as e:
            logger.warning("zimage quality decode failed: %s", e)
            return result

        if not detect_too_bumpy(image):
            if attempt > 0:
                result["quality_retry"] = {
                    "reason": "bumpy_image",
                    "prompt_used": prompt,
                    "attempts": attempt + 1,
                }
            return result

        metrics = bumpy_metrics(image)
        logger.warning(
            "zimage bumpy image detected on attempt %d "
            "(lap_ratio=%.3f, lap_mean=%.1f, entropy=%.2f)",
            attempt + 1,
            metrics.laplacian_ratio,
            metrics.laplacian_abs_mean,
            metrics.entropy,
        )

    if last_result is not None:
        last_result["quality_warning"] = "bumpy_image_after_retry"
        return last_result
    raise HTTPException(500, "image generation failed")


def _is_cuda_oom(exc: Exception) -> bool:
    text = str(exc).lower()
    return "out of memory" in text and ("cuda" in text or "accelerator" in type(exc).__name__.lower())


def _recover_from_cuda_oom():
    logger.warning("recovering from CUDA OOM: unloading zimage and clearing CUDA cache")
    model_manager.force_unload("zimage")
    if torch.cuda.is_available():
        try:
            torch.cuda.synchronize()
        except Exception:
            pass
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()


def _with_zimage_model_retry(operation_name: str, fn):
    last_exc = None
    for attempt in range(2):
        try:
            with model_manager.use("zimage"):
                if zimage_pipeline is None:
                    raise HTTPException(503, "zimage model failed to load")
                return fn()
        except Exception as e:
            last_exc = e
            if not _is_cuda_oom(e):
                raise
            if attempt > 0:
                _recover_from_cuda_oom()
                raise HTTPException(503, f"{operation_name} failed after CUDA OOM recovery")
            logger.warning("%s hit CUDA OOM; reloading model and retrying once", operation_name)
            _recover_from_cuda_oom()
    raise HTTPException(503, f"{operation_name} failed after CUDA OOM recovery: {last_exc}")


def _generate_image_with_model_sync(req: ZImageRequest):
    return _with_zimage_model_retry("generate_image", lambda: _generate_image_sync(req))


@app.post("/generate_image")
async def generate_image(req: ZImageRequest):
    if not LOAD_ZIMAGE:
        raise HTTPException(503, "zimage disabled")
    async with gpu_slot(req.low_priority):
        return await asyncio.get_event_loop().run_in_executor(
            None, _generate_image_with_model_sync, req
        )


# GET with query params for cutedsl-site internal use (returns base64)
@app.get("/generate_image_b64")
def generate_image_b64(
    prompt: str,
    width: int = ZIMAGE_DEFAULT_WIDTH,
    height: int = ZIMAGE_DEFAULT_HEIGHT,
    seed: int = 0,
    lora_id: Optional[str] = None,
    auto_lora: bool = True,
):
    return generate_image(ZImageRequest(
        prompt=prompt, width=width, height=height, seed=seed,
        lora_id=lora_id, auto_lora=auto_lora,
    ))


# ---------------------------------------------------------------------------
# LoRA search & listing endpoints
# ---------------------------------------------------------------------------

@app.get("/loras")
def list_loras():
    from lora_fixtures import get_all_zimage_loras
    loras = get_all_zimage_loras()
    return {
        "count": len(loras),
        "loras": [
            {"id": l.id, "name": l.name, "trigger_word": l.trigger_word,
             "template": l.template, "scale": l.scale, "is_adult": l.is_adult,
             "keywords": l.keywords}
            for l in loras
        ],
    }


@app.get("/loras/search")
def search_loras(q: str = Query(..., min_length=1), top_k: int = 5):
    if not lora_engine:
        raise HTTPException(503, "lora search engine not initialized")
    results = lora_engine.search(q, top_k=top_k)
    return {
        "query": q,
        "results": [
            {"id": r.lora.id, "name": r.lora.name, "score": round(r.score, 3),
             "match_type": r.match_type, "trigger_word": r.lora.trigger_word,
             "template": r.lora.template, "scale": r.lora.scale,
             "is_adult": r.lora.is_adult}
            for r in results
        ],
    }


# ---------------------------------------------------------------------------
# Chronos2 (time series forecasting)
# ---------------------------------------------------------------------------

class ChronosRequest(BaseModel):
    values: list[float]
    prediction_length: int = 64
    quantile_levels: Optional[list[float]] = None


def _forecast_sync(req: ChronosRequest):
    """Synchronous GPU work for forecasting."""
    t0 = time.time()
    context = torch.tensor(req.values, dtype=torch.float32)

    quantile_levels = req.quantile_levels or [0.1, 0.5, 0.9]

    quantiles, mean = chronos_pipeline.predict_quantiles(
        context,
        prediction_length=req.prediction_length,
        quantile_levels=quantile_levels,
    )

    elapsed = time.time() - t0

    q_tensor = quantiles[0].squeeze(0)
    m_tensor = mean[0].squeeze(0)

    logger.info("chronos2: %d values -> %d steps in %.2fms",
                len(req.values), req.prediction_length, elapsed * 1000)

    return {
        "mean": m_tensor.tolist(),
        "quantiles": {
            str(ql): q_tensor[:, i].tolist()
            for i, ql in enumerate(quantile_levels)
        },
        "prediction_length": req.prediction_length,
        "context_length": len(req.values),
        "inference_time_ms": int(elapsed * 1000),
    }


@app.post("/forecast")
async def forecast(req: ChronosRequest):
    if not LOAD_CHRONOS:
        raise HTTPException(503, "chronos2 disabled")
    model_manager.ensure_loaded("chronos2")
    if chronos_pipeline is None:
        raise HTTPException(503, "chronos2 model failed to load")

    async with gpu_semaphore:
        return await asyncio.get_event_loop().run_in_executor(
            None, _forecast_sync, req
        )


# ---------------------------------------------------------------------------
# Chronos2 batch forecast — multiple series in one call
# ---------------------------------------------------------------------------

class ChronosBatchRequest(BaseModel):
    """Batch forecast: predict multiple time series at once.
    Each series can be a different OHLC channel (open, high, low, close).
    """
    series: list[list[float]]  # list of time series
    prediction_length: int = 64
    quantile_levels: Optional[list[float]] = None
    constrain_ohlc: bool = False  # if True, reorder so high >= open,close >= low


def _forecast_batch_sync(req: ChronosBatchRequest):
    """Batch GPU forecasting — all series in one model call."""
    t0 = time.time()
    contexts = [torch.tensor(s, dtype=torch.float32) for s in req.series]
    quantile_levels = req.quantile_levels or [0.1, 0.5, 0.9]

    # Pad to same length for batching
    max_len = max(len(c) for c in contexts)
    padded = torch.zeros(len(contexts), max_len)
    for i, c in enumerate(contexts):
        padded[i, -len(c):] = c

    quantiles, mean = chronos_pipeline.predict_quantiles(
        padded,
        prediction_length=req.prediction_length,
        quantile_levels=quantile_levels,
    )

    elapsed = time.time() - t0

    results = []
    for i in range(len(req.series)):
        m = mean[i].squeeze(0).tolist()
        q = {
            str(ql): quantiles[i].squeeze(0)[:, j].tolist()
            for j, ql in enumerate(quantile_levels)
        }
        results.append({"mean": m, "quantiles": q})

    # OHLC constraint: ensure high is always max, low is always min
    if req.constrain_ohlc and len(results) == 4:
        for step in range(req.prediction_length):
            vals = [results[ch]["mean"][step] for ch in range(4)]
            o, h, l, c = vals
            h_fixed = max(vals)
            l_fixed = min(vals)
            results[1]["mean"][step] = h_fixed  # high = max
            results[2]["mean"][step] = l_fixed  # low = min

    logger.info("chronos2 batch: %d series, %d steps in %.2fms",
                len(req.series), req.prediction_length, elapsed * 1000)

    return {
        "results": results,
        "prediction_length": req.prediction_length,
        "series_count": len(req.series),
        "inference_time_ms": int(elapsed * 1000),
    }


@app.post("/forecast_batch")
async def forecast_batch(req: ChronosBatchRequest):
    if not LOAD_CHRONOS:
        raise HTTPException(503, "chronos2 disabled")
    model_manager.ensure_loaded("chronos2")
    if chronos_pipeline is None:
        raise HTTPException(503, "chronos2 model failed to load")

    async with gpu_semaphore:
        return await asyncio.get_event_loop().run_in_executor(
            None, _forecast_batch_sync, req
        )


# ---------------------------------------------------------------------------
# TTS (proxy to text-generator.io Kokoro)
# ---------------------------------------------------------------------------

class TTSRequest(BaseModel):
    text: str
    voice: str = "af_nicole"
    speed: float = 1.0


@app.post("/synthesize")
async def synthesize(req: TTSRequest):
    try:
        resp = await tg_client.post(
            "/api/v1/generate_speech",
            json={"text": req.text, "voice": req.voice, "speed": req.speed},
        )
        resp.raise_for_status()
        # Return audio bytes directly
        return Response(
            content=resp.content,
            media_type="audio/wav",
            headers={"X-Voice": req.voice},
        )
    except httpx.HTTPError as e:
        logger.error("TTS proxy error: %s", e)
        raise HTTPException(502, f"TTS backend error: {e}")


# ---------------------------------------------------------------------------
# STT (proxy to text-generator.io Gemma4 audio or dedicated STT)
# ---------------------------------------------------------------------------

class STTRequest(BaseModel):
    audio_url: str
    translate_to_english: bool = False


@app.post("/transcribe")
async def transcribe(req: STTRequest):
    try:
        resp = await tg_client.post(
            "/api/v1/audio-extraction",
            json={
                "audio_url": req.audio_url,
                "translate_to_english": req.translate_to_english,
                "output_filetype": "txt",
            },
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        logger.error("STT proxy error: %s", e)
        raise HTTPException(502, f"STT backend error: {e}")


@app.post("/transcribe_file")
async def transcribe_file(audio_file: UploadFile = File(...)):
    try:
        content = await audio_file.read()
        resp = await tg_client.post(
            "/api/v1/audio-file-extraction",
            files={"audio_file": (audio_file.filename, content, audio_file.content_type or "audio/wav")},
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        logger.error("STT file proxy error: %s", e)
        raise HTTPException(502, f"STT backend error: {e}")


# ---------------------------------------------------------------------------
# Image Captioning (proxy to text-generator.io GitBase)
# ---------------------------------------------------------------------------

class CaptionRequest(BaseModel):
    image_url: str


@app.post("/caption")
async def caption_image(req: CaptionRequest):
    try:
        resp = await tg_client.post(
            "/api/v1/image-caption",
            data={"image_url": req.image_url, "fast_mode": "true"},
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        logger.error("Caption proxy error: %s", e)
        raise HTTPException(502, f"Caption backend error: {e}")


@app.post("/caption_file")
async def caption_file(image_file: UploadFile = File(...)):
    try:
        content = await image_file.read()
        resp = await tg_client.post(
            "/api/v1/image-caption",
            files={"image_file": (image_file.filename, content, image_file.content_type or "image/jpeg")},
            data={"fast_mode": "true"},
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        logger.error("Caption file proxy error: %s", e)
        raise HTTPException(502, f"Caption backend error: {e}")


# ---------------------------------------------------------------------------
# Gemma4 Chat (proxy to text-generator.io OpenAI-compatible API)
# ---------------------------------------------------------------------------

class Gemma4Request(BaseModel):
    messages: list[dict]
    max_tokens: int = 1024
    temperature: float = 0.7
    stream: bool = False


@app.post("/chat")
async def gemma4_chat(req: Gemma4Request):
    try:
        resp = await tg_client.post(
            "/v1/chat/completions",
            json={
                "messages": req.messages,
                "max_tokens": req.max_tokens,
                "temperature": req.temperature,
                "stream": req.stream,
                "model": "default",
            },
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        logger.error("Gemma4 proxy error: %s", e)
        raise HTTPException(502, f"Gemma4 backend error: {e}")


# ---------------------------------------------------------------------------
# stable-diffusion-server compatible API (secret-protected, R2 upload)
# Compatible with netwrck/stable-diffusion-server endpoints so we can
# remap image.netwrck.com traffic here.
# ---------------------------------------------------------------------------

from r2_upload import (
    upload_bytes, check_if_blob_exists, build_save_path,
)


def _image_to_webp_bytes(image, quality: int = 85) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="WEBP", quality=quality, optimize=True)
    return buf.getvalue()


@contextlib.contextmanager
def _nvtx_range(name: str):
    if torch.cuda.is_available():
        try:
            torch.cuda.nvtx.range_push(name)
            yield
            return
        finally:
            try:
                torch.cuda.nvtx.range_pop()
            except Exception:
                pass
    yield


def _fallback_image_path(prompt: str, seed: int) -> str:
    slug = prompt[:60].replace(" ", "_").replace("/", "_")
    return f"{slug}_{seed}.webp"


def _generate_and_upload_sync(prompt: str, width: int, height: int, save_path: str,
                               auto_lora: bool = True, lora_id: str | None = None,
                               return_perf: bool = False) -> dict:
    seed = int(hashlib.md5(prompt.encode()).hexdigest()[:8], 16) % (2**31)
    target_path = save_path or _fallback_image_path(prompt, seed)
    if target_path and check_if_blob_exists(target_path):
        from r2_upload import R2_PUBLIC_BASE_URL, R2_BUCKET_PATH
        url = f"https://{R2_PUBLIC_BASE_URL}/{R2_BUCKET_PATH}/{target_path}"
        logger.info("cached: %s", url)
        result = {"path": url}
        if return_perf:
            result["perf"] = {"cache_hit": True, "upload_time_ms": 0, "inference_time_ms": 0}
        return result

    text2img_pipe, _ = zimage_pipeline

    req = ZImageRequest(
        prompt=prompt, width=width, height=height,
        seed=seed,
        auto_lora=auto_lora,
        lora_id=lora_id,
    )
    lora, final_prompt = _resolve_lora(req)

    w = (width // 64) * 64 or 1024
    h = (height // 64) * 64 or 1024

    t0 = time.time()
    generator = torch.Generator(device=DEVICE).manual_seed(req.seed)

    pipe_kwargs = dict(
        prompt=final_prompt, width=w, height=h,
        num_inference_steps=ZIMAGE_DEFAULT_STEPS,
        guidance_scale=ZIMAGE_DEFAULT_GUIDANCE,
        generator=generator,
    )
    _reset_zimage_scheduler(text2img_pipe)

    if lora:
        try:
            _load_lora_onto_pipe(text2img_pipe, lora.url, lora_scale=_effective_lora_scale(lora))
            try:
                with _nvtx_range("zimage.full.pipeline_lora"):
                    result = text2img_pipe(**pipe_kwargs)
            finally:
                _restore_original_weights(text2img_pipe.transformer)
        except Exception as e:
            logger.warning("LoRA %s failed, generating without: %s", lora.id, e)
            _restore_original_weights(text2img_pipe.transformer)
            _reset_zimage_scheduler(text2img_pipe)
            with _nvtx_range("zimage.full.pipeline"):
                result = text2img_pipe(**pipe_kwargs)
            lora = None
    else:
        with _nvtx_range("zimage.full.pipeline"):
            result = text2img_pipe(**pipe_kwargs)

    image = result.images[0]
    elapsed = time.time() - t0
    logger.info("compat: %dx%d in %.2fs (lora=%s)", w, h, elapsed, lora.id if lora else "none")

    encode_t0 = time.time()
    with _nvtx_range("zimage.webp_encode"):
        webp_bytes = _image_to_webp_bytes(image, quality=85)
    encode_elapsed = time.time() - encode_t0

    upload_t0 = time.time()
    with _nvtx_range("zimage.r2_upload"):
        url = upload_bytes(target_path, webp_bytes)
    upload_elapsed = time.time() - upload_t0

    result = {"path": url}
    if return_perf:
        result["perf"] = {
            "cache_hit": False,
            "inference_time_ms": int(elapsed * 1000),
            "encode_time_ms": int(encode_elapsed * 1000),
            "upload_time_ms": int(upload_elapsed * 1000),
            "width": w,
            "height": h,
            "steps": ZIMAGE_DEFAULT_STEPS,
            "lora": lora.id if lora else None,
        }
    return result


def _latent_teleport_unit(prompt: str, width: int, height: int, steps: int, seed: int):
    from latentteleport.tokenizer import VisualUnit

    key = f"{prompt}|{width}x{height}|steps={steps}|seed={seed}|guidance={ZIMAGE_DEFAULT_GUIDANCE}"
    return VisualUnit.from_text(key)


def _get_latent_teleport_cache(width: int, height: int):
    global latent_teleport_cache
    if latent_teleport_cache is None or latent_teleport_cache.resolution != (height, width):
        from latentteleport.cache import LatentCache

        latent_teleport_cache = LatentCache(
            LATENT_TELEPORT_CACHE_DIR,
            resolution=(height, width),
        )
    return latent_teleport_cache


def _run_zimage_with_capture(pipe, pipe_kwargs: dict, capture_step: int) -> tuple[object, dict[int, torch.Tensor]]:
    captured: dict[int, torch.Tensor] = {}

    def _capture(_pipe, step_index, _timestep, callback_kwargs):  # noqa: ANN001
        if step_index == capture_step and "latents" in callback_kwargs:
            captured[step_index] = callback_kwargs["latents"].detach().clone().cpu()
        return callback_kwargs

    result = pipe(
        **pipe_kwargs,
        callback_on_step_end=_capture,
        callback_on_step_end_tensor_inputs=["latents"],
    )
    return result, captured


def _generate_and_upload_teleport_sync(prompt: str, width: int, height: int, save_path: str,
                                       auto_lora: bool = True, lora_id: str | None = None,
                                       return_perf: bool = False) -> dict:
    if not LATENT_TELEPORT_ENABLED:
        raise HTTPException(400, "latent teleportation disabled")

    seed = int(hashlib.md5(prompt.encode()).hexdigest()[:8], 16) % (2**31)
    target_path = save_path or _fallback_image_path(prompt, seed)
    if target_path and check_if_blob_exists(target_path):
        from r2_upload import R2_PUBLIC_BASE_URL, R2_BUCKET_PATH
        url = f"https://{R2_PUBLIC_BASE_URL}/{R2_BUCKET_PATH}/{target_path}"
        logger.info("cached: %s", url)
        result = {"path": url, "teleport": {"method": "r2_cache"}}
        if return_perf:
            result["perf"] = {"cache_hit": True, "upload_time_ms": 0, "inference_time_ms": 0}
        return result

    text2img_pipe, _ = zimage_pipeline
    req = ZImageRequest(
        prompt=prompt, width=width, height=height,
        seed=seed,
        auto_lora=auto_lora,
        lora_id=lora_id,
    )
    lora, final_prompt = _resolve_lora(req)
    if lora:
        # LoRA-mutated transformer weights invalidate cached base-model latents.
        logger.info("latent teleport skipped for LoRA prompt (lora=%s)", lora.id)
        return _generate_and_upload_sync(prompt, width, height, save_path, auto_lora, lora_id, return_perf)

    w = (width // 64) * 64 or 1024
    h = (height // 64) * 64 or 1024
    steps = ZIMAGE_DEFAULT_STEPS
    capture_step = max(0, min(LATENT_TELEPORT_START_STEP - 1, steps - 2))
    resume_step = capture_step + 1
    cache = _get_latent_teleport_cache(w, h)
    unit = _latent_teleport_unit(final_prompt, w, h, steps, req.seed)
    cached_latent = cache.load_latent(unit, capture_step)
    cached_prompt_emb = cache.load_text_embedding_full(unit) if cached_latent is not None else None

    generator = torch.Generator(device=DEVICE).manual_seed(req.seed)
    pipe_kwargs = dict(
        prompt=final_prompt,
        width=w,
        height=h,
        num_inference_steps=steps,
        guidance_scale=ZIMAGE_DEFAULT_GUIDANCE,
        generator=generator,
    )

    t0 = time.time()
    teleport_meta = {
        "enabled": True,
        "cache_hit": cached_latent is not None,
        "capture_step": capture_step,
        "resume_step": resume_step,
        "total_steps": steps,
    }

    if cached_latent is not None:
        from latentteleport.refine import refine_from_latent

        try:
            with _nvtx_range("zimage.teleport.replay"):
                image = refine_from_latent(
                    text2img_pipe,
                    cached_latent,
                    final_prompt,
                    None,
                    resume_step,
                    prompt_embeds=[cached_prompt_emb] if cached_prompt_emb is not None else None,
                    num_total_steps=steps,
                    height=h,
                    width=w,
                    guidance_scale=ZIMAGE_DEFAULT_GUIDANCE,
                    seed=req.seed,
                    device=DEVICE,
                )
            teleport_meta["method"] = "exact_prompt_latent_replay"
        except Exception as e:
            logger.warning("latent teleport replay failed, falling back to full generation: %s", e)
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            cached_latent = None
            teleport_meta["cache_hit"] = False
            teleport_meta["fallback_reason"] = type(e).__name__

    if cached_latent is None:
        with _nvtx_range("zimage.teleport.prime_pipeline"):
            result, captured = _run_zimage_with_capture(text2img_pipe, pipe_kwargs, capture_step)
        image = result.images[0]
        if capture_step in captured:
            try:
                with _nvtx_range("zimage.teleport.prompt_embed_cache"):
                    text_emb, _ = text2img_pipe.encode_prompt(
                        prompt=final_prompt,
                        negative_prompt=None,
                        do_classifier_free_guidance=False,
                        device=DEVICE,
                    )
                emb = text_emb[0].detach().cpu() if isinstance(text_emb, list) else text_emb.detach().cpu()
            except Exception as e:
                logger.warning("latent teleport text embedding capture failed: %s", e)
                emb = None
            cache.store_latents(
                unit,
                {capture_step: captured[capture_step]},
                text_embedding=emb,
                metadata={"prompt": final_prompt, "seed": req.seed, "steps": steps, "mode": "exact_prompt"},
            )
        teleport_meta["method"] = "full_generation_cached_latent"

    elapsed = time.time() - t0
    logger.info(
        "compat teleport: %dx%d in %.2fs (method=%s, hit=%s)",
        w, h, elapsed, teleport_meta["method"], teleport_meta["cache_hit"],
    )

    encode_t0 = time.time()
    with _nvtx_range("zimage.webp_encode"):
        webp_bytes = _image_to_webp_bytes(image, quality=85)
    encode_elapsed = time.time() - encode_t0
    upload_t0 = time.time()
    with _nvtx_range("zimage.r2_upload"):
        url = upload_bytes(target_path, webp_bytes)
    upload_elapsed = time.time() - upload_t0

    teleport_meta["inference_time_ms"] = int(elapsed * 1000)
    result = {"path": url, "teleport": teleport_meta}
    if return_perf:
        result["perf"] = {
            "cache_hit": False,
            "inference_time_ms": int(elapsed * 1000),
            "encode_time_ms": int(encode_elapsed * 1000),
            "upload_time_ms": int(upload_elapsed * 1000),
            "width": w,
            "height": h,
            "steps": steps,
            "teleport_method": teleport_meta["method"],
            "teleport_cache_hit": teleport_meta["cache_hit"],
        }
    return result


def _generate_and_upload_with_model_sync(prompt: str, width: int, height: int, save_path: str,
                                         auto_lora: bool = True, lora_id: str | None = None,
                                         return_perf: bool = False) -> dict:
    return _with_zimage_model_retry(
        "create_and_upload_image",
        lambda: _generate_and_upload_sync(prompt, width, height, save_path, auto_lora, lora_id, return_perf),
    )


def _generate_and_upload_teleport_with_model_sync(prompt: str, width: int, height: int, save_path: str,
                                                  auto_lora: bool = True, lora_id: str | None = None,
                                                  return_perf: bool = False) -> dict:
    return _with_zimage_model_retry(
        "create_and_upload_image_teleport",
        lambda: _generate_and_upload_teleport_sync(prompt, width, height, save_path, auto_lora, lora_id, return_perf),
    )


def _style_transfer_and_upload_sync(prompt: str, image_url: str, save_path: str,
                                     strength: float = 0.6) -> dict:
    if save_path and check_if_blob_exists(save_path):
        from r2_upload import R2_PUBLIC_BASE_URL, R2_BUCKET_PATH
        url = f"https://{R2_PUBLIC_BASE_URL}/{R2_BUCKET_PATH}/{save_path}"
        return {"path": url}

    _, img2img_pipe = zimage_pipeline

    from diffusers.utils import load_image
    input_image = load_image(image_url).convert("RGB")

    w = (input_image.width // 64) * 64 or 1024
    h = (input_image.height // 64) * 64 or 1024
    input_image = input_image.resize((w, h))

    t0 = time.time()
    seed = int(hashlib.md5(prompt.encode()).hexdigest()[:8], 16) % (2**31)
    generator = torch.Generator(device=DEVICE).manual_seed(seed)

    # Re-enable offload hooks before img2img call to avoid stale device state
    if hasattr(img2img_pipe, "_offload_gpu_id"):
        img2img_pipe.enable_model_cpu_offload()

    result = img2img_pipe(
        prompt=prompt,
        image=input_image,
        strength=strength,
        num_inference_steps=ZIMAGE_DEFAULT_STEPS,
        guidance_scale=ZIMAGE_DEFAULT_GUIDANCE,
        generator=generator,
    )

    image = result.images[0]
    elapsed = time.time() - t0
    logger.info("compat style_transfer: %dx%d in %.2fs", w, h, elapsed)

    webp_bytes = _image_to_webp_bytes(image, quality=85)

    if save_path:
        url = upload_bytes(save_path, webp_bytes)
    else:
        url = upload_bytes(f"style_{seed}.webp", webp_bytes)

    return {"path": url}


def _style_transfer_and_upload_with_model_sync(prompt: str, image_url: str, save_path: str,
                                               strength: float = 0.6) -> dict:
    return _with_zimage_model_retry(
        "style_transfer_and_upload_image",
        lambda: _style_transfer_and_upload_sync(prompt, image_url, save_path, strength),
    )


@app.get("/create_and_upload_image")
async def create_and_upload_image(
    prompt: str,
    width: int = 1024,
    height: int = 1024,
    save_path: str = "",
    model: str = "zimage-turbo",
    secret: str = "",
    lora_id: Optional[str] = None,
    auto_lora: bool = True,
    teleport: bool = True,
    perf: bool = False,
    low_priority: bool = False,
    background: bool = False,
):
    _check_secret(secret)
    sp = build_save_path(save_path) if save_path else ""
    if sp and check_if_blob_exists(sp):
        from r2_upload import R2_PUBLIC_BASE_URL, R2_BUCKET_PATH
        return {"path": f"https://{R2_PUBLIC_BASE_URL}/{R2_BUCKET_PATH}/{sp}"}
    async with gpu_slot(low_priority or background):
        fn = _generate_and_upload_teleport_with_model_sync if teleport else _generate_and_upload_with_model_sync
        return await asyncio.get_event_loop().run_in_executor(
            None, fn, prompt, width, height, sp,
            auto_lora, lora_id, perf,
        )


@app.get("/style_transfer_and_upload_image")
async def style_transfer_and_upload_image(
    prompt: str,
    image_url: str,
    save_path: str = "",
    strength: float = 0.6,
    model: str = "zimage-turbo",
    secret: str = "",
):
    _check_secret(secret)
    _require_http_url(image_url, "image_url")
    sp = build_save_path(save_path) if save_path else ""
    if sp and check_if_blob_exists(sp):
        from r2_upload import R2_PUBLIC_BASE_URL, R2_BUCKET_PATH
        return {"path": f"https://{R2_PUBLIC_BASE_URL}/{R2_BUCKET_PATH}/{sp}"}
    async with gpu_semaphore:
        return await asyncio.get_event_loop().run_in_executor(
            None, _style_transfer_and_upload_with_model_sync, prompt, image_url, sp, strength,
        )


@app.post("/style_transfer_bytes_and_upload_image")
async def style_transfer_bytes_and_upload_image(
    prompt: str = Form(...),
    save_path: str = Form(""),
    strength: float = Form(0.6),
    model: str = Form("zimage-turbo"),
    secret: str = Form(""),
    image_url: str = Form(""),
    image_file: Optional[UploadFile] = File(None),
):
    _check_secret(secret)
    if image_file:
        content = await image_file.read()
        from PIL import Image
        input_image = Image.open(io.BytesIO(content)).convert("RGB")

        _, img2img_pipe = zimage_pipeline
        w = (input_image.width // 64) * 64 or 1024
        h = (input_image.height // 64) * 64 or 1024
        input_image = input_image.resize((w, h))

        seed = int(hashlib.md5(prompt.encode()).hexdigest()[:8], 16) % (2**31)
        suffix = uuid.uuid4().hex[:7]
        sp = build_save_path(save_path, suffix=suffix) if save_path else f"style_{suffix}.webp"

        def _do():
            if hasattr(img2img_pipe, "_offload_gpu_id"):
                img2img_pipe.enable_model_cpu_offload()
            generator = torch.Generator(device=DEVICE).manual_seed(seed)
            result = img2img_pipe(
                prompt=prompt, image=input_image, strength=strength,
                num_inference_steps=ZIMAGE_DEFAULT_STEPS,
                guidance_scale=ZIMAGE_DEFAULT_GUIDANCE,
                generator=generator,
            )
            webp_bytes = _image_to_webp_bytes(result.images[0], quality=85)
            return {"path": upload_bytes(sp, webp_bytes)}

        with model_manager.use("zimage"):
            if zimage_pipeline is None:
                raise HTTPException(503, "zimage model not loaded")
            async with gpu_semaphore:
                return await asyncio.get_event_loop().run_in_executor(None, _do)

    elif image_url:
        _require_http_url(image_url, "image_url")
        sp = build_save_path(save_path) if save_path else ""
        with model_manager.use("zimage"):
            if zimage_pipeline is None:
                raise HTTPException(503, "zimage model not loaded")
            async with gpu_semaphore:
                return await asyncio.get_event_loop().run_in_executor(
                    None, _style_transfer_and_upload_sync, prompt, image_url, sp, strength,
                )
    else:
        raise HTTPException(400, "either image_url or image_file required")


# ---------------------------------------------------------------------------
# LoRA Training API
# ---------------------------------------------------------------------------

# In-memory cache backed by JSON status files so long-running jobs survive a
# process restart and frontend polling can resume cleanly.
training_jobs: dict[str, dict] = load_jobs()


def _save_training_job(job_id: str) -> None:
    job = training_jobs.get(job_id)
    if job:
        save_job(job)


class LoRATrainRequest(BaseModel):
    """Request to start a LoRA fine-tuning job."""
    model: str  # "zimage" or "chronos2"
    dataset_name: str  # identifier for the uploaded dataset
    values: Optional[list[list[float]]] = None  # for chronos2: list of time series
    # LoRA hyperparams
    lora_r: int = 16
    lora_alpha: int = 32
    learning_rate: float = 1e-4
    num_steps: int = 1000
    batch_size: int = 32


def _run_chronos2_training(job_id: str, req: LoRATrainRequest):
    """Background thread for Chronos2 LoRA training."""
    job = training_jobs[job_id]
    try:
        import sys
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "cutedsl")))

        job["status"] = "loading_model"
        job["progress"] = 0.05
        _save_training_job(job_id)

        from cutechronos.pipeline import CuteChronos2Pipeline

        # Load base model for fine-tuning
        base_model_path = os.getenv("CHRONOS_MODEL_PATH", "amazon/chronos-2")
        train_device, train_dtype = _chronos_device_dtype()
        pipeline = CuteChronos2Pipeline.from_pretrained(
            base_model_path,
            device=train_device,
            dtype=train_dtype,
            use_cute=False,  # no custom kernels during training
        )

        job["status"] = "preparing_data"
        job["progress"] = 0.1
        _save_training_job(job_id)

        # Prepare training data from provided values
        if not req.values or len(req.values) == 0:
            raise ValueError("values required: list of time series for chronos2 training")

        train_tensors = [torch.tensor(v, dtype=torch.float32) for v in req.values]

        job["status"] = "training"
        job["progress"] = 0.15
        _save_training_job(job_id)

        # Apply LoRA adapters
        try:
            from peft import LoraConfig, get_peft_model
            lora_config = LoraConfig(
                r=req.lora_r,
                lora_alpha=req.lora_alpha,
                target_modules=["q", "k", "v", "o"],
                lora_dropout=0.05,
                bias="none",
            )
            pipeline.model = get_peft_model(pipeline.model, lora_config)
        except ImportError:
            raise ValueError("peft package required for LoRA training: pip install peft")

        # Simple training loop
        optimizer = torch.optim.AdamW(
            pipeline.model.parameters(),
            lr=req.learning_rate,
        )

        pipeline.model.train()
        total_steps = min(req.num_steps, 5000)  # cap at 5000 steps

        # Patch length is 16 by default for chronos-2; 4 patches = 64 tokens lookahead
        PATCH = 16
        NUM_FUTURE_PATCHES = 4

        for step in range(total_steps):
            idx = step % len(train_tensors)
            series = train_tensors[idx].to(train_device, dtype=train_dtype)

            future_len = PATCH * NUM_FUTURE_PATCHES
            if len(series) < future_len + 32:
                continue
            ctx_len = min(512, len(series) - future_len)
            context = series[:ctx_len].unsqueeze(0)            # (1, ctx_len)
            future_target = series[ctx_len:ctx_len + future_len].unsqueeze(0)  # (1, 64)

            out = pipeline.model(
                context=context,
                future_target=future_target,
                num_output_patches=NUM_FUTURE_PATCHES,
            )
            loss = out.loss
            if loss is None:
                continue
            loss.backward()
            optimizer.step()
            optimizer.zero_grad()

            job["progress"] = 0.15 + 0.8 * (step / total_steps)
            if step % 5 == 0:
                job["loss"] = float(loss.item())
                _save_training_job(job_id)
                logger.info("Training job %s: step %d/%d loss=%.4f", job_id, step, total_steps, loss.item())

        # Save the trained LoRA adapter
        output_dir = os.path.join(TRAINED_LORA_ROOT, job_id)
        os.makedirs(output_dir, exist_ok=True)
        pipeline.model.save_pretrained(output_dir)

        job["status"] = "completed"
        job["progress"] = 1.0
        job["output_path"] = output_dir
        try:
            job.update(upload_training_artifacts(job_id, output_dir))
        except Exception as upload_err:
            logger.warning("Training job %s artifact upload failed: %s", job_id, upload_err)
            job["artifact_upload_error"] = str(upload_err)
        _save_training_job(job_id)
        logger.info("Training job %s completed: %s", job_id, output_dir)

    except Exception as e:
        logger.error("Training job %s failed: %s", job_id, e)
        job["status"] = "failed"
        job["error"] = str(e)
        _save_training_job(job_id)


DATASET_ROOT = os.getenv("LORA_DATASET_ROOT", os.path.join(os.path.dirname(__file__), "lora_datasets"))
TRAINED_LORA_ROOT = os.getenv("TRAINED_LORA_ROOT", os.path.join(os.path.dirname(__file__), "trained_loras"))


def _dataset_dir(dataset_name: str) -> str:
    safe = "".join(c for c in dataset_name if c.isalnum() or c in "._-")
    if not safe:
        raise ValueError("invalid dataset_name")
    return os.path.join(DATASET_ROOT, safe)


def _run_zimage_training(job_id: str, req: LoRATrainRequest):
    """Background thread for Z-Image LoRA fine-tuning via rectified flow matching.

    Uses the real diffusers Z-Image transformer call convention:
        transformer(latent_list, timestep, prompt_embeds, return_dict=False)
    Training objective: sample t~U(0,1), interpolate x_t=(1-t)*noise+t*latent,
    target velocity v=latent-noise, MSE on predicted velocity.
    Fails fast on consecutive OOMs and refuses to mark 'completed' unless at
    least one step actually succeeded.
    """
    job = training_jobs[job_id]
    try:
        from PIL import Image as PILImage
        import numpy as np
        from glob import glob
        import gc

        job["status"] = "loading_dataset"
        job["progress"] = 0.02
        _save_training_job(job_id)

        ds_dir = _dataset_dir(req.dataset_name)
        if not os.path.isdir(ds_dir):
            raise ValueError(f"dataset directory not found: {ds_dir}")

        image_paths = sorted(
            [p for ext in ("jpg", "jpeg", "png", "webp") for p in glob(os.path.join(ds_dir, f"*.{ext}"))]
        )
        if not image_paths:
            raise ValueError(f"no images found in {ds_dir}")
        logger.info("Training job %s: %d images in dataset %s", job_id, len(image_paths), req.dataset_name)

        captions = {}
        for img_path in image_paths:
            txt_path = os.path.splitext(img_path)[0] + ".txt"
            if os.path.exists(txt_path):
                with open(txt_path) as f:
                    captions[img_path] = f.read().strip() or "a photo"
            else:
                captions[img_path] = "a photo"

        job["dataset_size"] = len(image_paths)
        job["status"] = "loading_model"
        job["progress"] = 0.05
        _save_training_job(job_id)

        # Load a VANILLA zimage pipeline for training — NOT the cute-accelerated
        # one. CuteZImageTransformer uses q_proj/k_proj/v_proj (Qwen-style) and
        # its fused kernels are inference-only (no backward). Training requires
        # the stock diffusers ZImageTransformer2DModel with to_q/to_k/to_v.
        from diffusers import ZImagePipeline
        text2img_pipe = ZImagePipeline.from_pretrained(
            os.getenv("ZIMAGE_MODEL_PATH", "Tongyi-MAI/Z-Image-Turbo"),
            torch_dtype=DTYPE,
        )
        # Move components individually (pipeline.to() can fail on meta tensors
        # when components were initialized with low_cpu_mem_usage)
        for comp_name in ("transformer", "vae", "text_encoder"):
            comp = getattr(text2img_pipe, comp_name, None)
            if comp is not None:
                try:
                    comp.to(DEVICE)
                except Exception:
                    # Fallback: to_empty then load params
                    comp.to_empty(device=DEVICE)

        torch.cuda.empty_cache()
        gc.collect()

        transformer = text2img_pipe.transformer
        vae = text2img_pipe.vae

        job["status"] = "preparing_lora"
        job["progress"] = 0.1
        _save_training_job(job_id)

        try:
            from peft import LoraConfig, get_peft_model
        except ImportError:
            raise ValueError("peft package required for LoRA training: pip install peft")

        for p in transformer.parameters():
            p.requires_grad = False
        for p in vae.parameters():
            p.requires_grad = False

        lora_config = LoraConfig(
            r=req.lora_r,
            lora_alpha=req.lora_alpha,
            target_modules=["to_q", "to_k", "to_v"],
            lora_dropout=0.0,
            bias="none",
        )
        transformer = get_peft_model(transformer, lora_config)
        text2img_pipe.transformer = transformer
        transformer.train()

        trainable = [p for p in transformer.parameters() if p.requires_grad]
        n_trainable = sum(p.numel() for p in trainable)
        logger.info("Training job %s: %d trainable LoRA params", job_id, n_trainable)

        optimizer = torch.optim.AdamW(trainable, lr=req.learning_rate)

        # Pre-encode prompts using the pipeline's own encoder (handles Qwen3 correctly)
        prompt_embeds_cache: dict[str, torch.Tensor] = {}
        unique_captions = set(captions.values())
        logger.info("Training job %s: pre-encoding %d unique captions", job_id, len(unique_captions))
        with torch.no_grad():
            for cap in unique_captions:
                try:
                    emb = text2img_pipe._encode_prompt(
                        prompt=[cap],
                        device=DEVICE,
                        max_sequence_length=256,
                    )
                    # Z-Image returns a list of per-sample tensors
                    prompt_embeds_cache[cap] = emb
                except Exception as e:
                    logger.warning("Caption encode failed for '%s': %s", cap[:40], str(e)[:200])
                    prompt_embeds_cache[cap] = None

        # Pre-encode latents once at a fixed small size (saves time and memory)
        TRAIN_SIZE = int(os.getenv("LORA_TRAIN_SIZE", "384"))
        latent_cache: list[tuple[torch.Tensor, str]] = []
        logger.info("Training job %s: pre-encoding %d latents at %dx%d", job_id, len(image_paths), TRAIN_SIZE, TRAIN_SIZE)
        with torch.no_grad():
            for img_path in image_paths:
                try:
                    pil = PILImage.open(img_path).convert("RGB").resize((TRAIN_SIZE, TRAIN_SIZE))
                    arr = np.asarray(pil, dtype=np.float32) / 127.5 - 1.0
                    img_tensor = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0).to(DEVICE, dtype=DTYPE)
                    latent = vae.encode(img_tensor).latent_dist.sample() * vae.config.scaling_factor
                    latent_cache.append((latent.detach(), captions.get(img_path, "a photo")))
                    del img_tensor
                except Exception as e:
                    logger.warning("Latent encode failed for %s: %s", os.path.basename(img_path), str(e)[:200])

        torch.cuda.empty_cache()
        gc.collect()

        if not latent_cache:
            raise RuntimeError("no latents could be encoded from the dataset (VAE failures)")

        total_steps = min(req.num_steps, 5000)
        job["status"] = "training"
        job["progress"] = 0.15
        _save_training_job(job_id)

        successful_steps = 0
        last_loss = None
        ooms_in_a_row = 0
        MAX_OOM = 5

        for step in range(total_steps):
            latent, caption = latent_cache[step % len(latent_cache)]
            prompt_embeds = prompt_embeds_cache.get(caption)
            if prompt_embeds is None:
                continue

            try:
                t_sample = torch.rand(1, device=DEVICE).to(DTYPE)
                timestep = t_sample.expand(1)

                noise = torch.randn_like(latent)
                x_t = (1.0 - t_sample) * noise + t_sample * latent
                target = latent - noise  # rectified flow velocity

                x_in = x_t.unsqueeze(2)  # (1, C, 1, H, W)
                x_list = list(x_in.unbind(0))

                out = transformer(x_list, timestep, prompt_embeds, return_dict=False)[0]
                pred = torch.stack(out, dim=0).squeeze(2)

                loss = torch.nn.functional.mse_loss(pred.float(), target.float())
                loss.backward()
                optimizer.step()
                optimizer.zero_grad()

                successful_steps += 1
                ooms_in_a_row = 0
                last_loss = float(loss.item())
                job["progress"] = 0.15 + 0.8 * (step / total_steps)
                if step % 5 == 0 or step == total_steps - 1:
                    job["loss"] = last_loss
                    _save_training_job(job_id)
                    logger.info("Z-Image train %s: step %d/%d loss=%.4f", job_id, step, total_steps, last_loss)

                del loss, pred, out, x_t, noise, target, x_in, x_list
            except torch.cuda.OutOfMemoryError as oom:
                ooms_in_a_row += 1
                logger.warning("Z-Image train %s: step %d OOM (%d/%d): %s",
                               job_id, step, ooms_in_a_row, MAX_OOM, str(oom)[:120])
                optimizer.zero_grad(set_to_none=True)
                torch.cuda.empty_cache()
                gc.collect()
                if ooms_in_a_row >= MAX_OOM:
                    raise RuntimeError(
                        f"{MAX_OOM} consecutive OOM errors — try fewer images, smaller LORA_TRAIN_SIZE, or free GPU memory"
                    )
                continue
            except Exception as inner:
                logger.warning("Z-Image train %s: step %d failed: %s", job_id, step, str(inner)[:300])
                continue

        if successful_steps == 0:
            raise RuntimeError("no training steps succeeded — all failed")

        output_dir = os.path.join(TRAINED_LORA_ROOT, job_id)
        os.makedirs(output_dir, exist_ok=True)
        transformer.save_pretrained(output_dir)

        job["status"] = "completed"
        job["progress"] = 1.0
        job["output_path"] = output_dir
        job["successful_steps"] = successful_steps
        if last_loss is not None:
            job["loss"] = last_loss
        try:
            job.update(upload_training_artifacts(job_id, output_dir))
        except Exception as upload_err:
            logger.warning("Training job %s artifact upload failed: %s", job_id, upload_err)
            job["artifact_upload_error"] = str(upload_err)
        _save_training_job(job_id)
        logger.info("Training job %s completed: %d/%d steps succeeded -> %s",
                    job_id, successful_steps, total_steps, output_dir)

    except Exception as e:
        logger.error("Training job %s failed: %s", job_id, e)
        job["status"] = "failed"
        job["error"] = str(e)
        _save_training_job(job_id)


@app.post("/train/upload_dataset")
async def upload_dataset(
    dataset_name: str = Form(...),
    files: list[UploadFile] = File(...),
):
    """Upload images (and optional caption .txt files) for a LoRA training dataset."""
    try:
        ds_dir = _dataset_dir(dataset_name)
    except ValueError as e:
        raise HTTPException(400, str(e))

    os.makedirs(ds_dir, exist_ok=True)
    saved = []
    for f in files:
        # Sanitize filename
        base = os.path.basename(f.filename or "")
        safe_name = "".join(c for c in base if c.isalnum() or c in "._-")
        if not safe_name:
            continue
        out_path = os.path.join(ds_dir, safe_name)
        content = await f.read()
        with open(out_path, "wb") as out:
            out.write(content)
        saved.append({"name": safe_name, "size": len(content)})

    return {
        "dataset_name": dataset_name,
        "directory": ds_dir,
        "files": saved,
        "count": len(saved),
    }


class LoRATrainFromURLsRequest(BaseModel):
    """Start a LoRA training job from a list of public image URLs (R2 etc.)."""
    model: str  # "zimage"
    dataset_name: str
    image_urls: list[str]
    captions: Optional[list[str]] = None
    lora_r: int = 16
    lora_alpha: int = 32
    learning_rate: float = 1e-4
    num_steps: int = 500
    batch_size: int = 1


@app.post("/train/from_urls")
def start_training_from_urls(req: LoRATrainFromURLsRequest):
    """Download images from URLs into a local dataset, then start training."""
    if req.model not in ("zimage", "chronos2"):
        raise HTTPException(400, "model must be 'zimage' or 'chronos2'")
    if not req.image_urls:
        raise HTTPException(400, "image_urls must be non-empty")

    if runpod_enabled():
        if req.model != "zimage":
            raise HTTPException(400, "RunPod remote training currently supports zimage only")
        job_id = str(uuid.uuid4())
        payload = req.model_dump() if hasattr(req, "model_dump") else req.dict()
        update_job(
            training_jobs,
            job_id,
            job_id=job_id,
            model=req.model,
            dataset_name=req.dataset_name,
            status="queued",
            progress=0.0,
            created_at=time.time(),
            image_count=len(req.image_urls),
            backend="runpod",
        )
        try:
            job = start_runpod_training(training_jobs, job_id, payload)
        except Exception as e:
            update_job(training_jobs, job_id, status="failed", error=str(e), progress=1.0)
            raise HTTPException(502, f"RunPod training backend unavailable: {e}")
        return {
            "job_id": job_id,
            "model": req.model,
            "dataset_name": req.dataset_name,
            "image_count": len(req.image_urls),
            "status": job.get("status", "starting"),
            "backend": "runpod",
            "runpod_cost_per_hr": job.get("runpod_cost_per_hr"),
        }

    try:
        ds_dir = _dataset_dir(req.dataset_name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    os.makedirs(ds_dir, exist_ok=True)

    # Download synchronously (small datasets typically <100 images)
    downloaded = 0
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for i, url in enumerate(req.image_urls):
            try:
                r = client.get(url)
                if r.status_code != 200:
                    logger.warning("Failed to fetch %s: %d", url, r.status_code)
                    continue
                # Determine extension from content-type
                ct = r.headers.get("content-type", "").lower()
                if "png" in ct:
                    ext = "png"
                elif "webp" in ct:
                    ext = "webp"
                else:
                    ext = "jpg"
                fname = f"img_{i:04d}.{ext}"
                with open(os.path.join(ds_dir, fname), "wb") as f:
                    f.write(r.content)
                # Caption file
                if req.captions and i < len(req.captions):
                    with open(os.path.join(ds_dir, f"img_{i:04d}.txt"), "w") as f:
                        f.write(req.captions[i])
                downloaded += 1
            except Exception as e:
                logger.warning("Error downloading %s: %s", url, e)

    if downloaded == 0:
        raise HTTPException(400, "no images could be downloaded")

    # Build a LoRATrainRequest and reuse the existing pipeline
    train_req = LoRATrainRequest(
        model=req.model,
        dataset_name=req.dataset_name,
        lora_r=req.lora_r,
        lora_alpha=req.lora_alpha,
        learning_rate=req.learning_rate,
        num_steps=req.num_steps,
        batch_size=req.batch_size,
    )

    job_id = str(uuid.uuid4())
    training_jobs[job_id] = {
        "job_id": job_id,
        "model": req.model,
        "dataset_name": req.dataset_name,
        "status": "queued",
        "progress": 0.0,
        "created_at": time.time(),
        "image_count": downloaded,
    }
    _save_training_job(job_id)

    if req.model == "chronos2":
        thread = threading.Thread(target=_run_chronos2_training, args=(job_id, train_req), daemon=True)
    else:
        thread = threading.Thread(target=_run_zimage_training, args=(job_id, train_req), daemon=True)
    thread.start()

    return {
        "job_id": job_id,
        "model": req.model,
        "dataset_name": req.dataset_name,
        "image_count": downloaded,
        "status": "queued",
    }


@app.get("/train/datasets")
def list_datasets():
    """List uploaded LoRA training datasets."""
    if not os.path.isdir(DATASET_ROOT):
        return {"datasets": []}
    out = []
    for name in sorted(os.listdir(DATASET_ROOT)):
        path = os.path.join(DATASET_ROOT, name)
        if not os.path.isdir(path):
            continue
        files = [f for f in os.listdir(path) if not f.startswith(".")]
        out.append({"name": name, "file_count": len(files), "directory": path})
    return {"datasets": out}


@app.post("/train")
def start_training(req: LoRATrainRequest):
    """Start an async LoRA training job."""
    if req.model not in ("zimage", "chronos2"):
        raise HTTPException(400, "model must be 'zimage' or 'chronos2'")

    job_id = str(uuid.uuid4())
    training_jobs[job_id] = {
        "job_id": job_id,
        "model": req.model,
        "dataset_name": req.dataset_name,
        "status": "queued",
        "progress": 0.0,
        "created_at": time.time(),
    }
    _save_training_job(job_id)

    if req.model == "chronos2":
        thread = threading.Thread(target=_run_chronos2_training, args=(job_id, req), daemon=True)
    else:
        thread = threading.Thread(target=_run_zimage_training, args=(job_id, req), daemon=True)

    thread.start()
    logger.info("Training job %s started: model=%s dataset=%s", job_id, req.model, req.dataset_name)

    return {
        "job_id": job_id,
        "model": req.model,
        "status": "queued",
    }


@app.get("/train/{job_id}")
def get_training_status(job_id: str):
    """Check training job status."""
    job = training_jobs.get(job_id)
    if not job:
        raise HTTPException(404, "training job not found")
    if job.get("backend") == "runpod" and job.get("status") not in {"completed", "failed"}:
        try:
            job = refresh_runpod_status(training_jobs, job_id) or job
        except Exception as e:
            job["status_refresh_error"] = str(e)
            _save_training_job(job_id)
    return job


@app.get("/train")
def list_training_jobs():
    """List all training jobs."""
    return {"jobs": list(training_jobs.values())}


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.getenv("INFERENCE_PORT", "8100"))
    workers = int(os.getenv("INFERENCE_WORKERS", "1"))
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=port,
        workers=workers,
        timeout_keep_alive=600,
    )
