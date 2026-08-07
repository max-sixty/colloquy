#!/usr/bin/env bash
# Run the suite where CI runs it. Everything else here is macOS, and what the two
# platforms disagree about is exactly what a browser test measures: how wide a system
# font sets a word, and whether a scrollbar takes a gutter out of the window. Nine tests
# failed on the runner from the day CI landed and none of them could be reproduced.
#
#   scripts/linux-suite.sh
#   scripts/linux-suite.sh tests/test_render.py -k a_press   # or any pytest arguments
#
# Needs a Docker daemon that can run linux/amd64 (linux-suite.Dockerfile says why). On
# Apple silicon that is `colima start --vm-type vz --vz-rosetta`.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

if [ $# -eq 0 ]; then set -- tests; fi

docker build --platform linux/amd64 -t colloquy-linux-suite \
  -f "$HERE/linux-suite.Dockerfile" "$HERE"

# --shm-size, because Chrome's default 64MB there is where a tab dies mid-suite. The
# named volume is uv's cache, which the run fills once: the suite runs uv offline, so
# everything it drives has to be there already, and `version export` is what fetches the
# one thing `uv.lock` doesn't cache (README, "Developing").
exec docker run --rm --platform linux/amd64 --shm-size=2g \
  -v "$ROOT:/repo" -v colloquy-linux-suite-uv:/root/.cache/uv \
  colloquy-linux-suite bash -c \
  'plugins/colloquy/bin/colloquy version export --help >/dev/null
   exec uv run --frozen pytest "$@"' bash "$@"
