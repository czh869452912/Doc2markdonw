from __future__ import annotations

import hashlib
import hmac
import shutil
import uuid
from pathlib import Path

import redis
from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from rq import Queue
from rq.job import Job

from .converter import (
    OutputFormat,
    validate_mermaid_density,
    validate_mermaid_direction,
    validate_mermaid_format,
    validate_mermaid_layout,
    validate_output_format,
)
from .jobs import run_conversion_job
from .settings import Settings, get_settings
from .sessions import COOKIE_NAME, SessionIdentity, resolve_session, set_session_cookie


settings = get_settings()
app = FastAPI(title="Markdown Convert", version="1.0.0")


def get_queue() -> Queue:
    connection = redis.from_url(settings.redis_url)
    return Queue(settings.queue_name, connection=connection)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/formats")
def formats() -> dict:
    return {"formats": [item.value for item in OutputFormat]}


@app.get("/api/session")
def get_session(request: Request, response: Response) -> dict:
    identity = _resolve_request_session(request, response)
    return {"session_id": identity.fingerprint}


@app.post("/api/jobs")
async def create_job(
    request: Request,
    response: Response,
    output_format: str = Form("docx"),
    markdown_text: str = Form(""),
    render_mermaid: bool = Form(True),
    mermaid_layout: str = Form("elk"),
    mermaid_format: str | None = Form(None),
    mermaid_direction: str = Form("source"),
    mermaid_density: str = Form("standard"),
    pdf_engine: str = Form("xelatex"),
    file: UploadFile | None = File(None),
    reference_docx: UploadFile | None = File(None),
) -> dict:
    identity = _resolve_request_session(request, response)
    selected_format = _validate_format_or_400(output_format)
    selected_mermaid_format = _validate_or_400(
        mermaid_format or settings.mermaid_output_format,
        validate_mermaid_format,
    )
    selected_direction = _validate_or_400(mermaid_direction, validate_mermaid_direction)
    selected_density = _validate_or_400(mermaid_density, validate_mermaid_density)
    selected_layout = _validate_or_400(mermaid_layout, validate_mermaid_layout)
    markdown = await _read_markdown(markdown_text, file, settings)
    job_id = str(uuid.uuid4())
    job_dir = settings.data_dir / "jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "source.md").write_text(markdown, encoding="utf-8")

    reference_path = None
    if reference_docx and reference_docx.filename:
        if not reference_docx.filename.lower().endswith(".docx"):
            raise HTTPException(status_code=400, detail="reference_docx must be a .docx file")
        reference_path = job_dir / "reference.docx"
        with reference_path.open("wb") as handle:
            shutil.copyfileobj(reference_docx.file, handle)

    queue = get_queue()
    _enqueue_conversion_job(
        queue,
        job_id=job_id,
        job_dir=str(job_dir),
        owner_hash=identity.owner_hash,
        options={
            "output_format": selected_format.value,
            "render_mermaid": render_mermaid,
            "mermaid_layout": selected_layout,
            "mermaid_format": selected_mermaid_format.value,
            "mermaid_direction": selected_direction.value,
            "mermaid_density": selected_density.value,
            "reference_docx": str(reference_path) if reference_path else None,
            "pdf_engine": pdf_engine,
        },
    )

    return {
        "job_id": job_id,
        "status": "queued",
        "status_url": f"api/jobs/{job_id}",
    }


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, request: Request, response: Response) -> dict:
    identity = _resolve_request_session(request, response)
    job = _fetch_owned_job_or_404(job_id, identity.owner_hash)
    status = job.get_status(refresh=True)
    response = {
        "job_id": job.id,
        "status": status,
        "download_url": None,
        "error": None,
    }
    if status == "finished":
        response["download_url"] = f"api/jobs/{job.id}/download"
        response["result"] = job.result
    elif status == "failed":
        response["error"] = job.exc_info
    return response


@app.get("/api/jobs/{job_id}/download")
def download_job(job_id: str, request: Request, response: Response) -> FileResponse:
    identity = _resolve_request_session(request, response)
    job = _fetch_owned_job_or_404(job_id, identity.owner_hash)
    if job.get_status(refresh=True) != "finished" or not isinstance(job.result, dict):
        raise HTTPException(status_code=409, detail="Job is not finished")

    output_path = Path(job.result["output_path"]).resolve()
    jobs_root = (settings.data_dir / "jobs").resolve()
    if jobs_root not in output_path.parents:
        raise HTTPException(status_code=500, detail="Invalid output path")
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Output file is missing")

    return FileResponse(
        output_path,
        filename=job.result.get("filename", output_path.name),
        media_type="application/octet-stream",
    )


async def _read_markdown(markdown_text: str, file: UploadFile | None, current_settings: Settings) -> str:
    if file and file.filename:
        content = await file.read()
        if len(content) > current_settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="Uploaded Markdown file is too large")
        return content.decode("utf-8")

    if markdown_text.strip():
        encoded = markdown_text.encode("utf-8")
        if len(encoded) > current_settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="Markdown text is too large")
        return markdown_text

    raise HTTPException(status_code=400, detail="Provide markdown_text or upload a Markdown file")


def _validate_format_or_400(value: str) -> OutputFormat:
    try:
        return validate_output_format(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _validate_or_400(value: str, validator):
    try:
        return validator(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _resolve_request_session(request: Request, response: Response) -> SessionIdentity:
    identity = resolve_session(request.cookies.get(COOKIE_NAME))
    if identity.is_new:
        set_session_cookie(response, identity, secure=settings.cookie_secure)
    return identity


def _enqueue_conversion_job(
    queue: Queue,
    job_id: str,
    job_dir: str,
    options: dict,
    owner_hash: str,
) -> Job:
    return queue.enqueue(
        run_conversion_job,
        job_id,
        job_dir,
        options,
        job_id=job_id,
        result_ttl=86400,
        failure_ttl=604800,
        job_timeout="30m",
        meta={"owner_session_hash": owner_hash},
    )


def _fetch_owned_job_or_404(job_id: str, owner_hash: str) -> Job:
    try:
        job = Job.fetch(job_id, connection=get_queue().connection)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    stored_owner = job.meta.get("owner_session_hash")
    if not isinstance(stored_owner, str) or not hmac.compare_digest(stored_owner, owner_hash):
        raise HTTPException(status_code=404, detail="Job not found")
    return job


static_dir = Path(__file__).parent / "static"


@app.middleware("http")
async def prevent_stale_ui(request: Request, call_next):
    response = await call_next(request)
    if request.url.path in {"/", "/index.html", "/app.js", "/styles.css", "/api/session"}:
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
def index():
    html = (static_dir / "index.html").read_text(encoding="utf-8")
    for filename in ("app.js", "styles.css"):
        version = hashlib.sha256((static_dir / filename).read_bytes()).hexdigest()[:16]
        html = html.replace(f'"{filename}"', f'"{filename}?v={version}"')
    return HTMLResponse(html)


app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
