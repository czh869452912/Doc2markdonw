# Deployment Down and Remove Commands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe `down`, `rm`, and `rm --purge-data` lifecycle operations to the offline Linux deployment script without changing its default deployment behavior.

**Architecture:** Keep one `deploy-linux.sh` entry point with a default `up` action and two positional lifecycle actions. Reuse the existing Compose compatibility layer and generated Compose v1 files; isolate argument validation, runtime Compose-file preparation, and purge-path validation in shell functions that are exercised through subprocess-level tests with stubbed Docker commands.

**Tech Stack:** Bash, Docker Compose v1/v2 CLI, Python 3 `unittest`, PowerShell packaging, Markdown.

---

### Task 1: Add Failing Lifecycle Command Tests

**Files:**
- Create: `deploy/ragflow-mineru/tests/test_deploy_lifecycle.py`
- Test: `deploy/ragflow-mineru/scripts/deploy-linux.sh`

- [x] **Step 1: Create a subprocess test harness**

Create a `unittest.TestCase` that makes a temporary `package`, `project`, and
`bin` directory. Write minimal `docker-compose.yml`,
`docker-compose.mineru.yml`, `docker-compose.md-convert.yml`, and
`docker-compose.gateway.yml` files into both the package and installed runtime.
Stub `docker` and optionally `docker-compose` in `bin`, recording every command
to a log outside the project directory through `COMMAND_LOG`.

The helper must invoke:

```python
subprocess.run(
    ["bash", str(SCRIPT), *arguments],
    cwd=ROOT,
    env={**os.environ, "PATH": stub_path, "COMMAND_LOG": str(command_log)},
    text=True,
    capture_output=True,
)
```

The Docker v2 stub returns success for `docker compose version`; the v1 setup
provides a `docker-compose` executable so the script selects the existing v1
compatibility branch.

- [x] **Step 2: Test the default deployment action**

Invoke the script without a positional action using `--package-dir`,
`--project-dir`, and a package containing `images/test.tar`. Assert exit code
zero, a recorded `docker load -i .../test.tar`, and a final Compose command
ending in `up -d`. This protects the current invocation contract.

- [x] **Step 3: Test `down` and default `rm`**

Invoke:

```text
down --project-dir <project>
rm --project-dir <project>
```

Assert `down` records Compose `stop`. Assert `rm` records
`down --remove-orphans`, does not contain `--volumes`, and leaves the project
directory and its sentinel data file in place.

- [x] **Step 4: Test purge and validation boundaries**

Invoke `rm --purge-data --project-dir <project>`, assert the recorded Compose
command contains `down --volumes --remove-orphans`, and assert the complete
project directory no longer exists. Also assert these calls fail before any
destructive command:

```text
down --purge-data
down --skip-load
rm --package-dir <package>
rm --purge-data --project-dir /
unknown-action
```

Check error messages name the invalid option or refused purge path.

- [x] **Step 5: Test Compose v1 and v2 command selection**

Run `down` once with a `docker-compose` stub and once with only the Docker v2
stub. Assert the command log starts with `docker-compose` in the first case and
`docker compose` in the second.

- [x] **Step 6: Run the new tests and verify they fail**

Run:

```bash
python deploy/ragflow-mineru/tests/test_deploy_lifecycle.py -v
```

Expected: failures because `down`, `rm`, and `--purge-data` are not recognized.

### Task 2: Implement Lifecycle Argument Parsing and Compose Actions

**Files:**
- Modify: `deploy/ragflow-mineru/scripts/deploy-linux.sh`
- Test: `deploy/ragflow-mineru/tests/test_deploy_lifecycle.py`

- [x] **Step 1: Add actions to help and parsing**

Default `ACTION` to `up`, track whether a positional action was explicitly set,
and parse `up`, `down`, and `rm` as mutually exclusive actions. Add
`PURGE_DATA`, plus flags recording whether deploy-only options were supplied.
Document these forms in `usage()`:

```text
deploy-linux.sh [up] [options]
deploy-linux.sh down [--project-dir PATH]
deploy-linux.sh rm [--project-dir PATH] [--purge-data]
```

Reject duplicate actions, unknown positional values, `--purge-data` outside
`rm`, and `--package-dir`, `--skip-load`, or `--skip-up` with lifecycle actions.

