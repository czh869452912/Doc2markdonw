# Pandoc GFM Math Extension Compatibility Design

## Goal

Restore Markdown-to-Word conversion with the Pandoc 2.17.1.1 version installed
by the service image. The generated Pandoc command must use only reader
extensions supported by the `gfm` reader.

## Root Cause

The converter currently selects this input format:

```text
gfm+tex_math_dollars+tex_math_single_backslash
```

Pandoc 2.17.1.1 supports `tex_math_dollars` for `gfm`, but it does not support
`tex_math_single_backslash`. Pandoc therefore rejects the command before
reading the Markdown input with an unsupported-extension error (exit code 23).

## Chosen Approach

Change the input format to:

```text
gfm+tex_math_dollars
```

This keeps GitHub-Flavored Markdown behavior and preserves `$...$` and
`$$...$$` math syntax. Support for `\(...\)` and `\[...\]` math syntax is not
required.

The converter will not switch to Pandoc's broader `markdown` reader because
that could change GFM tables, task lists, and other existing parsing behavior.
It will not add version-dependent command construction because the unsupported
syntax is not a product requirement.

## Code And Test Changes

- Update `_pandoc_command` to omit `tex_math_single_backslash`.
- Update the command-generation regression test to require the compatible
  input format.
- Run the full converter unit test suite.
- Execute a representative Markdown command with Pandoc 2.17.1.1 to verify the
  selected `gfm+tex_math_dollars` reader accepts dollar-delimited math.

## Scope

This change only fixes reader-extension compatibility. Improvements to
subprocess stderr presentation and unrelated conversion behavior are outside
this fix.
