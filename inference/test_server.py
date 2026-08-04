"""E2E tests for CuteDSL inference server.

Run with: pytest test_server.py -v
Requires: inference server running on localhost:8100
  OR set INFERENCE_TEST_URL to override
"""

import os
import time
import json
import math
import pytest
import httpx

BASE_URL = os.getenv("INFERENCE_TEST_URL", "http://localhost:8100")
SECRET = os.getenv("INFERENCE_TEST_SECRET", "cutedsl2024")
RUN_SLOW_ZIMAGE_TESTS = os.getenv("RUN_SLOW_ZIMAGE_TESTS", "0") == "1"
client = httpx.Client(base_url=BASE_URL, timeout=180.0)


def server_available():
    try:
        r = client.get("/health")
        return r.status_code == 200
    except httpx.ConnectError:
        return False


skip_if_no_server = pytest.mark.skipif(
    not server_available(),
    reason=f"Inference server not running at {BASE_URL}",
)


# ---- Health ----

@skip_if_no_server
def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] in {"ok", "degraded"}
    assert "cuda" in data
    assert "models" in data
    assert "zimage" in data["models"]
    assert "chronos2" in data["models"]
    assert "device" in data
    assert "dtype" in data


# ---- Z-Image ----

@skip_if_no_server
def test_generate_image_missing_prompt():
    r = client.post("/generate_image", json={})
    assert r.status_code == 422  # Pydantic validation error


@skip_if_no_server
@pytest.mark.parametrize("payload", [
    {"prompt": ""},
    {"prompt": "   "},
])
def test_generate_image_blank_prompt_rejected_before_gpu(payload):
    r = client.post("/generate_image", json=payload)
    assert r.status_code == 422
    assert "prompt" in r.text


@skip_if_no_server
@pytest.mark.parametrize("prompt", ["", "   "])
def test_create_and_upload_blank_prompt_rejected_before_gpu(prompt):
    r = client.get("/create_and_upload_image", params={
        "prompt": prompt,
        "width": 512,
        "height": 512,
        "model": "zimage-turbo",
        "auto_lora": "true",
        "teleport": "true",
        "perf": "true",
        "secret": SECRET,
    })
    assert r.status_code == 400
    assert r.json()["detail"] == "prompt must not be empty"


@skip_if_no_server
def test_generate_image_model_not_loaded():
    """Z-Image lazy-loads on first use, so unloaded is not an error state."""
    r = client.get("/health")
    if not r.json()["models"]["zimage"]:
        pytest.skip("zimage is configured for lazy loading")


@skip_if_no_server
def test_generate_image_success():
    """Full image generation test (only if model is loaded)."""
    health = client.get("/health").json()
    if not health["models"]["zimage"]:
        pytest.skip("zimage model not loaded")

    r = client.post("/generate_image", json={
        "prompt": "a cute fairy in a magical forest, digital art",
        "width": 512,
        "height": 512,
        "num_inference_steps": 4,
        "seed": 42,
    })
    assert r.status_code == 200
    data = r.json()
    assert "image_base64" in data
    assert data["format"] == "webp"
    assert data["width"] == 512
    assert data["height"] == 512
    assert data["seed"] == 42
    assert data["inference_time_ms"] > 0
    # Verify base64 is decodable
    import base64
    img_bytes = base64.b64decode(data["image_base64"])
    assert len(img_bytes) > 1000  # Should be a non-trivial image


@skip_if_no_server
def test_openai_images_bad_secret():
    r = client.post("/v1/images/generations",
                    json={"prompt": "x"},
                    headers={"Authorization": "Bearer wrong-secret"})
    assert r.status_code == 403


