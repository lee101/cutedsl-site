import os
import re
import unittest
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "deploy/nginx-cutedsl.conf"


class StaticShellRoutingTest(unittest.TestCase):
    def test_exported_shells_never_depend_on_the_api_upstream(self):
        config = CONFIG.read_text()
        match = re.search(r"location ~ (\S+) \{([^}]+)\}", config)
        self.assertIsNotNone(match)
        pattern, block = match.groups()
        for route in ("account", "lora-trainer"):
            for suffix in ("", "/"):
                with self.subTest(route=route, suffix=suffix):
                    capture = re.fullmatch(pattern, f"/{route}{suffix}")
                    self.assertIsNotNone(capture)
                    self.assertEqual(capture.group(1), route)
        for path in ("/api/health", "/api/service", "/accounting", "/image/example"):
            self.assertIsNone(re.fullmatch(pattern, path))
        self.assertIn("root /opt/cutedsl-site/frontend/out;", block)
        self.assertIn("try_files /$1.html =404;", block)
        self.assertNotIn("proxy_pass", block)
        self.assertNotIn("error_page", block)
        self.assertIn("server 127.0.0.1:8095;", config)

    @unittest.skipUnless(os.getenv("CUTEDSL_NGINX_ORIGIN"), "live nginx check is opt-in")
    def test_managed_nginx_serves_the_installed_exports(self):
        origin = os.environ["CUTEDSL_NGINX_ORIGIN"].rstrip("/")
        for route in ("account", "lora-trainer"):
            expected = Path(f"/opt/cutedsl-site/frontend/out/{route}.html").read_bytes()
            for suffix in ("", "/"):
                with self.subTest(route=route, suffix=suffix):
                    request = Request(
                        f"{origin}/{route}{suffix}?monitor_check=static-regression",
                        headers={"Host": "cutedsl.cc"},
                    )
                    with urlopen(request, timeout=15) as response:
                        self.assertEqual(response.status, 200)
                        self.assertEqual(response.headers.get_content_type(), "text/html")
                        self.assertEqual(response.read(), expected)
                        # Go sets CORS headers on every response; these shells
                        # must be served without passing through that process.
                        self.assertIsNone(response.headers.get("Access-Control-Allow-Methods"))


if __name__ == "__main__":
    unittest.main()
