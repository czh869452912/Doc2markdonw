from __future__ import annotations

import re
import struct
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol


MERMAID_FILTER_PATH = Path(__file__).parent / "filters" / "mermaid_size.lua"


class OutputFormat(str, Enum):
    DOCX = "docx"
    DOC = "doc"
    PDF = "pdf"
    HTML = "html"
    ODT = "odt"
    EPUB = "epub"


class MermaidFormat(str, Enum):
    AUTO = "auto"
    PNG = "png"
    SVG = "svg"


class MermaidDirection(str, Enum):
    SOURCE = "source"
    TB = "tb"
    LR = "lr"


class MermaidDensity(str, Enum):
    COMPACT = "compact"
    STANDARD = "standard"
    SPACIOUS = "spacious"


class MermaidRenderError(RuntimeError):
    pass


class ConversionCommandError(RuntimeError):
    def __init__(self, executable: str, exit_code: int, stderr: str):
        detail = stderr.strip()[:4000] or "No stderr output"
        super().__init__(f"{executable} failed with exit code {exit_code}: {detail}")


@dataclass(frozen=True)
class ConversionRequest:
    output_format: OutputFormat
    render_mermaid: bool = True
    mermaid_layout: str = "elk"
    reference_docx: Path | None = None
    pdf_engine: str = "xelatex"
    mermaid_format: MermaidFormat = MermaidFormat.AUTO
    mermaid_direction: MermaidDirection = MermaidDirection.SOURCE
    mermaid_density: MermaidDensity = MermaidDensity.STANDARD


@dataclass(frozen=True)
class ConversionPlan:
    commands: list[list[str]]
    final_output: Path


@dataclass(frozen=True)
class RenderedDiagram:
    path: Path
    image_format: MermaidFormat
    width_px: float
    height_px: float


@dataclass(frozen=True)
class PageBox:
    width_inches: float
    height_inches: float


@dataclass(frozen=True)
class ImageDimension:
    axis: str
    inches: float


class MermaidRenderer(Protocol):
    def render(
        self,
        diagram: str,
        output_dir: Path,
        layout: str,
        density: MermaidDensity,
    ) -> RenderedDiagram:
        """Render a Mermaid diagram and return its path and dimensions."""


