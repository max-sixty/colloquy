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

The page lives in its own directory, conventionally `~/.claude/colloquy/<slug>/`,
where `<slug>` is a short kebab-case name for the topic (`migration-options`,
`auth-diagnosis`) — every command takes the directory explicitly, so any location
works. The directory survives the session and is where every version, the event log,
and the vendored widget layer live. The same `~/.claude/colloquy/` also carries the user's
personal overlay layer (see Customizing), which reserves `widgets` and `vendor` as
slugs. `interact.py` mediates everything; its module docstring documents the layout.

Invoke it with `uv run` — it's a `uv` script (a PEP 723 header declares its
dependencies), and `uv` is the one prerequisite for the whole plugin. If
`CLAUDE_SKILL_DIR` isn't set in your shell, the script lives at
`scripts/interact.py` beside this file:

```bash
IX="uv run ${CLAUDE_SKILL_DIR}/scripts/interact.py"
$IX init <dir>                          # create layout, vendor the widget layer
$IX catalog <dir>                       # the page's vocabulary: widgets + theme idioms
$IX serve <dir>                         # background task; prints the URL
$IX status <dir> working "<detail>"     # or: waiting, idle
$IX wait <dir>                          # background task; exits on new user events
$IX reply <dir> --to <id> --text "…"
$IX check <dir>                         # pre-handover lint (see below)
$IX note <dir> --version 1 --text "<one-line changelog>"   # re-runs check, then publishes vNNN.html
$IX events <dir>                        # reprint the full thread
$IX export <dir>                        # the review thread as Markdown
$IX stop <dir>                          # stop the server; its background task exits 143 (SIGTERM — normal)
```

1. `init`, then read `catalog <dir>` — it prints the vendored registry (widget schemas
   with examples) and the theme's class idioms, which vary per project.
2. Write the page as `<dir>/versions/v001.html` (conventions below).
3. `serve` as a background task (`run_in_background`). The port is stable per directory
   and a live server is reused, so the URL survives restarts.
4. `check`, then `note` the version — the server exposes a version only once its note
   lands, and `note` re-runs `check` and refuses a failing version, so a half-written or
   broken file is never live in the reviewer's browser. Then hand the user the URL with
   a one-line orientation (select text to comment; on a sign-off page, "✓ Looks good"
   approves) and enter the review loop.

## Page conventions

- Pages are complete HTML documents. `check` enforces the scaffold — exactly one
  stylesheet link (`/theme.css`) and one external script (the `/colloquy.js` module);
  the rest of the head (title, charset, the `cq-*` metas below) is yours:

  ```html
  <!doctype html>
  <html lang="en">
  <head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>…</title>
  <link rel="stylesheet" href="/theme.css">
  </head>
  <body>
  <main>
    …authored HTML and widgets…
  </main>
  <script type="module" src="/colloquy.js"></script>
  </body>
  </html>
  ```

- **The theme owns the look.** Palette, type, spacing, headings, tables, code,
  `details`, and the class idioms all come from the vendored `theme.css` — write plain
  semantic HTML and it gets the voice for free. A page-local `<style>` is the escape
  hatch for genuinely page-specific presentation, not for re-declaring the palette.
- **Widgets are `cq-*` elements**, validated against the vendored registry: attributes
  carry scalars (enums, flags), children carry prose, an item's title is a leading
  `<strong>` child. Every `cq-*` element takes an explicit end tag — `<cq-ref …/>` is
  rejected because HTML ignores the slash. A `data`-bodied widget (`cq-diagram`) takes
  text in its notation with `<` and `>` escaped. The catalog is the authority; don't
  invent tags or attributes.
- Give every section, major block, and widget item a stable, meaningful `id`: comments
  anchor to the nearest `id`, and an anchor survives into a new version only where its
  id does. The reader's place on the page falls back to those same ids when the text
  around it was rewritten. Keep ids stable across versions so neither detaches.
- The runtime injects the status banner, comment sidebar, version picker, and keyboard
  shortcuts (`?` in the browser shows the reference); don't build page UI for any of
  those.
- **Sign-off is declared, not assumed.** A page whose review ends in the reader's
  assent — a plan, a design, a proposed change, anything where approval unblocks
  work — declares `<meta name="cq-review" content="sign-off">` in the head, and the
  banner offers "✓ Looks good". A page that only informs (a status report, an
  incident chronicle) omits it: its review is comments only, with nothing to approve.
  `check` rejects unknown `cq-*` metas and any other `cq-review` value.
