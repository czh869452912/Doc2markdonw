from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import redis
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from rq import Queue
from rq.job import Job

from .converter import OutputFormat, validate_output_format
from .jobs import run_conversion_job
from .settings import Settings, get_settings


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


@app.post("/api/jobs")
async def create_job(
    output_format: str = Form("docx"),
    markdown_text: str = Form(""),
    render_mermaid: bool = Form(True),
    mermaid_layout: str = Form("elk"),
    pdf_engine: str = Form("xelatex"),
    file: UploadFile | None = File(None),
    reference_docx: UploadFile | None = File(None),
) -> dict:
    selected_format = _validate_format_or_400(output_format)
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
    queue.enqueue(
        run_conversion_job,
        job_id,
        str(job_dir),
        {
            "output_format": selected_format.value,
            "render_mermaid": render_mermaid,
            "mermaid_layout": mermaid_layout,
            "reference_docx": str(reference_path) if reference_path else None,
            "pdf_engine": pdf_engine,
        },
        job_id=job_id,
        result_ttl=86400,
        failure_ttl=604800,
        job_timeout="30m",
    )

    return {
        "job_id": job_id,
        "status": "queued",
        "status_url": f"api/jobs/{job_id}",
    }


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = _fetch_job_or_404(job_id)
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
def download_job(job_id: str) -> FileResponse:
    job = _fetch_job_or_404(job_id)
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


def _fetch_job_or_404(job_id: str) -> Job:
    try:
        return Job.fetch(job_id, connection=get_queue().connection)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc


static_dir = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
