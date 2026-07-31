# colloquy

A page Claude hands the reviewer, and the loop that carries their comments back. The
README covers what it does; this covers how it is built, and the rules that keep it
buildable.

## Soul

Everything here serves a high-fidelity connection between the agent and the person it is
working with. That is why the handover is a page. A terminal has one channel and one
width; a page has as many as the subject needs — a diagram, a board the reviewer drags,
two screenshots that flip in place — and it carries the reply back on the words that
prompted it. The vocabulary is something to build with rather than a form to fill in: a
shape colloquy hasn't got is one a project can add, since theme, registry and widget
modules all overlay from the user's own config.

Bandwidth is one axis; the other is time. A page that keeps up with the work — a list of
things ticking over as each is done — says more than the same list written afterwards,
and keeping it true costs a version rather than a paragraph. Build toward pages that are
the work itself.

## Stage

Early, and nothing owes the past anything. Nobody uses it, so there is no deployment,
no database, no page or log older than the directory in front of you that has to keep
working, and no command, flag, or name anyone has learned. Backward compatibility
carries zero weight: rename and reshape whenever the better form is clear, and treat a
name being the current one as no argument for keeping it. So the trade between
simplicity and robustness is already settled — take the simpler code. A guard earns
its place only where the state it defends against is reachable and there is something
to do about it; the rest is complexity paid for a case that never arrives, and it
reads as if the impossible were expected.

Where data enters, check it once and completely: browser events at `POST /api/event`,
authored markup at `version check`, a replayed action's detail in the widget's own
`applyAction`, since only it knows that shape. Everything downstream then indexes the
field rather than asking a second time whether it arrived.

## Shape

Claude Code and Codex both resolve `plugins/colloquy/` as the plugin payload:
`.claude-plugin/marketplace.json` and `.agents/plugins/marketplace.json` are the two
repo-root pointers, and the payload carries one manifest for each host. Six things make
the product, and nothing sits between them:

- `plugins/colloquy/skills/colloquy/scripts/interact.py` — a `uv` script: the server, the event log, the
  lint (`version check`), what a message renders to, vendoring, export. No daemon, no database. Reached as `colloquy`,
  through the payload's `bin/` shim: Claude Code puts it on PATH and Codex resolves it
  from the active skill directory.
- `plugins/colloquy/skills/colloquy/assets/colloquy.js` — the runtime the page loads. One ES module owning
  the widget layer and the comment layer, with its stylesheet in a `<style>` block inside
  it. No build step.
- `plugins/colloquy/skills/colloquy/assets/widgets/*.js` — one module per interactive widget, importing a
  small helper surface from the runtime.
- `plugins/colloquy/skills/colloquy/assets/registry.json` — the vocabulary. The renderer, the linter, and
  the agent's documentation all read it, so none of them can drift from the others.
- `plugins/colloquy/skills/colloquy/assets/theme.css` — the tokens and rules every page links, and that the
  runtime styles its own chrome from, so a page themes as one thing.
- `examples/` — complete pages that are also the render suite's corpus, plus
  `gallery.html`, all on one page (generated; edit the examples, not it).

`plugins/colloquy/hooks/hooks.json` is shared too: both hosts speak its three events,
and Codex supplies `CLAUDE_PLUGIN_ROOT` as a compatibility alias. The launcher maps
Codex's thread identity into the session record that Claude Code supplies directly.

The whole layer is vendored into each page directory by `page init`. A page you approved
can't change under you when the defaults do.

A page's own images are the one thing in that directory the layer doesn't put there, and
they hold the same promise a different way: `page media` names each file by the hash of its
bytes, so a name can only ever mean one picture. That is also the only door an image has.
The page's author is a language model, and a screenshot is a megabyte of base64 it cannot
type — nor should each version carry a copy of one that a `version check` walks and a
browser reloads. So the transport was never an optimisation over inlining; inlining was
never available.

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

Two readings of one element's words are the case that does earn it, because they answer
different questions. `says` is what is on the screen for a reviewer to point at, so a
label a widget declared as the page's words is in it; `wrote` is what the author put
there, so everything an upgrade generated is out. The version diff wants the second (the
base version it compares against has no generated nodes at all) and so does a widget
naming one of its own parts — a picked row's mark is the page speaking, which belongs in
what a reviewer can quote and not in the row's name, or a question answered reads its own
answer back as part of what was asked. One reading with a flag would have been the same
two answers with nothing saying which is which.

