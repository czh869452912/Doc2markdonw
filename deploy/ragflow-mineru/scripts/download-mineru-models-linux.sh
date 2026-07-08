#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/opt/ragflow-mineru"
IMAGE="mineru:latest"
SOURCE="modelscope"
MODEL_SET="all"

usage() {
  cat <<'EOF'
Usage: bash scripts/download-mineru-models-linux.sh [options]

Run this only on a staging machine that can access model registries. The output
directory can then be included in the Windows package with:

  .\deploy\ragflow-mineru\scripts\package-windows.ps1 -IncludeMineruHome -MineruHomePath <path>

Options:
  --project-dir PATH   Directory containing mineru-home. Default: /opt/ragflow-mineru
  --image IMAGE        MinerU image tag. Default: mineru:latest
  --source SOURCE      modelscope, huggingface, or another MinerU-supported source.
                       Default: modelscope
  --model-set NAME     MinerU downloader model set. Default: all
  -h, --help           Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-dir)
      PROJECT_DIR="$2"
      shift 2
      ;;
    --image)
      IMAGE="$2"
      shift 2
      ;;
    --source)
      SOURCE="$2"
      shift 2
      ;;
    --model-set)
      MODEL_SET="$2"
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

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "MinerU image is not present locally: $IMAGE" >&2
  exit 1
fi

MINERU_HOME="$PROJECT_DIR/ragflow/docker/mineru-home"
mkdir -p "$MINERU_HOME"

echo "Downloading MinerU models into $MINERU_HOME"
docker run --rm \
  -e "MINERU_MODEL_SOURCE=$SOURCE" \
  -v "$MINERU_HOME:/root" \
  "$IMAGE" \
  mineru-models-download -s "$SOURCE" -m "$MODEL_SET"

echo "MinerU model download completed. Keep this mineru-home directory with the offline package."
