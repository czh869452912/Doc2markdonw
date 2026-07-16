from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from app.converter import MermaidDensity, MermaidDirection, MermaidFormat
from app.jobs import run_conversion_job


class JobOptionTests(unittest.TestCase):
    @patch("app.jobs.run_conversion")
    @patch("app.jobs.KrokiMermaidRenderer")
    @patch("app.jobs.get_settings")
    def test_job_revalidates_options_and_resolves_auto_renderer_format(
        self,
        get_settings,
        renderer_class,
        run_conversion,
    ):
        get_settings.return_value = SimpleNamespace(
            kroki_url="http://kroki:8000",
            mermaid_output_format="svg",
        )
        with tempfile.TemporaryDirectory() as directory:
            work_dir = Path(directory)
            (work_dir / "source.md").write_text("# Demo", encoding="utf-8")
            output = work_dir / "result.docx"
            output.write_bytes(b"docx")
            run_conversion.return_value = output

            run_conversion_job(
                "job-1",
                str(work_dir),
                {
                    "output_format": "docx",
                    "render_mermaid": True,
                    "mermaid_layout": "dagre",
                    "mermaid_format": "auto",
                    "mermaid_direction": "lr",
                    "mermaid_density": "compact",
                },
            )

        request = run_conversion.call_args.args[2]
        self.assertIs(request.mermaid_format, MermaidFormat.AUTO)
        self.assertIs(request.mermaid_direction, MermaidDirection.LR)
        self.assertIs(request.mermaid_density, MermaidDensity.COMPACT)
        renderer_class.assert_called_once_with(
            "http://kroki:8000",
            output_format=MermaidFormat.PNG,
        )


if __name__ == "__main__":
    unittest.main()