- **Announce interactivity in prose.** A fresh reviewer won't guess from a grip glyph
  or a hover cursor that a board takes drags or an options group takes clicks — the
  sentence introducing the widget says it ("drag cards to reprioritize; your edits
  reach me directly", "click an option to decide"). The widgets stay chrome-free on
  purpose; the page's own words carry the affordance.
- **Never lose user text.** A central tenet of the comment layer: drafts (the general
  box, each reply, the selection composer) survive navigation, reload, version switches,
  and server death; only a successful send clears them.
- **Diagrams are graphical, never ASCII.** Flow, sequence, and state diagrams go in a
  `cq-diagram` (mermaid source body); reach for hand-drawn inline `<svg>` only where
  layout must be bespoke, drawn from the theme's tokens, with labelled nodes and
  arrowheaded edges. Never box-drawing (`┌─┐ │ ▼`) in a `<pre>`.
- **Make references clickable.** Declare the repo or tracker base once as
  `<meta name="cq-base" content="https://host/repo/blob/main/{path}#L{line}">` and
  write source references as `<cq-ref src="path/to/file.py:88"></cq-ref>`. Render
  ticket keys, MR/PR numbers, and URLs as real `<a>` links, not plain text. In a
  labeled specimen a fictional base is fine.
- **Keep wide content inside the column** — 760px in the default theme. The comment
  layer anchors to on-screen text, so a page that scrolls sideways is hard to review.
  Give any element that can overflow (a `<pre>`, a `<table>`, an `<svg>`)
  `max-width: 100%` or `overflow-x: auto`, and size diagrams responsively rather than a
  fixed pixel width wider than the column. `check` flags fixed widths that exceed it.
- **Show real content as evidence; label invented content as a specimen.** Prefer
  putting the actual file contents, diff, or output behind `<details>` over
  paraphrasing it. But an example that merely exhibits syntax or a widget must be
  visibly fictional and labeled a specimen — real project content in an example gets
  read as a live proposal.
- **Show the destination, not the journey.** Explain the concept as it stands — total
  cut-over. Don't spend content on what was considered before or how you got here.
- **Retire a decision once it's settled**, which is the same rule applied across
  versions: a choice that's been made and acted on has turned into the journey, and a
  page that keeps rendering four options at full height after one of them shipped is
  spending its best space on a question nobody is still asking. Mark the group
  `settled` and it collapses to one line naming the pick, with every card still there
  behind a disclosure — no id is dropped, so the anchors riding them and `check` both
  hold, and the reader can open it, disagree, and pick again. Settling is a
  later moment than honoring: a decision stays live while you're applying it, and
  settles once nothing is revisiting it, which is usually a version or two on. The
  same instinct applies without the widget — a section that has served its purpose
  belongs behind a `<details>`, not left at full height.

## The review loop

Whenever you hand over the URL or finish a round of work: `status <dir> waiting`, start
`wait <dir>` as a background task, and end your turn. While `wait` runs, the banner
shows "Claude is listening"; it exits — re-invoking you — when the user comments,
replies, resolves, approves, or edits an interactive widget (a drag on a `cq-board`
arrives as an `action` event), printing the new events as JSON. `wait` delivers
everything no previous `wait` has delivered — including events posted while you were
working, so comments never get lost between rounds; reading the log another way
(`events`) doesn't count as delivery. User comments exist only through the browser —
there is no CLI that posts as the user.

On wake:

1. `status <dir> working "<what you're doing>"` — refresh the detail at each milestone;
   the banner shows it live, and reads a status left unrefreshed long enough as Claude
   having gone quiet.
2. Address every event `wait` printed (each is JSON carrying the server-minted `id`
   that `reply --to` takes):
   - **A comment**: `reply` in-thread, and change the page where the comment warrants
     it — usually both. A reply is brief plain text, or may carry widget markup (a
     small `cq-diagram` explaining a fix renders live in the thread); `reply`
     validates widgets against the vendored registry and rejects what `check` would,
     and their ids must be fresh — `reply` refuses ids the page or an earlier reply
     already uses, and `check` keeps later versions off a reply's.
   - **A suggestion** (a comment with `"suggestion": true`) proposes replacement text
     for its quoted passage: take it verbatim into the next version, or reply with
     why not — never silently rewrite it.
   - **A page-widget action** is the user editing the document through a widget — a
     board drag arrives as `{"kind": "action", "widget": "feeder-board", "action":
     "move", "detail": {"card": "card-baffle", "to": "col-doing", "index": 0}}`, an
     options pick with `"action": "choose"` and `"detail": {"option": "st-s3"}` —
     and they have already seen the change on screen. The version is the reply
     either way: honor the edit by carrying it into the next version's markup
     exactly (move that element, keep its id; mark the option `chosen` — and
     `settled` too, once the decision has stopped being live), or decline
     by shipping without that edit — everything else may still change — and saying
     why in the note; tabs roll back to the authored state as they pick up that
     version.
   - **A thread-widget action**: a `cq-options choose` group in one of your replies
     is an inline question (announce it there too — "click an option to answer");
     the user's pick is the answer, so acknowledge it with a reply in the same
     thread. Reply markup is frozen in the log — versions neither carry nor revert
     it, and the picked state stays put on its own.
3. Page changes go in the next version: Write `versions/v002.html` (incrementing; never
   rewrite a version the user has seen — the picker is the history), `check` it, then
   `note` its changelog — brief, though a decline's why can take a sentence or two —
   which publishes it; the browser follows automatically.
4. Back to `status waiting` + `wait`.

A `done` event is sign-off — it arrives only from a page declaring it (see the
conventions): `status <dir> idle`, don't restart `wait`, and carry the approval back
into the main task — `export` prints the whole review as Markdown when a PR
description wants it. A comments-only page has no terminal event; when the discussion
has served its purpose, set `status idle` yourself. Either way, `stop` the server once
the page won't be revisited.

Between turns a page is either watched or idle, and a `Stop` hook holds you to it:
ending a turn with a page still `waiting` under no live `wait`, or holding events you
never picked up, is blocked and names the page. The invariant is what the reviewer is
owed — from the browser, a page nobody is listening to looks exactly like a page whose
reviewer simply hasn't commented yet, so without it they find out by asking. It covers
the pages you `serve` or `wait` on, the two acts that put a reviewer on the other end,
so a directory you only built or linted is outside it. `status idle` ends a review and
so refuses while events sit unread: pick them up first with `wait`, which returns at
once when events are already there. `wait`
also restarts a server that died under it and reports the restart on stderr; exit 2
means it couldn't, and the page stays down until `serve`.

## Customizing the widget layer

`init` vendors the layer into the page directory by overlaying, per file: colloquy's
shipped defaults, then the user's `~/.claude/colloquy/`, then the project's
`.claude/colloquy/` — each mirroring the same layout (`theme.css`, `registry.json`,
`widgets/`, `vendor/`) — so a project can override `theme.css`, extend `registry.json`,
or add widget modules, and `catalog` always reflects what this page actually has. The
page directory is self-contained: an approved version can't change under its reviewer.
Re-running `init` on a live page is the explicit re-vendor; note it in the next
version's changelog.

## When the browser can't reach the server

The server binds `127.0.0.1`, so the browser must be on the same machine (a local
terminal, the desktop app, or an IDE that forwards localhost ports — VS Code Remote-SSH
and devcontainers do this automatically, so the URL opens as-is). In a session with no
path to localhost there is no hand-over; present in the terminal instead. An opt-in
tunnel is on the backlog.

## Check before handing over

Before each `note`, run `check`:

```bash
uv run "${CLAUDE_SKILL_DIR}/scripts/interact.py" check <dir>
```

It's a deterministic static lint (no browser, near-zero cost): the HTML parses with
balanced tags; the scaffold is exactly the theme link and the module script; every
`cq-*` element validates against the vendored registry (schema, nesting, no
self-closing form); ids are unique and every anchor id from the previous version
survives; nothing has a fixed pixel width wider than the column. It exits non-zero and
lists what to fix.

Then read the page once against this checklist:

- **Claims backed.** Every assertion the reader would question is traceable to real
  evidence on the page — a command, a diff, a linked source, output behind `<details>` —
  not asserted bare.
- **Excess pruned.** No paragraph restates another; nothing explains what the reader
  already knows. If a version has been patched several times, rewrite the section clean
  rather than layering another note. A decision already made and acted on is excess at
  full height: mark its `cq-options` group `settled`.
- **Diagrams read.** Each diagram earns its place and says something the prose doesn't.
- **References clickable.** Tickets, PRs, and URLs are real links.

If browser tools are available **and** the page has diagrams, render the served URL and
take one screenshot to confirm the diagrams aren't clipped — a single shot, not a
scroll-through. Without browser tools, `check` plus the first user comment are the safety
net; skip it.
