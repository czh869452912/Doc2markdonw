import tempfile
import unittest
from pathlib import Path

from patch_gradio_pdf import CMAP_REMOTE, WORKER_REMOTE, patch_bundle


class PatchGradioPdfTests(unittest.TestCase):
    def test_replaces_each_remote_url_once(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "index.js"
            bundle.write_text(
                f'workerSrc="{WORKER_REMOTE}";cMapUrl="{CMAP_REMOTE}";',
                encoding="utf-8",
            )
            patch_bundle(bundle)
            content = bundle.read_text(encoding="utf-8")
            self.assertNotIn(WORKER_REMOTE, content)
            self.assertNotIn(CMAP_REMOTE, content)
            self.assertIn(
                "./gradio_api/file=/opt/mineru-ui-assets/pdf.worker.min.mjs",
                content,
            )
            self.assertIn(
                "./gradio_api/file=/opt/mineru-ui-assets/cmaps/",
                content,
            )

    def test_refuses_unknown_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "index.js"
            bundle.write_text("no expected urls", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "exactly once"):
                patch_bundle(bundle)


if __name__ == "__main__":
    unittest.main()
