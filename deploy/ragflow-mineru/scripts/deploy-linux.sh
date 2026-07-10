#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_PACKAGE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PACKAGE_DIR="$DEFAULT_PACKAGE_DIR"
PROJECT_DIR="/opt/ragflow-mineru"
SKIP_LOAD=0
SKIP_UP=0

usage() {
  cat <<'EOF'
Usage: sudo bash scripts/deploy-linux.sh [options]

Options:
  --package-dir PATH   Unpacked offline package directory.
  --project-dir PATH   Install/runtime directory. Default: /opt/ragflow-mineru
  --skip-load          Do not run docker load for images/*.tar.
  --skip-up            Prepare files and images but do not start containers.
  -h, --help           Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --package-dir)
      PACKAGE_DIR="$2"
      shift 2
      ;;
    --project-dir)
      PROJECT_DIR="$2"
      shift 2
      ;;
    --skip-load)
      SKIP_LOAD=1
      shift
      ;;
    --skip-up)
      SKIP_UP=1
      shift
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

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_cmd docker

run_compose() {
  if command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  elif docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  else
    echo "Docker Compose is required: install either 'docker compose' or 'docker-compose'." >&2
    exit 1
  fi
}

write_compose_v1_file() {
  local source="$1"
  local target="$2"
  local strip_include="${3:-0}"

  awk -v strip_include="$strip_include" '
    function indent(line, prefix) {
      prefix = line
      sub(/[^ ].*$/, "", prefix)
      return length(prefix)
    }

    function should_strip_block(line) {
      return current_service != "" &&
        current_service != "gateway" &&
        line ~ /^    (ports|extra_hosts|deploy):/
    }

    function is_gpu_service(service_name) {
      return service_name == "ragflow-gpu" ||
        service_name == "mineru-router" ||
        service_name == "mineru-gradio" ||
        service_name == "tei-gpu"
    }

    {
      if (skipping_include) {
        if ($0 ~ /^[^[:space:]#][^:]*:/) {
          skipping_include = 0
        } else {
          next
        }
      }

      if (strip_include == "1" && $0 ~ /^include:/) {
        skipping_include = 1
        next
      }

      if (skipping_block) {
        if ($0 ~ /^[[:space:]]*$/) {
          next
        }
        if (indent($0) > block_indent) {
          next
        }
        skipping_block = 0
      }

      if ($0 ~ /^  [A-Za-z0-9_.-]+:/) {
        current_service = $0
        sub(/^  /, "", current_service)
        sub(/:.*/, "", current_service)
        print
        if (is_gpu_service(current_service)) {
          print "    runtime: nvidia"
        }
        next
      }

      if (should_strip_block($0)) {
        skipping_block = 1
        block_indent = indent($0)
        next
      }

      print
    }
  ' "$source" > "$target"
}

prepare_compose_v1_files() {
  local docker_dir="$1"
  local main_file="$docker_dir/docker-compose.yml"
  local has_include=0

  if grep -Eq '^include:' "$main_file"; then
    has_include=1
  fi

  if [[ "$has_include" -eq 1 && ! -f "$docker_dir/docker-compose-base.yml" ]]; then
    echo "docker-compose.yml uses include, but docker-compose-base.yml is missing: $docker_dir" >&2
    exit 1
  fi

  if [[ "$has_include" -eq 1 ]]; then
    write_compose_v1_file "$docker_dir/docker-compose-base.yml" "$docker_dir/docker-compose-base.v1.yml" 0
  fi

  write_compose_v1_file "$docker_dir/docker-compose.yml" "$docker_dir/docker-compose.v1.yml" "$has_include"
  write_compose_v1_file "$docker_dir/docker-compose.mineru.yml" "$docker_dir/docker-compose.mineru.v1.yml" 0
  write_compose_v1_file "$docker_dir/docker-compose.md-convert.yml" "$docker_dir/docker-compose.md-convert.v1.yml" 0
  write_compose_v1_file "$docker_dir/docker-compose.gateway.yml" "$docker_dir/docker-compose.gateway.v1.yml" 0
}

