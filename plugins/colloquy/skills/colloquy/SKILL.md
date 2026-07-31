---
name: colloquy
description:
  'Presents a concept, design, decisions, findings, or a run of work in progress as an
  HTML page the user comments on in the browser — the agent watches for comments, replies
  in-thread, and ships revised versions as the work moves. Use instead of a wall-of-text
  plan or a handed-over .md report. Triggers: "explain this in HTML", "write it up as a
  page", "write up the findings", "I want to see the options", a run of work whose items
  the user will want to watch go by, or an intricate design that needs review.'
allowed-tools:
  - Bash(colloquy:*)
---

Present a concept, decision, findings, or work in progress as an HTML page the user opens
in a browser and reviews in place: they select text and comment, you reply in-thread and ship revised
versions, and a banner shows whether you're working or listening. Reach for it instead
of a wall-of-text plan or a `.md` report handed over by path, when a complex change
needs shared understanding or a decision before code, when a diagnosis or review is
itself the deliverable, or when a run of work has items the reviewer will want to watch
go by. With nothing named below, the subject is whatever the session is about — the plan
you were about to give, the design under discussion, the findings you just gathered, or
the work you are about to start.

$ARGUMENTS

## Soul

A page is the highest-bandwidth thing you can hand someone, so use it. Two habits carry
most of that.

**Shape follows the subject.** Ask what the subject *is* before writing about it. A set
of things renders as things — `cq-milestones` for work with stages, `cq-board` for work
the reviewer re-orders, `cq-options` for a decision, `cq-metrics` for what was measured —
and the prose says what only prose can. Five paragraphs about five items hand the reader
the job of rebuilding the list you dissolved; the same five as items, each carrying its
own state, are read at a glance and commented on one at a time.

**A page that asks leaves somewhere to answer.** Anything you want a decision on ends in
a `cq-options … choose`, wherever on the page the question falls. Where the alternatives
are short, they are the cards. Where each one needs a section of its own — a diagram, a
diff, three paragraphs — write those sections and let the group be bare labels naming
them (`for="<section id>"`), which renders as a compact list; `multiple` where more than
one can win. Every such group carries a box for words, so "none of these" and a pick's
why need no separate gesture. A page presenting five candidates in prose and offering
nothing to press has handed the reader a document where it meant to ask a question.

**The page keeps up with the work.** A page is not only a thing to review before the
work starts. Where the work is yours to do and the page tracks it, publish a version each
time the state moves — an item to `active`, then `done`; a finding added as you find it —
and the reviewer watches it happen instead of reading about it afterwards. Their browser
follows each new version by itself, deferring only while they are mid-comment or
mid-drag, so a version costs them nothing. Ship one when an item's state actually
changes rather than at every step it took, and let
`review state <page> working "<detail>"` carry the finer grain in between. Keep
`review wait <page>` running while you work, restarting it as soon as it delivers: a
comment that lands mid-flight ("skip that one") then reaches you at the next step
rather than at the end, and the banner reads as working throughout.

## Setup

The page lives in its own directory, conventionally
`~/.local/state/colloquy/pages/<slug>/`, where `<slug>` is a short kebab-case name
for the topic (`migration-options`, `auth-diagnosis`) — every leaf command takes the
page directory explicitly, so any location works. The directory survives the session
and is where every version, the event log, and the vendored widget layer live. It is
review state, not an archive: content with a life beyond the review leaves through
`version export` or a copied version, to wherever that content belongs.

The launcher is `${CLAUDE_SKILL_DIR}/../../bin/colloquy`. Resolve
`${CLAUDE_SKILL_DIR}` to this skill's directory and use that launcher for every command
shown as `colloquy` below. Claude Code also puts the same launcher on PATH.

```bash
colloquy page init <page>                    # create layout, vendor the widget layer
colloquy page catalog <page>                 # widgets and theme idioms
colloquy page media <page> <file>…           # add images; print each page path
colloquy version check <page> --render       # browser gate, once per page
colloquy version publish <page> --version 1 --text "<changelog>"
colloquy version export <page> -o <file>     # standalone HTML copy
colloquy server run <page>                   # background task; prints the URL
colloquy review state <page> working "<detail>"  # or: waiting, idle
colloquy review wait <page>                  # background task; exits on reviewer events
colloquy review comment <page> --quote "<passage>" --text "…"
colloquy review reply <page> --to <id> --text "…"
colloquy review events <page>                # full event log
colloquy review transcript <page>            # review as Markdown
```

If the resolved launcher does not exist, the plugin payload is incomplete; say so. In a
repository checkout it lives at `plugins/colloquy/bin/colloquy`.

1. Run `page init <page>`, then read `page catalog <page>`. It prints the vendored
   registry (widget schemas with examples) and the theme's class idioms, which vary per
   project.
