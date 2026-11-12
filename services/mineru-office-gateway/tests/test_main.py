import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from starlette.datastructures import FormData

from app.main import create_app
from app.render import OfficeRenderError, OfficeRenderTimeout
from app.settings import Settings
from tests.docx_fixture import minimal_docx_bytes


class MainApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.temporary_directory.name) / "requests"
        self.router_requests = []
        self.router_error = None
        self.router_health = {
            "status": "healthy",
            "protocol_version": 2,
            "max_concurrent_requests": 2,
            "processing_window_size": 4,
            "version": "3.4.2",
            "servers": [{"server_id": "worker-0", "healthy": True}],
        }
        self.router_health_status = 200

        async def router(request):
            if self.router_error is not None:
                raise self.router_error
            await request.aread()
            self.router_requests.append(request)
            if request.url.path == "/health":
                return httpx.Response(self.router_health_status, json=self.router_health)
            status = 202 if request.url.path == "/tasks" else 200
            return httpx.Response(status, json={"task_id": "upstream-task"})

        def renderer(source, request_root, binary, timeout_seconds):
            output = request_root / "rendered" / f"{source.stem}.pdf"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"%PDF-1.7\noffline fixture")
            return output

        self.settings = Settings(
            upstream_url="http://mineru-router:8002",
            default_mode="pdf_ocr",
            office_parse_method="ocr",
            office_backend="pipeline",
            max_file_bytes=104857600,
            max_files=10,
            convert_timeout_seconds=300,
            max_concurrent_conversions=1,
            tmp_dir=self.tmp_dir,
            extra_font_dir=None,
            libreoffice_binary="libreoffice",
        )
        self.app = create_app(
            settings=self.settings,
            upstream_transport=httpx.MockTransport(router),
            renderer=renderer,
        )
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://gateway",
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.lifespan.__aexit__(None, None, None)
        self.temporary_directory.cleanup()

    async def test_docx_defaults_to_pdf_ocr_and_cleans_request_directory(self):
        response = await self.client.post(
            "/tasks",
            files=[
                (
                    "files",
                    (
                        "report.docx",
                        minimal_docx_bytes(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                )
            ],
            data={"return_md": "true"},
        )

        self.assertEqual(response.status_code, 202)
        captured = self.router_requests[-1].content
        self.assertIn(b'name="parse_method"\r\n\r\nocr', captured)
        self.assertIn(b'name="backend"\r\n\r\npipeline', captured)
        self.assertIn(b'filename="report.pdf"', captured)
        self.assertEqual(list(self.tmp_dir.iterdir()), [])

    async def test_pdf_local_backends_discard_hidden_gradio_server_url(self):
        for backend in ("pipeline", "vlm-engine", "hybrid-engine"):
            with self.subTest(backend=backend):
                response = await self.client.post(
                    "/tasks",
                    files=[("files", ("scan.pdf", b"%PDF-1.7", "application/pdf"))],
                    data={"backend": backend, "server_url": "http://localhost:30000"},
                )
                self.assertEqual(response.status_code, 202)
                captured = self.router_requests[-1].content
                self.assertNotIn(b'name="server_url"', captured)
                self.assertIn(backend.encode(), captured)

    async def test_remote_backend_keeps_its_server_url(self):
        response = await self.client.post(
            "/tasks",
            files=[("files", ("scan.pdf", b"%PDF-1.7", "application/pdf"))],
            data={"backend": "vlm-http-client", "server_url": "http://model:30000"},
        )
        self.assertEqual(response.status_code, 202)
        self.assertIn(b'name="server_url"', self.router_requests[-1].content)
        self.assertIn(b"http://model:30000", self.router_requests[-1].content)

    async def test_office_pipeline_override_discards_remote_server_url(self):
        response = await self.client.post(
            "/tasks",
            files=[("files", ("report.docx", minimal_docx_bytes(), "application/octet-stream"))],
            data={"backend": "vlm-http-client", "server_url": "http://localhost:30000"},
        )
        self.assertEqual(response.status_code, 202)
        captured = self.router_requests[-1].content
        self.assertNotIn(b'name="server_url"', captured)
        self.assertIn(b'name="backend"\r\n\r\npipeline', captured)

    async def test_native_docx_is_forwarded_without_rendering(self):
        response = await self.client.post(
            "/file_parse",
            files=[
                (
                    "files",
                    (
                        "report.docx",
                        minimal_docx_bytes(),
                        "application/octet-stream",
                    ),
                )
            ],
            data={"office_mode": "native"},
        )

        self.assertEqual(response.status_code, 200)
        captured = self.router_requests[-1].content
        self.assertIn(b'filename="report.docx"', captured)
        self.assertNotIn(b'name="office_mode"', captured)

    async def test_same_stem_office_files_use_distinct_render_directories(self):
        def distinguishing_renderer(source, render_root, binary, timeout_seconds):
            output = render_root / "rendered" / f"{source.stem}.pdf"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"%PDF-" + source.parent.name.encode())
            return output

        self.app.state.renderer = distinguishing_renderer
        response = await self.client.post(
            "/tasks",
            files=[
                (
                    "files",
                    (
                        "report.docx",
                        minimal_docx_bytes(),
                        "application/octet-stream",
                    ),
                ),
                (
                    "files",
                    (
                        "report.docx",
                        minimal_docx_bytes(),
                        "application/octet-stream",
                    ),
                ),
            ],
        )

        self.assertEqual(response.status_code, 202)
        captured = self.router_requests[-1].content
        self.assertEqual(captured.count(b"%PDF-0"), 1)
        self.assertEqual(captured.count(b"%PDF-1"), 1)

    async def test_mixed_batch_returns_400(self):
        response = await self.client.post(
            "/tasks",
            files=[
                ("files", ("report.docx", minimal_docx_bytes(), "application/octet-stream")),
                ("files", ("scan.pdf", b"%PDF-1.7", "application/pdf")),
            ],
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["stage"], "classify")

    async def test_upload_limit_returns_413(self):
        self.app.state.settings = replace(self.settings, max_file_bytes=4)
        response = await self.client.post(
            "/tasks",
            files=[("files", ("report.docx", minimal_docx_bytes(), "application/octet-stream"))],
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["stage"], "upload")

    async def test_submit_does_not_use_unbounded_request_form_parser(self):
        with patch(
            "starlette.requests.Request.form",
            new=AsyncMock(return_value=FormData()),
        ):
            response = await self.client.post(
                "/tasks",
                files=[
                    (
                        "files",
                        (
                            "report.docx",
                            minimal_docx_bytes(),
                            "application/octet-stream",
                        ),
                    )
                ],
            )
        self.assertEqual(response.status_code, 202)

    async def test_render_errors_have_stable_status_codes(self):
        for error, expected in (
            (OfficeRenderError("bad document"), 422),
            (OfficeRenderTimeout("too slow"), 504),
        ):
            with self.subTest(error=type(error).__name__):
                def failing_renderer(*args, current_error=error, **kwargs):
                    raise current_error

                self.app.state.renderer = failing_renderer
                response = await self.client.post(
                    "/tasks",
                    files=[("files", ("report.docx", minimal_docx_bytes(), "application/octet-stream"))],
                )
                self.assertEqual(response.status_code, expected)
                self.assertEqual(response.json()["stage"], "render")

    async def test_router_errors_return_502(self):
        self.router_error = httpx.ConnectError("router unavailable")
        response = await self.client.post(
            "/tasks",
            files=[("files", ("scan.pdf", b"%PDF-1.7", "application/pdf"))],
        )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["stage"], "upstream")

    async def test_get_task_path_and_query_are_proxied(self):
        response = await self.client.get("/tasks/upstream-task?include=markdown")
        self.assertEqual(response.status_code, 200)
        captured = self.router_requests[-1]
        self.assertEqual(captured.url.path, "/tasks/upstream-task")
        self.assertEqual(captured.url.query, b"include=markdown")

    async def test_health_checks_libreoffice_and_router(self):
        completed = subprocess.CompletedProcess(
            ["libreoffice", "--version"], 0, "LibreOffice 25.2", ""
        )
        with patch("app.main.subprocess.run", return_value=completed):
            response = await self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["gateway"], "ok")
        self.assertEqual(response.json()["libreoffice"], "ok")
        self.assertEqual(response.json()["mineru"], "ok")
        for key, value in self.router_health.items():
            self.assertEqual(response.json()[key], value)
        timeout = self.router_requests[-1].extensions["timeout"]
        self.assertEqual(timeout["connect"], 5)
        self.assertEqual(timeout["read"], 5)
        self.assertEqual(timeout["write"], 5)
        self.assertEqual(timeout["pool"], 5)

    async def test_health_does_not_mask_router_failure(self):
        completed = subprocess.CompletedProcess([], 0, "LibreOffice", "")
        for status_code, payload in (
            (200, {"status": "unhealthy", "error": "No workers"}),
            (503, {"status": "unhealthy", "error": "No workers"}),
            (503, {"status": "healthy"}),
            (200, {"status": "ok"}),
            (200, ["unexpected response"]),
        ):
            with self.subTest(status_code=status_code, payload=payload):
                self.router_health_status = status_code
                self.router_health = payload
                with patch("app.main.subprocess.run", return_value=completed):
                    response = await self.client.get("/health")
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()["status"], "unhealthy")
                self.assertEqual(response.json()["mineru"], "error")

    async def test_health_reports_libreoffice_failure_despite_healthy_router(self):
        completed = subprocess.CompletedProcess([], 1, "", "failed")
        with patch("app.main.subprocess.run", return_value=completed):
            response = await self.client.get("/health")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "unhealthy")
        self.assertEqual(response.json()["mineru"], "ok")
        self.assertEqual(response.json()["libreoffice"], "error")

    async def test_health_reports_router_connection_failure(self):
        self.router_error = httpx.ConnectError("router unavailable")
        completed = subprocess.CompletedProcess([], 0, "LibreOffice", "")
        with patch("app.main.subprocess.run", return_value=completed):
            response = await self.client.get("/health")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "unhealthy")
        self.assertEqual(response.json()["mineru"], "error")

    async def test_upstream_client_uses_bounded_timeouts(self):
        timeout = self.app.state.client.timeout
        self.assertEqual(timeout.connect, 10)
        self.assertEqual(timeout.read, 3600)
        self.assertEqual(timeout.write, 300)
        self.assertEqual(timeout.pool, 30)


if __name__ == "__main__":
    unittest.main()
