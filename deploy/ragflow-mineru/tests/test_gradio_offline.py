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
        self.assertIn("resolver 127.0.0.11", nginx)
        self.assertIn("resolver_timeout 2s;", nginx)
        self.assertIn("set $mineru_gradio_upstream mineru-gradio:7860;", nginx)
        self.assertIn("rewrite ^/mineru-ui/(.*)$ /$1 break;", nginx)
        self.assertIn("proxy_pass http://$mineru_gradio_upstream;", nginx)
        self.assertNotIn("proxy_pass http://mineru-gradio:7860/;", nginx)
        self.assertIn("error_page 502 504 =503 @mineru_ui_unavailable;", nginx)
        self.assertIn("location @mineru_ui_unavailable", nginx)
        self.assertIn("X-Forwarded-Prefix", nginx)
        self.assertIn("proxy_buffering off", nginx)
        self.assertIn("Content-Security-Policy", nginx)

    def test_nginx_rewrites_optional_browser_cdn_resources_locally(self):
        nginx = read(STACK / "gateway" / "nginx.conf.template")
        for expected in (
            'location ^~ /mineru-ui/_offline/',
            'proxy_set_header Accept-Encoding "";',
            "sub_filter_once off;",
            "sub_filter_types application/json application/javascript text/javascript text/css;",
            "https://fonts.googleapis.com",
            "https://fonts.gstatic.com",
            "https://cdnjs.cloudflare.com/ajax/libs/iframe-resizer/4.3.1/iframeResizer.contentWindow.min.js",
            "https://use.fontawesome.com/releases/v5.15.4/css/all.css",
            "https://img.shields.io/github/stars/opendatalab/MinerU.svg",
            "data:image/gif;base64,",
            "/mineru-ui/_offline/",
        ):
            self.assertIn(expected, nginx)

    def test_gateway_override_keeps_gradio_port_private(self):
        gateway = read(STACK / "docker-compose.gateway.yml")
        self.assertIn("mineru-gradio:\n    ports: []", gateway)

    def test_windows_packaging_builds_selected_ui_image(self):
        script = read(STACK / "scripts" / "package-windows.ps1")
        for expected in (
            '[string]$MineruGradioImage = "mineru-gradio-offline:latest"',
            "[switch]$SkipMineruGradioBuild",
            '"services\\mineru-gradio-offline"',
            '"mineru-gradio-offline-source"',
            '"MINERU_BASE_IMAGE=$MineruImage"',
            '"MINERU_GRADIO_IMAGE"',
            '"mineru-ui"',
            "mineruGradioImage = $MineruGradioImage",
        ):
            self.assertIn(expected, script)

    def test_deployment_summary_and_verification_cover_prefixed_ui(self):
        deploy = read(STACK / "scripts" / "deploy-linux.sh")
        verify = read(STACK / "scripts" / "verify-linux.sh")
        self.assertIn("/mineru-ui/", deploy)
        for expected in (
            "COMPOSE_PROFILES",
            "mineru-ui",
            "Checking gateway MinerU Gradio route",
            "/mineru-ui/",
            "window.gradio_config",
            "fonts.googleapis.com",
            "fonts.gstatic.com",
            "cdnjs.cloudflare.com",
            "use.fontawesome.com",
            "img.shields.io",
            "docker port mineru-gradio",
            "/opt/mineru-ui-assets/pdf.worker.min.mjs",
            "docker logs --tail 40 mineru-gradio",
        ):
            self.assertIn(expected, verify)

    def test_documentation_defines_offline_ui_scope(self):
        deployment_readme = read(STACK / "README.md")
        root_readme = read(ROOT / "README.md")
        for expected in (
            "/mineru-ui/",
            "mineru-gradio-offline",
            "PDF preview",
            "upload, conversion, and download",
            "Office gateway",
            "Microsoft Office Online iframe",
            "Google Fonts",
            "Font Awesome",
            "CDNJS",
            "star badge",
            "port 7860",
            "mineru-ui",
        ):
            self.assertIn(expected, deployment_readme)
        self.assertIn("/mineru-ui/", root_readme)


if __name__ == "__main__":
    unittest.main()
