# Pandoc GFM Math Extension Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Markdown-to-Word conversion compatible with the Pandoc 2.17.1.1 `gfm` reader while retaining dollar-delimited math.

**Architecture:** Keep the existing Pandoc command builder and change only its reader extension list. Lock the compatible command in the existing unit test, then verify the reader with the same Pandoc version used by the service image.

**Tech Stack:** Python 3.12, `unittest`, Pandoc 2.17.1.1, Docker

---

### Task 1: Remove the unsupported GFM reader extension

**Files:**
- Modify: `services/md-convert/tests/test_converter.py`
- Modify: `services/md-convert/app/converter.py`

- [x] **Step 1: Change the command-generation test to require the compatible reader**

In `test_build_conversion_plan_generates_docx_pandoc_command`, replace the
reader string in the expected command with:

```python
"gfm+tex_math_dollars",
```

- [x] **Step 2: Run the focused test to verify it fails**

Run:

```powershell
$env:PYTHONPATH = 'services/md-convert'
python services/md-convert/tests/test_converter.py ConverterTests.test_build_conversion_plan_generates_docx_pandoc_command -v
```

Expected: `FAIL`; the actual command still contains
`gfm+tex_math_dollars+tex_math_single_backslash`.

- [x] **Step 3: Implement the minimal command change**

In `_pandoc_command` in `services/md-convert/app/converter.py`, set the reader
argument to:

```python
"gfm+tex_math_dollars",
```

- [x] **Step 4: Run the complete converter test suite**

Run:

```powershell
$env:PYTHONPATH = 'services/md-convert'
python -m unittest discover -s services/md-convert/tests -v
```

Expected: all six converter tests pass.

- [x] **Step 5: Verify the reader with Pandoc 2.17.1.1**

Run:

```powershell
@'
# Math

Inline: $E=mc^2$
'@ | docker run -i --rm pandoc/core:2.17.1.1 --from gfm+tex_math_dollars --to native
```

Expected: exit code `0`, with a Pandoc AST containing `Math InlineMath
"E=mc^2"`.

- [x] **Step 6: Check the final diff and commit the fix**

Run:

```powershell
git diff --check
git diff -- services/md-convert/app/converter.py services/md-convert/tests/test_converter.py
git add services/md-convert/app/converter.py services/md-convert/tests/test_converter.py docs/superpowers/plans/2026-07-14-pandoc-gfm-math-extension.md
git commit -m "fix: use supported pandoc gfm math extension"
```

Expected: no whitespace errors; the diff removes only
`tex_math_single_backslash` from the command and its expected test value.
