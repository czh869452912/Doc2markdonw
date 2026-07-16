import struct
import unittest

from app.converter import MermaidRenderError, read_png_dimensions, read_svg_dimensions


def png_header(width: int, height: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I4sII", 13, b"IHDR", width, height)


class ImageDimensionTests(unittest.TestCase):
    def test_reads_png_ihdr_dimensions(self):
        self.assertEqual(read_png_dimensions(png_header(1200, 600)), (1200.0, 600.0))

    def test_rejects_invalid_png(self):
        with self.assertRaisesRegex(MermaidRenderError, "PNG"):
            read_png_dimensions(b"not png")

    def test_reads_svg_viewbox_and_physical_dimensions(self):
        self.assertEqual(
            read_svg_dimensions(b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 400"/>'),
            (800.0, 400.0),
        )
        width, height = read_svg_dimensions(
            b'<svg xmlns="http://www.w3.org/2000/svg" width="6in" height="3in"/>'
        )
        self.assertAlmostEqual(width, 576.0)
        self.assertAlmostEqual(height, 288.0)

    def test_rejects_svg_without_dimensions(self):
        with self.assertRaisesRegex(MermaidRenderError, "dimensions"):
            read_svg_dimensions(b'<svg xmlns="http://www.w3.org/2000/svg"/>')

    def test_rejects_non_svg_xml_with_viewbox(self):
        with self.assertRaisesRegex(MermaidRenderError, "SVG"):
            read_svg_dimensions(b'<html viewBox="0 0 100 100"/>')


if __name__ == "__main__":
    unittest.main()
