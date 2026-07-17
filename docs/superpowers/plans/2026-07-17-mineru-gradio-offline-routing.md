# MinerU Gradio Offline Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose MinerU Gradio at `/mineru-ui/` through the single public port and make its core UI, local PDF preview, upload, conversion, and download workflows independent of internet resources.

**Architecture:** Nginx proxies the prefixed route with Gradio-aware forwarded headers, event-stream settings, and a scoped offline Content Security Policy. A thin `mineru-gradio-offline` image derives from the pinned MinerU image, patches only `gradio-pdf` third-party asset URLs, and sends all conversion requests to `mineru-office-gateway` without starting another model service.

**Tech Stack:** Docker multi-stage builds, MinerU 3.4.2, Gradio 6.8.0, `gradio-pdf` 0.0.24, PDF.js 4.2.67, Nginx 1.27, Docker Compose, Python `unittest`

---

## Prerequisite

Execute `2026-07-17-mineru-office-gateway.md` first. This plan assumes
`mineru-office-gateway:8081`, `docker-compose.office-gateway.yml`, and the
`mineru-office` profile already exist.

## File Map

- `services/mineru-gradio-offline/Dockerfile`: thin UI image and pinned PDF.js asset stage.
- `services/mineru-gradio-offline/patch_gradio_pdf.py`: guarded third-party bundle rewrite.
- `services/mineru-gradio-offline/tests/`: patch and image contract tests.
- `deploy/ragflow-mineru/docker-compose.mineru.yml`: Gradio image, offline environment, and Office gateway API URL.
- `deploy/ragflow-mineru/gateway/nginx.conf.template`: `/mineru-ui/` proxy and scoped CSP.
- Packaging, deployment, verification, and README files: build, save, install, and test the UI image.

### Task 1: Lock The Gradio Deployment Contract In Tests

**Files:**
- Create: `deploy/ragflow-mineru/tests/test_gradio_offline.py`

- [ ] **Step 1: Write failing Compose and Nginx contract tests**

```python
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
STACK = ROOT / "deploy" / "ragflow-mineru"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class GradioOfflineDeploymentTests(unittest.TestCase):
    def test_gradio_uses_offline_image_and_office_gateway(self):
        compose = read(STACK / "docker-compose.mineru.yml")
        self.assertIn("MINERU_GRADIO_IMAGE", compose)
        self.assertIn("GRADIO_ROOT_PATH", compose)
        self.assertIn("GRADIO_ANALYTICS_ENABLED", compose)
        self.assertIn("HF_HUB_OFFLINE", compose)
        self.assertIn("TRANSFORMERS_OFFLINE", compose)
        self.assertIn("http://mineru-office-gateway:8081", compose)

    def test_nginx_exposes_prefixed_gradio_route(self):
        nginx = read(STACK / "gateway" / "nginx.conf.template")
        self.assertIn("location = /mineru-ui", nginx)
        self.assertIn("location /mineru-ui/", nginx)
        self.assertIn("proxy_pass http://mineru-gradio:7860/;", nginx)
        self.assertIn("X-Forwarded-Prefix", nginx)
        self.assertIn("proxy_buffering off", nginx)
        self.assertIn("Content-Security-Policy", nginx)

    def test_gateway_override_keeps_gradio_port_private(self):
        gateway = read(STACK / "docker-compose.gateway.yml")
        self.assertIn("mineru-gradio:\n    ports: []", gateway)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest deploy/ragflow-mineru/tests/test_gradio_offline.py -v`

Expected: FAIL because the route and offline settings do not exist.

- [ ] **Step 3: Commit the failing contract test**

```bash
git add deploy/ragflow-mineru/tests/test_gradio_offline.py
git commit -m "test: define offline Gradio deployment contract"
```

### Task 2: Configure Gradio To Use The Prefixed Route And Office Gateway

**Files:**
- Modify: `deploy/ragflow-mineru/docker-compose.mineru.yml`
- Modify: `deploy/ragflow-mineru/docker-compose.gateway.yml`
- Modify: `deploy/ragflow-mineru/gateway/nginx.conf.template`
- Modify: `deploy/ragflow-mineru/env/airgap.env.example`
- Test: `deploy/ragflow-mineru/tests/test_gradio_offline.py`

