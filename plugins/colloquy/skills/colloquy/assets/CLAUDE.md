# The page in the browser

The norms the runtime, the widget modules and the theme are built to. Each was learned
by getting it wrong, and the failure is named because the rule without the failure is
just a preference. The four that bind this layer and the Python side at once — the log
outranking the document, one representation per concept, the file's reading never
claiming more than the page's, and the widget list never being closed — are in the
repo's own CLAUDE.md.

## One writer per thing

If two functions can write the same page state, they have to agree about who owns what
and who runs first — and that agreement lives nowhere the compiler or the tests can see
it. `paintAnchors` is the only thing that marks the page: threads' marks and the open
composer's draft mark are decided in one loop, so ownership is an `if` rather than a
protocol. Before that it was three functions, an ordering constraint stated only in a
comment, and a guard in one function reading a `data-` attribute the other wrote. Every
bug in that arrangement was the two drifting apart.

When you find yourself writing a guard that reads state another function wrote, the fix
is to merge the writers, not to add the guard.

## Derive rendering from state; never read it back

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

## Paint; don't wrap

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

## The runtime's line lands inside widgets

A comment can land anywhere the reviewer can select, so the hidden line announcing one
lands inside widgets — and a widget reading its own light DOM back gets the runtime's
words along with the author's. `.cq-ui` is no help there: it keeps chrome out of
everything *the runtime* reads (the quote search, the capture, the version diff), and
`textContent` honours no markers.

Two rules, because there are two failures. The line goes on a text block or on the element
an anchor names, never on the inline run or body div between them: `cq-draft` seeds the
editor a reviewer types into from its body div, and a line left there arrived in the
textarea and posted with their edit. And a widget asking what its own slot holds calls
`says`, not `textContent` — a block inside a widget is still a block, so the line lands in
it legitimately, and `cq-suggestion` labelled itself from the raw text and offered to
accept "Retry three times. 1 comment". The first rule keeps the line out of a widget's
content; the second is for where it belongs there anyway.

## The page holds still under the reviewer's aim

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

The rule has an edge, and it is the pressed control's own line. Below that line the page
is content and may move, since a tab showing another panel is what the press was for. On
it nothing may move, because it is where the next gesture is already aimed. That edge is
what makes the rule checkable rather than a thing to remember: the press sweep walks every
control on every shipped example, holds the ones beside it still, and reads the single
property a widget hasn't got a say in — that a thing can be pressed. It found two more the
day it was written. The sign-off button's "✓ Approved" is 12px narrower than "✓ Looks
good", so signing off slid the version chooser and the Comments button right; a row-form
pick mark took the room for the word it says at the moment it was pressed, dragging that
row's § reference 54px out from under the pointer.

News arriving has no gesture behind it, so there is no press to draw a line around and the
edge falls around the whole of the chrome instead: its controls are addresses the reviewer
is holding whether or not they are looking at them, while the document below may still
change, because a fact arriving is what they are here to see. The banner takes all of it,
packed to the right against a spacer, and that decides who pays — a control that grows
moves itself and everything to its left, while everything to its right keeps its place. A
comment posted from the terminal took `Comments (9)` to `Comments (10)` and the version
chooser 6px with it; a second tab deciding the last pending suggestion took the ✓ Accept
all away and slid the New-version chip 148px right, under whoever was reaching for it.

Two sweeps are what make a reserved width safe to state as a number, and between them they
work every one: a press, and the poll, which is the half no gesture can reach. Room
reserved before it is needed gets measured in a browser, so it is a fact about one font,
free to stop covering when the words change or where the system font sets them wider.
Reserving and checking are one mechanism rather than two: the number alone is a guess that
stops being true silently, which is the failure this whole norm is made of.

A stylesheet lint was the first attempt at that check, and the shape is wrong. It reads
the selector, and the state a control shows is not reliably in one: a class the module
adds, a label the runtime rewrites, a count that gains a digit. It caught one of the four
real cases, missed the ring that prompted all this, and objected to every deliberate hover
lift. What a control does to its neighbours is a fact about a rendered page, so the page is
where to ask.

The poll then asks two things of reserving that a press never did. A control that comes and
goes claims its room the first time it appears and keeps it for the rest of the page's
life: reserving from the start would hold room on every row for news that page will never
get, and reserving nothing is the movement, so this spends only where the alternative is a
control moving and only on the pages that got the news. And a row out of room takes it from
whatever will give, so which control that is has to be chosen rather than left to the
stylesheet: the chooser was the one that could, so it did, dropping under the width it
states and putting every arrival back in play on any window narrow enough. What gives now
is the status text and the chip, both of them left of everything else on the row, where
what they give up moves nothing.

A shift before the first paint is not jerk, since nothing was on screen to move, and nearly
every widget upgrade measured on the shipped examples lands there, ahead of its own page's
first paint — so hiding them behind `:not(:defined)` would buy nothing and cost every
rendering of the vocabulary that carries no script. The one that doesn't is where the
rule's lower edge is. A diagram arrives at 163ms against a 52ms first paint and grows its
element 93px, so the page does move with something on it; it is still not jerk, because aim
needs a target and a moment to reach it and at a tenth of a second the reviewer has
neither. What would make it jerk is that number growing, and the number is a fact about the
vendored bundle rather than about the widget: mermaid's fetch completes 12ms *before* first
paint, and the 123ms after it is parsing and drawing 2.75MB, so nothing about when the load
is started reaches it.

