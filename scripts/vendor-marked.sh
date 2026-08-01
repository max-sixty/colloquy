#!/usr/bin/env bash
# Rebuild plugins/colloquy/skills/colloquy/assets/vendor/marked.esm.js.
#
# marked is zero-dependency and its package export is already one browser-native
# ESM file, so unlike highlight.js there is nothing to bundle: vendoring is a
# copy out of the published package. The runtime renders every message's text
# with it; what it may not do — pass raw HTML through, since a message injects
# widgets only via the event's `markup` field — is configured where it is
# loaded, in colloquy.js, not patched here.
set -euo pipefail

MARKED_VERSION=18.0.7
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/plugins/colloquy/skills/colloquy/assets/vendor/marked.esm.js"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cd "$work"

npm pack "marked@$MARKED_VERSION" >/dev/null
tar xzf "marked-$MARKED_VERSION.tgz"
cp package/lib/marked.esm.js "$OUT"

printf 'wrote %s (%s bytes)\n' "$OUT" "$(wc -c <"$OUT" | tr -d ' ')"
