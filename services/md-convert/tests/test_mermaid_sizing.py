from pathlib import Path
import tempfile
import unittest
import zipfile

from app.converter import (
    MermaidFormat,
    PageBox,
    RenderedDiagram,
    calculate_display_dimension,
    read_docx_page_box,
)


DOCUMENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:sectPr>
    <w:pgSz w:w="12240" w:h="15840"/>
    <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/>
  </w:sectPr></w:body>
</w:document>
"""


class MermaidSizingTests(unittest.TestCase):
    def test_reads_usable_page_box_from_reference_docx(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reference.docx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", DOCUMENT_XML)

            box = read_docx_page_box(path)

        self.assertAlmostEqual(box.width_inches, 6.5)
        self.assertAlmostEqual(box.height_inches, 9.0)

    def test_invalid_reference_uses_safe_default(self):
        box = read_docx_page_box(Path("missing.docx"))
        self.assertEqual(box, PageBox(6.3, 8.5))

    def test_reference_without_section_uses_safe_default(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reference.docx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(
                    "word/document.xml",
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/'
                    'wordprocessingml/2006/main"><w:body/></w:document>',
                )

            box = read_docx_page_box(path)

        self.assertEqual(box, PageBox(6.3, 8.5))

    def test_png_is_not_enlarged_beyond_150_ppi(self):
        image = RenderedDiagram(Path("small.png"), MermaidFormat.PNG, 300, 150)

        dimension = calculate_display_dimension(image, PageBox(6.5, 9.0))

        self.assertEqual(dimension.axis, "width")
        self.assertAlmostEqual(dimension.inches, 2.0)

    def test_wide_and_tall_images_fit_both_page_axes(self):
        wide = RenderedDiagram(Path("wide.png"), MermaidFormat.PNG, 1200, 600)
        tall = RenderedDiagram(Path("tall.png"), MermaidFormat.PNG, 600, 1800)

        wide_size = calculate_display_dimension(wide, PageBox(6.5, 9.0))
        tall_size = calculate_display_dimension(tall, PageBox(6.5, 9.0))

        self.assertEqual(wide_size.axis, "width")
        self.assertAlmostEqual(wide_size.inches, 5.85)
        self.assertEqual(tall_size.axis, "height")
        self.assertAlmostEqual(tall_size.inches, 8.1)


if __name__ == "__main__":
    unittest.main()
