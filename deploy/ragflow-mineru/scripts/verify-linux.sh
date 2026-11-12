#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/runtime-common.sh"
PROJECT_DIR="/opt/ragflow-mineru"
PROJECT_NAME=""

usage() {
  cat <<'EOF'
Usage: bash scripts/verify-linux.sh [options]

Options:
  --project-dir PATH   Install/runtime directory. Default: /opt/ragflow-mineru
  --project-name NAME  Compose namespace (defaults to the saved runtime name).
  -h, --help           Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-dir)
      PROJECT_DIR="$2"
      shift 2
      ;;
    --project-name)
      PROJECT_NAME="${2:?--project-name requires a value}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

DOCKER_DIR="$(cd "$PROJECT_DIR/ragflow/docker" && pwd -P)"
ENV_FILE="$DOCKER_DIR/.env"

read_env() {
  read_runtime_env "$ENV_FILE" "$1" "$2"
}

profile_enabled() {
  local requested="$1"
  case ",${COMPOSE_PROFILES}," in
    *",${requested},"*) return 0 ;;
    *) return 1 ;;
  esac
}

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing .env: $ENV_FILE" >&2
  exit 1
fi

cd "$DOCKER_DIR"
resolve_compose_project_name "$DOCKER_DIR" "$PROJECT_NAME"
ROUTER_ID="$(service_container mineru-router)"
OFFICE_ID="$(service_container mineru-office-gateway)"
API_ID="$(service_container md-convert-api)"
WORKER_ID="$(service_container md-convert-worker)"
GATEWAY_ID="$(service_container gateway)"
RAGFLOW_ID="$(service_container ragflow-gpu 2>/dev/null || service_container ragflow-cpu)"

if docker inspect "$ROUTER_ID" \
  --format '{{range .Mounts}}{{println .Destination}}{{end}}' \
  | grep -Fxq '/root'; then
  echo "MinerU container must not mount /root; the mount hides image-owned models." >&2
  exit 1
fi

echo "Checking embedded MinerU model paths..."
docker exec -i "$ROUTER_ID" python3 - <<'PY'
import os

from mineru.utils.config_reader import get_local_models_dir

models_dir = get_local_models_dir()
if not isinstance(models_dir, dict):
    raise SystemExit("MinerU 'models-dir' configuration is missing or invalid")

for repo_mode in ("pipeline", "vlm"):
    model_path = models_dir.get(repo_mode)
    if not isinstance(model_path, str) or not os.path.isdir(model_path):
        raise SystemExit(
            f"Embedded MinerU {repo_mode} model directory is missing: {model_path!r}"
        )
    print(f"Embedded MinerU {repo_mode} models: {model_path}")
PY

echo "Compose services:"
docker ps \
  --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME" \
  --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'

PUBLIC_PORT="$(read_env PUBLIC_PORT 18080)"
COMPOSE_PROFILES="$(read_env COMPOSE_PROFILES '')"
VERIFY_TMP="$(mktemp -d)"
GRADIO_HTML="$VERIFY_TMP/mineru-gradio.html"
OFFICE_FIXTURE="$VERIFY_TMP/mineru-office-smoke.docx"
OFFICE_RESULT="$VERIFY_TMP/mineru-office-smoke.zip"
trap 'rm -rf -- "$VERIFY_TMP"' EXIT

echo
echo "Checking gateway RAGFlow route..."
curl -fsSI "http://127.0.0.1:${PUBLIC_PORT}/" >/dev/null
echo "Gateway root route is reachable."

echo
echo "Checking gateway MinerU route..."
curl -fsS "http://127.0.0.1:${PUBLIC_PORT}/mineru/health" >/dev/null
echo "MinerU health endpoint is reachable through gateway."

echo
echo "Checking Office gateway and LibreOffice..."
docker exec "$OFFICE_ID" libreoffice --version
curl -fsS "http://127.0.0.1:${PUBLIC_PORT}/mineru/health" >/dev/null
echo "Office gateway and LibreOffice are reachable."

