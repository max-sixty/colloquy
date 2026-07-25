# Changelog

## Unreleased

- Sign-off is now the page's ask, not standing chrome. The banner offers
  "✓ Looks good" only when the version declares
  `<meta name="cq-review" content="sign-off">` — a plan, design, or proposed
  change whose review ends in assent. An informational page (a status report, an
  incident chronicle, a product page) omits the meta and takes comments only.
  The declaration rides the document, so it versions with the page and a pinned
  older version keeps its own ask. `check` owns the head's `cq-*` meta
  vocabulary the way the registry owns `cq-*` elements: an unknown name or a
  `cq-review` value other than `sign-off` is rejected, since either would
  silently declare nothing.
- Keyboard bindings, in two scopes. Global single-key shortcuts, dispatched from one
  table that never fires from a typing context: `c` comments on the selection (or
  toggles the panel), `j`/`k` walk open threads with the page highlight in tow, `d`
  toggles the version diff, `[`/`]` step versions, `?` shows a reference rendered
  from the same table, and `Escape` backs out one layer per press (help → composer →
  reply → panel). Sign-off and resolve stay unbound on purpose. Focus-scoped keys
  belong to the focused control: `Enter` on a focused thread drops into its reply
  box; the board grip is now a real button — `Enter` grabs, arrows move the card
  (each step announced), `Enter` drops as the same single `move` action a drag sends,
  `Escape` or focus loss restores — and each choose option carries an injected
  "Choose" button, so Tab+Enter picks. Widgets register no global keys; the helper
  surface grows by `announce()` (a polite live region that toasts also route through,
  so moves and picks are announced to screen readers) and `keyHelp()` (rows for the
  `?` overlay).
- `cq-tabs`/`cq-tab`: parallel workstreams on one page — each tab is a
  self-contained sub-context and a generated strip switches between them. The open
  tab is the reader's view state, remembered per browser tab like scroll position:
  switching never sends an action and versions never carry it, so the widget stays
  off the action channel entirely. Inactive panels hide as `until-found`, so browser
  find-in-page reaches them and the owning tab opens itself; while Δ is on, each tab
  wears a count of the changed passages its panel hides. Ships the full keyboard
  tabs pattern (roving focus, arrow keys, real tablist/tab/tabpanel roles).
  Unupgraded and in print, panels stack as labeled sections.
- The runtime scrolls to comment anchors through a new reveal path: a closed
  `<details>` around the target opens, and a container widget holding it is asked to
  show it (`cq-reveal`, which cq-tabs answers by switching tabs). Previously a
  thread quote pointing into a collapsed `<details>` scrolled nowhere.
- Reading-position restore now runs on every arrival — reload and back, not only
  version switches — with the browser's own scroll restoration turned off: upgrades
  change the page's height after the browser restores (tabs collapse, diagrams
  render, diff files fold), so its offsets went stale. The landmark also never
  captures from inside a `[hidden]` subtree, whose descendants still measure under
  `until-found`.

- Board dragging rebuilt on vendored SortableJS 1.15.7 (single MIT file, pointer-driven
  `forceFallback` mode — native HTML5 DnD is gone): a placeholder holds the source slot
  instead of the card teleporting on first contact with a neighbor column, moves animate
  (FLIP, 150ms), swap hysteresis stops boundary flip-flop, empty columns accept nearby
  drops, auto-scroll works, and drags work on touch. Columns stretch to equal height, so
  the dead zones beside short columns are gone. Replayed moves (reload, second tab, a
  version landing) animate instead of teleporting.
- Affordances: the grip is visible at rest with a ~34px hit target; every choose option
  lifts on hover (the recommended card previously had none — the one option most likely
  to be picked looked least clickable); choose cards reserve badge room up front so a
  pick never shifts layout; the ✓ badge reads "your pick" only for this reader's pick,
  "chosen" when the markup carried it. One global `prefers-reduced-motion` guard covers
  theme, comment layer, and widget animation; JS-driven motion (smooth scrolls,
  Web-Animations moves) honors the same preference through a runtime export.

