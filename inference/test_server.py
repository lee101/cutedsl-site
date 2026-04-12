"""E2E tests for CuteDSL inference server.

Run with: pytest test_server.py -v
Requires: inference server running on localhost:8100
  OR set INFERENCE_TEST_URL to override
"""

import os
import pytest
import httpx

BASE_URL = os.getenv("INFERENCE_TEST_URL", "http://localhost:8100")
client = httpx.Client(base_url=BASE_URL, timeout=60.0)


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
    assert data["status"] == "ok"
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
def test_generate_image_model_not_loaded():
    """If zimage isn't loaded, should get 503."""
    r = client.get("/health")
    if not r.json()["models"]["zimage"]:
        r2 = client.post("/generate_image", json={"prompt": "test"})
        assert r2.status_code == 503


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
        "seed": 1,
    })
    assert r.status_code == 200
    assert "image_base64" in r.json()


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
    assert r.status_code in (200, 502)


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
