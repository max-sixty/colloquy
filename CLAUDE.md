# colloquy

A page Claude hands the reviewer, and the loop that carries their comments back. The
README covers what it does; this covers how it is built, and the rules that keep it
buildable.

## Shape

Six things, and nothing between them:

- `skills/colloquy/scripts/interact.py` — a `uv` script: the server, the event log, the
  lint (`check`), vendoring, export. No daemon, no database. Reached as `colloquy`,
  through the `bin/` shim Claude Code puts on PATH for every enabled plugin, so the skill
  can hand an agent commands with no path to resolve and nothing shell-specific to
  expand.
- `skills/colloquy/assets/colloquy.js` — the runtime the page loads. One ES module owning
  the widget layer and the comment layer, with its stylesheet in a `<style>` block inside
  it. No build step.
- `skills/colloquy/assets/widgets/*.js` — one module per interactive widget, importing a
  small helper surface from the runtime.
- `skills/colloquy/assets/registry.json` — the vocabulary. The renderer, the linter, and
  the agent's documentation all read it, so none of them can drift from the others.
- `skills/colloquy/assets/theme.css` — the tokens and rules every page links, and that the
  runtime styles its own chrome from, so a page themes as one thing.
- `examples/` — six complete pages that are also the render suite's corpus, plus
  `gallery.html`, all six on one page (generated; edit the examples, not it).

The whole layer is vendored into each page directory at `init`. A page you approved can't
change under you when the defaults do.

## Norms

Each of these was learned by getting it wrong. The failure is named because the rule
without the failure is just a preference.

### One writer per thing

If two functions can write the same page state, they have to agree about who owns what
and who runs first — and that agreement lives nowhere the compiler or the tests can see
it. `paintAnchors` is the only thing that marks the page: threads' marks and the open
composer's draft mark are decided in one loop, so ownership is an `if` rather than a
protocol. Before that it was three functions, an ordering constraint stated only in a
comment, and a guard in one function reading a `data-` attribute the other wrote. Every
bug in that arrangement was the two drifting apart.

When you find yourself writing a guard that reads state another function wrote, the fix
is to merge the writers, not to add the guard.

### Derive rendering from state; never read it back

`composerOpen`, `fabAnchor`, `diffBase` are the state. `style.display` is a rendering of
it. Nothing reads `style.display` to find out what is going on, because the rendering has
values the state doesn't: `display` is `""` before an element is first shown, which is
neither `"block"` nor `"none"`, and a guard testing for one of them ran on every mousedown
in the document and swallowed the click.

A setter owns the pair (`showComposer`, `showFab`) and states the whole outcome, so it can
be called from anywhere without first asking what the current state is. It is not free —
`showComposer` repaints — so a caller firing on every mousedown says what it means
(`if (composerOpen && !composerInput.value)`) rather than the setter guessing which of its
callers was the noisy one. That guess was wrong once already: an early return meant for the
mousedown also skipped the repaint when the composer reopened on a new passage, stranding
the mark on the old one.

### One representation per concept

A passage is `{node, start, end}` segments — for the quote search, the quote capture, the
reading-position landmark, and the version diff's block keys alike. When there were four
answers to "what text is in this region", every one of them was some other one's bug: a
selection's `toString()` returns what `text-transform` rendered, so a quote captured that
way could never be found again.

A second representation earns its place only when the two things are genuinely different
(an element anchor has no text to paint, so it wears an outline). Not when they are the
same thing reached by different code.

### Paint; don't wrap

Marking text by wrapping it in an element splits text nodes, and a redraw that lands
between a mousedown and its mouseup swaps the node under the pointer — so the browser
dispatches no click at all, and a link inside a marked passage silently stops working.
The CSS custom highlight registry paints a `Range` and touches no nodes, so a redraw is
safe whenever it lands. That is what lets the same pass run from a mousedown handler and
from a poll.

What wrapping gave for free — knowing which thread the pointer is over, and the pointer
cursor — comes back as a geometric hit-test (`markAt`) over the pass's own record of what
it drew.

One thing does not come back: a painted range builds no accessibility node, where a
`<mark>` was a `mark` node, so a screen reader no longer hears that a passage carries a
comment — the panel, which lists every thread with its quote, is what says so now. Paint is
still right, because a mark nobody can click is worse than one nobody hears. State the cost
anyway: a norm that hides what it costs gets applied where it shouldn't be. `TODO.md` holds
the gap and the way out.

### Assume the browser it already assumes

The runtime requires ES modules, custom elements, `field-sizing`, `color-mix`, `:has()`,
and the highlight registry. Guarding one of those while assuming the rest buys nothing and
reads as if the others were checked. Add a feature guard only where there is a real
fallback to take.

