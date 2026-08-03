# The tests

Each of these was learned by getting it wrong, and most of the failures were a test that
passed while proving nothing.

## They are integration tests in a real browser

`test_render.py` drives the shipped examples through Chrome (`channel="chrome"`, so no
download). Assert what a static lint can't reach. A synthetic
`dispatchEvent(new MouseEvent("click"))` skips the mousedown and so sails straight past a
whole class of bug the runtime is built around — use real mouse input (`page.mouse`,
`locator.click()`) when the gesture is the point. Assert the outcome with `expect(...)`,
never a bare `is_hidden()` or `count()`: every gesture that sends is a round trip, and a
plain read taken right after one passes on a fast run and fails on a slow one, which is
worse than failing outright.

A render invariant belongs in `render_version` rather than in a test. That function is
what `version check --render` runs at handover, and `test_example_renders` drives it over
the examples, so the gate a reviewer's page passes and the suite the examples pass are one
implementation and cannot drift.

## A round trip is not over when its response lands

The runtime answers a post by polling, so what the page does about a send arrives with
that poll rather than with the post. The press sweep learned this the expensive way: two
matching frames read the page from before the press had an effect, and it caught its own
regression on about half of the runs written to prove it caught it. Watch the trip rather
than timing it. The runtime posts and reads state back through `fetch`, so one wrapper
sees both halves and no widget declares anything; a hold sized to `POLL_MS` states a
number the runtime is free to change, still guesses on a loaded machine, and charges every
press two seconds for a trip that takes ten milliseconds.
`wait_for_load_state("networkidle")` is not the wait either: with no navigation to answer
for, it returns at once.

`open_page` puts that wrapper on every page: a test that had to ask for the counter first
is a test that asserted straight through the trip instead, and counting costs a page
nothing. `ROUND_TRIP` is the page's own sends coming back, which is what to wait on before
reading the event log — a widget settles a decision in front of the reviewer before the
server has taken it, so the page reading done is not the log holding it. Polling the log
instead only ever asks after the send it names, and a stray one from the widget that was
supposed to stay quiet passes straight through it.

A file the test writes is the same trip the other way round, and `expect`'s own timeout is
the hold in disguise. A declared status, a bumped heartbeat, an appended event: none of
them announce themselves, so the page learns of each when its next poll asks, and an
assertion made straight after the write spends a whole poll interval of whatever budget
`expect` was given — 1.8 to 2.3 of the default five, measured, and every time, because
each assertion returns just after a poll lands. `told(page)` is that wait watched instead:
a poll counted out after the write went looking for it, and its answer is the page being
told. A wait's own timeout is the net under a hang rather than a budget for the work, so
once the wait is right the number is left alone: raising it buys back a margin while
hiding what is being bought, and lowering it — ten seconds for a version turnover where
the default gives thirty — makes the outcome a question about the machine.

## A wait consumes a fact the system states

A page that has not started moving is as still as one that finished, so a wait that
infers completion from stillness — two frames agreeing, a stretch with no change —
returns early exactly when the machine is loaded enough to fit its first samples in
ahead of the effect. `panel_settled` settled that way on a transition that had not
begun: a transition's first ticked frame still computes its start value, so the sample
at injection and the one on the next frame both read the margin the page already had.
The press sweep drew the same wrong inference from two matching frames before it
learned to watch the trip (above).

So a wait asks for what the system declares — an element existing,
`document.body.getAnimations()` emptying, the wrapped fetch resolving, a resize reaching
its listeners. Where stillness is itself the assertion, an observed edge precedes it: the
press sweep measures "nothing moved" only after `ROUND_TRIP` has watched the response
land, so the quiet it reads is after the effect. And a timing flake reproduces by
emulating the poller's own schedule in the page — `wait_for_function` runs its predicate
once at injection, then once per animation frame — which makes the failure a rate to
measure rather than a rerun to hope for.

An edge is not the same fact as arrival, and a gesture that moves the page twice is where
they come apart. Clicking a quote scrolls instantly to bring the passage's box on screen,
then smoothly to centre the painted range, and `scrollend` fires for each: the first is a
statement the browser makes, and it is 232 pixels short of where the click was aimed. The
fact worth waiting on is the destination — the mark reaching the middle, which is what
`scrollToThread` computed — because a glide that approaches it passes through no earlier
position that could be mistaken for it.

