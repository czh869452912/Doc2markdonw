import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.multipart import UploadLimitError, copy_upload, office_fields


class MultipartTests(unittest.TestCase):
    def test_copy_upload_enforces_limit_while_streaming(self):
        upload = SimpleNamespace(file=io.BytesIO(b"123456"))
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(UploadLimitError):
                asyncio.run(copy_upload(upload, Path(directory) / "x.docx", 5))

    def test_office_fields_strip_gateway_field_and_override_backend(self):
        fields = [
            ("backend", "hybrid-engine"),
            ("office_mode", "pdf_ocr"),
            ("return_md", "true"),
        ]
        result = office_fields(fields, parse_method="ocr", backend="pipeline")
        self.assertEqual(
            result,
            [
                ("return_md", "true"),
                ("parse_method", "ocr"),
                ("backend", "pipeline"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
