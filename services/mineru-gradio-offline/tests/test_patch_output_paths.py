import tempfile
import unittest
from pathlib import Path

from patch_output_paths import patch_source


SOURCE = Path(__file__).with_name("output_paths_fixture.py")


class OutputPathTests(unittest.TestCase):
    def setUp(self):
        self.namespace = {}
        exec(patch_source(SOURCE.read_text(encoding="utf-8")), self.namespace)
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def result(self, folder):
        directory = self.root / "测试文档" / folder
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "测试文档.md").write_text("# converted", encoding="utf-8")
        return directory

    def resolve(self, backend="hybrid-engine"):
        return self.namespace["resolve_parse_dir"](
            self.root, "测试文档", backend, "auto", allow_office_fallback=True
        )

    def test_office_gateway_pipeline_ocr_result(self):
        directory = self.result("ocr")
        self.assertEqual(self.resolve(), directory)
        self.assertEqual(self.resolve("pipeline"), directory)

    def test_original_hybrid_path_is_preserved(self):
        directory = self.result("hybrid_auto")
        self.result("ocr")
        self.assertEqual(self.resolve(), directory)

    def test_office_native_fallback_is_preserved(self):
        self.assertEqual(self.resolve(), self.root / "测试文档" / "hybrid_auto")
        directory = self.result("office")
        self.assertEqual(self.resolve(), directory)

    def test_empty_expected_directory_does_not_hide_real_result(self):
        (self.root / "测试文档" / "hybrid_auto").mkdir(parents=True)
        directory = self.result("ocr")
        self.assertEqual(self.resolve(), directory)

    def test_ambiguous_results_are_rejected(self):
        self.result("ocr")
        self.result("auto")
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            self.resolve()

    def test_patch_is_idempotent_and_rejects_unknown_source(self):
        patched = patch_source(SOURCE.read_text(encoding="utf-8"))
        self.assertEqual(patch_source(patched), patched)
        with self.assertRaises(ValueError):
            patch_source("def resolve_parse_dir():\n    return None\n")
