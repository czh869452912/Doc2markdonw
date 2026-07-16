from __future__ import annotations

from pathlib import Path

from .converter import (
    ConversionRequest,
    KrokiMermaidRenderer,
    MermaidDensity,
    MermaidDirection,
    OutputFormat,
    resolve_mermaid_format,
    run_conversion,
    validate_mermaid_density,
    validate_mermaid_direction,
    validate_mermaid_format,
    validate_mermaid_layout,
)
from .settings import get_settings


def run_conversion_job(job_id: str, job_dir: str, options: dict) -> dict:
    settings = get_settings()
    work_dir = Path(job_dir)
    reference_docx = options.get("reference_docx")
    mermaid_format = validate_mermaid_format(
        options.get("mermaid_format", settings.mermaid_output_format)
    )
    request = ConversionRequest(
        output_format=OutputFormat(options["output_format"]),
        render_mermaid=bool(options.get("render_mermaid", True)),
        mermaid_layout=validate_mermaid_layout(options.get("mermaid_layout", "elk")),
        reference_docx=Path(reference_docx) if reference_docx else None,
        pdf_engine=options.get("pdf_engine", "xelatex"),
        mermaid_format=mermaid_format,
        mermaid_direction=validate_mermaid_direction(
            options.get("mermaid_direction", MermaidDirection.SOURCE.value)
        ),
        mermaid_density=validate_mermaid_density(
            options.get("mermaid_density", MermaidDensity.STANDARD.value)
        ),
    )
    renderer = KrokiMermaidRenderer(
        settings.kroki_url,
        output_format=resolve_mermaid_format(request),
    )
    markdown = (work_dir / "source.md").read_text(encoding="utf-8")
    output_path = run_conversion(markdown, work_dir, request, renderer)
    return {
        "job_id": job_id,
        "output_path": str(output_path),
        "filename": output_path.name,
        "output_format": request.output_format.value,
    }
