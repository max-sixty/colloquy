---
name: ui-sweep
description: Use the shipped examples like a user in a real browser and fix the interaction defects the sweeps can't see — placement, tracking, legibility, crowding. Run after runtime or theme changes, or as a standing dispatch.
---

# UI sweep

The suite holds the invariants somebody has already stated: render_version gates a
page's rendering, and the press and poll sweeps hold it still under the aim. The
defects that reach the user first are the ones nobody has stated yet — a float
that parts from its passage on scroll, a diagram scaled below legibility, an input
that stops growing at ten lines. Those are found by using the page. This skill is
that use: drive, judge, fix, pin.

## Drive

Serve pages the way tests/test_render.py does (`serve`, `open_page`, or the same
pattern in a scratch script) and drive them with real input. Tour the gallery and
one prose-heavy example, at 1200×900 and 1440×900, in both color schemes. At each
station take a screenshot and record the geometry it claims:

1. Select mid-paragraph, raise the 💬, open the composer, type twenty lines.
2. Scroll ±300px with the composer open.
3. ⌥-click a widget and repeat 2.
4. Repeat 1 with the panel open, and at the covering-sheet width.
5. Work the widgets: drag a card, pick an option, accept a suggestion, switch a
   tab, edit a draft.
6. Switch versions with a draft unsent.
7. Emulate print and compare with the screen reading.

## Judge

Read the frames against assets/CLAUDE.md — each norm there is a checklist row —
and against the craft the norms don't state: nothing stands on words being read or
written about, nothing renders below legibility, nothing runs out of room while
the screen has some, floats track what they point at. A finding is a reproduced
number or screenshot, not an impression.

## Fix and pin

Fix each finding, then pin it where the gate and the suite share it: a fact about
a rendered page goes in render_version, a fact about a gesture becomes a test in
test_render.py. Put the bug back once and watch the new check fail. A judgment
call — removing a control, redesigning a flow — goes in the report with its
screenshot, not in the diff. The run ends as a green branch and a report, and
landing waits for the go-ahead.
