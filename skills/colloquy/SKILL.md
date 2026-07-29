---
name: colloquy
description:
  'Presents a concept, design, decisions, or findings as an HTML page the user comments
  on in the browser — Claude watches for comments, replies in-thread, and ships revised
  versions. Use instead of a wall-of-text plan or a handed-over .md report. Triggers:
  "explain this in HTML", "write it up as a page", "write up the findings", "I want to
  see the options", or reaching for plan mode on something intricate.'
argument-hint: "[concept or decision to explain]"
allowed-tools:
  - Bash(colloquy:*)
---

Explain a concept, decision, or findings as an HTML page the user opens in a browser and
reviews in place: they select text and comment, you reply in-thread and ship revised
versions, and a banner shows whether you're working or listening. Reach for it instead
of a wall-of-text plan or a `.md` report handed over by path, when a complex change
needs shared understanding or a decision before code, or when a diagnosis or review is
itself the deliverable. With nothing named below, the subject is whatever the session is
about — the plan you were about to give, the design under discussion, or the findings you
just gathered.

$ARGUMENTS

## Setup

The page lives in its own directory, conventionally
`~/.local/state/colloquy/pages/<slug>/`, where `<slug>` is a short kebab-case name
for the topic (`migration-options`, `auth-diagnosis`) — every command takes the
directory explicitly, so any location works. The directory survives the session and
is where every version, the event log, and the vendored widget layer live. It is
review state, not an archive: content with a life beyond the review leaves through
`export` or a copied version, to wherever that content belongs.

`colloquy` mediates everything, and is on PATH because Claude Code puts each enabled
plugin's `bin/` there. Nothing below has a path to resolve or a variable to expand, so
it runs verbatim in any shell.

```bash
colloquy init <dir>                          # create layout, vendor the widget layer
colloquy catalog <dir>                       # the page's vocabulary: widgets + theme idioms
colloquy serve <dir>                         # background task; prints the URL
colloquy status <dir> working "<detail>"     # or: waiting, idle
colloquy wait <dir>                          # background task; exits on new user events
colloquy comment <dir> --quote "<passage>" --text "…"   # open a thread on a passage
colloquy reply <dir> --to <id> --text "…"
colloquy note <dir> --version 1 --text "<one-line changelog>"   # lints, then publishes vNNN.html
colloquy check --render <dir>                # the browser gate, once per page (see below)
colloquy events <dir>                        # reprint the full thread
colloquy export <dir>                        # the review thread as Markdown
colloquy stop <dir>                          # stop the server; its background task exits 143 (SIGTERM — normal)
```

`command not found` means colloquy isn't installed as a plugin — say so rather than
hunting for the script. From a checkout of the repo the same command is
`uv run skills/colloquy/scripts/interact.py`; that script's module docstring documents
the page directory's layout, and its PEP 723 header is why `uv` is the plugin's one
prerequisite.

1. `init`, then read `catalog <dir>` — it prints the vendored registry (widget schemas
   with examples) and the theme's class idioms, which vary per project.
2. Write the page as `<dir>/versions/v1.html` (conventions below).
3. `serve` as a background task (`run_in_background`). The port is stable per directory
   and a live server is reused, so the URL survives restarts.
4. `note` the version — the server exposes a version only once its note lands, and
   `note` lints first and refuses a failing version, so a half-written or broken file is
   never live in the reviewer's browser. Before the URL first goes out, run the browser
   gate too: `check --render` (see "Before the URL goes out"). Then hand the user the
   URL with a one-line orientation (select text to comment; on a sign-off page,
   "✓ Looks good" approves) and enter the review loop.

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
  around it was rewritten. Keep ids stable across versions so neither detaches, and out
  of the `cq-` prefix, which the runtime coins its own ARIA targets in.
- **Edits to reviewed content ship as suggestions.** Changing a passage the reader
  has already seen — a rewrite, a deletion, above all the fix a comment asked for —
  goes in a `cq-suggestion`: `cq-old` carries the current markup verbatim (its ids
  ride there), `cq-new` the proposal, and the reader accepts or rejects it in the
  margin. Fresh content — the first version, a new section, a restructure — is
  written straight, and its review is comments as usual. Name the answered thread
  with `resolves="<comment id>"` so accepting the fix closes the thread too.
  Deciding isn't the only answer: the proposed words are ordinary page text, so the
  reader can select them and comment instead — worth saying where the page
  introduces its first suggestion, since ✓ and ✗ are the only visible affordances.
