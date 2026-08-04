"""Lightweight aesthetic scorer: CLIP ViT-L/14 embeddings + LAION MLP head.

Uses the LAION improved-aesthetic-predictor head (768 -> 1) over CLIP image
embeddings. Scores are roughly 1-10 (higher = more aesthetic). Runs on CPU by
default so it never competes with the diffusion model for VRAM; total weights
are ~0.6GB fp32 (vision tower) + ~4MB (head).

Env:
  AESTHETIC_ENABLED=1        master switch
  AESTHETIC_DEVICE=cpu       cpu|cuda
  AESTHETIC_CLIP_MODEL=openai/clip-vit-large-patch14
  AESTHETIC_HEAD_REPO=trl-lib/ddpo-aesthetic-predictor
  AESTHETIC_HEAD_FILE=aesthetic-model.pth
"""

from __future__ import annotations

import logging
import os
import threading

import torch
from PIL import Image

logger = logging.getLogger("aesthetic")

AESTHETIC_ENABLED = os.getenv("AESTHETIC_ENABLED", "1") == "1"
AESTHETIC_DEVICE = os.getenv("AESTHETIC_DEVICE", "cpu")
AESTHETIC_CLIP_MODEL = os.getenv("AESTHETIC_CLIP_MODEL", "openai/clip-vit-large-patch14")
AESTHETIC_HEAD_REPO = os.getenv("AESTHETIC_HEAD_REPO", "trl-lib/ddpo-aesthetic-predictor")
AESTHETIC_HEAD_FILE = os.getenv("AESTHETIC_HEAD_FILE", "aesthetic-model.pth")


class AestheticHead(torch.nn.Module):
    """LAION improved-aesthetic-predictor MLP (sac+logos+ava1-l14-linearMSE)."""

    def __init__(self, input_dim: int = 768):
        super().__init__()
        self.layers = torch.nn.Sequential(
            torch.nn.Linear(input_dim, 1024),
            torch.nn.Dropout(0.2),
            torch.nn.Linear(1024, 128),
            torch.nn.Dropout(0.2),
            torch.nn.Linear(128, 64),
            torch.nn.Dropout(0.1),
            torch.nn.Linear(64, 16),
            torch.nn.Linear(16, 1),
        )

    def forward(self, embed: torch.Tensor) -> torch.Tensor:
        return self.layers(embed)


def _remap_head_state_dict(state: dict) -> dict:
    """Accept both trl (layers.N.*) and LAION (layers.N.* with same indices) keys."""
    out = {}
    for k, v in state.items():
        out[k if k.startswith("layers.") else f"layers.{k}"] = v
    return out


class AestheticScorer:
    def __init__(self, device: str = AESTHETIC_DEVICE):
        from huggingface_hub import hf_hub_download
        from transformers import CLIPImageProcessor, CLIPVisionModelWithProjection

        self.device = device
        dtype = torch.float16 if device.startswith("cuda") else torch.float32
        self.dtype = dtype
        self.processor = CLIPImageProcessor.from_pretrained(AESTHETIC_CLIP_MODEL)
        self.clip = CLIPVisionModelWithProjection.from_pretrained(
            AESTHETIC_CLIP_MODEL, dtype=dtype
        ).to(device).eval()
        head_path = hf_hub_download(AESTHETIC_HEAD_REPO, AESTHETIC_HEAD_FILE)
        state = torch.load(head_path, map_location="cpu", weights_only=True)
        self.head = AestheticHead()
        self.head.load_state_dict(_remap_head_state_dict(state))
        self.head.to(device=device, dtype=dtype).eval()
        self._text = None
        self._tokenizer = None

    def _ensure_text_tower(self):
        if self._text is None:
            from transformers import CLIPTextModelWithProjection, CLIPTokenizer

            self._tokenizer = CLIPTokenizer.from_pretrained(AESTHETIC_CLIP_MODEL)
            self._text = CLIPTextModelWithProjection.from_pretrained(
                AESTHETIC_CLIP_MODEL, dtype=self.dtype
            ).to(self.device).eval()

    @torch.inference_mode()
    def embed_texts(self, texts: list[str]) -> torch.Tensor:
        """Normalized CLIP text embeddings [N,768] on CPU (77-token truncation)."""
        self._ensure_text_tower()
        tokens = self._tokenizer(texts, padding=True, truncation=True, return_tensors="pt")
        tokens = {k: v.to(self.device) for k, v in tokens.items()}
        embeds = self._text(**tokens).text_embeds
        embeds = embeds / embeds.norm(dim=-1, keepdim=True)
        return embeds.float().cpu()

    @torch.inference_mode()
    def embed_and_score(self, images: list[Image.Image]) -> tuple[torch.Tensor, list[float]]:
        """Return (normalized CLIP image embeddings [N,768] on CPU, scores)."""
        if not images:
            return torch.empty(0, 768), []
        inputs = self.processor(images=images, return_tensors="pt")
        pixel_values = inputs["pixel_values"].to(device=self.device, dtype=self.dtype)
        embeds = self.clip(pixel_values=pixel_values).image_embeds
        embeds = embeds / embeds.norm(dim=-1, keepdim=True)
        scores = self.head(embeds).squeeze(-1).float()
        return embeds.float().cpu(), [float(s) for s in scores.cpu()]

    def score(self, images: list[Image.Image]) -> list[float]:
        return self.embed_and_score(images)[1]


_scorer: AestheticScorer | None = None
_scorer_lock = threading.Lock()
_scorer_failed = False


def get_scorer() -> AestheticScorer | None:
    """Lazy singleton; returns None when disabled or load failed."""
    global _scorer, _scorer_failed
    if not AESTHETIC_ENABLED or _scorer_failed:
        return None
    if _scorer is not None:
        return _scorer
    with _scorer_lock:
        if _scorer is None and not _scorer_failed:
            try:
                _scorer = AestheticScorer()
                logger.info("aesthetic scorer loaded (%s on %s)", AESTHETIC_CLIP_MODEL, AESTHETIC_DEVICE)
            except Exception as e:
                _scorer_failed = True
                logger.warning("aesthetic scorer unavailable: %s", e)
    return _scorer


def unload_scorer() -> None:
    global _scorer, _scorer_failed
    with _scorer_lock:
        _scorer = None
        _scorer_failed = False


def score_images(images: list[Image.Image]) -> list[float] | None:
    scorer = get_scorer()
    if scorer is None:
        return None
    try:
        return scorer.score(images)
    except Exception as e:
        logger.warning("aesthetic scoring failed: %s", e)
        return None
