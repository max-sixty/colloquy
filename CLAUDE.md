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

`page_passages` is that one answer on the Python side, so anything asking what a version
says slices it (`spoken`) rather than walking the markup again. A fifth answer would have
been quiet and wrong in the usual way: an attribute the registry marks `x-says` is a word
on the page, and a walk that only sees text nodes would say a picked option's `effort`
never changed.

### The file's reading never claims more than the page's

An anchor is captured in two places and resolved in one. `selectionAnchor` captures from
the DOM, `comment` captures from the version file, and `resolveAnchor` is still the only
thing that searches. Two captures are not two answers to "what does the page say here":
both write the same collapsed text under the same rules, so what the file's reading holds
the page holds too — where a module replaces what the file holds, the reading skips it,
and everywhere else a module only adds. The file alone is not enough: a reviewer's
decision moves the page's reading too, retiring a settled suggestion's losing slot, so
`comment` reads the log and retires the same slot from its reading (`x-retired-when` in
the registry), refusing a quote into one by naming the decision that removed it.

Keeping that true is not free, and the first draft wasn't. A board's module prepends each
column's heading, so a quote running from the lede into the first card matched a file the
page no longer resembled and anchored on nothing; a milestone's chips do the same
mid-element, where no edge keyword can reach. And a prefix captured one character wider
than the DOM's — a leading space the runtime's own collapse trims — is context no
occurrence can ever confirm, which silently costs the comment its copy.

So where the file can't model what a module writes, the reading stops rather than guesses:
`x-says` and `x-verbatim` cover what the registry can declare, a fence covers the rest, and
a quote across a fence is refused when it is written instead of detaching later in front of
the reviewer. A widget that writes words of its own declares them or stays fenced. Never
teach the passage reader about a widget by name — that is the drift the registry exists to
prevent, and this would be the fourth place to forget.

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

One thing comes back coarser: a painted range builds no accessibility node, where a
`<mark>` was a `mark` node, so the passage itself can't say it carries a comment. The
block it lands in says it instead — `aria-describedby` from that block to the comment's
own words in the panel, written by the same pass that paints, the author's own attribute
restored when the last thread leaves. A mark nobody can click is still worse than one
nobody hears; the trade stands, at a block's coarseness rather than in silence.

### Assume the browser it already assumes

The runtime requires ES modules, custom elements, `field-sizing`, `color-mix`, `:has()`,
`@scope`, and the highlight registry. Guarding one of those while assuming the rest buys nothing and
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

Paper asks the same question and answers it harder: nothing there can be pressed, so
`.cq-ui` doesn't print at all. Where a control's label is also the page's only statement
of a state, the widget owes paper that statement — `cq-tabs` hides its strip and each
panel's own label comes back, and a `cq-options` pick prints the mark on the card
carrying it. Skip that half and a printed decision rests on a border colour greyscale
drops, or, for a settled group whose summary row is UI too, on nothing at all.

### Widgets declare, the runtime decides

A widget module gets the helper surface `colloquy.js` exports, and no more until one
genuinely needs it. Widgets never register keys with a dispatcher: focus-scoped keys
belong to the focused control, and the global table (`KEYS`) is also the source of the `?`
overlay, so help can't drift from behaviour.

An `applyAction` implementation states an absolute placement, never a relative mutation,
because the poll replays it and the sender's own action must be a no-op. The verb, its
detail schema, its fold unit, and its record form are declared in the registry
(`x-state`), not known privately to the module: absoluteness is what makes the
reviewer's standing state a fold over the log, and the declaration is what lets four
consumers read it — check's state gate, the record-lag report, the runtime's uniform
decided-but-unhonored mark, and the diff's state half — without any of them being
taught a widget by name. The registry doubles as the page's vocabulary stamp
(`$events`): the log is append-only and its verbs are a forever-contract, so `note`
refuses to write a shape the page's vendored layer doesn't read, and `init` refuses to
re-vendor over a log recorded in vocabulary the incoming layer no longer speaks — the
lost-decision bug's third door, after version-scoping and hand-copying: fifteen of
this page's own `decide` events fell silent when the verb was retired, and only the
stamp makes that a refusal instead of a quiet no-op.