- [ ] **Step 1: Change only the Gradio image and runtime contract**

Use this Compose shape for `mineru-gradio`; preserve its volumes, GPU runtime,
ulimits, IPC, and shared-memory settings:

```yaml
  mineru-gradio:
    image: ${MINERU_GRADIO_IMAGE:-mineru-gradio-offline:latest}
    container_name: mineru-gradio
    profiles:
      - mineru-ui
    restart: unless-stopped
    ports:
      - ${MINERU_GRADIO_PORT:-7860}:7860
    environment:
      MINERU_MODEL_SOURCE: ${MINERU_MODEL_SOURCE:-local}
      MINERU_BACKEND: ${MINERU_BACKEND:-pipeline}
      NVIDIA_VISIBLE_DEVICES: ${MINERU_NVIDIA_VISIBLE_DEVICES:-all}
      CUDA_VISIBLE_DEVICES: ${MINERU_CUDA_VISIBLE_DEVICES:-0}
      GRADIO_ROOT_PATH: /mineru-ui
      GRADIO_ANALYTICS_ENABLED: "False"
      GRADIO_SHARE: "False"
      GRADIO_ALLOWED_PATHS: /opt/mineru-ui-assets
      HF_HUB_OFFLINE: "1"
      TRANSFORMERS_OFFLINE: "1"
      DO_NOT_TRACK: "1"
    entrypoint: mineru-gradio
    command:
      - --server-name
      - 0.0.0.0
      - --server-port
      - "7860"
      - --api-url
      - http://mineru-office-gateway:8081
    depends_on:
      - mineru-office-gateway
```

The gateway override continues to clear Gradio's host port. The deployment
script's v1 rewrite also strips the source `ports` block.

- [ ] **Step 2: Add a Gradio-aware Nginx connection map**

Add before `server`:

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    '' close;
}
```

- [ ] **Step 3: Add the prefixed route and scoped offline policy**

```nginx
    location = /mineru-ui {
        return 302 /mineru-ui/;
    }

    location /mineru-ui/ {
        proxy_pass http://mineru-gradio:7860/;
        proxy_http_version 1.1;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Host $http_host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Prefix /mineru-ui;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_buffering off;
        add_header Content-Security-Policy "default-src 'self' data: blob:; connect-src 'self'; img-src 'self' data: blob:; media-src 'self' data: blob:; frame-src 'self'; font-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline' 'unsafe-eval' blob:; worker-src 'self' blob:;" always;
    }
```

Do not apply this CSP to `/`, `/mineru/`, or `/convert/`.

- [ ] **Step 4: Add environment defaults**

```text
MINERU_GRADIO_IMAGE=mineru-gradio-offline:latest
MINERU_GRADIO_ROOT_PATH=/mineru-ui
```

Use `${MINERU_GRADIO_ROOT_PATH:-/mineru-ui}` in Compose rather than duplicating
the literal environment value.

- [ ] **Step 5: Run deployment contract tests**

Run: `python -m unittest deploy/ragflow-mineru/tests/test_gradio_offline.py -v`

Expected: all tests except image/package assertions PASS.

- [ ] **Step 6: Commit routing and runtime settings**

```bash
git add deploy/ragflow-mineru/docker-compose.mineru.yml deploy/ragflow-mineru/docker-compose.gateway.yml deploy/ragflow-mineru/gateway/nginx.conf.template deploy/ragflow-mineru/env/airgap.env.example deploy/ragflow-mineru/tests/test_gradio_offline.py
git commit -m "feat: expose MinerU Gradio through gateway"
```

### Task 3: Guardedly Rewrite Only `gradio-pdf` Asset URLs

**Files:**
- Create: `services/mineru-gradio-offline/patch_gradio_pdf.py`
- Create: `services/mineru-gradio-offline/tests/__init__.py`
- Create: `services/mineru-gradio-offline/tests/test_patch_gradio_pdf.py`

- [ ] **Step 1: Write failing patch tests**

```python
import tempfile
import unittest
from pathlib import Path

from patch_gradio_pdf import CMAP_REMOTE, WORKER_REMOTE, patch_bundle


