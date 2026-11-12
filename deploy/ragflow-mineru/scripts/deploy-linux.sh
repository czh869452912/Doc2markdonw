#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/runtime-common.sh"
DEFAULT_PACKAGE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PACKAGE_DIR="$DEFAULT_PACKAGE_DIR"
PROJECT_DIR="/opt/ragflow-mineru"
PROJECT_NAME=""
ACTION="up"
ACTION_SET=0
SKIP_LOAD=0
SKIP_UP=0
PURGE_DATA=0
PACKAGE_DIR_SET=0
SKIP_LOAD_SET=0
SKIP_UP_SET=0

usage() {
  cat <<'EOF'
Usage:
  sudo bash scripts/deploy-linux.sh [up] [options]
  sudo bash scripts/deploy-linux.sh down [--project-dir PATH]
  sudo bash scripts/deploy-linux.sh rm [--project-dir PATH] [--purge-data]

Options:
  --package-dir PATH   Unpacked offline package directory.
  --project-dir PATH   Install/runtime directory. Default: /opt/ragflow-mineru
  --project-name NAME  Compose namespace. Default: doc2markdown (saved per runtime).
  --skip-load          Do not run docker load for images/*.tar.
  --skip-up            Prepare files and images but do not start containers.
  --purge-data         With rm, also remove Compose volumes and PROJECT_DIR.
  -h, --help           Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    up|down|rm)
      if [[ "$ACTION_SET" -eq 1 ]]; then
        echo "Only one action may be specified." >&2
        exit 2
      fi
      ACTION="$1"
      ACTION_SET=1
      shift
      ;;
    --package-dir)
      PACKAGE_DIR="$2"
      PACKAGE_DIR_SET=1
      shift 2
      ;;
    --project-dir)
      PROJECT_DIR="$2"
      shift 2
      ;;
    --project-name)
      PROJECT_NAME="${2:?--project-name requires a value}"
      shift 2
      ;;
    --skip-load)
      SKIP_LOAD=1
      SKIP_LOAD_SET=1
      shift
      ;;
    --skip-up)
      SKIP_UP=1
      SKIP_UP_SET=1
      shift
      ;;
    --purge-data)
      PURGE_DATA=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown action or option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ "$PURGE_DATA" -eq 1 && "$ACTION" != "rm" ]]; then
  echo "--purge-data is valid only with the rm action." >&2
  exit 2
fi

if [[ "$ACTION" != "up" ]]; then
  if [[ "$PACKAGE_DIR_SET" -eq 1 ]]; then
    echo "--package-dir is valid only with the up action." >&2
    exit 2
  fi
  if [[ "$SKIP_LOAD_SET" -eq 1 ]]; then
    echo "--skip-load is valid only with the up action." >&2
    exit 2
  fi
  if [[ "$SKIP_UP_SET" -eq 1 ]]; then
    echo "--skip-up is valid only with the up action." >&2
    exit 2
  fi
fi

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_cmd docker

run_compose() {
  if command -v docker-compose >/dev/null 2>&1; then
    docker-compose -p "$COMPOSE_PROJECT_NAME" "$@"
  elif docker compose version >/dev/null 2>&1; then
    docker compose -p "$COMPOSE_PROJECT_NAME" "$@"
  else
    echo "Docker Compose is required: install either 'docker compose' or 'docker-compose'." >&2
    exit 1
  fi
}

write_compose_v1_file() {
  local source="$1"
  local target="$2"
  local strip_include="${3:-0}"

  awk -v strip_include="$strip_include" -v office_pids="$OFFICE_PIDS_LIMIT" '
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
      # Let Compose scope every container, including upstream services.
      if ($0 ~ /^    container_name:/) next
      if (current_service == "mineru-office-gateway" && $0 ~ /^    pids_limit:/) {
        print "    pids_limit: " office_pids
        next
      }
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
  OFFICE_PIDS_LIMIT="${OFFICE_PIDS_LIMIT:-$(read_runtime_env "$docker_dir/.env" OFFICE_PIDS_LIMIT 256)}"
  if [[ ! "$OFFICE_PIDS_LIMIT" =~ ^[1-9][0-9]*$ ]]; then
    echo "OFFICE_PIDS_LIMIT must be a positive integer." >&2
    return 1
  fi

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
  write_compose_v1_file "$docker_dir/docker-compose.office-gateway.yml" "$docker_dir/docker-compose.office-gateway.v1.yml" 0
  write_compose_v1_file "$docker_dir/docker-compose.md-convert.yml" "$docker_dir/docker-compose.md-convert.v1.yml" 0
  write_compose_v1_file "$docker_dir/docker-compose.gateway.yml" "$docker_dir/docker-compose.gateway.v1.yml" 0
}

compose_files=()

prepare_runtime_compose_files() {
  local docker_dir="$1"
  local source_file
  local required_files=(
    docker-compose.yml
    docker-compose.mineru.yml
    docker-compose.office-gateway.yml
    docker-compose.md-convert.yml
    docker-compose.gateway.yml
  )

  for source_file in "${required_files[@]}"; do
    if [[ ! -f "$docker_dir/$source_file" ]]; then
      echo "Installed runtime is missing $source_file: $docker_dir" >&2
      echo "Run the deployment action first." >&2
      exit 1
    fi
  done

  prepare_compose_v1_files "$docker_dir"
  compose_files=()
  if [[ -f "$docker_dir/docker-compose-base.v1.yml" ]]; then
    compose_files+=(-f docker-compose-base.v1.yml)
  fi
  compose_files+=(
    -f docker-compose.v1.yml
    -f docker-compose.mineru.v1.yml
    -f docker-compose.office-gateway.v1.yml
    -f docker-compose.md-convert.v1.yml
    -f docker-compose.gateway.v1.yml
  )
}

resolve_installed_project_dir() {
  if [[ ! -d "$PROJECT_DIR" ]]; then
    echo "Installed project directory does not exist: $PROJECT_DIR" >&2
    return 1
  fi
  (cd "$PROJECT_DIR" && pwd -P)
}

validate_purge_project_dir() {
  local resolved_project_dir="$1"

  case "$resolved_project_dir" in
    ""|/|/opt|/usr|/var|/home)
      echo "Refusing to purge dangerous project path: $resolved_project_dir" >&2
      return 1
      ;;
  esac

  if [[ "$resolved_project_dir" != /* ]]; then
    echo "Refusing to purge non-absolute project path: $resolved_project_dir" >&2
    return 1
  fi

  if [[ ! -d "$resolved_project_dir/ragflow/docker" ]]; then
    echo "Refusing to purge path without ragflow/docker: $resolved_project_dir" >&2
    return 1
  fi
}

run_lifecycle_action() {
  local resolved_project_dir
  local runtime_docker_dir

  resolved_project_dir="$(resolve_installed_project_dir)"
  runtime_docker_dir="$resolved_project_dir/ragflow/docker"
  resolve_compose_project_name "$runtime_docker_dir" "$PROJECT_NAME"
  if [[ "$PURGE_DATA" -eq 1 ]]; then
    validate_purge_project_dir "$resolved_project_dir"
  fi

  prepare_runtime_compose_files "$runtime_docker_dir"
  cd "$runtime_docker_dir"

  case "$ACTION" in
    down)
      run_compose "${compose_files[@]}" stop
      echo "Deployment containers stopped."
      ;;
    rm)
      if [[ "$PURGE_DATA" -eq 1 ]]; then
        run_compose "${compose_files[@]}" down --volumes --remove-orphans
        cd /
        echo "Removing deployment data: $resolved_project_dir"
        rm -rf -- "$resolved_project_dir"
        echo "Deployment containers, networks, volumes, and data removed. Docker images were preserved."
      else
        run_compose "${compose_files[@]}" down --remove-orphans
        echo "Deployment containers and networks removed. Data and Docker images were preserved."
      fi
      ;;
  esac
}

if [[ "$ACTION" != "up" ]]; then
  run_lifecycle_action
  exit 0
fi

PACKAGE_DIR="$(cd "$PACKAGE_DIR" && pwd -P)"
SOURCE_DOCKER_DIR="$PACKAGE_DIR/ragflow/docker"

if [[ ! -f "$SOURCE_DOCKER_DIR/docker-compose.yml" ]]; then
  echo "Package is missing ragflow/docker/docker-compose.yml: $SOURCE_DOCKER_DIR" >&2
  exit 1
fi

if [[ ! -f "$SOURCE_DOCKER_DIR/docker-compose.mineru.yml" ]]; then
  echo "Package is missing ragflow/docker/docker-compose.mineru.yml: $SOURCE_DOCKER_DIR" >&2
  exit 1
fi

if [[ ! -f "$SOURCE_DOCKER_DIR/docker-compose.office-gateway.yml" ]]; then
  echo "Package is missing ragflow/docker/docker-compose.office-gateway.yml: $SOURCE_DOCKER_DIR" >&2
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

resolve_compose_project_name "$PROJECT_DIR/ragflow/docker" "$PROJECT_NAME" "$SOURCE_DOCKER_DIR/.env"

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

mkdir -p "$PROJECT_DIR"
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd -P)"
TARGET_DOCKER_DIR="$PROJECT_DIR/ragflow/docker"
mkdir -p "$TARGET_DOCKER_DIR"
if [[ "$SOURCE_DOCKER_DIR" -ef "$TARGET_DOCKER_DIR" ]]; then
  echo "Package and runtime use the same docker directory; skipping file copy."
else
  shopt -s dotglob nullglob
  for entry in "$SOURCE_DOCKER_DIR"/*; do
    name="${entry##*/}"
    # Keep server passwords/ports and the installed namespace on upgrades.
    [[ "$name" == .compose-project-name ]] && continue
    [[ "$name" == .env && -f "$TARGET_DOCKER_DIR/.env" ]] && continue
    case "$name" in
      ragflow-logs|mineru-input|mineru-output|office-fonts|md-convert-data)
        [[ -d "$TARGET_DOCKER_DIR/$name" ]] && continue
        ;;
    esac
    cp -a -- "$entry" "$TARGET_DOCKER_DIR/"
  done
  shopt -u dotglob