- [x] **Step 2: Extract installed Compose-file preparation**

Add a function that verifies the four installed source Compose files, runs
`prepare_compose_v1_files`, and fills a global `compose_files` array with the
optional base file followed by the main, MinerU, Markdown Convert, and gateway
files. Reuse this function for both `up` and lifecycle actions so all actions
address the same Compose project and services.

- [x] **Step 3: Implement purge-path validation**

Resolve an existing `PROJECT_DIR` using `cd "$PROJECT_DIR" && pwd -P`. Refuse
empty or non-absolute results and exact paths `/`, `/opt`, `/usr`, `/var`, and
`/home`. Require `<project>/ragflow/docker` and its four source Compose files.
Return the validated absolute path without modifying it.

- [x] **Step 4: Implement lifecycle dispatch**

Before package validation or image loading, dispatch non-`up` actions against
the installed runtime:

```bash
run_compose "${compose_files[@]}" stop
run_compose "${compose_files[@]}" down --remove-orphans
run_compose "${compose_files[@]}" down --volumes --remove-orphans
```

For purge, leave the target directory after Compose succeeds, print the exact
validated path, and remove only that directory with `rm -rf -- "$path"`.
Return immediately after lifecycle completion so no image archives are loaded
and no package files are copied.

- [x] **Step 5: Run lifecycle tests and verify they pass**

Run:

```bash
python deploy/ragflow-mineru/tests/test_deploy_lifecycle.py -v
bash -n deploy/ragflow-mineru/scripts/deploy-linux.sh
```

Expected: all lifecycle tests pass and Bash syntax exits zero.

### Task 3: Document Commands and Synchronize the Offline Package

**Files:**
- Modify: `deploy/ragflow-mineru/README.md`
- Modify: `deploy/ragflow-mineru/tests/test_deploy_lifecycle.py`
- Synchronize ignored copy: `dist/ragflow-mineru-airgap-v0.26.4-20260708-163537/scripts/deploy-linux.sh`
- Synchronize ignored copy: `dist/ragflow-mineru-airgap-v0.26.4-20260708-163537/README.md`

- [x] **Step 1: Add failing documentation and synchronization assertions**

Assert the tracked and unpacked deployment scripts have identical SHA-256
content when the unpacked package exists. Assert both READMEs contain examples
for `down`, `rm`, and `rm --purge-data`, and state that Docker images remain.

- [x] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
python deploy/ragflow-mineru/tests/test_deploy_lifecycle.py -v
```

Expected: failure because the ignored package copy and documentation are stale.

- [x] **Step 3: Update the operations documentation**

Add a lifecycle section after Linux deployment. Include the exact four command
forms, a concise preservation table, the restriction that `--purge-data` only
works with `rm`, and an explicit statement that none of these actions remove
Docker images.

- [x] **Step 4: Synchronize ignored package files**

Copy the tracked script and README to the existing unpacked package with
literal paths and force overwrite. Do not alter `images/*.tar` or rebuild the
archive.

- [x] **Step 5: Run the focused tests and verify they pass**

Run:

```bash
python deploy/ragflow-mineru/tests/test_deploy_lifecycle.py -v
```

Expected: all lifecycle, documentation, and synchronization tests pass.

### Task 4: Full Verification and Commit

**Files:**
- Modify: `docs/superpowers/plans/2026-07-16-deployment-down-rm.md`

- [x] **Step 1: Run all deployment tests**

Run:

```bash
python -m unittest discover -s deploy/ragflow-mineru/tests -v
```

Expected: all deployment tests pass.

- [x] **Step 2: Run static and repository checks**

Run:

```bash
bash -n deploy/ragflow-mineru/scripts/deploy-linux.sh
git diff --check
```

Expected: both commands exit zero.

- [x] **Step 3: Verify package synchronization and image preservation**

Compare SHA-256 hashes for the tracked and unpacked script and README. Record
the existing image archive names, sizes, and modification timestamps before and
after synchronization and assert they did not change.

- [x] **Step 4: Mark the plan complete and commit**

Change every plan checkbox to `[x]`, stage only the tracked implementation,
tests, README, and plan, then commit:

```bash
git commit -m "feat: add deployment down and remove commands"
```
