import os
import pwd
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("setfacl") is None, reason="POSIX ACL tools required")
def test_shared_image_storage_survives_monitor_private_umask(tmp_path):
    script = Path(__file__).resolve().parents[1] / "deploy/configure-image-storage.sh"
    user = pwd.getpwuid(os.getuid()).pw_name
    images = tmp_path / "images"
    for _ in range(2):
        subprocess.run(["bash", str(script), str(images), user], check=True)

    for variant in ("originals", "medium", "thumbs"):
        directory = images / variant
        acl = subprocess.check_output(["getfacl", "-cp", str(directory)], text=True)
        assert f"user:{user}:rwx" in acl
        assert f"default:user:{user}:rwx" in acl
        image = directory / "canary.webp"
        subprocess.run(
            ["bash", "-c", 'umask 0077; printf image > "$1"', "bash", str(image)],
            check=True,
        )
        acl = subprocess.check_output(["getfacl", "-cp", str(image)], text=True)
        assert f"user:{user}:rwx\t#effective:rw-" in acl
        assert "mask::rw-" in acl
