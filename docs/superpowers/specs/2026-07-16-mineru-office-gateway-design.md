# MinerU Office Gateway Design

## Goal

Accept legacy and OOXML Office files through a MinerU-compatible HTTP API,
render them to PDF with a separately deployed LibreOffice runtime, and submit
the PDF to the unchanged `mineru-router` for OCR. Clients and MinerU Gradio use
one public `/mineru/` API and do not need to pre-convert files.

## Decision

Implement a dedicated `mineru-office-gateway` container. Do not install
LibreOffice in the MinerU GPU image and do not modify MinerU source code.

This follows MinerU's documented modular architecture: Office rendering is an
independent preprocessing service, while MinerU remains responsible for PDF
and image parsing. A single gateway container contains the lightweight HTTP
adapter and LibreOffice for the first implementation. The renderer can later
be split into a separate worker service without changing the public API.

## Supported Inputs And Defaults

The gateway accepts the multipart forms used by MinerU `/file_parse` and
`/tasks`.

| Input | Default behavior |
| --- | --- |
| PDF and supported images | Forward unchanged |
| DOC, PPT, XLS | Render to PDF, then submit with OCR |
| DOCX, PPTX, XLSX | Render to PDF, then submit with OCR |
| DOCX, PPTX, XLSX with `office_mode=native` | Forward to MinerU's native Office parser |

`office_mode` is an optional gateway-only form field with values `pdf_ocr` and
`native`. The default is configurable and is `pdf_ocr`. The gateway removes the
field before forwarding the request. `native` is rejected for legacy DOC, PPT,
and XLS because MinerU does not support them directly.

The first version accepts batches containing only Office files or only
non-Office files. It rejects mixed Office/PDF/image batches with HTTP 400. This
avoids forcing OCR onto unrelated PDFs and preserves the upstream task ID
without introducing a second task registry. Clients can submit mixed inputs as
separate requests.

## Public API Contract

Nginx routes `/mineru/` to `mineru-office-gateway:8081`. The Router remains
private at `mineru-router:8002`.

The gateway implements:

- `GET /health` with gateway, LibreOffice, and Router readiness;
- `POST /file_parse` for synchronous conversion;
- `POST /tasks` for asynchronous MinerU task submission;
- transparent proxying for task status, result, cancellation, and other
  non-conversion Router endpoints.

For `/tasks`, Office rendering completes before the request is submitted to the
Router. The successful response is the original MinerU response and task ID.
Subsequent task requests require no gateway-side mapping.

For `pdf_ocr` requests, `return_original_file=true` refers to the PDF submitted
to MinerU, not the original Office package. Preserving and reinserting the
source Office file would require gateway task storage and ZIP response
rewriting and is outside the first version.

## Request Flow

For a non-Office request, the gateway streams the multipart body to the Router
without changing fields or filenames.

For an Office request, the gateway:

1. validates the number, extension, detected container type, and configured
   byte limit;
2. writes each upload into a request-scoped temporary directory;
3. invokes LibreOffice headlessly with a unique user profile and output
   directory;
4. validates that exactly one non-empty PDF was produced per source file;
5. submits PDFs with the original stems and `application/pdf` media type;
6. replaces `parse_method` with the configured Office value, defaulting to
   `ocr`, and replaces `backend` with the configured Office backend, defaulting
   to `pipeline`;
7. streams the upstream response back to the client;
8. deletes the request directory after the upstream upload has completed.

The gateway preserves all other supported MinerU form fields. Page ranges,
formula, table, image-analysis, response-format, and output-selection fields
continue to be interpreted by MinerU after PDF rendering.

## LibreOffice Runtime

The image is based on a slim Debian or Ubuntu release and pins LibreOffice
Writer, Impress, and Calc packages. It includes Noto CJK, Noto Core, Liberation,
DejaVu, and fontconfig. Additional licensed organization fonts may be mounted
read-only through an optional directory and are refreshed into the font cache
at container startup.

