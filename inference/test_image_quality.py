from pathlib import Path
from io import BytesIO

import pytest
import requests
from PIL import Image

from image_quality import compact_prompt, detect_too_bumpy, retry_prompt


REPO_ROOT = Path(__file__).resolve().parents[1]
STABLE_DIFFUSION_DATA = REPO_ROOT.parent / "stable_diffusion_server" / "tests" / "data"

BAD_EXAMPLES = [
    "https://cutedsl.app.nz/images/medium/852fdf600653ad09_5707fd8a.webp",
    "https://cutedsl.app.nz/images/medium/b9a24d7066bdbaa4_adf8297c.webp",
    "https://cutedsl.app.nz/images/medium/3ab0c7eba2c4062a_5ef2f747.webp",
]
GOOD_EXAMPLES = [
    "https://cutedsl.app.nz/images/medium/bf4b7f2bb9c8639f_1900d257.webp",
]


def test_detect_too_bumpy_legacy_fixtures():
    for path in (STABLE_DIFFUSION_DATA / "bugs").glob("*"):
        if path.is_file():
            assert detect_too_bumpy(Image.open(path)), path.name

    good_path = (
        STABLE_DIFFUSION_DATA
        / "Serqet-Selket-goddess-of-protection-Egyptian-Heritage-octane-render-cinematic-color-grading-soft-light-atmospheric-reali.png"
    )
    assert not detect_too_bumpy(Image.open(good_path))


@pytest.mark.parametrize("url", BAD_EXAMPLES)
def test_detect_too_bumpy_remote_bad_examples(url):
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    image = Image.open(BytesIO(response.content))
    assert detect_too_bumpy(image), url


@pytest.mark.parametrize("url", GOOD_EXAMPLES)
def test_detect_too_bumpy_remote_good_examples(url):
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    image = Image.open(BytesIO(response.content))
    assert not detect_too_bumpy(image), url


def test_prompt_compaction_and_retry_prompt():
    prompt = " ".join(["the", "highly", "detailed", "portrait"] * 100)
    compacted = compact_prompt(prompt, max_chars=120)
    retry = retry_prompt(prompt, max_chars=120)

    assert len(compacted) <= 120
    assert len(retry) <= 120
    assert "clean smooth detailed coherent image" in retry
