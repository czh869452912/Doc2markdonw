# Mermaid Output And Layout Design

## Goal

Improve Mermaid rendering in generated documents without turning the existing
single-page converter into a complex editor. Word output must work in clients
that cannot display embedded SVG, raster output must remain legible, and
oversized diagrams must fit inside the usable page area.

## Scope

This design adds:

- Per-job Mermaid image format, layout engine, flow direction, and flowchart
  density controls.
- Output-aware SVG/PNG selection.
- Mermaid-only image sizing for paged documents.
- Focused frontend controls in the existing HTML form.

It does not add a visual Mermaid editor, automatic direction heuristics, a
custom Kroki image, synthetic PNG upscaling, or direct OOXML SVG fallback
manipulation.

## Chosen Approach

Use Kroki's native Mermaid SVG and PNG endpoints. In `auto` mode, DOCX, DOC,
and PDF use PNG for broad compatibility; HTML, ODT, and EPUB use SVG. PNG is
rendered by Kroki's Chromium-based Mermaid companion so HTML labels remain
correct. PDF uses PNG because the service's Pandoc 2.17 and XeLaTeX path would
otherwise require an additional SVG-to-PDF executable that the image does not
explicitly install.

The service will not claim to produce a synthetic 2x PNG. Kroki's Mermaid PNG
implementation screenshots the rendered container at its configured browser
viewport and does not expose a supported per-request device-scale option.
Instead, the converter keeps PNG output at an effective display resolution of
at least 150 PPI by limiting its physical size in the output document. This
prevents a small PNG from being enlarged until it becomes visibly blurry.

## Per-Job Mermaid Options

The conversion request gains these validated values:

```text
mermaid_format: auto | png | svg
mermaid_layout: elk | dagre
mermaid_direction: source | tb | lr
mermaid_density: compact | standard | spacious
```

Defaults are `auto`, `elk`, `source`, and `standard`. Invalid values fail at the
API boundary with HTTP 400 and are validated again when a worker reconstructs
the request.

`MERMAID_OUTPUT_FORMAT` remains the service-level default for API clients that
omit `mermaid_format`, and it accepts `auto`, `png`, or `svg`. Deployment
examples default it to `auto`.

### Output Format

The `auto` mapping is:

| Target | Mermaid image |
| --- | --- |
| DOCX, DOC, PDF | PNG |
| HTML, ODT, EPUB | SVG |

Explicit `png` and `svg` selections override the mapping for every target.

### Layout Engine

The existing ELK/Dagre option remains a Kroki Mermaid `layout` diagram option.
ELK stays the default because it handles larger and more complex flowcharts
well. The converter does not silently change the selected engine based on
diagram size.

### Flow Direction

`source` preserves the diagram exactly. `tb` and `lr` rewrite only the first
valid, line-anchored `flowchart` or `graph` declaration in a Mermaid block. The
rewrite handles `TB`, `TD`, `BT`, `RL`, and `LR` source directions and replaces
them with `TB` or `LR`.

Frontmatter and comments are preserved. Sequence, state, class, Gantt, ER, and
other Mermaid diagram types are never rewritten. If no supported declaration
is found, the diagram remains unchanged.

### Flowchart Density

Density is intentionally limited to flowchart options and is labeled
"Flowchart density" in the UI. Kroki diagram options use these presets:

| Preset | nodeSpacing | rankSpacing | wrappingWidth |
| --- | ---: | ---: | ---: |
| compact | 30 | 35 | 160 |
| standard | Mermaid defaults | Mermaid defaults | Mermaid defaults |
| spacious | 70 | 80 | 240 |

The standard preset sends no spacing overrides. This preserves Mermaid's
version-specific defaults.

## Rendering And Image Metadata

### Render Result

The Mermaid renderer returns a structured result containing:

- Image path relative to the job directory
- Actual format
- Pixel width and height for PNG
- Intrinsic width, height, and viewBox-derived aspect ratio for SVG

PNG dimensions are read from the PNG header. SVG is parsed with a structured
XML parser; the viewBox is preferred when present, with width and height as a
fallback. Empty responses, mismatched response content types, invalid image
signatures, and unreadable dimensions fail the job with a specific conversion
error.

### Available Page Area

When a reference DOCX is uploaded, the converter reads the final Word section's
`w:pgSz` and `w:pgMar` values from `word/document.xml` and converts twips into
inches. The usable box is page width and height minus their corresponding
margins.

If there is no reference file, or its page metadata cannot be read, the
converter uses a conservative 6.3 by 8.5 inch usable box. Page metadata parsing
failure falls back to these dimensions and does not fail an otherwise valid
conversion.

### Display Size Calculation

Mermaid images may occupy at most 90% of the usable page width and 90% of the
usable page height. Aspect ratio is always preserved.

For PNG, its quality-limited size is calculated at 150 PPI:

