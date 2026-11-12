from __future__ import annotations

import ast
from pathlib import Path


MARKER = "# Office gateway may change the backend and parse method."
OLD_RETURN = "    return parse_dir"
REPLACEMENT = '''    # Office gateway may change the backend and parse method.
    # Resolve only within this document, and require its Markdown result.
    if not (parse_dir / f"{pdf_name}.md").is_file():
        document_dir = Path(output_dir) / pdf_name
        candidates = sorted(
            path for path in document_dir.iterdir()
            if path.is_dir() and (path / f"{pdf_name}.md").is_file()
        ) if document_dir.is_dir() else []
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            raise ValueError(f"Ambiguous result directories for {pdf_name}: {candidates}")
    return parse_dir'''


def patch_source(source: str) -> str:
    if MARKER in source:
        return source
    tree = ast.parse(source)
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "resolve_parse_dir"
    ]
    if len(functions) != 1:
        raise ValueError("Expected one resolve_parse_dir function")
    function = functions[0]
    lines = source.splitlines(keepends=True)
    last_line = function.end_lineno - 1
    if lines[last_line].rstrip("\r\n") != OLD_RETURN:
        raise ValueError("Unknown resolve_parse_dir implementation; no file changed")
    lines[last_line] = REPLACEMENT + "\n"
    result = "".join(lines)
    ast.parse(result)
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    args.path.write_text(
        patch_source(args.path.read_text(encoding="utf-8")),
        encoding="utf-8",
    )