A version is written in two languages, and each one is read by a parser for that
language: `_StructParser` for what the markup declares and `page_passages` for what it
says, `tinycss2` for the CSS a `<style>` block holds. A new question about a version is a
field on one of those readings rather than a pattern over the file's text, because a
pattern answers something adjacent to the question asked. The column check's three did:
the document read as a stylesheet handed a screenshot's base64 to the rule walker, `width`
needed a lookbehind to exclude `max-width` because it matched a name instead of reading a
property, and the scan for `style=""` never saw one written with the other quote.

Hand-rolling one is the same mistake a level down, and harder to see, because a
hand-rolled parser is right about the grammar it was written against. The brace walk those
patterns became knew that a comment's braces are not braces, and still read a `}` inside
`content: "}"` as the end of the block, dropping every declaration after it in that rule;
still read a rule holding both declarations and a nested rule as declaring nothing of its
own; and still told a fixed `900px` from a `calc(100% - 900px)` by asking whether the
string ended in `px`, which `900px !important` does not. CSS has no parser in the stdlib,
so the dependency is a real cost — one more wheel behind every `version check`, ~6ms to
read the theme — and it buys the grammar whole rather than one bug's worth at a time.

A message is written in a third language, and the same rule places its parser: Markdown
has none in the stdlib either, so `markdown-it-py` reads it whole. Where that runs is
what had a choice. The page's own code blocks are colored in the browser, because
coloring them in Python would put spans in the file Claude writes the next version from;
a message has no file, and reading it in the browser would have stood a second answer
beside the one the post-time gate uses — the two then having to keep agreeing about which
`<cq-tabs>` is a widget and which is a fenced picture of one. So it renders once, in
Python, and the panel injects the string that was validated. What a message *says* is
still the log's: the render is derived on every read and stored nowhere, which is what
leaves `review wait` and the transcript printing the words that were typed. The one
exception is what makes this about honesty rather than uniformity — a suggestion's
characters are bound for the page verbatim, so it arrives unrendered rather than showing
the reviewer an italic the next version will spell in asterisks.

What a message may inject is the vocabulary, not HTML. Prose says `Vec<T>`, and raw HTML
reads that as an element to open — `if a<b and c>d` as one with two attributes — so a
message written whole would lose its own words in front of the reviewer with nothing on
either side to say so. Every tag the registry can't name is escaped to the characters it
was written in, which leaves the markup that reaches the panel exactly the markup the
gate has a schema for.

### A widget's form follows its content, and each form states its own rules

`cq-options` renders as a grid of cards or as a list of rows, and nothing declares which:
an option leading with a `<strong>` title argues its own case, so a group holding one is
cards — until an option carries block content, an argument no 13rem card can hold, which
stacks the group into full-width argument rows with a `.facts` rail — and a group whose
options are bare labels is a question about the page and reads as a list. An attribute
saying `layout="rows"` would have been the same fact written twice, free to disagree with
the markup under it.

What that costs is paid in the stylesheet, and paying it the cheap way doesn't work. The
first draft left every card rule general and added row overrides after them, which is the
same shape as a guard reading state another function wrote: `cq-option[recommended]` is an
attribute selector and `cq-options:not(:has(…)) > cq-option` is not, so the card's accent
ring outranked the row's own look and a row wore a ring it had no border to hang on.
Chips pinned to a card's corners reached a row with no corners to pin to. So the rules
that only make sense for one form say which form — the reset never fires, because there is
nothing to reset — and a rule stays general only where it is true of both, which is most
of them.

The module is where this stops. It sees the difference exactly once (`for` renders a
reference) and never asks which form it is in, because a second reading of "am I rows?"
in a second language is two predicates to keep in step.

### The file's reading never claims more than the page's

