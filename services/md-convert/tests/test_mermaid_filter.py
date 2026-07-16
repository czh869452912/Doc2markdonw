from pathlib import Path
import tempfile
import unittest

from app.converter import (
    MERMAID_FILTER_PATH,
    ConversionRequest,
    OutputFormat,
    build_conversion_plan,
)


class MermaidFilterTests(unittest.TestCase):
    def test_every_pandoc_command_uses_bundled_mermaid_filter(self):
        with tempfile.TemporaryDirectory() as directory:
            work_dir = Path(directory)
            plan = build_conversion_plan(
                work_dir / "input.md",
                work_dir,
                ConversionRequest(output_format=OutputFormat.DOCX),
            )

        self.assertTrue(MERMAID_FILTER_PATH.exists())
        self.assertIn("--lua-filter", plan.commands[0])
        index = plan.commands[0].index("--lua-filter")
        self.assertEqual(plan.commands[0][index + 1], str(MERMAID_FILTER_PATH))


if __name__ == "__main__":
    unittest.main()
