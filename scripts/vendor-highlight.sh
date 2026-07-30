#!/usr/bin/env bash
# Rebuild skills/colloquy/assets/vendor/highlight.esm.js.
#
# Unlike mermaid and Sortable, upstream ships no browser-native ESM build: the
# `es/` directory re-exports CommonJS and only resolves through a bundler. So the
# vendored file is one we produce — core plus exactly the languages the registry
# enumerates, bundled to ESM and minified. Each language registers under
# colloquy's own name (`html`, not hljs's `xml`), so the page's vocabulary and
# the tokenizer's cannot drift: `lang="html"` either resolves or the bundle was
# built from a different list than the registry states.
#
# The language list is not stated here: it is read out of registry.json's
# `$languages.names`, which is the list `version check` refuses an unknown language against
# and the list the catalog shows Claude. One list, so the bundle cannot offer a
# language the lint rejects or lack one it accepts. Add a language there, then rerun
# this.
set -euo pipefail

HLJS_VERSION=11.11.1
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ASSETS="$ROOT/skills/colloquy/assets"
OUT="$ASSETS/vendor/highlight.esm.js"

# Where colloquy's name for a language differs from highlight.js's module. Every
# other name maps to itself.
ALIAS_html=xml
ALIAS_toml=ini

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cd "$work"

npm pack "highlight.js@$HLJS_VERSION" >/dev/null
tar xzf "highlight.js-$HLJS_VERSION.tgz"

languages=$(python3 -c '
import json, sys
print(" ".join(json.load(open(sys.argv[1]))["$languages"]["names"]))
' "$ASSETS/registry.json")

{
  echo "/*! highlight.js $HLJS_VERSION — BSD-3-Clause — https://highlightjs.org */"
  echo 'import hljs from "./package/lib/core.js";'
  for name in $languages; do
    alias_var="ALIAS_$name"
    echo "import $name from \"./package/es/languages/${!alias_var:-$name}.js\";"
  done
  # Registered under colloquy's name, not highlight.js's, so `lang="html"` resolves
  # without a translation table living anywhere at runtime.
  for name in $languages; do
    echo "hljs.registerLanguage(\"$name\", $name);"
  done
  echo 'export default hljs;'
} >entry.mjs

npx --yes esbuild@0.25 entry.mjs \
  --bundle --format=esm --minify --legal-comments=inline --outfile="$OUT"

printf 'wrote %s (%s bytes)\n' "$OUT" "$(wc -c <"$OUT" | tr -d ' ')"
