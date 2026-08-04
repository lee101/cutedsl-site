import numpy as np
from PIL import Image

from inference.texture_quality import measure_tileability, spectral_embedding, toroidal_roll


def periodic_texture(size: int = 128) -> Image.Image:
    y, x = np.mgrid[:size, :size]
    value = 0.5 + 0.22 * np.sin(2 * np.pi * x / 16) + 0.18 * np.cos(2 * np.pi * y / 32)
    rgb = np.stack((value, np.roll(value, 3, 0), np.roll(value, 5, 1)), axis=-1)
    return Image.fromarray(np.uint8(np.clip(rgb, 0, 1) * 255), "RGB")


def test_periodic_texture_passes_and_broken_edge_fails():
    good = periodic_texture()
    good_score = measure_tileability(good)
    broken = np.asarray(good).copy()
    broken[:, -4:, :] = 255
    bad_score = measure_tileability(Image.fromarray(broken))
    assert good_score.verified
    assert good_score.score > bad_score.score
    assert not bad_score.verified


def test_spectral_embedding_is_toroidal_shift_invariant():
    image = periodic_texture()
    shifted = toroidal_roll(image, 19, 37)
    a = np.asarray(spectral_embedding(image))
    b = np.asarray(spectral_embedding(shifted))
    assert float(np.dot(a, b)) > 0.999
