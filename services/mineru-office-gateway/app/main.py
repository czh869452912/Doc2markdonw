from __future__ import annotations

import asyncio
import subprocess
import tempfile
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile

from .files import BatchKind, classify_file, resolve_batch_mode
from .multipart import UploadLimitError, copy_upload, office_fields, parse_multipart
from .render import OfficeRenderError, OfficeRenderTimeout, render_to_pdf
from .settings import Settings, get_settings
from .upstream import send_upstream


Renderer = Callable[[Path, Path, str, int], Path]


def create_app(
    settings: Settings | None = None,
    upstream_transport: httpx.AsyncBaseTransport | None = None,
    renderer: Renderer = render_to_pdf,
) -> FastAPI:
    configured_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        configured_settings.tmp_dir.mkdir(parents=True, exist_ok=True)
        application.state.settings = configured_settings
        application.state.client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=configured_settings.upstream_connect_timeout_seconds,
                read=configured_settings.upstream_read_timeout_seconds,
                write=configured_settings.upstream_write_timeout_seconds,
                pool=configured_settings.upstream_pool_timeout_seconds,
            ),
            follow_redirects=False,
            transport=upstream_transport,
        )
        application.state.render_slots = asyncio.Semaphore(
            configured_settings.max_concurrent_conversions
        )
        application.state.renderer = renderer
        try:
            yield
        finally:
            await application.state.client.aclose()

    application = FastAPI(
        title="MinerU Office Gateway",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @application.get("/health")
    async def health(request: Request):
        current = request.app.state.settings
        libreoffice_status = "error"
        mineru_status = "error"
        mineru_health: dict[str, Any] = {}
        try:
            completed = await asyncio.to_thread(
                subprocess.run,
                [current.libreoffice_binary, "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if completed.returncode == 0:
                libreoffice_status = "ok"
        except (OSError, subprocess.SubprocessError):
            pass

        try:
            upstream = await request.app.state.client.get(
                f"{current.upstream_url}/health",
                timeout=current.upstream_health_timeout_seconds,
            )
            payload = upstream.json()
            if isinstance(payload, dict):
                mineru_health = payload
            if (
                200 <= upstream.status_code < 300
                and mineru_health.get("status") == "healthy"
            ):
                mineru_status = "ok"
        except (httpx.HTTPError, ValueError):
            pass

        healthy = libreoffice_status == "ok" and mineru_status == "ok"
        return JSONResponse(
            {
                **mineru_health,
                "status": "healthy" if healthy else "unhealthy",
                "gateway": "ok",
                "libreoffice": libreoffice_status,
                "mineru": mineru_status,
            },
            status_code=200 if healthy else 503,
        )

    async def submit(request: Request):
        current: Settings = request.app.state.settings
        uploads: list[tuple[str, UploadFile]] = []
        try:
            form = await parse_multipart(
                request.headers,
                request.stream(),
                max_files=current.max_files,
                max_file_bytes=current.max_file_bytes,
            )
            items = list(form.multi_items())
            uploads = [
                (name, value)
                for name, value in items
                if isinstance(value, UploadFile)
            ]
            fields = [
                (name, str(value))
                for name, value in items
                if not isinstance(value, UploadFile)
            ]
            if not uploads:
                raise ValueError("At least one file is required")
            if len(uploads) > current.max_files:
                raise UploadLimitError(
                    f"Request contains more than {current.max_files} files"
                )

            requested_mode = next(
                (value for name, value in fields if name == "office_mode"),
                None,
            )
            with tempfile.TemporaryDirectory(dir=current.tmp_dir) as directory:
                request_root = Path(directory)
                prepared: list[tuple[str, UploadFile, Path, Any]] = []
                for index, (field_name, upload) in enumerate(uploads):
                    filename = Path(upload.filename or f"upload-{index}").name
                    if not filename or filename in {".", ".."}:
                        raise ValueError("Every upload must have a valid filename")
                    source = request_root / "uploads" / str(index) / filename
                    await copy_upload(upload, source, current.max_file_bytes)
                    with source.open("rb") as handle:
                        classified = classify_file(filename, handle.read(16))
                    prepared.append((field_name, upload, source, classified))

                mode = resolve_batch_mode(
                    [item[3] for item in prepared],
                    requested_mode,
                    current.default_mode,
                )
                if mode == "pdf_ocr":
                    forwarded_fields = office_fields(
                        fields,
                        parse_method=current.office_parse_method,
                        backend=current.office_backend,
                    )
                else:
                    forwarded_fields = [
                        (name, value)
                        for name, value in fields
                        if name != "office_mode"
                    ]

                # Gradio submits the hidden server URL even for local backends.
                # Office preprocessing may also replace a remote backend with pipeline.
                effective_backend = next(
                    (value for name, value in reversed(forwarded_fields) if name == "backend"),
                    None,
                )
                if effective_backend in {
                    "pipeline", "vlm-engine", "hybrid-engine",
                    "vlm-auto-engine", "hybrid-auto-engine",
                }:
                    forwarded_fields = [
                        (name, value) for name, value in forwarded_fields
                        if name != "server_url"
                    ]

                handles = []
                upstream_files = []
                try:
                    for render_index, (
                        field_name,
                        upload,
                        source,
                        classified,
                    ) in enumerate(prepared):
                        forwarded = source
                        content_type = upload.content_type or "application/octet-stream"
                        if mode == "pdf_ocr" and classified.kind == BatchKind.OFFICE:
                            render_root = (
                                request_root / "conversions" / str(render_index)
                            )
                            async with request.app.state.render_slots:
                                forwarded = await asyncio.to_thread(
                                    request.app.state.renderer,
                                    source,
                                    render_root,
                                    current.libreoffice_binary,
                                    current.convert_timeout_seconds,
                                )
                            content_type = "application/pdf"
                        handle = forwarded.open("rb")
                        handles.append(handle)
                        upstream_files.append(
                            (
                                field_name,
                                (forwarded.name, handle, content_type),
                            )
                        )

                    return await send_upstream(
                        request.app.state.client,
                        _upstream_url(current, request),
                        "POST",
                        forwarded_fields,
                        upstream_files,
                    )
                finally:
                    for handle in handles:
                        handle.close()
        except UploadLimitError as exc:
            return _error("upload", exc, 413)
        except OfficeRenderTimeout as exc:
            return _error("render", exc, 504)
        except OfficeRenderError as exc:
            return _error("render", exc, 422)
        except ValueError as exc:
            return _error("classify", exc, 400)
        except httpx.TimeoutException as exc:
            return _error("upstream", exc, 504)
        except httpx.HTTPError as exc:
            return _error("upstream", exc, 502)
        finally:
            for _, upload in uploads:
                await upload.close()

    application.add_api_route("/file_parse", submit, methods=["POST"])
    application.add_api_route("/tasks", submit, methods=["POST"])

    @application.api_route(
        "/{proxy_path:path}",
        methods=["GET", "DELETE", "POST", "PUT", "PATCH", "OPTIONS"],
    )
    async def proxy(request: Request, proxy_path: str):
        if request.method not in {"GET", "DELETE"}:
            return JSONResponse(
                {"stage": "route", "detail": "Method is not supported"},
                status_code=405,
            )
        current: Settings = request.app.state.settings
        try:
            return await send_upstream(
                request.app.state.client,
                _upstream_url(current, request),
                request.method,
                [],
                [],
            )
        except httpx.TimeoutException as exc:
            return _error("upstream", exc, 504)
        except httpx.HTTPError as exc:
            return _error("upstream", exc, 502)

    return application


def _upstream_url(settings: Settings, request: Request) -> str:
    url = f"{settings.upstream_url}{request.url.path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"
    return url


def _error(stage: str, exc: Exception, status_code: int) -> JSONResponse:
    return JSONResponse(
        {"stage": stage, "detail": str(exc)},
        status_code=status_code,
    )


app = create_app()
