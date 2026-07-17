import os
import unittest
from unittest.mock import patch

from app.settings import get_settings


class SettingsTests(unittest.TestCase):
    def test_defaults_match_deployment_contract(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = get_settings()
        self.assertEqual(settings.upstream_url, "http://mineru-router:8002")
        self.assertEqual(settings.default_mode, "pdf_ocr")
        self.assertEqual(settings.office_parse_method, "ocr")
        self.assertEqual(settings.office_backend, "pipeline")
        self.assertEqual(settings.max_file_bytes, 104857600)
        self.assertEqual(settings.max_files, 10)
        self.assertEqual(settings.convert_timeout_seconds, 300)
        self.assertEqual(settings.max_concurrent_conversions, 1)
        self.assertEqual(
            getattr(settings, "upstream_connect_timeout_seconds", None), 10
        )
        self.assertEqual(
            getattr(settings, "upstream_read_timeout_seconds", None), 3600
        )
        self.assertEqual(
            getattr(settings, "upstream_write_timeout_seconds", None), 300
        )
        self.assertEqual(
            getattr(settings, "upstream_pool_timeout_seconds", None), 30
        )
        self.assertEqual(
            getattr(settings, "upstream_health_timeout_seconds", None), 5
        )

    def test_invalid_default_mode_fails_at_startup(self):
        with patch.dict(os.environ, {"OFFICE_DEFAULT_MODE": "guess"}, clear=True):
            with self.assertRaisesRegex(ValueError, "OFFICE_DEFAULT_MODE"):
                get_settings()


if __name__ == "__main__":
    unittest.main()