class PatchGradioPdfTests(unittest.TestCase):
    def test_replaces_each_remote_url_once(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "index.js"
            bundle.write_text(
                f'workerSrc="{WORKER_REMOTE}";cMapUrl="{CMAP_REMOTE}";',
                encoding="utf-8",
            )
            patch_bundle(bundle)
            content = bundle.read_text(encoding="utf-8")
            self.assertNotIn(WORKER_REMOTE, content)
            self.assertNotIn(CMAP_REMOTE, content)
            self.assertIn("./gradio_api/file=/opt/mineru-ui-assets/pdf.worker.min.mjs", content)
            self.assertIn("./gradio_api/file=/opt/mineru-ui-assets/cmaps/", content)

    def test_refuses_unknown_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "index.js"
            bundle.write_text("no expected urls", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "exactly once"):
                patch_bundle(bundle)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd services/mineru-gradio-offline && python -m unittest discover -s tests -v`

Expected: FAIL because `patch_gradio_pdf.py` does not exist.

- [ ] **Step 3: Implement the guarded patcher**

```python
from __future__ import annotations

from importlib import metadata
from pathlib import Path


EXPECTED_GRADIO_PDF_VERSION = "0.0.24"
WORKER_REMOTE = "https://cdn.jsdelivr.net/gh/freddyaboulton/gradio-pdf@main/pdf.worker.min.mjs"
CMAP_REMOTE = "https://huggingface.co/datasets/freddyaboulton/bucket/resolve/main/cmaps/"
WORKER_LOCAL = "./gradio_api/file=/opt/mineru-ui-assets/pdf.worker.min.mjs"
CMAP_LOCAL = "./gradio_api/file=/opt/mineru-ui-assets/cmaps/"


def patch_bundle(bundle: Path) -> None:
    content = bundle.read_text(encoding="utf-8")
    for remote in (WORKER_REMOTE, CMAP_REMOTE):
        if content.count(remote) != 1:
            raise RuntimeError(f"Expected {remote!r} exactly once")
    content = content.replace(WORKER_REMOTE, WORKER_LOCAL)
    content = content.replace(CMAP_REMOTE, CMAP_LOCAL)
    bundle.write_text(content, encoding="utf-8")


def installed_bundle() -> Path:
    if metadata.version("gradio-pdf") != EXPECTED_GRADIO_PDF_VERSION:
        raise RuntimeError(
            f"Expected gradio-pdf {EXPECTED_GRADIO_PDF_VERSION}, got "
            f"{metadata.version('gradio-pdf')}"
        )
    distribution = metadata.distribution("gradio-pdf")
    root = Path(distribution.locate_file(""))
    bundle = root / "gradio_pdf" / "templates" / "component" / "index.js"
    if not bundle.is_file():
        raise RuntimeError(f"Missing gradio-pdf bundle: {bundle}")
    return bundle


if __name__ == "__main__":
    patch_bundle(installed_bundle())
```

- [ ] **Step 4: Run patch tests**

Run: `cd services/mineru-gradio-offline && python -m unittest discover -s tests -v`

Expected: 2 tests PASS.

- [ ] **Step 5: Commit the patcher**

```bash
git add services/mineru-gradio-offline
git commit -m "feat: localize gradio-pdf browser assets"
```

### Task 4: Build The Thin Offline Gradio Image

**Files:**
- Create: `services/mineru-gradio-offline/Dockerfile`
- Create: `services/mineru-gradio-offline/.dockerignore`
- Create: `services/mineru-gradio-offline/tests/test_image_contract.py`

- [ ] **Step 1: Write a failing image contract test**

```python
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ImageContractTests(unittest.TestCase):
    def test_dockerfile_pins_pdfjs_and_derives_from_mineru(self):
        content = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("pdfjs-dist@4.2.67", content)
        self.assertIn("ARG MINERU_BASE_IMAGE", content)
        self.assertIn("FROM ${MINERU_BASE_IMAGE}", content)
        self.assertIn("patch_gradio_pdf.py", content)
        self.assertNotIn("pip install mineru", content)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the image contract test to verify it fails**

Run: `cd services/mineru-gradio-offline && python -m unittest discover -s tests -v`

Expected: FAIL because `Dockerfile` does not exist.

- [ ] **Step 3: Add the multi-stage Dockerfile**

```dockerfile
ARG MINERU_BASE_IMAGE=mineru:latest

FROM node:22-alpine AS pdfjs
WORKDIR /build
RUN npm pack pdfjs-dist@4.2.67 \
    && tar -xzf pdfjs-dist-4.2.67.tgz \
    && test -f package/build/pdf.worker.min.mjs \
    && test -d package/cmaps \
    && test -d package/standard_fonts

FROM ${MINERU_BASE_IMAGE}

COPY --from=pdfjs /build/package/build/pdf.worker.min.mjs /opt/mineru-ui-assets/pdf.worker.min.mjs
COPY --from=pdfjs /build/package/cmaps /opt/mineru-ui-assets/cmaps
COPY --from=pdfjs /build/package/standard_fonts /opt/mineru-ui-assets/standard_fonts
COPY patch_gradio_pdf.py /tmp/patch_gradio_pdf.py

RUN python3 /tmp/patch_gradio_pdf.py \
    && rm /tmp/patch_gradio_pdf.py \
    && test -s /opt/mineru-ui-assets/pdf.worker.min.mjs

ENV GRADIO_ALLOWED_PATHS=/opt/mineru-ui-assets \
    GRADIO_ANALYTICS_ENABLED=False \
    GRADIO_SHARE=False \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    DO_NOT_TRACK=1

LABEL org.doc2markdown.component="mineru-gradio-offline" \
      org.doc2markdown.pdfjs.version="4.2.67" \
      org.doc2markdown.gradio-pdf.version="0.0.24"
```

Use `.dockerignore` containing `.git`, `__pycache__`, `*.pyc`, and `tests`.

- [ ] **Step 4: Run unit and image contract tests**

Run: `cd services/mineru-gradio-offline && python -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 5: Build the thin image**

Run: `docker build --build-arg MINERU_BASE_IMAGE=mineru:latest -t mineru-gradio-offline:test services/mineru-gradio-offline`

Expected: build succeeds without downloading MinerU models again.

- [ ] **Step 6: Verify installed versions and local URLs**

Run:

```bash
docker run --rm --entrypoint python3 mineru-gradio-offline:test -c "from importlib.metadata import version; print(version('mineru'), version('gradio'), version('gradio-pdf'))"
```

Expected: prints MinerU `3.4.2`, Gradio `6.8.0`, and `gradio-pdf` `0.0.24` for
the currently pinned base image.

Run:

```bash
docker run --rm --entrypoint sh mineru-gradio-offline:test -c "grep -R 'cdn.jsdelivr.net/gh/freddyaboulton/gradio-pdf\|huggingface.co/datasets/freddyaboulton/bucket' /usr/local/lib/python3.12/dist-packages/gradio_pdf/templates/component/index.js; test $? -eq 1"
```

Expected: no matching remote URL and exit 0.

- [ ] **Step 7: Verify MinerU package files are unchanged**

Generate sorted SHA-256 lists of `/usr/local/lib/python3.12/dist-packages/mineru`
inside `mineru:latest` and `mineru-gradio-offline:test`, then compare them.

Expected: lists are byte-for-byte identical.

- [ ] **Step 8: Commit the UI image**

```bash
git add services/mineru-gradio-offline/Dockerfile services/mineru-gradio-offline/.dockerignore services/mineru-gradio-offline/tests/test_image_contract.py
git commit -m "build: package offline MinerU Gradio image"
```

### Task 5: Package The Offline UI Image And Profile

**Files:**
- Modify: `deploy/ragflow-mineru/scripts/package-windows.ps1`
- Modify: `deploy/ragflow-mineru/tests/test_gradio_offline.py`
- Modify: `deploy/ragflow-mineru/env/airgap.env.example`

- [ ] **Step 1: Add failing package contract assertions**

Assert the packaging script exposes `MineruGradioImage`, copies
`services/mineru-gradio-offline`, builds it with `MINERU_BASE_IMAGE`, sets the
environment image value, saves it through Compose image discovery, records it
in `manifest.json`, and includes `mineru-ui` in recommended profiles.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest deploy/ragflow-mineru/tests/test_gradio_offline.py -v`

Expected: FAIL on missing package behavior.

- [ ] **Step 3: Add package parameters and build ordering**

Add:

```powershell
[string]$MineruGradioImage = "mineru-gradio-offline:latest",
[switch]$SkipMineruGradioBuild,
```

After the optional MinerU base build, detect whether `mineru-ui` appears in
`COMPOSE_PROFILES`. When enabled and not skipped, build the UI image:

```powershell
$gradioSource = Join-Path $RepoRoot "services\mineru-gradio-offline"
Invoke-Checked -FilePath "docker" -Arguments @(
    "build",
    "--build-arg", "MINERU_BASE_IMAGE=$MineruImage",
    "-t", $MineruGradioImage,
    $gradioSource
)
```

Copy the source to `mineru-gradio-offline-source`, set
`MINERU_GRADIO_IMAGE`, and record `mineruGradioImage` in the manifest.

- [ ] **Step 4: Make UI enablement explicit**

Keep API-only packaging supported. The recommended `-BuildMineru` command uses
profiles:

```text
infinity,gpu,mineru,mineru-office,mineru-ui,md-convert,gateway
```

If `mineru-ui` is selected with `-SkipMineruGradioBuild`, packaging must require
the requested UI image to exist locally and fail with a specific message when
it does not.

- [ ] **Step 5: Run package contract tests**

Run: `python -m unittest deploy/ragflow-mineru/tests/test_gradio_offline.py -v`

Expected: all tests PASS.

- [ ] **Step 6: Run a package configuration smoke test**

Run the packaging script with `-SkipImageSave -NoArchive` and existing local
images. Inspect the generated `.env`, Compose files, and `manifest.json`.

Expected: `mineru-ui` is enabled, `MINERU_GRADIO_IMAGE` is present, and Compose
image discovery lists the offline UI image.

- [ ] **Step 7: Commit packaging changes**

```bash
git add deploy/ragflow-mineru/scripts/package-windows.ps1 deploy/ragflow-mineru/env/airgap.env.example deploy/ragflow-mineru/tests/test_gradio_offline.py
git commit -m "build: package offline MinerU Gradio UI"
```

### Task 6: Extend Deployment Verification And Documentation

**Files:**
- Modify: `deploy/ragflow-mineru/scripts/deploy-linux.sh`
- Modify: `deploy/ragflow-mineru/scripts/verify-linux.sh`
- Modify: `deploy/ragflow-mineru/README.md`
- Modify: `README.md`
- Modify: `deploy/ragflow-mineru/tests/test_gradio_offline.py`

- [ ] **Step 1: Add failing endpoint and documentation assertions**

Assert the deployment summary prints `/mineru-ui/`. Assert verification reads
`COMPOSE_PROFILES`, checks the UI only when `mineru-ui` is enabled, curls the
prefixed page, verifies the container has no published port, and tails Gradio
logs. Assert README documents the endpoint, offline limitations, image pinning,
profile opt-out, and Office conversion behavior.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest deploy/ragflow-mineru/tests/test_gradio_offline.py -v`

Expected: FAIL on missing summary, verification, and documentation text.

- [ ] **Step 3: Add deployment output**

Print:

```bash
echo "MinerU Gradio:  http://<server>:${PUBLIC_PORT}/mineru-ui/"
```

Use the script's existing `.env` lookup expression rather than introducing a
second parser.

- [ ] **Step 4: Add conditional Linux verification**

When `COMPOSE_PROFILES` contains `mineru-ui`:

```bash
echo "Checking gateway MinerU Gradio route..."
curl -fsS "http://127.0.0.1:${PUBLIC_PORT}/mineru-ui/" >/tmp/mineru-gradio.html
grep -Fq 'window.gradio_config' /tmp/mineru-gradio.html
if docker port mineru-gradio | grep -q .; then
  echo "mineru-gradio must not publish a host port" >&2
  exit 1
fi
docker exec mineru-gradio test -s /opt/mineru-ui-assets/pdf.worker.min.mjs
echo "MinerU Gradio is reachable through the gateway."
```

Remove `/tmp/mineru-gradio.html` before the script exits and tail the last 40
Gradio log lines.

- [ ] **Step 5: Document supported offline behavior**

State that PDF preview, upload, conversion, and download work offline; Office
conversion goes through the Office gateway; the current Microsoft Office Online
iframe is blocked and unavailable; remote project links are informational; and
port 7860 remains private.

- [ ] **Step 6: Run deployment tests**

Run: `python -m unittest discover -s deploy/ragflow-mineru/tests -v`

Expected: all deployment tests PASS.

- [ ] **Step 7: Validate shell syntax**

Run: `bash -n deploy/ragflow-mineru/scripts/deploy-linux.sh`

Expected: exit 0.

Run: `bash -n deploy/ragflow-mineru/scripts/verify-linux.sh`

Expected: exit 0.

- [ ] **Step 8: Commit verification and documentation**

```bash
git add README.md deploy/ragflow-mineru/README.md deploy/ragflow-mineru/scripts/deploy-linux.sh deploy/ragflow-mineru/scripts/verify-linux.sh deploy/ragflow-mineru/tests/test_gradio_offline.py
git commit -m "docs: verify offline MinerU Gradio access"
```

### Task 7: Run End-To-End Offline Browser Verification

**Files:**
- Modify only if a verified defect requires a focused fix in files from Tasks 2-6.

- [ ] **Step 1: Start the complete local stack**

Enable profiles:

```text
infinity,gpu,mineru,mineru-office,mineru-ui,md-convert,gateway
```

Start with the same five Compose files used by deployment. Wait for Router,
Office gateway, Gradio, and Nginx health checks.

- [ ] **Step 2: Verify prefixed HTTP resources**

Run:

```bash
curl -fsS http://127.0.0.1:18080/mineru-ui/ -o /tmp/mineru-ui.html
grep -F 'http://127.0.0.1:18080/mineru-ui' /tmp/mineru-ui.html
curl -fsS http://127.0.0.1:18080/mineru/health
```

Expected: UI HTML contains the prefixed Gradio root and Office gateway health
is OK.

- [ ] **Step 3: Inspect the UI with the in-app Browser**

Open `http://127.0.0.1:18080/mineru-ui/`. Confirm the page is nonblank, upload
controls and conversion options are visible, no content overlaps at 1440x900
and 390x844, and the console has no error that blocks a core workflow.

- [ ] **Step 4: Prove required browser requests are local**

Record browser network requests while loading the page and previewing a local
PDF. Fail verification if a required request targets jsDelivr, Hugging Face,
Google Fonts, Font Awesome, Microsoft Office Online, GitHub raw content, or
Gradio S3. Informational link clicks are excluded because the user initiates
navigation.

Expected: PDF worker and CMaps load beneath `/mineru-ui/gradio_api/file=`.

- [ ] **Step 5: Exercise PDF and Office conversion**

Upload a PDF, verify its preview renders, convert it, and download the result.
Upload DOCX and DOC fixtures, verify conversion completes through the Office
gateway, and download each result. Confirm the Office iframe is blocked without
preventing conversion.

- [ ] **Step 6: Verify private ports and model reuse**

Run: `docker ps --format 'table {{.Names}}\t{{.Ports}}'`

Expected: only the gateway publishes `PUBLIC_PORT`; neither 7860, 8002, nor
8081 is published.

Inspect logs and process lists. Expected: Gradio calls
`mineru-office-gateway:8081` and does not start a reusable local `mineru-api`.

- [ ] **Step 7: Run the full regression suite**

Run: `python -m unittest discover -s services/mineru-office-gateway/tests -v`

Expected: all Office gateway tests PASS.

Run: `python -m unittest discover -s services/mineru-gradio-offline/tests -v`

Expected: all offline UI image tests PASS.

Run: `python -m unittest discover -s deploy/ragflow-mineru/tests -v`

Expected: all deployment tests PASS.

Run: `python -m unittest discover -s services/md-convert/tests -v`

Expected: all Markdown Convert tests PASS.

- [ ] **Step 8: Review the completed branch**

Run: `git status --short`

Expected: no output.

Run: `git log --oneline --max-count=10`

Expected: shows the focused Gradio commits above the Office gateway and design
commits.
