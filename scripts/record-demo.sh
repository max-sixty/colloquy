#!/usr/bin/env bash
# Re-record docs/demo.gif by driving the shipped page, server, and browser.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# `--project` because the recorder runs in the suite's environment (pyproject.toml
# says why), which uv would otherwise look for from wherever this was called.
exec uv run --project "$HERE/.." "$HERE/record-demo.py" "$@"
