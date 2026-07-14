from pathlib import Path
import unittest

from app.converter import (
    ConversionRequest,
    OutputFormat,
    build_conversion_plan,
    preprocess_markdown,
    validate_output_format,
)


class FakeRenderer:
    def __init__(self):
        self.calls = []

    def render(self, diagram: str, output_dir: Path, layout: str) -> Path:
        self.calls.append({"diagram": diagram, "layout": layout})
        path = output_dir / f"diagram-{len(self.calls)}.svg"
        path.write_text("<svg></svg>", encoding="utf-8")
        return path


class ConverterTests(unittest.TestCase):
    def test_validate_output_format_accepts_word_and_common_exports(self):
        self.assertIs(validate_output_format("docx"), OutputFormat.DOCX)
        self.assertIs(validate_output_format("doc"), OutputFormat.DOC)
        self.assertIs(validate_output_format("pdf"), OutputFormat.PDF)
        self.assertIs(validate_output_format("html"), OutputFormat.HTML)
        self.assertIs(validate_output_format("odt"), OutputFormat.ODT)

    def test_validate_output_format_rejects_unsupported_values(self):
        with self.assertRaisesRegex(ValueError, "Unsupported output format"):
            validate_output_format("exe")

    def test_preprocess_markdown_renders_mermaid_blocks_with_elk_layout(self):
        with self.subTest("renders mermaid"):
            import tempfile

            with tempfile.TemporaryDirectory() as directory:
                tmp_path = Path(directory)
                renderer = FakeRenderer()
                source = """# Demo

```mermaid
flowchart LR
  A --> B
```

Math remains inline: $E=mc^2$.
"""

                result = preprocess_markdown(
                    source,
                    work_dir=tmp_path,
                    renderer=renderer,
                    mermaid_layout="elk",
                )

                self.assertEqual(
                    renderer.calls,
                    [{"diagram": "flowchart LR\n  A --> B", "layout": "elk"}],
                )
                self.assertNotIn("```mermaid", result)
                self.assertIn("![Mermaid diagram](diagram-1.svg)", result)
                self.assertIn("$E=mc^2$", result)

    def test_preprocess_markdown_leaves_mermaid_disabled(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            renderer = FakeRenderer()
            source = "```mermaid\nflowchart TD\nA-->B\n```"

            result = preprocess_markdown(
                source,
                work_dir=tmp_path,
                renderer=renderer,
                render_mermaid=False,
            )

            self.assertEqual(result, source)
            self.assertEqual(renderer.calls, [])

    def test_build_conversion_plan_generates_docx_pandoc_command(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            request = ConversionRequest(output_format=OutputFormat.DOCX)
            plan = build_conversion_plan(tmp_path / "input.md", tmp_path, request)

            self.assertEqual(plan.final_output, tmp_path / "result.docx")
            self.assertEqual(
                plan.commands,
                [
                    [
                        "pandoc",
                        str(tmp_path / "input.md"),
                        "--from",
                        "gfm+tex_math_dollars",
                        "--standalone",
                        "--resource-path",
                        str(tmp_path),
                        "-o",
                        str(tmp_path / "result.docx"),
                    ]
                ],
            )

    def test_build_conversion_plan_generates_doc_via_docx_then_libreoffice(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            request = ConversionRequest(output_format=OutputFormat.DOC)
            plan = build_conversion_plan(tmp_path / "input.md", tmp_path, request)

            self.assertEqual(plan.final_output, tmp_path / "result.doc")
            self.assertEqual(plan.commands[0][-1], str(tmp_path / "intermediate.docx"))
            self.assertEqual(
                plan.commands[1],
                [
                    "libreoffice",
                    "--headless",
                    "--convert-to",
                    "doc",
                    "--outdir",
                    str(tmp_path),
                    str(tmp_path / "intermediate.docx"),
                ],
            )


if __name__ == "__main__":
    unittest.main()