- **Who writes the words picks the shape.** Three things change text once a review is
  under way, and they differ by seat rather than by style. Prose you own, rewritten
  after the reader has seen it: a `cq-suggestion`, theirs to accept or reject. A
  passage that is theirs to word — a release note, a summary in their voice: a
  `cq-draft`, which nobody decides and the next version carries verbatim. Their
  wording for prose you own: a suggestion comment, which reaches the log for you to
  take or answer. So a draft never sits inside a suggestion — its words aren't yours
  to propose — and a suggestion carries markup, not a widget's own state: proposing a
  card's column or an option's pick has no form yet.
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
- **Name a code block's language and it gets colored.** Two shapes, by what the block
  is for: `<pre><code class="language-python">` for a literal the reader selects and
  quotes — a command, a config, a snippet of output — and `<cq-code lang="python">` for
  a walkthrough, which adds line numbers, `hi` ranges, and `cq-note` remarks anchored at
  a line. The language names are the same set either way, `catalog` lists them, and
  `check` refuses one outside it. Nothing is inferred from the text, so a block whose
  body isn't source — a transcript, a stack trace, a log — simply says nothing and stays
  plain.
- **Make references clickable.** Declare the repo or tracker base once as
  `<meta name="cq-base" content="https://host/repo/blob/main/{path}#L{line}">` and
  write source references as `<cq-ref src="path/to/file.py:88"></cq-ref>`. Render
  ticket keys, MR/PR numbers, and URLs as real `<a>` links, not plain text. Inside
  a `<cq-specimen>` a fictional base is fine.
- **Keep wide content inside the column** — 760px in the default theme. The comment
  layer anchors to on-screen text, so a page that scrolls sideways is hard to review.
  Give any element that can overflow (a `<pre>`, a `<table>`, an `<svg>`)
  `max-width: 100%` or `overflow-x: auto`, and size diagrams responsively rather than a
  fixed pixel width wider than the column. `check` flags fixed widths that exceed it.
