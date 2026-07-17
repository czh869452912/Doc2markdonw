import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.render import OfficeRenderError, OfficeRenderTimeout, render_to_pdf


class RendererTests(unittest.TestCase):
    def test_render_returns_nonempty_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.docx"
            source.write_bytes(b"PK\x03\x04")

            def fake_run(command, **kwargs):
                output_dir = Path(command[command.index("--outdir") + 1])
                (output_dir / "input.pdf").write_bytes(b"%PDF-1.7\nfixture")
                return subprocess.CompletedProcess(command, 0, "converted", "")

            with patch("app.render.subprocess.run", side_effect=fake_run):
                result = render_to_pdf(source, root, "libreoffice", 30)
            self.assertEqual(result.name, "input.pdf")

    def test_timeout_has_stable_error_type(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.docx"
            source.write_bytes(b"PK\x03\x04")
            with patch(
                "app.render.subprocess.run",
                side_effect=subprocess.TimeoutExpired("libreoffice", 1),
            ):
                with self.assertRaises(OfficeRenderTimeout):
                    render_to_pdf(source, Path(directory), "libreoffice", 1)

    def test_missing_pdf_is_render_error(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.docx"
            source.write_bytes(b"PK\x03\x04")
            completed = subprocess.CompletedProcess([], 0, "", "")
            with patch("app.render.subprocess.run", return_value=completed):
                with self.assertRaises(OfficeRenderError):
                    render_to_pdf(source, Path(directory), "libreoffice", 30)


if __name__ == "__main__":
    unittest.main()
