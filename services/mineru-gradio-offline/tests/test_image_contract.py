from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ImageContractTests(unittest.TestCase):
    def test_dockerfile_pins_pdfjs_and_derives_from_mineru(self):
        content = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("pdfjs-dist@4.2.67", content)
        self.assertIn("ARG MINERU_BASE_IMAGE", content)
        self.assertIn("FROM ${MINERU_BASE_IMAGE}", content)
        self.assertIn("patch_gradio_pdf.py", content)
        self.assertNotIn("pip install mineru", content)


if __name__ == "__main__":
    unittest.main()
