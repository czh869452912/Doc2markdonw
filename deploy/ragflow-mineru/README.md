# RAGFlow + MinerU Offline Deployment

This stack uses RAGFlow as the multi-user WebUI/API platform, MinerU as the rich
document parsing service, and a lightweight Markdown conversion service for
Markdown -> Word/PDF/HTML exports. It is designed for an intranet Linux server
with Docker, Docker Compose v2, NVIDIA driver, and nvidia-container-toolkit.

## What the package contains

- Upstream RAGFlow `docker/` files pinned to a selected tag.
- `docker-compose.mineru.yml`, which adds `mineru-router` and optional
  `mineru-gradio` services to the same Docker network.
- `docker-compose.md-convert.yml`, which adds FastAPI, RQ worker, Kroki, and
  kroki-mermaid for Markdown conversion.
- `docker-compose.gateway.yml`, which exposes a single configurable public
  port and keeps internal service ports off the host.
- Docker image archives under `images/`.
- Linux scripts to load images, install runtime files, start containers, and
  verify health.

## Windows packaging machine

Requirements:

- Docker Desktop in Linux container mode.
- Git.
- Enough disk space for pulled images and exported tar files.

Recommended command:

```powershell
.\deploy\ragflow-mineru\scripts\package-windows.ps1 -BuildMineru
```

This creates `dist\ragflow-mineru-airgap-<version>-<time>\` and a zip archive.
By default it also builds `md-convert:latest` locally and saves the Markdown
conversion, gateway, Kroki, and kroki-mermaid images into the offline bundle.

Useful options:

```powershell
# Package without rebuilding MinerU if mineru:latest already exists locally.
.\deploy\ragflow-mineru\scripts\package-windows.ps1

# Package without rebuilding md-convert if md-convert:latest already exists locally.
.\deploy\ragflow-mineru\scripts\package-windows.ps1 -SkipMdConvertBuild

# Also enable MinerU's Gradio UI in addition to RAGFlow WebUI.
.\deploy\ragflow-mineru\scripts\package-windows.ps1 -BuildMineru -ComposeProfiles "infinity,gpu,mineru,mineru-ui,md-convert,gateway"

# Apply production passwords, ports, and GPU settings from an override file.
Copy-Item .\deploy\ragflow-mineru\env\airgap.env.example .\airgap.prod.env
notepad .\airgap.prod.env
.\deploy\ragflow-mineru\scripts\package-windows.ps1 -BuildMineru -EnvOverridePath .\airgap.prod.env

# Use Elasticsearch instead of Infinity.
.\deploy\ragflow-mineru\scripts\package-windows.ps1 -BuildMineru -DocEngine elasticsearch