### The chrome's rules stay inside the chrome

Tags, attributes, nesting, and ids are registry-driven, so the renderer, the linter,
and the catalog can't drift apart. Class names have no registry entry; their owner is
the stylesheet's shape. The runtime's private rules sit in one `@scope` block rooted
at its own container, where no class a widget or a page coins can match them —
`cq-tabs` once marked itself `cq-live`, the chrome's name for its visually-hidden
live region, and every tabbed page clipped to a pixel. What is styled at document
level is the shared vocabulary, and only that: `cq-ui` and `cq-btn`, which a widget's
controls wear on purpose, and the marks the runtime paints onto the page's own
elements. A global rule is a widening of that vocabulary; the render suite pins the
list so widening is a decision rather than a leak.

### The document is the state, and the log outranks it

A reviewer's edit (a dragged card, a pick) posts an `action`, and every action replays
onto every version after the one it was made on. Nothing is stored as "the current
board"; the log plus the version is the whole truth. Keep it that way — a second store
is a second thing to reconcile.

There was a second store once, unnamed: recorded state in the log and authored state in
the markup, with the page's author expected to copy each decision from one to the other
by hand. `check` guaranteed ids survived a republish and nothing guaranteed the state on
them did, so a forgotten copy silently un-made a decision. A reviewer re-approved the
same drafts version after version, and no part of the system said a word.

One writer, then: markup states the initial condition, the log every transition after
it. A version that says nothing about a decision leaves it standing. The cost lands
where the old design hid it — a version can't quietly revise what a reviewer acted on,
because replay would paint their state back over the revision — so `restated` on the
rewritten element retracts what rested on it, and `check` refuses a bare rewrite and an
unearned `restated` alike (`restatement_errors`). Divergence comes in two kinds and the
gate reads both: words, through `spoken`, and declared state, through the fold — every
`applyAction` is absolute, so the reviewer's standing state is the last surviving
action per unit the registry's `x-state` declares, one linear scan and no replay
simulation. Writing the folded state is honoring; re-emitting the previous version's is
blessed silence; a unit with no surviving action is the author's again. And liveness
has one key space — the sending widget plus the detail ids it contains, in both
runtimes — or a group-level retraction floors differently in Python than in the
browser. State the registry doesn't declare gets the browser's backstop instead:
replay records the ids it wrote (`data-cq-replay-wrote`), and `check --render` reports
the ones the author also changed since the previous version, so a markup assertion the
log overrides is heard rather than silently repainted.

That attribute is a declaration, not state: `note` records it on the note event it
publishes (one append — a second event could be torn from its note by a crash) and the
log carries it onward. Left in the markup it would hold for exactly one version,
because the version *after* a rewrite has nothing to declare, and its silence would hand
the retracted decision straight back — the same bug, one version later.

Both failures are invisible to the reviewer, so the question was never which is worse
but who can see each. A dropped decision is visible to nobody. A stale decision standing
over rewritten content is visible to the author as they rewrite it, and only they know
whether the rewrite invalidates it. Route a failure to whoever can adjudicate it: the
runtime preserves by default, and discarding costs the author a word.

### Never lose user text

Every draft persists to `localStorage` on input; only a successful send clears one. Escape
and outside clicks hide, they don't discard. Cancel is the only discard.

## Working on it

- **Tests are integration tests in a real browser.** `test_render.py` drives the shipped
  examples through Chrome (`channel="chrome"`, so no download). Assert what a static lint
  can't reach. A synthetic `dispatchEvent(new MouseEvent("click"))` skips the mousedown
  and so sails straight past the whole class of bug above — use real mouse input
  (`page.mouse`, `locator.click()`) when the gesture is the point. Assert the outcome
  with `expect(...)`, never a bare `is_hidden()` or `count()`: every gesture that sends
  is a round trip, and a plain read taken right after one passes on a fast run and fails
  on a slow one, which is worse than failing outright.
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
