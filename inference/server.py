"""CuteDSL Inference Server.

Serves CuteDSL-accelerated models (zimage, chronos2) directly and proxies
TTS, STT, captioning, and gemma4 requests to a text-generator.io backend.

Optimized for RTX 5090 with NVFP4 quantization support.
"""

import asyncio
import base64
import binascii
import io
import json
import logging
import re
import math
import os
import shlex
import subprocess
import threading
import time
import uuid
import hashlib
import contextlib
import ipaddress
import traceback
import socket
import unicodedata
from collections import OrderedDict
from contextlib import asynccontextmanager
from typing import Callable, Iterator, Optional
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlparse

import httpx
import requests
import torch
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, field_validator

from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

try:
    from .dynamic_batcher import DynamicBatcher
except ImportError:  # server.py is also launched directly from inference/
    from dynamic_batcher import DynamicBatcher
from aesthetic_score import score_images as aesthetic_score_images
from image_quality import (
    bumpy_metrics,
    compact_prompt,
    detect_too_bumpy,
    enhance_prompt,
    retry_prompt,
)
from training_store import load_jobs, save_job, update_job, upload_training_artifacts
from runpod_lora_manager import refresh_runpod_status, runpod_enabled, start_runpod_training

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("cutedsl-inference")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

IMAGE_API_SECRET = os.getenv("IMAGE_API_SECRET", "")
# Comma-separated additional accepted secrets (e.g. rotated keys, NETWRCK_API_KEY)
IMAGE_API_SECRETS = {s.strip() for s in os.getenv("IMAGE_API_SECRETS", "").split(",") if s.strip()}
if IMAGE_API_SECRET:
    IMAGE_API_SECRETS.add(IMAGE_API_SECRET)
ERROR_LOG_PATH = os.getenv("ERROR_LOG_PATH", "/nvme0n1-disk/tmp/cutedsl-inference-errors.jsonl")

DEVICE = os.getenv("DEVICE", "cuda")
NSFW_DEVICE = os.getenv("NSFW_DEVICE", "cpu").strip() or "cpu"
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

# NVFP4 quantization (Blackwell sm_100+). ENABLE_NVFP4: "1" force on, "0" force
# off, unset = auto (autotune file > per-GPU capability heuristic). Resolved at
# startup by _resolve_precision(); PRECISION holds the full decision.
import precision as _precision_mod

ENABLE_NVFP4 = os.getenv("ENABLE_NVFP4", "") == "1"
PRECISION: dict | None = None

# AITune: ahead-of-time TensorRT optimization for text_encoder + VAE.
# Run inference/aitune_experiment.py --tune first to generate the engine file.
# Only applies to the vanilla (non-CuteZImage) pipeline path.
AITUNE_ENGINES_PATH = os.getenv("AITUNE_ENGINES_PATH", "")

# Model paths
ZIMAGE_MODEL_PATH = os.getenv("ZIMAGE_MODEL_PATH", "Tongyi-MAI/Z-Image-Turbo")
# Default to the real Chronos-2 (the model we own/host): 8192-step context,
# forecasts up to 1024 steps ahead in a single pass, 21 quantile levels. The
# CuteChronos2Pipeline is built for the Chronos-2 architecture; chronos-bolt is
# a different (T5-encoder-only) family and is not what this pipeline expects.
CHRONOS_MODEL_PATH = os.getenv("CHRONOS_MODEL_PATH", "amazon/chronos-2")
ZIMAGE_COMPILE_MODE = os.getenv("ZIMAGE_COMPILE_MODE", "default") or None
_zimage_compile_mode = ZIMAGE_COMPILE_MODE
_zimage_compile_mode_lock = threading.Lock()
# Chronos has hit CUDA graph assertion failures under torch.compile in local
# inference, so keep it eager by default unless explicitly enabled.
CHRONOS_COMPILE_MODE = os.getenv("CHRONOS_COMPILE_MODE", "") or None
# CuteChronos2Model currently diverges ~10% from upstream on quantile outputs
# (kernel toggles ruled out; under investigation). use_cute=0 delegates to the
# upstream Chronos2Model for exact outputs at ~1.4x the latency.
CHRONOS_USE_CUTE = os.getenv("CHRONOS_USE_CUTE", "1") == "1"

# Text-generator.io backend for TTS, STT, captioning, gemma4
TG_BACKEND_URL = os.getenv("TG_BACKEND_URL", "http://localhost:9080")
COEXISTING_TEXT_SLEEP_URL = os.getenv(
    "COEXISTING_TEXT_SLEEP_URL", "http://127.0.0.1:8300/backend/sleep"
).strip()
COEXISTING_TEXT_SLEEP_TIMEOUT = float(os.getenv("COEXISTING_TEXT_SLEEP_TIMEOUT", "120"))
PRELOAD_DELAY_SECONDS = max(0.0, float(os.getenv("PRELOAD_DELAY_SECONDS", "1")))


