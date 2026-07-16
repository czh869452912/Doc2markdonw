# Deployment Down and Remove Commands Design

## Goal

Extend `deploy/ragflow-mineru/scripts/deploy-linux.sh` with lifecycle commands
for stopping or removing every container managed by the offline deployment.
The existing command without an action must keep its current deployment
behavior.

## Command Interface

The script accepts an optional positional action:

```bash
sudo bash scripts/deploy-linux.sh
sudo bash scripts/deploy-linux.sh down
sudo bash scripts/deploy-linux.sh rm
sudo bash scripts/deploy-linux.sh rm --purge-data
```

No action means the current install, image-load, and Compose `up -d` flow.
`down` and `rm` may be combined with `--project-dir PATH`. They operate on the
already installed runtime files and do not require the offline package or image
archives.

`--purge-data` is valid only with `rm`. The existing `--package-dir`,
`--skip-load`, and `--skip-up` options remain deployment options and are
rejected for lifecycle actions when they would otherwise be meaningless.

## Lifecycle Semantics

`down` runs Compose `stop` across the same generated Compose v1 files and
services used by deployment. Containers, networks, volumes, bind-mounted data,
configuration, and images remain available for a later restart.

`rm` runs Compose `down --remove-orphans`. It removes the deployment's
containers and Compose-created networks while retaining named volumes,
bind-mounted runtime data, the installed project directory, and Docker images.

`rm --purge-data` runs Compose `down --volumes --remove-orphans`, then removes
the complete resolved project directory. This deletes installed configuration
and bind-mounted persistent data in addition to Compose volumes. Docker images
remain installed so an intranet server does not need to import the image bundle
again.

## Compose Compatibility

Lifecycle actions reuse the script's `run_compose` helper, preserving support
for both `docker-compose` v1 and `docker compose` v2. They also reuse the
generated `*.v1.yml` files because deployment strips unsupported upstream
Compose features and host-port blocks into those files before starting the
stack.

Before running an action, the script verifies that the installed Docker
directory and required generated Compose files exist. Missing runtime files
produce an actionable error directing the operator to deploy first.

## Purge Safety

Before deleting data, the script resolves `PROJECT_DIR` to an absolute path and
refuses dangerous targets including an empty path, `/`, `/opt`, `/usr`, `/var`,
and `/home`. The target must contain the expected `ragflow/docker` runtime
directory and generated Compose files. Deletion uses the verified literal
project path only.

The explicit `rm --purge-data` combination is the destructive confirmation;
the script prints the target before removal. No images or unrelated Docker
resources are removed.

## Documentation and Packaging

The README documents all four command forms and precisely states what each
command preserves or removes. The updated deployment script is copied into the
existing unpacked air-gap directory under `dist` so that local testing uses the
same behavior. The ignored image archives are not rebuilt or modified.

## Testing

Shell-level regression tests run the script with stubbed Docker and Compose
commands in temporary directories. Tests cover:

- existing deployment invocation remaining the default action;
- `down` issuing Compose `stop` for the full stack;
- `rm` issuing `down --remove-orphans` without volume deletion;
- `rm --purge-data` issuing volume removal and deleting only the validated
  project directory;
- invalid action/flag combinations;
- missing runtime files and dangerous purge paths;
- both Compose command variants where practical.

Static checks run `bash -n`, and packaging verification confirms the source and
unpacked air-gap scripts match.
