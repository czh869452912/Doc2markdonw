# MinerU Office Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an offline `mineru-office-gateway` that accepts MinerU-compatible API requests, renders Office files to PDF with LibreOffice, and submits the PDFs to the unchanged MinerU Router for OCR.

**Architecture:** A new FastAPI service owns multipart classification, bounded temporary storage, LibreOffice execution, and request forwarding. Nginx routes `/mineru/` to this service; non-Office requests pass through unchanged, while Office requests default to PDF+OCR and retain the upstream MinerU task ID.

**Tech Stack:** Python 3.12, FastAPI, httpx, LibreOffice Writer/Impress/Calc, Docker Compose, Nginx, `unittest`

---

## File Map

- `services/mineru-office-gateway/app/settings.py`: immutable environment configuration.
- `services/mineru-office-gateway/app/files.py`: file signatures, Office mode selection, and batch validation.
- `services/mineru-office-gateway/app/render.py`: isolated LibreOffice subprocess execution.
- `services/mineru-office-gateway/app/multipart.py`: bounded upload copying and upstream multipart reconstruction.
- `services/mineru-office-gateway/app/upstream.py`: streaming MinerU Router client and response filtering.
- `services/mineru-office-gateway/app/main.py`: FastAPI routes and error mapping.
- `services/mineru-office-gateway/tests/`: focused unit and API contract tests.
- `services/mineru-office-gateway/Dockerfile`: CPU-only LibreOffice runtime.
- `deploy/ragflow-mineru/docker-compose.office-gateway.yml`: private service definition.
- Existing packaging, deployment, gateway, verification, and documentation files: include and expose the service.

### Task 1: Scaffold Configuration

**Files:**
- Create: `services/mineru-office-gateway/requirements.txt`
- Create: `services/mineru-office-gateway/app/__init__.py`
- Create: `services/mineru-office-gateway/app/settings.py`
- Create: `services/mineru-office-gateway/tests/__init__.py`
- Create: `services/mineru-office-gateway/tests/test_settings.py`

- [ ] **Step 1: Write the failing settings tests**

```python
import os
import unittest
from unittest.mock import patch

from app.settings import get_settings


class SettingsTests(unittest.TestCase):
    def test_defaults_match_deployment_contract(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = get_settings()
        self.assertEqual(settings.upstream_url, "http://mineru-router:8002")
        self.assertEqual(settings.default_mode, "pdf_ocr")
        self.assertEqual(settings.office_parse_method, "ocr")
        self.assertEqual(settings.office_backend, "pipeline")
        self.assertEqual(settings.max_file_bytes, 104857600)
        self.assertEqual(settings.max_files, 10)
        self.assertEqual(settings.convert_timeout_seconds, 300)
        self.assertEqual(settings.max_concurrent_conversions, 1)

    def test_invalid_default_mode_fails_at_startup(self):
        with patch.dict(os.environ, {"OFFICE_DEFAULT_MODE": "guess"}, clear=True):
            with self.assertRaisesRegex(ValueError, "OFFICE_DEFAULT_MODE"):
                get_settings()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd services/mineru-office-gateway && python -m unittest tests.test_settings -v`

Expected: FAIL because `app.settings` does not exist.

- [ ] **Step 3: Add pinned runtime dependencies**

```text
fastapi==0.115.6
uvicorn[standard]==0.34.0
python-multipart==0.0.20
httpx==0.28.1
```

- [ ] **Step 4: Implement `Settings` and `get_settings`**

```python
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
    )
```

- [ ] **Step 5: Run the settings tests**

Run: `cd services/mineru-office-gateway && python -m unittest tests.test_settings -v`

Expected: 2 tests PASS.

- [ ] **Step 6: Commit the scaffold**

```bash
git add services/mineru-office-gateway
git commit -m "feat: scaffold MinerU Office gateway"
```

### Task 2: Classify Inputs And Select Office Mode

**Files:**
- Create: `services/mineru-office-gateway/app/files.py`
- Create: `services/mineru-office-gateway/tests/test_files.py`

- [ ] **Step 1: Write failing classification tests**

