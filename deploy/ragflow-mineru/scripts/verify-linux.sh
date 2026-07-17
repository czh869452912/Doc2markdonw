#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/opt/ragflow-mineru"

usage() {
  cat <<'EOF'
Usage: bash scripts/verify-linux.sh [options]

Options:
  --project-dir PATH   Install/runtime directory. Default: /opt/ragflow-mineru
  -h, --help           Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-dir)
      PROJECT_DIR="$2"
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

DOCKER_DIR="$PROJECT_DIR/ragflow/docker"
ENV_FILE="$DOCKER_DIR/.env"

read_env() {
  local key="$1"
  local default="$2"
  if [[ -f "$ENV_FILE" ]]; then
    local value
    value="$(grep -E "^${key}=" "$ENV_FILE" | tail -n1 | cut -d= -f2- | tr -d '\r' || true)"
    if [[ -n "$value" ]]; then
      printf '%s' "$value"
      return
    fi
  fi
  printf '%s' "$default"
}

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing .env: $ENV_FILE" >&2
  exit 1
fi

cd "$DOCKER_DIR"

if docker inspect mineru-router \
  --format '{{range .Mounts}}{{println .Destination}}{{end}}' \
  | grep -Fxq '/root'; then
  echo "MinerU container must not mount /root; the mount hides image-owned models." >&2
  exit 1
fi

echo "Checking embedded MinerU model paths..."
docker exec -i mineru-router python3 - <<'PY'
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
  --filter name=ragflow \
  --filter name=mineru \
  --filter name=md-convert \
  --filter name=kroki \
  --filter name=redis \
  --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'

PUBLIC_PORT="$(read_env PUBLIC_PORT 18080)"

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
docker exec mineru-office-gateway libreoffice --version
curl -fsS "http://127.0.0.1:${PUBLIC_PORT}/mineru/health" >/dev/null
echo "Office gateway and LibreOffice are reachable."

echo
echo "Checking gateway Markdown Convert route..."
curl -fsS "http://127.0.0.1:${PUBLIC_PORT}/convert/api/health" >/dev/null
echo "Markdown Convert health endpoint is reachable through gateway."

echo
echo "Recent MinerU logs:"
docker logs --tail 40 mineru-router || true

echo
echo "Recent Office gateway logs:"
docker logs --tail 40 mineru-office-gateway || true

echo
echo "Recent Markdown Convert logs:"
docker logs --tail 40 md-convert-api || true
docker logs --tail 40 md-convert-worker || true

echo
echo "Recent gateway logs:"
docker logs --tail 40 ragflow-mineru-gateway || true

echo
echo "Recent RAGFlow logs:"
docker logs --tail 40 ragflow-gpu || \
  docker logs --tail 40 ragflow-cpu || true
