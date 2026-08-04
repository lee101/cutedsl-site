import os
import subprocess
from pathlib import Path

import pytest


HELPER = Path(__file__).with_name("caption_backend_auth.sh")


@pytest.mark.parametrize(
    ("status", "expected_returncode"),
    [("200", 0), ("400", 0), ("401", 1), ("403", 1), ("000", 1)],
)
def test_caption_auth_preflight_interprets_backend_status(tmp_path, status, expected_returncode):
    fake_curl = tmp_path / "curl"
    fake_curl.write_text(f"#!/bin/sh\ncat >/dev/null\nprintf '{status}'\n")
    fake_curl.chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "CAPTION_BACKEND_API_KEY": "scoped-test-key",
        "TG_BACKEND_URL": "http://caption.test",
    }
    result = subprocess.run(
        ["bash", "-c", f". {HELPER}; verify_caption_backend_auth"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == expected_returncode
    assert "scoped-test-key" not in result.stdout
    assert "scoped-test-key" not in result.stderr


def test_caption_auth_preflight_requires_a_scoped_credential():
    env = {
        **os.environ,
        "CAPTION_BACKEND_API_KEY": "",
        "NETWRCK_IMAGE_CAPTION_SECRET": "",
        "TG_API_KEY": "",
    }
    result = subprocess.run(
        ["bash", "-c", f". {HELPER}; verify_caption_backend_auth"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "no scoped credential" in result.stderr
