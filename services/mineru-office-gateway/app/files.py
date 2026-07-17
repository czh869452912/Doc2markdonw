from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import PurePath


LEGACY_OFFICE = frozenset({"doc", "ppt", "xls"})
OOXML_OFFICE = frozenset({"docx", "pptx", "xlsx"})
PDF_EXTENSIONS = frozenset({"pdf"})
IMAGE_EXTENSIONS = frozenset(
    {"png", "jpg", "jpeg", "gif", "bmp", "tiff", "webp", "jp2"}
)
OLE_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")


class BatchKind(str, Enum):
    OFFICE = "office"
    PASSTHROUGH = "passthrough"


@dataclass(frozen=True)
class ClassifiedFile:
    filename: str
    extension: str
    kind: BatchKind
    native_supported: bool


def classify_file(filename: str, prefix: bytes) -> ClassifiedFile:
    extension = PurePath(filename).suffix.lower().lstrip(".")
    if extension in LEGACY_OFFICE:
        if not prefix.startswith(OLE_SIGNATURE):
            raise ValueError(f"{filename}: Office signature does not match extension")
        return ClassifiedFile(filename, extension, BatchKind.OFFICE, False)
    if extension in OOXML_OFFICE:
        if not prefix.startswith(b"PK"):
            raise ValueError(f"{filename}: OOXML signature does not match extension")
        return ClassifiedFile(filename, extension, BatchKind.OFFICE, True)
    if extension in PDF_EXTENSIONS:
        if not prefix.startswith(b"%PDF"):
            raise ValueError(f"{filename}: PDF signature does not match extension")
        return ClassifiedFile(filename, extension, BatchKind.PASSTHROUGH, False)
    if extension in IMAGE_EXTENSIONS:
        return ClassifiedFile(filename, extension, BatchKind.PASSTHROUGH, False)
    raise ValueError(f"Unsupported file extension: {extension or '<none>'}")


def resolve_batch_mode(
    files: list[ClassifiedFile], requested_mode: str | None, default_mode: str
) -> str:
    kinds = {item.kind for item in files}
    if len(kinds) != 1:
        raise ValueError("Mixed Office and PDF/image batches are not supported")
    if BatchKind.PASSTHROUGH in kinds:
        return "passthrough"
    mode = (requested_mode or default_mode).strip().lower()
    if mode not in {"pdf_ocr", "native"}:
        raise ValueError("office_mode must be pdf_ocr or native")
    if mode == "native" and any(not item.native_supported for item in files):
        raise ValueError("office_mode=native is unavailable for legacy Office files")
    return mode
