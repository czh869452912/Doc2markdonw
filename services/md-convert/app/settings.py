from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    redis_url: str
    queue_name: str
    kroki_url: str
    mermaid_output_format: str
    max_upload_bytes: int


def get_settings() -> Settings:
    data_dir = Path(os.getenv("MD_CONVERT_DATA_DIR", "/data")).resolve()
    redis_url = os.getenv("MD_CONVERT_REDIS_URL", "").strip()
    if not redis_url:
        password = quote(os.getenv("REDIS_PASSWORD", ""), safe="")
        host = os.getenv("MD_CONVERT_REDIS_HOST", "redis")
        port = os.getenv("MD_CONVERT_REDIS_PORT", "6379")
        db = os.getenv("MD_CONVERT_REDIS_DB", "1")
        auth = f":{password}@" if password else ""
        redis_url = f"redis://{auth}{host}:{port}/{db}"

    return Settings(
        data_dir=data_dir,
        redis_url=redis_url,
        queue_name=os.getenv("MD_CONVERT_QUEUE", "md-convert"),
        kroki_url=os.getenv("KROKI_URL", "http://kroki:8000"),
        mermaid_output_format=os.getenv("MERMAID_OUTPUT_FORMAT", "svg"),
        max_upload_bytes=int(os.getenv("MD_CONVERT_MAX_UPLOAD_BYTES", "52428800")),
    )
