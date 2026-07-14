from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
STACK = ROOT / "deploy" / "ragflow-mineru"
PACKAGE = ROOT / "dist" / "ragflow-mineru-airgap-v0.26.4-20260708-163537"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class EmbeddedMineruModelsTests(unittest.TestCase):
    def test_compose_uses_image_owned_models(self):
        compose_files = [STACK / "docker-compose.mineru.yml"]
        packaged_compose = (
            PACKAGE / "ragflow" / "docker" / "docker-compose.mineru.yml"
        )
        if packaged_compose.exists():
            compose_files.append(packaged_compose)

        for path in compose_files:
            with self.subTest(path=path):
                content = read(path)
                self.assertNotIn("./mineru-home:/root", content)
                self.assertEqual(content.count("./mineru-output:/tmp/mineru"), 2)
                self.assertEqual(content.count("./mineru-input:/data/input:ro"), 2)
                model_source_keys = sum(
                    line.lstrip().startswith("MINERU_MODEL_SOURCE:")
                    for line in content.splitlines()
                )
                self.assertEqual(model_source_keys, 2)

    def test_scripts_do_not_manage_external_mineru_home(self):
        package_script = read(STACK / "scripts" / "package-windows.ps1")
        self.assertNotIn("IncludeMineruHome", package_script)
        self.assertNotIn("MineruHomePath", package_script)
        self.assertNotIn("download-mineru-models-linux.sh", package_script)
        self.assertNotIn('"mineru-home"', package_script)

        deploy_scripts = [STACK / "scripts" / "deploy-linux.sh"]
        packaged_deploy = PACKAGE / "scripts" / "deploy-linux.sh"
        if packaged_deploy.exists():
            deploy_scripts.append(packaged_deploy)
        for path in deploy_scripts:
            with self.subTest(path=path):
                self.assertNotIn("mineru-home", read(path))

        self.assertFalse(
            (STACK / "scripts" / "download-mineru-models-linux.sh").exists()
        )
        self.assertFalse(
            (PACKAGE / "scripts" / "download-mineru-models-linux.sh").exists()
        )

    def test_verification_checks_image_model_paths(self):
        verify_scripts = [STACK / "scripts" / "verify-linux.sh"]
        packaged_verify = PACKAGE / "scripts" / "verify-linux.sh"
        if packaged_verify.exists():
            verify_scripts.append(packaged_verify)
        for path in verify_scripts:
            with self.subTest(path=path):
                content = read(path)
                self.assertIn("MinerU container must not mount /root", content)
                self.assertIn("models-dir", content)
                self.assertIn("pipeline", content)
                self.assertIn("vlm", content)

    def test_documentation_describes_embedded_models(self):
        readmes = [STACK / "README.md"]
        packaged_readme = PACKAGE / "README.md"
        if packaged_readme.exists():
            readmes.append(packaged_readme)
        for path in readmes:
            with self.subTest(path=path):
                content = read(path)
                self.assertNotIn("IncludeMineruHome", content)
                self.assertNotIn("download-mineru-models-linux.sh", content)
                self.assertIn("embedded", content.lower())


if __name__ == "__main__":
    unittest.main()