```text
quality width  = pixel width / 150
quality height = pixel height / 150
```

The selected display size is the largest proportional size that fits both the
page box and quality box. The service never enlarges PNG beyond the 150 PPI
quality floor.

For SVG, there is no raster quality limit. The intrinsic CSS-pixel size is
interpreted at 96 PPI and reduced only when needed to fit the page box. Small
SVG diagrams are not enlarged automatically.

The sizing code selects one dimension, width or height, for Pandoc and lets the
writer infer the other dimension. It never writes both dimensions, avoiding
distortion.

### Pandoc Integration

Generated Mermaid image links carry a private title marker containing one
validated physical dimension, for example:

```text
![Mermaid diagram](diagram-1.png "md-convert-mermaid:width=5.8in")
```

A bundled Lua filter recognizes only the exact `md-convert-mermaid` marker,
validates its dimension again, removes the private title, and assigns the image
width or height attribute. Ordinary Markdown images pass through unchanged.

The filter is added to Pandoc commands for all output targets, but it is inert
when a document has no marked Mermaid images. The existing GFM reader remains
unchanged.

## Frontend Design

The current page structure and visual style remain. Mermaid controls are
grouped together in the conversion form without a wizard, modal, preview, or
additional page.

The controls are:

- Render Mermaid: checkbox
- Image format: Auto, PNG, SVG
- Layout engine: ELK, Dagre
- Flow direction: Preserve source, Prefer vertical, Prefer horizontal
- Flowchart density: Compact, Standard, Spacious

When Mermaid rendering is disabled, the four dependent controls are disabled.
The frontend submits all current values explicitly.

## API And Worker Data Flow

```text
Browser submits Markdown plus Mermaid options
  -> API validates values and stores complete options in the RQ job
  -> worker validates options and preprocesses each Mermaid block
  -> direction rewrite and density options are applied
  -> Kroki renders the selected PNG or SVG format
  -> image dimensions and page bounds determine display size
  -> Markdown receives the private Mermaid size marker
  -> Pandoc Lua filter converts the marker into an image attribute
```

The original uploaded Markdown remains in `source.md`. Direction overrides and
private markers exist only in the generated `input.md` inside the job working
directory.

## Error Handling

- API enum validation returns HTTP 400 with the invalid field and supported
  values.
- Kroki HTTP failures include response status and a bounded response excerpt.
- Kroki output must be non-empty and match the expected content type and image
  signature.
- Invalid image dimensions fail with the diagram filename and format.
- Unsupported direction overrides preserve the source diagram.
- Reference DOCX page parsing falls back to safe dimensions.
- Pandoc subprocess failures include the executable, exit code, and captured
  stderr in the RQ failure information.

## Compatibility And Migration

- Existing API clients remain valid because all new form fields are optional.
- Existing DOCX, DOC, PDF, HTML, ODT, and EPUB target behavior remains except
  for the `auto` Mermaid image selection.
- DOC conversion applies sizing in the intermediate DOCX before LibreOffice
  converts it to DOC.
- Explicit SVG remains available for modern Word clients.
- Deployment source, packaged `md-convert-source`, Compose environment
  examples, and maintained documentation use the same defaults.

## Validation

Automated tests will cover:

1. Enum defaults, accepted values, and API rejection of invalid values.
2. Auto output mapping for every target format.
3. Flowchart direction rewrites with comments and frontmatter, plus no-op
   behavior for other Mermaid diagram types.
4. Density-to-Kroki option mapping and standard no-override behavior.
5. PNG and SVG dimension extraction, invalid image rejection, and content-type
   validation.
6. Wide, tall, small, and oversized image fitting without aspect distortion.
7. Reference DOCX page and margin parsing with safe fallback.
8. Lua filter behavior for marked Mermaid images and ordinary images using
   Pandoc 2.17.1.1.
9. Regression coverage for DOCX, DOC, PDF, HTML, ODT, and EPUB plans.
10. Browser behavior for defaults, disabled Mermaid controls, submission, and
    responsive layout.
11. Real Kroki Mermaid PNG and SVG rendering for representative compact,
    standard, horizontal, and vertical flowcharts.

## References

- Mermaid flowchart directions and renderers:
  https://mermaid.js.org/syntax/flowchart.html
- Mermaid flowchart spacing configuration:
  https://mermaid.js.org/config/schema-docs/config-defs-flowchart-diagram-config.html
- Kroki Mermaid diagram options:
  https://docs.kroki.io/kroki/setup/diagram-options/
- Kroki Mermaid Chromium screenshot implementation:
  https://github.com/yuzutech/kroki/blob/main/mermaid/src/worker.js
- Pandoc image dimensions:
  https://pandoc.org/demo/example33/8.17-images.html
- Pandoc SVG conversion for direct PDF output:
  https://github.com/jgm/pandoc/issues/8334
