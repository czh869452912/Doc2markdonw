# MinerU Embedded Models Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the air-gap stack use the pipeline and VLM models embedded in `mineru:latest` without masking `/root` with an empty host directory.

**Architecture:** The image owns MinerU configuration and model files; Compose persists only input and output data. Packaging and deployment stop creating or copying an external MinerU home, while verification checks both the Docker mount contract and the embedded model paths.

**Tech Stack:** Docker Compose YAML, Bash, PowerShell, Python standard-library `unittest`

---

### Task 1: Add Deployment Contract Regression Tests

**Files:**
- Create: `deploy/ragflow-mineru/tests/test_embedded_models.py`
- Test: `deploy/ragflow-mineru/tests/test_embedded_models.py`

- [ ] **Step 1: Write failing source and package contract tests**

Create this test:

```python
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
STACK = ROOT / "deploy" / "ragflow-mineru"
PACKAGE = ROOT / "dist" / "ragflow-mineru-airgap-v0.26.4-20260708-163537"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class EmbeddedMineruModelsTests(unittest.TestCase):
    def test_compose_uses_image_owned_models(self):
        compose_files = [STACK / "docker-compose.mineru.yml"]
        packaged_compose = PACKAGE / "ragflow" / "docker" / "docker-compose.mineru.yml"
        if packaged_compose.exists():
            compose_files.append(packaged_compose)

        for path in compose_files:
            with self.subTest(path=path):
                content = read(path)
                self.assertNotIn("./mineru-home:/root", content)
                self.assertEqual(content.count("./mineru-output:/tmp/mineru"), 2)
                self.assertEqual(content.count("./mineru-input:/data/input:ro"), 2)
                model_source_keys = sum(
                    line.lstrip().startswith("MINERU_MODEL_SOURCE:")
                    for line in content.splitlines()
                )
                self.assertEqual(model_source_keys, 2)

    def test_scripts_do_not_manage_external_mineru_home(self):
        package_script = read(STACK / "scripts" / "package-windows.ps1")
        self.assertNotIn("IncludeMineruHome", package_script)
        self.assertNotIn("MineruHomePath", package_script)
        self.assertNotIn("download-mineru-models-linux.sh", package_script)
        self.assertNotIn('"mineru-home"', package_script)

        deploy_scripts = [STACK / "scripts" / "deploy-linux.sh"]
        packaged_deploy = PACKAGE / "scripts" / "deploy-linux.sh"
        if packaged_deploy.exists():
            deploy_scripts.append(packaged_deploy)
        for path in deploy_scripts:
            with self.subTest(path=path):
                self.assertNotIn("mineru-home", read(path))

        self.assertFalse((STACK / "scripts" / "download-mineru-models-linux.sh").exists())
        self.assertFalse((PACKAGE / "scripts" / "download-mineru-models-linux.sh").exists())

    def test_verification_checks_image_model_paths(self):
        verify_scripts = [STACK / "scripts" / "verify-linux.sh"]
        packaged_verify = PACKAGE / "scripts" / "verify-linux.sh"
        if packaged_verify.exists():
            verify_scripts.append(packaged_verify)
        for path in verify_scripts:
            with self.subTest(path=path):
                content = read(path)
                self.assertIn("MinerU container must not mount /root", content)
                self.assertIn("models-dir", content)
                self.assertIn("pipeline", content)
                self.assertIn("vlm", content)

    def test_documentation_describes_embedded_models(self):
        readmes = [STACK / "README.md"]
        packaged_readme = PACKAGE / "README.md"
        if packaged_readme.exists():
            readmes.append(packaged_readme)
        for path in readmes:
            with self.subTest(path=path):
                content = read(path)
                self.assertNotIn("IncludeMineruHome", content)
                self.assertNotIn("download-mineru-models-linux.sh", content)
                self.assertIn("embedded", content.lower())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the regression test and verify RED**

Run:

```powershell
python -m unittest deploy/ragflow-mineru/tests/test_embedded_models.py -v
```

Expected: FAIL because source and packaged Compose files still mount `/root`,
scripts still manage `mineru-home`, and the download helper still exists.

### Task 2: Remove External Model Ownership From Maintained Source

**Files:**
- Modify: `deploy/ragflow-mineru/docker-compose.mineru.yml`
- Modify: `deploy/ragflow-mineru/scripts/deploy-linux.sh`
- Modify: `deploy/ragflow-mineru/scripts/package-windows.ps1`
- Modify: `deploy/ragflow-mineru/scripts/verify-linux.sh`
- Delete: `deploy/ragflow-mineru/scripts/download-mineru-models-linux.sh`
- Modify: `deploy/ragflow-mineru/README.md`

- [ ] **Step 1: Remove both `/root` mounts**

Delete only this volume entry from `mineru-router` and `mineru-gradio`:

```yaml
- ./mineru-home:/root
```

Keep `mineru-output`, `mineru-input`, and `MINERU_MODEL_SOURCE=local`.

- [ ] **Step 2: Remove obsolete packaging and deployment behavior**

Remove `IncludeMineruHome` and `MineruHomePath` parameters, the helper-copy
operation, the `mineru-home` directory creation, and the external home copy
block from `package-windows.ps1`. Remove only the `mineru-home` creation line
from `deploy-linux.sh`.

- [ ] **Step 3: Add runtime verification**

Extend `verify-linux.sh` to fail when Docker reports a `/root` mount and execute
Python in `mineru-router` to assert that `models-dir.pipeline` and
`models-dir.vlm` are dictionaries entries pointing to existing directories.

- [ ] **Step 4: Remove helper and revise documentation**

Delete `download-mineru-models-linux.sh`. Replace external-model instructions
with the image-owned model contract, image rebuild guidance, container
recreation command, and a note that old `mineru-home` directories are unused but
not automatically removed.

- [ ] **Step 5: Run the regression test**

Run the Task 1 command. Expected: source assertions pass; package assertions
still fail until Task 3 updates the existing package.

### Task 3: Update The Existing Air-Gap Package In Place

**Files:**
- Modify: `dist/ragflow-mineru-airgap-v0.26.4-20260708-163537/ragflow/docker/docker-compose.mineru.yml`
- Modify: `dist/ragflow-mineru-airgap-v0.26.4-20260708-163537/scripts/deploy-linux.sh`
- Modify: `dist/ragflow-mineru-airgap-v0.26.4-20260708-163537/scripts/verify-linux.sh`
- Delete: `dist/ragflow-mineru-airgap-v0.26.4-20260708-163537/scripts/download-mineru-models-linux.sh`
- Modify: `dist/ragflow-mineru-airgap-v0.26.4-20260708-163537/README.md`

- [ ] **Step 1: Mirror runtime configuration and script changes**

Apply the maintained Compose, deployment, verification, and README behavior to
the unpacked package without rebuilding or modifying any image archive.

- [ ] **Step 2: Run regression tests and verify GREEN**

Run:

```powershell
python -m unittest deploy/ragflow-mineru/tests/test_embedded_models.py -v
```

Expected: all tests PASS.

### Task 4: Validate Scripts, Compose, And Embedded Models

**Files:**
- Verify all modified source and package files

- [ ] **Step 1: Validate shell syntax**

Run `bash -n` for source/package `deploy-linux.sh` and `verify-linux.sh`.
Expected: exit code 0.

- [ ] **Step 2: Validate PowerShell syntax**

Parse `package-windows.ps1` through the PowerShell parser and assert there are
zero syntax errors. Expected: `0`.

- [ ] **Step 3: Render Compose configuration**

Run Docker Compose config with the packaged `.env` and all source/package
Compose files. Inspect the rendered MinerU services. Expected: no `/root`
mount; `/tmp/mineru` and `/data/input` remain.

- [ ] **Step 4: Verify image-owned models**

Run a fresh `mineru:latest` container without a `/root` mount and assert both
configured model directories exist. Expected: `pipeline=True` and `vlm=True`.

- [ ] **Step 5: Run repository regression tests and inspect diff**

Run the new deployment tests and existing Markdown converter tests, then run
`git diff --check`, `git status --short`, and a final `rg` scan for obsolete
external-model instructions. Expected: all tests pass, diff check is clean, and
no maintained or packaged runtime file retains the old mount/helper behavior.