def _configured_caption_backend_api_key() -> str:
    """Resolve the caption service's authoritative partner credential.

    Some production launchers inherit an older generic ``TG_API_KEY`` while
    the caption backend's systemd unit has the rotated scoped credential.  A
    read-only service query keeps inline systemd launches aligned with the
    backend; non-systemd environments fall back to their explicit variables.
    """
    inherited = (
        os.getenv("CAPTION_BACKEND_API_KEY", "")
        or os.getenv("NETWRCK_IMAGE_CAPTION_SECRET", "")
    )
    if os.getenv("CAPTION_BACKEND_SYSTEMD_LOOKUP", "1") != "1":
        return inherited
    try:
        result = subprocess.run(
            [
                "systemctl",
                "show",
                "text-generator-inference.service",
                "--property=Environment",
                "--value",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            settings = dict(
                item.split("=", 1)
                for item in shlex.split(result.stdout)
                if "=" in item
            )
            service_key = (
                settings.get("NETWRCK_IMAGE_CAPTION_SECRET", "")
                or settings.get("NETWRCK_PARTNER_SECRET", "")
            )
            if service_key:
                return service_key
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return inherited


CAPTION_BACKEND_API_KEY = _configured_caption_backend_api_key()
# A deployment may retain the historical caption-specific variable while the
# same scoped partner credential is used by all text-generator proxy routes.
TG_API_KEY = os.getenv("TG_API_KEY", "") or CAPTION_BACKEND_API_KEY

# Which models to load on startup
LOAD_ZIMAGE = os.getenv("LOAD_ZIMAGE", "1") == "1"
LOAD_CHRONOS = os.getenv("LOAD_CHRONOS", "1") == "1"
ZIMAGE_USE_CUTE = os.getenv("ZIMAGE_USE_CUTE", "1") == "1"

# Inference defaults
ZIMAGE_DEFAULT_STEPS = int(os.getenv("ZIMAGE_DEFAULT_STEPS", "8"))
ZIMAGE_DEFAULT_GUIDANCE = float(os.getenv("ZIMAGE_DEFAULT_GUIDANCE", "0.0"))
ZIMAGE_DEFAULT_WIDTH = int(os.getenv("ZIMAGE_DEFAULT_WIDTH", "1024"))
ZIMAGE_DEFAULT_HEIGHT = int(os.getenv("ZIMAGE_DEFAULT_HEIGHT", "1024"))
LATENT_TELEPORT_ENABLED = os.getenv("LATENT_TELEPORT_ENABLED", "0") == "1"
LATENT_TELEPORT_CACHE_DIR = os.getenv("LATENT_TELEPORT_CACHE_DIR", "/nvme0n1-disk/tmp/latentteleport-cache")
LATENT_TELEPORT_START_STEP = int(os.getenv("LATENT_TELEPORT_START_STEP", "7"))
LATENT_TELEPORT_MAX_ENTRIES_PER_RESOLUTION = max(
    1, int(os.getenv("LATENT_TELEPORT_MAX_ENTRIES_PER_RESOLUTION", "2048"))
)
LATENT_TELEPORT_MAX_GIB_PER_RESOLUTION = max(
    0.25, float(os.getenv("LATENT_TELEPORT_MAX_GIB_PER_RESOLUTION", "8"))
)
LATENT_TELEPORT_PRUNE_INTERVAL_SECONDS = max(
    0.0, float(os.getenv("LATENT_TELEPORT_PRUNE_INTERVAL_SECONDS", "60"))
)
ZIMAGE_LATENT_CACHE_VERSION = os.getenv("ZIMAGE_LATENT_CACHE_VERSION", "v3")
LATENT_SAVE = os.getenv("LATENT_SAVE", "1") == "1"
ZIMAGE_EARLY_EXIT = float(os.getenv("ZIMAGE_EARLY_EXIT", "0") or 0)
ZIMAGE_EARLY_EXIT_MIN_STEPS = int(os.getenv("ZIMAGE_EARLY_EXIT_MIN_STEPS", "4"))
ZIMAGE_SKIP_NOOP_STEPS = os.getenv("ZIMAGE_SKIP_NOOP_STEPS", "1") == "1"
ZIMAGE_EARLY_EXIT_CONSECUTIVE = int(os.getenv("ZIMAGE_EARLY_EXIT_CONSECUTIVE", "2"))
DX0_LOG = os.getenv("DX0_LOG", "1") == "1"
DX0_CORPUS_PATH = os.getenv("DX0_CORPUS_PATH", "/nvme0n1-disk/tmp/dx0-corpus.jsonl")
STEP_TRACE_DIR = os.getenv("STEP_TRACE_DIR", "/nvme0n1-disk/tmp/step-trace")
LATENT_TELEPORT_APPROX_MIN_SIM = float(os.getenv("LATENT_TELEPORT_APPROX_MIN_SIM", "0.92"))
# Approximate replay resumes from a neighbouring prompt's latent. Off by default
# on the paid path: it is a real quality trade, not a transparent cache hit.
LATENT_TELEPORT_APPROX_DEFAULT = os.getenv("LATENT_TELEPORT_APPROX_DEFAULT", "0") == "1"
LATENT_TELEPORT_MIN_FREE_MB = int(os.getenv("LATENT_TELEPORT_MIN_FREE_MB", "512"))
# Full BF16 residency needs about 20.5 GiB of weights plus allocator/workspace
# headroom.  A stale production unit once supplied 12.5 GiB here and auto mode
# selected full CUDA with only 19 GiB free, wedging the load halfway through.
# Operators who truly have a dedicated device can still explicitly set
# ZIMAGE_CPU_OFFLOAD=0; auto mode must keep this safety floor.
ZIMAGE_NO_OFFLOAD_MIN_FREE_MB = max(
    24576, int(os.getenv("ZIMAGE_NO_OFFLOAD_MIN_FREE_MB", "24576"))
)
ZIMAGE_DIRECT_DEVICE_MAP = os.getenv("ZIMAGE_DIRECT_DEVICE_MAP", "1") == "1"
# "cpu" keeps the Qwen3 text encoder (~8 GB bf16) in system RAM: prompt encodes
# run on CPU (cache misses only) and only the conditioning tensors move to GPU.
# Frees VRAM for co-resident services (vLLM text backend) at no image-quality cost.
ZIMAGE_TEXT_ENCODER_DEVICE = os.getenv("ZIMAGE_TEXT_ENCODER_DEVICE", "").strip().lower() or None
# Weight-only quantization applied to the text encoder ALONE ("int8wo" ~4 GB,
# "nvfp4" ~2.2 GB) so it can stay GPU-resident beside the bf16 transformer.
# This host's CPU (Xeon E5 v4, AVX2, no AMX/bf16) encodes a prompt in ~5 s,
# which dominates a ~2.5 s denoise; a quantized GPU encoder removes that.
ZIMAGE_TEXT_ENCODER_QUANT = os.getenv("ZIMAGE_TEXT_ENCODER_QUANT", "").strip().lower() or None
# Refuse to move a quantized encoder onto a GPU that cannot also hold the
# transformer's activations; falling back to CPU is slow but never OOMs.
ZIMAGE_TEXT_ENCODER_MIN_FREE_MB = int(os.getenv("ZIMAGE_TEXT_ENCODER_MIN_FREE_MB", "1536"))
ZIMAGE_LOAD_MIN_FREE_MB = int(os.getenv("ZIMAGE_LOAD_MIN_FREE_MB", "9216"))
ZIMAGE_OOM_RECOVERY_WAIT_SECONDS = float(os.getenv("ZIMAGE_OOM_RECOVERY_WAIT_SECONDS", "10"))
ZIMAGE_OOM_RECOVERY_POLL_SECONDS = float(os.getenv("ZIMAGE_OOM_RECOVERY_POLL_SECONDS", "0.5"))
ZIMAGE_FATAL_RESTART_DELAY_SECONDS = float(os.getenv("ZIMAGE_FATAL_RESTART_DELAY_SECONDS", "10"))
ZIMAGE_REQUIRE_CUDA_READY = os.getenv("ZIMAGE_REQUIRE_CUDA_READY", "1") == "1"
# A co-resident quantized Z-Image backend can keep image service available when
# this BF16 worker is cold. A warm CuteDSL pipeline always retains the existing
# generation path; a failed native call may use the local loader only when the
# CUDA cold-load headroom check says doing so is safe.
ZIMAGE_NATIVE_FALLBACK_URL = os.getenv("ZIMAGE_NATIVE_FALLBACK_URL", "").strip().rstrip("/")
ZIMAGE_NATIVE_FALLBACK_TIMEOUT_SECONDS = float(
    os.getenv("ZIMAGE_NATIVE_FALLBACK_TIMEOUT_SECONDS", "180")
)
ZIMAGE_NATIVE_FALLBACK_RETRIES = max(
    0, int(os.getenv("ZIMAGE_NATIVE_FALLBACK_RETRIES", "1"))
)
# A failed resident native backend is normally a signal that shared GPU
# capacity is unavailable.  Starting the much larger local BF16 pipeline in
# that state can monopolize the interpreter during checkpoint loading and make
# even /healthz time out.  Development deployments can opt back into that
# legacy fallback explicitly.
ZIMAGE_LOCAL_COLD_FALLBACK_ENABLED = (
    os.getenv("ZIMAGE_LOCAL_COLD_FALLBACK_ENABLED", "0") == "1"
)
ZIMAGE_NATIVE_HEADROOM_GRACE_SECONDS = max(
    0.0, float(os.getenv("ZIMAGE_NATIVE_HEADROOM_GRACE_SECONDS", "0"))
)
ZIMAGE_NATIVE_HEADROOM_POLL_SECONDS = max(
    0.1, float(os.getenv("ZIMAGE_NATIVE_HEADROOM_POLL_SECONDS", "2"))
)
# Background producers have their own durable retry queues.  Do not let one of
# them occupy the single native image lane for the full interactive request
# budget when another GPU tenant owns the card; return explicit backpressure
# quickly so paid/interactive work can be admitted ahead of it.
ZIMAGE_NATIVE_BACKGROUND_HEADROOM_GRACE_SECONDS = max(
    0.0, float(os.getenv("ZIMAGE_NATIVE_BACKGROUND_HEADROOM_GRACE_SECONDS", "5"))
)
ZIMAGE_NATIVE_GENERATION_FAILURE_GRACE_SECONDS = max(
    0.0, float(os.getenv("ZIMAGE_NATIVE_GENERATION_FAILURE_GRACE_SECONDS", "0"))
)
ZIMAGE_NATIVE_GENERATION_FAILURE_POLL_SECONDS = max(
    0.1, float(os.getenv("ZIMAGE_NATIVE_GENERATION_FAILURE_POLL_SECONDS", "2"))
)
ZIMAGE_NATIVE_RESTART_GRACE_SECONDS = max(
    0.0, float(os.getenv("ZIMAGE_NATIVE_RESTART_GRACE_SECONDS", "0"))
)
ZIMAGE_NATIVE_RESTART_POLL_SECONDS = max(
    0.1, float(os.getenv("ZIMAGE_NATIVE_RESTART_POLL_SECONDS", "2"))
)
# A remote Z-Image endpoint is the last-resort lane when every local CUDA path
# is unavailable.  Keep it explicitly opt-in because it is metered, but use
# the same model, dimensions, steps, seed, prompt and LoRA so recovery does not
# silently turn into a different generation product.
ZIMAGE_FAL_FALLBACK_ENABLED = os.getenv("ZIMAGE_FAL_FALLBACK_ENABLED", "0") == "1"
ZIMAGE_FAL_FALLBACK_TIMEOUT_SECONDS = float(
    os.getenv("ZIMAGE_FAL_FALLBACK_TIMEOUT_SECONDS", "180")
)
ZIMAGE_NATIVE_FAILURE_COOLDOWN_SECONDS = max(
    0.0, float(os.getenv("ZIMAGE_NATIVE_FAILURE_COOLDOWN_SECONDS", "30"))
)
ALLOW_PRIVATE_IMAGE_URLS = os.getenv("ALLOW_PRIVATE_IMAGE_URLS", "0") == "1"
REMOTE_IMAGE_TIMEOUT_SECONDS = float(os.getenv("REMOTE_IMAGE_TIMEOUT_SECONDS", "15"))
REMOTE_IMAGE_MAX_BYTES = int(os.getenv("REMOTE_IMAGE_MAX_BYTES", str(20 * 1024 * 1024)))
REMOTE_IMAGE_MAX_REDIRECTS = int(os.getenv("REMOTE_IMAGE_MAX_REDIRECTS", "3"))
ZIMAGE_PROMPT_CACHE_SIZE = max(0, int(os.getenv("ZIMAGE_PROMPT_CACHE_SIZE", "64")))
ZIMAGE_ENHANCE_PROMPT = os.getenv("ZIMAGE_ENHANCE_PROMPT", "1") == "1"
ZIMAGE_PREWARM_LORA_IDS = tuple(
    item.strip()
    for item in os.getenv("ZIMAGE_PREWARM_LORA_IDS", "").split(",")
    if item.strip()
)

# ---------------------------------------------------------------------------
# Model memory manager — lazy load, LRU eviction, idle unload
# ---------------------------------------------------------------------------

MODEL_IDLE_TIMEOUT = int(os.getenv("MODEL_IDLE_TIMEOUT", "20"))  # Release shared GPU memory between bursts
BATCH_WINDOW_MS = int(os.getenv("BATCH_WINDOW_MS", "50"))  # ms to wait for batching
ZIMAGE_DYNAMIC_BATCH_ENABLED = os.getenv("ZIMAGE_DYNAMIC_BATCH_ENABLED", "1") == "1"
ZIMAGE_DYNAMIC_BATCH_MAX_SIZE = max(1, int(os.getenv("ZIMAGE_DYNAMIC_BATCH_MAX_SIZE", "4")))
ZIMAGE_DYNAMIC_BATCH_MAX_PIXELS = max(
    # Z-Image currently packs list-shaped samples into one long attention
    # sequence; at 512px, batch 2 benchmarked slower than two serial chunks.
    # Keep coalescing/residency sharing enabled but default physical batching
    # to 256px workloads until a true batch dimension lands in the kernel.
    64 * 64, int(os.getenv("ZIMAGE_DYNAMIC_BATCH_MAX_PIXELS", str(512 * 512)))
)
ZIMAGE_DYNAMIC_BATCH_RESERVE_MB = max(0, int(os.getenv("ZIMAGE_DYNAMIC_BATCH_RESERVE_MB", "512")))
ZIMAGE_DYNAMIC_BATCH_EXTRA_MB = max(1, int(os.getenv("ZIMAGE_DYNAMIC_BATCH_EXTRA_MB", "1024")))
ZIMAGE_VRAM_BROKER_URL = os.getenv("ZIMAGE_VRAM_BROKER_URL", "").strip().rstrip("/")
ZIMAGE_VRAM_BROKER_TIMEOUT_SECONDS = 0.25
ZIMAGE_VRAM_BROKER_RETRY_SECONDS = 5.0
ZIMAGE_VRAM_BROKER_TTL_SECONDS = 600

zimage_pipeline = None
chronos_pipeline = None
tg_client: httpx.AsyncClient = None

# GPU inference gate — limits concurrent GPU work and lets public requests
# jump ahead of background dataset generation between inference calls.
MAX_GPU_CONCURRENT = int(os.getenv("MAX_GPU_CONCURRENT", "2"))
LOW_PRIORITY_IDLE_SECONDS = float(os.getenv("LOW_PRIORITY_IDLE_SECONDS", "5.0"))
gpu_semaphore = None
zimage_dynamic_batcher: DynamicBatcher | None = None
_zimage_batch_runtime_lock = threading.Lock()
_zimage_batch_runtime = {
    "pipeline_batches": 0,
    "pipeline_images": 0,
    "serial_chunks": 0,
    "oom_batch_fallbacks": 0,
    "largest_pipeline_batch": 0,
    "broker_grants": 0,
    "broker_denials": 0,
    "broker_errors": 0,
    "last_granted_mb": 0,
}
_zimage_vram_broker_state_lock = threading.Lock()
_zimage_vram_broker_unreachable_until = 0.0

# LoRA search engine (lazy init)
lora_engine = None
latent_teleport_cache = None
_zimage_effective_cpu_offload: bool | None = None
_zimage_load_strategy: str | None = None
# Where the text encoder actually ended up. Quantized placement can fall back to
# CPU when VRAM is short, and the runtime paths that re-home the pipeline must
# follow the real placement — a blind pipe.to(cuda) on a CPU-pinned fp32 encoder
# drags ~16 GB across PCIe and OOMs the worker.
_zimage_text_encoder_placement: str | None = None
_zimage_prompt_cache: OrderedDict[tuple, tuple[list[torch.Tensor], list[torch.Tensor] | None]] = OrderedDict()
_zimage_prompt_cache_lock = threading.Lock()
_zimage_prompt_cache_hits = 0
_zimage_prompt_cache_misses = 0
_cuda_runtime_fault_lock = threading.Lock()
_cuda_runtime_fault: str | None = None
_cuda_runtime_fault_at: float | None = None
_cuda_process_restart_scheduled = False


_FATAL_CUDA_ERROR_MARKERS = (
    "unspecified launch failure",
    "illegal memory access",
    "device-side assert",
    "device is lost",
    "device lost",
    "driver shutting down",
    "initialization error",
    "cuda-capable device(s) is/are busy or unavailable",
)


def _is_fatal_cuda_error(exc: BaseException) -> bool:
    """Return whether an error means this process's CUDA context is unusable."""
    text = str(exc).lower()
    return "cuda" in text and any(marker in text for marker in _FATAL_CUDA_ERROR_MARKERS)


def _mark_cuda_runtime_fault(exc: BaseException | str) -> None:
    """Latch fatal CUDA state so later requests fail fast instead of storming the GPU."""
    global _cuda_runtime_fault, _cuda_runtime_fault_at
    detail = str(exc).splitlines()[0].strip() or type(exc).__name__
    with _cuda_runtime_fault_lock:
        if _cuda_runtime_fault is None:
            _cuda_runtime_fault = detail
            _cuda_runtime_fault_at = time.time()
            logger.error("CUDA runtime marked unhealthy: %s", detail)


def _schedule_cuda_process_restart() -> None:
    """Exit once after the current 503 is flushed so systemd can replace CUDA state."""
    global _cuda_process_restart_scheduled
    with _cuda_runtime_fault_lock:
        if _cuda_process_restart_scheduled:
            return
        _cuda_process_restart_scheduled = True
    delay = max(0.5, ZIMAGE_FATAL_RESTART_DELAY_SECONDS)
    logger.critical("scheduling inference process restart in %.1fs after CUDA became unavailable", delay)
    timer = threading.Timer(delay, os._exit, args=(70,))
    timer.daemon = True
    timer.start()


def _cuda_unavailable_detail(*, probe: bool = True) -> str | None:
    """Describe an unavailable/poisoned CUDA runtime, otherwise return ``None``."""
    if not (LOAD_ZIMAGE and DEVICE.startswith("cuda")):
        return None
    with _cuda_runtime_fault_lock:
        fault = _cuda_runtime_fault
    if fault:
        return f"CUDA runtime is unhealthy and the inference process must restart ({fault})"
    try:
        available = torch.cuda.is_available()
    except Exception as exc:
        if _is_fatal_cuda_error(exc):
            _mark_cuda_runtime_fault(exc)
        return f"CUDA availability probe failed ({type(exc).__name__})"
    if not available:
        return "CUDA device is unavailable"
    if probe:
        try:
            torch.cuda.mem_get_info()
        except Exception as exc:
            if _is_fatal_cuda_error(exc):
                _mark_cuda_runtime_fault(exc)
            return f"CUDA memory probe failed ({type(exc).__name__})"
    return None


def _raise_if_zimage_cuda_unavailable() -> None:
    detail = _cuda_unavailable_detail()
    if detail:
        # cudaGetDeviceCount can remain false for the lifetime of a process when
        # PyTorch first probes it before the NVIDIA driver is ready. A request
        # proves this worker is serving image traffic, so let the supervisor
        # replace it after the retryable response has had time to flush.
        if ZIMAGE_REQUIRE_CUDA_READY and LOAD_ZIMAGE and DEVICE.startswith("cuda"):
            _schedule_cuda_process_restart()
        raise HTTPException(503, detail, headers={"Retry-After": "30"})


def _require_zimage_cuda_at_startup(cuda_detail: str | None) -> None:
    """Refuse readiness when this worker requires CUDA but initialized without it."""
    if (
        cuda_detail
        and ZIMAGE_REQUIRE_CUDA_READY
        and LOAD_ZIMAGE
        and DEVICE.startswith("cuda")
    ):
        raise RuntimeError(f"Z-Image CUDA startup check failed: {cuda_detail}")


def _clear_torch_cuda_caches():
    """Best-effort cleanup which never replaces the exception being handled."""
    import gc
    gc.collect()
    try:
        available = torch.cuda.is_available()
    except Exception as exc:
        if _is_fatal_cuda_error(exc):
            _mark_cuda_runtime_fault(exc)
        return
    if not available:
        return
    with _cuda_runtime_fault_lock:
        if _cuda_runtime_fault is not None:
            return
    cleanup_calls = (
        ("synchronize", torch.cuda.synchronize),
        ("empty_cache", torch.cuda.empty_cache),
        ("ipc_collect", torch.cuda.ipc_collect),
        ("clear_cublas_workspaces", torch._C._cuda_clearCublasWorkspaces),
    )
    for name, cleanup in cleanup_calls:
        try:
            cleanup()
        except Exception as exc:
            if _is_fatal_cuda_error(exc):
                _mark_cuda_runtime_fault(exc)
                return
            logger.warning("CUDA cleanup %s failed: %s", name, exc)


def _embedding_list(value) -> list[torch.Tensor] | None:
    if value is None:
        return None
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _cpu_embedding_copy(value) -> list[torch.Tensor] | None:
    tensors = _embedding_list(value)
    if tensors is None:
        return None
    return [tensor.detach().to(device="cpu").contiguous() for tensor in tensors]


def _device_embedding_copy(value, *, device, dtype) -> list[torch.Tensor] | None:
    tensors = _embedding_list(value)
    if tensors is None:
        return None
    return [tensor.detach().to(device=device, dtype=dtype, non_blocking=True) for tensor in tensors]


def _clear_zimage_prompt_cache() -> None:
    global _zimage_prompt_cache_hits, _zimage_prompt_cache_misses
    with _zimage_prompt_cache_lock:
        _zimage_prompt_cache.clear()
        _zimage_prompt_cache_hits = 0
        _zimage_prompt_cache_misses = 0


def _zimage_prompt_cache_snapshot() -> dict:
    with _zimage_prompt_cache_lock:
        size_bytes = sum(
            tensor.numel() * tensor.element_size()
            for positive, negative in _zimage_prompt_cache.values()
            for tensor in positive + (negative or [])
        )
        return {
            "enabled": ZIMAGE_PROMPT_CACHE_SIZE > 0,
            "max_entries": ZIMAGE_PROMPT_CACHE_SIZE,
            "entries": len(_zimage_prompt_cache),
            "size_mib": round(size_bytes / (1024 * 1024), 2),
            "hits": _zimage_prompt_cache_hits,
            "misses": _zimage_prompt_cache_misses,
        }


def _prepare_zimage_prompt_embeddings(pipe, pipe_kwargs: dict) -> tuple[dict, dict]:
    """Replace prompt text with reusable CPU-cached embeddings.

    The cache is independent of image size, seed, step count, and transformer
    LoRAs. Cached tensors live on CPU so a useful cache does not consume scarce
    serving VRAM; each hit transfers only the conditioning tensors.
    """
    global _zimage_prompt_cache_hits, _zimage_prompt_cache_misses
    prompt = pipe_kwargs.get("prompt")
    if ZIMAGE_PROMPT_CACHE_SIZE <= 0 or not isinstance(prompt, str):
        return pipe_kwargs, {"enabled": False, "hit": False, "encode_ms": 0}

    guidance = float(pipe_kwargs.get("guidance_scale", 0.0))
    negative_prompt = pipe_kwargs.get("negative_prompt")
    do_cfg = guidance > 0
    key = (ZIMAGE_MODEL_PATH, DTYPE_STR, prompt, negative_prompt, do_cfg)
    with _zimage_prompt_cache_lock:
        cached = _zimage_prompt_cache.pop(key, None)
        if cached is not None:
            _zimage_prompt_cache[key] = cached
            _zimage_prompt_cache_hits += 1

    target_device = DEVICE if not str(DEVICE).startswith("cuda") or torch.cuda.is_available() else "cpu"
    target_dtype = getattr(getattr(pipe, "transformer", None), "dtype", DTYPE)
    encoder = getattr(pipe, "text_encoder", None)
    encode_device = str(getattr(encoder, "device", target_device)) if encoder is not None else target_device
    started = time.perf_counter()
    if cached is None:
        # encode_prompt is called directly here, outside the pipeline's own
        # inference wrapper. Keep conditioning graph-free both for lower
        # memory use and for safe persistence by latent-teleport caches.
        with torch.inference_mode():
            positive, negative = pipe.encode_prompt(
                prompt=prompt,
                negative_prompt=negative_prompt,
                do_classifier_free_guidance=do_cfg,
                device=encode_device,
            )
        positive_cpu = _cpu_embedding_copy(positive)
        negative_cpu = _cpu_embedding_copy(negative)
        if positive_cpu is None:
            raise RuntimeError("Z-Image encode_prompt returned no prompt embeddings")
        with _zimage_prompt_cache_lock:
            _zimage_prompt_cache[key] = (positive_cpu, negative_cpu)
            _zimage_prompt_cache_misses += 1
            while len(_zimage_prompt_cache) > ZIMAGE_PROMPT_CACHE_SIZE:
                _zimage_prompt_cache.popitem(last=False)
        positive_device = _device_embedding_copy(positive, device=target_device, dtype=target_dtype)
        negative_device = _device_embedding_copy(negative, device=target_device, dtype=target_dtype)
        hit = False
    else:
        positive_device = _device_embedding_copy(cached[0], device=target_device, dtype=target_dtype)
        negative_device = _device_embedding_copy(cached[1], device=target_device, dtype=target_dtype)
        hit = True

    prepared = dict(pipe_kwargs)
    prepared["prompt"] = None
    prepared["prompt_embeds"] = positive_device
    if do_cfg:
        prepared["negative_prompt_embeds"] = negative_device
    return prepared, {
        "enabled": True,
        "hit": hit,
        "encode_ms": int((time.perf_counter() - started) * 1000),
    }


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


def _sleep_coexisting_text_backend(model_name: str) -> bool:
    """Best-effort VRAM handoff before diffusion/forecast GPU work.

    The paired text adapter sleeps vLLM level-1 synchronously, retaining its
    CPU-backed weights for a fast later wake while freeing GPU weights and KV.
    Deployments without that adapter retain the existing local preflight/OOM
    handling.
    """
    if not COEXISTING_TEXT_SLEEP_URL:
        return True
    try:
        response = requests.post(
            COEXISTING_TEXT_SLEEP_URL,
            timeout=max(1.0, COEXISTING_TEXT_SLEEP_TIMEOUT),
        )
        if 200 <= response.status_code < 300:
            logger.info("slept coexisting text backend before using %s", model_name)
            return True
        if response.status_code == 409:
            raise HTTPException(
                503,
                "text generation is active; retry the GPU model request shortly",
                headers={"Retry-After": "5"},
            )
        logger.warning(
            "text backend sleep returned HTTP %s before loading %s",
            response.status_code,
            model_name,
        )
    except requests.RequestException as exc:
        logger.debug("coexisting text backend sleep unavailable: %s", exc)
    return False


class ModelManager:
    """LRU model manager with idle timeout and lazy loading.

    Only keeps the most recently used model in GPU memory. If no requests
    arrive for MODEL_IDLE_TIMEOUT seconds, all models are unloaded.
    Requests are batched within a BATCH_WINDOW_MS window to avoid thrashing.
    """

    def __init__(self, coexisting_text_sleep: Callable[[str], bool] | None = None):
        self._lock = threading.Lock()
        self._last_access: dict[str, float] = {}  # model -> last use time
        self._loaded: set[str] = set()
        self._in_use: dict[str, int] = {}  # model -> active request refcount
        # Requests reserve admission before entering an async queue or executor.
        # Without this separate count, /admin/hold can land after an HTTP request
        # was accepted but before use() pins the model, turning admitted work into
        # a 503 during a peer GPU handoff.
        self._admitted: dict[str, int] = {}
        self._idle_timer: threading.Timer | None = None
        self._batch_queues: dict[str, list] = {}  # model -> [(request, future)]
        self._hold_until = 0.0
        # Keep cross-service mutation injectable. Unit-created managers are
        # isolated by default; the production singleton opts in explicitly.
        self._coexisting_text_sleep = coexisting_text_sleep

    def _coordinate_gpu_handoff(self, model_name: str) -> None:
        if self._coexisting_text_sleep is not None:
            self._coexisting_text_sleep(model_name)

    def _raise_if_held_locked(self) -> None:
        remaining = self._hold_until - time.time()
        if remaining > 0:
            raise HTTPException(
                503,
                f"GPU model admission is paused for a text backend transition ({remaining:.0f}s remaining)",
                headers={"Retry-After": str(max(1, min(30, int(remaining))))},
            )

    def hold(self, seconds: float) -> float:
        """Pause new model loads/uses while another GPU backend boots."""
        seconds = max(1.0, min(float(seconds), 3600.0))
        with self._lock:
            self._hold_until = max(self._hold_until, time.time() + seconds)
            return max(0.0, self._hold_until - time.time())

    def try_hold(self, seconds: float) -> tuple[float | None, dict[str, int]]:
        """Atomically acquire a hold only when all admitted GPU work is idle."""
        seconds = max(1.0, min(float(seconds), 3600.0))
        with self._lock:
            busy_models = {
                model_name: max(
                    self._admitted.get(model_name, 0),
                    self._in_use.get(model_name, 0),
                )
                for model_name in set(self._admitted) | set(self._in_use)
                if self._admitted.get(model_name, 0) > 0
                or self._in_use.get(model_name, 0) > 0
            }
            if busy_models:
                return None, busy_models
            self._hold_until = max(self._hold_until, time.time() + seconds)
            return max(0.0, self._hold_until - time.time()), {}

    @contextlib.contextmanager
    def reserve(self, model_name: str, *, allow_while_held: bool = False):
        """Protect accepted async work from a later peer admission hold.

        ``allow_while_held`` is only for work that is guaranteed to execute on
        a separately managed backend. Such work must not be counted as local
        GPU admission while a peer already owns the local-model hold.
        """
        admitted = False
        with self._lock:
            held = self._hold_until > time.time()
            if held and not allow_while_held:
                self._raise_if_held_locked()
            if not held:
                self._admitted[model_name] = self._admitted.get(model_name, 0) + 1
                admitted = True
        try:
            yield
        finally:
            if admitted:
                with self._lock:
                    remaining = max(0, self._admitted.get(model_name, 0) - 1)
                    if remaining:
                        self._admitted[model_name] = remaining
                    else:
                        self._admitted.pop(model_name, None)

    def release_hold(self) -> None:
        with self._lock:
            self._hold_until = 0.0

    def hold_remaining(self) -> float:
        with self._lock:
            return max(0.0, self._hold_until - time.time())

    @contextlib.contextmanager
    def use(self, model_name: str):
        """Context manager: ensure model is loaded and pin it for the duration."""
        # A loaded diffusion pipeline can still expand its CUDA footprint at
        # inference time, so coordinate every use rather than cold loads only.
        # Check the local hold before the network call so a text wake already
        # in progress wins without us trying to put it back to sleep.
        with self._lock:
            self._raise_if_held_locked()
        self._coordinate_gpu_handoff(model_name)
        self.ensure_loaded(model_name, coordinate=False)
        with self._lock:
            self._raise_if_held_locked()
            # An admin hold/unload can land between ensure_loaded() and this
            # pin. Fail cleanly rather than executing through a dropped global
            # pipeline reference.
            if model_name not in self._loaded:
                raise HTTPException(503, f"{model_name} was unloaded before inference started")
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
                _clear_torch_cuda_caches()
                free, total = torch.cuda.mem_get_info()
                logger.info("All models unloaded → %.2f GB free / %.2f GB total",
                            free / 1e9, total / 1e9)

    def _drop_locked(self, model_name: str):
        """Caller must hold self._lock."""
        global zimage_pipeline, chronos_pipeline, _zimage_effective_cpu_offload
        if model_name == "zimage":
            zimage_pipeline = None
            _zimage_effective_cpu_offload = None
            _clear_zimage_external_caches()
            # Swapper holds references to the dropped transformer; discard with it.
            global _lora_swapper
            _lora_swapper = None
        elif model_name == "chronos2":
            chronos_pipeline = None
        self._loaded.discard(model_name)
        self._last_access.pop(model_name, None)

    def force_unload(self, model_name: str | None = None) -> list[str]:
        """Immediately unload a model (or all) and free GPU cache."""
        global nsfw_classifier
        with self._lock:
            targets = [model_name] if model_name else list(self._loaded)
            dropped = []
            for m in targets:
                if m is None:
                    continue
                if self._in_use.get(m, 0) > 0:
                    logger.info("Skip force-unload of %s: in_use=%d", m, self._in_use[m])
                    continue
                if m in self._loaded:
                    logger.info("Force unloading model: %s", m)
                    self._drop_locked(m)
                    dropped.append(m)
                elif m == "zimage":
                    # A failed cold load never reaches _loaded, but can still
                    # leave partially constructed CUDA modules and module-level
                    # CuteZImage caches alive. Clear the same state anyway.
                    logger.info("Force clearing partial model state: %s", m)
                    self._drop_locked(m)
            if not self._loaded and self._idle_timer:
                self._idle_timer.cancel()
                self._idle_timer = None
        if model_name is None:
            nsfw_classifier = None
        _clear_torch_cuda_caches()
        return dropped

    def ensure_loaded(self, model_name: str, *, coordinate: bool = True):
        """Ensure model is loaded (lazy load if needed). Evicts other models if needed."""
        global zimage_pipeline, chronos_pipeline, _zimage_effective_cpu_offload
        # Cross-service calls must happen outside _lock. The text manager can
        # simultaneously be asking /admin/hold for this lock; keeping the HTTP
        # handshake outside prevents a distributed lock inversion.
        with self._lock:
            self._raise_if_held_locked()
            if model_name in self._loaded:
                self.touch(model_name)
                return
        if coordinate:
            self._coordinate_gpu_handoff(model_name)

        with self._lock:
            self._raise_if_held_locked()
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
                        _zimage_effective_cpu_offload = None
                        _clear_zimage_external_caches()
                    elif oldest == "chronos2":
                        chronos_pipeline = None
                    self._loaded.discard(oldest)
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()

            # Load requested model
            logger.info("Loading model: %s", model_name)
            try:
                if model_name == "zimage":
                    _load_zimage()
                    _init_lora_engine()
                elif model_name == "chronos2":
                    _load_chronos()
            except Exception:
                logger.exception("Failed to load model: %s; clearing partial model state", model_name)
                self._drop_locked(model_name)
                _clear_torch_cuda_caches()
                raise

            self._loaded.add(model_name)
            self.touch(model_name)

    def is_loaded(self, model_name: str) -> bool:
        return model_name in self._loaded


model_manager = ModelManager(_sleep_coexisting_text_backend)

# NSFW classifier (lazy loaded to save GPU memory)
nsfw_classifier = None
nsfw_lock = None


def _resolve_precision():
    global ENABLE_NVFP4, PRECISION
    PRECISION = _precision_mod.resolve_precision()
    ENABLE_NVFP4 = PRECISION["mode"] != "bf16"
    source = PRECISION["source"]
    if PRECISION.get("config_name"):
        source = f"{source}:{PRECISION['config_name']}"
    logger.info(
        "precision: gpu=%s cap=%s mode=%s source=%s skip=%s first_last_skip=%s",
        PRECISION["gpu"], PRECISION["capability"], PRECISION["mode"], source,
        ",".join(PRECISION["skip_patterns"]) if PRECISION["mode"] == "nvfp4" else "-",
        PRECISION["skip_first_last"] if PRECISION["mode"] == "nvfp4" else "-",
    )


def _apply_nvfp4_quantization(model: torch.nn.Module) -> torch.nn.Module:
    """Apply the resolved weight-only quantization (nvfp4 or int8wo) selectively."""
    if PRECISION is None:
        _resolve_precision()
    if PRECISION["mode"] == "bf16":
        return model

    try:
        _precision_mod.apply_quant(
            model, PRECISION["mode"],
            skip_patterns=PRECISION["skip_patterns"],
            skip_first_last=PRECISION["skip_first_last"],
        )
        logger.info("%s quantization applied", PRECISION["mode"])
    except ImportError:
        logger.warning("torchao not available for %s quantization. pip install torchao", PRECISION["mode"])
    except Exception as e:
        logger.warning("%s quantization failed: %s", PRECISION["mode"], e)

    return model


def _place_text_encoder(encoder: torch.nn.Module) -> str:
    """Place the text encoder and remember where it landed."""
    global _zimage_text_encoder_placement
    _zimage_text_encoder_placement = _place_text_encoder_uncached(encoder)
    return _zimage_text_encoder_placement


def _text_encoder_on_cpu() -> bool:
    """True when moving the whole pipeline to CUDA would drag the encoder along."""
    if _zimage_text_encoder_placement is not None:
        return _zimage_text_encoder_placement.startswith("cpu")
    return ZIMAGE_TEXT_ENCODER_DEVICE == "cpu"


def _place_text_encoder_uncached(encoder: torch.nn.Module) -> str:
    """Quantize the text encoder and move it to the GPU, or leave it on CPU.

    Records and returns the placement actually used, for logging and /health.
    The encoder is quantized while still on CPU so peak VRAM never includes the
    bf16 copy, then moved; if the device lacks room for the quantized weights
    plus a working margin we keep the CPU/fp32 encoder rather than risk an OOM
    that would take the whole image worker down.
    """
    mode = ZIMAGE_TEXT_ENCODER_QUANT
    if not mode or mode in ("none", "bf16") or not str(DEVICE).startswith("cuda"):
        return "cpu/fp32" if ZIMAGE_TEXT_ENCODER_DEVICE == "cpu" else str(DEVICE)

    bytes_per_param = {"int8wo": 1, "nvfp4": 0.55}.get(mode)
    if bytes_per_param is None:
        logger.warning("unknown ZIMAGE_TEXT_ENCODER_QUANT=%s; keeping encoder on CPU", mode)
        return "cpu/fp32"

    params = sum(p.numel() for p in encoder.parameters())
    needed_mb = int(params * bytes_per_param / 1e6) + ZIMAGE_TEXT_ENCODER_MIN_FREE_MB
    try:
        free_mb = torch.cuda.mem_get_info()[0] // (1024 * 1024)
    except Exception as exc:  # CUDA can be busy/unhealthy during a cold load
        logger.warning("text encoder VRAM probe failed (%s); keeping it on CPU", exc)
        return "cpu/fp32"
    if free_mb < needed_mb:
        logger.warning(
            "text encoder stays on CPU: %s needs ~%d MB (incl. %d MB margin), only %d MB free",
            mode, needed_mb, ZIMAGE_TEXT_ENCODER_MIN_FREE_MB, free_mb,
        )
        encoder.to("cpu", dtype=torch.float32)
        return "cpu/fp32"

    try:
        encoder.to("cpu", dtype=DTYPE)
        _precision_mod.apply_quant(encoder, mode, skip_patterns=[], skip_first_last=False)
        encoder.to(DEVICE)
    except Exception as exc:
        logger.warning("text encoder %s quantization failed (%s); falling back to CPU/fp32", mode, exc)
        try:
            encoder.to("cpu", dtype=torch.float32)
        except Exception:
            pass
        return "cpu/fp32"

    logger.info(
        "Z-Image text encoder on %s (%s weight-only, %.1f GB bf16 -> ~%.1f GB)",
        DEVICE, mode, params * 2 / 1e9, params * bytes_per_param / 1e9,
    )
    return f"{DEVICE}/{mode}"


def _optimize_for_inference():
    """Apply global PyTorch inference optimizations."""
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
    _resolve_precision()


def _get_zimage_compile_mode() -> str | None:
    with _zimage_compile_mode_lock:
        return _zimage_compile_mode


def _downgrade_zimage_compile_mode(reason: str) -> bool:
    """Disable CUDA-graph compilation after an inductor runtime fault."""
    global _zimage_compile_mode
    with _zimage_compile_mode_lock:
        old_mode = _zimage_compile_mode
        if old_mode is None:
            return False
        new_mode = "default" if old_mode != "default" else None
        _zimage_compile_mode = new_mode

    logger.warning(
        "downgrading Z-Image compile mode from %s to %s after %s",
        old_mode,
        new_mode or "eager",
        reason,
    )
    try:
        torch._dynamo.reset()
    except Exception:
        pass
    return True


def _clear_zimage_external_caches():
    """Drop CuteZImage's module-level pipeline cache during server unloads."""
    _clear_zimage_prompt_cache()
    try:
        from cutezimage.pipeline import clear_pipeline_caches
    except Exception:
        return
    try:
        clear_pipeline_caches()
    except Exception as exc:
        logger.warning("failed to clear CuteZImage pipeline cache: %s", exc)


def _zimage_cpu_offload_mode() -> str:
    raw = os.getenv("ZIMAGE_CPU_OFFLOAD", "1").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return "on"
    if raw in {"0", "false", "no", "off"}:
        return "off"
    if raw == "auto":
        return "auto"
    logger.warning("invalid ZIMAGE_CPU_OFFLOAD=%r; using CPU offload", raw)
    return "on"


def _resolve_zimage_cpu_offload() -> bool:
    mode = _zimage_cpu_offload_mode()
    if mode == "on":
        return True
    if mode == "off":
        return False

    free_mb = _cuda_free_mb()
    if free_mb is None:
        logger.info("ZIMAGE_CPU_OFFLOAD=auto: no CUDA free-memory reading; using CPU offload")
        return True
    # The 24 GiB safety floor models the full ~8 GiB BF16 text encoder. A
    # weight-only encoder leaves substantially more headroom, so applying that
    # unadjusted floor needlessly selects accelerate CPU offload and turns a
    # few-second image request into a multi-minute component-shuttling job.
    encoder_savings_mb = {
        "int8wo": 4096,
        "nvfp4": 6144,
    }.get(ZIMAGE_TEXT_ENCODER_QUANT or "", 0)
    effective_min_free_mb = max(
        16384,
        ZIMAGE_NO_OFFLOAD_MIN_FREE_MB - encoder_savings_mb,
    )
    use_offload = free_mb < effective_min_free_mb
    logger.info(
        "ZIMAGE_CPU_OFFLOAD=auto: free CUDA memory=%d MB, "
        "no-offload threshold=%d MB (encoder_quant=%s), cpu_offload=%s",
        free_mb,
        effective_min_free_mb,
        ZIMAGE_TEXT_ENCODER_QUANT or "none",
        use_offload,
    )
    return use_offload


def _zimage_cpu_offload_enabled() -> bool:
    return _zimage_effective_cpu_offload if _zimage_effective_cpu_offload is not None else _resolve_zimage_cpu_offload()


def _enable_zimage_model_cpu_offload(pipe, *, keep_text_encoder_cpu: bool) -> None:
    """Enable component offload without hooking a deliberately CPU-pinned encoder.

    Diffusers' Z-Image offload sequence normally starts with ``text_encoder``.
    Hiding that component while hooks are installed keeps prompt encoding on
    CPU and prevents an 8 GB encoder transfer from competing with co-resident
    GPU services. Transformer/VAE offload behavior is unchanged.
    """
    encoder = getattr(pipe, "text_encoder", None) if keep_text_encoder_cpu else None
    if encoder is None:
        pipe.enable_model_cpu_offload()
        return

    pipe.text_encoder = None
    try:
        pipe.enable_model_cpu_offload()
    finally:
        pipe.text_encoder = encoder
    encoder.to("cpu", dtype=torch.float32)
    logger.info("Z-Image text encoder excluded from GPU offload hooks and pinned to CPU/fp32")


def _cuda_free_mb() -> int | None:
    if not torch.cuda.is_available():
        return None
    try:
        free_bytes, _total_bytes = torch.cuda.mem_get_info()
        return int(free_bytes / (1024 * 1024))
    except Exception:
        return None


def _zimage_memory_pressure_detail(min_free_mb: int, operation_name: str) -> str | None:
    if min_free_mb <= 0:
        return None
    free_mb = _cuda_free_mb()
    if free_mb is None or free_mb >= min_free_mb:
        return None
    return (
        f"{operation_name} needs at least {min_free_mb} MB free CUDA memory "
        f"before starting Z-Image; only {free_mb} MB is free"
    )


def _should_use_native_zimage_fallback(operation_name: str) -> bool:
    """Prefer the resident quantized backend over a duplicate BF16 cold load."""
    del operation_name  # retained for readable call sites and health diagnostics
    return bool(ZIMAGE_NATIVE_FALLBACK_URL and not model_manager.is_loaded("zimage"))


def _native_failure_allows_local_cold_load(operation_name: str) -> bool:
    return (
        ZIMAGE_LOCAL_COLD_FALLBACK_ENABLED
        and _zimage_memory_pressure_detail(ZIMAGE_LOAD_MIN_FREE_MB, operation_name) is None
    )


def _raise_if_zimage_memory_pressure(min_free_mb: int, operation_name: str):
    detail = _zimage_memory_pressure_detail(min_free_mb, operation_name)
    if detail:
        raise HTTPException(503, detail, headers={"Retry-After": "10"})


def _reclaim_zimage_cold_load_headroom(min_free_mb: int, operation_name: str) -> None:
    """Release stale partial-model/cache state before rejecting a cold load.

    An OOM traceback can temporarily retain pipeline tensors after recovery has
    marked the model unloaded. Once that request unwinds, those tensors become
    reclaimable, but a later request used to fail the free-memory preflight
    before PyTorch's allocator or partial model caches were cleaned again.
    """
    detail = _zimage_memory_pressure_detail(min_free_mb, operation_name)
    if detail is None:
        return

    before_mb = _cuda_free_mb()
    logger.warning(
        "%s cold load is under CUDA memory pressure (%s); "
        "clearing stale Z-Image state and rechecking",
        operation_name,
        detail,
    )
    # This is idempotent when the manager has no loaded model. It also clears
    # partially constructed pipelines and the process's unused allocator pool.
    model_manager.force_unload("zimage")
    after_mb = _cuda_free_mb()
    if before_mb is not None and after_mb is not None and after_mb > before_mb:
        logger.info(
            "%s cold-load cleanup reclaimed %d MB CUDA headroom (%d -> %d MB free)",
            operation_name,
            after_mb - before_mb,
            before_mb,
            after_mb,
        )
    _raise_if_zimage_memory_pressure(min_free_mb, operation_name)


def _wait_for_zimage_memory_headroom(min_free_mb: int, operation_name: str) -> bool:
    deadline = time.monotonic() + max(0.0, ZIMAGE_OOM_RECOVERY_WAIT_SECONDS)
    while True:
        if _zimage_memory_pressure_detail(min_free_mb, operation_name) is None:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(max(0.1, ZIMAGE_OOM_RECOVERY_POLL_SECONDS))


def _pipeline_execution_device(pipe) -> torch.device:
    try:
        device = getattr(pipe, "_execution_device", None)
    except Exception:
        device = None
    if device is None:
        device = getattr(pipe, "device", DEVICE)
    return torch.device(device)


def _make_pipeline_generator(pipe, seed: int) -> torch.Generator:
    device = _pipeline_execution_device(pipe)
    return torch.Generator(device=device).manual_seed(int(seed))


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
    global zimage_pipeline, _zimage_effective_cpu_offload, _zimage_load_strategy

    import sys
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "cutedsl")))

    if PRECISION is None:
        _resolve_precision()

    compile_mode = _get_zimage_compile_mode()
    logger.info(
        "Loading Z-Image from %s (quant=%s, CuteZImage=%s, compile_mode=%s)...",
        ZIMAGE_MODEL_PATH,
        PRECISION["mode"],
        ZIMAGE_USE_CUTE,
        compile_mode or "eager",
    )
    t0 = time.time()

    enable_offload = _resolve_zimage_cpu_offload()
    _zimage_effective_cpu_offload = enable_offload
    skip_warmup = os.getenv("ZIMAGE_SKIP_WARMUP", "0") == "1" or ENABLE_NVFP4

    if ENABLE_NVFP4 or not ZIMAGE_USE_CUTE:
        # Vanilla diffusers path. This is required for NVFP4 because torchao
        # swaps stock nn.Linear modules; it is also useful as a production
        # fallback when CuteZImage conversion/compilation is being benchmarked.
        from diffusers import ZImagePipeline, ZImageImg2ImgPipeline
        load_kwargs = {"torch_dtype": DTYPE}
        text_encoder_cpu = ZIMAGE_TEXT_ENCODER_DEVICE == "cpu"
        # A quantized encoder must be built on CPU and quantized before it moves,
        # so the direct-to-GPU device_map shortcut cannot be used for it.
        if (
            not enable_offload
            and not ENABLE_NVFP4
            and ZIMAGE_DIRECT_DEVICE_MAP
            and not text_encoder_cpu
            and not ZIMAGE_TEXT_ENCODER_QUANT
        ):
            load_kwargs["device_map"] = DEVICE
        try:
            text2img_pipe = ZImagePipeline.from_pretrained(ZIMAGE_MODEL_PATH, **load_kwargs)
            _zimage_load_strategy = (
                "direct-device-map"
                if "device_map" in load_kwargs
                else ("cpu-model-offload" if enable_offload else "cpu-then-cuda")
            )
        except (TypeError, ValueError, NotImplementedError) as exc:
            if "device_map" not in load_kwargs:
                raise
            logger.warning("direct-to-device Z-Image load unsupported; retrying via CPU: %s", exc)
            load_kwargs.pop("device_map")
            text2img_pipe = ZImagePipeline.from_pretrained(ZIMAGE_MODEL_PATH, **load_kwargs)
            _zimage_load_strategy = "cpu-then-cuda"

        if ENABLE_NVFP4:
            # Quantize the heavyweights BEFORE moving to GPU so peak load memory
            # stays low. Weight-only quant swaps the .weight tensor in-place.
            for comp_name in ("transformer", "text_encoder"):
                comp = getattr(text2img_pipe, comp_name, None)
                if comp is not None:
                    logger.info("quant(%s): %s (%.1f GB bf16)", PRECISION["mode"], comp_name,
                                sum(p.numel() for p in comp.parameters()) * 2 / 1e9)
                    _apply_nvfp4_quantization(comp)

        # Loading the CPU checkpoint can take minutes on a busy host. In auto
        # mode another GPU service may consume the headroom observed above
        # while those shards are being read. Re-evaluate immediately before
        # moving components to CUDA so a stale no-offload decision cannot turn
        # a safe cold load into an avoidable OOM. Explicit 0/1 settings retain
        # their requested behavior, and NVFP4 remains resident because its
        # tensor subclasses are incompatible with accelerate CPU offload.
        if (
            not enable_offload
            and not ENABLE_NVFP4
            and not getattr(text2img_pipe, "hf_device_map", None)
        ):
            refreshed_offload = _resolve_zimage_cpu_offload()
            if refreshed_offload:
                logger.warning(
                    "CUDA headroom changed during Z-Image checkpoint load; "
                    "enabling CPU offload before moving components to GPU"
                )
                enable_offload = True
                _zimage_effective_cpu_offload = True
                _zimage_load_strategy = "cpu-model-offload-after-load"

        if ZIMAGE_TEXT_ENCODER_QUANT and enable_offload:
            logger.warning(
                "ZIMAGE_TEXT_ENCODER_QUANT=%s ignored: accelerate CPU offload owns component placement",
                ZIMAGE_TEXT_ENCODER_QUANT,
            )

        if enable_offload and not ENABLE_NVFP4 and hasattr(text2img_pipe, "enable_model_cpu_offload"):
            _enable_zimage_model_cpu_offload(
                text2img_pipe,
                keep_text_encoder_cpu=text_encoder_cpu,
            )
        else:
            # NVFP4 already shrinks weights substantially, and no-offload is
            # also the low-latency path on 24 GB+ GPUs for 1024px generation.
            # Accelerate's CPU offload breaks NVFP4 tensor subclasses, so keep
            # those components resident on the target device.
            try:
                if not getattr(text2img_pipe, "hf_device_map", None):
                    for comp_name in ("transformer", "vae", "text_encoder"):
                        comp = getattr(text2img_pipe, comp_name, None)
                        if comp is not None:
                            if comp_name == "text_encoder" and ZIMAGE_TEXT_ENCODER_QUANT:
                                text_encoder_placement = _place_text_encoder(comp)
                                text_encoder_cpu = text_encoder_placement.startswith("cpu")
                            elif comp_name == "text_encoder" and text_encoder_cpu:
                                # float32 on CPU: oneDNN fp32 GEMM is ~10x faster
                                # than PyTorch's emulated bf16 CPU path.
                                comp.to("cpu", dtype=torch.float32)
                                logger.info("Z-Image text encoder pinned to CPU/fp32 (ZIMAGE_TEXT_ENCODER_DEVICE=cpu)")
                            else:
                                comp.to(DEVICE)
            except Exception as e:
                if (
                    str(DEVICE).startswith("cuda")
                    and not ENABLE_NVFP4
                    and hasattr(text2img_pipe, "enable_model_cpu_offload")
                ):
                    logger.warning(
                        "Z-Image component .to(%s) failed; enabling CPU offload fallback: %s",
                        DEVICE,
                        e,
                    )
                    _enable_zimage_model_cpu_offload(
                        text2img_pipe,
                        keep_text_encoder_cpu=text_encoder_cpu,
                    )
                    enable_offload = True
                    _zimage_effective_cpu_offload = True
                    _zimage_load_strategy = "cpu-model-offload-fallback"
                else:
                    raise RuntimeError(f"Z-Image component .to({DEVICE}) failed") from e

        img2img_pipe = ZImageImg2ImgPipeline(**text2img_pipe.components)

        if _text_encoder_on_cpu() and not enable_offload:
            # DiffusionPipeline.device reports the FIRST component's device, so
            # a CPU-pinned text encoder makes _execution_device=cpu and latents
            # get built on CPU against the CUDA transformer. Pin the property.
            def _pin_pipe_device(pipe, device):
                cls = type(pipe)
                pinned = type(cls.__name__ + "Pinned", (cls,), {
                    "device": property(lambda self: torch.device(device)),
                })
                pipe.__class__ = pinned
            _pin_pipe_device(text2img_pipe, DEVICE)
            _pin_pipe_device(img2img_pipe, DEVICE)

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
            compile_mode=compile_mode,
            device=DEVICE,
            enable_cpu_offload=enable_offload,
        )

    zimage_pipeline = (text2img_pipe, img2img_pipe)
    logger.info("Z-Image loaded in %.1fs (cpu_offload=%s)", time.time() - t0, enable_offload)

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

    if ZIMAGE_PREWARM_LORA_IDS and not ENABLE_NVFP4:
        _prewarm_zimage_loras(text2img_pipe, ZIMAGE_PREWARM_LORA_IDS)

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
            generator=_make_pipeline_generator(text2img_pipe, 0),
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
        use_cute=CHRONOS_USE_CUTE,
        compile_mode=CHRONOS_COMPILE_MODE if chronos_device.startswith("cuda") else None,
    )

    # Apply NVFP4 to model weights
    if ENABLE_NVFP4:
        _apply_nvfp4_quantization(chronos_pipeline.model)

    logger.info("Chronos2 loaded in %.1fs", time.time() - t0)

    # Warmup
    logger.info("Chronos2 warmup...")
    try:
        # Vary each dim independently so torch.compile marks both context and
        # horizon dynamic at startup instead of recompiling (~40s) on the first
        # user request with an unseen (context, num_output_patches) combo.
        warmup_shapes = (
            [(64, 16), (128, 16), (128, 32), (512, 64), (512, 30)]
            if CHRONOS_COMPILE_MODE
            else [(64, 16)]
        )
        t_w = time.time()
        for ctx_len, horizon in warmup_shapes:
            dummy = torch.randn(1, ctx_len, device=chronos_device)
            chronos_pipeline.predict(dummy, prediction_length=horizon)
        logger.info("Chronos2 warmup complete (%.1fs, %d shapes)", time.time() - t_w, len(warmup_shapes))
    except Exception as e:
        logger.warning("Chronos2 warmup failed (non-fatal): %s", e)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------


