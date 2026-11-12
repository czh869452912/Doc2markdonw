#!/usr/bin/env bash
# Shared by deployment and verification; never source the user-managed .env.
read_runtime_env() {
  local file="$1" key="$2" fallback="${3:-}" value=""
  if [[ -f "$file" ]]; then
    value="$(sed -n "s/^${key}=//p" "$file" | tail -n1 | tr -d '\r')"
    value="${value#\"}"; value="${value%\"}"
    value="${value#\'}"; value="${value%\'}"
  fi
  printf '%s' "${value:-$fallback}"
}

resolve_compose_project_name() {
  local docker_dir="$1" requested="${2:-${COMPOSE_PROJECT_NAME:-}}" fallback_env="${3:-}"
  local marker="$docker_dir/.compose-project-name" saved=""
  if [[ -f "$marker" ]]; then
    saved="$(tr -d '\r\n' < "$marker")"
  fi
  if [[ -z "$requested" ]]; then
    requested="${saved:-$(read_runtime_env "$docker_dir/.env" COMPOSE_PROJECT_NAME)}"
    requested="${requested:-$(read_runtime_env "$fallback_env" COMPOSE_PROJECT_NAME doc2markdown)}"
  fi
  if [[ ! "$requested" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
    echo "Invalid Compose project name: $requested" >&2
    return 1
  fi
  if [[ -n "$saved" && "$saved" != "$requested" ]]; then
    echo "Runtime belongs to Compose project '$saved', not '$requested'. Use a separate --project-dir for a new project." >&2
    return 1
  fi
  COMPOSE_PROJECT_NAME="$requested"
  export COMPOSE_PROJECT_NAME
}

service_container() {
  local service="$1" ids
  ids="$(docker ps -q --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME" \
    --filter "label=com.docker.compose.service=$service")"
  if [[ -z "$ids" || "$ids" == *$'\n'* ]]; then
    echo "Expected one running $service container in project $COMPOSE_PROJECT_NAME." >&2
    return 1
  fi
  printf '%s' "$ids"
}
