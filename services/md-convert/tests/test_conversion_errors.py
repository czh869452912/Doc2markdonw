from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from app.converter import (
    ConversionCommandError,
    ConversionRequest,
    OutputFormat,
    RenderedDiagram,
    MermaidFormat,
    run_conversion,
)


class NoopRenderer:
    def render(self, diagram, output_dir, layout, density):
        return RenderedDiagram(output_dir / "unused.svg", MermaidFormat.SVG, 1, 1)


class ConversionErrorTests(unittest.TestCase):
    @patch("app.converter.subprocess.run")
    def test_failed_command_includes_exit_code_executable_and_stderr(self, run):
        run.side_effect = subprocess.CalledProcessError(
            23,
            ["pandoc", "input.md"],
            stderr="The extension x is not supported",
        )

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ConversionCommandError) as error:
                run_conversion(
                    "# Demo",
                    Path(directory),
                    ConversionRequest(
                        output_format=OutputFormat.DOCX,
                        render_mermaid=False,
                    ),
                    NoopRenderer(),
                )

        message = str(error.exception)
        self.assertIn("pandoc", message)
        self.assertIn("exit code 23", message)
        self.assertIn("The extension x is not supported", message)


if __name__ == "__main__":
    unittest.main()
