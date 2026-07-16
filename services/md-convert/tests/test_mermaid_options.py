import unittest

from app.converter import (
    ConversionRequest,
    MermaidDensity,
    MermaidDirection,
    MermaidFormat,
    OutputFormat,
    density_options,
    resolve_mermaid_format,
    rewrite_flowchart_direction,
    validate_mermaid_density,
    validate_mermaid_direction,
    validate_mermaid_format,
    validate_mermaid_layout,
)


class MermaidOptionTests(unittest.TestCase):
    def test_auto_format_uses_png_for_paged_targets_and_svg_for_vector_targets(self):
        for target in (OutputFormat.DOCX, OutputFormat.DOC, OutputFormat.PDF):
            with self.subTest(target=target):
                request = ConversionRequest(output_format=target)
                self.assertIs(resolve_mermaid_format(request), MermaidFormat.PNG)

        for target in (OutputFormat.HTML, OutputFormat.ODT, OutputFormat.EPUB):
            with self.subTest(target=target):
                request = ConversionRequest(output_format=target)
                self.assertIs(resolve_mermaid_format(request), MermaidFormat.SVG)

    def test_explicit_format_overrides_target_mapping(self):
        request = ConversionRequest(
            output_format=OutputFormat.DOCX,
            mermaid_format=MermaidFormat.SVG,
        )
        self.assertIs(resolve_mermaid_format(request), MermaidFormat.SVG)

    def test_mermaid_validators_accept_known_values_and_reject_unknown_values(self):
        self.assertIs(validate_mermaid_format(" PNG "), MermaidFormat.PNG)
        self.assertIs(validate_mermaid_direction("tb"), MermaidDirection.TB)
        self.assertIs(validate_mermaid_density("spacious"), MermaidDensity.SPACIOUS)
        self.assertEqual(validate_mermaid_layout(" ELK "), "elk")
        for validator in (
            validate_mermaid_format,
            validate_mermaid_direction,
            validate_mermaid_density,
        ):
            with self.subTest(validator=validator.__name__):
                with self.assertRaisesRegex(ValueError, "Supported"):
                    validator("invalid")
        with self.assertRaisesRegex(ValueError, "Supported"):
            validate_mermaid_layout("dot")

    def test_direction_rewrite_only_changes_flowchart_declaration(self):
        source = """---
title: Demo
---
%% comment
flowchart RL
  A --> B
"""
        self.assertIn(
            "flowchart TB",
            rewrite_flowchart_direction(source, MermaidDirection.TB),
        )
        self.assertIn(
            "flowchart LR",
            rewrite_flowchart_direction(source, MermaidDirection.LR),
        )
        self.assertEqual(
            rewrite_flowchart_direction(source, MermaidDirection.SOURCE),
            source,
        )
        sequence = "sequenceDiagram\n  Alice->>Bob: Hello"
        self.assertEqual(
            rewrite_flowchart_direction(sequence, MermaidDirection.TB),
            sequence,
        )

    def test_density_options_match_kroki_mermaid_names(self):
        self.assertEqual(density_options(MermaidDensity.STANDARD), {})
        self.assertEqual(
            density_options(MermaidDensity.COMPACT),
            {
                "flowchart_node-spacing": "30",
                "flowchart_rank-spacing": "35",
                "flowchart_wrapping-width": "160",
            },
        )
        self.assertEqual(
            density_options(MermaidDensity.SPACIOUS),
            {
                "flowchart_node-spacing": "70",
                "flowchart_rank-spacing": "80",
                "flowchart_wrapping-width": "240",
            },
        )


if __name__ == "__main__":
    unittest.main()
