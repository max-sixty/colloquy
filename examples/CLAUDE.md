# The examples

## Every widget in the vocabulary stands here

`examples/` is the whole corpus of eight sweeps in `test_render.py`: a page renders in
both palettes, holds still under a press, passes axe, gives up every passage to a quote,
answers an anchor written from its own file, and exports with its scripts gone. A widget
no example holds is a widget none of the eight has ever read inside a whole page, and the
gap reads as coverage, because the widget's own tests are green.

`cq-shot` and `cq-specimen` were outside the corpus from the day each was written — a
specimen stood on two `docs/` pages, which the sweeps do not read — so the sweep that
reads both palettes never reached one, and nothing could say a specimen's gutter was
painted in the dark palette until a fixture was written by hand for it
(`test_the_specimen_gutter_is_painted_in_both_schemes`).
`test_every_widget_in_the_vocabulary_stands_in_an_example` is the floor, read off the
registry, so the next widget joins the corpus by being declared.

The floor is the widget; the shapes it takes are a judgement. A `cq-options` group takes
its form from what its options hold and its arity from `multiple`, independently, so a
rule written for one form governs the other five combinations without saying so. No
example held a card-form `multiple` group. The empty box saying a slot is untaken was
then suppressed as though drawing it were the list form's business, every example stayed
green, and a card group asking "which of these" gave the reader nothing to count. Where
an attribute or a content shape changes what a reader sees, a page here shows it.

## An example is one version with an empty log

`restated`, `overruled` and `resolves` each name something the log holds — an action to
retract, a standing report to answer, a comment to close — so a page published as v1 with
nothing behind it cannot earn one, and `version check` refuses all three here. That is
the whole of what the corpus can't reach.

## The media an example names sits beside it

A `cq-shot` needs bytes a single file can't hold. `examples/media/` carries them,
content-addressed exactly as `colloquy page media` names them in a page directory, and
every place that builds a page directory out of an example lays them in it: `serve` and
`test_an_installed_payload_passes_its_real_browser_gate` in `test_render.py`,
`test_examples_pass_check`, `export_examples` in `scripts/site.py`, and
`scripts/preview.py`. A publisher that forgets fails loudly — `version check` refuses a
`/media/` reference the directory can't answer.
