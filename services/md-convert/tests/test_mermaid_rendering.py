from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import requests

from app.converter import (
    KrokiMermaidRenderer,
    MermaidDensity,
    MermaidFormat,
    MermaidRenderError,
)


class FakeResponse:
    def __init__(self, content: bytes, content_type: str, status_code: int = 200):
        self.content = content
        self.headers = {"Content-Type": content_type}
        self.status_code = status_code
        self.text = content.decode("utf-8", errors="replace")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def png_header(width: int, height: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I4sII", 13, b"IHDR", width, height)


class MermaidRenderingTests(unittest.TestCase):
    @patch("requests.post")
    def test_renderer_returns_dimensions_and_sends_layout_density_options(self, post):
        post.return_value = FakeResponse(png_header(1200, 600), "image/png")
        renderer = KrokiMermaidRenderer("http://kroki:8000", MermaidFormat.PNG)

        with tempfile.TemporaryDirectory() as directory:
            result = renderer.render(
                "flowchart LR\nA-->B",
                Path(directory),
                "elk",
                MermaidDensity.COMPACT,
            )

        self.assertIs(result.image_format, MermaidFormat.PNG)
        self.assertEqual((result.width_px, result.height_px), (1200.0, 600.0))
        self.assertEqual(result.path.name, "diagram-1.png")
        params = post.call_args.kwargs["params"]
        self.assertEqual(params["layout"], "elk")
        self.assertEqual(params["flowchart_node-spacing"], "30")

    @patch("requests.post")
    def test_renderer_rejects_mismatched_content_type(self, post):
        post.return_value = FakeResponse(png_header(10, 10), "text/html")
        renderer = KrokiMermaidRenderer("http://kroki:8000", MermaidFormat.PNG)

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(MermaidRenderError, "Content-Type"):
                renderer.render(
                    "flowchart LR\nA-->B",
                    Path(directory),
                    "elk",
                    MermaidDensity.STANDARD,
                )

    @patch("requests.post")
    def test_renderer_wraps_network_errors(self, post):
        post.side_effect = requests.ConnectionError("connection refused")
        renderer = KrokiMermaidRenderer("http://kroki:8000", MermaidFormat.SVG)

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(MermaidRenderError, "connection refused"):
                renderer.render(
                    "flowchart LR\nA-->B",
                    Path(directory),
                    "elk",
                    MermaidDensity.STANDARD,
                )


if __name__ == "__main__":
    unittest.main()
