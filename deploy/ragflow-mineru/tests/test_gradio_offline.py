from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
STACK = ROOT / "deploy" / "ragflow-mineru"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class GradioOfflineDeploymentTests(unittest.TestCase):
    def test_gradio_uses_offline_image_and_office_gateway(self):
        compose = read(STACK / "docker-compose.mineru.yml")
        self.assertIn("MINERU_GRADIO_IMAGE", compose)
        self.assertIn("GRADIO_ROOT_PATH", compose)
        self.assertIn("GRADIO_ANALYTICS_ENABLED", compose)
        self.assertIn("HF_HUB_OFFLINE", compose)
        self.assertIn("TRANSFORMERS_OFFLINE", compose)
        self.assertIn("http://mineru-office-gateway:8081", compose)

    def test_nginx_exposes_prefixed_gradio_route(self):
        nginx = read(STACK / "gateway" / "nginx.conf.template")
        self.assertIn("location = /mineru-ui", nginx)
        self.assertIn("location /mineru-ui/", nginx)
        self.assertIn("proxy_pass http://mineru-gradio:7860/;", nginx)
        self.assertIn("X-Forwarded-Prefix", nginx)
        self.assertIn("proxy_buffering off", nginx)
        self.assertIn("Content-Security-Policy", nginx)

    def test_gateway_override_keeps_gradio_port_private(self):
        gateway = read(STACK / "docker-compose.gateway.yml")
        self.assertIn("mineru-gradio:\n    ports: []", gateway)


if __name__ == "__main__":
    unittest.main()