async def _preload_model_after_startup(model_name: str) -> None:
    """Delay background preloading until after uvicorn has had time to bind.

    Uvicorn enters the application lifespan before binding its HTTP socket. A
    duplicate service can therefore complete an expensive GPU preload and
    disturb peer workloads before finally reporting EADDRINUSE. The short
    cancellable delay makes bind failure win that race.
    """
    try:
        if PRELOAD_DELAY_SECONDS:
            await asyncio.sleep(PRELOAD_DELAY_SECONDS)
        await asyncio.to_thread(model_manager.ensure_loaded, model_name)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("background preload of %s failed: %s", model_name, exc)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global tg_client, gpu_semaphore, zimage_dynamic_batcher
    _optimize_for_inference()

    gpu_semaphore = PriorityGPUSemaphore(MAX_GPU_CONCURRENT)
    if ZIMAGE_DYNAMIC_BATCH_ENABLED:
        zimage_dynamic_batcher = DynamicBatcher(
            key_fn=_zimage_batch_compatibility_key,
            run_batch=_run_zimage_dynamic_batch,
            priority_fn=lambda req: 0 if req.low_priority else 1,
            max_batch_size=ZIMAGE_DYNAMIC_BATCH_MAX_SIZE,
            window_ms=BATCH_WINDOW_MS,
        )

    tg_client = httpx.AsyncClient(
        base_url=TG_BACKEND_URL,
        timeout=httpx.Timeout(180.0, connect=10.0),
        headers={"secret": TG_API_KEY} if TG_API_KEY else {},
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
    )

    # Lazy load models on first request via model_manager.
    # Optionally warm them in a background executor so the HTTP socket comes up
    # immediately after restarts instead of making nginx wait on checkpoint load.
    cuda_detail = _cuda_unavailable_detail()
    if cuda_detail:
        logger.critical("Z-Image unavailable at startup: %s", cuda_detail)
    _require_zimage_cuda_at_startup(cuda_detail)

    preload_tasks: list[asyncio.Task] = []
    if os.getenv("PRELOAD_MODELS", "0") == "1":
        if LOAD_ZIMAGE and cuda_detail is None:
            preload_tasks.append(asyncio.create_task(_preload_model_after_startup("zimage")))
        if LOAD_CHRONOS:
            preload_tasks.append(asyncio.create_task(_preload_model_after_startup("chronos2")))

    logger.info("CuteDSL Inference Server ready")
    try:
        yield
    finally:
        if zimage_dynamic_batcher is not None:
            await zimage_dynamic_batcher.close()
            zimage_dynamic_batcher = None
        for task in preload_tasks:
            if not task.done():
                task.cancel()
        if preload_tasks:
            await asyncio.gather(*preload_tasks, return_exceptions=True)
        await tg_client.aclose()
        logger.info("Shutdown complete")


try:
    from fastapi.responses import ORJSONResponse as _DefaultResponse
except ImportError:
    _DefaultResponse = JSONResponse

app = FastAPI(title="CuteDSL Inference Server", lifespan=lifespan, default_response_class=_DefaultResponse)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=1000)


def _sanitize_query(query_string: bytes) -> str:
    pairs = []
    for key, value in parse_qsl(query_string.decode("utf-8", errors="replace"), keep_blank_values=True):
        if key.lower() in {"prompt", "secret", "api_key", "key", "token"}:
            value = "<redacted>"
        pairs.append((key, value))
    return urlencode(pairs)


def _request_prompt_info(request: Request) -> dict:
    prompt = getattr(request.state, "prompt_text", None)
    if prompt is None:
        prompt = request.query_params.get("prompt", "")
    return {
        "prompt_len": len(prompt),
        "prompt_words": len(prompt.split()) if prompt else 0,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16] if prompt else "",
    }


def _remember_request_prompt(request: Request, prompt: str):
    request.state.prompt_text = prompt


def _remember_request_inference_params(request: Request, **params) -> None:
    """Keep non-sensitive generation settings for reproducible error events."""
    request.state.inference_params = params


def _validate_prompt_text(prompt: str, field_name: str = "prompt") -> str:
    if not prompt or not prompt.strip():
        raise ValueError(f"{field_name} must not be empty")
    # The native image backend accepts a C string. Embedded controls (notably
    # NUL) can truncate or corrupt that string after JSON decoding and have
    # caused stable-diffusion.cpp's text conditioner to abort the whole worker.
    # Keep ordinary multiline prompts, but reject non-text controls and lone
    # UTF-16 surrogates before they reach any inference backend.
    if any(
        unicodedata.category(char) in {"Cc", "Cs"} and char not in "\t\n\r"
        for char in prompt
    ):
        raise ValueError(f"{field_name} contains unsupported control characters")
    return prompt


def _require_nonempty_prompt(prompt: str, field_name: str = "prompt"):
    try:
        _validate_prompt_text(prompt, field_name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


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
        "inference": getattr(request.state, "inference_params", {}),
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


def _json_safe(value):
    """Recursively make error payloads safe for Starlette's strict encoder."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return str(value)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request.state.request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    response = await call_next(request)
    response.headers["x-request-id"] = request.state.request_id
    return response


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    # Validation errors echo the rejected input. FastAPI's default response
    # therefore contains NaN/Infinity when those tokens arrive in JSON, which
    # makes Starlette's allow_nan=False serializer raise a second exception.
    return JSONResponse(
        status_code=422,
        content={
            "detail": _json_safe(exc.errors()),
            "request_id": getattr(request.state, "request_id", ""),
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code >= 500:
        _log_request_error(request, exc, exc.status_code, detail=str(exc.detail))
    return JSONResponse(
        status_code=exc.status_code,
        content=_json_safe({"detail": exc.detail, "request_id": getattr(request.state, "request_id", "")}),
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
    if IMAGE_API_SECRETS and secret not in IMAGE_API_SECRETS:
        raise HTTPException(403, "invalid secret")


def _require_http_url(value: str, field_name: str = "url"):
    try:
        parsed = urlparse(value)
    except ValueError as e:
        raise HTTPException(400, f"{field_name} is not a valid URL") from e
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(400, f"{field_name} must be an http(s) URL")


def _is_public_ip_address(host: str) -> bool:
    try:
        addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise HTTPException(400, "image_url host could not be resolved")

    for address in addresses:
        ip_text = address[4][0]
        try:
            ip = ipaddress.ip_address(ip_text)
        except ValueError:
            raise HTTPException(400, "image_url resolved to an invalid address")
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False
    return True


def _validate_remote_image_url(value: str, field_name: str = "image_url"):
    _require_http_url(value, field_name)
    parsed = urlparse(value)
    try:
        host = parsed.hostname
        # Accessing port makes urllib reject malformed/out-of-range ports here,
        # before the HTTP client can turn them into an unhandled InvalidURL.
        parsed.port
    except ValueError as e:
        raise HTTPException(400, f"{field_name} is not a valid URL") from e
    if not host:
        raise HTTPException(400, f"{field_name} must include a host")
    # Numeric dotted hosts with leading zeroes have inconsistent octal/decimal
    # interpretations across URL parsers and resolvers. Reject them instead of
    # letting the fetch client fail or accidentally resolve one as loopback.
    if all(part.isdigit() for part in host.split(".")) and len(host.split(".")) == 4:
        try:
            ipaddress.IPv4Address(host)
        except ipaddress.AddressValueError as e:
            raise HTTPException(400, f"{field_name} has an invalid IPv4 address") from e
    if not ALLOW_PRIVATE_IMAGE_URLS and not _is_public_ip_address(host):
        raise HTTPException(400, f"{field_name} must resolve to a public address")


def _load_image_bytes(image_bytes: bytes, source_name: str = "image") -> Image.Image:
    if not image_bytes:
        raise HTTPException(400, f"{source_name} is empty")
    if len(image_bytes) > REMOTE_IMAGE_MAX_BYTES:
        raise HTTPException(413, f"{source_name} is too large")
    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            source.load()
            return source.convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as e:
        raise HTTPException(400, f"{source_name} did not contain a valid image") from e


def _load_base64_image(image_base64: str) -> Image.Image:
    # Bound the encoded payload before allocating the decoded copy. The small
    # allowance covers padding and whitespace used by wrapped base64 encoders.
    if len(image_base64) > REMOTE_IMAGE_MAX_BYTES * 2:
        raise HTTPException(413, "image_base64 is too large")
    try:
        image_bytes = base64.b64decode(image_base64, validate=True)
    except (binascii.Error, ValueError, TypeError) as e:
        raise HTTPException(400, "image_base64 is not valid base64") from e
    return _load_image_bytes(image_bytes, "image_base64")


def _load_remote_image(image_url: str) -> Image.Image:
    try:
        current_url = image_url
        for redirect_count in range(REMOTE_IMAGE_MAX_REDIRECTS + 1):
            _validate_remote_image_url(current_url, "image_url")
            with requests.get(
                current_url,
                stream=True,
                timeout=REMOTE_IMAGE_TIMEOUT_SECONDS,
                headers={"User-Agent": "CuteDSL inference image fetcher"},
                allow_redirects=False,
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location", "")
                    if not location:
                        raise HTTPException(400, "image_url returned a redirect without a location")
                    if redirect_count >= REMOTE_IMAGE_MAX_REDIRECTS:
                        raise HTTPException(400, "image_url returned too many redirects")
                    current_url = urljoin(current_url, location)
                    continue
                if response.status_code >= 400:
                    raise HTTPException(400, f"image_url returned HTTP {response.status_code}")
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if content_type and not content_type.startswith("image/"):
                    raise HTTPException(400, "image_url did not return an image")

                buf = io.BytesIO()
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    buf.write(chunk)
                    if buf.tell() > REMOTE_IMAGE_MAX_BYTES:
                        raise HTTPException(413, "image_url image is too large")
                return _load_image_bytes(buf.getvalue(), "image_url")
        raise HTTPException(400, "image_url returned too many redirects")
    except HTTPException:
        raise
    except requests.exceptions.RequestException as e:
        raise HTTPException(400, f"image_url could not be fetched: {type(e).__name__}") from e


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.post("/admin/unload")
def admin_unload(model: str | None = None):
    """Force-unload a model (or all) and free GPU memory immediately."""
    if model is None and model_manager.hold_remaining() <= 0:
        # Peer lifecycle managers first acquire /admin/hold and then poll this
        # endpoint until all models are gone. If hold acquisition was rejected,
        # allowing their fallback poll to unload later would bypass the atomic
        # admission decision and recreate the handoff race.
        raise HTTPException(
            409,
            "GPU model unload requires an active admission hold",
            headers={"Retry-After": "2"},
        )
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
        "hold_seconds_remaining": round(model_manager.hold_remaining(), 1),
    }


@app.post("/admin/hold")
def admin_hold(seconds: float = 600):
    """Atomically pause idle GPU admission for a peer boot.

    A handoff is not acquired when HTTP work is already admitted. Returning a
    retryable conflict is essential: reporting success and then skipping the
    unload leaves the image endpoint paused even though the peer never received
    the GPU.
    """
    remaining, busy_models = model_manager.try_hold(seconds)
    if remaining is None:
        busy = ", ".join(
            f"{model_name}={count}" for model_name, count in sorted(busy_models.items())
        )
        raise HTTPException(
            409,
            f"GPU model handoff is busy ({busy}); retry shortly",
            headers={"Retry-After": "2"},
        )
    try:
        dropped = model_manager.force_unload()
    except BaseException:
        model_manager.release_hold()
        raise
    loaded = sorted(model_manager._loaded)
    if loaded:
        # Defensive invariant: a successful hold must actually make the GPU
        # models releasable. Never strand admission if an unknown user remains.
        model_manager.release_hold()
        raise HTTPException(
            409,
            f"GPU model handoff could not unload: {', '.join(loaded)}",
            headers={"Retry-After": "2"},
        )
    return {
        "status": "held",
        "hold_seconds_remaining": round(remaining, 1),
        "dropped": dropped,
        "loaded": loaded,
    }


@app.post("/admin/release")
def admin_release():
    """Release a peer's bounded GPU admission hold."""
    model_manager.release_hold()
    return {
        "status": "released",
        "hold_seconds_remaining": 0.0,
        "loaded": sorted(model_manager._loaded),
    }


@app.get("/health")
@app.get("/healthz")
def health(request: Request):
    gpu_queue = gpu_semaphore.snapshot() if gpu_semaphore is not None else {}
    cuda_detail = _cuda_unavailable_detail()
    # Readiness probes are the only traffic an unhealthy/idle worker may see.
    # Let them initiate process replacement too, instead of waiting for a real
    # image request to discover the already-poisoned CUDA context.
    if (
        request.url.path == "/healthz"
        and cuda_detail
        and ZIMAGE_REQUIRE_CUDA_READY
        and LOAD_ZIMAGE
        and DEVICE.startswith("cuda")
    ):
        _schedule_cuda_process_restart()
    payload = {
        "status": "degraded" if cuda_detail else "ok",
        "cuda": {
            "healthy": cuda_detail is None,
            "detail": cuda_detail,
            "fatal_fault_at": _cuda_runtime_fault_at,
        },
        "models": {
            "zimage": model_manager.is_loaded("zimage"),
            "chronos2": model_manager.is_loaded("chronos2"),
            "zimage_enabled": LOAD_ZIMAGE,
            "zimage_native_fallback_enabled": bool(ZIMAGE_NATIVE_FALLBACK_URL),
            "zimage_native_fallback_active": _should_use_native_zimage_fallback("health"),
            "zimage_fal_fallback_enabled": ZIMAGE_FAL_FALLBACK_ENABLED,
            "zimage_native_circuit_open": (
                time.monotonic() < _native_fallback_disabled_until
            ),
            "chronos2_enabled": LOAD_CHRONOS,
            "nsfw": nsfw_classifier is not None,
            "text_encoder": _zimage_text_encoder_placement
            or ("cpu/fp32" if ZIMAGE_TEXT_ENCODER_DEVICE == "cpu" else None),
        },
        "gpu_queue": gpu_queue,
        "dynamic_batching": {
            **(
                zimage_dynamic_batcher.snapshot()
                if zimage_dynamic_batcher is not None
                else {
                    "enabled": False,
                    "window_ms": BATCH_WINDOW_MS,
                    "max_batch_size": ZIMAGE_DYNAMIC_BATCH_MAX_SIZE,
                    "pending": 0,
                }
            ),
            "max_pixels": ZIMAGE_DYNAMIC_BATCH_MAX_PIXELS,
            "reserve_mb": ZIMAGE_DYNAMIC_BATCH_RESERVE_MB,
            "extra_mb_per_image": ZIMAGE_DYNAMIC_BATCH_EXTRA_MB,
            "broker_enabled": bool(ZIMAGE_VRAM_BROKER_URL),
            **_zimage_batch_runtime_snapshot(),
        },
        "gpu_admission_hold_seconds": round(model_manager.hold_remaining(), 1),
        "nvfp4": ENABLE_NVFP4,
        "precision": PRECISION,
        "zimage_use_cute": ZIMAGE_USE_CUTE,
        "zimage_cpu_offload": _zimage_cpu_offload_enabled(),
        "zimage_cpu_offload_mode": _zimage_cpu_offload_mode(),
        "zimage_effective_cpu_offload": _zimage_effective_cpu_offload,
        "zimage_load_strategy": _zimage_load_strategy,
        "zimage_direct_device_map": ZIMAGE_DIRECT_DEVICE_MAP,
        "zimage_no_offload_min_free_mb": ZIMAGE_NO_OFFLOAD_MIN_FREE_MB,
        "zimage_compile_mode": _get_zimage_compile_mode() or "eager",
        "latent_teleport": {
            "enabled": LATENT_TELEPORT_ENABLED,
            "cache_dir": LATENT_TELEPORT_CACHE_DIR,
            "start_step": LATENT_TELEPORT_START_STEP,
            "max_entries_per_resolution": LATENT_TELEPORT_MAX_ENTRIES_PER_RESOLUTION,
            "max_gib_per_resolution": LATENT_TELEPORT_MAX_GIB_PER_RESOLUTION,
            "prune_interval_seconds": LATENT_TELEPORT_PRUNE_INTERVAL_SECONDS,
            "approx_min_similarity": LATENT_TELEPORT_APPROX_MIN_SIM,
            "min_free_mb": LATENT_TELEPORT_MIN_FREE_MB,
            "latent_save": LATENT_SAVE,
        },
        "prompt_embedding_cache": _zimage_prompt_cache_snapshot(),
        "device": DEVICE,
        "dtype": DTYPE_STR,
    }
    # /health remains a liveness endpoint for CPU proxy/forecast routes;
    # /healthz is readiness and must not route image traffic to a dead GPU.
    readiness_unavailable = request.url.path == "/healthz" and cuda_detail is not None
    return JSONResponse(
        status_code=503 if readiness_unavailable else 200,
        content=_json_safe(payload),
        headers={"Retry-After": "30"} if readiness_unavailable else None,
    )


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
            # This small safety model is latency-tolerant and shares the host
            # with several much larger CUDA services. Loading it on GPU raced
            # other tenants and produced a 500 while only 35 MiB was free.
            # CPU placement is deterministic and leaves image-generation VRAM
            # untouched even when global CUDA admission changes concurrently.
            device=NSFW_DEVICE,
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
async def nsfw_detect(req: NSFWRequest, secret: str = ""):
    """Classify an image as NSFW or not. Model loads on demand and unloads after."""
    _check_secret(secret)
    if req.image_base64:
        image = _load_base64_image(req.image_base64)
    elif req.image_url:
        image = await asyncio.get_event_loop().run_in_executor(
            None, _load_remote_image, req.image_url
        )
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
    secret: str = "",
):
    """Classify an uploaded image as NSFW or not."""
    _check_secret(secret)
    content = await image_file.read()
    image = _load_image_bytes(content, "image_file")

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