- **Show real content as evidence; quote invented content in a specimen.** Prefer
  putting the actual file contents, diff, or output behind `<details>` over
  paraphrasing it. An example that merely exhibits syntax or a widget goes in a
  `<cq-specimen>` — its gutter and label mark the region as quoted rather than
  spoken, and interactive widgets inside take no input — with visibly fictional
  content: real project content in an example gets read as a live proposal.
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
`comment` posts as you, never as them.

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
     options pick with `"action": "choose"` and `"detail": {"option": "st-s3"}`,
     a suggestion decided with `"action": "accept"` or `"reject"` — and they have
     already seen the change on screen. It stays on screen without your help: the
     page replays every recorded action onto every later version, so their edit
     survives a republish whether or not your markup mentions it. Write the next
     version as the document should now read and leave their widget alone. What
     the markup still owes them is the record — mark the picked option `chosen`
     (and `settled` once the decision has stopped being live), replace an accepted
     suggestion with its `cq-new` markup and a rejected one with its `cq-old`,
     keeping the old id where the passage survives — so the page reads right to
     someone who never saw the log. `check` says where the record is behind
     ("record behind the log", advice on a passing run), and until a version
     carries a decision the page marks that widget as decided-and-unhonored.

     Declining means putting different words there — yours, or the originals
     back — and that takes `restated` on the element plus the reason in the note
     (`catalog`'s `$restated` has the rest). Without it replay paints their words
     over yours, so `check` refuses the version rather than let the two disagree
     in silence. It guards the other end
     too — a version may retire
     ids only where the log settled the suggestion holding them, so an undecided
     proposal is carried, withdrawn whole, or left alone, never quietly kept as
     settled content.
   - **A thread-widget action**: a `cq-options choose` group in one of your replies
     is an inline question (announce it there too — "click an option to answer");
     the user's pick is the answer, so acknowledge it with a reply in the same
     thread. Reply markup is frozen in the log — versions neither carry nor revert
     it, and the picked state stays put on its own.
3. Page changes go in the next version: Write `versions/v2.html` (incrementing; never
   rewrite a version the user has seen — the picker is the history), then `note` its
   changelog — brief, though a decline's why can take a sentence or two — which lints it
   and publishes it; the browser follows automatically.
4. Back to `status waiting` + `wait`.

A `done` event is sign-off — it arrives only from a page declaring it (see the
conventions): `status <dir> idle`, don't restart `wait`, and carry the approval back
into the main task — `export` prints the whole review as Markdown when a PR
description wants it. A review ending with record debt publishes one final honoring
version first — the final version is the page that has to read right without the
log, and `export` lists what still lags on stderr. A comments-only page has no terminal event; when the discussion
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

## Pointing at a passage yourself

`comment` opens a thread the way the reviewer's selection does — same anchor, same panel,
same reply box, labelled Claude instead of You. Reach for it when what you have to say is
about one passage and you can't settle it yourself: a sentence that reads two ways, an
assumption the paragraph rests on, a line only they have the fact to fix. Anything you
can settle, settle — ship the fix. In chat, the reader has to find the passage again;
in the margin it is already beside them.

```bash
colloquy comment <dir> --quote "<the passage, as the version file holds it>" --text "…"
colloquy comment <dir> --section <element id> --text "…"    # a diagram, an image
```

It anchors in the newest published version, deriving the section the way the browser
does, and reads the version the way the reviewer sees it: a slot their decision retired
(an accepted suggestion's `cq-old`, a rejected one's `cq-new`) is off the page, however
much the file still holds it, and a `cq-draft` they have edited says their words — quote
the text their edit sent, not the body you authored. Quote the words the file holds, not
what the page renders, and stay inside one part of a widget — a module writes words of
its own between an element's children (a column's heading, a milestone's chips, a
`cq-ref`'s link text), and a quote spanning that join names nothing. A quote the version
doesn't hold, holds twice, runs across such a join, sits in a retired slot, or names
words an edit replaced is refused with what to do about it, rather than posted as a
comment that lands nowhere — as is a `--section` naming an element their decision left
empty (a deletion accepted, an insertion refused): present in the file, absent from
their screen.

A comment asks; a `cq-suggestion` proposes. Where you have the better sentence, ship it
as a suggestion in the next version and let them accept it — a comment is for the
question you can't answer yourself. The reviewer resolves either. There is no CLI that
resolves a thread: a note's purpose is discharged by being read, and only the reader
knows that happened.

## Customizing the widget layer

`init` vendors the layer into the page directory by overlaying, per file: colloquy's
shipped defaults, then the user's `~/.config/colloquy/`, then the project's
`.claude/colloquy/` — each mirroring the same layout (`theme.css`, `registry.json`,
`widgets/`, `vendor/`) — so a project can override `theme.css`, extend `registry.json`,
or add widget modules, and `catalog` always reflects what this page actually has. The
page directory is self-contained: an approved version can't change under its reviewer.
Re-running `init` on a live page is the explicit re-vendor; note it in the next
version's changelog. It refuses when the page's log holds event kinds or action verbs
the incoming layer no longer speaks — those events would silently never replay again —
and `--retire-vocabulary` is the explicit override. The same stamp guards the other
direction: `note` refuses to write a shape the page's vendored layer doesn't read,
and says to re-vendor first.

## When the browser can't reach the server

The server binds `127.0.0.1`, so the browser must be on the same machine (a local
terminal, the desktop app, or an IDE that forwards localhost ports — VS Code Remote-SSH
and devcontainers do this automatically, so the URL opens as-is). In a session with no
path to localhost there is no hand-over; present in the terminal instead. An opt-in
tunnel is on the backlog.

## Before the URL goes out

Three passes stand between a version and its reviewer.

**The lint.** `note` runs it on every version and refuses to publish one that fails, so
the workflow holds no separate `check` call and a failing version never reaches the
reviewer. It is deterministic and needs no browser, and a failure names what to fix —
the markup's structure, the registry's rules, and the id-survival rule above.

**The render gate**, once, before the page's URL first reaches the user:

```bash
colloquy check --render <dir>
```

It loads the version in the machine's installed Chrome (a couple of seconds, and works
before the version is noted) and fails, in both color schemes, on what a static lint
cannot see: a console error, a widget upgraded into a box of no size, a page that
scrolls sideways, a `cq-diagram` whose mermaid source doesn't parse, words on screen
that no selection can reach, words the screen shows and a printout drops, a version
that authors widget state the log replays over
(a different option `chosen`, a card in a column the reviewer dragged it out of — the
decision stands, so carry it in the markup or rewrite the passage and declare
`restated`). The lint validates a diagram element but never the notation
in its body, so a typo there would otherwise reach the reader as an error box; and it
can't see a heading rendered as CSS generated content or marked `.cq-ui`, which leaves
the reader looking at text they can't comment on. When Chrome isn't installed, the gate says so on stderr and
lets the lint's result stand. It is the page's whole browser budget; a screenshot after
it reads neither the console nor the second scheme.

**Then read the page yourself.** Nothing above has an opinion about any of this:

- **Claims backed.** Every assertion the reader would question is traceable to real
  evidence on the page — a command, a diff, a linked source, output behind `<details>` —
  not asserted bare.
- **Excess pruned.** No paragraph restates another; nothing explains what the reader
  already knows. If a version has been patched several times, rewrite the section clean
  rather than layering another note. A decision already made and acted on is excess at
  full height: mark its `cq-options` group `settled`.
- **Diagrams read.** Each diagram earns its place and says something the prose doesn't.
- **References clickable.** Tickets, PRs, and URLs are real links.