Holding the first paint until the page is done becoming itself is the fix that suggests
itself, and the trade is bad. It buys that tenth of a second with a permanently blank page
whenever anything between the hide and the reveal throws or hangs — for a product whose
whole deliverable is the page, where the failure today is a readable page with broken
chrome. The one arrival that does have aim behind it needs none of it: a version switch is
a load the reviewer asked for, and the reading position is restored after the same
`settling` the SVG lands in, so it is re-found in the page that grew rather than in the one
that was about to.

And a change the reviewer asked for may change the page: accepting a suggestion replaces
the words, and the paragraph below moves because the content did. What is forbidden is
movement they did not ask for, and movement that answers a small gesture with a large
rearrangement.

## Assume the browser it already assumes

The runtime requires ES modules, custom elements, `field-sizing`, `color-mix`, `:has()`,
`@scope`, anchor positioning, `caretPositionFromPoint`, `Intl.Segmenter`, and the highlight
registry. Guarding one of those while assuming the rest buys nothing and reads as if the
others were checked. Add a feature guard only where there is a real fallback to take.

A stale entry is the same mistake as a stray guard, so cut one the moment nothing uses it.
And the list promises support, not uniform rendering: `::highlight()` takes a narrow,
deliberately layout-free property set that engines implement unevenly, so a mark's tint
carries its meaning and the underline is a bonus.

## Everything the page says, the reviewer can point at

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

## Three voices, because the page has three kinds of words

What the page *says* is prose a reviewer reads closely and points at. What it *labels* —
an eyebrow, a column heading, a chip, a table header, a metric's caption — is apparatus,
the page pointing at its own content. What it *shows* is evidence: code, diffs, trees,
timestamps. The norms here already turn on that distinction; until the theme had more
than one face, nothing on screen carried it. Document and chrome were the same system
sans, so "this is not the document" rested on size and colour alone — and those are the
two things that go first, colour being what a project theme overrides and size what a
dense page compresses.

So the page's own prose is a text serif, apparatus is the UI sans small and tracked, and
evidence is mono. `.cq-ui` reads `--sans` rather than naming a stack, which makes the
chrome's face a consequence of that one decision instead of a second one to keep in step;
a diagram reads the same token, because mermaid paints its own labels and would otherwise
carry a palette and a face from nowhere. Which voice a widget's words take is decided in
one rule in `theme.css` listing the apparatus, and that is the point of it: what counts
as a label is a judgement, and a judgement made in twenty rules is twenty chances to
answer it differently. It is a look and not a permission — the line the norm directly
above draws. A chip a widget says is set in the sans because it reads as machinery, and is
still the page's words, still something to select and quote. Nothing built through
`offer` belongs in that rule: those wear `.cq-ui`, which already answers in the same
face, so listing one is inert and reads as a claim that the runtime's chrome is the page.

The serif is stacked, not shipped, and the reason is the copy. `theme.css` is inlined
whole into every `version export` and parsed by `version check` on every version, so a
webfont has to arrive as a base64 blob in both — and referenced by URL instead it falls
back silently in exactly the medium that has no server to ask. Charter and Iowan Old
Style ship on macOS, Georgia everywhere else; each is a screen serif with a large
x-height, which is what matters at 17px.

Changing any of this moves every width someone reserved by measuring, and the press sweep
above is what says so — it named the sign-off button the day `--t-5` went from 13.5px to
14px and 110px stopped covering "✓ Looks good". Re-measure and restate the number; don't
derive it.

## A widget's form follows its content, and each form states its own rules

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

## A widget module takes the helper surface, and no more

A widget module gets the helper surface `colloquy.js` exports, and no more until one
genuinely needs it. Widgets never register keys with a dispatcher: focus-scoped keys
belong to the focused control, and the global table (`KEYS`) is also the source of the `?`
overlay, so help can't drift from behaviour.

## A widget's chrome outlives its handlers

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

## The chrome's rules stay inside the chrome

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

## Never lose user text

Every draft persists to tab-local `sessionStorage` on input; absence and an empty value
are different, because deleting all of a `cq-draft` is still an edit. It survives reload
and version navigation, while another tab's successful send or Cancel cannot erase it;
submitted actions converge through the log instead. Only a successful send (or finding
the same value already authored) clears one. A send owns that input until its response,
so an earlier response can never clear or overtake newer text. Escape and outside clicks
hide, they don't discard. Cancel is the only discard.

## Working on it

`node --check` proves syntax, not bindings: a deleted `const` with six live callers
passes it. Run the suite.

It does not reliably prove syntax either, and the runtime's stylesheet is where that
bites. Those rules live in a template literal, so a backtick written inside one of
their comments — quoting a token name the way prose does everywhere else in this
repo — closes the literal, and the CSS after it is parsed as code. A pair of them
leaves the file's backticks balanced, which is enough for `node --check` to pass a
file Chrome refuses outright: the module never loads, and every page is a bare
document with no chrome on it. `version check --render` is what says so, in one line.

Its cost is worth knowing before you spend it. A runtime that doesn't load doesn't
fail the suite quickly — it makes every browser test wait out its own timeout, at no
CPU, so the run stops looking broken and starts looking slow. Ninety minutes of that
reads exactly like a loaded machine. If the suite is somehow still going, render one
example before assuming it is contention.