2. Write the page as `<page>/versions/v1.html` (conventions below).
3. Run `server run <page>` as a background task (`run_in_background`). Hand over the URL
   it prints as printed: the key in it is what opens the page. Address, key and port are
   all stable per directory, so the URL survives a restart.
4. Run `version publish <page> --version 1 --text "<changelog>"`. Publishing checks
   the version first and refuses a failure, so a half-written or broken file is never
   live in the reviewer's browser. Before the URL first goes out, run the browser gate
   too: `version check <page> --render` (see "Before the URL goes out"). Then hand the
   user the URL with a one-line orientation (select text to comment; on a sign-off
   page, "✓ Looks good" approves) and enter the review loop.

## When the deliverable is the file

`--export` in the argument asks for the page rather than the review: steps 1, 2 and 4
as above, then `version export <page> -o <file>` and hand back the `file://` URL. No
`server run`, no `review wait`, no review loop — the page directory is still built, so
the same page can be served and reviewed later without being rewritten, and the Stop
hook covers only pages that were served or waited on, so it has nothing to say about
this one. Write the file wherever the project puts things for the user to open.

Mid-review the same command answers "give me a copy": `version export` writes any
published version, as many times as asked, and the review carries on around it. The
copy is the page as the browser drew it, with the reviewer's decisions replayed onto it
and the comment layer left behind.

## Page conventions

- Pages are complete HTML documents. `version check` enforces the scaffold — exactly one
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
  `<strong>` child. Every `cq-*` element takes an explicit end tag — `<cq-diagram id="flow"/>` is
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
  `version check` rejects unknown `cq-*` metas and any other `cq-review` value.
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
  quotes — a command, a config, a snippet of output — and `<cq-code language="python">` for
  a walkthrough, which adds line numbers, `hi` ranges, and `cq-note` remarks anchored at
  a line. The language names are the same set either way, `page catalog` lists them, and
  `version check` refuses one outside it. Nothing is inferred from the text, so a block
  whose body isn't source — a transcript, a stack trace, a log — simply says nothing
  and stays plain. A `cq-diff` needs no language and takes none: a unified diff spans
  files, so each file's own path says what it holds, and a path naming nothing leaves
  that file plain like any undeclared block.
- **Make references clickable.** Write source locations as ordinary semantic links,
  such as `<a href="https://host/repo/blob/main/path/to/file.py#L88"><code>path/to/file.py:88</code></a>`.
  Render ticket keys, MR/PR numbers, and URLs as real `<a>` links, not plain text.
  Inside a `<cq-specimen>` a fictional URL is fine.
- **Keep wide content inside the column** — 760px in the default theme. The comment
  layer anchors to on-screen text, so a page that scrolls sideways is hard to review.
  Give any element that can overflow (a `<pre>`, a `<table>`, an `<svg>`)
  `max-width: 100%` or `overflow-x: auto`, and size diagrams responsively rather than a
  fixed pixel width wider than the column. `version check` flags fixed widths that
  exceed it.
- **Images come in by reference, never inline.**
  `colloquy page media <page> <file>…` copies files into the page directory and prints
  the `src` to write; that path is the only form an image takes on a page, because a
  base64 `data:` URI is more bytes than you can usefully type and it would sit in every
  version forever. Each file is named by the hash of its bytes, so two versions showing
  one screenshot share one copy and a version the reader approved cannot come to show
  them something else. `version check` refuses a `/media/` reference the directory
  can't answer.
  Where the deliverable is a change to a UI with a real *before* state, let the reader
  compare the renders rather than describing what moved: a `cq-shot` holds the pair and
  flips between them in place. Capture both states at the same viewport (the
  `/playwright-cli:playwright-cli` skill drives the browser; render the base commit in
  a second worktree rather than stashing). Say in prose what changed — a downscaled
  full-page shot shows that something moved and not what, and the column is 760px, so
  crop to the part that moved wherever the change is smaller than the page.
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
  behind a disclosure — no id is dropped, so the anchors riding them and `version check`
  both hold, and the reader can open it, disagree, and pick again. Settling is a
  later moment than honoring: a decision stays live while you're applying it, and
  settles once nothing is revisiting it, which is usually a version or two on. The
  same instinct applies without the widget — a section that has served its purpose
  belongs behind a `<details>`, not left at full height.

## The review loop

Whenever you hand over the URL or finish a round of work, run
`review state <page> waiting`, start `review wait <page>` as a background task, and end
your turn. The reply ending each round carries the page's URL again: the reviewer opens
the page from the turn in front of them. While `review wait` runs, the banner names the
current agent as listening; it exits — re-invoking you — when the user comments,
replies, resolves, approves, or edits an interactive widget (a drag on a `cq-board`
arrives as an `action` event), printing the new events as JSON. `review wait` delivers
everything no previous `review wait` has delivered, including events posted while you
were working, so comments never get lost between rounds. Reading the log with
`review events` doesn't count as delivery. User comments exist only through the
browser; `review comment` posts as you, never as them.
A delivery while the page already says `working` leaves that status untouched;
`handoff` dates only a pickup from a non-working state.

