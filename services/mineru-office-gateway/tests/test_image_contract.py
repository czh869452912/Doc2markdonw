from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ImageContractTests(unittest.TestCase):
    def test_image_contains_all_office_apps_and_nonroot_runtime(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        for package in (
            "libreoffice-writer",
            "libreoffice-impress",
            "libreoffice-calc",
        ):
            self.assertIn(package, dockerfile)
        self.assertIn("USER office", dockerfile)
        self.assertIn("HEALTHCHECK", dockerfile)
        self.assertIn("ENTRYPOINT", dockerfile)

        entrypoint = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
        self.assertIn("OFFICE_EXTRA_FONT_DIR", entrypoint)
        self.assertIn("fc-cache", entrypoint)
        self.assertIn('exec "$@"', entrypoint)


if __name__ == "__main__":
    unittest.main()