An anchor is captured in two places and resolved in one. `selectionAnchor` captures from
the DOM, `review comment` captures from the version file, and `resolveAnchor` is still
the only thing that searches. Two captures are not two answers to "what does the page say here":
both write the same collapsed text under the same rules, so what the file's reading holds
the page holds too — where a module replaces what the file holds, the reading skips it,
and everywhere else a module only adds. The file alone is not enough: a reviewer's
decision moves the page's reading too, retiring a settled suggestion's losing slot, so
`review comment` reads the log and retires the same slot from its reading
(`x-retired-when` in the registry), refusing a quote into one by naming the decision
that removed it — and
where the decision empties its widget (a deletion accepted, an insertion refused), the
wrapper goes with the slot in both runtimes, because an element anchor asks what is on
the screen, which the markup's presence does not answer. Their
edit moves it the other way: an `edit` carries the whole new body and replay paints
exactly that, so the reading puts their words where the authored body was (`x-state`'s
body record, read through the fold) — quotable like any passage, adjacent to its neighbours,
with the words the edit replaced refused by naming it. Retirement drops and rewriting
substitutes because that is what each leaves on the screen; a fence would say the
reading doesn't know what stands there, and in both cases it knows exactly.

Keeping that true is not free, and the first draft wasn't. A board's module prepends each
column's heading, so a quote running from the lede into the first card matched a file the
page no longer resembled and anchored on nothing; a milestone's chips do the same
mid-element, where no edge keyword can reach. And a prefix captured one character wider
than the DOM's — a leading space the runtime's own collapse trims — is context no
occurrence can ever confirm, which silently costs the comment its copy.

So where the file can't model what a module writes, the reading stops rather than guesses:
`x-says` and `x-verbatim` cover what the registry can declare, a fence covers the rest, and
a quote across a fence is refused when it is written instead of detaching later in front of
the reviewer. The browser indexes those same fences before upgrades run and clips captured
context to them afterward, so neither capture claims neighbours the other cannot confirm.
A widget that writes words of its own declares them or stays fenced.

Context identifies an occurrence only when exactly one candidate confirms it in full.
If no candidate does, a quote that occurs once can still identify itself; a repeated quote
cannot. It detaches instead of falling back to document order, because an offset or ordinal
is not evidence that a revised copy is the one the reviewer meant.

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

A painted range builds no accessibility node either, where a `<mark>` was a `mark` node,
and no ARIA relation puts one back: on a block that isn't focusable, NVDA ignores
`aria-describedby` in browse mode and reports none of the labelling attributes on a bare
`<p>` at all, VoiceOver reads it only on an interactive, image or landmark role, and
`aria-details` is supported unevenly and says only that details exist. What every screen
reader announces in every mode is text, so the same pass writes one hidden, unselectable
button per block that holds a mark, saying how many comments are on it. Focus reveals it
like a skip link; activating it enters the first matching thread, and j/k continues from
there. It names the block rather than the words, because naming the words is wrapping them
again.

State the cost anyway: a norm that hides what it costs gets applied where it shouldn't be.
Writing text into the author's document is a thing to do carefully rather than freely —
the line has to stay out of a selection, out of the next quote, out of what a widget reads
back as its own, and out of the mutation stream a screen reader rebuilds its buffer on.
Each of those is a rule the pass keeps rather than a property it gets for free.

### The page holds still under the reviewer's aim

A reviewer works by pointing, and the gestures this product is made of are the long ones:
a double-click that opens an editor, a drag across three lines, a press on a row hanging
in the margin. Anything that moves between deciding where to point and arriving there is
aim thrown away. So a state change may repaint whatever it likes and must move nothing,
and where something has to move it moves as motion rather than as a jump, which is the
form the eye can follow to where the sentence went.

Two of the three ways a page moves are layout, and any geometry read catches them. An
element that resizes pushes its neighbours. A control that shows its state in metrics does
the same thing smaller — a selected tab set in 600 weight is a wider tab, so the strip
reshuffled under the pointer that had just pressed it — which is why the state a control
wears is paint (ink, rule, fill) and never weight or size. Metrics are shared with the
neighbours; paint is not.

The third moves nothing and is the one no measurement reaches. The draft's editor wore an
outset focus ring, so a double-click aimed at one word was answered by the frame around it
growing 2px on every side, corners rounding wider to match. Every rect was identical,
because in layout nothing had happened; what found it was a screenshot diff of the pixels
outside the box, which is the check to reach for whenever the fix is a border, a ring, or
a shadow. Emphasis paints inside the box it belongs to.

Said positively, room is reserved before it is needed rather than taken when it is: the
draft's control row exists in both its views, so opening the editor adds no height; a
`choose` group holds the pick mark's strip on every card, because the pick can land on any
of them; the version chooser states a width rather than taking one from the longest note
Claude has yet published. Each spends something on a case that may not arrive, and that is
the trade — the alternative is paid at the moment the reviewer had something to say.