```python
import unittest

from app.files import BatchKind, classify_file, resolve_batch_mode


class FileClassificationTests(unittest.TestCase):
    def test_classifies_legacy_and_ooxml_office(self):
        legacy = classify_file("report.doc", bytes.fromhex("D0CF11E0A1B11AE1"))
        modern = classify_file("report.docx", b"PK\x03\x04")
        self.assertEqual(legacy.kind, BatchKind.OFFICE)
        self.assertFalse(legacy.native_supported)
        self.assertEqual(modern.kind, BatchKind.OFFICE)
        self.assertTrue(modern.native_supported)

    def test_rejects_extension_signature_mismatch(self):
        with self.assertRaisesRegex(ValueError, "signature"):
            classify_file("report.docx", b"%PDF-1.7")

    def test_rejects_mixed_office_and_pdf_batch(self):
        office = classify_file("report.docx", b"PK\x03\x04")
        pdf = classify_file("scan.pdf", b"%PDF-1.7")
        with self.assertRaisesRegex(ValueError, "Mixed"):
            resolve_batch_mode([office, pdf], None, "pdf_ocr")

    def test_native_is_rejected_for_legacy_office(self):
        legacy = classify_file("report.doc", bytes.fromhex("D0CF11E0A1B11AE1"))
        with self.assertRaisesRegex(ValueError, "native"):
            resolve_batch_mode([legacy], "native", "pdf_ocr")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd services/mineru-office-gateway && python -m unittest tests.test_files -v`

Expected: FAIL because `app.files` does not exist.

- [ ] **Step 3: Implement deterministic classification**

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import PurePath


LEGACY_OFFICE = frozenset({"doc", "ppt", "xls"})
OOXML_OFFICE = frozenset({"docx", "pptx", "xlsx"})
PDF_EXTENSIONS = frozenset({"pdf"})
IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "gif", "bmp", "tiff", "webp", "jp2"})
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
```

- [ ] **Step 4: Run classification tests**

Run: `cd services/mineru-office-gateway && python -m unittest tests.test_files -v`

Expected: 4 tests PASS.

- [ ] **Step 5: Commit classification**

```bash
git add services/mineru-office-gateway/app/files.py services/mineru-office-gateway/tests/test_files.py
git commit -m "feat: classify Office gateway uploads"
```

### Task 3: Render Office Files With Isolated LibreOffice Profiles

**Files:**
- Create: `services/mineru-office-gateway/app/render.py`
- Create: `services/mineru-office-gateway/tests/test_render.py`

- [ ] **Step 1: Write failing renderer tests**

```python
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.render import OfficeRenderError, OfficeRenderTimeout, render_to_pdf


