---
name: colloquy
description:
  'Presents a concept, design, decisions, or findings as an HTML page the user comments
  on in the browser — Claude watches for comments, replies in-thread, and ships revised
  versions. Use instead of a wall-of-text plan or a handed-over .md report. Triggers:
  "explain this in HTML", "write it up as a page", "write up the findings", "I want to
  see the options", or reaching for plan mode on something intricate.'
argument-hint: "[concept or decision to explain]"
---

Explain a concept, decision, or findings as an HTML page the user opens in a browser and
reviews in place: they select text and comment, you reply in-thread and ship revised
versions, and a banner shows whether you're working or listening. Reach for it instead
of a wall-of-text plan or a `.md` report handed over by path, when a complex change
needs shared understanding or a decision before code, or when a diagnosis or review is
itself the deliverable.

$ARGUMENTS

## Setup

The page lives in its own directory under `~/.claude/colloquy/<slug>/`, where `<slug>`
is a short kebab-case name for the topic (`migration-options`, `auth-diagnosis`). The
directory survives the session and is where every version and the event log live.
`interact.py` mediates everything; its module docstring documents the layout.

Invoke it with `uv run` — it's a `uv` script (a PEP 723 header declares its one
dependency, `click`), and `uv` is the one prerequisite for the whole plugin:

```bash
IX="uv run ${CLAUDE_SKILL_DIR}/scripts/interact.py"
$IX init <dir>                          # create layout, copy in the comment layer
$IX serve <dir>                         # background task; prints the URL
$IX status <dir> working "<detail>"     # or: waiting, idle
$IX wait <dir>                          # background task; exits on new user events
$IX reply <dir> --to <id> --text "…"
$IX note <dir> --version <n> --text "<one-line changelog>"
$IX check <dir>                         # pre-handover lint (see below)
$IX events <dir>                        # reprint the full thread
$IX stop <dir>                          # shut the server down
```

1. `init`, then Write the page as `<dir>/versions/v001.html` (conventions below).
2. `serve` as a background task (`run_in_background`). The port is stable per directory
   and a live server is reused, so the URL survives restarts.
3. `check` the version (below), then hand the user the URL with a one-line orientation
   (select text to comment; "✓ Looks good" signs off) and enter the review loop.

## Page conventions

- Self-contained — inline CSS/JS/SVG — plus exactly one external tag, before `</body>`:
  `<script src="/interact.js" defer></script>`.
- Give every section and major block a stable, meaningful `id`: comments anchor to the
  nearest `id`, and an anchor survives into a new version only where its id does. The
  reader's place on the page falls back to those same ids when the text around it was
  rewritten. Keep ids stable across versions so neither detaches.
- The layer injects the status banner, comment sidebar, and version picker; don't build
  page UI for any of those.
- **Never lose user text.** A central tenet of the comment layer: drafts (the general
  box, each reply, the selection composer) survive navigation, reload, version switches,
  and server death; only a successful send clears them.
- **Use light mode.** Ship a light `:root` palette — dark ink on near-white, one or two
  accents.
- **Diagrams are graphical, never ASCII.** Author any architecture/flow/sequence diagram
  as inline `<svg>`, not box-drawing (`┌─┐ │ ▼`) in a `<pre>`. A good one has labelled
  rounded-rect nodes; arrowheaded, labelled edges (one small reused `<defs>` marker); a
  legend or colour meaning when paths differ (e.g. green = fast path, amber = new path);
  aligned spacing. Draw it from the page's light palette.
- **Keep wide content inside the column.** The comment layer anchors to on-screen text,
  so a page that scrolls sideways is hard to review. Give any element that can overflow
  (a `<pre>`, a `<table>`, an `<svg>`) `max-width: 100%` or `overflow-x: auto`, and size
  diagrams responsively (`style="width: 100%; height: auto"`) rather than a fixed pixel
  width wider than the column. `check` flags fixed widths that exceed it.
- **Show real content, not mocks.** It's a dynamic medium — prefer putting the actual
  file contents, diff, or output behind `<details>` over paraphrasing it.
- **Make references clickable.** Render each ticket key, MR/PR/issue number, and URL the
  reader might open as a real `<a>`, not plain text or `<code>`. Resolve the base once
  (the tracker or repo host) and link every reference of that kind; don't leave bare
  text because the host was uncertain.
- **Show the destination, not the journey.** Explain the concept as it stands — total
  cut-over. Don't spend content on what was considered before or how you got here.

## The review loop

Whenever you hand over the URL or finish a round of work: `status <dir> waiting`, start
`wait <dir>` as a background task, and end your turn. While `wait` runs, the banner
shows "Claude is listening"; it exits — re-invoking you — when the user comments,
replies, resolves, or approves, printing the new events as JSON. It also delivers events
posted while you were working, so comments never get lost between rounds.

On wake:

1. `status <dir> working "<what you're doing>"` — refresh the detail at each milestone;
   the banner shows it live.
2. Address every comment: `reply` in-thread (brief plain text), and change the page
   where the comment warrants it — usually both.
3. Page changes go in the next version: Write `versions/v002.html` (incrementing; never
   rewrite a version the user has seen — the picker is the history), `check` it, then
   `note` a one-line changelog for it.
4. Back to `status waiting` + `wait`.

A `done` event is sign-off: `status <dir> idle`, don't restart `wait`, and carry the
approval back into the main task. `stop` the server once the page won't be revisited. If
`wait` exits reporting the server died, re-run `serve` and re-enter the loop.

## When the browser can't reach the server

The server binds `127.0.0.1`, so the browser must be on the same machine (a local
terminal, the desktop app, or an IDE that forwards localhost ports — VS Code Remote-SSH
and devcontainers do this automatically, so the URL opens as-is).

When it can't reach localhost (a cloud session, bare SSH with no forwarding), skip the
server and hand over a single self-contained file instead: Write the page with
everything inline and **no** `<script src="/interact.js">` tag, save it to
`~/.claude/colloquy/<slug>.html`, and give the user the `file://` path. The commentable
loop is gone, but the page is still readable; iterate by overwriting the same file so
the path stays stable.

## Check before handing over

Before handing over the URL, and before each `note`d version, run `check`:

```bash
uv run "${CLAUDE_SKILL_DIR}/scripts/interact.py" check <dir>
```

It's a deterministic static lint (no browser, near-zero cost): the HTML parses with
balanced tags, there is exactly one external `<script>` tag, every anchor id from the
previous version survives, and no fixed-pixel-width element is wider than the column. It
exits non-zero and lists what to fix.

Then read the page once against this checklist:

- **Claims backed.** Every assertion the reader would question is traceable to real
  evidence on the page — a command, a diff, a linked source, output behind `<details>` —
  not asserted bare.
- **Excess pruned.** No paragraph restates another; nothing explains what the reader
  already knows. If a version has been patched several times, rewrite the section clean
  rather than layering another note.
- **Diagrams read.** Each diagram is SVG, labelled, and says something the prose doesn't.
- **References clickable.** Tickets, PRs, and URLs are real links.

If browser tools are available **and** the page has diagrams, render the served URL and
take one screenshot to confirm the diagrams aren't clipped — a single shot, not a
scroll-through. Without browser tools, `check` plus the first user comment are the safety
net; skip it.
