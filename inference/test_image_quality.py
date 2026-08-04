from pathlib import Path
from io import BytesIO

import pytest
import requests
from PIL import Image

from image_quality import (
    PERSON_SUFFIX,
    SCENE_SUFFIX,
    compact_prompt,
    detect_too_bumpy,
    enhance_prompt,
    is_person_prompt,
    retry_prompt,
)


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


def test_is_person_prompt():
    assert is_person_prompt("a beautiful elf warrior in a forest")
    assert is_person_prompt("Portrait of an old man")
    assert not is_person_prompt("misty mountain lake at sunrise")


def test_enhance_prompt_person():
    enhanced = enhance_prompt("a woman reading in a cafe")
    assert enhanced.startswith("a woman reading in a cafe")
    assert "award-winning portrait" in enhanced


def test_enhance_prompt_scene():
    enhanced = enhance_prompt("misty mountain lake at sunrise")
    assert "award-winning landscape photography" in enhanced
    assert PERSON_SUFFIX.split(",")[0] not in enhanced


def test_enhance_prompt_skips_engineered_prompts():
    prompt = "cyberpunk city, masterpiece, 8k"
    assert enhance_prompt(prompt) == prompt
    long_prompt = "castle " * 100
    assert enhance_prompt(long_prompt, max_chars=120) == compact_prompt(long_prompt)


def test_enhance_prompt_deduplicates_existing_terms():
    prompt = "a radiant man in a garden"
    enhanced = enhance_prompt(prompt)
    assert enhanced.count("radiant") == 1
    assert "stunningly beautiful" in enhanced


def test_enhance_suffixes_stay_compact():
    assert len(PERSON_SUFFIX) < 140
    assert len(SCENE_SUFFIX) < 140


def test_enhance_prompt_skips_compositional_prompts():
    for prompt in (
        "a pelican riding a bicycle",
        "two beautiful girls hugging",
        "3 cats on a sofa",
        "a red cube stacked between two spheres",
    ):
        assert enhance_prompt(prompt) == prompt, prompt


def test_enhance_prompt_still_applies_to_simple_prompts():
    assert "award-winning" in enhance_prompt("a woman in a cafe")
    assert "award-winning" in enhance_prompt("misty mountain lake")