class KrokiMermaidRenderer:
    def __init__(
        self,
        base_url: str,
        output_format: str | MermaidFormat = MermaidFormat.SVG,
        timeout_seconds: int = 60,
    ):
        self.base_url = base_url.rstrip("/")
        self.output_format = (
            output_format
            if isinstance(output_format, MermaidFormat)
            else validate_mermaid_format(output_format)
        )
        if self.output_format is MermaidFormat.AUTO:
            raise ValueError("Kroki renderer requires png or svg output")
        self.timeout_seconds = timeout_seconds

    def render(
        self,
        diagram: str,
        output_dir: Path,
        layout: str,
        density: MermaidDensity = MermaidDensity.STANDARD,
    ) -> RenderedDiagram:
        import requests

        output_dir.mkdir(parents=True, exist_ok=True)
        suffix = self.output_format.value
        index = len(list(output_dir.glob(f"diagram-*.{suffix}"))) + 1
        target = output_dir / f"diagram-{index}.{suffix}"
        url = f"{self.base_url}/mermaid/{suffix}"
        params = {"layout": layout}
        params.update(density_options(density))
        try:
            response = requests.post(
                url,
                params=params,
                data=diagram.encode("utf-8"),
                headers={"Content-Type": "text/plain; charset=utf-8"},
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise MermaidRenderError(f"Kroki request failed: {exc}") from exc
        if response.status_code >= 400:
            excerpt = response.text[:1000]
            raise MermaidRenderError(
                f"Kroki returned HTTP {response.status_code}: {excerpt}"
            )
        expected_type = (
            "image/png"
            if self.output_format is MermaidFormat.PNG
            else "image/svg+xml"
        )
        content_type = (
            response.headers.get("Content-Type", "")
            .split(";", 1)[0]
            .strip()
            .lower()
        )
        if content_type != expected_type:
            raise MermaidRenderError(
                f"Kroki returned Content-Type '{content_type}', expected '{expected_type}'"
            )
        if not response.content:
            raise MermaidRenderError("Kroki returned an empty image")
        if self.output_format is MermaidFormat.PNG:
            width, height = read_png_dimensions(response.content)
        else:
            width, height = read_svg_dimensions(response.content)
        target.write_bytes(response.content)
        return RenderedDiagram(target, self.output_format, width, height)


MERMAID_BLOCK_RE = re.compile(
    r"(^|\n)```[ \t]*mermaid[^\n]*\n(?P<diagram>.*?)(?:\n```)",
    re.DOTALL,
)
FLOWCHART_DIRECTION_RE = re.compile(
    r"^(?P<declaration>[ \t]*(?:flowchart|graph)[ \t]+)(?:TB|TD|BT|RL|LR)(?=\s|$)",
    re.IGNORECASE | re.MULTILINE,
)


def validate_output_format(value: str) -> OutputFormat:
    try:
        return OutputFormat(value.lower().strip())
    except ValueError as exc:
        supported = ", ".join(item.value for item in OutputFormat)
        raise ValueError(f"Unsupported output format '{value}'. Supported: {supported}") from exc


def validate_mermaid_format(value: str) -> MermaidFormat:
    return _validate_enum(value, MermaidFormat, "Mermaid format")


def validate_mermaid_direction(value: str) -> MermaidDirection:
    return _validate_enum(value, MermaidDirection, "Mermaid direction")


def validate_mermaid_density(value: str) -> MermaidDensity:
    return _validate_enum(value, MermaidDensity, "Mermaid density")


def validate_mermaid_layout(value: str) -> str:
    normalized = value.lower().strip()
    if normalized not in {"elk", "dagre"}:
        raise ValueError(
            f"Unsupported Mermaid layout '{value}'. Supported: elk, dagre"
        )
    return normalized


def _validate_enum(value: str, enum_type: type[Enum], label: str):
    try:
        return enum_type(value.lower().strip())
    except ValueError as exc:
        supported = ", ".join(item.value for item in enum_type)
        raise ValueError(f"Unsupported {label} '{value}'. Supported: {supported}") from exc


def resolve_mermaid_format(request: ConversionRequest) -> MermaidFormat:
    if request.mermaid_format is not MermaidFormat.AUTO:
        return request.mermaid_format
    if request.output_format in {OutputFormat.DOCX, OutputFormat.DOC, OutputFormat.PDF}:
        return MermaidFormat.PNG
    return MermaidFormat.SVG


def rewrite_flowchart_direction(
    diagram: str,
    direction: MermaidDirection,
) -> str:
    if direction is MermaidDirection.SOURCE:
        return diagram
    replacement = "TB" if direction is MermaidDirection.TB else "LR"
    return FLOWCHART_DIRECTION_RE.sub(
        lambda match: f"{match.group('declaration')}{replacement}",
        diagram,
        count=1,
    )


def density_options(density: MermaidDensity) -> dict[str, str]:
    if density is MermaidDensity.COMPACT:
        values = (30, 35, 160)
    elif density is MermaidDensity.SPACIOUS:
        values = (70, 80, 240)
    else:
        return {}
    node_spacing, rank_spacing, wrapping_width = values
    return {
        "flowchart_node-spacing": str(node_spacing),
        "flowchart_rank-spacing": str(rank_spacing),
        "flowchart_wrapping-width": str(wrapping_width),
    }


def read_png_dimensions(content: bytes) -> tuple[float, float]:
    if len(content) < 24 or content[:8] != b"\x89PNG\r\n\x1a\n" or content[12:16] != b"IHDR":
        raise MermaidRenderError("Invalid PNG image data")
    width, height = struct.unpack(">II", content[16:24])
    if width <= 0 or height <= 0:
        raise MermaidRenderError("Invalid PNG dimensions")
    return float(width), float(height)


def read_svg_dimensions(content: bytes) -> tuple[float, float]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise MermaidRenderError("Invalid SVG image data") from exc
    if root.tag.rsplit("}", 1)[-1].lower() != "svg":
        raise MermaidRenderError("Invalid SVG root element")

    view_box = root.attrib.get("viewBox", "").replace(",", " ").split()
    if len(view_box) == 4:
        try:
            width, height = float(view_box[2]), float(view_box[3])
        except ValueError:
            width = height = 0
        if width > 0 and height > 0:
            return width, height

    width = _svg_length_to_px(root.attrib.get("width"))
    height = _svg_length_to_px(root.attrib.get("height"))
    if width is None or height is None or width <= 0 or height <= 0:
        raise MermaidRenderError("SVG dimensions are missing or invalid")
    return width, height


def _svg_length_to_px(value: str | None) -> float | None:
    if not value:
        return None
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*(px|pt|in|cm|mm)?\s*", value)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2) or "px"
    factors = {
        "px": 1.0,
        "pt": 96 / 72,
        "in": 96.0,
        "cm": 96 / 2.54,
        "mm": 96 / 25.4,
    }
    return number * factors[unit]


def read_docx_page_box(reference_docx: Path | None) -> PageBox:
    fallback = PageBox(6.3, 8.5)
    if reference_docx is None:
        return fallback
    try:
        with zipfile.ZipFile(reference_docx) as archive:
            root = ET.fromstring(archive.read("word/document.xml"))
        namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        sections = root.findall(f".//{{{namespace}}}sectPr")
        if not sections:
            return fallback
        page_size = sections[-1].find(f"{{{namespace}}}pgSz")
        margins = sections[-1].find(f"{{{namespace}}}pgMar")
        if page_size is None or margins is None:
            return fallback

        def twips(element: ET.Element, name: str) -> float:
            return float(element.attrib[f"{{{namespace}}}{name}"]) / 1440

        width = twips(page_size, "w") - twips(margins, "left") - twips(margins, "right")
        height = twips(page_size, "h") - twips(margins, "top") - twips(margins, "bottom")
        if width <= 0 or height <= 0:
            return fallback
        return PageBox(width, height)
    except (KeyError, OSError, ValueError, ET.ParseError, zipfile.BadZipFile):
        return fallback


def calculate_display_dimension(
    image: RenderedDiagram,
    page_box: PageBox,
) -> ImageDimension:
    ppi = 150 if image.image_format is MermaidFormat.PNG else 96
    natural_width = image.width_px / ppi
    natural_height = image.height_px / ppi
    max_width = page_box.width_inches * 0.9
    max_height = page_box.height_inches * 0.9
    scale = min(1.0, max_width / natural_width, max_height / natural_height)
    display_width = natural_width * scale
    display_height = natural_height * scale
    if image.width_px / image.height_px >= max_width / max_height:
        return ImageDimension("width", display_width)
    return ImageDimension("height", display_height)


def preprocess_markdown(
    markdown: str,
    work_dir: Path,
    renderer: MermaidRenderer,
    mermaid_layout: str = "elk",
    render_mermaid: bool = True,
    mermaid_direction: MermaidDirection = MermaidDirection.SOURCE,
    mermaid_density: MermaidDensity = MermaidDensity.STANDARD,
    page_box: PageBox = PageBox(6.3, 8.5),
) -> str:
    if not render_mermaid:
        return markdown

    diagrams_dir = work_dir
    diagrams_dir.mkdir(parents=True, exist_ok=True)

    def replace(match: re.Match[str]) -> str:
        diagram = match.group("diagram").strip()
        diagram = rewrite_flowchart_direction(diagram, mermaid_direction)
        rendered = renderer.render(
            diagram,
            diagrams_dir,
            mermaid_layout,
            mermaid_density,
        )
        relative_path = rendered.path.relative_to(work_dir).as_posix()
        dimension = calculate_display_dimension(rendered, page_box)
        inches = f"{dimension.inches:.3f}".rstrip("0").rstrip(".")
        marker = f"md-convert-mermaid:{dimension.axis}={inches}in"
        return f'{match.group(1)}![Mermaid diagram]({relative_path} "{marker}")'

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
        mermaid_direction=request.mermaid_direction,
        mermaid_density=request.mermaid_density,
        page_box=read_docx_page_box(request.reference_docx),
    )
    input_path.write_text(processed, encoding="utf-8")

    plan = build_conversion_plan(input_path, work_dir, request)
    for command in plan.commands:
        try:
            subprocess.run(
                command,
                cwd=work_dir,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise ConversionCommandError(
                command[0],
                exc.returncode,
                exc.stderr or "",
            ) from exc

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
        "--lua-filter",
        str(MERMAID_FILTER_PATH),
    ]
    if request.output_format is OutputFormat.HTML:
        command.extend(["--embed-resources"])
    if request.output_format is OutputFormat.PDF:
        command.extend(["--pdf-engine", request.pdf_engine])
    if request.reference_docx and output_path.suffix.lower() == ".docx":
        command.extend(["--reference-doc", str(request.reference_docx)])
    command.extend(["-o", str(output_path)])
    return command
