import unittest

from app.files import BatchKind, classify_file, resolve_batch_mode


class FileClassificationTests(unittest.TestCase):
    def test_classifies_legacy_and_ooxml_office(self):
        legacy = classify_file("report.doc", bytes.fromhex("D0CF11E0A1B11AE1"))
        modern = classify_file("report.docx", b"PK\x03\x04")
        self.assertEqual(legacy.kind, BatchKind.OFFICE)
        self.assertFalse(legacy.native_supported)
        self.assertEqual(modern.kind, BatchKind.OFFICE)
        self.assertTrue(modern.native_supported)

    def test_rejects_extension_signature_mismatch(self):
        with self.assertRaisesRegex(ValueError, "signature"):
            classify_file("report.docx", b"%PDF-1.7")

    def test_rejects_mixed_office_and_pdf_batch(self):
        office = classify_file("report.docx", b"PK\x03\x04")
        pdf = classify_file("scan.pdf", b"%PDF-1.7")
        with self.assertRaisesRegex(ValueError, "Mixed"):
            resolve_batch_mode([office, pdf], None, "pdf_ocr")

    def test_native_is_rejected_for_legacy_office(self):
        legacy = classify_file("report.doc", bytes.fromhex("D0CF11E0A1B11AE1"))
        with self.assertRaisesRegex(ValueError, "native"):
            resolve_batch_mode([legacy], "native", "pdf_ocr")


if __name__ == "__main__":
    unittest.main()
