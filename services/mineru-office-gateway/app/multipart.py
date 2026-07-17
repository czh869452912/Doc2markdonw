from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

from starlette.datastructures import FormData, Headers
from starlette.formparsers import MultiPartException, MultiPartParser


CHUNK_SIZE = 1024 * 1024


class UploadLimitError(ValueError):
    pass


class _UploadLimitExceeded(MultiPartException):
    pass


class BoundedMultiPartParser(MultiPartParser):
    def __init__(
        self,
        headers: Headers,
        stream: AsyncGenerator[bytes, None],
        *,
        max_files: int,
        max_file_bytes: int,
    ) -> None:
        super().__init__(headers, stream, max_files=max_files)
        self.max_file_bytes = max_file_bytes
        self._current_file_bytes = 0

    def on_part_begin(self) -> None:
        super().on_part_begin()
        self._current_file_bytes = 0

    def on_headers_finished(self) -> None:
        try:
            super().on_headers_finished()
        except MultiPartException as exc:
            if exc.message.startswith("Too many files"):
                raise _UploadLimitExceeded(exc.message) from exc
            raise

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        if self._current_part.file is not None:
            self._current_file_bytes += end - start
            if self._current_file_bytes > self.max_file_bytes:
                filename = self._current_part.file.filename or "upload"
                raise _UploadLimitExceeded(
                    f"{filename} exceeds {self.max_file_bytes} bytes"
                )
        super().on_part_data(data, start, end)


async def parse_multipart(
    headers: Headers,
    stream: AsyncGenerator[bytes, None],
    *,
    max_files: int,
    max_file_bytes: int,
) -> FormData:
    parser = BoundedMultiPartParser(
        headers,
        stream,
        max_files=max_files,
        max_file_bytes=max_file_bytes,
    )
    try:
        return await parser.parse()
    except _UploadLimitExceeded as exc:
        raise UploadLimitError(exc.message) from exc
    except MultiPartException as exc:
        raise ValueError(exc.message) from exc


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
