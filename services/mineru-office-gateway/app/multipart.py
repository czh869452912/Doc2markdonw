from __future__ import annotations

import asyncio
from pathlib import Path


CHUNK_SIZE = 1024 * 1024


class UploadLimitError(ValueError):
    pass


async def copy_upload(upload, destination: Path, max_bytes: int) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with destination.open("wb") as output:
        while chunk := await asyncio.to_thread(upload.file.read, CHUNK_SIZE):
            total += len(chunk)
            if total > max_bytes:
                raise UploadLimitError(
                    f"{getattr(upload, 'filename', destination.name)} "
                    f"exceeds {max_bytes} bytes"
                )
            output.write(chunk)
    return total


def office_fields(
    fields: list[tuple[str, str]], parse_method: str, backend: str
) -> list[tuple[str, str]]:
    result = [
        (name, value)
        for name, value in fields
        if name not in {"office_mode", "parse_method", "backend"}
    ]
    result.extend((("parse_method", parse_method), ("backend", backend)))
    return result