class RendererTests(unittest.TestCase):
    def test_render_returns_nonempty_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.docx"
            source.write_bytes(b"PK\x03\x04")

            def fake_run(command, **kwargs):
                output_dir = Path(command[command.index("--outdir") + 1])
                (output_dir / "input.pdf").write_bytes(b"%PDF-1.7\nfixture")
                return subprocess.CompletedProcess(command, 0, "converted", "")

            with patch("app.render.subprocess.run", side_effect=fake_run):
                result = render_to_pdf(source, root, "libreoffice", 30)
            self.assertEqual(result.name, "input.pdf")

    def test_timeout_has_stable_error_type(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.docx"
            source.write_bytes(b"PK\x03\x04")
            with patch(
                "app.render.subprocess.run",
                side_effect=subprocess.TimeoutExpired("libreoffice", 1),
            ):
                with self.assertRaises(OfficeRenderTimeout):
                    render_to_pdf(source, Path(directory), "libreoffice", 1)

    def test_missing_pdf_is_render_error(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.docx"
            source.write_bytes(b"PK\x03\x04")
            completed = subprocess.CompletedProcess([], 0, "", "")
            with patch("app.render.subprocess.run", return_value=completed):
                with self.assertRaises(OfficeRenderError):
                    render_to_pdf(source, Path(directory), "libreoffice", 30)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd services/mineru-office-gateway && python -m unittest tests.test_render -v`

Expected: FAIL because `app.render` does not exist.

- [ ] **Step 3: Implement the renderer**

```python
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
    if not pdf_path.read_bytes()[:4] == b"%PDF":
        raise OfficeRenderError("LibreOffice output is not a PDF")
    return pdf_path
```

- [ ] **Step 4: Run renderer tests**

Run: `cd services/mineru-office-gateway && python -m unittest tests.test_render -v`

Expected: 3 tests PASS.

- [ ] **Step 5: Commit the renderer**

```bash
git add services/mineru-office-gateway/app/render.py services/mineru-office-gateway/tests/test_render.py
git commit -m "feat: render Office uploads to PDF"
```

### Task 4: Prepare Bounded Multipart Requests

**Files:**
- Create: `services/mineru-office-gateway/app/multipart.py`
- Create: `services/mineru-office-gateway/tests/test_multipart.py`

- [ ] **Step 1: Write failing multipart tests**

```python
import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.multipart import UploadLimitError, copy_upload, office_fields


class MultipartTests(unittest.TestCase):
    def test_copy_upload_enforces_limit_while_streaming(self):
        upload = SimpleNamespace(file=io.BytesIO(b"123456"))
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(UploadLimitError):
                asyncio.run(copy_upload(upload, Path(directory) / "x.docx", 5))

    def test_office_fields_strip_gateway_field_and_override_backend(self):
        fields = [("backend", "hybrid-engine"), ("office_mode", "pdf_ocr"), ("return_md", "true")]
        result = office_fields(fields, parse_method="ocr", backend="pipeline")
        self.assertEqual(
            result,
            [("return_md", "true"), ("parse_method", "ocr"), ("backend", "pipeline")],
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd services/mineru-office-gateway && python -m unittest tests.test_multipart -v`

Expected: FAIL because `app.multipart` does not exist.

- [ ] **Step 3: Implement bounded copying and field rewriting**

```python
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
                    f"{getattr(upload, 'filename', destination.name)} exceeds {max_bytes} bytes"
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
```

- [ ] **Step 4: Run multipart tests**

Run: `cd services/mineru-office-gateway && python -m unittest tests.test_multipart -v`

Expected: 2 tests PASS.

- [ ] **Step 5: Commit multipart helpers**

```bash
git add services/mineru-office-gateway/app/multipart.py services/mineru-office-gateway/tests/test_multipart.py
git commit -m "feat: prepare bounded Office gateway uploads"
```

### Task 5: Stream Requests To MinerU Router

**Files:**
- Create: `services/mineru-office-gateway/app/upstream.py`
- Create: `services/mineru-office-gateway/tests/test_upstream.py`

- [ ] **Step 1: Write a failing upstream response test**

```python
import asyncio
import unittest

import httpx

from app.upstream import send_upstream


class UpstreamTests(unittest.TestCase):
    def test_preserves_status_body_and_safe_headers(self):
        async def run():
            transport = httpx.MockTransport(
                lambda request: httpx.Response(
                    202,
                    json={"task_id": "abc"},
                    headers={"content-type": "application/json", "connection": "close"},
                )
            )
            async with httpx.AsyncClient(transport=transport) as client:
                response = await send_upstream(
                    client,
                    "http://mineru-router:8002/tasks",
                    "POST",
                    [("return_md", "true")],
                    [],
                )
                body = b"".join([chunk async for chunk in response.body_iterator])
                await response.background()
                return response, body

        response, body = asyncio.run(run())
        self.assertEqual(response.status_code, 202)
        self.assertEqual(body, b'{"task_id":"abc"}')
        self.assertNotIn("connection", response.headers)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd services/mineru-office-gateway && python -m unittest tests.test_upstream -v`

Expected: FAIL because `app.upstream` does not exist.

- [ ] **Step 3: Implement the streaming upstream adapter**

```python
from __future__ import annotations

from collections.abc import BinaryIO

import httpx
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask


HOP_BY_HOP = frozenset(
    {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade"}
)


async def send_upstream(
    client: httpx.AsyncClient,
    url: str,
    method: str,
    fields: list[tuple[str, str]],
    files: list[tuple[str, tuple[str, BinaryIO, str]]],
) -> StreamingResponse:
    request = client.build_request(method, url, data=fields or None, files=files or None)
    upstream = await client.send(request, stream=True)

    async def body():
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
```

- [ ] **Step 4: Run upstream tests**

Run: `cd services/mineru-office-gateway && python -m unittest tests.test_upstream -v`

Expected: 1 test PASS.

- [ ] **Step 5: Commit upstream streaming**

```bash
git add services/mineru-office-gateway/app/upstream.py services/mineru-office-gateway/tests/test_upstream.py
git commit -m "feat: stream Office gateway requests to MinerU"
```

### Task 6: Implement MinerU-Compatible Routes

**Files:**
- Create: `services/mineru-office-gateway/app/main.py`
- Create: `services/mineru-office-gateway/tests/test_main.py`
- Create: `services/mineru-office-gateway/tests/docx_fixture.py`

- [ ] **Step 1: Write failing API contract tests**

Create a deterministic OOXML fixture helper so unit and integration tests do not
depend on a binary file checked into the repository:

```python
# tests/docx_fixture.py
from html import escape
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile


def minimal_docx_bytes(text: str = "Offline Office fixture") -> bytes:
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""
    relationships = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""
    document = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>
    <w:sectPr>
      <w:pgSz w:w="11906" w:h="16838"/>
      <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/>
    </w:sectPr>
  </w:body>
</w:document>
"""

    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", relationships)
        archive.writestr("word/document.xml", document)
    return output.getvalue()
```

Use `minimal_docx_bytes()` for every API test that uploads a DOCX.

Use `unittest.IsolatedAsyncioTestCase`, `httpx.ASGITransport`, a fake renderer
that writes `%PDF` bytes, and `httpx.MockTransport` for the Router. Cover these
exact assertions in `tests/test_main.py`:

```python
async def test_docx_defaults_to_pdf_ocr(self):
    response = await self.client.post(
        "/tasks",
        files=[("files", ("report.docx", b"PK\x03\x04fixture", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))],
        data={"return_md": "true"},
    )
    self.assertEqual(response.status_code, 202)
    captured = self.router_requests[-1]
    self.assertIn(b'name="parse_method"\r\n\r\nocr', captured.content)
    self.assertIn(b'filename="report.pdf"', captured.content)

async def test_native_docx_is_forwarded_without_rendering(self):
    response = await self.client.post(
        "/file_parse",
        files=[("files", ("report.docx", b"PK\x03\x04fixture", "application/octet-stream"))],
        data={"office_mode": "native"},
    )
    self.assertEqual(response.status_code, 200)
    self.assertIn(b'filename="report.docx"', self.router_requests[-1].content)

async def test_mixed_batch_returns_400(self):
    response = await self.client.post(
        "/tasks",
        files=[
            ("files", ("report.docx", b"PK\x03\x04fixture", "application/octet-stream")),
            ("files", ("scan.pdf", b"%PDF-1.7", "application/pdf")),
        ],
    )
    self.assertEqual(response.status_code, 400)
    self.assertEqual(response.json()["stage"], "classify")
```

Also assert `/health`, 413 upload limits, 422 render errors, 504 render
timeouts, Router 502 errors, GET task proxying, and request-directory cleanup.

- [ ] **Step 2: Run the API tests to verify they fail**

Run: `cd services/mineru-office-gateway && python -m unittest tests.test_main -v`

Expected: FAIL because `app.main` does not exist.

- [ ] **Step 3: Implement application lifespan and health**

Create a FastAPI lifespan that first creates `settings.tmp_dir` with
`mkdir(parents=True, exist_ok=True)`, then owns one shared `httpx.AsyncClient`,
one `asyncio.Semaphore(settings.max_concurrent_conversions)`, and immutable
settings. Implement `/health` to execute `libreoffice --version` with a
10-second timeout and call `${MINERU_UPSTREAM_URL}/health`. Return 200 only when
both checks succeed; otherwise return 503 with `gateway`, `libreoffice`, and
`mineru` fields.

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = get_settings()
    app.state.client = httpx.AsyncClient(timeout=None, follow_redirects=False)
    app.state.render_slots = asyncio.Semaphore(
        app.state.settings.max_concurrent_conversions
    )
    try:
        yield
    finally:
        await app.state.client.aclose()
```

- [ ] **Step 4: Implement POST request preparation**

Parse `await request.form()` with `multi_items()` so repeated `files` and
`lang_list` fields remain ordered. Copy every upload into a
`TemporaryDirectory(dir=settings.tmp_dir)`, classify its first 16 bytes, call
`resolve_batch_mode`, and either forward the copied source or render it under
the semaphore with `await asyncio.to_thread(render_to_pdf, ...)`.

Map errors exactly:

```python
except UploadLimitError as exc:
    return JSONResponse({"stage": "upload", "detail": str(exc)}, status_code=413)
except OfficeRenderTimeout as exc:
    return JSONResponse({"stage": "render", "detail": str(exc)}, status_code=504)
except OfficeRenderError as exc:
    return JSONResponse({"stage": "render", "detail": str(exc)}, status_code=422)
except ValueError as exc:
    return JSONResponse({"stage": "classify", "detail": str(exc)}, status_code=400)
except httpx.TimeoutException as exc:
    return JSONResponse({"stage": "upstream", "detail": str(exc)}, status_code=504)
except httpx.HTTPError as exc:
    return JSONResponse({"stage": "upstream", "detail": str(exc)}, status_code=502)
```

- [ ] **Step 5: Implement public routes and transparent task proxying**

Register POST handlers for `/file_parse` and `/tasks`. Register a generic route
for `GET` and `DELETE` beneath `/tasks/{task_path:path}` plus a final Router
proxy for `/docs`, `/openapi.json`, and other non-upload endpoints. Reject POST
paths other than the two documented conversion endpoints.

The POST handler must await `send_upstream` before leaving its temporary
directory and then close local file handles. The Router has consumed the upload
when response headers arrive, while the response body remains streamed by the
returned `StreamingResponse`.

- [ ] **Step 6: Run all service tests**

Run: `cd services/mineru-office-gateway && python -m unittest discover -s tests -v`

Expected: all settings, classification, renderer, multipart, upstream, and API
contract tests PASS.

- [ ] **Step 7: Commit the API**

```bash
git add services/mineru-office-gateway/app/main.py services/mineru-office-gateway/tests/test_main.py
git commit -m "feat: expose MinerU-compatible Office API"
```

### Task 7: Build And Harden The LibreOffice Image

**Files:**
- Create: `services/mineru-office-gateway/Dockerfile`
- Create: `services/mineru-office-gateway/.dockerignore`
- Create: `services/mineru-office-gateway/tests/test_image_contract.py`

- [ ] **Step 1: Write a failing Dockerfile contract test**

```python
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ImageContractTests(unittest.TestCase):
    def test_image_contains_all_office_apps_and_nonroot_runtime(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        for package in ("libreoffice-writer", "libreoffice-impress", "libreoffice-calc"):
            self.assertIn(package, dockerfile)
        self.assertIn("USER office", dockerfile)
        self.assertIn("HEALTHCHECK", dockerfile)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the contract test to verify it fails**

Run: `cd services/mineru-office-gateway && python -m unittest tests.test_image_contract -v`

Expected: FAIL because `Dockerfile` does not exist.

- [ ] **Step 3: Add the hardened Dockerfile**

```dockerfile
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp/office-home

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        fontconfig \
        fonts-dejavu-core \
        fonts-liberation2 \
        fonts-noto-core \
        fonts-noto-cjk \
        libreoffice-calc \
        libreoffice-impress \
        libreoffice-writer \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 office \
    && mkdir -p /app /tmp/mineru-office /tmp/office-home \
    && chown -R office:office /app /tmp/mineru-office /tmp/office-home

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY app /app/app
USER office
EXPOSE 8081
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8081/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8081"]
```

Use `.dockerignore` containing `.git`, `__pycache__`, `*.pyc`, `tests`, and
local virtual environments.

- [ ] **Step 4: Run unit and image contract tests**

Run: `cd services/mineru-office-gateway && python -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 5: Build and smoke-test the image**

Run: `docker build -t mineru-office-gateway:test services/mineru-office-gateway`

Expected: build succeeds.

Run: `docker run --rm --entrypoint libreoffice mineru-office-gateway:test --version`

Expected: prints a LibreOffice version and exits 0.

- [ ] **Step 6: Commit the image**

```bash
git add services/mineru-office-gateway/Dockerfile services/mineru-office-gateway/.dockerignore services/mineru-office-gateway/tests/test_image_contract.py
git commit -m "build: package LibreOffice gateway image"
```

### Task 8: Add Compose And Public Gateway Routing

**Files:**
- Create: `deploy/ragflow-mineru/docker-compose.office-gateway.yml`
- Create: `deploy/ragflow-mineru/tests/test_office_gateway_deployment.py`
- Modify: `deploy/ragflow-mineru/docker-compose.gateway.yml`
- Modify: `deploy/ragflow-mineru/gateway/nginx.conf.template`
- Modify: `deploy/ragflow-mineru/env/airgap.env.example`

- [ ] **Step 1: Write failing deployment contract tests**

Create assertions that the new Compose file uses profile `mineru-office`, has
no host `ports`, depends on `mineru-router`, defines every environment variable
from the design, mounts a tmpfs, drops capabilities, and sets
`no-new-privileges`. Assert Nginx proxies `/mineru/` to
`mineru-office-gateway:8081` and the public gateway depends on the Office
gateway.

```python
def test_nginx_routes_mineru_through_office_gateway(self):
    nginx = read(STACK / "gateway" / "nginx.conf.template")
    self.assertIn("proxy_pass http://mineru-office-gateway:8081/;", nginx)
    self.assertNotIn("proxy_pass http://mineru-router:8002/;", nginx)
```

- [ ] **Step 2: Run the deployment test to verify it fails**

Run: `python -m unittest deploy/ragflow-mineru/tests/test_office_gateway_deployment.py -v`

Expected: FAIL because the Compose file and route do not exist.

- [ ] **Step 3: Add the Compose service**

Define `mineru-office-gateway` with image
`${MINERU_OFFICE_GATEWAY_IMAGE:-mineru-office-gateway:latest}`, profile
`mineru-office`, environment values from `.env`, `depends_on: mineru-router`,
network `ragflow`, `tmpfs: /tmp`, `read_only: true`, `cap_drop: [ALL]`,
`security_opt: [no-new-privileges:true]`, and no `ports` block.

- [ ] **Step 4: Route `/mineru/` through the Office gateway**

Replace only the MinerU proxy target. Preserve `/mineru` to `/mineru/`
redirect, HTTP/1.1, upload size, and timeouts. Update gateway `depends_on` from
`mineru-router` to `mineru-office-gateway`.

- [ ] **Step 5: Add environment defaults**

Add the exact environment contract from the design plus:

```text
MINERU_OFFICE_GATEWAY_IMAGE=mineru-office-gateway:latest
```

- [ ] **Step 6: Run deployment contract tests**

Run: `python -m unittest deploy/ragflow-mineru/tests/test_office_gateway_deployment.py -v`

Expected: all tests PASS.

- [ ] **Step 7: Commit deployment routing**

```bash
git add deploy/ragflow-mineru/docker-compose.office-gateway.yml deploy/ragflow-mineru/docker-compose.gateway.yml deploy/ragflow-mineru/gateway/nginx.conf.template deploy/ragflow-mineru/env/airgap.env.example deploy/ragflow-mineru/tests/test_office_gateway_deployment.py
git commit -m "feat: route MinerU through Office gateway"
```

### Task 9: Package And Deploy The Fifth Compose File

**Files:**
- Modify: `deploy/ragflow-mineru/scripts/package-windows.ps1`
- Modify: `deploy/ragflow-mineru/scripts/deploy-linux.sh`
- Modify: `deploy/ragflow-mineru/tests/test_deploy_lifecycle.py`
- Modify: `deploy/ragflow-mineru/tests/test_office_gateway_deployment.py`

- [ ] **Step 1: Extend failing lifecycle expectations**

Add `docker-compose.office-gateway.yml` to `COMPOSE_FILES` in
`test_deploy_lifecycle.py`. Add static assertions that packaging copies the
Compose file and service source, builds `MINERU_OFFICE_GATEWAY_IMAGE`, records
it in `manifest.json`, and includes `mineru-office` in required profiles.

- [ ] **Step 2: Run lifecycle and deployment tests to verify they fail**

Run: `python -m unittest deploy/ragflow-mineru/tests/test_deploy_lifecycle.py deploy/ragflow-mineru/tests/test_office_gateway_deployment.py -v`

Expected: FAIL because scripts still know only four Compose files.

- [ ] **Step 3: Extend Windows packaging**

Add parameters:

```powershell
[string]$MineruOfficeGatewayImage = "mineru-office-gateway:latest",
[switch]$SkipOfficeGatewayBuild,
```

Copy `docker-compose.office-gateway.yml` into the package Docker directory and
copy `services/mineru-office-gateway` to `office-gateway-source`. Unless skipped,
build the image from that source. Set `MINERU_OFFICE_GATEWAY_IMAGE`, add
`mineru-office` to required profiles, add the Compose file to
`Get-ComposeImages`, and record `mineruOfficeGatewayImage` in the manifest.

- [ ] **Step 4: Extend Linux deployment and lifecycle composition**

Add `docker-compose.office-gateway.yml` to every required, generated v1, and
runtime Compose list. Do not add it to the GPU-service set. Validate the source
file before copying the package.

- [ ] **Step 5: Run lifecycle and deployment tests**

Run: `python -m unittest deploy/ragflow-mineru/tests/test_deploy_lifecycle.py deploy/ragflow-mineru/tests/test_office_gateway_deployment.py -v`

Expected: all tests PASS for Compose v1 and v2 stubs.

- [ ] **Step 6: Validate shell syntax**

Run: `bash -n deploy/ragflow-mineru/scripts/deploy-linux.sh`

Expected: exit 0 with no output.

- [ ] **Step 7: Commit packaging lifecycle changes**

```bash
git add deploy/ragflow-mineru/scripts/package-windows.ps1 deploy/ragflow-mineru/scripts/deploy-linux.sh deploy/ragflow-mineru/tests/test_deploy_lifecycle.py deploy/ragflow-mineru/tests/test_office_gateway_deployment.py
git commit -m "build: package MinerU Office gateway"
```

### Task 10: Verify, Document, And Exercise Real Office Conversion

**Files:**
- Modify: `deploy/ragflow-mineru/scripts/verify-linux.sh`
- Modify: `deploy/ragflow-mineru/README.md`
- Modify: `README.md`
- Modify: `deploy/ragflow-mineru/tests/test_office_gateway_deployment.py`

- [ ] **Step 1: Add failing verification and documentation tests**

Assert verification checks `mineru-office-gateway`, calls its health endpoint
through `/mineru/health`, prints LibreOffice version, and tails gateway logs.
Assert README documents `pdf_ocr`, `office_mode=native`, supported formats,
mixed-batch rejection, `return_original_file` semantics, fidelity limitations,
and direct DOC/DOCX curl examples.

- [ ] **Step 2: Run the deployment test to verify it fails**

Run: `python -m unittest deploy/ragflow-mineru/tests/test_office_gateway_deployment.py -v`

Expected: FAIL on missing verification and documentation text.

- [ ] **Step 3: Extend Linux verification**

Add:

```bash
echo "Checking Office gateway and LibreOffice..."
docker exec mineru-office-gateway libreoffice --version
curl -fsS "http://127.0.0.1:${PUBLIC_PORT}/mineru/health" >/dev/null
docker logs --tail 40 mineru-office-gateway || true
```

Keep the existing Router model-path check because the Office gateway does not
own models.

- [ ] **Step 4: Document API examples and limitations**

Add synchronous and asynchronous examples using `sample.docx`, plus:

```bash
curl -X POST http://<server>:<PUBLIC_PORT>/mineru/file_parse \
  -F "files=@sample.docx" \
  -F "office_mode=pdf_ocr" \
  -F "return_md=true" \
  -F "response_format_zip=true" \
  -o result.zip
```

State that `pdf_ocr` is the default and no extra field is required for normal
clients.

- [ ] **Step 5: Run all repository tests**

Run: `python -m unittest discover -s services/mineru-office-gateway/tests -v`

Expected: all Office gateway tests PASS.

Run: `python -m unittest discover -s deploy/ragflow-mineru/tests -v`

Expected: all deployment tests PASS.

Run: `python -m unittest discover -s services/md-convert/tests -v`

Expected: all Markdown Convert tests PASS.

- [ ] **Step 6: Run a real local integration smoke test**

Build `mineru-office-gateway:test`, start it with a stub HTTP Router that records
the multipart request, generate the input with
`tests.docx_fixture.minimal_docx_bytes()`, and assert the stub receives a
non-empty `%PDF` upload named with the original stem. Repeat with
`office_mode=native` and assert the DOCX bytes pass unchanged.

Expected: both requests return the stub's 200/202 response and temporary
request directories are empty after completion.

- [ ] **Step 7: Validate rendered Compose**

Run from a prepared RAGFlow Docker directory:

```bash
docker compose --env-file .env \
  -f docker-compose.yml \
  -f docker-compose.mineru.yml \
  -f docker-compose.office-gateway.yml \
  -f docker-compose.md-convert.yml \
  -f docker-compose.gateway.yml config
```

Expected: `mineru-office-gateway` has no published port, gateway targets it,
and only the public gateway publishes `PUBLIC_PORT`.

- [ ] **Step 8: Commit verification and documentation**

```bash
git add README.md deploy/ragflow-mineru/README.md deploy/ragflow-mineru/scripts/verify-linux.sh deploy/ragflow-mineru/tests/test_office_gateway_deployment.py
git commit -m "docs: verify offline Office conversion"
```

- [ ] **Step 9: Review the completed branch**

Run: `git status --short`

Expected: no output.

Run: `git log --oneline --max-count=10`

Expected: shows the focused commits from this plan above the design commit.