- Widget actions: interactive widgets report the user editing the document through
  them as `action` events on the same log as comments — `wait` delivers them, the
  banner flips, and the next version's markup carries the change. Until it ships, the
  live view is the version plus its own actions: a reload replays them, a second tab
  follows along live, and an edit made while Claude was already writing a version
  carries forward onto it rather than visibly reverting. Declining an edit is a
  version too — one shipped without the change, saying why in its changelog — and
  the view rolls back to the authored state when it lands.
- `cq-board`/`cq-column`/`cq-card`: a kanban board whose cards drag between columns —
  each drop reaches Claude as a `move` action naming the card, target column, and
  position. Dragging rides a grip so card text still takes selection comments;
  presentation is pure theme CSS, so an unupgraded page reads as a static board.
- `cq-options choose`: the second rider on the channel — clicking an option card
  picks it, the pick arrives as a `choose` action, and the card wears a green ring
  and ✓ badge until the next version marks it `chosen`. Text selections and link
  clicks inside cards don't choose. Works inside a thread reply too: a choose group
  there is an inline question, and the pick comes back as an action. Widget ids are
  one universe across the page and replies — `reply` and `check` both refuse a
  collision, since the runtime routes actions by id.
- An examples gallery (`examples/`): an incident report, a PR walkthrough, a status
  report, a design decision, and a draggable triage board — complete pages that lint
  clean against the shipped layer in the tests and double as authoring references.
- `examples/gallery.html`: the whole gallery on one page, one example per tab —
  generated from the sibling examples by `scripts/gallery.py`, with a test failing
  any commit where the two drift. Example ids stay disjoint across files (the
  generator embeds each `<main>` verbatim and refuses a collision), so an id means
  the same element standalone and in the gallery.

## 0.2.0 — 2026-07-24