On wake:

1. Run `review state <page> working "<what you're doing>"` and refresh the detail at
   each milestone. The banner shows it live, and reads a state left unrefreshed long
   enough as the agent having gone quiet.
2. Address every event `review wait` printed. Each is JSON carrying the server-minted
   `id` that `review reply --to` takes:
   - **A comment**: `review reply` in-thread, and change the page where the comment
     warrants it — usually both. A reply is brief plain text, or may carry widget
     markup (a small `cq-diagram` explaining a fix renders live in the thread);
     `review reply` validates widgets against the vendored registry and rejects what
     `version check` would, and their ids must be fresh — `review reply` refuses ids
     the page or an earlier reply already uses, and `version check` keeps later
     versions off a reply's.
   - **A suggestion** (a comment with `"suggestion": true`) proposes replacement text
     for its quoted passage: take it verbatim into the next version, or reply with
     why not — never silently rewrite it.
   - **A page-widget action** is the user editing the document through a widget — a
     board drag arrives as `{"kind": "action", "widget": "feeder-board", "action":
     "move", "detail": {"card": "card-baffle", "to": "col-doing", "index": 0}}`, an
     options pick with `"action": "choose"` and `"detail": {"options": ["st-s3"]}`
     (every option that now holds the pick, so an empty list is one cleared),
     a suggestion decided with `"action": "accept"` or `"reject"` — and they have
     already seen the change on screen. It stays on screen without your help: the
     page replays every recorded action onto every later version, so their edit
     survives a republish whether or not your markup mentions it. Write the next
     version as the document should now read and leave their widget alone. What
     the markup still owes them is the record — mark every picked option `chosen`
     (and `settled` once the decision has stopped being live), replace an accepted
     suggestion with its `cq-new` markup and a rejected one with its `cq-old`,
     keeping the old id where the passage survives — so the page reads right to
     someone who never saw the log. `version check` says where the record is behind
     ("record behind the log", advice on a passing run), and until a version
     carries a decision the page marks that widget as decided-and-unhonored.

     Declining means putting different words there — yours, or the originals
     back — and that takes `restated` on the element plus the reason in the note
     (`page catalog`'s `$restated` has the rest). Without it replay paints their words
     over yours, so `version check` refuses the version rather than let the two
     disagree in silence. It guards the other end too: a version may retire ids only
     where the log settled the suggestion holding them, so an undecided proposal is
     carried, withdrawn whole, or left alone, never quietly kept as settled content.
   - **A thread-widget action**: a `cq-options choose` group in one of your replies
     is an inline question (announce it there too — "click an option to answer");
     the user's pick is the answer, so acknowledge it with a reply in the same
     thread. Reply markup is frozen in the log — versions neither carry nor revert
     it, and the picked state stays put on its own.
3. Page changes go in the next version: Write `versions/v2.html` (incrementing; never
   rewrite a version the user has seen — the picker is the history), then run
   `version publish <page> --version 2 --text "<changelog>"`. Keep the changelog brief,
   though a decline's why can take a sentence or two. The browser follows the published
   version automatically.
4. Restart `review wait <page>`, under `review state <page> waiting` where the next move
   is the reviewer's and `working` where it is yours.

A `done` event is sign-off — it arrives only from a page declaring it (see the
conventions). It approves the work rather than ending the page: carry the approval back
into the main task, and where the approved work is yours to do, the page keeps up with
it from here. So the page stays `working` under a live `review wait` — "skip that one"
then reaches you mid-flight rather than at the end.

`review state <page> idle` ends a page, and is the only thing that does: when the work
it tracks is finished, or when a comments-only page's discussion has served its purpose
— that page has no terminal event of its own. The server needs no stopping; it goes
down with the session. A review ending with record debt publishes one final honoring
version first, because the final version is the page that has to read right without the
log; `review transcript` lists what still lags on stderr, and prints the whole review as
Markdown when a PR description wants it. `version export` writes the page itself as one
file when that is what outlives the review.

Between turns a page is either watched or idle, and a `Stop` hook holds you to it:
ending a turn with a page not yet idle and no live `review wait`, or holding events
you never picked up, is blocked and names the page. The invariant is what the reviewer
is owed — from the browser, a page nobody is listening to looks exactly like a page
whose reviewer simply hasn't commented yet, so without it they find out by asking. It
covers the pages you run `server run` or `review wait` on, the two acts that put a
reviewer on the other end, so a directory you only built or linted is outside it.
`review state <page> idle` refuses while events sit unread: pick them up first with
`review wait`, which returns at once when events are already there.
`review wait` also restarts a server that died under it and reports the restart on
stderr; exit 2 means it couldn't, and the page stays down until `server run`.

## Pointing at a passage yourself

`review comment` opens a thread the way the reviewer's selection does — same anchor,
same reply box, labelled with the current agent instead of You. Reach for it when what you have to say is
about one passage and you can't settle it yourself: a sentence that reads two ways, an
assumption the paragraph rests on, a line only they have the fact to fix. Anything you
can settle, settle — ship the fix. In chat, the reader has to find the passage again;
in the margin it is already beside them.

```bash
colloquy review comment <page> --quote "<passage from the version file>" --text "…"
colloquy review comment <page> --section <element-id> --text "…"  # diagram or image
```

It anchors in the newest published version, deriving the section the way the browser
does, and reads the version the way the reviewer sees it: a slot their decision retired
(an accepted suggestion's `cq-old`, a rejected one's `cq-new`) is off the page, however
much the file still holds it, and a `cq-draft` they have edited says their words — quote
the text their edit sent, not the body you authored. Quote the words the file holds, not
what the page renders, and stay inside one part of a widget — a module writes words of
its own between an element's children (a column's heading or a milestone's chips), and
a quote spanning that join names nothing. A quote the version
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

`page init` vendors the layer into the page directory from colloquy's shipped defaults,
then the user's `~/.config/colloquy/`, then the project's `.colloquy/`. Each
mirrors the same layout (`theme.css`, `registry.json`, `widgets/`, `vendor/`). Theme
files concatenate in that order, so a short later file can override tokens or rules
without copying the defaults. Runtime, widget, and vendor files replace by path;
registry files merge by top-level entry, with a later layer replacing one complete
entry. A custom widget therefore adds its entry without copying the shipped registry,
while overriding a tag supplies its whole schema. `colloquy customize theme` and
`colloquy customize widget cq-name [--upgrade]` scaffold those files in the project
layer; pass `--user` for the user layer. The merged vocabulary is validated before
vendoring, and its `x-state.detail` schema validates every action at
`POST /api/event`. `page catalog` reflects the result.

The page directory is self-contained: an approved version can't change under its
reviewer. Re-running `page init` on a live page is the explicit re-vendor; note it in
the next version's changelog. It refuses when the incoming layer no longer accepts a
logged event kind or action contract (tag, verb, and detail), since that event would
stop replaying.

## Where the page is served

`server run` serves a page on the address its session arrived on: for an SSH session, the
one the client reached this machine on; otherwise loopback. The URL therefore opens as
printed whether the reviewer's browser is here or on the machine they SSH'd from.

Reaching past loopback opens the port to that network, and `POST /api/event` appends to a
log that outranks the document, so the URL carries a key. The browser keeps it in a cookie
from the first request, and a reader without it gets 403 on the document, the assets, the
state reads and the event writes alike. That key is the boundary, and colloquy reaches no
further than the network the session it serves already crossed: there is no public tunnel.

Address and key are minted once and kept in `<page>/access.json`, because a restart has to
reproduce the URL an open browser is still polling. Where the reviewer's machine can't
reach that address (a jump host, NAT), the page never loads and nothing reports it;
deleting that file derives the address again from the session running now.

## Before the URL goes out

Three passes stand between a version and its reviewer.

**The lint.** `version publish` runs `version check` on every version and refuses a
failure, so the workflow needs no separate static check and a failing version never
reaches the reviewer. It is deterministic and needs no browser, and a failure names
what to fix — the markup's structure, the registry's rules, and the id-survival rule
above.

**The render gate**, once, before the page's URL first reaches the user:

```bash
colloquy version check <page> --render
```

It loads the version in the machine's installed Chrome (a couple of seconds, and works
before the version is published) and fails, in both color schemes, on what a static lint
cannot see: a console error, a widget upgraded into a box of no size, a page that
scrolls sideways, a `cq-diagram` whose mermaid source doesn't parse, words on screen
that no selection can reach, words the screen shows and a printout drops, a version
that authors widget state the log replays over
(a different option `chosen`, a card in a column the reviewer dragged it out of — the
decision stands, so carry it in the markup or rewrite the passage and declare
`restated`). The lint validates a diagram element but never the notation
in its body, so a typo there would otherwise reach the reader as an error box; and it
can't see a heading rendered as CSS generated content, or left under `.cq-ui` with
nothing said about whose words these are, which leaves the reader looking at text they can't
comment on. When Chrome isn't installed, the gate fails and says so on stderr. It is
the page's whole browser budget; a screenshot after it reads neither the console nor
the second scheme.

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