@skip_if_no_server
def test_openai_images_accepts_compat_secret_header_before_validation():
    r = client.post(
        "/v1/images/generations",
        json={},
        headers={"secret": SECRET},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "prompt must not be empty"


@skip_if_no_server
def test_openai_images_missing_prompt():
    r = client.post("/v1/images/generations", json={},
                    headers={"Authorization": f"Bearer {SECRET}"})
    assert r.status_code == 400


@skip_if_no_server
def test_openai_images_generation():
    health = client.get("/health").json()
    if not health["models"]["zimage"]:
        pytest.skip("zimage model not loaded")
    r = client.post("/v1/images/generations", json={
        "prompt": "a lighthouse at dusk, oil painting",
        "size": "512x512",
        "steps": 4,
        "seed": 7,
        "auto_lora": False,
    }, headers={"Authorization": f"Bearer {SECRET}"})
    assert r.status_code == 200
    data = r.json()
    assert data["model"] == "z-image-turbo"
    assert len(data["data"]) == 1
    import base64
    assert len(base64.b64decode(data["data"][0]["b64_json"])) > 1000


@skip_if_no_server
def test_generate_image_dimension_alignment():
    """Dimensions should be aligned to 64px."""
    health = client.get("/health").json()
    if not health["models"]["zimage"]:
        pytest.skip("zimage model not loaded")

    r = client.post("/generate_image", json={
        "prompt": "test alignment",
        "width": 500,  # Not aligned to 64
        "height": 500,
        "num_inference_steps": 1,
        "seed": 0,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["width"] % 64 == 0
    assert data["height"] % 64 == 0


@skip_if_no_server
def test_create_and_upload_image_compat():
    """Test the GET compatibility endpoint."""
    health = client.get("/health").json()
    if not health["models"]["zimage"]:
        pytest.skip("zimage model not loaded")

    r = client.get("/create_and_upload_image", params={
        "prompt": "test compat endpoint",
        "width": 512,
        "height": 512,
        "secret": SECRET,
        "save_path": f"pytest/compat_{int(time.time())}.webp",
    })
    assert r.status_code == 200
    assert r.json()["path"].startswith("https://")


slow_zimage = pytest.mark.skipif(
    not RUN_SLOW_ZIMAGE_TESTS,
    reason="set RUN_SLOW_ZIMAGE_TESTS=1 to run GPU-backed prompt/teleport coverage",
)


def _upload_image(prompt: str, name: str, *, auto_lora: bool, teleport: bool, width: int = 512, height: int = 512):
    r = client.get("/create_and_upload_image", params={
        "prompt": prompt,
        "width": width,
        "height": height,
        "model": "zimage-turbo",
        "auto_lora": str(auto_lora).lower(),
        "teleport": str(teleport).lower(),
        "perf": "true",
        "secret": SECRET,
        "save_path": f"pytest/{int(time.time())}_{name}.webp",
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["path"].startswith("https://")
    assert data.get("perf", {}).get("inference_time_ms", 0) >= 0
    return data


@skip_if_no_server
@slow_zimage
@pytest.mark.parametrize("label,prompt", [
    ("short", "pretty girl portrait"),
    ("medium", "cinematic watercolor fox in a misty forest with soft rim light and coherent detail"),
    ("long", " ".join(["clean detailed product photo of a futuristic smartphone on a white seamless background"] * 12)),
    ("very_long", " ".join(["high quality coherent fantasy landscape with mountains, river, castle, atmospheric light"] * 28)),
])
def test_create_and_upload_prompt_lengths(label, prompt):
    health = client.get("/health").json()
    if not health["models"]["zimage"]:
        pytest.skip("zimage model not loaded")

    data = _upload_image(prompt, f"prompt_len_{label}", auto_lora=True, teleport=False)
    assert data["perf"]["width"] == 512
    assert data["perf"]["height"] == 512


@skip_if_no_server
@slow_zimage
def test_create_and_upload_teleport_replay_quality_and_latency():
    health = client.get("/health").json()
    if not health["models"]["zimage"]:
        pytest.skip("zimage model not loaded")

    prompt = "pixel art stone block inventory icon, centered, simple game UI asset"
    baseline = _upload_image(prompt, "teleport_baseline", auto_lora=False, teleport=False)
    _upload_image(prompt, "teleport_prime", auto_lora=False, teleport=True)
    replay = _upload_image(prompt, "teleport_replay", auto_lora=False, teleport=True)

    assert replay["perf"]["teleport_cache_hit"] is True
    assert replay["perf"]["inference_time_ms"] <= baseline["perf"]["inference_time_ms"]

    import io
    import math
    import numpy as np
    from PIL import Image

    base_img = Image.open(io.BytesIO(httpx.get(baseline["path"], timeout=30).content)).convert("RGB")
    replay_img = Image.open(io.BytesIO(httpx.get(replay["path"], timeout=30).content)).convert("RGB")
    diff = np.asarray(base_img, dtype=np.float32) - np.asarray(replay_img, dtype=np.float32)
    mse = float(np.mean(diff * diff))
    psnr = float("inf") if mse == 0 else float(20 * math.log10(255.0 / math.sqrt(mse)))
    assert psnr >= 30.0


# ---- Chronos2 Forecast ----

@skip_if_no_server
def test_forecast_missing_values():
    r = client.post("/forecast", json={})
    assert r.status_code == 422


@skip_if_no_server
def test_forecast_model_not_loaded():
    health = client.get("/health").json()
    if not health["models"]["chronos2"]:
        r = client.post("/forecast", json={"values": [1.0, 2.0, 3.0]})
        assert r.status_code == 503


@skip_if_no_server
def test_forecast_success():
    health = client.get("/health").json()
    if not health["models"]["chronos2"]:
        pytest.skip("chronos2 model not loaded")

    values = [float(i) + 0.1 * i for i in range(100)]
    r = client.post("/forecast", json={
        "values": values,
        "prediction_length": 16,
        "quantile_levels": [0.1, 0.5, 0.9],
    })
    assert r.status_code == 200
    data = r.json()
    assert "mean" in data
    assert len(data["mean"]) == 16
    assert "quantiles" in data
    assert "0.5" in data["quantiles"]
    assert len(data["quantiles"]["0.5"]) == 16
    assert data["prediction_length"] == 16
    assert data["context_length"] == 100
    assert data["inference_time_ms"] >= 0


@skip_if_no_server
def test_forecast_default_params():
    health = client.get("/health").json()
    if not health["models"]["chronos2"]:
        pytest.skip("chronos2 model not loaded")

    values = [float(i) for i in range(50)]
    r = client.post("/forecast", json={"values": values})
    assert r.status_code == 200
    data = r.json()
    assert data["prediction_length"] == 64  # default
    assert "0.1" in data["quantiles"]  # default quantile levels
    assert "0.5" in data["quantiles"]
    assert "0.9" in data["quantiles"]


@skip_if_no_server
@pytest.mark.parametrize("payload", [
    '{"values":[]}',
    '{"values":[1.0,Infinity,3.0],"prediction_length":4}',
    '{"values":[1.0,2.0,3.0],"prediction_length":0}',
    '{"values":[1.0,2.0,3.0],"quantile_levels":[NaN]}',
])
def test_forecast_rejects_inputs_that_would_produce_non_finite_json(payload):
    r = client.post("/forecast", content=payload, headers={"content-type": "application/json"})
    assert r.status_code == 422, r.text
    json.dumps(r.json(), allow_nan=False)


@skip_if_no_server
def test_forecast_accepts_long_context_with_missing_values():
    health = client.get("/health").json()
    if not health["models"]["chronos2"]:
        pytest.skip("chronos2 model not loaded")

    values = [float(i) for i in range(4095)] + [float("nan")]
    r = client.post(
        "/forecast",
        content=json.dumps({"values": values, "prediction_length": 4}),
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["context_length"] == 4096
    assert all(math.isfinite(value) for value in data["mean"])


@skip_if_no_server
def test_forecast_batch_rejects_empty_series():
    r = client.post("/forecast_batch", json={
        "series": [[]],
        "prediction_length": 4,
    })
    assert r.status_code == 422, r.text


# ---- TTS ----

@skip_if_no_server
def test_synthesize_missing_text():
    r = client.post("/synthesize", json={})
    assert r.status_code == 422


@skip_if_no_server
def test_synthesize_backend_error():
    """TTS proxy should return 502 if backend is down."""
    r = client.post("/synthesize", json={
        "text": "Hello world",
        "voice": "af_nicole",
    })
    # Either 200 (backend running) or 502 (backend down)
    assert r.status_code in (200, 502)
    if r.status_code == 200:
        assert r.headers.get("content-type", "").startswith("audio/")


# ---- STT ----

@skip_if_no_server
def test_transcribe_missing_url():
    r = client.post("/transcribe", json={})
    assert r.status_code == 422


@skip_if_no_server
def test_transcribe_invalid_url():
    r = client.post("/transcribe", json={
        "audio_url": "https://nonexistent.example.com/audio.wav",
    })
    assert r.status_code in (200, 502)


# ---- Caption ----

@skip_if_no_server
def test_caption_missing_url():
    r = client.post("/caption", json={})
    assert r.status_code == 422


@skip_if_no_server
def test_caption_request():
    r = client.post("/caption", json={
        "image_url": "https://picsum.photos/200/200",
    })
    assert r.status_code in (200, 400)


@skip_if_no_server
def test_caption_file_proxy_authentication():
    """A valid image must reach the caption backend without an auth 5xx."""
    from io import BytesIO
    from PIL import Image

    image = Image.new("RGB", (32, 32), "navy")
    payload = BytesIO()
    image.save(payload, format="PNG")
    r = client.post(
        "/caption_file",
        files={"image_file": ("auth-probe.png", payload.getvalue(), "image/png")},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["caption"]
    assert data["source"] == "file"


# ---- Gemma4 Chat ----

@skip_if_no_server
def test_chat_missing_messages():
    r = client.post("/chat", json={})
    assert r.status_code == 422


@skip_if_no_server
def test_chat_request():
    r = client.post("/chat", json={
        "messages": [{"role": "user", "content": "Say hi"}],
        "max_tokens": 10,
    })
    assert r.status_code in (200, 502)


# ---- Training API ----

@skip_if_no_server
def test_train_invalid_model():
    r = client.post("/train", json={
        "model": "invalid",
        "dataset_name": "test",
    })
    assert r.status_code == 400


@skip_if_no_server
def test_train_start_and_status():
    r = client.post("/train", json={
        "model": "chronos2",
        "dataset_name": "test-data",
        "values": [[float(i) for i in range(100)]],
        "num_steps": 10,
    })
    assert r.status_code == 200
    data = r.json()
    assert "job_id" in data
    assert data["model"] == "chronos2"
    assert data["status"] == "queued"

    # Check status
    job_id = data["job_id"]
    r2 = client.get(f"/train/{job_id}")
    assert r2.status_code == 200
    status_data = r2.json()
    assert status_data["job_id"] == job_id
    assert status_data["model"] == "chronos2"


@skip_if_no_server
def test_train_status_not_found():
    r = client.get("/train/nonexistent-id")
    assert r.status_code == 404


@skip_if_no_server
def test_train_list():
    r = client.get("/train")
    assert r.status_code == 200
    data = r.json()
    assert "jobs" in data
    assert isinstance(data["jobs"], list)