class AestheticRequest(BaseModel):
    image_base64: Optional[str] = None
    image_url: Optional[str] = None


@app.post("/aesthetic_score")
async def aesthetic_score(req: AestheticRequest, secret: str = ""):
    """Score image aesthetics (LAION predictor, ~1-10). CPU by default."""
    _check_secret(secret)
    if req.image_base64:
        image = _load_base64_image(req.image_base64)
    elif req.image_url:
        image = await asyncio.get_event_loop().run_in_executor(
            None, _load_remote_image, req.image_url
        )
    else:
        raise HTTPException(400, "image_url or image_base64 required")
    scores = await asyncio.get_event_loop().run_in_executor(
        None, aesthetic_score_images, [image]
    )
    if not scores:
        raise HTTPException(503, "aesthetic scorer unavailable")
    return {"aesthetic_score": round(scores[0], 3)}


# ---------------------------------------------------------------------------
# Z-Image (text-to-image) with auto LoRA selection
# ---------------------------------------------------------------------------

class ZImageRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    width: int = ZIMAGE_DEFAULT_WIDTH
    height: int = ZIMAGE_DEFAULT_HEIGHT
    seed: int = 0
    num_inference_steps: int = ZIMAGE_DEFAULT_STEPS
    guidance_scale: float = ZIMAGE_DEFAULT_GUIDANCE
    lora_id: Optional[str] = None
    auto_lora: bool = True
    # Callers such as RA1 may already have applied the catalog template. Keep
    # the explicit LoRA activation while avoiding a second trigger/template.
    prompt_is_final: bool = False
    lora_scale: float = 1.0
    low_priority: bool = False
    quality_retry: bool = True
    enhance_prompt: bool = True
    best_of: int = Field(1, ge=1, le=4)
    score_aesthetic: bool = False
    early_exit: Optional[float] = Field(None, ge=0.0, le=1.0)
    early_exit_min_steps: Optional[int] = Field(None, ge=1)
    teleport: bool = False
    # None => follow LATENT_TELEPORT_APPROX_DEFAULT. Approximate replay reuses a
    # *different* prompt's latent, so it stays opt-in on the paid path.
    teleport_approx: Optional[bool] = None
    teleport_approx_min_sim: Optional[float] = Field(None, ge=0.0, le=1.0)

    @field_validator("prompt")
    @classmethod
    def _validate_prompt(cls, value: str) -> str:
        return _validate_prompt_text(value)


_lora_cache_dir = os.path.join(os.path.dirname(__file__), ".lora_cache")


_lora_swapper = None
_lora_swapper_lock = threading.Lock()
_native_fallback_circuit_lock = threading.Lock()
_native_fallback_disabled_until = 0.0


def _get_lora_swapper(transformer):
    """Lazily build a cuteloras swapper over the fixtures catalog (sticky hot-swapping)."""
    global _lora_swapper
    with _lora_swapper_lock:
        if _lora_swapper is None or _lora_swapper.transformer is not transformer:
            from cuteloras import LoRARecord, LoRARegistry, LoRASwapper
            from lora_fixtures import get_all_zimage_loras

            registry = LoRARegistry(cache_dir=_lora_cache_dir)
            for lora in get_all_zimage_loras():
                registry.add(LoRARecord(
                    id=lora.id,
                    name=lora.name,
                    url=lora.url,
                    trigger_word=lora.trigger_word,
                    template=lora.template or "{prompt}",
                    keywords=lora.keywords,
                    negative_keywords=lora.negative_keywords,
                    is_adult=lora.is_adult,
                    scale=lora.scale,
                ))
            _lora_swapper = LoRASwapper(transformer, registry)
        return _lora_swapper


def _activate_lora(pipe, lora, lora_scale: float = 1.0):
    """Activate a single LoRA on the pipeline transformer; sticky across requests."""
    swapper = _get_lora_swapper(pipe.transformer)
    if lora.id not in swapper.registry:
        from cuteloras import LoRARecord
        swapper.registry.add(LoRARecord(id=lora.id, name=lora.name, url=lora.url,
                                        scale=getattr(lora, "scale", 1.0)))
    return swapper.activate([(lora.id, lora_scale)])


def _deactivate_loras(pipe):
    """Restore pristine base weights if any LoRA is active."""
    if _lora_swapper is not None and _lora_swapper.transformer is pipe.transformer:
        _lora_swapper.deactivate()


