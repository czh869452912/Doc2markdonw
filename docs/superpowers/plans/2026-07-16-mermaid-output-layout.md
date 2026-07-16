# Mermaid Output And Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-job Mermaid rendering controls and keep rendered diagrams legible and inside paged document bounds.

**Architecture:** The converter validates explicit Mermaid enums, renders structured PNG/SVG results through Kroki, computes one physical display dimension, and passes it through a private image-title marker to a bundled Pandoc Lua filter. The native frontend exposes only format, engine, direction, and flowchart-density controls.

**Tech Stack:** Python 3.12 standard library, requests, Pandoc 2.17.1.1 Lua filters, Kroki Mermaid, FastAPI, vanilla HTML/CSS/JavaScript, `unittest`

---

### Task 1: Define validated Mermaid options and auto format mapping

**Files:**
- Modify: `services/md-convert/app/converter.py`
- Modify: `services/md-convert/app/jobs.py`
- Modify: `services/md-convert/app/main.py`
- Modify: `services/md-convert/tests/test_converter.py`

- [ ] **Step 1: Write failing enum and auto-mapping tests**

Test wished-for `MermaidFormat`, `MermaidDirection`, `MermaidDensity`, validation
helpers, and `resolve_mermaid_format(request)` with this mapping:

```python
word_targets = [OutputFormat.DOCX, OutputFormat.DOC, OutputFormat.PDF]
vector_targets = [OutputFormat.HTML, OutputFormat.ODT, OutputFormat.EPUB]
```

Assert invalid strings raise a `ValueError` listing supported values.

- [ ] **Step 2: Run the focused tests and verify RED**

```powershell
$env:PYTHONPATH = 'services/md-convert'
python services/md-convert/tests/test_converter.py -v
```

Expected: import failures for the new enums/helpers.

- [ ] **Step 3: Implement enums and propagate options**

Extend `ConversionRequest` with defaults:

```python
mermaid_format: MermaidFormat = MermaidFormat.AUTO
mermaid_direction: MermaidDirection = MermaidDirection.SOURCE
mermaid_density: MermaidDensity = MermaidDensity.STANDARD
```

Add optional form fields with API validation, save them in RQ options, and
revalidate them in `run_conversion_job`. Use `MERMAID_OUTPUT_FORMAT` only when
the client omits `mermaid_format`.

- [ ] **Step 4: Run focused and full tests**

```powershell
$env:PYTHONPATH = 'services/md-convert'
python services/md-convert/tests/test_converter.py -v
python -m unittest discover -s services/md-convert/tests -v
```

Expected: all tests pass.

### Task 2: Add direction rewriting and density options

**Files:**
- Create: `services/md-convert/tests/test_mermaid_options.py`
- Modify: `services/md-convert/app/converter.py`

- [ ] **Step 1: Write failing direction and density tests**

Cover `flowchart LR`, `graph TD`, frontmatter followed by `flowchart`, no-op
sequence diagrams, and no-op source mode. Assert density options are exactly:

```python
compact = {
    "flowchart_node-spacing": "30",
    "flowchart_rank-spacing": "35",
    "flowchart_wrapping-width": "160",
}
standard = {}
spacious = {
    "flowchart_node-spacing": "70",
    "flowchart_rank-spacing": "80",
    "flowchart_wrapping-width": "240",
}
```

- [ ] **Step 2: Run tests and verify RED**

```powershell
$env:PYTHONPATH = 'services/md-convert'
python -m unittest services/md-convert/tests/test_mermaid_options.py -v
```

Expected: missing helper failures.

- [ ] **Step 3: Implement safe rewrite and mapping helpers**

Use a multiline, line-anchored expression that only replaces direction tokens
after `flowchart` or `graph`. Preserve all other text. Merge density options
with the existing `layout` Kroki parameter.

- [ ] **Step 4: Run focused tests**

```powershell
$env:PYTHONPATH = 'services/md-convert'
python -m unittest services/md-convert/tests/test_mermaid_options.py -v
```

Expected: all option tests pass.

### Task 3: Return validated structured render results

**Files:**
- Create: `services/md-convert/tests/test_image_dimensions.py`
- Modify: `services/md-convert/app/converter.py`

- [ ] **Step 1: Write failing PNG/SVG dimension tests**

Test `read_png_dimensions` with a minimal PNG IHDR, and
`read_svg_dimensions` with viewBox, pixel dimensions, and physical units.
Assert invalid signatures, empty SVG, missing dimensions, and mismatched Kroki
content types raise a specific `MermaidRenderError`.

- [ ] **Step 2: Run tests and verify RED**

```powershell
$env:PYTHONPATH = 'services/md-convert'
python -m unittest services/md-convert/tests/test_image_dimensions.py -v
```

Expected: missing structured render APIs.

- [ ] **Step 3: Implement `RenderedDiagram` and validation**

Add:

```python
@dataclass(frozen=True)
class RenderedDiagram:
    path: Path
    image_format: MermaidFormat
    width_px: float
    height_px: float
```

Parse PNG with `struct`, SVG with `xml.etree.ElementTree`, validate HTTP status,
content type, non-empty content, signature, and dimensions before writing the
target file. Include a bounded Kroki response excerpt in HTTP errors.

- [ ] **Step 4: Run image and full tests**

```powershell
$env:PYTHONPATH = 'services/md-convert'
python -m unittest services/md-convert/tests/test_image_dimensions.py -v
python -m unittest discover -s services/md-convert/tests -v
```

Expected: all tests pass.

### Task 4: Compute page-aware display dimensions

**Files:**
- Create: `services/md-convert/tests/test_mermaid_sizing.py`
- Modify: `services/md-convert/app/converter.py`

- [ ] **Step 1: Write failing page-box and sizing tests**