Where nothing will happen there is nothing to consume, and polling has no end. An absence
holds a window instead, long enough that the thing would have happened, with the length
derived from the mechanism rather than picked: a manually launched server must outlive
the grace a session watcher would have shut it down after, so the window is
`ORPHAN_GRACE_SECS` plus room to act. A window too short fails the other way round from
everything above — it passes vacuously rather than flaking — which is why nearly every
absence here holds none at all. A POST the test aborted cannot reach the log, and a
decision the page never took cannot be in it; those assert straight after the edge that
proves the gesture was handled.

## Be the loaded machine on purpose

Only a slow machine can say a suite is clear of all this. `COLLOQUY_TEST_LOAD=1` is that
machine: every `/api/state` answer held back three and a half seconds, so a poll-carried
effect lands a long way after the write that caused it, and the page's own JS throttled
twentyfold, so a listener, a frame, or a queued timer is still outstanding when the next
read arrives. The hold spends the margin an assertion made straight after a write lives
on. The throttle reaches what holding the network cannot, which is the page not having got
to its own work yet: `resized` exists because `set_viewport_size` returns on a fact about
the browser and the runtime's listener had not run, and `open_page` waits for the upgrade
stamp because the gallery, the heaviest page here, had not finished upgrading when the
banner appeared. Run it before believing the suite.

The hold goes on once the page is up, since a request permanently in flight is a page that
never reaches networkidle and so never finishes loading at all. Two tests went red on an
ordinary busy run, and being that machine on purpose found seven more standing on the same
margin: the ones that go red are only ever those with the least room, so fixing them
without running this again hands the next loaded run a different victim.

## A page's source is formatted, so ask what it says

Prettier formats the `.html` under `docs/` and `examples/`, and it re-derives every line
break in a paragraph — half of the corpus's, measured. So a sentence asserted as a
substring of a file is a sentence that fails the day it gets a word longer, somewhere
else. Collapse whitespace first, which is what a test about what a page *says* meant
anyway; the page's own reading (`spoken`) is the same answer where a test already has a
registry to hand.

Markup is the same rule for the same reason. A whole tag written out as a literal
encodes a formatter's opinion about attribute order and line breaks: prettier writes a
void element `<link … />` and splits a long one over four lines. Match the attribute
that carries the meaning, or a pattern that admits any tag around it. What made this
expensive once was that the literal lived in `scripts/site.py` rather than in a test —
it silently stopped matching, a generic path rule took the stylesheet href instead, and
every published page linked a GitHub source view in place of its CSS. The link resolved,
so the build's dead-link check said nothing; what noticed was a palette test reading
colours off the rendered page.

## A sweep that walks controls by index must prove it pressed them

A list read before the runtime injects its banner is a short list, and a short list skips
silently rather than failing — which is the vacuous pass, wearing the same green as the
real one. Pin the count across reloads, and check a new gate by putting each bug back and
watching it fail; a gate that has only ever passed has been tested for nothing.

## A captured stream nothing reads is a failure that names nothing

`check=True` over `capture_output=True` raises a `CalledProcessError` naming the command
and the exit status, and the streams it captured — the only account of what went wrong —
die with it, because nothing prints them. The demo recording failed that way three times
in one stress run and the cause stayed unconfirmable until the streams came back: two runs
sharing a page directory, with the traceback that said so sitting in `e.stderr` the whole
time.

Pytest already captures a child's output and prints it under the failure, so capture it in
the test only where something reads it, and where something does, assert the status
yourself with both streams in the message. A script the test drives owes the same of every
process it starts, or the test reports a silence the script was told the reason for. The
browser end of this is `open_page`, whose console says only "Failed to load resource".

## Reloading is not resetting

The panel's open state is in `localStorage` and the reading position and drafts are in
`sessionStorage`, all deliberately, so a fresh `goto` restores the state the last gesture
left. Clear both where a test means the page as published — an open panel crowds the
banner enough to absorb a shrinking button, and that alone decided whether a real
regression reproduced.
