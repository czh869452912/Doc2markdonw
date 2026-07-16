from pathlib import Path
import os
import unittest
from unittest.mock import patch

from app.settings import get_settings


def deployment_files() -> tuple[Path, Path, Path] | None:
    for parent in Path(__file__).resolve().parents:
        source_compose = parent / "deploy/ragflow-mineru/docker-compose.md-convert.yml"
        source_env = parent / "deploy/ragflow-mineru/env/airgap.env.example"
        source_readme = parent / "deploy/ragflow-mineru/README.md"
        if source_compose.exists() and source_env.exists() and source_readme.exists():
            return source_compose, source_env, source_readme
        package_compose = parent / "ragflow/docker/docker-compose.md-convert.yml"
        package_env = parent / "ragflow/docker/.env"
        package_readme = parent / "README.md"
        if package_compose.exists() and package_env.exists() and package_readme.exists():
            return package_compose, package_env, package_readme
    return None


class DeploymentDefaultTests(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_service_defaults_to_auto_mermaid_and_insecure_session_cookie(self):
        settings = get_settings()

        self.assertEqual(settings.mermaid_output_format, "auto")
        self.assertFalse(settings.cookie_secure)

    def test_compose_and_airgap_env_expose_matching_defaults(self):
        files = deployment_files()
        if files is None:
            self.skipTest("deployment files are outside the mounted test directory")
        compose_path, env_path, readme_path = files
        compose = compose_path.read_text(encoding="utf-8")
        env_example = env_path.read_text(encoding="utf-8")
        readme = readme_path.read_text(encoding="utf-8")

        self.assertIn("${MERMAID_OUTPUT_FORMAT:-auto}", compose)
        self.assertIn("${MD_CONVERT_COOKIE_SECURE:-false}", compose)
        self.assertIn("MERMAID_OUTPUT_FORMAT=auto", env_example)
        self.assertIn("MD_CONVERT_COOKIE_SECURE=false", env_example)
        self.assertIn("-c md-convert.cookies", readme)
        self.assertIn("-b md-convert.cookies", readme)


if __name__ == "__main__":
    unittest.main()
