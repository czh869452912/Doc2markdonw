from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


VALID_MODES = frozenset({"pdf_ocr", "native"})


@dataclass(frozen=True)
class Settings:
    upstream_url: str
    default_mode: str
    office_parse_method: str
    office_backend: str
    max_file_bytes: int
    max_files: int
    convert_timeout_seconds: int
    max_concurrent_conversions: int
    tmp_dir: Path
    extra_font_dir: Path | None
    libreoffice_binary: str
    upstream_connect_timeout_seconds: int = 10
    upstream_read_timeout_seconds: int = 3600
    upstream_write_timeout_seconds: int = 300
    upstream_pool_timeout_seconds: int = 30
    upstream_health_timeout_seconds: int = 5


def _positive_int(name: str, default: str) -> int:
    value = int(os.getenv(name, default))
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def get_settings() -> Settings:
    default_mode = os.getenv("OFFICE_DEFAULT_MODE", "pdf_ocr").strip().lower()
    if default_mode not in VALID_MODES:
        raise ValueError("OFFICE_DEFAULT_MODE must be pdf_ocr or native")
    extra_fonts = os.getenv("OFFICE_EXTRA_FONT_DIR", "").strip()
    return Settings(
        upstream_url=os.getenv(
            "MINERU_UPSTREAM_URL", "http://mineru-router:8002"
        ).rstrip("/"),
        default_mode=default_mode,
        office_parse_method=os.getenv("OFFICE_PARSE_METHOD", "ocr"),
        office_backend=os.getenv("OFFICE_BACKEND", "pipeline"),
        max_file_bytes=_positive_int("OFFICE_MAX_FILE_BYTES", "104857600"),
        max_files=_positive_int("OFFICE_MAX_FILES_PER_REQUEST", "10"),
        convert_timeout_seconds=_positive_int(
            "OFFICE_CONVERT_TIMEOUT_SECONDS", "300"
        ),
        max_concurrent_conversions=_positive_int(
            "OFFICE_MAX_CONCURRENT_CONVERSIONS", "1"
        ),
        tmp_dir=Path(os.getenv("OFFICE_TMP_DIR", "/tmp/mineru-office")),
        extra_font_dir=Path(extra_fonts) if extra_fonts else None,
        libreoffice_binary=os.getenv("OFFICE_LIBREOFFICE_BINARY", "libreoffice"),
        upstream_connect_timeout_seconds=_positive_int(
            "OFFICE_UPSTREAM_CONNECT_TIMEOUT_SECONDS", "10"
        ),
        upstream_read_timeout_seconds=_positive_int(
            "OFFICE_UPSTREAM_READ_TIMEOUT_SECONDS", "3600"
        ),
        upstream_write_timeout_seconds=_positive_int(
            "OFFICE_UPSTREAM_WRITE_TIMEOUT_SECONDS", "300"
        ),
        upstream_pool_timeout_seconds=_positive_int(
            "OFFICE_UPSTREAM_POOL_TIMEOUT_SECONDS", "30"
        ),
        upstream_health_timeout_seconds=_positive_int(
            "OFFICE_UPSTREAM_HEALTH_TIMEOUT_SECONDS", "5"
        ),
    )
