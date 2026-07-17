from __future__ import annotations

from typing import BinaryIO

import httpx
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask


HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
)


async def send_upstream(
    client: httpx.AsyncClient,
    url: str,
    method: str,
    fields: list[tuple[str, str]],
    files: list[tuple[str, tuple[str, BinaryIO, str]]],
) -> StreamingResponse:
    if files:
        multipart = [
            (name, (None, value)) for name, value in fields
        ] + files
        request = client.build_request(method, url, files=multipart)
    else:
        request = client.build_request(method, url, data=dict(fields) or None)
    upstream = await client.send(request, stream=True)

    async def body():
        if upstream.is_stream_consumed:
            yield upstream.content
        else:
            async for chunk in upstream.aiter_raw():
                yield chunk

    headers = {
        name: value
        for name, value in upstream.headers.items()
        if name.lower() not in HOP_BY_HOP and name.lower() != "content-length"
    }
    return StreamingResponse(
        body(),
        status_code=upstream.status_code,
        headers=headers,
        background=BackgroundTask(upstream.aclose),
    )