echo
echo "Checking real Office conversion through gateway..."
docker exec -i "$OFFICE_ID" python3 - <<'PY' >"$OFFICE_FIXTURE"
from io import BytesIO
import sys
from zipfile import ZIP_DEFLATED, ZipFile

parts = {
    "[Content_Types].xml": """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>""",
    "_rels/.rels": """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>""",
    "word/document.xml": """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body><w:p><w:r><w:t>Offline Office smoke test</w:t></w:r></w:p>
<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:body>
</w:document>""",
}
output = BytesIO()
with ZipFile(output, "w", ZIP_DEFLATED) as archive:
    for name, content in parts.items():
        archive.writestr(name, content)
sys.stdout.buffer.write(output.getvalue())
PY
curl -fsS -X POST \
  "http://127.0.0.1:${PUBLIC_PORT}/mineru/file_parse" \
  -F "files=@${OFFICE_FIXTURE};type=application/vnd.openxmlformats-officedocument.wordprocessingml.document" \
  -F "office_mode=pdf_ocr" \
  -F "return_md=true" \
  -F "response_format_zip=true" \
  -o "$OFFICE_RESULT"
docker exec -i "$OFFICE_ID" python3 -c \
  'import io,sys,zipfile; z=zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read())); m=[n for n in z.namelist() if n.endswith(".md")]; assert m and any(z.read(n).strip() for n in m)' \
  <"$OFFICE_RESULT"
if docker exec "$OFFICE_ID" sh -c \
  'find /tmp/mineru-office -mindepth 1 -maxdepth 1 -print -quit | grep -q .'; then
  echo "Office gateway left request files under /tmp/mineru-office" >&2
  exit 1
fi
echo "Real Office conversion produced non-empty Markdown and cleaned temporary files."

if profile_enabled "mineru-ui"; then
  GRADIO_ID="$(service_container mineru-gradio)"
  echo
  echo "Checking gateway MinerU Gradio route..."
  curl -fsS "http://127.0.0.1:${PUBLIC_PORT}/mineru-ui/" >"$GRADIO_HTML"
  grep -Fq 'window.gradio_config' "$GRADIO_HTML"
  for forbidden in \
    'fonts.googleapis.com' \
    'fonts.gstatic.com' \
    'cdnjs.cloudflare.com' \
    'use.fontawesome.com' \
    'img.shields.io'; do
    if grep -Fq "$forbidden" "$GRADIO_HTML"; then
      echo "MinerU Gradio still references external browser resource: $forbidden" >&2
      exit 1
    fi
  done
  if docker port "$GRADIO_ID" | grep -q .; then
    echo "mineru-gradio must not publish a host port" >&2
    exit 1
  fi
  docker exec "$GRADIO_ID" test -s /opt/mineru-ui-assets/pdf.worker.min.mjs
  docker exec -i "$GRADIO_ID" sh -c 'cat > /tmp/mineru-ui-smoke.docx' < "$OFFICE_FIXTURE"
  docker exec -i "$GRADIO_ID" python3 - /tmp/mineru-ui-smoke.docx < "$SCRIPT_DIR/verify-gradio.py"
  echo "MinerU Gradio is reachable through the gateway."
fi

echo
echo "Checking gateway Markdown Convert route..."
curl -fsS "http://127.0.0.1:${PUBLIC_PORT}/convert/api/health" >/dev/null
echo "Markdown Convert health endpoint is reachable through gateway."

echo
echo "Recent MinerU logs:"
docker logs --tail 40 "$ROUTER_ID" || true

echo
echo "Recent Office gateway logs:"
docker logs --tail 40 "$OFFICE_ID" || true

if profile_enabled "mineru-ui"; then
  echo
  echo "Recent MinerU Gradio logs:"
  docker logs --tail 40 "$GRADIO_ID" || true
fi

echo
echo "Recent Markdown Convert logs:"
docker logs --tail 40 "$API_ID" || true
docker logs --tail 40 "$WORKER_ID" || true

echo
echo "Recent gateway logs:"
docker logs --tail 40 "$GATEWAY_ID" || true

echo
echo "Recent RAGFlow logs:"
docker logs --tail 40 "$RAGFLOW_ID" || true
