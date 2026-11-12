"""Opt in with RUN_DOCKER_TESTS=1; requires a locally available nginx image."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import unittest
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.request import HTTPRedirectHandler, build_opener, urlopen


STACK = Path(__file__).resolve().parents[1]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@unittest.skipUnless(os.environ.get("RUN_DOCKER_TESTS") == "1", "set RUN_DOCKER_TESTS=1 to run nginx")
class GatewayRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        template = (STACK / "gateway/nginx.conf.template").read_text()
        for source, target in {
            "${GATEWAY_MAX_BODY_SIZE}": "1m",
            "${GATEWAY_PROXY_READ_TIMEOUT}": "30s",
            "${RAGFLOW_WEB_UPSTREAM}": "127.0.0.1:18081",
            "md-convert-api:8080": "127.0.0.1:18081",
            "mineru-office-gateway:8081": "127.0.0.1:18081",
            "mineru-gradio:7860": "127.0.0.1:18081",
        }.items():
            template = template.replace(source, target)
        config = Path(temporary.name) / "nginx.conf"
        config.write_text('events {}\nhttp {\n' + template + '''
server {
    listen 18081;
    location = /config {
        default_type application/json;
        return 200 '{"stylesheets":["https://fonts.googleapis.com/css2?family=Source+Sans+Pro"]}';
    }
    location /gradio_api/custom_component/ {
        default_type application/javascript;
        return 200 'import "../../../../../assets/svelte/svelte_internal_client.js";';
    }
    location /assets/ {
        default_type application/javascript;
        return 200 'export {};';
    }
    location / { default_type text/html; return 200 '<html>fallback</html>'; }
}
}
''', encoding="utf-8")
        cls.container = subprocess.check_output([
            "docker", "run", "--pull=never", "--rm", "-d", "-p", "127.0.0.1::80",
            "--mount", f"type=bind,source={config},target=/etc/nginx/nginx.conf,readonly",
            os.environ.get("NGINX_TEST_IMAGE", "nginx:alpine"),
        ], text=True).strip()
        cls.addClassCleanup(subprocess.run, ["docker", "rm", "-f", cls.container], capture_output=True)
        address = subprocess.check_output(["docker", "port", cls.container, "80/tcp"], text=True).strip()
        cls.root = "http://" + address
        deadline = time.monotonic() + 10
        while True:
            try:
                with urlopen(cls.root, timeout=1):
                    break
            except URLError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)

    def test_redirect_retains_path_query_port_and_loads_relative_import(self):
        path = "/gradio_api/custom_component/pdf/client/component/index.js?version=abc"
        with self.assertRaises(URLError) as caught:
            build_opener(NoRedirect()).open(self.root + path)
        self.assertEqual(caught.exception.code, 307)
        self.assertEqual(caught.exception.headers["Location"], "/mineru-ui" + path)
        with urlopen(self.root + path) as response:
            self.assertIn("/mineru-ui/gradio_api/", response.url)
            self.assertIn("javascript", response.headers.get_content_type())
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            dependency = re.search(r'"([^"]+)"', response.read().decode())[1]
            dependency_url = urljoin(response.url, dependency)
        self.assertEqual(dependency_url, self.root + "/mineru-ui/assets/svelte/svelte_internal_client.js")
        with urlopen(dependency_url) as response:
            self.assertIn("javascript", response.headers.get_content_type())

    def test_font_url_does_not_duplicate_prefix_and_pages_disable_cache(self):
        with urlopen(self.root + "/mineru-ui/config") as response:
            config = json.load(response)
        stylesheet = config["stylesheets"][0]
        self.assertEqual(stylesheet, "_offline/google-fonts/css2?family=Source+Sans+Pro")
        with urlopen(self.root + "/mineru-ui/" + stylesheet) as response:
            self.assertEqual(response.status, 204)
        for path in ("/convert/", "/mineru-ui/"):
            with urlopen(self.root + path) as response:
                self.assertEqual(response.headers["Cache-Control"], "no-store")