A shift before the first paint is not jerk, since nothing was on screen to move, and every
widget upgrade measured on the shipped examples lands there, ahead of its own page's first
paint — so hiding them behind `:not(:defined)` would buy nothing and cost every rendering
of the vocabulary that carries no script. And a change the reviewer asked for may change
the page: accepting a suggestion replaces the words, and the paragraph below moves because
the content did. What is forbidden is movement they did not ask for, and movement that
answers a small gesture with a large rearrangement.

### Assume the browser it already assumes

The runtime requires ES modules, custom elements, `field-sizing`, `color-mix`, `:has()`,
`@scope`, anchor positioning, `caretPositionFromPoint`, `Intl.Segmenter`, and the highlight
registry. Guarding one of those while assuming the rest buys nothing and reads as if the
others were checked. Add a feature guard only where there is a real fallback to take.

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

Chrome is a look, not a permission, and the reviewer has no such category — so the class
cannot be the whole of anchoring's answer. Whose words these are is declared where they
are written (`relabel`'s `says`, the same word paper reads), and the anchor pass takes the
nearest answer: the class where nothing nearer speaks, the declaration where one does, so
a label is the page's inside the chrome that holds it. Without that there is nowhere left
to put the words a control is the only place for.

`.cq-ui` still marks the runtime's own layer and the controls a widget injects — a
control is a thing to work rather than a thing to say, which is why its label is usually
the name of an action ("Save", "choose", the drag grip) — and still carries the face that
says "this is not the document". It just no longer decides. The line counting the comments
on a passage is the runtime's one word inside the page's own blocks: about the document
rather than of it, which is why it wears the class there and why the gate names it beside
the controls rather than as a heading someone hid. A widget's own label, note, heading or
badge outside a control declares nothing at all — `data-cq-gen` alone keeps it out of the
version diff and in reach of the anchor pass, and those two questions were never the same
question.

The rule has a second edge, and that one had every shipped widget: `content: attr(label)`
paints glyphs into no text node, so a metric's headline number, a column's heading and an
option's risk could be read and not selected — no `.cq-ui` anywhere near them. Hence
`x-says` in the registry, and one runtime pass rendering what it names. Leaving it to each
widget would be leaving it to be forgotten, which is how it was forgotten the first time.
A widget writes its own only where the pass can't reach: one run of words at the element's
first or last child is all a pseudo-element could ever have been, so a chip row placed
after a title (`cq-milestone`) or a heading that doubles as a list's accessible name
(`cq-column`) is a module's job. Same contract either way — generated, so the diff looks
away; no chrome marker, so the anchor pass doesn't — and `data-cq-said` beyond that only
where something else reads it: the theme keys the column heading's look on it, the chip
row has a class of its own.

A control that says one of those words is never a `<button>`. Chrome starts no pointer
selection inside a form control — not with `user-select: text`, and not on a span nested
inside one, which is what the plan this replaced assumed would work — so the words are on
screen and out of reach whatever they are marked. `offer` builds every press as a span wearing
`role="button"`, and one listener supplies the keys the UA would have — on the bubble, so
a control that handles Enter itself has already said so by preventing the default and the
runtime doesn't overrule the focused control. That is one place rather than each widget
remembering, and it costs nothing these controls used: no forms, and no `disabled`, which
a widget's press therefore cannot have. What the platform gives back has to be given back too — the press refuses a
drag exactly where nothing under it is said, since `user-select: none` on the control
takes the whole subtree with it and no descendant can win it back.

Then a drag that ends on a control is that selection's mouseup and not a press, which is
`offer`'s to know. Two guards around it each asked a question next to the right one and
paid differently. Where the *pointer* stopped is not it: a tab's name runs to within a few
pixels of its own padding, so the mouseup lands on chrome while the selection is the
page's, and the Comment button never came up. Whether the selection *contains* the control
is not it either, and that one cost more — containment is a fact about the DOM, and a
suggestion's row stands in the column between the block holding the change and the next
one, so a reviewer who read across the change and then reached for Accept pressed a
control that did nothing, and kept doing nothing, since a press that refuses a drag never
collapses the selection deadening it. The question is whether this click's own mouseup is
where the selection stopped, and the selection's focus end is that answer.

The button raised by that same drag is the other way a press goes missing, and it needs no
wrong question to do it: a selection fills the lines it covers, so the button placed beside
it lands in the margin, on the line a change's row hangs. Nothing was deadened — the
reviewer pressed the 💬 they could see and got a composer, because a press on it is not the
outside click that dismisses it. Floating chrome steps aside from what stands on the page
(`placeFab`), asked of `data-cq-offer` so it holds for any control any widget hangs.

Paper asks its own question and reads its own pair of markers. Print's question is "is
this a thing to work, and nothing else?", because nothing on paper can be pressed; the
class's answer is "these are the runtime's words". Keying print on the class cost a
printed decision the only words that stated it: a pick mark is a control and a statement
at once, and the settled row naming the chosen card is chrome too, so a printed group
said which option won only in a border colour greyscale drops, and a settled one said it
nowhere at all. So a control says which it is where its label is written — `offer`
marks the chrome a widget injects, `relabel` marks a label that turns out to be the page
speaking — print hides the declaration rather than the class, and the runtime's own layer
hides as one thing at its `@scope` root. No print rule anywhere has to remember a
control's label now: what `cq-tabs` still restores on paper is each panel's own authored
label, painted back on the panel because the strip that carried it is gone.

Each marker gets one writer, and the arrangement where one of them had two cost
something. `relabel` used to *clear* `offer`'s mark instead of adding its own, which made
that mark read "paper drops this" rather than "a widget injected this control" — so the
two other passes that ask it went blind on exactly the controls this norm is about. A
drag across a picked card's mark was a press again, and nothing but `cq-options`' own
guard on the card stood between the reviewer selecting the word and losing their pick.

`render_version` reads the page in both media and reports what the second drops — the
whole page, not the widgets in it, because a printout losing a paragraph is no better
than losing a widget's word. A label written without saying which kind it is throws
where the widget upgrades, and the console error is a finding of that same gate. What no
pass can catch is a wrong answer, since a statement declared an offer is exempt by
construction; that mistake is now made where the label is written, in front of whoever
wrote the word, rather than in a print rule three files away that nobody thought to
write.

### The widget list is never closed

The vocabulary grows by an entry in `registry.json` and a module beside it, and nothing
may assume it has seen the whole of it. A consumer that works from which widget it is
looking at is a consumer that stops at the ones it was taught, and it fails quietly
rather than loudly: it keeps working perfectly on those while silently doing nothing for
the next one, so the bug surfaces as a feature that was never wired up rather than as an
error. So a consumer works from what an entry declares — where a behaviour is wanted by
some widgets and not others, it becomes an `x-` key they declare and the consumer
dispatches on, and no branch anywhere reads `cq-diagram` and does something particular.
That binds the runtime, the lint, `version check --render`, `version export`, and the
skill's own prose alike; the test is whether a twelfth widget touches anything but its
module and its entry, and where it would, the thing missing is a declaration.

Most widgets are things a page contains, and those are anonymous outside their own
module. A few are part of the machine the list is defined against, and core names those
outright. The suggestion is the one today: the log settles it, `retirable_ids` is written
in terms of its slots, thread markup refuses one, and the banner offers to accept them
all. That name is a mechanism's, not a member's, so it isn't a special case waiting for a
declaration to replace it. Which kind a widget is has one question behind it — is this one
of the ways colloquy works, or one of the things a page can hold? Convenience is not an
answer to it; a widget joins the first set by having the loop written in terms of it.

Declare the general property, not the particular widget, or the special case has only
moved into the registry: `x-upgrade` says a module enhances this tag, not that mermaid
needs loading. The bar is real — an `x-` key the log records is a forever-contract the
vendored-layer stamp then carries (`$events`) — which is an argument for finding the
general shape, not for reaching past the registry.

A fact the whole layer shares belongs to the layer, under a `$` key, rather than to
whichever widget first needed it. The vendored tokenizer's language list lived in
`cq-code`'s `language` enum, and from there the only way for the lint to read it was to name
`cq-code`: the wrong home was the cause and the reach by name only the symptom, which is
why moving the list (`$languages`) is what let the widgets declare instead (`x-language`
names the attribute carrying one). The tell is a consumer indexing past the entry it was
handed — and the second tell is what such a consumer does when the reach comes up empty,
because a list read from the wrong place is a list that can move, and a check standing
down on `if not known` retires itself the day it does.

A widget module gets the helper surface `colloquy.js` exports, and no more until one
genuinely needs it. Widgets never register keys with a dispatcher: focus-scoped keys
belong to the focused control, and the global table (`KEYS`) is also the source of the `?`
overlay, so help can't drift from behaviour.

An `applyAction` implementation states an absolute placement, never a relative mutation,
because the poll replays it and the sender's own action must be a no-op. The verb, its
detail schema, its fold unit, and its record form are declared in the registry
(`x-state`), not known privately to the module: absoluteness is what makes the
reviewer's standing state a fold over the log, and the declaration drives the POST and
re-vendor contract gates, `version check`'s state gate, the record-lag report, the
runtime's uniform decided-but-unhonored mark, and the diff's state half without teaching
any consumer a widget by name. The registry doubles as the page's vocabulary stamp
(`$events`): the log is append-only and its verbs are a forever-contract, so
`version publish` refuses to write a `note` event the page's vendored layer doesn't read,
and `page init` refuses to re-vendor over a log recorded in vocabulary the incoming layer
no longer speaks — the lost-decision bug's third door, after version-scoping and
hand-copying: fifteen of this page's own `decide` events fell silent when the verb was
retired, and only the stamp makes that a refusal instead of a quiet no-op.

The traffic runs the other way too. A comment can land anywhere the reviewer can select,
so the hidden line announcing one lands inside widgets — and a widget reading its own light
DOM back gets the runtime's words along with the author's. `.cq-ui` is no help there: it
keeps chrome out of everything *the runtime* reads (the quote search, the capture, the
version diff), and `textContent` honours no markers.

Two rules, because there are two failures. The line goes on a text block or on the element
an anchor names, never on the inline run or body div between them: `cq-draft` seeds the
editor a reviewer types into from its body div, and a line left there arrived in the
textarea and posted with their edit. And a widget asking what its own slot holds calls
`says`, not `textContent` — a block inside a widget is still a block, so the line lands in
it legitimately, and `cq-suggestion` labelled itself from the raw text and offered to
accept "Retry three times. 1 comment". The first rule keeps the line out of a widget's
content; the second is for where it belongs there anyway.

### A widget's chrome outlives its handlers

`cq-shot` flips between two screenshots with a radio group and one `:has(:checked)` rule,
where a dragged wipe divider would have read more naturally. The reason is what a colloquy
page becomes once it leaves the server: rendered DOM, script tags dropped. The upgrade has
already run, so everything a module built is still on the page — and nothing it bound is.
A slider would freeze wherever the last reader left it. A radio's state belongs to the
browser, and CSS can see it.

That cuts both ways, and the first draft got the other half wrong: `checked` set as a
property leaves no attribute to serialize, so the standalone copy opened with neither
frame chosen and both of them stacked in the one cell. What a widget wants to survive
goes in an attribute, and the test that proves it strips every `<script>` before asking.

Print is the same question asked by a medium that has always been script-less, which is
why the answers coincide: paper drops the radios and stacks both frames, and the captions
naming them are `data-cq-gen` rather than `.cq-ui` — a frame's caption is the widget's own
word, like a column's heading, not a control's like "Save".

A copy is the third medium, and `version export` marks it as one: `.cq-copy` on the root.
The theme reads it as a guard rather than a case — a widget writes its affordance once,
inside `@media screen { html:not(.cq-copy) { … } }`, and everything outside that block is
the page the markup already describes, which is what a copy and paper both get by never
being handed the affordance rather than by undoing it. Where a control's state is the
browser's the widget has no such block and keeps working; where it needed a handler,
withholding the block is what stacks `cq-tabs`' panels and drops a strip that switches
nothing. The theme's `@media print` is then only what paper needs beyond a copy, and
paper needs two things: it can press nothing, so `cq-shot` stacks both frames there while
a copy still flips them, and it cannot edit the document, so it undoes the
content-visibility that `version export` removes outright by dropping
`hidden="until-found"` — a promise nothing in the file can keep, and one that takes the
collapsed element's layout with it, since the theme zeroes a hidden card's padding and
that padding is the room its chips are positioned into.

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

The container answers in script too, and the class had been answering for it. Whether
a widget's state has a version to contradict, and which block the reader's eye rests
on, are questions about *which document* an element is in; the layer is one container,
so they ask `.cq-chrome`. Asking `.cq-ui` was the same substitution the anchoring norm
above is about, and it worked for the same reason — the layer wears that face — right
up until a widget's own chrome, out on the page, wraps something of the page's. Where a
marker does own the question it still answers it: the class for the composer's quote,
the one injected element carrying an id (`[id]:not(.cq-ui)`), and `data-cq-offer` for a
thing to work, which is what a draft's double-click asks before it swallows the
browser's word selection.

### The document is the state, and the log outranks it

A reviewer's edit (a dragged card, a pick) posts an `action`, and every action replays
onto every version after the one it was made on. Nothing is stored as "the current
board"; the log plus the version is the whole truth. Keep it that way — a second store
is a second thing to reconcile.

There was a second store once, unnamed: recorded state in the log and authored state in
the markup, with the page's author expected to copy each decision from one to the other
by hand. `version check` guaranteed ids survived a republish and nothing guaranteed the
state on them did, so a forgotten copy silently un-made a decision. A reviewer
re-approved the same drafts version after version, and no part of the system said a word.

One writer, then: markup states the initial condition, the log every transition after
it. A version that says nothing about a decision leaves it standing. The cost lands
where the old design hid it — a version can't quietly revise what a reviewer acted on,
because replay would paint their state back over the revision — so `restated` on the
rewritten element retracts what rested on it, and `version check` refuses a bare rewrite
and an unearned `restated` alike (`restatement_errors`). Divergence comes in two kinds
and the gate reads both: words, through `spoken`, and declared state, through the fold — every
`applyAction` is absolute, so the reviewer's standing state is the last surviving
action per unit the registry's `x-state` declares, one linear scan and no replay
simulation. Writing the folded state is honoring; re-emitting the previous version's is
blessed silence; a unit with no surviving action is the author's again. And liveness
has one key space — the sending widget plus the detail ids it contains, in both
runtimes — or a group-level retraction floors differently in Python than in the
browser. State the registry doesn't declare gets the browser's backstop instead: replay
records the ids it wrote (`data-cq-replay-wrote`), and `version check --render` reports
the ones the author also changed since the previous version, so a markup assertion the
log overrides is heard rather than silently repainted.

That attribute is a declaration, not state: `version publish` records it on the `note`
event it publishes (one append — a second event could be torn from its note by a crash)
and the log carries it onward. Left in the markup it would hold for exactly one version,
because the version *after* a rewrite has nothing to declare, and its silence would hand
the retracted decision straight back — the same bug, one version later.

Both failures are invisible to the reviewer, so the question was never which is worse
but who can see each. A dropped decision is visible to nobody. A stale decision standing
over rewritten content is visible to the author as they rewrite it, and only they know
whether the rewrite invalidates it. Route a failure to whoever can adjudicate it: the
runtime preserves by default, and discarding costs the author a word.

### Never lose user text

Every draft persists to tab-local `sessionStorage` on input; absence and an empty value
are different, because deleting all of a `cq-draft` is still an edit. It survives reload
and version navigation, while another tab's successful send or Cancel cannot erase it;
submitted actions converge through the log instead. Only a successful send (or finding
the same value already authored) clears one. A send owns that input until its response,
so an earlier response can never clear or overtake newer text. Escape and outside clicks
hide, they don't discard. Cancel is the only discard.

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
- **`version check` runs on every version** and refuses one that `version publish` would
  expose as a failing page. It's near-free and deterministic; keep it that way. The
  browser lives in `version check --render`, run once per page at handover: its invariants
  are `render_version`, which `test_example_renders` drives over the shipped examples —
  one implementation, so the gate a reviewer's page passes and the suite the examples
  pass cannot drift.
- **Merge locally.** The project isn't at the stage of PRs: a finished branch lands with
  `wt merge`, a direct squash merge to main. That holds for background jobs too, whose
  harness default is to push and open a draft PR.
- **A session loads each host's cached copy, not the checkout.** Both repo-root
  marketplaces point at `plugins/colloquy/`, and both hosts install from GitHub main, so a
  payload change reaches a session only once pushed, and reaches the next session rather
  than the one that pushed it. Neither manifest declares a version, because that string is
  Claude Code's cache key: an unchanged one leaves the old copy in place and the update
  reports it as the latest. Without one the key is the commit, so Claude Code's periodic
  marketplace sweep installs each pushed commit on its own and nothing needs running.
  Codex installs from a marketplace snapshot it fetches separately and does not sweep, so
  a change reaches it through `codex plugin marketplace upgrade colloquy` and then
  `codex plugin add colloquy@colloquy`.