- Widget system: pages carry `cq-*` elements (semantic markup) rendered by a theme the
  user owns. Ships `cq-options`/`cq-option` (a decision's alternatives, pure CSS),
  `cq-ref` (source reference resolved into a link via a per-page `cq-base` template),
  and `cq-diagram` (mermaid-source body rendered by a vendored mermaid). A JSON-Schema
  registry (`registry.json`) drives the runtime, `check`, and the new `catalog`
  subcommand, so renderer, linter, and the agent's docs can't drift apart.
- `cq-plan` (titled, numbered plan container) and `cq-milestones`/`cq-milestone` (a
  status-dot timeline whose chip row comes from a small upgrade) — the first widgets
  past v1, exercising authored composition: a plan holds milestones by nesting.
- The rest of the committed catalog: `cq-timeline`/`cq-event`, `cq-compare`/
  `cq-variant`, and `cq-metrics`/`cq-metric` as pure-CSS element-widgets (the metric
  delta colors by sign × direction, honestly, with no script), plus three upgraded
  body-parsers — `cq-diff` (unified diff with per-file collapse and counts),
  `cq-code`/`cq-note` (numbered walkthrough with highlighted ranges and line-anchored
  remarks), and `cq-tree` (indent-notation file tree with change badges).
- The page scaffold is now `<link rel="stylesheet" href="/theme.css">` plus
  `<script type="module" src="/colloquy.js">`: a shared theme (tokens, element styles,
  class idioms `.eyebrow`/`.lede`/`.tag`/`.callout`/`.facts`/`ol.steps`) replaces
  per-page CSS, and one ES-module runtime replaces `interact.js`, absorbing the comment
  layer and styling it from the theme's tokens.
- `init` vendors the layer (runtime, theme, registry, widget modules, vendor assets)
  into the page directory, overlaying shipped defaults with `~/.claude/colloquy/` and
  the project's `.claude/colloquy/` — approved versions can't change under their
  reviewer; re-running `init` is the explicit re-vendor.
- `check` grows registry validation: unknown tags, attribute schemas (required, enums,
  patterns, unknown attributes), nesting (`x-parent`, content models), rejection of
  self-closed `cq-*` tags, and duplicate-id detection.
- A version is served only once its changelog `note` lands (which follows a passing
  `check`), so a half-written or failing version is never live to an open browser.
- Claude's `reply` may carry widget markup, validated against the vendored registry at
  post time and rendered live in the thread; user comments stay plain text.
- Suggested edits: the selection composer's "Suggest replacement text" mode seeds the
  box with the quoted passage to edit in place; the thread shows the replacement as a
  tinted "suggested replacement" body, and the skill directs Claude to take it verbatim
  into the next version or reply with why not.
- Element anchors: diagrams and images, which have no text to select, take comments by
  click — the same 💬 button, anchored to the element's id. The element wears an
  outline while its thread is open, and the thread shows a § chip that jumps to it.
- Version diff: a Δ toggle in the banner marks every passage changed or added since
  the previous version, so re-reviewing a revision is cheap. Block-level and
  additions-only; data-widget bodies are opaque to it.
- `export`: the review thread as Markdown (versions with changelogs, threads with
  quotes and resolution state, sign-off), for reuse in a PR description.
- Dark mode: every surface in the theme and the injected comment layer rides a token,
  and a `prefers-color-scheme: dark` block swaps the palette — one block, nothing else;
  diagrams render with mermaid's dark theme to match.
- The `file://` no-server fallback is gone: the server is required, and remote sessions
  rely on port forwarding (an opt-in tunnel remains on the backlog).
- `interact.py` runs as a `uv` script: a PEP 723 inline-metadata header declares its
  dependencies (`click`, `jsonschema`), and the CLI is built on `click` instead of
  `argparse`. `uv` is now the one declared prerequisite for the plugin, replacing the
  plain-`python3`, standard-library-only invocation the previous release shipped.
- Pages follow the newest version automatically. Picking an older version in the picker
  pins the view (`?pin`); previously every page stayed put and only showed a "new
  version available" chip.
- Comment boxes grow with what you type, and ⌘/Ctrl+Enter sends from all three (the
  general box, a thread reply, the selection composer). Send buttons disable while the
  box is empty or a send is in flight.
- A reply arriving while you type no longer scrolls the panel or drops the cursor, and
  sending a reply clears its box.
- The selection composer shows the passage it quotes, which a `display` bug had been
  hiding, and stays on screen clear of the banner and the open panel.
- A thread whose passage isn't in the version on screen shows a dimmed, dashed quote
  instead of a link that goes nowhere.
- Sign-off comes from the event log, so "✓ Approved" survives a reload rather than
  inviting a second approval.
- The panel remembers whether it was open across version switches, Escape closes it,
  and the "Claude replied" toast opens it.
- A version switch also keeps the reader's place on the page: it re-finds the passage
  that was at the top of the screen instead of jumping to the top of the document.
  Position travels as a landmark (the passage's text within its section, then the
  section) so it survives content moving between versions.
- With no watcher, the banner says comments are saved and delivered next turn; the
  nudge-the-terminal wording is now reserved for a status stale by ten minutes.
- Keyboard selections raise the comment button, and the panel fits windows too narrow
  for a fixed 360px sidebar.

## 0.1.0

Initial release.

- `colloquy` skill: Claude presents a plan, design, decision, or findings as a
  commentable HTML page served on localhost, watches for selection-anchored comments,
  replies in-thread, and ships immutable revised versions with one-line changelogs.
- `/colloquy [topic]` command for explicit invocation.
- `interact.py`: standard-library Python 3 (no `uv`, no dependencies). Subcommands
  `init serve status wait reply note events stop check`.
- `check`: deterministic pre-handover lint (HTML parses, exactly one external script
  tag, anchor ids carried over from the previous version, no fixed-width overflow).
- `/colloquy-plans on|off` (experimental): redirect plan mode into a colloquy review
  page. Off by default.
- No-server fallback: a single self-contained `file://` HTML page when the browser
  can't reach localhost.
