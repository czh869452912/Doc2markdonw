#!/bin/sh
set -eu

if [ -n "${OFFICE_EXTRA_FONT_DIR:-}" ] && [ -d "$OFFICE_EXTRA_FONT_DIR" ]; then
    fc-cache -f "$OFFICE_EXTRA_FONT_DIR"
fi

exec "$@"