def _prewarm_zimage_loras(pipe, lora_ids: tuple[str, ...]) -> None:
    """Pay first-merge CUDA setup during background preload, then restore base."""
    from lora_fixtures import get_lora_by_id

    started = time.perf_counter()
    warmed = []
    try:
        for lora_id in lora_ids:
            lora = get_lora_by_id(lora_id)
            if lora is None:
                logger.warning("Z-Image LoRA prewarm skipped unknown id: %s", lora_id)
                continue
            _activate_lora(pipe, lora, lora_scale=_effective_lora_scale(lora))
            warmed.append(lora_id)
    except Exception as exc:
        logger.warning("Z-Image LoRA prewarm failed after %s: %s", warmed, exc)
    finally:
        _deactivate_loras(pipe)
    logger.info(
        "Z-Image LoRA prewarm complete: ids=%s elapsed=%.2fs",
        warmed,
        time.perf_counter() - started,
    )


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
    if ENABLE_NVFP4:
        if req.lora_id:
            logger.warning("lora_id '%s' skipped because NVFP4 direct LoRA mutation is unsupported", req.lora_id)
        return None, req.prompt

    from lora_fixtures import get_lora_by_id, apply_lora_template

    if req.lora_id:
        lora = get_lora_by_id(req.lora_id)
        if lora:
            final_prompt = req.prompt if req.prompt_is_final else apply_lora_template(lora, req.prompt)
            return lora, final_prompt
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

    # Ensure pipeline is on GPU (may have been displaced by NSFW model).
    # With the text encoder pinned to CPU, a whole-pipeline .to(DEVICE) would
    # drag its ~8 GB back onto the GPU (and stall for minutes when those pages
    # are swapped) — move only the GPU-resident components in that mode.
    if hasattr(text2img_pipe, 'to') and not hasattr(text2img_pipe, '_offload_gpu_id'):
        try:
            if _text_encoder_on_cpu():
                for _comp_name in ("transformer", "vae"):
                    _comp = getattr(text2img_pipe, _comp_name, None)
                    if _comp is not None:
                        _comp.to(DEVICE)
            else:
                text2img_pipe.to(DEVICE)
        except Exception:
            pass

    lora, final_prompt = _resolve_lora(req)

    width = (req.width // 64) * 64 or 1024
    height = (req.height // 64) * 64 or 1024

    t0 = time.time()
    generator = _make_pipeline_generator(text2img_pipe, req.seed)

    # Reset the scheduler state between calls — the vanilla diffusers
    # ZImagePipeline doesn't always re-init step_index, so a leaked _step_index
    # from the previous call causes IndexError on sigmas[N+1].
    _reset_zimage_scheduler(text2img_pipe)

    teleport_meta = None
    if req.teleport and LATENT_TELEPORT_ENABLED and lora is None and req.num_inference_steps > 1:
        resume_step = max(1, min(LATENT_TELEPORT_START_STEP, req.num_inference_steps - 1))
        capture_step = resume_step - 1
        cache = _get_latent_teleport_cache(width, height)
        unit = _latent_teleport_unit(
            final_prompt,
            width,
            height,
            req.num_inference_steps,
            req.seed,
            req.guidance_scale,
        )
        cached_latent = cache.load_latent(unit, capture_step)
        cached_prompt_embedding = (
            cache.load_text_embedding_full(unit) if cached_latent is not None else None
        )
        teleport_meta = {
            "enabled": True,
            "cache_hit": cached_latent is not None,
            "capture_step": capture_step,
            "resume_step": resume_step,
            "total_steps": req.num_inference_steps,
        }
        if cached_latent is not None:
            try:
                from latentteleport.refine import refine_from_latent

                replay_started = time.time()
                with _nvtx_range("zimage.openai_teleport_replay"):
                    image = refine_from_latent(
                        text2img_pipe,
                        cached_latent,
                        final_prompt,
                        None,
                        resume_step,
                        prompt_embeds=(
                            [cached_prompt_embedding]
                            if cached_prompt_embedding is not None
                            else None
                        ),
                        num_total_steps=req.num_inference_steps,
                        height=height,
                        width=width,
                        guidance_scale=req.guidance_scale,
                        seed=req.seed,
                        device=DEVICE,
                    )
                elapsed = time.time() - replay_started
                buf = io.BytesIO()
                image.save(buf, format="WEBP", quality=90)
                teleport_meta.update({
                    "method": "exact_prompt_latent_replay",
                    "inference_time_ms": int(elapsed * 1000),
                })
                return {
                    "image_base64": base64.b64encode(buf.getvalue()).decode(),
                    "format": "webp",
                    "width": width,
                    "height": height,
                    "inference_time_ms": int(elapsed * 1000),
                    "seed": req.seed,
                    "prompt_used": final_prompt,
                    "lora": None,
                    "prompt_embedding_cache": {
                        "enabled": ZIMAGE_PROMPT_CACHE_SIZE > 0,
                        "hit": cached_prompt_embedding is not None,
                        "encode_ms": 0,
                        "source": "latent_cache" if cached_prompt_embedding is not None else None,
                    },
                    "pipeline_timing": None,
                    "early_exit": None,
                    "teleport": teleport_meta,
                }
            except Exception as exc:
                logger.warning(
                    "OpenAI latent replay failed; falling back to full generation: %s", exc
                )
                teleport_meta.update({
                    "cache_hit": False,
                    "fallback_reason": type(exc).__name__,
                })

        approx_enabled = (
            req.teleport_approx if req.teleport_approx is not None else LATENT_TELEPORT_APPROX_DEFAULT
        )
        teleport_meta["approx_enabled"] = approx_enabled
        if not teleport_meta.get("cache_hit") and approx_enabled:
            approx = _teleport_approximate_replay(
                text2img_pipe,
                cache,
                final_prompt,
                width,
                height,
                req.num_inference_steps,
                resume_step,
                capture_step,
                req.guidance_scale,
                req.seed,
                req.teleport_approx_min_sim,
            )
            if approx is not None:
                image, approx_meta = approx
                buf = io.BytesIO()
                image.save(buf, format="WEBP", quality=90)
                teleport_meta.update(approx_meta)
                return {
                    "image_base64": base64.b64encode(buf.getvalue()).decode(),
                    "format": "webp",
                    "width": width,
                    "height": height,
                    "inference_time_ms": approx_meta["inference_time_ms"],
                    "seed": req.seed,
                    "prompt_used": final_prompt,
                    "lora": None,
                    "prompt_embedding_cache": {
                        "enabled": ZIMAGE_PROMPT_CACHE_SIZE > 0,
                        "hit": False,
                        "encode_ms": approx_meta.get("encode_ms", 0),
                        "source": "teleport_approx",
                    },
                    "pipeline_timing": None,
                    "early_exit": None,
                    "teleport": teleport_meta,
                }

    pipe_kwargs = dict(
        prompt=final_prompt,
        width=width,
        height=height,
        num_inference_steps=req.num_inference_steps,
        guidance_scale=req.guidance_scale,
        generator=generator,
    )
    pipe_kwargs, prompt_cache_meta = _prepare_zimage_prompt_embeddings(text2img_pipe, pipe_kwargs)

    early_exit_threshold = req.early_exit if req.early_exit is not None else (ZIMAGE_EARLY_EXIT or None)
    # A teleport miss primes an exact latent. Approximate early-exit latents
    # are deliberately not cached, so run the full schedule on that first hit.
    if teleport_meta is not None and not teleport_meta.get("cache_hit"):
        early_exit_threshold = None
    early_exit_min_steps = req.early_exit_min_steps or ZIMAGE_EARLY_EXIT_MIN_STEPS
    exit_info: dict = {}
    captured = {}
    pipeline_timing = {}
    if lora:
        try:
            _activate_lora(text2img_pipe, lora, lora_scale=_effective_lora_scale(lora, req.lora_scale))
            result, _ = _run_zimage_capture_multi(
                text2img_pipe, pipe_kwargs, (), pipeline_timing,
                early_exit=early_exit_threshold,
                early_exit_min_steps=early_exit_min_steps,
                exit_info=exit_info,
                log_prompt=final_prompt,
            )
        except Exception as e:
            logger.warning("LoRA generation failed (%s), retrying without: %s", lora.id, e)
            _deactivate_loras(text2img_pipe)
            pipeline_timing = {}
            result, _ = _run_zimage_capture_multi(text2img_pipe, pipe_kwargs, (), pipeline_timing)
            lora = None
    else:
        _deactivate_loras(text2img_pipe)
        capture = _capture_steps_for(req.num_inference_steps) if _latent_save_active() else ()
        result, captured = _run_zimage_capture_multi(
            text2img_pipe, pipe_kwargs, capture, pipeline_timing,
            early_exit=early_exit_threshold,
            early_exit_min_steps=early_exit_min_steps,
            exit_info=exit_info,
            log_prompt=final_prompt,
        )

    image = result.images[0]
    elapsed = time.time() - t0

    if exit_info.get("exited_after_step"):
        # threshold early-exit produces an approximate final latent; do not
        # poison the exact-replay teleport cache with it. noop-step skips are
        # bitwise-identical, so their captures stay valid.
        captured = {}
    if captured and not lora:
        cached_conditioning = (pipe_kwargs.get("prompt_embeds") or [None])[0]
        _persist_generation_latents(final_prompt, req.seed, req.num_inference_steps,
                                    width, height, req.guidance_scale, captured,
                                    text_embedding=cached_conditioning)

    buf = io.BytesIO()
    image.save(buf, format="WEBP", quality=90)
    img_bytes = buf.getvalue()
    img_b64 = base64.b64encode(img_bytes).decode()

    lora_info = {"lora_id": lora.id, "lora_name": lora.name} if lora else None
    logger.info("zimage: %dx%d in %.2fs (steps=%d, lora=%s)",
                width, height, elapsed, req.num_inference_steps,
                lora.id if lora else "none")

    response = {
        "image_base64": img_b64,
        "format": "webp",
        "width": width,
        "height": height,
        "inference_time_ms": int(elapsed * 1000),
        "seed": req.seed,
        "prompt_used": final_prompt,
        "lora": lora_info,
        "prompt_embedding_cache": prompt_cache_meta,
        "pipeline_timing": pipeline_timing,
        "early_exit": exit_info or None,
    }
    if teleport_meta is not None:
        teleport_meta.update({
            "method": "full_generation_cached_latent",
            "inference_time_ms": int(elapsed * 1000),
        })
        response["teleport"] = teleport_meta
    return response


def _copy_zimage_request(req: ZImageRequest, prompt: str) -> ZImageRequest:
    if hasattr(req, "model_copy"):
        return req.model_copy(update={"prompt": prompt})
    return req.copy(update={"prompt": prompt})


def _decode_result_image(result: dict) -> Image.Image | None:
    try:
        return Image.open(io.BytesIO(base64.b64decode(result["image_base64"]))).convert("RGB")
    except Exception as e:
        logger.warning("zimage result decode failed: %s", e)
        return None


def _native_zimage_request(req: ZImageRequest, prompt: str) -> tuple[dict, object | None]:
    """Build the canonical native request while preserving CuteDSL LoRA routing."""
    if lora_engine is None:
        _init_lora_engine()
    resolved_req = _copy_zimage_request(req, prompt)
    lora, final_prompt = _resolve_lora(resolved_req)
    width = (req.width // 64) * 64 or 1024
    height = (req.height // 64) * 64 or 1024
    payload = {
        "model": "zimage-turbo",
        "prompt": final_prompt,
        "width": width,
        "height": height,
        "steps": req.num_inference_steps,
        "guidance_scale": req.guidance_scale,
        "seed": req.seed,
        "teleport": bool(req.teleport and lora is None),
        "response_format": "b64_json",
        # Private routing metadata. _call_native_zimage removes this before
        # serialising the OpenAI-compatible request body.
        "_omniserve_tier": "background" if req.low_priority else "paid",
    }
    if req.teleport_approx:
        logger.info("native fallback ignores approximate teleport and uses exact-key replay only")
    if lora is not None:
        lora_filename = unquote(os.path.basename(urlparse(lora.url).path))
        if not lora_filename:
            raise HTTPException(503, f"native LoRA {lora.id} has no cache filename")
        payload.update({
            "lora_id": lora.id,
            "lora_filename": lora_filename,
            "lora_scale": _effective_lora_scale(lora, req.lora_scale),
        })
    return payload, lora


def _call_native_zimage(payload: dict) -> dict:
    """Call the co-resident native backend with bounded transient retry."""
    tier = str(payload.get("_omniserve_tier") or "paid").strip().lower()
    if tier not in {"paid", "sub", "free", "background"}:
        tier = "paid"
    request_payload = {
        key: value for key, value in payload.items() if key != "_omniserve_tier"
    }
    headers = {
        "Content-Type": "application/json",
        "X-Omniserve-Internal": "local",
        "X-Omniserve-Tier": tier,
    }
    if IMAGE_API_SECRET:
        headers["Authorization"] = f"Bearer {IMAGE_API_SECRET}"

    last_error = "native fallback failed"
    transient_statuses = {429, 500, 502, 503, 504}
    attempt = 0
    # Capacity, generation and restart errors can alternate during one outage.
    # Measure every recovery grace from the first failure, not each new type.
    recovery_started = None
    headroom_cache_reclaimed = False
    while True:
        try:
            response = requests.post(
                f"{ZIMAGE_NATIVE_FALLBACK_URL}/v1/images/generations",
                json=request_payload,
                headers=headers,
                timeout=max(1.0, ZIMAGE_NATIVE_FALLBACK_TIMEOUT_SECONDS),
            )
            if response.status_code >= 400:
                message = ""
                try:
                    error_document = response.json()
                    error_value = error_document.get("error") if isinstance(error_document, dict) else None
                    if isinstance(error_value, dict):
                        message = str(error_value.get("message") or "")
                    elif error_value is not None:
                        message = str(error_value)
                except (ValueError, TypeError):
                    pass
                message = " ".join(message.split())[:240]
                last_error = f"native fallback returned HTTP {response.status_code}"
                if message:
                    last_error = f"{last_error}: {message}"
                # Another managed GPU workload can temporarily keep the native
                # backend below its explicit safety floor. The old generic
                # 100-ms retry could not outlive even a short model residency,
                # so otherwise healthy image requests failed immediately.
                # Queue only this precise capacity response; arbitrary native
                # 5xx failures retain the tightly bounded generic retry below.
                headroom_failure = (
                    response.status_code == 503
                    and "image generation needs at least" in message
                    and "free GPU memory" in message
                )
                admission_timeout_failure = (
                    response.status_code == 503
                    and message == "admission timeout; retry"
                )
                if headroom_failure:
                    headroom_grace_seconds = (
                        ZIMAGE_NATIVE_BACKGROUND_HEADROOM_GRACE_SECONDS
                        if tier == "background"
                        else ZIMAGE_NATIVE_HEADROOM_GRACE_SECONDS
                    )
                    now = time.monotonic()
                    if recovery_started is None:
                        recovery_started = now
                    headroom_deadline = recovery_started + headroom_grace_seconds
                    if now < headroom_deadline:
                        # Reclaim our unused allocator blocks before waiting on
                        # another tenant. Doing this only in the generic retry
                        # below leaves reclaimable VRAM idle for the entire
                        # capacity grace (60 seconds in production). Never
                        # unload a resident pipeline or alter the request.
                        if not headroom_cache_reclaimed:
                            headroom_cache_reclaimed = True
                            if not model_manager.is_loaded("zimage"):
                                _clear_torch_cuda_caches()
                        delay = min(
                            ZIMAGE_NATIVE_HEADROOM_POLL_SECONDS,
                            headroom_deadline - now,
                        )
                        logger.warning(
                            "%s; waiting %.1fs for managed GPU capacity",
                            last_error,
                            delay,
                        )
                        time.sleep(delay)
                        continue
                # stable-diffusion.cpp currently reports CUDA allocation and
                # conditioner failures through this one opaque native error.
                # They can happen after the admission check when another GPU
                # tenant grows during denoising. Keep only that exact runtime
                # failure attached to a bounded recovery window; detailed 5xx
                # errors and all client errors retain the generic retry below.
                generation_capacity_failure = (
                    response.status_code == 500
                    and message == "image generation failed"
                )
                generation_failure_grace_seconds = (
                    ZIMAGE_NATIVE_BACKGROUND_HEADROOM_GRACE_SECONDS
                    if tier == "background"
                    else ZIMAGE_NATIVE_GENERATION_FAILURE_GRACE_SECONDS
                )
                if generation_capacity_failure and generation_failure_grace_seconds:
                    now = time.monotonic()
                    if recovery_started is None:
                        recovery_started = now
                    generation_failure_deadline = (
                        recovery_started + generation_failure_grace_seconds
                    )
                    if now < generation_failure_deadline:
                        if not model_manager.is_loaded("zimage"):
                            _clear_torch_cuda_caches()
                        delay = min(
                            ZIMAGE_NATIVE_GENERATION_FAILURE_POLL_SECONDS,
                            generation_failure_deadline - now,
                        )
                        logger.warning(
                            "%s; waiting %.1fs for transient native GPU recovery",
                            last_error,
                            delay,
                        )
                        time.sleep(delay)
                        continue
                if (
                    response.status_code in transient_statuses
                    and attempt < ZIMAGE_NATIVE_FALLBACK_RETRIES
                    and not (tier == "background" and admission_timeout_failure)
                    # The dedicated recovery loop has already spent its
                    # budget. Do not start another potentially slow native
                    # request via the generic retry after that deadline.
                    and not (headroom_failure and headroom_grace_seconds > 0)
                    and not (
                        generation_capacity_failure
                        and generation_failure_grace_seconds > 0
                    )
                ):
                    # This worker can retain unreferenced CUDA allocations after
                    # a failed local training/load attempt even while its BF16
                    # inference model is cold.  The co-resident native backend
                    # then fails its first scratch allocation.  Reclaim those
                    # allocations before retrying; a plain sleep cannot change
                    # the memory condition which produced the 500.
                    if not model_manager.is_loaded("zimage"):
                        before_mb = _cuda_free_mb()
                        _clear_torch_cuda_caches()
                        after_mb = _cuda_free_mb()
                        logger.warning(
                            "%s; reclaimed local CUDA cache (%d -> %d MB free) before retry",
                            last_error,
                            before_mb,
                            after_mb,
                        )
                    else:
                        logger.warning("%s; retrying once", last_error)
                    time.sleep(0.1)
                    attempt += 1
                    continue
                background_backpressure = tier == "background" and (
                    headroom_failure
                    or generation_capacity_failure
                    or admission_timeout_failure
                )
                raise HTTPException(
                    429 if background_backpressure else (
                        503 if response.status_code in transient_statuses else 502
                    ),
                    last_error,
                    headers={"Retry-After": "15" if background_backpressure else "5"},
                )
            document = response.json()
            rows = document.get("data") if isinstance(document, dict) else None
            row = rows[0] if isinstance(rows, list) and rows else None
            encoded = row.get("b64_json") if isinstance(row, dict) else None
            if not isinstance(encoded, str) or not encoded:
                raise ValueError("response has no b64_json image")
            image_bytes = base64.b64decode(encoded, validate=True)
            with Image.open(io.BytesIO(image_bytes)) as image:
                actual_width, actual_height = image.size
                image_format = (image.format or row.get("format") or "webp").lower()
            expected = (int(request_payload["width"]), int(request_payload["height"]))
            if (actual_width, actual_height) != expected:
                raise ValueError(
                    f"response dimensions {actual_width}x{actual_height} do not match "
                    f"requested {expected[0]}x{expected[1]}"
                )
            return {
                "encoded": encoded,
                "image_bytes": image_bytes,
                "format": image_format,
                "width": actual_width,
                "height": actual_height,
                "inference_time_ms": int(row.get("inference_time_ms") or 0),
                "teleport": row.get("teleport"),
                "model": document.get("model"),
                "backend": "omniserve-native",
            }
        except HTTPException:
            raise
        except requests.ConnectionError as exc:
            # The native service is managed by systemd. A fatal assertion can
            # make its socket refuse connections while the model reloads; the
            # old 0.1-second retry immediately fell through to a metered Fal
            # account that may itself be unavailable. In production, allow a
            # bounded grace window for that same managed service to return.
            # Background producers already have durable retry queues, though,
            # and must not occupy the single image lane throughout that grace
            # period. Treat an unavailable native socket as the same explicit
            # backpressure used for native admission/capacity failures.
            if tier == "background":
                last_error = "native fallback is restarting"
                raise HTTPException(
                    429,
                    last_error,
                    headers={"Retry-After": "15"},
                ) from exc
            now = time.monotonic()
            if recovery_started is None:
                recovery_started = now
            restart_deadline = recovery_started + ZIMAGE_NATIVE_RESTART_GRACE_SECONDS
            if attempt < ZIMAGE_NATIVE_FALLBACK_RETRIES or now < restart_deadline:
                logger.warning(
                    "native fallback connection failed; waiting %.1fs for managed restart",
                    ZIMAGE_NATIVE_RESTART_POLL_SECONDS,
                )
                time.sleep(ZIMAGE_NATIVE_RESTART_POLL_SECONDS)
                attempt += 1
                continue
            last_error = "native fallback response failed validation (ConnectionError)"
            raise HTTPException(503, last_error, headers={"Retry-After": "5"}) from exc
        except (requests.RequestException, ValueError, TypeError, json.JSONDecodeError) as exc:
            last_error = f"native fallback response failed validation ({type(exc).__name__})"
            if attempt < ZIMAGE_NATIVE_FALLBACK_RETRIES:
                logger.warning("%s; retrying once", last_error)
                time.sleep(0.1)
                attempt += 1
                continue
            raise HTTPException(503, last_error, headers={"Retry-After": "5"}) from exc
    raise HTTPException(503, last_error, headers={"Retry-After": "5"})


def _fal_result_image_bytes(location: str) -> bytes:
    """Decode a trusted fal result URL without accepting an unbounded body."""
    if not isinstance(location, str) or not location:
        raise ValueError("fal response image has no URL")
    if location.startswith("data:"):
        header, separator, encoded = location.partition(",")
        if not separator or ";base64" not in header.lower():
            raise ValueError("fal response data URL is not base64")
        if len(encoded) > REMOTE_IMAGE_MAX_BYTES * 2:
            raise ValueError("fal response image is too large")
        return base64.b64decode(encoded, validate=True)
    parsed = urlparse(location)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("fal response image URL is invalid")
    with requests.get(
        location,
        stream=True,
        timeout=max(1.0, ZIMAGE_FAL_FALLBACK_TIMEOUT_SECONDS),
        headers={"User-Agent": "CuteDSL inference fal fallback"},
    ) as response:
        response.raise_for_status()
        output = io.BytesIO()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            output.write(chunk)
            if output.tell() > REMOTE_IMAGE_MAX_BYTES:
                raise ValueError("fal response image is too large")
        return output.getvalue()


def _call_fal_zimage(payload: dict, lora: object | None = None) -> dict:
    """Run the same Z-Image request remotely after local CUDA exhaustion."""
    steps = int(payload.get("steps") or ZIMAGE_DEFAULT_STEPS)
    if steps < 1 or steps > 8:
        raise HTTPException(503, "remote Z-Image fallback supports 1 to 8 steps")
    try:
        import fal_client
    except ImportError as exc:
        raise HTTPException(503, "remote Z-Image fallback client is unavailable") from exc

    width = int(payload["width"])
    height = int(payload["height"])
    arguments = {
        "prompt": str(payload["prompt"]),
        "image_size": {"width": width, "height": height},
        "num_inference_steps": steps,
        "seed": int(payload.get("seed") or 0),
        "sync_mode": True,
        "num_images": 1,
        "enable_safety_checker": False,
        "output_format": "webp",
        "enable_prompt_expansion": False,
    }
    endpoint = "fal-ai/z-image/turbo"
    if lora is not None:
        lora_url = str(getattr(lora, "url", "") or "")
        if not lora_url:
            raise HTTPException(503, "remote Z-Image LoRA has no URL")
        endpoint += "/lora"
        arguments["loras"] = [{
            "path": lora_url,
            "scale": _effective_lora_scale(lora, float(payload.get("lora_scale") or 1.0)),
        }]

    started = time.perf_counter()
    try:
        document = fal_client.subscribe(
            endpoint,
            arguments=arguments,
            start_timeout=max(1.0, ZIMAGE_FAL_FALLBACK_TIMEOUT_SECONDS),
            client_timeout=max(1.0, ZIMAGE_FAL_FALLBACK_TIMEOUT_SECONDS),
        )
        rows = document.get("images") if isinstance(document, dict) else None
        row = rows[0] if isinstance(rows, list) and rows else None
        location = row.get("url") if isinstance(row, dict) else None
        image_bytes = _fal_result_image_bytes(location)
        with Image.open(io.BytesIO(image_bytes)) as image:
            image.load()
            actual_width, actual_height = image.size
            image_format = (image.format or "webp").lower()
        if (actual_width, actual_height) != (width, height):
            raise ValueError(
                f"fal response dimensions {actual_width}x{actual_height} do not match "
                f"requested {width}x{height}"
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("remote Z-Image fallback failed: %s", type(exc).__name__)
        raise HTTPException(
            503,
            f"remote Z-Image fallback failed ({type(exc).__name__})",
            headers={"Retry-After": "5"},
        ) from exc

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    teleport = None
    if payload.get("teleport"):
        teleport = {
            "method": "remote_full_generation",
            "cache_hit": False,
            "fallback_reason": "local_cuda_unavailable",
        }
    return {
        "encoded": base64.b64encode(image_bytes).decode(),
        "image_bytes": image_bytes,
        "format": image_format,
        "width": actual_width,
        "height": actual_height,
        "inference_time_ms": elapsed_ms,
        "teleport": teleport,
        "model": "fal-ai/z-image/turbo/lora" if lora is not None else "fal-ai/z-image/turbo",
        "backend": "fal",
    }


def _call_resilient_zimage(payload: dict, lora: object | None = None) -> dict:
    """Prefer native inference, opening a short circuit after CUDA failures."""
    global _native_fallback_disabled_until
    if not ZIMAGE_FAL_FALLBACK_ENABLED:
        return _call_native_zimage(payload)

    now = time.monotonic()
    with _native_fallback_circuit_lock:
        native_circuit_open = now < _native_fallback_disabled_until
    if not native_circuit_open:
        try:
            result = _call_native_zimage(payload)
            with _native_fallback_circuit_lock:
                _native_fallback_disabled_until = 0.0
            return result
        except HTTPException as native_error:
            with _native_fallback_circuit_lock:
                _native_fallback_disabled_until = (
                    time.monotonic() + ZIMAGE_NATIVE_FAILURE_COOLDOWN_SECONDS
                )
            logger.warning(
                "%s; opening native image circuit for %.1fs and using remote Z-Image",
                native_error.detail,
                ZIMAGE_NATIVE_FAILURE_COOLDOWN_SECONDS,
            )
    else:
        logger.info("native image circuit is open; using remote Z-Image")
    return _call_fal_zimage(payload, lora)


def _native_lora_validation_failure(error: HTTPException) -> bool:
    """Only discard an adapter when the backend explicitly rejects that adapter.

    Capacity, restart and transport failures apply equally to the base model.
    Retrying them without LoRA repeats the recovery wait and changes image style.
    Native client/validation errors are mapped to 502 by _call_native_zimage.
    """
    detail = str(error.detail)
    return (
        error.status_code == 502
        and detail.startswith("native fallback returned HTTP 400:")
        and re.search(r"\bloras?(?:\b|_)", detail, re.IGNORECASE) is not None
    )


def _generate_image_native_once_sync(req: ZImageRequest, prompt: str) -> dict:
    payload, lora = _native_zimage_request(req, prompt)
    try:
        native = _call_resilient_zimage(payload, lora)
    except HTTPException as exc:
        if lora is None or not _native_lora_validation_failure(exc):
            raise
        # Match the local path: a bad adapter must not take down image serving.
        logger.warning("native LoRA %s failed; retrying the same prompt without LoRA", lora.id)
        for key in ("lora_id", "lora_filename", "lora_scale"):
            payload.pop(key, None)
        native = _call_resilient_zimage(payload)
        lora = None
    return {
        "image_base64": native["encoded"],
        "format": native["format"],
        "width": native["width"],
        "height": native["height"],
        "inference_time_ms": native["inference_time_ms"],
        "seed": req.seed,
        "prompt_used": payload["prompt"],
        "lora": {"lora_id": lora.id, "lora_name": lora.name} if lora else None,
        "teleport": native["teleport"],
        "backend": native.get("backend") or "omniserve-native",
        "backend_model": native["model"],
        "prompt_embedding_cache": None,
        "pipeline_timing": None,
        "early_exit": None,
    }


def _generate_image_native_sync(req: ZImageRequest) -> dict:
    """Native equivalent of the local quality/best-of policy."""
    first_prompt = compact_prompt(req.prompt)
    if ZIMAGE_ENHANCE_PROMPT and req.enhance_prompt:
        first_prompt = enhance_prompt(first_prompt)
    if req.best_of > 1:
        candidates = []
        for index in range(req.best_of):
            attempt_req = _copy_zimage_request(req, first_prompt)
            attempt_req.seed = req.seed + index
            result = _generate_image_native_once_sync(attempt_req, first_prompt)
            image = _decode_result_image(result)
            candidates.append({
                "result": result,
                "image": image,
                "bumpy": detect_too_bumpy(image) if image is not None else True,
            })
        images = [item["image"] for item in candidates if item["image"] is not None]
        scores = aesthetic_score_images(images) if images else None
        score_iter = iter(scores) if scores else None
        for candidate in candidates:
            raw = next(score_iter) if (score_iter and candidate["image"] is not None) else 0.0
            candidate["score"] = raw
            candidate["ranked"] = raw - (100.0 if candidate["bumpy"] else 0.0)
        best_index = max(range(len(candidates)), key=lambda i: candidates[i]["ranked"])
        best = candidates[best_index]["result"]
        if scores:
            best["aesthetic_score"] = round(candidates[best_index]["score"], 3)
        best["best_of"] = {
            "candidates": req.best_of,
            "best_index": best_index,
            "scores": [round(item["score"], 3) for item in candidates],
            "bumpy": [item["bumpy"] for item in candidates],
        }
        return best

    prompts = [first_prompt]
    if req.quality_retry:
        prompts.append(retry_prompt(first_prompt))
    last_result = None
    for attempt, prompt in enumerate(prompts):
        attempt_req = _copy_zimage_request(req, prompt)
        attempt_req.seed = req.seed + attempt
        result = _generate_image_native_once_sync(attempt_req, prompt)
        last_result = result
        image = _decode_result_image(result)
        if image is None or not req.quality_retry or not detect_too_bumpy(image):
            if attempt:
                result["quality_retry"] = {
                    "reason": "bumpy_image",
                    "prompt_used": prompt,
                    "attempts": attempt + 1,
                }
            if req.score_aesthetic:
                _attach_aesthetic_score(result, image)
            return result
    if last_result is not None:
        last_result["quality_warning"] = "bumpy_image_after_retry"
        return last_result
    raise HTTPException(503, "native image generation failed")


def _attach_aesthetic_score(result: dict, image: Image.Image | None = None) -> None:
    if image is None:
        image = _decode_result_image(result)
    if image is None:
        return
    scores = aesthetic_score_images([image])
    if scores:
        result["aesthetic_score"] = round(scores[0], 3)


def _generate_best_of_sync(req: ZImageRequest, prompt: str) -> dict:
    """Generate best_of candidates and return the highest aesthetic scorer pick."""
    candidates = []
    for i in range(req.best_of):
        attempt_req = _copy_zimage_request(req, prompt)
        attempt_req.seed = req.seed + i
        result = _generate_image_once_sync(attempt_req)
        image = _decode_result_image(result)
        bumpy = detect_too_bumpy(image) if image is not None else True
        candidates.append({"result": result, "image": image, "bumpy": bumpy})

    images = [c["image"] for c in candidates if c["image"] is not None]
    scores = aesthetic_score_images(images) if images else None
    score_iter = iter(scores) if scores else None
    for cand in candidates:
        raw = next(score_iter) if (score_iter and cand["image"] is not None) else 0.0
        cand["score"] = raw
        cand["ranked"] = raw - (100.0 if cand["bumpy"] else 0.0)

    best_index = max(range(len(candidates)), key=lambda i: candidates[i]["ranked"])
    best = candidates[best_index]["result"]
    if scores:
        best["aesthetic_score"] = round(candidates[best_index]["score"], 3)
    best["best_of"] = {
        "candidates": req.best_of,
        "best_index": best_index,
        "scores": [round(c["score"], 3) for c in candidates],
        "bumpy": [c["bumpy"] for c in candidates],
    }
    return best


def _generate_image_sync(req: ZImageRequest):
    """Generate an image and retry once if deterministic quality checks fail."""
    first_prompt = compact_prompt(req.prompt)
    if ZIMAGE_ENHANCE_PROMPT and req.enhance_prompt:
        first_prompt = enhance_prompt(first_prompt)
    if req.best_of > 1:
        return _generate_best_of_sync(req, first_prompt)
    if not req.quality_retry:
        result = _generate_image_once_sync(_copy_zimage_request(req, first_prompt))
        if req.score_aesthetic:
            _attach_aesthetic_score(result)
        return result
    prompts = [first_prompt, retry_prompt(first_prompt)]

    last_result = None
    for attempt, prompt in enumerate(prompts):
        attempt_req = _copy_zimage_request(req, prompt)
        attempt_req.seed = req.seed + attempt
        result = _generate_image_once_sync(attempt_req)
        last_result = result

        image = _decode_result_image(result)
        if image is None:
            return result

        if not detect_too_bumpy(image):
            if attempt > 0:
                result["quality_retry"] = {
                    "reason": "bumpy_image",
                    "prompt_used": prompt,
                    "attempts": attempt + 1,
                }
            if req.score_aesthetic:
                _attach_aesthetic_score(result, image)
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


def _zimage_batch_compatibility_key(req: ZImageRequest) -> tuple:
    """Return fields which must be identical for one diffusion forward batch."""
    width = (req.width // 64) * 64 or 1024
    height = (req.height // 64) * 64 or 1024
    # Explicit LoRAs can batch across prompts. Auto selection is prompt-driven,
    # so only identical auto-LoRA prompts share a batch unless an ID is pinned.
    lora_route = req.lora_id or (req.prompt if req.auto_lora else None)
    threshold = req.early_exit if req.early_exit is not None else (ZIMAGE_EARLY_EXIT or None)
    return (
        width,
        height,
        req.num_inference_steps,
        round(req.guidance_scale, 6),
        lora_route,
        req.auto_lora,
        round(req.lora_scale, 6),
        threshold,
        req.early_exit_min_steps or ZIMAGE_EARLY_EXIT_MIN_STEPS,
        req.low_priority,
        req.best_of,
        req.teleport,
    )


def _zimage_batch_runtime_add(**increments: int) -> None:
    with _zimage_batch_runtime_lock:
        for key, amount in increments.items():
            if key == "last_granted_mb":
                _zimage_batch_runtime[key] = amount
            elif key == "largest_pipeline_batch":
                _zimage_batch_runtime[key] = max(_zimage_batch_runtime[key], amount)
            else:
                _zimage_batch_runtime[key] += amount


def _zimage_batch_runtime_snapshot() -> dict:
    with _zimage_batch_runtime_lock:
        return dict(_zimage_batch_runtime)


def _zimage_batch_desired_capacity(reqs: list[ZImageRequest]) -> int:
    if not reqs:
        return 1
    width = (reqs[0].width // 64) * 64 or 1024
    height = (reqs[0].height // 64) * 64 or 1024
    by_pixels = max(1, ZIMAGE_DYNAMIC_BATCH_MAX_PIXELS // max(1, width * height))
    return max(1, min(len(reqs), ZIMAGE_DYNAMIC_BATCH_MAX_SIZE, by_pixels))


def _zimage_batch_capacity_from_cuda(desired_capacity: int) -> int:
    capacity = desired_capacity
    free_mb = _cuda_free_mb()
    if free_mb is not None:
        by_headroom = 1 + max(
            0,
            (free_mb - ZIMAGE_DYNAMIC_BATCH_RESERVE_MB) // ZIMAGE_DYNAMIC_BATCH_EXTRA_MB,
        )
        capacity = min(capacity, by_headroom)
    return max(1, capacity)


def _zimage_vram_broker_is_cached_unreachable() -> bool:
    with _zimage_vram_broker_state_lock:
        return time.monotonic() < _zimage_vram_broker_unreachable_until


def _zimage_vram_broker_mark_unreachable() -> None:
    global _zimage_vram_broker_unreachable_until
    with _zimage_vram_broker_state_lock:
        _zimage_vram_broker_unreachable_until = (
            time.monotonic() + ZIMAGE_VRAM_BROKER_RETRY_SECONDS
        )


def _zimage_vram_broker_lease(
    reqs: list[ZImageRequest], desired_capacity: int
) -> tuple[int, str | None]:
    if not ZIMAGE_VRAM_BROKER_URL or _zimage_vram_broker_is_cached_unreachable():
        return _zimage_batch_capacity_from_cuda(desired_capacity), None

    requested_mb = (
        (desired_capacity - 1) * ZIMAGE_DYNAMIC_BATCH_EXTRA_MB
        + ZIMAGE_DYNAMIC_BATCH_RESERVE_MB
    )
    try:
        response = requests.post(
            f"{ZIMAGE_VRAM_BROKER_URL}/v1/gpu/lease",
            json={
                "owner": "zimage",
                "mb": requested_mb,
                "min_mb": ZIMAGE_DYNAMIC_BATCH_RESERVE_MB,
                "tier": (
                    "background"
                    if reqs and all(req.low_priority for req in reqs)
                    else "free"
                ),
                "ttl_s": ZIMAGE_VRAM_BROKER_TTL_SECONDS,
            },
            timeout=ZIMAGE_VRAM_BROKER_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("granted"), bool):
            raise ValueError("invalid broker lease response")
        if not payload["granted"]:
            denied_mb = payload.get("mb")
            if (
                isinstance(denied_mb, bool)
                or not isinstance(denied_mb, int)
                or denied_mb != 0
                or not isinstance(payload.get("reason"), str)
            ):
                raise ValueError("invalid broker denial response")
            _zimage_batch_runtime_add(broker_denials=1)
            return _zimage_batch_capacity_from_cuda(desired_capacity), None

        lease_id = payload.get("lease_id")
        granted_mb = payload.get("mb")
        expires_in_s = payload.get("expires_in_s")
        if (
            not isinstance(lease_id, str)
            or not lease_id
            or isinstance(granted_mb, bool)
            or not isinstance(granted_mb, int)
            or granted_mb < ZIMAGE_DYNAMIC_BATCH_RESERVE_MB
            or granted_mb > requested_mb
            or isinstance(expires_in_s, bool)
            or not isinstance(expires_in_s, int)
            or expires_in_s <= 0
        ):
            raise ValueError("invalid broker grant response")

        by_headroom = 1 + max(
            0,
            (granted_mb - ZIMAGE_DYNAMIC_BATCH_RESERVE_MB)
            // ZIMAGE_DYNAMIC_BATCH_EXTRA_MB,
        )
        _zimage_batch_runtime_add(
            broker_grants=1,
            last_granted_mb=granted_mb,
        )
        return max(1, min(desired_capacity, by_headroom)), lease_id
    except Exception as exc:
        _zimage_batch_runtime_add(broker_errors=1)
        _zimage_vram_broker_mark_unreachable()
        logger.warning("Z-Image VRAM broker lease failed; using CUDA headroom: %s", exc)
        return _zimage_batch_capacity_from_cuda(desired_capacity), None


def _zimage_vram_broker_release(lease_id: str | None) -> None:
    if not lease_id:
        return
    try:
        response = requests.post(
            f"{ZIMAGE_VRAM_BROKER_URL}/v1/gpu/release",
            json={"lease_id": lease_id},
            timeout=ZIMAGE_VRAM_BROKER_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("released") is not True:
            raise ValueError("invalid broker release response")
    except Exception as exc:
        _zimage_batch_runtime_add(broker_errors=1)
        _zimage_vram_broker_mark_unreachable()
        logger.warning("Z-Image VRAM broker release failed: %s", exc)


@contextlib.contextmanager
def _zimage_batch_allocation(reqs: list[ZImageRequest]) -> Iterator[int]:
    desired_capacity = _zimage_batch_desired_capacity(reqs)
    capacity, lease_id = _zimage_vram_broker_lease(reqs, desired_capacity)
    try:
        yield capacity
    finally:
        _zimage_vram_broker_release(lease_id)


def _zimage_batch_capacity(reqs: list[ZImageRequest]) -> int:
    """Choose a live microbatch size, releasing any probe lease immediately."""
    with _zimage_batch_allocation(reqs) as capacity:
        return capacity


def _move_zimage_inference_components_to_device(pipe) -> None:
    """Restore GPU-resident components without moving a pinned CPU encoder."""
    if not hasattr(pipe, "to") or hasattr(pipe, "_offload_gpu_id"):
        return
    try:
        if _text_encoder_on_cpu():
            for component_name in ("transformer", "vae"):
                component = getattr(pipe, component_name, None)
                if component is not None:
                    component.to(DEVICE)
        else:
            pipe.to(DEVICE)
    except Exception:
        # Preserve the existing single-request behavior: the pipeline call is
        # the authoritative check and produces a useful CUDA error if needed.
        pass


def _prepare_zimage_batch_embeddings(pipe, prompts: list[str], common: dict) -> tuple[dict, list[dict]]:
    positive: list[torch.Tensor] = []
    negative: list[torch.Tensor] = []
    metadata: list[dict] = []
    for prompt in prompts:
        prepared, prompt_meta = _prepare_zimage_prompt_embeddings(
            pipe,
            {**common, "prompt": prompt},
        )
        positive.extend(prepared.get("prompt_embeds") or [])
        negative.extend(prepared.get("negative_prompt_embeds") or [])
        metadata.append(prompt_meta)
    batch_kwargs = dict(common)
    batch_kwargs["prompt"] = None
    batch_kwargs["prompt_embeds"] = positive
    if negative:
        batch_kwargs["negative_prompt_embeds"] = negative
    return batch_kwargs, metadata


def _generate_image_batch_once_sync(reqs: list[ZImageRequest]) -> list[dict]:
    """Run compatible requests in one Z-Image pipeline invocation."""
    if len(reqs) == 1:
        return [_generate_image_once_sync(reqs[0])]
    if nsfw_classifier is not None:
        _unload_nsfw_classifier()

    text2img_pipe, _ = zimage_pipeline
    _move_zimage_inference_components_to_device(text2img_pipe)
    resolved = [_resolve_lora(req) for req in reqs]
    loras = [item[0] for item in resolved]
    final_prompts = [item[1] for item in resolved]
    lora_keys = {
        (
            lora.id if lora else None,
            round(_effective_lora_scale(lora, req.lora_scale), 6) if lora else None,
        )
        for req, lora in zip(reqs, loras)
    }
    if len(lora_keys) != 1:
        logger.info("dynamic batch split after auto-LoRA routes diverged")
        return [_generate_image_once_sync(req) for req in reqs]

    first = reqs[0]
    width = (first.width // 64) * 64 or 1024
    height = (first.height // 64) * 64 or 1024
    generators = [_make_pipeline_generator(text2img_pipe, req.seed) for req in reqs]
    _reset_zimage_scheduler(text2img_pipe)
    common = {
        "width": width,
        "height": height,
        "num_inference_steps": first.num_inference_steps,
        "guidance_scale": first.guidance_scale,
        "generator": generators,
    }
    pipe_kwargs, prompt_cache_metadata = _prepare_zimage_batch_embeddings(
        text2img_pipe, final_prompts, common
    )

    early_exit_threshold = (
        first.early_exit if first.early_exit is not None else (ZIMAGE_EARLY_EXIT or None)
    )
    early_exit_min_steps = first.early_exit_min_steps or ZIMAGE_EARLY_EXIT_MIN_STEPS
    exit_info: dict = {}
    pipeline_timing: dict = {}
    lora = loras[0]
    capture = ()
    if lora is None and _latent_save_active():
        capture = _capture_steps_for(first.num_inference_steps)
    try:
        if lora is not None:
            _activate_lora(
                text2img_pipe,
                lora,
                lora_scale=_effective_lora_scale(lora, first.lora_scale),
            )
        else:
            _deactivate_loras(text2img_pipe)
        started = time.time()
        result, captured = _run_zimage_capture_multi(
            text2img_pipe,
            pipe_kwargs,
            capture,
            pipeline_timing,
            early_exit=early_exit_threshold,
            early_exit_min_steps=early_exit_min_steps,
            exit_info=exit_info,
            log_prompt=" | ".join(final_prompts),
        )
    except Exception as exc:
        if lora is None:
            raise
        logger.warning("batched LoRA generation failed (%s), retrying without: %s", lora.id, exc)
        _deactivate_loras(text2img_pipe)
        pipeline_timing = {}
        started = time.time()
        result, captured = _run_zimage_capture_multi(
            text2img_pipe, pipe_kwargs, (), pipeline_timing
        )
        lora = None
    elapsed = time.time() - started

    if exit_info.get("exited_after_step"):
        captured = {}
    if captured and lora is None:
        embeddings = pipe_kwargs.get("prompt_embeds") or []
        for index, req in enumerate(reqs):
            per_image_captures = {
                step: latent[index:index + 1] for step, latent in captured.items()
            }
            embedding = embeddings[index] if index < len(embeddings) else None
            _persist_generation_latents(
                final_prompts[index],
                req.seed,
                req.num_inference_steps,
                width,
                height,
                req.guidance_scale,
                per_image_captures,
                text_embedding=embedding,
            )

    outputs = []
    lora_info = {"lora_id": lora.id, "lora_name": lora.name} if lora else None
    for index, (req, image) in enumerate(zip(reqs, result.images)):
        buf = io.BytesIO()
        image.save(buf, format="WEBP", quality=90)
        outputs.append({
            "image_base64": base64.b64encode(buf.getvalue()).decode(),
            "format": "webp",
            "width": width,
            "height": height,
            "inference_time_ms": int(elapsed * 1000),
            "seed": req.seed,
            "prompt_used": final_prompts[index],
            "lora": lora_info,
            "prompt_embedding_cache": prompt_cache_metadata[index],
            "pipeline_timing": dict(pipeline_timing),
            "early_exit": dict(exit_info) if exit_info else None,
            "dynamic_batch": {
                "size": len(reqs),
                "index": index,
                "total_inference_time_ms": int(elapsed * 1000),
            },
        })
    _zimage_batch_runtime_add(
        pipeline_batches=1,
        pipeline_images=len(outputs),
        largest_pipeline_batch=len(outputs),
    )
    logger.info(
        "zimage dynamic batch: size=%d %dx%d in %.2fs (steps=%d, lora=%s)",
        len(outputs), width, height, elapsed, first.num_inference_steps,
        lora.id if lora else "none",
    )
    return outputs


def _generate_image_batch_sync(reqs: list[ZImageRequest]) -> list[dict]:
    """Apply quality policy around a shared first diffusion pass."""
    if len(reqs) == 1 or any(req.best_of > 1 or req.teleport for req in reqs):
        _zimage_batch_runtime_add(serial_chunks=len(reqs))
        return [_generate_image_sync(req) for req in reqs]

    prepared_reqs = []
    for req in reqs:
        prompt = compact_prompt(req.prompt)
        if ZIMAGE_ENHANCE_PROMPT and req.enhance_prompt:
            prompt = enhance_prompt(prompt)
        prepared_reqs.append(_copy_zimage_request(req, prompt))

    results = _generate_image_batch_once_sync(prepared_reqs)
    for index, (original, prepared, result) in enumerate(zip(reqs, prepared_reqs, results)):
        image = _decode_result_image(result)
        if original.quality_retry and image is not None and detect_too_bumpy(image):
            retry_req = _copy_zimage_request(original, retry_prompt(prepared.prompt))
            retry_req.seed = original.seed + 1
            result = _generate_image_once_sync(retry_req)
            result["quality_retry"] = {
                "reason": "bumpy_image",
                "prompt_used": retry_req.prompt,
                "attempts": 2,
                "initial_dynamic_batch_size": len(reqs),
            }
            results[index] = result
            image = _decode_result_image(result)
        if original.score_aesthetic:
            _attach_aesthetic_score(results[index], image)
    return results


def _is_cuda_oom(exc: Exception) -> bool:
    text = str(exc).lower()
    return "out of memory" in text and ("cuda" in text or "accelerator" in type(exc).__name__.lower())


def _is_zimage_cudagraph_list_assertion(exc: Exception) -> bool:
    if not isinstance(exc, AssertionError):
        return False
    text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return (
        "<class 'list'>" in text
        and "cudagraph_trees.py" in text
        and "CUDAGraphNode" in text
    )


def _recover_from_zimage_runtime_fault(reason: str):
    logger.warning("recovering from %s: unloading zimage and clearing compiler/CUDA cache", reason)
    model_manager.force_unload("zimage")
    try:
        torch._dynamo.reset()
    except Exception:
        pass
    _clear_torch_cuda_caches()


def _recover_from_cuda_oom():
    _recover_from_zimage_runtime_fault("CUDA OOM")


def _detach_recoverable_exception_traceback(exc: BaseException) -> None:
    """Drop unwound generation frames before CUDA cleanup runs.

    Pipeline and intermediate tensor locals remain reachable through an
    exception traceback. Keeping that traceback while calling empty_cache()
    makes an OOM recovery appear to unload the model while its allocations are
    still live, which prevents both the immediate retry and later cold loads.
    """
    exc.__traceback__ = None


class _ZImageOOMRecoveredForNativeFallback(Exception):
    """Signal that local OOM cleanup completed and native serving can resume."""


def _with_zimage_model_retry(operation_name: str, fn):
    last_exc = None
    for attempt in range(3):
        try:
            _raise_if_zimage_cuda_unavailable()
            if not model_manager.is_loaded("zimage"):
                _reclaim_zimage_cold_load_headroom(ZIMAGE_LOAD_MIN_FREE_MB, operation_name)
            with model_manager.use("zimage"):
                if zimage_pipeline is None:
                    raise HTTPException(503, "zimage model failed to load")
                # Global driver free memory is not the pipeline's usable
                # headroom: PyTorch can satisfy inference from its reserved
                # allocator pool even when cudaMemGetInfo is low. Let the
                # actual operation run and use the OOM recovery below if its
                # real allocation cannot be fulfilled.
                return fn()
        except Exception as e:
            last_exc = e
            if _is_fatal_cuda_error(e):
                _mark_cuda_runtime_fault(e)
                # Drop Python/module references, but never issue more CUDA work
                # after a launch failure. Only a fresh process can recover.
                model_manager.force_unload("zimage")
                _schedule_cuda_process_restart()
                raise HTTPException(
                    503,
                    f"{operation_name} stopped after a fatal CUDA runtime error; process restart required",
                    headers={"Retry-After": "30"},
                ) from e
            if _is_cuda_oom(e):
                logger.warning("%s hit CUDA OOM; recovering and retrying safely", operation_name)
                _detach_recoverable_exception_traceback(e)
                last_exc = None
                _recover_from_cuda_oom()
                if ZIMAGE_NATIVE_FALLBACK_URL and operation_name in {
                    "generate_image",
                    "generate_image_batch",
                }:
                    # The local model is cold after recovery. Loading the same
                    # large BF16 pipeline immediately can make the HTTP worker
                    # unresponsive for minutes under shared-GPU memory pressure.
                    # Let the image wrappers retry this request on the already
                    # resident quantized backend instead.
                    raise _ZImageOOMRecoveredForNativeFallback() from None
                if attempt > 0:
                    raise HTTPException(503, f"{operation_name} failed after CUDA OOM recovery")
                if not _wait_for_zimage_memory_headroom(ZIMAGE_LOAD_MIN_FREE_MB, operation_name):
                    detail = _zimage_memory_pressure_detail(ZIMAGE_LOAD_MIN_FREE_MB, operation_name)
                    raise HTTPException(
                        503,
                        f"{operation_name} failed after CUDA OOM recovery: {detail}",
                        headers={"Retry-After": "10"},
                    )
                continue
            if _is_zimage_cudagraph_list_assertion(e):
                downgraded = _downgrade_zimage_compile_mode("torch inductor CUDA graph list-output assertion")
                _detach_recoverable_exception_traceback(e)
                last_exc = None
                _recover_from_zimage_runtime_fault("torch inductor CUDA graph assertion")
                if not downgraded or attempt >= 2:
                    raise HTTPException(503, f"{operation_name} failed after compile-mode recovery")
                logger.warning(
                    "%s hit torch inductor CUDA graph assertion; reloading model and retrying",
                    operation_name,
                )
                continue
            raise
    raise HTTPException(503, f"{operation_name} failed after zimage recovery: {last_exc}")


def _generate_image_with_model_sync(req: ZImageRequest):
    try:
        return _with_zimage_model_retry("generate_image", lambda: _generate_image_sync(req))
    except _ZImageOOMRecoveredForNativeFallback:
        logger.warning("routing image request to native fallback after local CUDA OOM recovery")
        return _generate_image_native_sync(req)


def _generate_image_batch_with_model_sync(reqs: list[ZImageRequest]) -> list[dict]:
    """Keep one model lease while executing one or more adaptive chunks."""
    if _should_use_native_zimage_fallback("generate_image_batch"):
        logger.warning(
            "routing %d image request(s) to native fallback because the BF16 pipeline is cold",
            len(reqs),
        )
        try:
            return [_generate_image_native_sync(req) for req in reqs]
        except HTTPException:
            if not _native_failure_allows_local_cold_load("generate_image_batch"):
                raise
            logger.exception(
                "native image fallback failed with safe BF16 headroom; trying the local loader"
            )

    def _run() -> list[dict]:
        outputs: list[dict] = []
        offset = 0
        while offset < len(reqs):
            remaining = reqs[offset:]
            with _zimage_batch_allocation(remaining) as capacity:
                chunk = remaining[:capacity]
                try:
                    outputs.extend(_generate_image_batch_sync(chunk))
                except Exception as exc:
                    if len(chunk) == 1 or not _is_cuda_oom(exc):
                        raise
                    logger.warning(
                        "dynamic batch size %d hit CUDA OOM; retrying the chunk serially",
                        len(chunk),
                    )
                    _detach_recoverable_exception_traceback(exc)
                    _clear_torch_cuda_caches()
                    _zimage_batch_runtime_add(oom_batch_fallbacks=1, serial_chunks=len(chunk))
                    outputs.extend(_generate_image_sync(req) for req in chunk)
            offset += len(chunk)
        return outputs

    try:
        return _with_zimage_model_retry("generate_image_batch", _run)
    except _ZImageOOMRecoveredForNativeFallback:
        logger.warning(
            "routing %d image request(s) to native fallback after local CUDA OOM recovery",
            len(reqs),
        )
        return [_generate_image_native_sync(req) for req in reqs]


async def _run_zimage_dynamic_batch(reqs: list[ZImageRequest]) -> list[dict]:
    low_priority = all(req.low_priority for req in reqs)
    async with gpu_slot(low_priority):
        return await asyncio.get_running_loop().run_in_executor(
            None, _generate_image_batch_with_model_sync, reqs
        )


async def _submit_zimage_request(req: ZImageRequest) -> dict:
    with model_manager.reserve(
        "zimage",
        allow_while_held=_should_use_native_zimage_fallback("generate_image"),
    ):
        if zimage_dynamic_batcher is None:
            async with gpu_slot(req.low_priority):
                return await asyncio.get_running_loop().run_in_executor(
                    None, _generate_image_with_model_sync, req
                )
        return await zimage_dynamic_batcher.submit(req)


@app.post("/generate_image")
async def generate_image(req: ZImageRequest, request: Request):
    if not LOAD_ZIMAGE:
        raise HTTPException(503, "zimage disabled")
    _remember_request_prompt(request, req.prompt)
    _remember_request_inference_params(
        request,
        model="zimage-turbo",
        width=req.width,
        height=req.height,
        num_inference_steps=req.num_inference_steps,
        auto_lora=req.auto_lora,
        teleport=False,
        perf=False,
        low_priority=req.low_priority,
    )
    return await _submit_zimage_request(req)


# GET with query params for cutedsl-site internal use (returns base64)
@app.get("/generate_image_b64")
async def generate_image_b64(
    request: Request,
    prompt: str,
    width: int = ZIMAGE_DEFAULT_WIDTH,
    height: int = ZIMAGE_DEFAULT_HEIGHT,
    seed: int = 0,
    lora_id: Optional[str] = None,
    auto_lora: bool = True,
):
    _require_nonempty_prompt(prompt)
    _remember_request_prompt(request, prompt)
    _remember_request_inference_params(
        request,
        model="zimage-turbo",
        width=width,
        height=height,
        num_inference_steps=ZIMAGE_DEFAULT_STEPS,
        auto_lora=auto_lora,
        teleport=False,
        perf=False,
    )
    req = ZImageRequest(
        prompt=prompt, width=width, height=height, seed=seed,
        lora_id=lora_id, auto_lora=auto_lora,
    )
    return await _submit_zimage_request(req)


def _openai_images_secret(request: Request, body: dict) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return str(
        request.headers.get("secret")
        or body.get("secret")
        or request.query_params.get("secret")
        or ""
    )


@app.post("/v1/images/generations")
async def openai_images_generations(request: Request):
    """OpenAI-compatible image generation so omniserve / omniserve-native can
    front this server with no payload translation. Extra fields (lora_id,
    auto_lora, prompt_is_final, lora_scale, steps, seed, guidance_scale) pass
    through."""
    if not LOAD_ZIMAGE:
        raise HTTPException(503, "zimage disabled")
    body = await request.json()
    _check_secret(_openai_images_secret(request, body))
    prompt = str(body.get("prompt") or "")
    _require_nonempty_prompt(prompt)
    width, height = ZIMAGE_DEFAULT_WIDTH, ZIMAGE_DEFAULT_HEIGHT
    size = body.get("size")
    if size:
        try:
            width, height = (int(x) for x in str(size).lower().split("x"))
        except ValueError:
            raise HTTPException(400, "size must be WIDTHxHEIGHT")
    width = int(body.get("width") or width)
    height = int(body.get("height") or height)
    n = max(1, min(int(body.get("n") or 1), 4))
    seed = int(body.get("seed") or 0)
    lora_id = body.get("lora_id")
    lora_scale = float(body.get("lora_scale") or 1.0)
    loras = body.get("loras") or []
    if not lora_id and loras:
        first = loras[0]
        lora_id = first.get("id") if isinstance(first, dict) else str(first)
        if isinstance(first, dict) and first.get("scale") is not None:
            lora_scale = float(first["scale"])
    base = dict(
        prompt=prompt, width=width, height=height,
        num_inference_steps=int(body.get("steps") or body.get("num_inference_steps") or ZIMAGE_DEFAULT_STEPS),
        guidance_scale=float(body.get("guidance_scale") or ZIMAGE_DEFAULT_GUIDANCE),
        lora_id=lora_id, lora_scale=lora_scale,
        auto_lora=bool(body.get("auto_lora", True)),
        prompt_is_final=bool(body.get("prompt_is_final", False)),
        low_priority=bool(body.get("low_priority", False)),
        quality_retry=bool(body.get("quality_retry", True)),
        enhance_prompt=bool(body.get("enhance_prompt", True)),
        best_of=max(1, min(int(body.get("best_of") or 1), 4)),
        score_aesthetic=bool(body.get("score_aesthetic", False)),
        early_exit=body.get("early_exit"),
        early_exit_min_steps=body.get("early_exit_min_steps"),
        teleport=bool(body.get("teleport", False)),
    )
    _remember_request_prompt(request, prompt)
    _remember_request_inference_params(
        request, model="zimage-turbo", width=width, height=height,
        num_inference_steps=base["num_inference_steps"],
        auto_lora=base["auto_lora"], teleport=False, perf=False,
        low_priority=base["low_priority"],
    )
    requests_to_run = [ZImageRequest(seed=seed + i, **base) for i in range(n)]
    results = await asyncio.gather(*(_submit_zimage_request(req) for req in requests_to_run))
    data = []
    for result in results:
        entry = {"b64_json": result.get("image_base64")}
        if result.get("lora"):
            entry["lora"] = result["lora"]
        if result.get("seed") is not None:
            entry["seed"] = result["seed"]
        if result.get("dynamic_batch"):
            entry["dynamic_batch"] = result["dynamic_batch"]
        if result.get("teleport"):
            entry["teleport"] = result["teleport"]
        data.append(entry)
    return {"created": int(time.time()), "model": "z-image-turbo", "data": data}


# ---------------------------------------------------------------------------
# Experimental: per-step diffusion trace for early-exit ablation
# ---------------------------------------------------------------------------


class StepTraceRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    width: int = 512
    height: int = 512
    seed: int = 0
    num_inference_steps: int = 9
    guidance_scale: float = ZIMAGE_DEFAULT_GUIDANCE
    decode_x0: bool = True
    save_tensors: bool = True
    low_priority: bool = True
    sigmas: Optional[list[float]] = None


def _decode_zimage_latent_to_pil(pipe, latents: torch.Tensor):
    vae = pipe.vae
    lat = latents.to(vae.dtype) / vae.config.scaling_factor + vae.config.shift_factor
    with torch.inference_mode():
        img = vae.decode(lat, return_dict=False)[0]
    return pipe.image_processor.postprocess(img, output_type="pil")[0]


def _step_trace_sync(req: StepTraceRequest):
    if nsfw_classifier is not None:
        _unload_nsfw_classifier()
    if zimage_pipeline is None:
        raise HTTPException(503, "zimage not loaded")
    pipe, _ = zimage_pipeline
    if hasattr(pipe, 'to') and not hasattr(pipe, '_offload_gpu_id'):
        try:
            if _text_encoder_on_cpu():
                for _comp_name in ("transformer", "vae"):
                    _comp = getattr(pipe, _comp_name, None)
                    if _comp is not None:
                        _comp.to(DEVICE)
            else:
                pipe.to(DEVICE)
        except Exception:
            pass
    _deactivate_loras(pipe)
    _reset_zimage_scheduler(pipe)

    width = (req.width // 64) * 64 or 1024
    height = (req.height // 64) * 64 or 1024
    generator = _make_pipeline_generator(pipe, req.seed)
    pipe_kwargs = dict(
        prompt=req.prompt, width=width, height=height,
        num_inference_steps=req.num_inference_steps,
        guidance_scale=req.guidance_scale, generator=generator,
    )
    pipe_kwargs, prompt_cache_meta = _prepare_zimage_prompt_embeddings(pipe, pipe_kwargs)
    if req.sigmas:
        pipe_kwargs["sigmas"] = req.sigmas

    zs: list[torch.Tensor] = []
    vs: list[torch.Tensor] = []
    step_times: list[float] = []

    def _cb(_pipe, step_index, _timestep, callback_kwargs):  # noqa: ANN001
        step_times.append(time.perf_counter())
        zs.append(callback_kwargs["latents"].detach().clone())
        vs.append(callback_kwargs["noise_pred"].detach().clone())
        return callback_kwargs

    t0 = time.perf_counter()
    result = pipe(
        **pipe_kwargs,
        callback_on_step_end=_cb,
        callback_on_step_end_tensor_inputs=["latents", "noise_pred"],
    )
    gen_seconds = time.perf_counter() - t0
    sigmas = [float(s) for s in pipe.scheduler.sigmas]
    final_img = result.images[0]

    trace_id = f"{int(time.time() * 1000)}_s{req.seed}"
    out_dir = os.path.join(STEP_TRACE_DIR, trace_id)
    os.makedirs(out_dir, exist_ok=True)
    final_path = os.path.join(out_dir, "final.webp")
    final_img.save(final_path, quality=95)

    from cutezimage.image_metrics import compare_images, pil_to_tensor
    final_t = pil_to_tensor(final_img)

    steps_data = []
    n = len(zs)
    for k in range(n):
        s_next = sigmas[k + 1] if k + 1 < len(sigmas) else 0.0
        row: dict = {"step": k, "sigma": sigmas[k], "sigma_next": s_next}
        if k > 0:
            dz = zs[k] - zs[k - 1]
            zn = zs[k].norm().item()
            row.update({
                "dz_l2": round(dz.norm().item(), 5),
                "dz_rel": round(dz.norm().item() / max(zn, 1e-8), 6),
                "dz_l1_mean": round(dz.abs().mean().item(), 6),
                "cos_prev": round(torch.nn.functional.cosine_similarity(
                    zs[k].flatten(), zs[k - 1].flatten(), dim=0).item(), 6),
            })
        if req.decode_x0:
            x0 = zs[k] - s_next * vs[k]
            img = _decode_zimage_latent_to_pil(pipe, x0)
            p = os.path.join(out_dir, f"x0_step{k:02d}.webp")
            img.save(p, quality=95)
            m = compare_images(pil_to_tensor(img), final_t)
            row.update({
                "x0_image": p,
                "ssim_to_final": round(m["ssim"], 5),
                "psnr_to_final": round(m["psnr_db"], 3) if math.isfinite(m["psnr_db"]) else None,
                "mae_to_final": round(m["mae"], 4),
            })
        steps_data.append(row)

    if req.save_tensors:
        emb = pipe_kwargs.get("prompt_embeds")
        pooled = None
        if emb:
            first = emb[0] if isinstance(emb, (list, tuple)) else emb
            pooled = first.float().mean(dim=0).cpu()
        torch.save({
            "latents": [z.half().cpu() for z in zs],
            "noise_preds": [v.half().cpu() for v in vs],
            "sigmas": sigmas,
            "prompt": req.prompt,
            "seed": req.seed,
            "width": width,
            "height": height,
            "pooled_prompt_embedding": pooled,
        }, os.path.join(out_dir, "trace.pt"))

    step_durations = [round(b - a, 4) for a, b in zip(step_times, step_times[1:])]
    return {
        "trace_id": trace_id,
        "dir": out_dir,
        "final_image": final_path,
        "gen_seconds": round(gen_seconds, 3),
        "step_durations": step_durations,
        "sigmas": sigmas,
        "steps": steps_data,
        "prompt_embedding_cache": prompt_cache_meta,
    }


@app.post("/experimental/step_trace")
async def step_trace(req: StepTraceRequest):
    if not LOAD_ZIMAGE:
        raise HTTPException(503, "zimage disabled")
    async with gpu_slot(req.low_priority):
        return await asyncio.get_event_loop().run_in_executor(None, _step_trace_sync, req)


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
    values: list[float] = Field(min_length=1, max_length=8192)
    prediction_length: int = Field(default=64, ge=1, le=1024)
    quantile_levels: Optional[list[float]] = None
    # Optional covariates for multivariate forecasting. Each is a named series.
    # past_covariates align 1:1 with `values` (same length, the model uses
    # cross-variate attention to inform the target). future_covariates supply
    # known-ahead values over the horizon (length == prediction_length) and must
    # be a subset of past_covariates keys.
    past_covariates: Optional[dict[str, list[float]]] = None
    future_covariates: Optional[dict[str, list[float]]] = None

    @field_validator("values")
    @classmethod
    def validate_values(cls, values: list[float]) -> list[float]:
        return _validate_chronos_series(values, "values")

    @field_validator("past_covariates", "future_covariates")
    @classmethod
    def validate_covariates(cls, covariates: Optional[dict[str, list[float]]]):
        if covariates is None:
            return None
        for name, values in covariates.items():
            _validate_chronos_series(values, f"covariate {name!r}")
        return covariates

    @field_validator("quantile_levels")
    @classmethod
    def validate_quantile_levels(cls, levels: Optional[list[float]]):
        return _validate_chronos_quantile_levels(levels)


def _validate_chronos_series(values: list[float], label: str) -> list[float]:
    """Accept NaN missing values, but reject values unsafe for model arithmetic."""
    if not values:
        raise ValueError(f"{label} must not be empty")
    if any(math.isinf(value) for value in values):
        raise ValueError(f"{label} must not contain infinite values")
    if not any(math.isfinite(value) for value in values):
        raise ValueError(f"{label} must contain at least one finite value")

    # Chronos consumes float32 contexts. Reject numbers that overflow during
    # conversion instead of letting them poison model activations and later
    # crash Starlette's strict JSON serializer with NaN/Infinity.
    tensor = torch.tensor(values, dtype=torch.float32)
    input_missing = torch.isnan(tensor)
    if not torch.isfinite(tensor[~input_missing]).all().item():
        raise ValueError(f"{label} contains values outside the float32 range")
    return values


def _validate_chronos_quantile_levels(levels: Optional[list[float]]):
    if levels is None:
        return None
    if not levels:
        raise ValueError("quantile_levels must not be empty")
    if len(levels) > 21:
        raise ValueError("quantile_levels must contain at most 21 values")
    if any(not math.isfinite(level) or not 0.0 < level < 1.0 for level in levels):
        raise ValueError("quantile_levels must contain finite values between 0 and 1")
    if len(set(levels)) != len(levels):
        raise ValueError("quantile_levels must not contain duplicates")
    return levels


def _require_finite_forecast(*tensors: torch.Tensor) -> None:
    if not all(torch.isfinite(tensor).all().item() for tensor in tensors):
        # A non-finite prediction has no valid JSON or forecasting meaning.
        # Surface it as an input-domain error rather than an opaque serializer
        # 500, without silently replacing model output or changing semantics.
        raise HTTPException(
            422,
            "forecast produced non-finite values; check the input scale and missing values",
        )


def _forecast_sync(req: ChronosRequest):
    with model_manager.use("chronos2"):
        return _forecast_loaded_sync(req)


def _forecast_loaded_sync(req: ChronosRequest):
    """Synchronous GPU work for forecasting."""
    t0 = time.time()
    quantile_levels = req.quantile_levels or [0.1, 0.5, 0.9]

    if req.past_covariates:
        # Multivariate path: build a rich task so Chronos-2 attends across
        # covariates. Lengths are validated by the pipeline; surface as 400.
        hist = len(req.values)
        for name, col in req.past_covariates.items():
            if len(col) != hist:
                raise HTTPException(
                    400,
                    f"past_covariate {name!r} length {len(col)} != values length {hist}",
                )
        for name, col in (req.future_covariates or {}).items():
            if name not in req.past_covariates:
                raise HTTPException(400, f"future_covariate {name!r} has no matching past_covariate")
            if len(col) != req.prediction_length:
                raise HTTPException(
                    400,
                    f"future_covariate {name!r} length {len(col)} != prediction_length {req.prediction_length}",
                )
        task = {
            "target": req.values,
            "past_covariates": req.past_covariates,
        }
        if req.future_covariates:
            task["future_covariates"] = req.future_covariates
        quantiles, mean = chronos_pipeline.predict_quantiles(
            [task],
            prediction_length=req.prediction_length,
            quantile_levels=quantile_levels,
        )
    else:
        context = torch.tensor(req.values, dtype=torch.float32)
        quantiles, mean = chronos_pipeline.predict_quantiles(
            context,
            prediction_length=req.prediction_length,
            quantile_levels=quantile_levels,
        )

    elapsed = time.time() - t0

    q_tensor = quantiles[0].squeeze(0)
    m_tensor = mean[0].squeeze(0)
    _require_finite_forecast(q_tensor, m_tensor)

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
    try:
        model_manager.ensure_loaded("chronos2")
    except Exception as e:
        logger.exception("chronos2 load failed")
        raise HTTPException(503, f"chronos2 model failed to load: {e}") from e
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
    series: list[list[float]] = Field(min_length=1, max_length=64)  # list of time series
    prediction_length: int = Field(default=64, ge=1, le=1024)
    quantile_levels: Optional[list[float]] = None
    constrain_ohlc: bool = False  # if True, reorder so high >= open,close >= low

    @field_validator("series")
    @classmethod
    def validate_series(cls, series: list[list[float]]) -> list[list[float]]:
        for index, values in enumerate(series):
            if len(values) > 8192:
                raise ValueError(f"series[{index}] must contain at most 8192 values")
            _validate_chronos_series(values, f"series[{index}]")
        return series

    @field_validator("quantile_levels")
    @classmethod
    def validate_quantile_levels(cls, levels: Optional[list[float]]):
        return _validate_chronos_quantile_levels(levels)


def _forecast_batch_sync(req: ChronosBatchRequest):
    with model_manager.use("chronos2"):
        return _forecast_batch_loaded_sync(req)


def _forecast_batch_loaded_sync(req: ChronosBatchRequest):
    """Batch GPU forecasting — all series in one model call."""
    t0 = time.time()
    contexts = [torch.tensor(s, dtype=torch.float32) for s in req.series]
    quantile_levels = req.quantile_levels or [0.1, 0.5, 0.9]

    # Pass the list directly: the pipeline left-pads with NaN (treated as
    # missing). Zero-padding here would poison instance-norm stats and make a
    # short series forecast differently in a batch than alone.
    quantiles, mean = chronos_pipeline.predict_quantiles(
        contexts,
        prediction_length=req.prediction_length,
        quantile_levels=quantile_levels,
    )

    elapsed = time.time() - t0

    results = []
    for i in range(len(req.series)):
        m_tensor = mean[i].squeeze(0)
        q_tensor = quantiles[i].squeeze(0)
        _require_finite_forecast(m_tensor, q_tensor)
        m = m_tensor.tolist()
        q = {
            str(ql): q_tensor[:, j].tolist()
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
    try:
        model_manager.ensure_loaded("chronos2")
    except Exception as e:
        logger.exception("chronos2 load failed")
        raise HTTPException(503, f"chronos2 model failed to load: {e}") from e
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
    text: str = Field(..., min_length=1)
    voice: str = "af_nicole"
    speed: float = 1.0

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be empty")
        return value


def _tg_backend_headers(*, caption: bool = False) -> dict[str, str]:
    """Return the scoped service credential without exposing it in errors."""
    key = CAPTION_BACKEND_API_KEY if caption and CAPTION_BACKEND_API_KEY else (TG_API_KEY or CAPTION_BACKEND_API_KEY)
    return {"secret": key} if key else {}


def _tg_backend_error(service: str, exc: httpx.HTTPError) -> HTTPException:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in {401, 403}:
            logger.error("%s backend rejected proxy credentials (status=%d)", service, status)
            return HTTPException(502, f"{service} backend authentication failed")
        if 400 <= status < 500:
            logger.info("%s backend rejected request (status=%d)", service, status)
            return HTTPException(status, f"{service} request rejected by backend")
    logger.error("%s backend request failed: %s", service, exc)
    return HTTPException(502, f"{service} backend request failed")


@app.post("/synthesize")
async def synthesize(req: TTSRequest):
    try:
        resp = await tg_client.post(
            "/api/v1/generate_speech",
            json={"text": req.text, "voice": req.voice, "speed": req.speed},
            headers=_tg_backend_headers(),
        )
        resp.raise_for_status()
        # Return audio bytes directly
        return Response(
            content=resp.content,
            media_type="audio/wav",
            headers={"X-Voice": req.voice},
        )
    except httpx.HTTPError as e:
        raise _tg_backend_error("TTS", e) from e


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
            headers=_tg_backend_headers(),
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        raise _tg_backend_error("STT", e) from e


@app.post("/transcribe_file")
async def transcribe_file(audio_file: UploadFile = File(...)):
    try:
        content = await audio_file.read()
        resp = await tg_client.post(
            "/api/v1/audio-file-extraction",
            files={"audio_file": (audio_file.filename, content, audio_file.content_type or "audio/wav")},
            headers=_tg_backend_headers(),
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        raise _tg_backend_error("STT", e) from e


# ---------------------------------------------------------------------------
# Image Captioning (proxy to text-generator.io GitBase)
# ---------------------------------------------------------------------------

class CaptionRequest(BaseModel):
    image_url: str


def _caption_backend_headers() -> dict[str, str]:
    """Return caption-specific auth, allowing independent credential rotation."""
    return _tg_backend_headers(caption=True)


def _caption_backend_error(exc: httpx.HTTPError) -> HTTPException:
    return _tg_backend_error("Caption", exc)


@app.post("/caption")
async def caption_image(req: CaptionRequest):
    await asyncio.get_event_loop().run_in_executor(
        None, _validate_remote_image_url, req.image_url, "image_url"
    )
    try:
        resp = await tg_client.post(
            "/api/v1/image-caption",
            data={"image_url": req.image_url, "fast_mode": "true"},
            headers=_caption_backend_headers(),
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        raise _caption_backend_error(e) from e


@app.post("/caption_file")
async def caption_file(image_file: UploadFile = File(...)):
    try:
        content = await image_file.read()
        resp = await tg_client.post(
            "/api/v1/image-caption",
            files={"image_file": (image_file.filename, content, image_file.content_type or "image/jpeg")},
            data={"fast_mode": "true"},
            headers=_caption_backend_headers(),
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        raise _caption_backend_error(e) from e


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
            headers=_tg_backend_headers(),
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        raise _tg_backend_error("Gemma4", e) from e


# ---------------------------------------------------------------------------
# stable-diffusion-server compatible API (secret-protected, R2 upload)
# Compatible with netwrck/stable-diffusion-server endpoints so we can
# remap image.netwrck.com traffic here.
# ---------------------------------------------------------------------------

from r2_upload import (
    upload_bytes, check_if_blob_exists, build_save_path,
)


def _validated_save_path(save_path: str, suffix: str | None = None) -> str:
    """Build a safe object key suffix or reject traversal/control input."""
    if len(save_path) > 1024:
        raise HTTPException(400, "save_path is too long")
    if "\\" in save_path or any(ord(char) < 32 for char in save_path):
        raise HTTPException(400, "save_path contains invalid characters")
    parts = [part for part in save_path.split("/") if part]
    if not parts or len(parts) > 32 or any(part in {".", ".."} for part in parts):
        raise HTTPException(400, "save_path must be a relative object path without traversal")
    built = build_save_path(save_path, suffix=suffix)
    if not built or len(built) > 1024:
        raise HTTPException(400, "save_path is invalid")
    return built


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


def _fallback_image_path(prompt: str, seed: int, steps: int | None = None) -> str:
    slug = prompt[:60].replace(" ", "_").replace("/", "_")
    step_suffix = f"_s{steps}" if steps is not None and steps != ZIMAGE_DEFAULT_STEPS else ""
    return f"{slug}_{seed}{step_suffix}.webp"


def _normalize_zimage_steps(value: int | None) -> int:
    return max(1, int(value if value is not None else ZIMAGE_DEFAULT_STEPS))


def _generate_and_upload_sync(prompt: str, width: int, height: int, save_path: str,
                               auto_lora: bool = True, lora_id: str | None = None,
                               return_perf: bool = False,
                               num_inference_steps: int | None = None) -> dict:
    seed = int(hashlib.md5(prompt.encode()).hexdigest()[:8], 16) % (2**31)
    steps = _normalize_zimage_steps(num_inference_steps)
    target_path = save_path or _fallback_image_path(prompt, seed, steps)
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
        num_inference_steps=steps,
        auto_lora=auto_lora,
        lora_id=lora_id,
    )
    lora, final_prompt = _resolve_lora(req)

    w = (width // 64) * 64 or 1024
    h = (height // 64) * 64 or 1024

    t0 = time.time()
    generator = _make_pipeline_generator(text2img_pipe, req.seed)

    pipe_kwargs = dict(
        prompt=final_prompt, width=w, height=h,
        num_inference_steps=steps,
        guidance_scale=ZIMAGE_DEFAULT_GUIDANCE,
        generator=generator,
    )
    pipe_kwargs, prompt_cache_meta = _prepare_zimage_prompt_embeddings(text2img_pipe, pipe_kwargs)
    _reset_zimage_scheduler(text2img_pipe)
    pipeline_timing = {}
    exit_info: dict = {}

    if lora:
        try:
            _activate_lora(text2img_pipe, lora, lora_scale=_effective_lora_scale(lora))
            with _nvtx_range("zimage.full.pipeline_lora"):
                result, _ = _run_zimage_capture_multi(
                    text2img_pipe, pipe_kwargs, (), pipeline_timing,
                    early_exit=ZIMAGE_EARLY_EXIT or None,
                    early_exit_min_steps=ZIMAGE_EARLY_EXIT_MIN_STEPS,
                    exit_info=exit_info,
                    log_prompt=final_prompt,
                )
        except Exception as e:
            logger.warning("LoRA %s failed, generating without: %s", lora.id, e)
            _deactivate_loras(text2img_pipe)
            _reset_zimage_scheduler(text2img_pipe)
            with _nvtx_range("zimage.full.pipeline"):
                pipeline_timing = {}
                exit_info = {}
                result, _ = _run_zimage_capture_multi(text2img_pipe, pipe_kwargs, (), pipeline_timing)
            lora = None
    else:
        _deactivate_loras(text2img_pipe)
        capture = _capture_steps_for(steps) if _latent_save_active() else ()
        with _nvtx_range("zimage.full.pipeline"):
            result, captured = _run_zimage_capture_multi(
                text2img_pipe, pipe_kwargs, capture, pipeline_timing,
                early_exit=ZIMAGE_EARLY_EXIT or None,
                early_exit_min_steps=ZIMAGE_EARLY_EXIT_MIN_STEPS,
                exit_info=exit_info,
                log_prompt=final_prompt,
            )
        if exit_info.get("exited_after_step"):
            captured = {}
        if captured:
            cached_conditioning = (pipe_kwargs.get("prompt_embeds") or [None])[0]
            _persist_generation_latents(final_prompt, req.seed, steps,
                                        w, h, ZIMAGE_DEFAULT_GUIDANCE, captured,
                                        text_embedding=cached_conditioning)

    image = result.images[0]
    elapsed = time.time() - t0
    logger.info("compat: %dx%d in %.2fs (lora=%s%s)", w, h, elapsed,
                lora.id if lora else "none",
                f", early_exit@{exit_info['exited_after_step']}" if exit_info.get("exited_after_step") else "")

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
            "steps": steps,
            "lora": lora.id if lora else None,
            "prompt_embedding_cache": prompt_cache_meta,
            "pipeline_timing": pipeline_timing,
            "early_exit": exit_info or None,
        }
    return result


def _latent_teleport_unit(prompt: str, width: int, height: int, steps: int, seed: int,
                          guidance: float | None = None, lora=None):
    from latentteleport.tokenizer import VisualUnit

    if guidance is None:
        guidance = ZIMAGE_DEFAULT_GUIDANCE
    precision_mode = (PRECISION or {}).get("mode", DTYPE_STR)
    compile_mode = _get_zimage_compile_mode() or "eager"
    # The text encoder's placement/quantization changes the conditioning tensors
    # slightly, so latents captured under a different encoder are not valid to
    # resume from — keep it in the key instead of silently replaying stale work.
    encoder = _zimage_text_encoder_placement or ZIMAGE_TEXT_ENCODER_DEVICE or str(DEVICE)
    lora_key = f"{lora.id}@{lora.scale}" if lora is not None else "none"
    key = (
        f"cache={ZIMAGE_LATENT_CACHE_VERSION}|model={ZIMAGE_MODEL_PATH}|"
        f"precision={precision_mode}|dtype={DTYPE_STR}|cute={int(ZIMAGE_USE_CUTE)}|"
        f"encoder={encoder}|lora={lora_key}|"
        f"compile={compile_mode}|early_exit={ZIMAGE_EARLY_EXIT}|"
        f"early_exit_min={ZIMAGE_EARLY_EXIT_MIN_STEPS}|"
        f"early_exit_consecutive={ZIMAGE_EARLY_EXIT_CONSECUTIVE}|"
        f"skip_noop={int(ZIMAGE_SKIP_NOOP_STEPS)}|"
        f"{prompt}|{width}x{height}|steps={steps}|seed={seed}|guidance={guidance}"
    )
    return VisualUnit.from_text(key)


def _teleport_approximate_replay(
    pipe,
    cache,
    final_prompt: str,
    width: int,
    height: int,
    steps: int,
    resume_step: int,
    capture_step: int,
    guidance_scale: float | None,
    seed: int,
    min_sim_override: float | None,
):
    """Resume from the nearest cached latent of a *different* but similar prompt.

    Returns ``(image, meta)`` when a neighbour clears the similarity floor, else
    ``None`` so the caller runs the normal schedule. Every failure mode falls
    through to a full generation: an approximate hit is an optimization, never a
    correctness requirement.
    """
    from latentteleport.refine import refine_from_latent

    min_sim = LATENT_TELEPORT_APPROX_MIN_SIM if min_sim_override is None else min_sim_override
    try:
        encode_started = time.time()
        with _nvtx_range("zimage.teleport.approx_prompt_embed"):
            text_emb, _ = pipe.encode_prompt(
                prompt=final_prompt,
                negative_prompt=None,
                do_classifier_free_guidance=False,
                device=DEVICE,
            )
        encode_ms = int((time.time() - encode_started) * 1000)
        target_emb = text_emb[0].detach().cpu() if isinstance(text_emb, list) else text_emb.detach().cpu()
        pooled = target_emb.float().mean(0) if target_emb.dim() == 2 else target_emb.float()
        nearest = cache.find_nearest(pooled, top_k=1)
        if not nearest:
            return None
        source_unit_id, source_text, sim = nearest[0]
        if sim < min_sim:
            return None
        source_unit = cache.load_unit_by_id(source_unit_id)
        source_latent = cache.load_latent(source_unit, capture_step) if source_unit is not None else None
        if source_latent is None:
            return None
        replay_started = time.time()
        with _nvtx_range("zimage.teleport.approx_replay"):
            image = refine_from_latent(
                pipe,
                source_latent,
                final_prompt,
                None,
                resume_step,
                prompt_embeds=[target_emb],
                num_total_steps=steps,
                height=height,
                width=width,
                guidance_scale=guidance_scale,
                seed=seed,
                device=DEVICE,
            )
    except Exception as exc:
        logger.warning("approximate latent teleport failed; running full generation: %s", exc)
        return None

    return image, {
        "method": "approx_prompt_latent_replay",
        "cache_hit": True,
        "approx_hit": True,
        "approx_similarity": float(sim),
        "approx_source": source_text,
        "encode_ms": encode_ms,
        "inference_time_ms": int((time.time() - replay_started) * 1000) + encode_ms,
    }


def _get_latent_teleport_cache(width: int, height: int):
    global latent_teleport_cache
    if latent_teleport_cache is None or latent_teleport_cache.resolution != (height, width):
        from latentteleport.cache import LatentCache

        latent_teleport_cache = LatentCache(
            LATENT_TELEPORT_CACHE_DIR,
            resolution=(height, width),
            max_entries=LATENT_TELEPORT_MAX_ENTRIES_PER_RESOLUTION,
            max_bytes=int(LATENT_TELEPORT_MAX_GIB_PER_RESOLUTION * 1024**3),
            prune_interval_s=LATENT_TELEPORT_PRUNE_INTERVAL_SECONDS,
        )
    return latent_teleport_cache


_lt_tokenizer = None


def _get_lt_tokenizer():
    global _lt_tokenizer
    if _lt_tokenizer is None:
        from latentteleport.tokenizer import CuratedTokenizer

        _lt_tokenizer = CuratedTokenizer()
    return _lt_tokenizer


def _latent_save_active() -> bool:
    return LATENT_TELEPORT_ENABLED and LATENT_SAVE


def _capture_steps_for(steps: int) -> tuple[int, ...]:
    cap_step = max(0, min(LATENT_TELEPORT_START_STEP - 1, steps - 2))
    return tuple(sorted({cap_step, steps - 1}))


def _run_zimage_capture_multi(pipe, pipe_kwargs: dict, capture_steps,
                              timing_out: dict | None = None,
                              early_exit: float | None = None,
                              early_exit_min_steps: int = 4,
                              exit_info: dict | None = None,
                              log_prompt: str | None = None) -> tuple[object, dict[int, torch.Tensor]]:
    if not capture_steps and timing_out is None and not early_exit and not ZIMAGE_SKIP_NOOP_STEPS:
        return pipe(**pipe_kwargs), {}
    captured: dict[int, torch.Tensor] = {}
    callback_times: list[float] = []
    prev_latent: list = [None]
    prev_x0: list = [None]
    below_count: list = [0]
    dx0_curve: list[float] = []
    started = time.perf_counter()

    def _capture(_pipe, step_index, _timestep, callback_kwargs):  # noqa: ANN001
        callback_times.append(time.perf_counter())
        z = callback_kwargs.get("latents")
        if step_index in capture_steps and z is not None:
            captured[step_index] = z.detach().clone().cpu()
        if ZIMAGE_SKIP_NOOP_STEPS and z is not None and not getattr(_pipe, "interrupt", False):
            total = getattr(_pipe, "_num_timesteps", 0)
            if step_index < total - 1:
                try:
                    noop = float(_pipe.scheduler.sigmas[step_index + 1]) <= 0.0
                except Exception:
                    noop = False
                if noop:
                    # sigma is already 0: every remaining step moves z by
                    # (0 - 0) * v, so skipping is bitwise-identical.
                    _pipe._interrupt = True
                    for k in capture_steps:
                        if k > step_index and k not in captured:
                            captured[k] = z.detach().clone().cpu()
                    if exit_info is not None:
                        exit_info["noop_steps_skipped"] = total - 1 - step_index
        if (early_exit or DX0_LOG) and z is not None:
            total = getattr(_pipe, "_num_timesteps", 0)
            zp = prev_latent[0]
            if zp is not None and step_index < total - 1:
                sig = _pipe.scheduler.sigmas
                s_prev = float(sig[step_index])
                s_cur = float(sig[step_index + 1])
                denom = s_cur - s_prev
                if abs(denom) > 1e-9:
                    # x0-hat: Euler-extrapolate to sigma=0 with this step's velocity.
                    # Threshold on x0-hat movement, not raw latent movement: the
                    # shifted few-step schedule takes growing sigma jumps so dz
                    # never shrinks, while the denoised prediction stabilizes.
                    x0 = z - s_cur * ((z - zp) / denom)
                    x0p = prev_x0[0]
                    if x0p is not None:
                        rel = ((x0 - x0p).norm() / x0.norm().clamp_min(1e-8)).item()
                        dx0_curve.append(round(rel, 5))
                        # hysteresis: require ZIMAGE_EARLY_EXIT_CONSECUTIVE
                        # consecutive below-threshold steps; flat slowly-decaying
                        # curves (high-texture prompts) fail a single-hit rule.
                        below_count[0] = below_count[0] + 1 if (early_exit and rel < early_exit) else 0
                        if (early_exit and not getattr(_pipe, "interrupt", False)
                                and (step_index + 1) >= early_exit_min_steps
                                and below_count[0] >= ZIMAGE_EARLY_EXIT_CONSECUTIVE):
                            if s_cur > 0:
                                callback_kwargs["latents"] = x0
                            _pipe._interrupt = True
                            if exit_info is not None:
                                exit_info.update({
                                    "exited_after_step": step_index + 1,
                                    "total_steps": total,
                                    "dx0_rel": round(rel, 6),
                                    "threshold": early_exit,
                                })
                    prev_x0[0] = x0
            prev_latent[0] = z
        return callback_kwargs

    try:
        result = pipe(
            **pipe_kwargs,
            callback_on_step_end=_capture,
            callback_on_step_end_tensor_inputs=["latents"],
        )
    except TypeError:
        logger.debug("pipeline does not support step callbacks; latent save skipped")
        callback_times.clear()
        result = pipe(**pipe_kwargs)
    finished = time.perf_counter()
    if timing_out is not None:
        timing_out.update({
            "pipeline_ms": int((finished - started) * 1000),
            "denoise_through_last_step_ms": (
                int((callback_times[-1] - started) * 1000) if callback_times else None
            ),
            "postprocess_after_last_step_ms": (
                int((finished - callback_times[-1]) * 1000) if callback_times else None
            ),
            "physical_steps_observed": len(callback_times) or None,
        })
        if dx0_curve:
            timing_out["dx0_curve"] = dx0_curve
    if DX0_LOG and dx0_curve:
        try:
            with open(DX0_CORPUS_PATH, "a") as f:
                f.write(json.dumps({
                    "t": int(time.time()),
                    "prompt": log_prompt,
                    "steps": getattr(pipe, "_num_timesteps", None),
                    "physical_steps": len(callback_times),
                    "dx0_curve": dx0_curve,
                    "exited_after_step": (exit_info or {}).get("exited_after_step"),
                    "width": pipe_kwargs.get("width"),
                    "height": pipe_kwargs.get("height"),
                }) + "\n")
        except Exception as e:
            logger.debug("dx0 corpus write failed: %s", e)
    return result, captured


def _persist_generation_latents(prompt: str, seed: int, steps: int, width: int, height: int,
                                guidance: float, captured: dict[int, torch.Tensor],
                                text_embedding: torch.Tensor | None = None):
    """Persist latents already computed during normal generation. Zero extra inference."""
    if not captured:
        return
    if text_embedding is not None:
        text_embedding = text_embedding.detach()
    try:
        cache = _get_latent_teleport_cache(width, height)
        unit = _latent_teleport_unit(prompt, width, height, steps, seed, guidance)
        if cache.has_unit(unit):
            return
        cache.store_latents(
            unit,
            captured,
            text_embedding=text_embedding,
            metadata={"prompt": prompt, "seed": seed, "steps": steps,
                      "width": width, "height": height, "guidance": guidance,
                      "mode": "generation_capture"},
        )
        try:
            word_units = _get_lt_tokenizer().tokenize(prompt)
        except Exception:
            word_units = []
        try:
            cache.record_prompt(prompt, unit, word_units, seed=seed,
                                width=width, height=height, steps=steps)
        except Exception as e:
            logger.debug("record_prompt failed: %s", e)
        logger.info("latent saved: unit=%s steps=%s words=%d", unit.unit_id,
                    list(captured), len(word_units))
    except Exception as e:
        logger.warning("latent save failed: %s", e)


def _generate_and_upload_teleport_sync(prompt: str, width: int, height: int, save_path: str,
                                       auto_lora: bool = True, lora_id: str | None = None,
                                       return_perf: bool = False,
                                       num_inference_steps: int | None = None,
                                       teleport_approx: bool = False,
                                       teleport_approx_min_sim: float | None = None,
                                       teleport_start_step: int | None = None) -> dict:
    if not LATENT_TELEPORT_ENABLED:
        raise HTTPException(400, "latent teleportation disabled")

    seed = int(hashlib.md5(prompt.encode()).hexdigest()[:8], 16) % (2**31)
    steps = _normalize_zimage_steps(num_inference_steps)
    target_path = save_path or _fallback_image_path(prompt, seed, steps)
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
        return _generate_and_upload_sync(prompt, width, height, save_path, auto_lora, lora_id, return_perf, num_inference_steps)

    w = (width // 64) * 64 or 1024
    h = (height // 64) * 64 or 1024
    requested_resume_step = LATENT_TELEPORT_START_STEP if teleport_start_step is None else teleport_start_step
    resume_step = max(1, min(int(requested_resume_step), steps - 1))
    capture_step = resume_step - 1
    cache = _get_latent_teleport_cache(w, h)
    unit = _latent_teleport_unit(final_prompt, w, h, steps, req.seed)
    cached_latent = cache.load_latent(unit, capture_step)
    cached_prompt_emb = cache.load_text_embedding_full(unit) if cached_latent is not None else None
    approximate_hit = False
    approximate_source = None
    approximate_similarity = None

    generator = _make_pipeline_generator(text2img_pipe, req.seed)
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
        "requested_resume_step": requested_resume_step,
        "approx_enabled": teleport_approx,
        "prompt_embedding_cache": {
            "enabled": ZIMAGE_PROMPT_CACHE_SIZE > 0,
            "hit": cached_prompt_emb is not None,
            "encode_ms": 0,
            "source": "latent_cache" if cached_prompt_emb is not None else None,
        },
    }

    if cached_latent is not None:
        from latentteleport.refine import refine_from_latent

        try:
            free_mb = _cuda_free_mb()
            if cached_prompt_emb is None and free_mb is not None and free_mb < LATENT_TELEPORT_MIN_FREE_MB:
                raise RuntimeError(f"insufficient free CUDA memory for prompt embedding replay ({free_mb} MB)")
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

    if cached_latent is None and teleport_approx:
        from latentteleport.refine import refine_from_latent

        min_sim = LATENT_TELEPORT_APPROX_MIN_SIM if teleport_approx_min_sim is None else teleport_approx_min_sim
        try:
            with _nvtx_range("zimage.teleport.approx_prompt_embed"):
                text_emb, _ = text2img_pipe.encode_prompt(
                    prompt=final_prompt,
                    negative_prompt=None,
                    do_classifier_free_guidance=False,
                    device=DEVICE,
                )
            target_emb = text_emb[0].detach().cpu() if isinstance(text_emb, list) else text_emb.detach().cpu()
            pooled_emb = target_emb.float().mean(0) if target_emb.dim() == 2 else target_emb.float()
            nearest = cache.find_nearest(pooled_emb, top_k=1)
            if nearest:
                source_unit_id, source_text, sim = nearest[0]
                source_unit = cache.load_unit_by_id(source_unit_id)
                source_latent = cache.load_latent(source_unit, capture_step) if source_unit is not None else None
                if source_latent is not None and sim >= min_sim:
                    with _nvtx_range("zimage.teleport.approx_replay"):
                        image = refine_from_latent(
                            text2img_pipe,
                            source_latent,
                            final_prompt,
                            None,
                            resume_step,
                            prompt_embeds=[target_emb],
                            num_total_steps=steps,
                            height=h,
                            width=w,
                            guidance_scale=ZIMAGE_DEFAULT_GUIDANCE,
                            seed=req.seed,
                            device=DEVICE,
                        )
                    cached_latent = source_latent
                    approximate_hit = True
                    approximate_source = source_text
                    approximate_similarity = sim
                    teleport_meta.update({
                        "cache_hit": True,
                        "approx_cache_hit": True,
                        "method": "approx_nearest_latent_replay",
                        "approx_similarity": sim,
                        "approx_source": source_text,
                    })
                elif nearest:
                    teleport_meta.update({
                        "approx_cache_hit": False,
                        "approx_similarity": sim,
                        "approx_min_similarity": min_sim,
                        "approx_rejected": True,
                    })
        except Exception as e:
            logger.warning("latent teleport approximate replay failed, falling back to full generation: %s", e)
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            teleport_meta["approx_fallback_reason"] = type(e).__name__

    if cached_latent is None:
        pipe_kwargs, prompt_cache_meta = _prepare_zimage_prompt_embeddings(text2img_pipe, pipe_kwargs)
        teleport_meta["prompt_embedding_cache"] = prompt_cache_meta
        pipeline_timing = {}
        with _nvtx_range("zimage.teleport.prime_pipeline"):
            result, captured = _run_zimage_capture_multi(
                text2img_pipe,
                pipe_kwargs,
                tuple(sorted({capture_step, steps - 1})),
                pipeline_timing,
            )
        teleport_meta["pipeline_timing"] = pipeline_timing
        image = result.images[0]
        if capture_step in captured:
            emb = (pipe_kwargs.get("prompt_embeds") or [None])[0]
            cache.store_latents(
                unit,
                captured,
                text_embedding=emb,
                metadata={"prompt": final_prompt, "seed": req.seed, "steps": steps,
                          "width": w, "height": h, "mode": "exact_prompt"},
            )
            try:
                cache.record_prompt(final_prompt, unit, _get_lt_tokenizer().tokenize(final_prompt),
                                    seed=req.seed, width=w, height=h, steps=steps)
            except Exception as e:
                logger.debug("record_prompt failed: %s", e)
        teleport_meta["method"] = "full_generation_cached_latent"

    elapsed = time.time() - t0
    logger.info(
        "compat teleport: %dx%d in %.2fs (method=%s, hit=%s, approx=%s, sim=%s)",
        w, h, elapsed, teleport_meta["method"], teleport_meta["cache_hit"],
        approximate_hit, f"{approximate_similarity:.3f}" if approximate_similarity is not None else "n/a",
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
            "cache_hit": teleport_meta["cache_hit"],
            "inference_time_ms": int(elapsed * 1000),
            "encode_time_ms": int(encode_elapsed * 1000),
            "upload_time_ms": int(upload_elapsed * 1000),
            "width": w,
            "height": h,
            "steps": steps,
            "teleport_method": teleport_meta["method"],
            "teleport_cache_hit": teleport_meta["cache_hit"],
            "teleport_capture_step": capture_step,
            "teleport_resume_step": resume_step,
            "teleport_approx_cache_hit": approximate_hit,
            "teleport_approx_similarity": approximate_similarity,
            "teleport_approx_source": approximate_source,
            "prompt_embedding_cache": teleport_meta["prompt_embedding_cache"],
            "pipeline_timing": teleport_meta.get("pipeline_timing"),
        }
    return result


def _generate_and_upload_native_sync(
    prompt: str,
    width: int,
    height: int,
    save_path: str,
    auto_lora: bool,
    lora_id: str | None,
    return_perf: bool,
    num_inference_steps: int | None,
    *,
    teleport: bool,
    low_priority: bool = False,
    teleport_approx: bool = False,
    teleport_start_step: int | None = None,
) -> dict:
    """Generate through the resident native backend and preserve the upload API."""
    seed = int(hashlib.md5(prompt.encode()).hexdigest()[:8], 16) % (2**31)
    steps = _normalize_zimage_steps(num_inference_steps)
    target_path = save_path or _fallback_image_path(prompt, seed, steps)
    if target_path and check_if_blob_exists(target_path):
        from r2_upload import R2_PUBLIC_BASE_URL, R2_BUCKET_PATH
        result = {"path": f"https://{R2_PUBLIC_BASE_URL}/{R2_BUCKET_PATH}/{target_path}"}
        if teleport:
            result["teleport"] = {"method": "r2_cache", "cache_hit": True}
        if return_perf:
            result["perf"] = {"cache_hit": True, "upload_time_ms": 0, "inference_time_ms": 0}
        return result

    req = ZImageRequest(
        prompt=prompt,
        width=width,
        height=height,
        seed=seed,
        num_inference_steps=steps,
        guidance_scale=ZIMAGE_DEFAULT_GUIDANCE,
        lora_id=lora_id,
        auto_lora=auto_lora,
        quality_retry=False,
        enhance_prompt=False,
        teleport=teleport,
        teleport_approx=teleport_approx,
        low_priority=low_priority,
    )
    payload, lora = _native_zimage_request(req, prompt)
    if teleport_start_step is not None and teleport and lora is None:
        payload["teleport_start_step"] = max(1, min(int(teleport_start_step), steps - 1))
    started = time.perf_counter()
    try:
        native = _call_resilient_zimage(payload, lora)
    except HTTPException as exc:
        if lora is None or not _native_lora_validation_failure(exc):
            raise
        logger.warning("native LoRA %s failed; retrying upload generation without LoRA", lora.id)
        for key in ("lora_id", "lora_filename", "lora_scale"):
            payload.pop(key, None)
        native = _call_resilient_zimage(payload)
        lora = None
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    upload_started = time.perf_counter()
    url = upload_bytes(
        target_path,
        native["image_bytes"],
        content_type=f"image/{native['format']}",
    )
    upload_ms = int((time.perf_counter() - upload_started) * 1000)
    result = {"path": url}
    teleport_meta = native.get("teleport") if teleport and lora is None else None
    if teleport:
        result["teleport"] = teleport_meta or {
            "method": "full_generation_lora" if lora else "full_generation",
            "cache_hit": False,
        }
    if return_perf:
        result["perf"] = {
            "cache_hit": bool((teleport_meta or {}).get("cache_hit")),
            "inference_time_ms": native["inference_time_ms"] or elapsed_ms,
            "encode_time_ms": 0,
            "upload_time_ms": upload_ms,
            "width": native["width"],
            "height": native["height"],
            "steps": steps,
            "lora": lora.id if lora else None,
            "backend": native.get("backend") or "omniserve-native",
            "backend_model": native["model"],
        }
        if teleport:
            result["perf"].update({
                "teleport_method": (teleport_meta or {}).get("method"),
                "teleport_cache_hit": bool((teleport_meta or {}).get("cache_hit")),
            })
    logger.info(
        "%s fallback upload: %dx%d in %.2fs (steps=%d, teleport=%s, lora=%s)",
        native.get("backend") or "omniserve-native",
        native["width"], native["height"], elapsed_ms / 1000, steps,
        teleport, lora.id if lora else "none",
    )
    return result


def _generate_and_upload_with_model_sync(prompt: str, width: int, height: int, save_path: str,
                                         auto_lora: bool = True, lora_id: str | None = None,
                                         return_perf: bool = False,
                                         num_inference_steps: int | None = None,
                                         low_priority: bool = False) -> dict:
    if _should_use_native_zimage_fallback("create_and_upload_image"):
        try:
            return _generate_and_upload_native_sync(
                prompt, width, height, save_path, auto_lora, lora_id,
                return_perf, num_inference_steps, teleport=False,
                low_priority=low_priority,
            )
        except HTTPException:
            if not _native_failure_allows_local_cold_load("create_and_upload_image"):
                raise
            logger.exception(
                "native upload fallback failed with safe BF16 headroom; trying the local loader"
            )
    return _with_zimage_model_retry(
        "create_and_upload_image",
        lambda: _generate_and_upload_sync(prompt, width, height, save_path, auto_lora, lora_id, return_perf, num_inference_steps),
    )


def _generate_and_upload_teleport_with_model_sync(prompt: str, width: int, height: int, save_path: str,
                                                  auto_lora: bool = True, lora_id: str | None = None,
                                                  return_perf: bool = False,
                                                  num_inference_steps: int | None = None,
                                                  teleport_approx: bool = False,
                                                  teleport_approx_min_sim: float | None = None,
                                                  teleport_start_step: int | None = None,
                                                  low_priority: bool = False) -> dict:
    if _should_use_native_zimage_fallback("create_and_upload_image_teleport"):
        try:
            return _generate_and_upload_native_sync(
                prompt, width, height, save_path, auto_lora, lora_id,
                return_perf, num_inference_steps, teleport=True,
                low_priority=low_priority,
                teleport_approx=teleport_approx,
                teleport_start_step=teleport_start_step,
            )
        except HTTPException:
            if not _native_failure_allows_local_cold_load("create_and_upload_image_teleport"):
                raise
            logger.exception(
                "native teleport fallback failed with safe BF16 headroom; trying the local loader"
            )
    return _with_zimage_model_retry(
        "create_and_upload_image_teleport",
        lambda: _generate_and_upload_teleport_sync(
            prompt,
            width,
            height,
            save_path,
            auto_lora,
            lora_id,
            return_perf,
            num_inference_steps,
            teleport_approx,
            teleport_approx_min_sim,
            teleport_start_step,
        ),
    )


def _style_transfer_and_upload_sync(prompt: str, input_image: Image.Image, save_path: str,
                                     strength: float = 0.6) -> dict:
    if save_path and check_if_blob_exists(save_path):
        from r2_upload import R2_PUBLIC_BASE_URL, R2_BUCKET_PATH
        url = f"https://{R2_PUBLIC_BASE_URL}/{R2_BUCKET_PATH}/{save_path}"
        return {"path": url}

    _, img2img_pipe = zimage_pipeline

    w = (input_image.width // 64) * 64 or 1024
    h = (input_image.height // 64) * 64 or 1024
    input_image = input_image.resize((w, h))

    t0 = time.time()
    seed = int(hashlib.md5(prompt.encode()).hexdigest()[:8], 16) % (2**31)
    generator = _make_pipeline_generator(img2img_pipe, seed)

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
    input_image = _load_remote_image(image_url)
    return _with_zimage_model_retry(
        "style_transfer_and_upload_image",
        lambda: _style_transfer_and_upload_sync(prompt, input_image, save_path, strength),
    )


@app.get("/create_and_upload_image")
async def create_and_upload_image(
    request: Request,
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
    num_inference_steps: int = ZIMAGE_DEFAULT_STEPS,
    teleport_approx: bool = False,
    teleport_approx_min_sim: float | None = None,
    teleport_start_step: int | None = None,
    low_priority: bool = False,
    background: bool = False,
):
    _check_secret(secret)
    _remember_request_prompt(request, prompt)
    _remember_request_inference_params(
        request,
        model=model,
        width=width,
        height=height,
        num_inference_steps=num_inference_steps,
        auto_lora=auto_lora,
        teleport=teleport,
        perf=perf,
        low_priority=low_priority or background,
    )
    _require_nonempty_prompt(prompt)
    sp = _validated_save_path(save_path) if save_path else ""
    if sp and check_if_blob_exists(sp):
        from r2_upload import R2_PUBLIC_BASE_URL, R2_BUCKET_PATH
        return {"path": f"https://{R2_PUBLIC_BASE_URL}/{R2_BUCKET_PATH}/{sp}"}
    with model_manager.reserve(
        "zimage",
        allow_while_held=_should_use_native_zimage_fallback("create_and_upload_image"),
    ):
        async with gpu_slot(low_priority or background):
            if teleport:
                return await asyncio.get_event_loop().run_in_executor(
                    None,
                    _generate_and_upload_teleport_with_model_sync,
                    prompt,
                    width,
                    height,
                    sp,
                    auto_lora,
                    lora_id,
                    perf,
                    num_inference_steps,
                    teleport_approx,
                    teleport_approx_min_sim,
                    teleport_start_step,
                    low_priority or background,
                )
            return await asyncio.get_event_loop().run_in_executor(
                None,
                _generate_and_upload_with_model_sync,
                prompt,
                width,
                height,
                sp,
                auto_lora,
                lora_id,
                perf,
                num_inference_steps,
                low_priority or background,
            )


@app.get("/style_transfer_and_upload_image")
async def style_transfer_and_upload_image(
    request: Request,
    prompt: str,
    image_url: str,
    save_path: str = "",
    strength: float = 0.6,
    model: str = "zimage-turbo",
    secret: str = "",
):
    _check_secret(secret)
    _remember_request_prompt(request, prompt)
    _require_nonempty_prompt(prompt)
    sp = _validated_save_path(save_path) if save_path else ""
    if sp and check_if_blob_exists(sp):
        from r2_upload import R2_PUBLIC_BASE_URL, R2_BUCKET_PATH
        return {"path": f"https://{R2_PUBLIC_BASE_URL}/{R2_BUCKET_PATH}/{sp}"}
    input_image = await asyncio.get_event_loop().run_in_executor(None, _load_remote_image, image_url)
    async with gpu_semaphore:
        return await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _with_zimage_model_retry(
                "style_transfer_and_upload_image",
                lambda: _style_transfer_and_upload_sync(prompt, input_image, sp, strength),
            ),
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
    _require_nonempty_prompt(prompt)
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
        sp = _validated_save_path(save_path, suffix=suffix) if save_path else f"style_{suffix}.webp"

        def _do():
            if hasattr(img2img_pipe, "_offload_gpu_id"):
                img2img_pipe.enable_model_cpu_offload()
            generator = _make_pipeline_generator(img2img_pipe, seed)
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
        sp = _validated_save_path(save_path) if save_path else ""
        input_image = await asyncio.get_event_loop().run_in_executor(None, _load_remote_image, image_url)
        async with gpu_semaphore:
            return await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: _with_zimage_model_retry(
                    "style_transfer_and_upload_image",
                    lambda: _style_transfer_and_upload_sync(prompt, input_image, sp, strength),
                ),
            )
    else:
        raise HTTPException(400, "either image_url or image_file required")


# ---------------------------------------------------------------------------
# LoRA Training API
# ---------------------------------------------------------------------------

# In-memory cache backed by JSON status files so long-running jobs survive a
# process restart and frontend polling can resume cleanly.
training_jobs: dict[str, dict] = load_jobs()
LOCAL_GPU_TRAINING_ENABLED = os.getenv("LOCAL_GPU_TRAINING_ENABLED", "1") == "1"
LOCAL_TRAINING_MAX_CONCURRENT = max(
    1, int(os.getenv("LOCAL_TRAINING_MAX_CONCURRENT", "1"))
)
_local_training_semaphore = threading.BoundedSemaphore(LOCAL_TRAINING_MAX_CONCURRENT)


def _require_local_gpu_training_enabled() -> None:
    if not LOCAL_GPU_TRAINING_ENABLED:
        raise HTTPException(
            409,
            "local GPU training is disabled on this inference-only worker; route training to the remote backend",
        )


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
    train_size: Optional[int] = None
    # "texture" enables a verified, toroidal-augmentation training path.
    dataset_mode: str = "standard"
    min_tileability: float = 0.72


def _validate_training_mode(model: str, dataset_mode: str, min_tileability: float) -> None:
    if dataset_mode not in ("standard", "texture"):
        raise HTTPException(400, "dataset_mode must be 'standard' or 'texture'")
    if not 0.0 < min_tileability <= 1.0:
        raise HTTPException(400, "min_tileability must be in (0, 1]")
    if dataset_mode == "texture" and model != "zimage":
        raise HTTPException(400, "texture dataset mode currently supports zimage only")


def _run_chronos2_training_impl(job_id: str, req: LoRATrainRequest):
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


def _run_zimage_training_impl(job_id: str, req: LoRATrainRequest):
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

        if req.dataset_mode == "texture":
            from texture_quality import measure_tileability

            verified_paths = []
            tile_scores = []
            for image_path in image_paths:
                try:
                    with PILImage.open(image_path) as candidate:
                        metrics = measure_tileability(candidate, threshold=req.min_tileability)
                    tile_scores.append(metrics.score)
                    if metrics.verified:
                        verified_paths.append(image_path)
                except Exception as quality_err:
                    logger.warning("Tileability check failed for %s: %s", os.path.basename(image_path), quality_err)
            image_paths = verified_paths
            job["tileability"] = {
                "accepted": len(verified_paths),
                "checked": len(tile_scores),
                "minimum": req.min_tileability,
                "mean_score": (sum(tile_scores) / len(tile_scores)) if tile_scores else 0,
            }
            _save_training_job(job_id)
            if len(image_paths) < 2:
                raise ValueError("texture training needs at least two tiles that pass the tileability gate")
        logger.info("Training job %s: %d images in dataset %s", job_id, len(image_paths), req.dataset_name)

        captions = {}
        for img_path in image_paths:
            txt_path = os.path.splitext(img_path)[0] + ".txt"
            if os.path.exists(txt_path):
                with open(txt_path) as f:
                    captions[img_path] = f.read().strip() or "a photo"
            else:
                captions[img_path] = "a photo"

        if req.dataset_mode == "texture":
            for img_path, caption in captions.items():
                if "seamless" not in caption.lower():
                    captions[img_path] = f"seamless tileable texture, {caption}"

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
        transformer = text2img_pipe.transformer
        vae = text2img_pipe.vae

        def _move_component(comp, device):
            if comp is None:
                return
            try:
                comp.to(device)
            except Exception:
                # Fallback for components initialized with meta tensors.
                comp.to_empty(device=device)

        def _free_cuda():
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        job["status"] = "preparing_lora"
        job["progress"] = 0.1
        _save_training_job(job_id)

        try:
            from peft import LoraConfig, get_peft_model
        except ImportError:
            raise ValueError("peft package required for LoRA training: pip install peft")

        # Pre-encode prompts using the pipeline's own encoder (handles Qwen3 correctly)
        prompt_embeds_cache: dict[str, torch.Tensor] = {}
        unique_captions = set(captions.values())
        logger.info("Training job %s: pre-encoding %d unique captions", job_id, len(unique_captions))
        _move_component(getattr(text2img_pipe, "text_encoder", None), DEVICE)
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
        _move_component(getattr(text2img_pipe, "text_encoder", None), "cpu")
        _free_cuda()

        # Pre-encode latents once at a fixed small size (saves time and memory)
        TRAIN_SIZE = int(req.train_size or os.getenv("LORA_TRAIN_SIZE", "384"))
        TRAIN_SIZE = max(64, min(TRAIN_SIZE, 1024))
        latent_cache: list[tuple[torch.Tensor, str]] = []
        logger.info("Training job %s: pre-encoding %d latents at %dx%d", job_id, len(image_paths), TRAIN_SIZE, TRAIN_SIZE)
        _move_component(vae, DEVICE)
        for p in vae.parameters():
            p.requires_grad = False
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

        _move_component(vae, "cpu")
        _free_cuda()

        if not latent_cache:
            raise RuntimeError("no latents could be encoded from the dataset (VAE failures)")

        _move_component(transformer, DEVICE)
        for p in transformer.parameters():
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
        if hasattr(transformer, "gradient_checkpointing_enable"):
            try:
                transformer.gradient_checkpointing_enable()
            except Exception as e:
                logger.warning("Training job %s: gradient checkpointing unavailable: %s", job_id, str(e)[:120])
        transformer.train()

        trainable = [p for p in transformer.parameters() if p.requires_grad]
        n_trainable = sum(p.numel() for p in trainable)
        logger.info("Training job %s: %d trainable LoRA params", job_id, n_trainable)

        optimizer = torch.optim.AdamW(trainable, lr=req.learning_rate)

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
                train_latent = latent
                if req.dataset_mode == "texture":
                    # Cyclic translation makes seam position uniformly random.
                    # It preserves exact periodicity and discourages the LoRA
                    # from treating any canvas edge as a privileged boundary.
                    shift_y = int(torch.randint(0, latent.shape[-2], (1,)).item())
                    shift_x = int(torch.randint(0, latent.shape[-1], (1,)).item())
                    train_latent = torch.roll(latent, shifts=(shift_y, shift_x), dims=(-2, -1))
                t_sample = torch.rand(1, device=DEVICE).to(DTYPE)
                timestep = t_sample.expand(1)

                noise = torch.randn_like(train_latent)
                x_t = (1.0 - t_sample) * noise + t_sample * train_latent
                target = train_latent - noise  # rectified flow velocity

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


def _run_local_training_serialized(runner, job_id: str, req: LoRATrainRequest) -> None:
    """Run at most one in-process trainer and always return CUDA memory.

    Training is a legacy/dev fallback; production uses a remote worker.  It
    must never load several complete diffusion pipelines into the public image
    process or leave their allocations behind after an exception.
    """
    with _local_training_semaphore:
        try:
            runner(job_id, req)
        finally:
            _clear_torch_cuda_caches()


def _run_chronos2_training(job_id: str, req: LoRATrainRequest) -> None:
    _run_local_training_serialized(_run_chronos2_training_impl, job_id, req)


def _run_zimage_training(job_id: str, req: LoRATrainRequest) -> None:
    _run_local_training_serialized(_run_zimage_training_impl, job_id, req)


@app.post("/train/upload_dataset")
async def upload_dataset(
    dataset_name: str = Form(...),
    files: list[UploadFile] = File(...),
    secret: str = "",
):
    """Upload images (and optional caption .txt files) for a LoRA training dataset."""
    _check_secret(secret)
    _require_local_gpu_training_enabled()
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
    train_size: Optional[int] = None
    dataset_mode: str = "standard"
    min_tileability: float = 0.72


@app.post("/train/from_urls")
def start_training_from_urls(req: LoRATrainFromURLsRequest, secret: str = ""):
    """Download images from URLs into a local dataset, then start training."""
    _check_secret(secret)
    if req.model not in ("zimage", "chronos2"):
        raise HTTPException(400, "model must be 'zimage' or 'chronos2'")
    if not req.image_urls:
        raise HTTPException(400, "image_urls must be non-empty")
    _validate_training_mode(req.model, req.dataset_mode, req.min_tileability)

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

    _require_local_gpu_training_enabled()
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
        train_size=req.train_size,
        dataset_mode=req.dataset_mode,
        min_tileability=req.min_tileability,
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
        "dataset_mode": req.dataset_mode,
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
def list_datasets(secret: str = ""):
    """List uploaded LoRA training datasets."""
    _check_secret(secret)
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
def start_training(req: LoRATrainRequest, secret: str = ""):
    """Start an async LoRA training job."""
    _check_secret(secret)
    if req.model not in ("zimage", "chronos2"):
        raise HTTPException(400, "model must be 'zimage' or 'chronos2'")
    _validate_training_mode(req.model, req.dataset_mode, req.min_tileability)
    _require_local_gpu_training_enabled()

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
def get_training_status(job_id: str, secret: str = ""):
    """Check training job status."""
    _check_secret(secret)
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
def list_training_jobs(secret: str = ""):
    """List all training jobs."""
    _check_secret(secret)
    return {"jobs": list(training_jobs.values())}


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def _local_port_has_listener(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.5)
            return probe.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False


def _wait_for_existing_local_server(port: int) -> bool:
    """Keep a managed standby quiet while an older instance owns the port.

    ``Restart=always`` service units otherwise spin forever on EADDRINUSE.
    Waiting keeps the unit healthy without importing a second model; when the
    old listener leaves, this same process continues into uvicorn and takes
    over normally.
    """
    if os.getenv("INFERENCE_WAIT_FOR_EXISTING_SERVER", "1") != "1":
        return False
    if not _local_port_has_listener(port):
        return False

    poll_seconds = max(
        0.25,
        float(os.getenv("INFERENCE_EXISTING_SERVER_POLL_SECONDS", "5")),
    )
    logger.warning(
        "port %s already has a local inference server; waiting in standby without loading models",
        port,
    )
    while _local_port_has_listener(port):
        time.sleep(poll_seconds)
    logger.info("port %s is free; standby is taking over", port)
    return True

if __name__ == "__main__":
    port = int(os.getenv("INFERENCE_PORT", "8100"))
    workers = int(os.getenv("INFERENCE_WORKERS", "1"))
    _wait_for_existing_local_server(port)
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=port,
        workers=workers,
        timeout_keep_alive=600,
    )
