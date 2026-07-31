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

## A sweep that walks controls by index must prove it pressed them

A list read before the runtime injects its banner is a short list, and a short list skips
silently rather than failing — which is the vacuous pass, wearing the same green as the
real one. Pin the count across reloads, and check a new gate by putting each bug back and
watching it fail; a gate that has only ever passed has been tested for nothing.

## Reloading is not resetting

The panel's open state is in `localStorage` and the reading position and drafts are in
`sessionStorage`, all deliberately, so a fresh `goto` restores the state the last gesture
left. Clear both where a test means the page as published — an open panel crowds the
banner enough to absorb a shrinking button, and that alone decided whether a real
regression reproduced.
