"""Deterministic quality checks and augmentation for periodic texture datasets.

The seam metric compares the wrap-around step with ordinary neighbouring
steps, rather than requiring the first and last pixels to be identical.  That
is the correct discrete condition for a sampled periodic signal.  The spectral
descriptor uses Fourier magnitudes, so cyclic translations of the same tile
map to (approximately) the same embedding.
"""

from __future__ import annotations

import io
import math
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class TileabilityMetrics:
    seam_x: float
    seam_y: float
    gradient_x: float
    gradient_y: float
    score: float
    verified: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _axis_metrics(rgb: np.ndarray, axis: int) -> tuple[float, float]:
    """Return normalized wrap colour and gradient scores for one axis."""
    delta = np.abs(np.diff(rgb, axis=axis))
    ordinary = float(np.mean(delta)) + 1e-6
    if axis == 1:
        wrap = np.abs(rgb[:, 0, :] - rgb[:, -1, :])
        first = rgb[:, 1, :] - rgb[:, 0, :]
        last = rgb[:, -1, :] - rgb[:, -2, :]
    else:
        wrap = np.abs(rgb[0, :, :] - rgb[-1, :, :])
        first = rgb[1, :, :] - rgb[0, :, :]
        last = rgb[-1, :, :] - rgb[-2, :, :]

    # A periodic boundary should look like an ordinary local step.  Ratios up
    # to 1.5 are normal for textured signals; large outliers are visible seams.
    ratio = float(np.mean(wrap)) / ordinary
    colour_score = math.exp(-max(0.0, ratio - 1.5))

    ordinary_grad = float(np.mean(np.abs(np.diff(delta, axis=axis)))) + 1e-6
    wrap_grad = float(np.mean(np.abs(first - last)))
    grad_ratio = wrap_grad / ordinary_grad
    gradient_score = math.exp(-max(0.0, grad_ratio - 2.0) * 0.5)
    return max(0.0, min(1.0, colour_score)), max(0.0, min(1.0, gradient_score))


def measure_tileability(image: Image.Image, threshold: float = 0.72) -> TileabilityMetrics:
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    if rgb.shape[0] < 8 or rgb.shape[1] < 8:
        raise ValueError("texture must be at least 8x8")
    seam_x, gradient_x = _axis_metrics(rgb, axis=1)
    seam_y, gradient_y = _axis_metrics(rgb, axis=0)
    # The weakest boundary dominates perception, so use a geometric mean with
    # a small minimum-axis penalty instead of an optimistic arithmetic mean.
    values = np.asarray([seam_x, seam_y, gradient_x, gradient_y], dtype=np.float64)
    score = float(np.prod(np.maximum(values, 1e-9)) ** 0.25)
    score *= 0.8 + 0.2 * float(np.min(values))
    score = max(0.0, min(1.0, score))
    return TileabilityMetrics(seam_x, seam_y, gradient_x, gradient_y, score, score >= threshold)


def measure_tileability_bytes(data: bytes, threshold: float = 0.72) -> TileabilityMetrics:
    with Image.open(io.BytesIO(data)) as image:
        return measure_tileability(image, threshold=threshold)


def toroidal_roll(image: Image.Image, x: int, y: int) -> Image.Image:
    """Cyclically translate a tile without introducing a new boundary."""
    arr = np.asarray(image)
    return Image.fromarray(np.roll(np.roll(arr, y, axis=0), x, axis=1))


def spectral_embedding(image: Image.Image, size: int = 32, bands: int = 5) -> list[float]:
    """Build a compact cyclic-shift-invariant visual descriptor.

    Translation changes Fourier phase but not magnitude.  We therefore retain
    low-frequency RGB magnitudes and normalize the vector for cosine search.
    """
    sample = np.asarray(image.convert("RGB").resize((size, size), Image.Resampling.LANCZOS), dtype=np.float32)
    sample = sample / 255.0
    features: list[float] = []
    for channel in range(3):
        spectrum = np.abs(np.fft.rfft2(sample[:, :, channel]))
        block = spectrum[:bands, :bands].copy()
        block[0, 0] = float(np.mean(sample[:, :, channel])) * size
        features.extend(block.reshape(-1).tolist())
    vector = np.asarray(features, dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    if norm > 0:
        vector /= norm
    return vector.astype(float).tolist()


def tiled_preview(image: Image.Image, repeats: int = 2) -> Image.Image:
    if repeats < 2 or repeats > 4:
        raise ValueError("repeats must be between 2 and 4")
    tile = image.convert("RGB")
    out = Image.new("RGB", (tile.width * repeats, tile.height * repeats))
    for y in range(repeats):
        for x in range(repeats):
            out.paste(tile, (x * tile.width, y * tile.height))
    return out
