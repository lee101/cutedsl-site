import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "deploy" / "needrestart" / "nginx.service"


class NeedrestartNginxHookTest(unittest.TestCase):
    def _fake_command(self, directory: Path, name: str, body: str) -> Path:
        command = directory / name
        command.write_text("#!/bin/sh\nset -eu\n" + body, encoding="utf-8")
        command.chmod(command.stat().st_mode | stat.S_IXUSR)
        return command

    def test_validates_then_gracefully_reloads_without_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            calls = tmp_path / "calls"
            nginx = self._fake_command(
                tmp_path, "nginx", f'printf "nginx %s\\n" "$*" >> "{calls}"\n'
            )
            systemctl = self._fake_command(
                tmp_path,
                "systemctl",
                f'printf "systemctl %s\\n" "$*" >> "{calls}"\n',
            )

            env = os.environ.copy()
            env.update(NGINX_BIN=str(nginx), SYSTEMCTL_BIN=str(systemctl))
            subprocess.run([str(HOOK)], check=True, env=env)

            self.assertEqual(
                calls.read_text(encoding="utf-8").splitlines(),
                ["nginx -t", "systemctl reload nginx.service"],
            )

    def test_does_not_touch_nginx_when_config_validation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            calls = tmp_path / "calls"
            nginx = self._fake_command(tmp_path, "nginx", "exit 1\n")
            systemctl = self._fake_command(
                tmp_path,
                "systemctl",
                f'printf "systemctl %s\\n" "$*" >> "{calls}"\n',
            )

            env = os.environ.copy()
            env.update(NGINX_BIN=str(nginx), SYSTEMCTL_BIN=str(systemctl))
            result = subprocess.run([str(HOOK)], check=False, env=env)

            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(calls.exists())


if __name__ == "__main__":
    unittest.main()
