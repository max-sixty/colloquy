#!/usr/bin/env bash
# Set up a live sample colloquy page and print the shot list for the README GIF.
#
# Records nothing itself (screen capture is OS-specific). It spins up a real page
# so you can screen-record the actual loop, then drop the result at docs/demo.gif.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IX="uv run $HERE/skills/colloquy/scripts/interact.py"
DIR="${TMPDIR:-/tmp}/colloquy-demo"

rm -rf "$DIR"
$IX init "$DIR" >/dev/null

cat > "$DIR/versions/v001.html" <<'HTML'
<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Migration plan</title>
<meta name="cq-review" content="sign-off">
<link rel="stylesheet" href="/theme.css"></head>
<body><main>
<header id="top">
<p class="eyebrow">demo · migration plan</p>
<h1>Migrating billing to the new service</h1>
<p class="lede">Three phases, one weekend of downtime. Select any line to comment.</p>
</header>
<section id="phases"><h2>Phases</h2>
<ol class="steps">
<li id="p1">Dual-write to old and new stores behind a flag.</li>
<li id="p2">Backfill history, then flip reads to the new store.</li>
<li id="p3">A weekend cutover window to retire the old store.</li>
</ol>
<cq-diagram id="flow">
graph LR
  DualWrite --> Backfill
  Backfill --> Cutover
</cq-diagram>
</section>
<section id="risk"><h2>Rollback</h2>
<p id="r1">Each phase is independently reversible by toggling the flag.</p></section>
<section id="work"><h2>Cutover weekend punch list</h2>
<p id="w1">Drag to reprioritize — each move reaches Claude directly.</p>
<cq-board id="punch-list">
  <cq-column id="col-before" label="Before the window">
    <cq-card id="card-dryrun"><strong>Dry-run the backfill</strong></cq-card>
    <cq-card id="card-oncall"><strong>Staff the on-call rota</strong></cq-card>
  </cq-column>
  <cq-column id="col-during" label="During">
    <cq-card id="card-flip"><strong>Flip reads</strong></cq-card>
  </cq-column>
  <cq-column id="col-after" label="After">
    <cq-card id="card-retire"><strong>Retire the old store</strong></cq-card>
  </cq-column>
</cq-board>
</section>
</main><script type="module" src="/colloquy.js"></script></body></html>
HTML

$IX check "$DIR" >/dev/null
$IX note "$DIR" --version 1 --text "the plan" >/dev/null
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
     and the reply lands in the thread.
  5. Drag "Staff the on-call rota" into the During column by its grip — the
     toast confirms "sent to Claude". End on the moved card.

Record with any screen recorder, export at <=1200px wide, save to docs/demo.gif.
EOF
wait
