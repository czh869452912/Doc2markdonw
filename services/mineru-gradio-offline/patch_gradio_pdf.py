from __future__ import annotations

from importlib import metadata
from pathlib import Path


EXPECTED_GRADIO_PDF_VERSION = "0.0.24"
WORKER_REMOTE = (
    "https://cdn.jsdelivr.net/gh/freddyaboulton/"
    "gradio-pdf@main/pdf.worker.min.mjs"
)
CMAP_REMOTE = (
    "https://huggingface.co/datasets/freddyaboulton/"
    "bucket/resolve/main/cmaps/"
)
WORKER_LOCAL = "./gradio_api/file=/opt/mineru-ui-assets/pdf.worker.min.mjs"
CMAP_LOCAL = "./gradio_api/file=/opt/mineru-ui-assets/cmaps/"


def patch_bundle(bundle: Path) -> None:
    content = bundle.read_text(encoding="utf-8")
    for remote in (WORKER_REMOTE, CMAP_REMOTE):
        if content.count(remote) != 1:
            raise RuntimeError(f"Expected {remote!r} exactly once")
    content = content.replace(WORKER_REMOTE, WORKER_LOCAL)
    content = content.replace(CMAP_REMOTE, CMAP_LOCAL)
    bundle.write_text(content, encoding="utf-8")


def installed_bundle() -> Path:
    installed_version = metadata.version("gradio-pdf")
    if installed_version != EXPECTED_GRADIO_PDF_VERSION:
        raise RuntimeError(
            f"Expected gradio-pdf {EXPECTED_GRADIO_PDF_VERSION}, got "
            f"{installed_version}"
        )
    distribution = metadata.distribution("gradio-pdf")
    root = Path(distribution.locate_file(""))
    bundle = root / "gradio_pdf" / "templates" / "component" / "index.js"
    if not bundle.is_file():
        raise RuntimeError(f"Missing gradio-pdf bundle: {bundle}")
    return bundle


if __name__ == "__main__":
    patch_bundle(installed_bundle())
