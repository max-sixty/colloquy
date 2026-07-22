#!/usr/bin/env bash
# Set up a live sample colloquy page and print the shot list for the README GIF.
#
# Records nothing itself (screen capture is OS-specific). It spins up a real page
# so you can screen-record the actual loop, then drop the result at docs/demo.gif.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IX="python3 $HERE/skills/colloquy/scripts/interact.py"
DIR="${TMPDIR:-/tmp}/colloquy-demo"

rm -rf "$DIR"
$IX init "$DIR" >/dev/null

cat > "$DIR/versions/v001.html" <<'HTML'
<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Migration plan</title>
<style>
  :root { --ink:#1f2430; --muted:#5b6472; --bg:#fcfcfa; --line:#e5e7eb; --accent:#4f46e5; }
  * { box-sizing:border-box; } body { margin:0; background:var(--bg); color:var(--ink);
    font:16px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
  main { max-width:720px; margin:0 auto; padding:40px 24px 120px; }
  h1 { font-size:1.6rem; letter-spacing:-0.015em; margin:0 0 6px; }
  .sub { color:var(--muted); margin:0 0 32px; }
  h2 { font-size:1.15rem; margin:32px 0 8px; }
  ol { padding-left:22px; } li { margin:8px 0; }
</style></head>
<body><main>
<h1 id="top">Migrating billing to the new service</h1>
<p class="sub">Three phases, one weekend of downtime. Select any line to comment.</p>
<section id="phases"><h2>Phases</h2>
<ol>
<li id="p1">Dual-write to old and new stores behind a flag.</li>
<li id="p2">Backfill history, then flip reads to the new store.</li>
<li id="p3">A weekend cutover window to retire the old store.</li>
</ol></section>
<section id="risk"><h2>Rollback</h2>
<p id="r1">Each phase is independently reversible by toggling the flag.</p></section>
</main><script src="/interact.js" defer></script></body></html>
HTML

$IX status "$DIR" waiting >/dev/null
URL=$($IX serve "$DIR" & sleep 1; cat "$DIR/server.json" | python3 -c 'import sys,json;print(json.load(sys.stdin)["url"])')

cat <<EOF

Sample page serving at: $URL
(leave this terminal open; Ctrl-C stops the server)

Shot list for docs/demo.gif (~30s, keep it tight):
  1. Open the URL. Let the banner read "Claude is listening".
  2. Select the text "one weekend of downtime" and comment:
       "Can we avoid the downtime window entirely?"
  3. In another terminal, drive Claude to reply + ship v002:
       $IX reply "$DIR" --to <id> --text "Yes: phase 3 becomes an online swap."
       (write versions/v002.html changing phase 3, then:)
       $IX note "$DIR" --version 2 --text "Phase 3 is now an online swap, no downtime"
  4. Back in the browser: the banner flips to "working", the picker gains v2,
     and the reply lands in the thread. End on the v2 page.

Record with any screen recorder, export at <=1200px wide, save to docs/demo.gif.
EOF
wait