A stale entry is the same mistake as a stray guard, so cut one the moment nothing uses it.
And the list promises support, not uniform rendering: `::highlight()` takes a narrow,
deliberately layout-free property set that engines implement unevenly, so a mark's tint
carries its meaning and the underline is a bonus.

### Everything the page says, the reviewer can point at

A reviewer selected a draft's text and commented on it, then tried the same on the label
naming that draft and got nothing back. He read the asymmetry as a bug, and it is one: a
label saying which draft you are looking at is exactly the thing to hang "this one's
wrong" on. It was a `<strong>` in a row marked `.cq-ui`, which the anchor pass skips. Its
author reached for that class meaning "this is chrome". What it means is "these are the
runtime's words, not the page's".

Chrome is a look, not a permission, and the reviewer has no such category. `.cq-ui`
belongs on the runtime's own layer and on the controls a widget injects — a control is a
thing to work rather than a thing to say, which is why its label is usually the name of
an action ("Save", "choose", the drag grip). A widget's own label, note, heading, or badge
wears `data-cq-gen` alone: the version diff looks away from it, the anchor pass does not,
and those two questions were never the same question.

The rule has a second edge, and that one had every shipped widget: `content: attr(label)`
paints glyphs into no text node, so a metric's headline number, a column's heading and an
option's risk could be read and not selected — no `.cq-ui` anywhere near them. Hence
`x-says` in the registry, and one runtime pass rendering what it names. Leaving it to each
widget would be leaving it to be forgotten, which is how it was forgotten the first time.
A widget writes its own only where the pass can't reach: one run of words at the element's
first or last child is all a pseudo-element could ever have been, so a chip row placed
after a title (`cq-milestone`) or a heading that doubles as a list's accessible name
(`cq-column`) is a module's job. Same span, same markers.

What stays out of reach is what a control says. State the cost where that leaves a word
with nowhere else to be said: after upgrade a `cq-tabs` strip button is a tab's only
label, and a settled `cq-options` row names the chosen card while collapsing it. Neither
is quotable, and both are in `TODO.md` rather than quietly absent.

### Widgets declare, the runtime decides

A widget module gets the helper surface `colloquy.js` exports, and no more until one
genuinely needs it. Widgets never register keys with a dispatcher: focus-scoped keys
belong to the focused control, and the global table (`KEYS`) is also the source of the `?`
overlay, so help can't drift from behaviour.

An `applyAction` implementation states an absolute placement, never a relative mutation,
because the poll replays it and the sender's own action must be a no-op.

### The document is the state

A reviewer's edit (a dragged card, a pick) posts an `action` and is replayed onto the
version on screen until Claude's next version carries it. Nothing is stored as "the
current board" anywhere; the log plus the version is the whole truth. Keep it that way —
a second store is a second thing to reconcile.

### Never lose user text

Every draft persists to `localStorage` on input; only a successful send clears one. Escape
and outside clicks hide, they don't discard. Cancel is the only discard.

## Working on it

- **Tests are integration tests in a real browser.** `test_render.py` drives the shipped
  examples through Chrome (`channel="chrome"`, so no download). Assert what a static lint
  can't reach. A synthetic `dispatchEvent(new MouseEvent("click"))` skips the mousedown
  and so sails straight past the whole class of bug above — use real mouse input
  (`page.mouse`, `locator.click()`) when the gesture is the point.
- **`node --check` proves syntax, not bindings.** A deleted `const` with six live callers
  passes it. Run the suite.
- **Measure before optimising and before assuming.** The cost claims in this codebase came
  from timing the real thing on `examples/gallery.html`, not from reasoning.
- **`check` runs on every version** and refuses one whose changelog `note` would publish a
  failing page. It's near-free and deterministic; keep it that way. The browser lives in
  `check --render`, run once per page at handover: its invariants are `render_version`,
  which `test_example_renders` drives over the shipped examples — one implementation, so
  the gate a reviewer's page passes and the suite the examples pass cannot drift.
- **Merge locally.** The project isn't at the stage of PRs: a finished branch lands with
  `wt merge`, a direct squash merge to main. That holds for background jobs too, whose
  harness default is to push and open a draft PR.
- **The main checkout is the installed plugin.** `.claude-plugin/marketplace.json` sets
  `source: "./"`, so Claude Code loads skills, commands, hooks, and `bin/` from the
  directory the marketplace points at, and landing on main publishes them. `claude plugin
  install` also copies the tree under `~/.claude/plugins/cache/colloquy/`, which nothing
  loads.