# Include a prepared MinerU /root directory containing mineru.json and model cache.
.\deploy\ragflow-mineru\scripts\package-windows.ps1 -BuildMineru -IncludeMineruHome -MineruHomePath D:\mineru-home
```

Before production packaging, use `-EnvOverridePath` to replace all default
passwords and set `PUBLIC_PORT`. The upstream `.env` contains defaults for
MySQL, Redis, MinIO, Elasticsearch/OpenSearch, and registration. MinerU and
Markdown conversion settings may appear both in upstream sections and at the
end of `.env`; the last value for a key is the value Docker Compose uses.

## MinerU models

The stack sets `MINERU_MODEL_SOURCE=local`, so the intranet server must already
have MinerU models inside `ragflow/docker/mineru-home`.

One practical path:

1. Build or pull `mineru:latest` on a connected staging Linux machine.
2. Run:

   ```bash
   bash scripts/download-mineru-models-linux.sh --project-dir /opt/ragflow-mineru --image mineru:latest --source modelscope
   ```

3. Copy `/opt/ragflow-mineru/ragflow/docker/mineru-home` back to the Windows
   packaging machine.
4. Package with `-IncludeMineruHome -MineruHomePath <copied-mineru-home>`.

If your organization mirrors Hugging Face or ModelScope internally, you can
also mount a prebuilt `mineru-home` directory directly on the Linux server
before starting the stack.

## Linux intranet server

Unzip or copy the package to the server, then run:

```bash
sudo bash scripts/deploy-linux.sh --package-dir /path/to/ragflow-mineru-airgap
```

The script:

1. Loads every `images/*.tar` archive with `docker load`.
2. Copies RAGFlow and MinerU compose files to `/opt/ragflow-mineru`.
3. Creates persistent runtime directories.
4. Starts the compose stack.

Verify:

```bash
bash scripts/verify-linux.sh --project-dir /opt/ragflow-mineru
```

Default endpoints:

- RAGFlow WebUI/API: `http://<server>:<PUBLIC_PORT>/`
- MinerU API: `http://<server>:<PUBLIC_PORT>/mineru/`
- Markdown Convert WebUI/API: `http://<server>:<PUBLIC_PORT>/convert/`

The default `PUBLIC_PORT` is `18080`.

## MinerU API smoke tests

Health:

```bash
curl http://<server>:<PUBLIC_PORT>/mineru/health
```

Asynchronous conversion for agents and workflow tools:

```bash
curl -X POST http://<server>:<PUBLIC_PORT>/mineru/tasks \
  -F "files=@sample.pdf" \
  -F "return_md=true"

curl http://<server>:<PUBLIC_PORT>/mineru/tasks/<task_id>
curl http://<server>:<PUBLIC_PORT>/mineru/tasks/<task_id>/result
```

Synchronous conversion:

```bash
curl -X POST http://<server>:<PUBLIC_PORT>/mineru/file_parse \
  -F "files=@sample.pdf" \
  -F "return_md=true" \
  -F "response_format_zip=true" \
  -o result.zip
```

## Markdown Convert

Open the WebUI:

```text
http://<server>:<PUBLIC_PORT>/convert/
```

API smoke test:

```bash
curl http://<server>:<PUBLIC_PORT>/convert/api/health
```

Submit Markdown -> DOCX with Mermaid rendered by Kroki and ELK layout:

```bash
curl -X POST http://<server>:<PUBLIC_PORT>/convert/api/jobs \
  -F "output_format=docx" \
  -F "render_mermaid=true" \
  -F "mermaid_layout=elk" \
  -F "file=@sample.md"
```

Poll and download:

```bash
curl http://<server>:<PUBLIC_PORT>/convert/api/jobs/<job_id>
curl -L http://<server>:<PUBLIC_PORT>/convert/api/jobs/<job_id>/download -o result.docx
```

Supported output formats:

- `docx`
- `doc`
- `pdf`
- `html`
- `odt`
- `epub`

LaTeX math is passed through Pandoc with
`gfm+tex_math_dollars+tex_math_single_backslash`. Mermaid code fences are
pre-rendered through Kroki before Pandoc runs. The default Mermaid layout is
`elk`; set `mermaid_layout=dagre` when needed.

## Operational notes

- Use RAGFlow for multi-user access, datasets, task management, and API-based
  integrations.
- Use MinerU API directly when an agent only needs PDF/Word-to-Markdown style
  conversion.
- Use Markdown Convert when the source is already Markdown and must become
  Word/PDF/HTML while preserving LaTeX formulas and Mermaid diagrams.
- For complex Word documents, convert DOCX to PDF with a controlled
  LibreOffice/OnlyOffice step if layout fidelity matters, then send the PDF to
  MinerU.
- Keep `mineru-output` if you need parsing artifacts for audits. Set
  `MINERU_DELETE_OUTPUT=1` only when storage pressure is more important.
- If GPU memory is tight, restrict visible GPUs with
  `MINERU_NVIDIA_VISIBLE_DEVICES` and `MINERU_CUDA_VISIBLE_DEVICES` in
  `ragflow/docker/.env`.
