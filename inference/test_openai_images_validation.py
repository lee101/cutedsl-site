"""Boundary validation for the OpenAI-compatible image endpoint.

Production telemetry recorded 500s on POST /v1/images/generations for bodies
whose numeric fields were strings (``"abc"``, prompt-injection payloads such as
``IGNORE_ALL_PREVIOUS_INSTRUCTIONS_167052``). ``int()``/``float()`` raised
ValueError inside the endpoint, so invalid client input surfaced as a server
error. These tests pin the 400 contract without touching the GPU.
"""

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402


@pytest.fixture(autouse=True)
def submitted_requests(monkeypatch):
    """Keep the endpoint off the GPU and capture accepted request models."""
    monkeypatch.setattr(server, "LOAD_ZIMAGE", True)
    monkeypatch.setattr(server, "IMAGE_API_SECRETS", set())
    submitted = []

    async def _fake_submit(req):
        submitted.append(req)
        return {"image_base64": "Zm9v", "seed": req.seed}

    monkeypatch.setattr(server, "_submit_zimage_request", _fake_submit)
    return submitted


def _post(content: bytes) -> httpx.Response:
    async def run():
        transport = httpx.ASGITransport(app=server.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            return await client.post(
                "/v1/images/generations",
                content=content,
                headers={"content-type": "application/json"},
            )

    return asyncio.run(run())


@pytest.mark.parametrize(
    "payload, field",
    [
        ({"prompt": "x", "width": "abc"}, "width"),
        ({"prompt": "x", "height": "abc"}, "height"),
        ({"prompt": "x", "steps": "IGNORE_ALL_PREVIOUS_INSTRUCTIONS_167052"}, "steps"),
        ({"prompt": "x", "num_inference_steps": "abc"}, "num_inference_steps"),
        ({"prompt": "x", "n": "abc"}, "n"),
        ({"prompt": "x", "seed": "abc"}, "seed"),
        ({"prompt": "x", "best_of": "abc"}, "best_of"),
        ({"prompt": "x", "guidance_scale": "abc"}, "guidance_scale"),
        ({"prompt": "x", "lora_scale": "abc"}, "lora_scale"),
        ({"prompt": "x", "early_exit": "abc"}, "early_exit"),
        ({"prompt": "x", "early_exit_min_steps": "abc"}, "early_exit_min_steps"),
    ],
)
def test_non_numeric_generation_params_are_client_errors(payload, field):
    response = _post(json.dumps(payload).encode())
    assert response.status_code == 400, response.text
    assert field in response.json()["detail"]


@pytest.mark.parametrize(
    "payload",
    [
        {"prompt": "x", "width": 10},
        {"prompt": "x", "height": 8192},
        {"prompt": "x", "steps": 0},
        {"prompt": "x", "steps": 1000},
        {"prompt": "x", "seed": 2**64},
        {"prompt": "x", "guidance_scale": float("nan")},
    ],
)
def test_out_of_contract_generation_params_are_client_errors(payload):
    response = _post(json.dumps(payload).encode())
    assert response.status_code == 400, response.text


def test_malformed_json_body_is_client_error():
    response = _post(b"{not json")
    assert response.status_code == 400
    assert "JSON" in response.json()["detail"]


def test_non_object_json_body_is_client_error():
    response = _post(b"[1, 2, 3]")
    assert response.status_code == 400
    assert "object" in response.json()["detail"]


def test_numeric_strings_still_parse_to_ints(submitted_requests):
    response = _post(
        json.dumps(
            {
                "prompt": "a lighthouse at dusk",
                "width": "512",
                "height": "512",
                "steps": "3",
                "seed": "7",
            }
        ).encode()
    )
    assert response.status_code == 200, response.text
    assert len(submitted_requests) == 1
    request_model = submitted_requests[0]
    assert (
        request_model.width,
        request_model.height,
        request_model.num_inference_steps,
        request_model.seed,
    ) == (512, 512, 3, 7)
