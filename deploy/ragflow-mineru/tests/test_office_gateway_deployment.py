from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
STACK = ROOT / "deploy" / "ragflow-mineru"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class OfficeGatewayDeploymentTests(unittest.TestCase):
    def test_compose_service_is_private_and_hardened(self):
        compose = read(STACK / "docker-compose.office-gateway.yml")
        self.assertIn("mineru-office-gateway:", compose)
        self.assertIn("${MINERU_OFFICE_GATEWAY_IMAGE:-mineru-office-gateway:latest}", compose)
        self.assertIn("- mineru-office", compose)
        self.assertIn("- mineru-router", compose)
        self.assertNotIn("ports:", compose)
        self.assertIn("tmpfs:", compose)
        self.assertIn("read_only: true", compose)
        self.assertIn("cap_drop:", compose)
        self.assertIn("- ALL", compose)
        self.assertIn("no-new-privileges:true", compose)
        self.assertIn("mem_limit:", compose)
        self.assertIn("cpus:", compose)

    def test_compose_exposes_the_complete_environment_contract(self):
        compose = read(STACK / "docker-compose.office-gateway.yml")
        for key in (
            "MINERU_UPSTREAM_URL",
            "OFFICE_DEFAULT_MODE",
            "OFFICE_PARSE_METHOD",
            "OFFICE_BACKEND",
            "OFFICE_MAX_FILE_BYTES",
            "OFFICE_MAX_FILES_PER_REQUEST",
            "OFFICE_CONVERT_TIMEOUT_SECONDS",
            "OFFICE_MAX_CONCURRENT_CONVERSIONS",
            "OFFICE_TMP_DIR",
            "OFFICE_EXTRA_FONT_DIR",
        ):
            self.assertIn(f"{key}:", compose)

    def test_nginx_routes_mineru_through_office_gateway(self):
        nginx = read(STACK / "gateway" / "nginx.conf.template")
        self.assertIn("proxy_pass http://mineru-office-gateway:8081/;", nginx)
        self.assertNotIn("proxy_pass http://mineru-router:8002/;", nginx)

        gateway = read(STACK / "docker-compose.gateway.yml")
        self.assertIn("- mineru-office-gateway", gateway)
        self.assertNotIn("- mineru-router", gateway)

    def test_airgap_environment_has_office_defaults(self):
        env = read(STACK / "env" / "airgap.env.example")
        self.assertIn("mineru-office", env)
        for assignment in (
            "MINERU_OFFICE_GATEWAY_IMAGE=mineru-office-gateway:latest",
            "MINERU_UPSTREAM_URL=http://mineru-router:8002",
            "OFFICE_DEFAULT_MODE=pdf_ocr",
            "OFFICE_PARSE_METHOD=ocr",
            "OFFICE_BACKEND=pipeline",
            "OFFICE_MAX_FILE_BYTES=104857600",
            "OFFICE_MAX_FILES_PER_REQUEST=10",
            "OFFICE_CONVERT_TIMEOUT_SECONDS=300",
            "OFFICE_MAX_CONCURRENT_CONVERSIONS=1",
            "OFFICE_TMP_DIR=/tmp/mineru-office",
            "OFFICE_EXTRA_FONT_DIR=/opt/office-fonts",
        ):
            self.assertIn(assignment, env)

    def test_windows_packaging_builds_and_records_office_gateway(self):
        script = read(STACK / "scripts" / "package-windows.ps1")
        for expected in (
            '[string]$MineruOfficeGatewayImage = "mineru-office-gateway:latest"',
            "[switch]$SkipOfficeGatewayBuild",
            '"docker-compose.office-gateway.yml"',
            '"services\\mineru-office-gateway"',
            '"office-gateway-source"',
            '"MINERU_OFFICE_GATEWAY_IMAGE"',
            '"mineru-office"',
            "mineruOfficeGatewayImage = $MineruOfficeGatewayImage",
        ):
            self.assertIn(expected, script)

    def test_linux_lifecycle_includes_fifth_compose_file(self):
        script = read(STACK / "scripts" / "deploy-linux.sh")
        self.assertGreaterEqual(
            script.count("docker-compose.office-gateway.yml"),
            3,
        )
        self.assertIn("docker-compose.office-gateway.v1.yml", script)


if __name__ == "__main__":
    unittest.main()
