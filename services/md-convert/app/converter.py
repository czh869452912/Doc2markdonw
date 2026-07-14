from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol


class OutputFormat(str, Enum):
    DOCX = "docx"
    DOC = "doc"
    PDF = "pdf"
    HTML = "html"
    ODT = "odt"
    EPUB = "epub"


@dataclass(frozen=True)
class ConversionRequest:
    output_format: OutputFormat
    render_mermaid: bool = True
    mermaid_layout: str = "elk"
    reference_docx: Path | None = None
    pdf_engine: str = "xelatex"


@dataclass(frozen=True)
class ConversionPlan:
    commands: list[list[str]]
    final_output: Path


class MermaidRenderer(Protocol):
    def render(self, diagram: str, output_dir: Path, layout: str) -> Path:
        """Render a Mermaid diagram and return a path relative to output_dir."""


class KrokiMermaidRenderer:
    def __init__(self, base_url: str, output_format: str = "svg", timeout_seconds: int = 60):
        self.base_url = base_url.rstrip("/")
        self.output_format = output_format
        self.timeout_seconds = timeout_seconds

    def render(self, diagram: str, output_dir: Path, layout: str) -> Path:
        import requests

        output_dir.mkdir(parents=True, exist_ok=True)
        suffix = self.output_format.strip(".").lower()
        index = len(list(output_dir.glob(f"diagram-*.{suffix}"))) + 1
        target = output_dir / f"diagram-{index}.{suffix}"
        url = f"{self.base_url}/mermaid/{suffix}"
        response = requests.post(
            url,
            params={"layout": layout},
            data=diagram.encode("utf-8"),
            headers={"Content-Type": "text/plain; charset=utf-8"},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        target.write_bytes(response.content)
        return target


MERMAID_BLOCK_RE = re.compile(
    r"(^|\n)```[ \t]*mermaid[^\n]*\n(?P<diagram>.*?)(?:\n```)",
    re.DOTALL,
)


def validate_output_format(value: str) -> OutputFormat:
    try:
        return OutputFormat(value.lower().strip())
    except ValueError as exc:
        supported = ", ".join(item.value for item in OutputFormat)
        raise ValueError(f"Unsupported output format '{value}'. Supported: {supported}") from exc


def preprocess_markdown(
    markdown: str,
    work_dir: Path,
    renderer: MermaidRenderer,
    mermaid_layout: str = "elk",
    render_mermaid: bool = True,
) -> str:
    if not render_mermaid:
        return markdown

    diagrams_dir = work_dir
    diagrams_dir.mkdir(parents=True, exist_ok=True)

    def replace(match: re.Match[str]) -> str:
        diagram = match.group("diagram").strip()
        image_path = renderer.render(diagram, diagrams_dir, mermaid_layout)
        relative_path = image_path.relative_to(work_dir).as_posix()
        return f"{match.group(1)}![Mermaid diagram]({relative_path})"

    return MERMAID_BLOCK_RE.sub(replace, markdown)


def build_conversion_plan(input_path: Path, work_dir: Path, request: ConversionRequest) -> ConversionPlan:
    output_format = request.output_format
    if output_format is OutputFormat.DOC:
        intermediate = work_dir / "intermediate.docx"
        final_output = work_dir / "result.doc"
        return ConversionPlan(
            commands=[
                _pandoc_command(input_path, intermediate, work_dir, request),
                [
                    "libreoffice",
                    "--headless",
                    "--convert-to",
                    "doc",
                    "--outdir",
                    str(work_dir),
                    str(intermediate),
                ],
            ],
            final_output=final_output,
        )

    final_output = work_dir / f"result.{output_format.value}"
    return ConversionPlan(
        commands=[_pandoc_command(input_path, final_output, work_dir, request)],
        final_output=final_output,
    )


def run_conversion(
    markdown: str,
    work_dir: Path,
    request: ConversionRequest,
    renderer: MermaidRenderer,
) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    input_path = work_dir / "input.md"
    processed = preprocess_markdown(
        markdown,
        work_dir=work_dir,
        renderer=renderer,
        mermaid_layout=request.mermaid_layout,
        render_mermaid=request.render_mermaid,
    )
    input_path.write_text(processed, encoding="utf-8")

    plan = build_conversion_plan(input_path, work_dir, request)
    for command in plan.commands:
        subprocess.run(command, cwd=work_dir, check=True)

    if not plan.final_output.exists():
        raise FileNotFoundError(f"Expected conversion output was not created: {plan.final_output}")
    return plan.final_output


def _pandoc_command(
    input_path: Path,
    output_path: Path,
    work_dir: Path,
    request: ConversionRequest,
) -> list[str]:
    command = [
        "pandoc",
        str(input_path),
        "--from",
        "gfm+tex_math_dollars",
        "--standalone",
        "--resource-path",
        str(work_dir),
    ]
    if request.output_format is OutputFormat.HTML:
        command.extend(["--embed-resources"])
    if request.output_format is OutputFormat.PDF:
        command.extend(["--pdf-engine", request.pdf_engine])
    if request.reference_docx and output_path.suffix.lower() == ".docx":
        command.extend(["--reference-doc", str(request.reference_docx)])
    command.extend(["-o", str(output_path)])
    return command