LibreOffice runs as a non-root user, with macros disabled, no host filesystem
access, a request-specific profile, and a hard timeout. The service serializes
conversions by default because concurrent LibreOffice processes are memory
intensive and profile locks are unsafe when profiles are shared.

The container requires no GPU. It uses temporary container storage by default;
no Office document is persisted after request completion.

## Configuration

The supported environment contract is:

```text
MINERU_UPSTREAM_URL=http://mineru-router:8002
OFFICE_DEFAULT_MODE=pdf_ocr
OFFICE_PARSE_METHOD=ocr
OFFICE_BACKEND=pipeline
OFFICE_MAX_FILE_BYTES=104857600
OFFICE_MAX_FILES_PER_REQUEST=10
OFFICE_CONVERT_TIMEOUT_SECONDS=300
OFFICE_MAX_CONCURRENT_CONVERSIONS=1
OFFICE_TMP_DIR=/tmp/mineru-office
OFFICE_EXTRA_FONT_DIR=
```

Compose adds health checks, a read-only root filesystem where practical,
`no-new-privileges`, dropped Linux capabilities, bounded memory and CPU, and a
tmpfs for request data. The service joins the existing private application
network and publishes no host port.

MinerU Gradio uses:

```text
--api-url http://mineru-office-gateway:8081
```

so UI and direct API conversions share identical Office behavior.

## Errors

The gateway uses stable HTTP errors with a short stage identifier:

- 400 for unsupported extensions, mixed-mode batches, invalid
  `office_mode`, or native mode on legacy Office files;
- 413 for request limits;
- 422 for a readable request that LibreOffice cannot render;
- 504 for a LibreOffice or Router timeout;
- 502 for an unavailable Router or malformed upstream response;
- 507 when temporary storage is exhausted.

Logs include a request ID, input type, byte count, render duration, PDF page
count, upstream duration, mode, and outcome. They do not include document text
or file bytes.

## Quality And Limitations

The `pdf_ocr` path optimizes visual fidelity and supports content that MinerU's
native Office parser skips on Linux, including many WMF/EMF and rich-layout
cases. It is slower and may produce OCR errors that native OOXML extraction
would avoid. `office_mode=native` remains available for clean OOXML files where
semantic structure matters more than visual rendering.

LibreOffice cannot guarantee Microsoft Office rendering parity. Password or
rights-managed documents, macros, ActiveX, embedded OLE applications, broken
packages, external linked objects, and unavailable proprietary fonts may fail
or render differently. The gateway reports these failures and does not fall
back to internet services.

## Packaging And Deployment

The Windows packaging script builds or requires a pinned
`mineru-office-gateway` image, includes it in Compose image discovery, saves it
in the offline bundle, and records its version in `manifest.json`. The default
production profiles include the gateway whenever MinerU is enabled.

The Linux deployment script installs the Compose file and starts the gateway
before exposing `/mineru/`. Existing direct `mineru-router` data and models are
unchanged. Rollback consists of routing `/mineru/` back to the Router and
disabling the Office gateway profile.

## Verification

Unit tests use a fake LibreOffice executable and stub Router to cover request
classification, multipart reconstruction, field overrides, error mapping,
timeouts, cleanup, size limits, native mode, and exact response pass-through.

Integration tests use the real image and representative fixtures:

- DOC and DOCX with text, tables, and embedded images;
- DOCX containing WMF or EMF content;
- PPT/PPTX and XLS/XLSX smoke samples;
- PDF and image pass-through;
- synchronous and asynchronous MinerU endpoints;
- task status and result proxying;
- conversion failure, timeout, mixed batch, and oversized upload cases.

Air-gap verification runs without internet access and confirms that an Office
file submitted to `/mineru/file_parse` and `/mineru/tasks` produces MinerU
output through the public gateway. It also checks that temporary source and
rendered files are deleted after success and failure.

## Future Extension

If Office rendering becomes a throughput or security bottleneck, extract
LibreOffice into an internal `office-renderer` service and keep the existing
gateway API. A gateway-owned asynchronous task registry, automatic native/OCR
quality selection, result ZIP rewriting, browser Office editing, and exact
Microsoft rendering are intentionally deferred.
