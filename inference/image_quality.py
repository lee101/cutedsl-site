"""Image quality checks and prompt cleanup for generated images."""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageFilter


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "in",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "to",
    "was",
    "were",
    "with",
}


@dataclass(frozen=True)
class BumpyMetrics:
    histogram_bottom: int
    histogram_top: int
    histogram_deviations: int
    laplacian_abs_mean: float
    laplacian_p95: float
    laplacian_ratio: float
    entropy: float


def _rgb_image(image: Image.Image) -> Image.Image:
    if image.mode != "RGB":
        return image.convert("RGB")
    return image


def _laplacian_metrics(image: Image.Image) -> tuple[float, float, float]:
    gray = np.asarray(image.convert("L").resize((512, 512)), dtype=np.float32)
    lap = np.abs(
        -4 * gray[1:-1, 1:-1]
        + gray[:-2, 1:-1]
        + gray[2:, 1:-1]
        + gray[1:-1, :-2]
        + gray[1:-1, 2:]
    )
    abs_mean = float(lap.mean())
    p95 = float(np.percentile(lap, 95))
    return abs_mean, p95, abs_mean / max(p95, 1.0)


def bumpy_metrics(image: Image.Image) -> BumpyMetrics:
    """Return deterministic metrics used by detect_too_bumpy."""
    rgb = _rgb_image(image)

    hist = rgb.histogram()
    r = hist[0:256]
    g = hist[256:512]
    b = hist[512:768]
    bottom = sum(r[:10]) + sum(g[:10]) + sum(b[:10])
    top = sum(r[-10:]) + sum(g[-10:]) + sum(b[-10:])

    gray_hist = rgb.convert("L").histogram()
    deviations = 0
    for i in range(1, 256):
        if abs(gray_hist[i] - gray_hist[i - 1]) > 50:
            deviations += 1

    lap_mean, lap_p95, lap_ratio = _laplacian_metrics(rgb)
    entropy = float(rgb.convert("L").entropy())

    return BumpyMetrics(
        histogram_bottom=bottom,
        histogram_top=top,
        histogram_deviations=deviations,
        laplacian_abs_mean=lap_mean,
        laplacian_p95=lap_p95,
        laplacian_ratio=lap_ratio,
        entropy=entropy,
    )


def detect_too_bumpy(image: Image.Image) -> bool:
    """Detect corrupted speckled/pointillist generations.

    The first predicate preserves the historical histogram detector from
    stable_diffusion_server. The second catches newer color-bumpy outputs
    where high-frequency noise is spread across most of the image instead of
    concentrated at real edges.
    """
    metrics = bumpy_metrics(image)
    old_histogram_detector = (
        metrics.histogram_bottom > 30000
        and metrics.histogram_top > 30000
        and metrics.histogram_deviations > 180
    )
    distributed_speckle_detector = (
        metrics.entropy >= 7.45
        and metrics.laplacian_ratio >= 0.30
        and metrics.laplacian_abs_mean >= 15.0
    )
    heavy_speckle_detector = (
        metrics.laplacian_abs_mean >= 42.0
        and metrics.laplacian_ratio >= 0.31
    )
    return old_histogram_detector or distributed_speckle_detector or heavy_speckle_detector


def compact_prompt(prompt: str, max_chars: int = 500) -> str:
    """Trim very long prompts while preserving meaningful tokens."""
    cleaned = " ".join(prompt.split())
    if len(cleaned) <= max_chars:
        return cleaned

    tokens = re.findall(r"[\w'-]+|[,.]", cleaned)
    meaningful = [
        token
        for token in tokens
        if token in {",", "."} or token.lower() not in STOPWORDS
    ]
    shortened = " ".join(meaningful)
    shortened = shortened.replace(" ,", ",").replace(" .", ".")
    if len(shortened) <= max_chars:
        return shortened
    return shortened[:max_chars].rsplit(" ", 1)[0].strip(" ,.")


def retry_prompt(prompt: str, max_chars: int = 360) -> str:
    """Build a shorter retry prompt for failed or bumpy generations."""
    suffix = "clean smooth detailed coherent image"
    compacted = compact_prompt(prompt, max_chars=max_chars - len(suffix) - 2)
    words = compacted.split()
    if len(words) > 24:
        compacted = " ".join(words[: max(12, len(words) // 2)])
    if suffix in compacted.lower():
        return compacted
    return f"{compacted}, {suffix}".strip(" ,")
