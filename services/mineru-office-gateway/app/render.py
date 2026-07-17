from __future__ import annotations

import subprocess
from pathlib import Path


class OfficeRenderError(RuntimeError):
    pass


class OfficeRenderTimeout(OfficeRenderError):
    pass


def render_to_pdf(
    source: Path, request_root: Path, binary: str, timeout_seconds: int
) -> Path:
    output_dir = request_root / "rendered"
    profile_dir = request_root / "libreoffice-profile"
    output_dir.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)
    command = [
        binary,
        f"-env:UserInstallation={profile_dir.resolve().as_uri()}",
        "--headless",
        "--nologo",
        "--nodefault",
        "--nofirststartwizard",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_dir),
        str(source),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise OfficeRenderTimeout(
            f"LibreOffice exceeded {timeout_seconds} seconds"
        ) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[-1000:]
        raise OfficeRenderError(
            f"LibreOffice exited with {completed.returncode}: {detail}"
        )
    pdf_path = output_dir / f"{source.stem}.pdf"
    if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
        raise OfficeRenderError("LibreOffice did not produce a non-empty PDF")
    if pdf_path.read_bytes()[:4] != b"%PDF":
        raise OfficeRenderError("LibreOffice output is not a PDF")
    return pdf_path