fi
printf '%s\n' "$COMPOSE_PROJECT_NAME" > "$TARGET_DOCKER_DIR/.compose-project-name"
mkdir -p \
  "$TARGET_DOCKER_DIR/ragflow-logs" \
  "$TARGET_DOCKER_DIR/mineru-input" \
  "$TARGET_DOCKER_DIR/mineru-output" \
  "$TARGET_DOCKER_DIR/office-fonts" \
  "$TARGET_DOCKER_DIR/md-convert-data"

chmod +x "$PACKAGE_DIR"/scripts/*.sh || true
find "$TARGET_DOCKER_DIR" -maxdepth 3 -type f -name "*.sh" -exec chmod +x {} \;

if command -v nvidia-smi >/dev/null 2>&1; then
  echo "Host NVIDIA devices:"
  nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader || true
else
  echo "nvidia-smi not found. Continue only if this is an intentional CPU test or the NVIDIA driver is installed differently."
fi

prepare_runtime_compose_files "$TARGET_DOCKER_DIR"

if [[ "$SKIP_UP" -eq 1 ]]; then
  echo "Files and images prepared. Containers were not started because --skip-up was set."
  exit 0
fi

cd "$TARGET_DOCKER_DIR"

run_compose \
  "${compose_files[@]}" \
  up -d

echo
echo "Stack start requested."
echo "Compose project: $COMPOSE_PROJECT_NAME"
PUBLIC_PORT="$(read_runtime_env .env PUBLIC_PORT 18080)"
echo "Gateway:        http://<server>:$PUBLIC_PORT"
echo "RAGFlow WebUI:  http://<server>:$PUBLIC_PORT/"
echo "MinerU API:     http://<server>:$PUBLIC_PORT/mineru/"
echo "MinerU Gradio:  http://<server>:$PUBLIC_PORT/mineru-ui/"
echo "MD Convert UI:  http://<server>:$PUBLIC_PORT/convert/"
echo "Run verification: bash $PACKAGE_DIR/scripts/verify-linux.sh --project-dir $PROJECT_DIR"
