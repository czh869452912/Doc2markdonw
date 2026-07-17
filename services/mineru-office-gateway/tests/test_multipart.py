import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from starlette.datastructures import Headers

from app import multipart
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


class MultipartParserTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_oversized_file_before_consuming_request_tail(self):
        parse_multipart = getattr(multipart, "parse_multipart", None)
        self.assertIsNotNone(parse_multipart, "parse_multipart must be implemented")
        boundary = "bounded-test"
        chunks = [
            (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="files"; '
                'filename="large.docx"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n"
            ).encode(),
            b"12345",
            b"6",
            f"\r\n--{boundary}--\r\n".encode(),
        ]
        consumed = []

        async def stream():
            for chunk in chunks:
                consumed.append(chunk)
                yield chunk

        headers = Headers(
            {"content-type": f"multipart/form-data; boundary={boundary}"}
        )
        with self.assertRaisesRegex(UploadLimitError, "large.docx"):
            await parse_multipart(
                headers,
                stream(),
                max_files=10,
                max_file_bytes=5,
            )
        self.assertEqual(consumed, chunks[:3])


if __name__ == "__main__":
    unittest.main()
