#!/usr/bin/env bash
# Re-record docs/demo.gif by driving the shipped page, server, and browser.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec uv run "$HERE/record-demo.py" "$@"