Create minimal reference DOCX ZIPs containing `w:pgSz` and `w:pgMar`. Cover
portrait/landscape page boxes, invalid DOCX fallback, wide/tall images, PNG's
150 PPI quality box, SVG's 96 PPI natural box, and no aspect distortion.

- [ ] **Step 2: Run tests and verify RED**

```powershell
$env:PYTHONPATH = 'services/md-convert'
python -m unittest services/md-convert/tests/test_mermaid_sizing.py -v
```

Expected: missing page sizing helpers.

- [ ] **Step 3: Implement page and image sizing**

Add immutable `PageBox` and `ImageDimension` values. Parse final `w:sectPr`
values in twips, fall back to 6.3 by 8.5 inches, limit both axes to 90%, use
150 PPI for PNG and 96 PPI for SVG, and emit exactly one width or height value
in inches.

- [ ] **Step 4: Run sizing tests**

```powershell
$env:PYTHONPATH = 'services/md-convert'
python -m unittest services/md-convert/tests/test_mermaid_sizing.py -v
```

Expected: all sizing tests pass.

### Task 5: Apply dimensions through a Pandoc Lua filter

**Files:**
- Create: `services/md-convert/app/filters/mermaid_size.lua`
- Create: `services/md-convert/tests/test_mermaid_filter.py`
- Modify: `services/md-convert/app/converter.py`
- Modify: `services/md-convert/tests/test_converter.py`

- [ ] **Step 1: Write failing marker and command tests**

Assert preprocessing emits an exact marker such as
`md-convert-mermaid:width=5.8in`, ordinary images are unchanged, and every
Pandoc command includes `--lua-filter` with the bundled filter path.

- [ ] **Step 2: Run tests and verify RED**

```powershell
$env:PYTHONPATH = 'services/md-convert'
python -m unittest services/md-convert/tests/test_mermaid_filter.py -v
python services/md-convert/tests/test_converter.py -v
```

Expected: marker/filter assertions fail.

- [ ] **Step 3: Implement marker emission and Lua filtering**

The Lua `Image` function must match only titles shaped as
`md-convert-mermaid:(width|height)=<positive decimal>in`, clear the title, and
set only the validated attribute. Malformed markers and normal image titles
pass through unchanged.

- [ ] **Step 4: Run unit and Pandoc 2.17 integration tests**

Use `pandoc/core:2.17.1.1` to convert marked and unmarked images to native AST,
asserting only the marked image receives a dimension attribute. Then run the
full Python suite.

### Task 6: Capture actionable subprocess errors

**Files:**
- Create: `services/md-convert/tests/test_conversion_errors.py`
- Modify: `services/md-convert/app/converter.py`

- [ ] **Step 1: Write a failing subprocess error test**

Patch `subprocess.run` to raise `CalledProcessError` with stderr
`The extension x is not supported` and assert the public exception contains the
executable, exit code, and stderr without dumping unbounded output.

- [ ] **Step 2: Implement `ConversionCommandError` and captured execution**

Run commands with `capture_output=True`, `text=True`, catch
`CalledProcessError`, truncate stderr to a documented bound, and raise the
domain exception from the original error.

- [ ] **Step 3: Run error and full tests**

```powershell
$env:PYTHONPATH = 'services/md-convert'
python -m unittest services/md-convert/tests/test_conversion_errors.py -v
python -m unittest discover -s services/md-convert/tests -v
```

Expected: all tests pass.

### Task 7: Add the compact frontend controls

**Files:**
- Modify: `services/md-convert/app/static/index.html`
- Modify: `services/md-convert/app/static/app.js`
- Modify: `services/md-convert/app/static/styles.css`

- [ ] **Step 1: Add format, direction, and density selects**

Use IDs/names `mermaid_format`, `mermaid_direction`, and `mermaid_density` with
the approved values and defaults. Keep the existing layout select. Group all
four controls under the current Mermaid rendering checkbox without nested
cards or explanatory copy.

- [ ] **Step 2: Disable dependent controls with Mermaid rendering**

Add one function that toggles the four controls' `disabled` property on initial
load and checkbox changes. FormData continues to submit enabled values.

- [ ] **Step 3: Verify JavaScript and responsive layout**

```powershell
node --check services/md-convert/app/static/app.js
```

Use the in-app browser at desktop and mobile sizes to verify labels fit,
controls do not overlap, disabled states are clear, and job submission includes
all values.

### Task 8: Update deployment/package defaults and run integration checks

**Files:**
- Modify: `deploy/ragflow-mineru/docker-compose.md-convert.yml`
- Modify: `deploy/ragflow-mineru/env/airgap.env.example`
- Modify: `deploy/ragflow-mineru/README.md`
- Update ignored package source under `dist/ragflow-mineru-airgap-v0.26.4-20260708-163537/`

- [ ] **Step 1: Change maintained defaults to auto**

Set `MERMAID_OUTPUT_FORMAT=auto` in examples and Compose fallbacks. Document
auto mapping, format/direction/density fields, SVG compatibility, and PNG's
150 PPI sizing policy.

- [ ] **Step 2: Synchronize the unpacked offline package**

Copy updated `services/md-convert` application source, tests, requirements, and
Dockerfile into `md-convert-source`; copy maintained Compose/docs into the
package while leaving existing image TAR archives unchanged.

- [ ] **Step 3: Run complete verification**

```powershell
$env:PYTHONPATH = 'services/md-convert'
python -m unittest discover -s services/md-convert/tests -v
node --check services/md-convert/app/static/app.js
git diff --check
```

Render representative PNG and SVG Mermaid diagrams through Kroki, convert a
PNG-auto DOCX with Pandoc 2.17.1.1, inspect `word/media` and drawing extents,
and confirm the output opens with a visible diagram.
