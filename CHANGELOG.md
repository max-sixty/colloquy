# Changelog

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