PACKAGE_DIR="$(cd "$PACKAGE_DIR" && pwd)"
SOURCE_DOCKER_DIR="$PACKAGE_DIR/ragflow/docker"
TARGET_DOCKER_DIR="$PROJECT_DIR/ragflow/docker"

if [[ ! -f "$SOURCE_DOCKER_DIR/docker-compose.yml" ]]; then
  echo "Package is missing ragflow/docker/docker-compose.yml: $SOURCE_DOCKER_DIR" >&2
  exit 1
fi

if [[ ! -f "$SOURCE_DOCKER_DIR/docker-compose.mineru.yml" ]]; then
  echo "Package is missing ragflow/docker/docker-compose.mineru.yml: $SOURCE_DOCKER_DIR" >&2
  exit 1
fi

if [[ ! -f "$SOURCE_DOCKER_DIR/docker-compose.md-convert.yml" ]]; then
  echo "Package is missing ragflow/docker/docker-compose.md-convert.yml: $SOURCE_DOCKER_DIR" >&2
  exit 1
fi

if [[ ! -f "$SOURCE_DOCKER_DIR/docker-compose.gateway.yml" ]]; then
  echo "Package is missing ragflow/docker/docker-compose.gateway.yml: $SOURCE_DOCKER_DIR" >&2
  exit 1
fi

if [[ "$SKIP_LOAD" -eq 0 ]]; then
  shopt -s nullglob
  image_archives=("$PACKAGE_DIR"/images/*.tar)
  if [[ "${#image_archives[@]}" -eq 0 ]]; then
    echo "No image archives found under $PACKAGE_DIR/images" >&2
    exit 1
  fi
  for archive in "${image_archives[@]}"; do
    echo "Loading image archive: $archive"
    docker load -i "$archive"
  done
fi

mkdir -p "$TARGET_DOCKER_DIR"
cp -a "$SOURCE_DOCKER_DIR"/. "$TARGET_DOCKER_DIR"/
mkdir -p \
  "$TARGET_DOCKER_DIR/ragflow-logs" \
  "$TARGET_DOCKER_DIR/mineru-home" \
  "$TARGET_DOCKER_DIR/mineru-input" \
  "$TARGET_DOCKER_DIR/mineru-output" \
  "$TARGET_DOCKER_DIR/md-convert-data"

chmod +x "$PACKAGE_DIR"/scripts/*.sh || true

if command -v nvidia-smi >/dev/null 2>&1; then
  echo "Host NVIDIA devices:"
  nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader || true
else
  echo "nvidia-smi not found. Continue only if this is an intentional CPU test or the NVIDIA driver is installed differently."
fi

if [[ "$SKIP_UP" -eq 1 ]]; then
  echo "Files and images prepared. Containers were not started because --skip-up was set."
  exit 0
fi

cd "$TARGET_DOCKER_DIR"
prepare_compose_v1_files "$TARGET_DOCKER_DIR"

compose_files=()
if [[ -f docker-compose-base.v1.yml ]]; then
  compose_files+=(-f docker-compose-base.v1.yml)
fi
compose_files+=(
  -f docker-compose.v1.yml
  -f docker-compose.mineru.v1.yml
  -f docker-compose.md-convert.v1.yml
  -f docker-compose.gateway.v1.yml
)

run_compose \
  "${compose_files[@]}" \
  up -d

echo
echo "Stack start requested."
echo "Gateway:        http://<server>:$(grep -E '^PUBLIC_PORT=' .env | tail -n1 | cut -d= -f2- || echo 18080)"
echo "RAGFlow WebUI:  http://<server>:$(grep -E '^PUBLIC_PORT=' .env | tail -n1 | cut -d= -f2- || echo 18080)/"
echo "MinerU API:     http://<server>:$(grep -E '^PUBLIC_PORT=' .env | tail -n1 | cut -d= -f2- || echo 18080)/mineru/"
echo "MD Convert UI:  http://<server>:$(grep -E '^PUBLIC_PORT=' .env | tail -n1 | cut -d= -f2- || echo 18080)/convert/"
echo "Run verification: bash $PACKAGE_DIR/scripts/verify-linux.sh --project-dir $PROJECT_DIR"
