"""What only a browser can see: that a page actually renders.

check is static — it parses the file and validates the vocabulary. Everything
downstream of that (a widget's upgrade, the theme's CSS, the runtime's injected
chrome) meets for the first time in the browser, and the failures that live
there are invisible to a linter. This suite drives the shipped examples through
the Chrome already on the machine and asserts the handful of things that were
each, at some point, wrong:

  - a widget that upgrades into a box of no size (cq-tabs marked itself with a
    class the runtime's chrome had already claimed for its visually-hidden live
    region, so every tabbed page rendered blank below the lede);
  - the document and the comment panel scrolling in one region, which stacks two
    scrollbars in the same few pixels at the window's right edge;
  - a text box sized by script, which had to shrink itself to re-measure and so
    flashed a scrollbar on every keystroke;
  - the passage under the open composer going unmarked, because focusing the box
    drops the browser's own selection and nothing drew it back.

One journey test walks the loop the product is — select a passage, comment on
it, drag a card, follow the next version, and find the comment still anchored —
and asserts the event log those gestures leave behind. The log is the trail
Claude actually reads, so it is the artifact worth pinning; the DOM along the
way is checked only where a step depends on it.

Chrome is driven through Playwright's `channel="chrome"`, which attaches to the
installed browser: no download, no build step, `uv` still the one prerequisite.
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from click.testing import CliRunner
from conftest import interact
from playwright.sync_api import expect, sync_playwright

EXAMPLES = sorted((Path(__file__).parent.parent / "examples").glob("*.html"))
assert EXAMPLES, "no examples found — parametrizing over an empty list tests nothing"

# A long page, so the document scrolls, and nothing else — the panel is the subject.
LONG_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>long</title>
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<h1 id="t">Long</h1>
{paras}
</main>
</body>
</html>
""".format(paras="\n".join(f"<p id='p{i}'>Paragraph {i}. " + "Filler. " * 20 + "</p>" for i in range(60)))

# A passage is quotable only in the form the page itself holds. The shapes the shipped
# examples already carry are swept by test_every_passage_in_a_real_page_can_be_quoted;
# what this fixture is for is the ones they don't have — inline markup (several text nodes
# to one selection), a widget whose body the runtime's own chrome sits inside, adjacent
# blocks (a selection across them reads as one line to the browser and as none to the
# source), a compound the page writes both ways, and a character straddling the quote cap.
INLINE_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>inline</title>
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<h1 id="t">Inline</h1>
<cq-options id="opts" choose>
  <cq-option id="opt-a"><strong>Keep the store</strong> Sessions stay where they are,
  which costs a replica and buys revocation for free.</cq-option>
  <cq-option id="opt-b"><strong>Signed tokens</strong> No store at all, until revocation
  quietly puts one back.</cq-option>
</cq-options>
<p id="p">A paragraph carrying <strong>bold text</strong> and <em>emphasis</em> inside it,
so that a selection across the middle of it lands in more than one text node.</p>
<p id="p2">A neighbouring block, so a selection reaching across the boundary between
them has a break in what the reader sees and none in what the document holds.</p>
<p id="compound">The setup is in the runbook and the rollback is one flag. When the
shadow index is ready we set up the comparison job and roll back the old one.</p>
<p id="cap">{long}&#128512;</p>
{filler}
<p id="q">A passage far enough down the page that a composer opened on it leaves the
first paragraph uncovered, which is what lets a test click a highlight up there.</p>
<figure id="fig"><svg viewBox="0 0 120 40" width="120" height="40" role="img"
aria-label="specimen"><rect x="2" y="2" width="116" height="36" fill="none"
stroke="currentColor"></rect></svg><figcaption>A specimen, for element anchors.</figcaption></figure>
</main>
</body>
</html>
""".format(
    filler="\n".join(f"<p id='f{i}'>Filler {i}. " + "Words. " * 20 + "</p>" for i in range(6)),
    # Exactly 399 characters before the emoji, so the 400-character cap falls between its
    # two UTF-16 halves — the boundary a naive slice cuts a character in two at.
    long=("Capped. " * 50)[:399],
)

# A decision already made and acted on, with the alternatives kept for the record.
SETTLED_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>settled</title>
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<h1 id="h">Session transport</h1>
<p id="lede">Decided last week; open the row for the alternatives.</p>
<cq-options id="transport" choose settled>
  <cq-option id="opt-lax" chosen><strong>Lax cookie</strong> Host-only, set by the auth
  origin, nothing for a script to read.</cq-option>
  <cq-option id="opt-strict"><strong>Strict cookie</strong> Tighter, but a session
  started from an emailed link arrives logged out.</cq-option>
  <cq-option id="opt-bearer"><strong>Bearer header</strong> Suits the mobile client;
  puts the id where every script can read it.</cq-option>
</cq-options>
</main>
</body>
</html>
"""


# A decision the page reports rather than offers: no `choose`, so there is nothing to
# press, and the mark the upgrade puts on the carried option is the page saying which
# one the document holds. The paragraph above it is the control — a passage nobody has
# ever doubted was quotable.
CARRIED_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>carried</title>
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<h1 id="h">Session transport</h1>
<p id="lede">Where the decision stands, for the record.</p>
<cq-options id="carried">
  <cq-option id="c-lax" chosen><strong>Lax cookie</strong> Host-only, set by the auth
  origin, nothing for a script to read.</cq-option>
  <cq-option id="c-bearer"><strong>Bearer header</strong> Suits the mobile client;
  puts the id where every script can read it.</cq-option>
</cq-options>
</main>
</body>
</html>
"""


# The words a widget renders from an attribute — a column's heading, a metric's number —
# with room around them, so a drag across one is an ordinary drag and not a two-pixel
# feat. Both column labels differ, so a quote can only anchor where it was picked.
SAID_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>said</title>
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<h1 id="h">This week</h1>
<cq-metrics id="numbers">
  <cq-metric id="m-open" value="1,204" delta="+18%" direction="up-good">Open sessions</cq-metric>
</cq-metrics>
<cq-board id="board">
  <cq-column id="col-now" label="In flight">
    <cq-card id="c-importer"><strong>Wire the importer</strong> Half done.</cq-card>
  </cq-column>
  <cq-column id="col-next" label="Queued">
    <cq-card id="c-backfill"><strong>Backfill the index</strong> Waiting on the importer.</cq-card>
  </cq-column>
</cq-board>
</main>
</body>
</html>
"""


# Short card titles, so the whole board fits in an expected ARIA snapshot and the
# snapshot stays about structure. One column starts empty: a keyboard user has to
# hear it to move a card into it.
BOARD_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>board</title>
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<h1 id="h">Sprint</h1>
<cq-board id="sprint">
  <cq-column id="col-todo" label="Todo">
    <cq-card id="card-heater"><strong>Heated perch</strong></cq-card>
    <cq-card id="card-baffle"><strong>Squirrel baffle</strong></cq-card>
  </cq-column>
  <cq-column id="col-done" label="Done"></cq-column>
</cq-board>
</main>
</body>
</html>
"""


# Exhibited widgets beside live ones, so a missing affordance can be pinned on the
# quoting rather than on a broken upgrade.
SPECIMEN_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>specimen</title>
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<h1 id="h">What a decision looks like</h1>
<cq-specimen id="spec" label="a decision">
  <cq-options id="quoted-group" choose>
    <cq-option id="q-shim"><strong>Shim the old schema</strong> Fastest to ship.</cq-option>
    <cq-option id="q-stage" recommended><strong>Migrate in stages</strong> Table by table.</cq-option>
  </cq-options>
  <cq-board id="quoted-board">
    <cq-column id="q-col" label="Doing">
      <cq-card id="q-card"><strong>Wire the importer</strong></cq-card>
    </cq-column>
  </cq-board>
  <cq-options id="quoted-settled" choose settled>
    <cq-option id="q-lax" chosen><strong>Lax cookie</strong> Host-only.</cq-option>
    <cq-option id="q-bearer"><strong>Bearer header</strong> Suits mobile.</cq-option>
  </cq-options>
  <p id="q-prose">Refill rules:
    <cq-suggestion id="quoted-suggestion">
      <cq-old>Refill every feeder each morning.</cq-old>
      <cq-new>Refill when the camera shows it half-empty.</cq-new>
    </cq-suggestion></p>
</cq-specimen>
<cq-options id="live-group" choose>
  <cq-option id="l-shim"><strong>Shim the old schema</strong> Fastest to ship.</cq-option>
  <cq-option id="l-stage" recommended><strong>Migrate in stages</strong> Table by table.</cq-option>
</cq-options>
<cq-board id="live-board">
  <cq-column id="l-col" label="Doing">
    <cq-card id="l-card"><strong>Wire the importer</strong></cq-card>
  </cq-column>
</cq-board>
<p id="l-prose">Refill rules:
  <cq-suggestion id="live-suggestion">
    <cq-old>Refill every feeder each morning.</cq-old>
    <cq-new>Refill when the camera shows it half-empty.</cq-new>
  </cq-suggestion></p>
</main>
</body>
</html>
"""


# A page with nothing to decide: the widgets under test arrive in the panel, on a
# reply, which is the other place markup renders.
REPLY_HOST_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>reply</title>
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<h1 id="h">Session store</h1>
<p id="intro">Redis, with a signed-cookie fallback for reads.</p>
</main>
</body>
</html>
"""

# Claude answering with a question to put and, beside it, the framing that question
# replaced — quoted, so the reply asks one thing rather than two.
SPECIMEN_REPLY = """Two shapes for the same question; this is the one I'd ship:
<cq-options id="rp-live" choose>
  <cq-option id="rp-shim"><strong>Shim the old schema</strong> Fastest to ship.</cq-option>
  <cq-option id="rp-stage" recommended><strong>Migrate in stages</strong> Table by table.</cq-option>
</cq-options>
And the framing it replaces, for the record:
<cq-specimen id="rp-spec" label="the April thread">
  <cq-options id="rp-quoted" choose>
    <cq-option id="rp-memory"><strong>App memory</strong> Nothing to build.</cq-option>
    <cq-option id="rp-sticky"><strong>Sticky sessions</strong> Until an instance recycles.</cq-option>
  </cq-options>
</cq-specimen>
"""

# Two decisions for a reviewer to take and a later version to honor, carry, or
# contradict: a pick and a move.
IMPORTER_CARD = '<cq-card id="card-importer"><strong>Wire the importer</strong></cq-card>'
REPLAYED_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>replayed</title>
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<h1 id="t">Rollout</h1>
<cq-options id="approach" choose>
  <cq-option id="opt-shim"><strong>Shim the old schema</strong> Fastest to ship.</cq-option>
  <cq-option id="opt-stage"><strong>Migrate in stages</strong> Table by table.</cq-option>
</cq-options>
<cq-board id="work">
  <cq-column id="col-doing" label="Doing">{card}</cq-column>
  <cq-column id="col-done" label="Done"><cq-card id="card-notes"><strong>Draft the notes</strong></cq-card></cq-column>
</cq-board>
</main>
</body>
</html>
""".format(card=IMPORTER_CARD)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        yield b
        b.close()


@pytest.fixture
def serve(tmp_path, monkeypatch):
    """Publish HTML as v1 of a fresh page directory and serve it, as the real
    server does — vendoring included, so the assets under test are this repo's."""

    def go(html, comments=0, anchored=()):
        monkeypatch.chdir(tmp_path)  # keep the project layer out of the overlay
        d = tmp_path / "page"
        assert CliRunner().invoke(interact.cli, ["init", str(d)]).exit_code == 0
        (d / "versions" / "v1.html").write_text(html)
        interact.append_event(d, {"kind": "note", "author": "claude", "version": 1, "text": "t"})
        for i in range(comments):
            interact.append_event(d, {"kind": "comment", "author": "user", "version": 1,
                                      "text": f"Comment {i}. " + "Long enough to wrap. " * 4})
        for section, quote in anchored:
            interact.append_event(d, {"kind": "comment", "author": "user", "version": 1,
                                      "text": "About this bit.",
                                      "anchor": {"section": section, "quote": quote}})
        # A subclass per server: page_dir is a class attribute, so two servers sharing
        # interact.Handler would both end up serving whichever directory was set last.
        handler = type("Handler", (interact.Handler,), {"page_dir": d})
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        servers.append(httpd)
        go.page_dir = d  # for tests that publish a v2 or read the event log
        return f"http://127.0.0.1:{httpd.server_address[1]}/versions/v1.html"

    servers = []
    yield go
    for httpd in servers:
        httpd.shutdown()


def open_page(browser, url):
    """A page with its console errors collected, settled enough for mermaid."""
    page = browser.new_page(viewport={"width": 1200, "height": 900}, color_scheme="light")
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    # The console's own word for a bad response is "Failed to load resource", which
    # names nothing; carry the status and URL so a failure says what went missing.
    page.on("response", lambda r: errors.append(f"{r.status} {r.url}") if r.status >= 400 else None)
    page.goto(url, wait_until="networkidle")
    page.wait_for_function("() => document.querySelector('.cq-banner') !== null")
    return page, errors


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda p: p.stem)
def test_example_renders(browser, serve, example):
    """Every shipped example loads clean and lays out, in both color schemes: no
    fail-soft error box, no console error, every visible widget occupies real
    space, no sideways scroll, no words on screen a selection can't reach. A
    widget that upgrades into a 1x1 box, or a heading painted by a pseudo-element,
    is the shape of failure a static lint cannot see. The invariants live in
    interact.render_version — the pass `check --render` runs on agent-authored
    pages — so this sweep also proves the gate a reviewer's page goes through."""
    assert interact.render_version(browser, serve(example.read_text())) == []


def test_the_gate_passes_a_page_that_carries_a_comment(browser, serve):
    """The gate refuses words under `.cq-ui` inside a widget, because a widget reaching for
    that marker is how a reviewer ends up unable to comment on a heading they can see. The
    line saying how many comments are on a passage wears the same marker and sits wherever
    the passage does — inside the widget, when that is where the comment was made. Unless
    the gate knows the difference, one comment on an option is a page nobody can hand over,
    and every page the sweep above renders is a page with no comments on it."""
    url = serve(INLINE_PAGE, anchored=[("opt-a", "Keep the store")])
    page, errors = open_page(browser, url)
    # Vacuous otherwise: the gate has to be looking at a page that has the line on it.
    page.wait_for_function("() => document.querySelectorAll('.cq-mark-note').length === 1")
    assert errors == []
    page.close()
    assert interact.render_version(browser, url) == []


def test_check_render_refuses_what_only_a_browser_can_see(serve):
    """`check --render` end to end, as the agent runs it: the static lint passes
    both of these versions, and only the one that renders clean may reach a
    reviewer. The broken version is deliberately unnoted — refusing it before
    `note` publishes it is the gate's whole job, so the preview server has to
    expose what no reviewer-facing server would."""
    serve(LONG_PAGE)
    d = serve.page_dir

    def gate(*args):
        return subprocess.run(
            [sys.executable, str(interact.__file__), "check", str(d), "--render", *args],
            capture_output=True,
            text=True,
            check=False,  # both exit codes are the subject
        )

    ok = gate()
    assert ok.returncode == 0, ok.stderr
    assert "renders clean" in ok.stdout

    # A vw width slips the static lint (which counts only px) and overflows only
    # in a layout engine.
    (d / "versions" / "v2.html").write_text(
        LONG_PAGE.replace("</main>", "<div style='width:150vw'>wide</div>\n</main>")
    )
    broken = gate("--version", "2")
    assert broken.returncode == 1
    assert "scrolls sideways" in broken.stderr


# A page that says one of its words on screen only. The rule is the page's own, which is
# the point: the gate asks what the printed page still says, not who took the words away.
PRINT_LOSS_PAGE = CARRIED_PAGE.replace(
    "</head>",
    "<style>@media print { #lede, #c-bearer { display: none } }</style></head>",
)


def test_render_reports_a_word_the_printed_page_loses(browser, serve):
    """A reviewer prints the page, or saves it to PDF for someone who wasn't in the
    loop, and whatever the screen said had better still be there. Ways it isn't, all
    silent: a control that is a statement as well as a thing to press (the pick mark,
    which is the only place a group says which option it carries) and a rule that
    hides page content in print, inside a widget or in plain prose. The gate reads
    the page in both media and reports what the second one drops.

    A control declared an offer is exempt, since paper has nothing to press: the same
    page's pick mark reads "chosen" and goes unreported either way."""
    assert interact.render_version(browser, serve(CARRIED_PAGE)) == [], (
        "a page whose print rendering keeps its words has nothing to report"
    )

    lost = interact.render_version(browser, serve(PRINT_LOSS_PAGE))
    assert [f for f in lost if f.startswith("[print]")] == [
        '[print] <p id=lede> drops "Where the decision stands, for the recor", '
        "which it says on screen",
        '[print] <cq-option id=c-bearer> drops "Bearer header", which it says on screen',
        '[print] <cq-option id=c-bearer> drops "Suits the mobile client;\\n  '
        'puts the id w", which it says on screen',
    ], lost


UNPARSEABLE_DIAGRAM = LONG_PAGE.replace(
    "</main>",
    "<cq-diagram id='d-broken'>\nflowchart LR\n  A[Start --&gt; B{{{ ]]] broken\n</cq-diagram>\n</main>",
)


def test_the_shim_runs_the_gate_from_anywhere(serve, tmp_path):
    """`colloquy` is what the skill hands an agent, so the shim's own resolution
    is load-bearing: it finds the script from its location rather than the cwd,
    and on `--render` it supplies the Playwright the PEP 723 header deliberately
    omits. Running it from an unrelated directory exercises both.

    The version under it carries a mermaid body that doesn't parse — a shape the
    static lint cannot reach, since it validates the element and never the
    notation inside it. The widget fails soft and the browser half is what sees
    the error box, which is why the gate is worth its couple of seconds."""
    serve(UNPARSEABLE_DIAGRAM)
    d = serve.page_dir
    assert CliRunner().invoke(interact.cli, ["check", str(d)]).exit_code == 0

    shim = Path(__file__).parent.parent / "bin" / "colloquy"
    run = subprocess.run(
        [str(shim), "check", str(d), "--render"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 1, run.stdout + run.stderr
    # "needs Playwright" here would mean the shim dispatched the plain `uv run`.
    assert "failed soft" in run.stderr and "Parse error" in run.stderr


def test_page_and_panel_scroll_in_separate_regions(browser, serve):
    """The document scrolls its own column, not the viewport. If it scrolled the
    viewport, its scrollbar would be drawn at the window's right edge — over the
    panel, in the same pixels as the thread list's own — and the two thumbs would
    stack. The regions must not share an edge."""
    page, _ = open_page(browser, serve(LONG_PAGE, comments=12))
    page.get_by_role("button", name="Comments", exact=False).click()
    page.wait_for_function("() => document.querySelector('.cq-panel').classList.contains('open')")

    geom = page.evaluate("""() => {
        const box = el => el.getBoundingClientRect();
        const body = document.body, threads = document.querySelector('.cq-threads');
        return { viewportScrolls: document.documentElement.scrollHeight > document.documentElement.clientHeight,
                 bodyScrolls: body.scrollHeight > body.clientHeight,
                 threadsScroll: threads.scrollHeight > threads.clientHeight,
                 bodyRight: box(body).right, threadsLeft: box(threads).left };
    }""")

    assert not geom["viewportScrolls"], (
        "the viewport is scrolling the document, so its scrollbar is drawn at the "
        "window's right edge — on top of the panel"
    )
    assert geom["bodyScrolls"] and geom["threadsScroll"], "both regions must overflow for this test to mean anything"
    assert geom["bodyRight"] <= geom["threadsLeft"], (
        f"scroll regions overlap: the page ends at {geom['bodyRight']}px, "
        f"the thread list starts at {geom['threadsLeft']}px"
    )
    page.close()


def test_covering_panel_takes_the_page_scroll_with_it(browser, serve):
    """Under 720px the panel covers the page instead of squeezing it, and the
    covered page gives up scrolling with its width: a wheel moves the sheet's
    thread list and never the page behind it. The page still follows navigation —
    a quote click positions it behind the sheet — and closing hands scrolling
    back right there. The resize path reaches the same states, since the layout's
    one writer runs from resize too."""
    page, _ = open_page(
        browser, serve(LONG_PAGE, comments=12, anchored=[("p40", "Paragraph 40.")])
    )
    page.set_viewport_size({"width": 500, "height": 600})

    # A reading position first, so surviving the sheet is observable.
    page.mouse.move(120, 300)
    page.mouse.wheel(0, 600)
    page.wait_for_function("() => document.body.scrollTop > 0")
    before = page.evaluate("() => document.body.scrollTop")

    page.locator("button[aria-expanded]").click()
    page.wait_for_function("() => document.querySelector('.cq-panel').classList.contains('open')")

    # One wheel over the page's visible sliver, one over the sheet. Waiting on the
    # second proves both were processed — input stays in order — so the first
    # having moved nothing is a real outcome rather than a race.
    page.mouse.move(60, 300)
    page.mouse.wheel(0, 400)
    page.mouse.move(400, 300)
    page.mouse.wheel(0, 400)
    page.wait_for_function("() => document.querySelector('.cq-threads').scrollTop > 0")
    assert page.evaluate("() => document.body.scrollTop") == before, (
        "the page scrolled behind the covering sheet"
    )

    # Navigation still positions the page: a quote click scrolls its passage into
    # view under the lock, so the sheet closes onto the passage it talked about.
    page.locator(".cq-quote", has_text="Paragraph 40").click()
    # Settled, not merely arrived: the click scrolls twice — instantly, to bring the
    # passage's own box into view, then smoothly to centre the painted range — so both
    # "it is on screen" and "scrollTop read the same twice" are already true while the
    # page is still moving, and a position read there is hundreds of pixels off the
    # resting one. Held for 200ms is the page saying it has stopped.
    page.wait_for_function(
        """() => { const t = document.body.scrollTop, now = performance.now();
                   if (window.__testLastTop !== t) {
                     window.__testLastTop = t; window.__testSince = now; return false;
                   }
                   const r = document.getElementById('p40').getBoundingClientRect();
                   return now - window.__testSince > 200 && r.top >= 0 && r.top < innerHeight; }"""
    )
    at_mark = page.evaluate("() => document.body.scrollTop")
    assert at_mark != before
    mark_top = page.evaluate("() => document.getElementById('p40').getBoundingClientRect().top")

    # Closing hands scrolling back, right where navigation left the page — measured on
    # the passage, not the number: unlocking returns the scrollbar, whose width reflows
    # the text where scrollbars are classic, and Chrome's scroll anchoring then nudges
    # scrollTop a pixel to keep the visible content put. The passage staying put is the
    # promise; the number is one rendering of it.
    page.get_by_role("button", name="Close comments").click()
    page.wait_for_function("() => !document.querySelector('.cq-panel').classList.contains('open')")
    page.wait_for_function(
        """(top) => Math.abs(document.getElementById('p40').getBoundingClientRect().top - top) < 2""",
        arg=mark_top,
    )
    page.mouse.move(120, 300)
    page.mouse.wheel(0, 200)
    page.wait_for_function(f"() => document.body.scrollTop > {at_mark}")

    # The resize path: narrowing onto an open panel locks, widening unlocks.
    page.locator("button[aria-expanded]").click()
    page.wait_for_function("() => document.querySelector('.cq-panel').classList.contains('open')")
    page.set_viewport_size({"width": 1000, "height": 600})
    page.wait_for_function(
        "() => getComputedStyle(document.body).overflowY !== 'hidden' && document.body.style.marginRight !== ''"
    )
    page.set_viewport_size({"width": 500, "height": 600})
    page.wait_for_function(
        "() => getComputedStyle(document.body).overflowY === 'hidden' && document.body.style.marginRight === ''"
    )
    page.close()


def test_a_coined_class_cannot_reach_the_chromes_rules(browser, serve):
    """The chrome's private rules live in one @scope block rooted at the runtime's
    own container, so whatever name a widget or a page coins, it matches none of
    them: cq-tabs once marked itself cq-live — the chrome's name for its
    visually-hidden live region — and every tabbed page clipped to a pixel. An
    element in the page wearing every scoped class at once must render exactly as
    its unclassed twin, and the classes styled at document level must be exactly
    the shared vocabulary a widget wears on purpose."""
    page, _ = open_page(browser, serve(
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>t</title>'
        '<link rel="stylesheet" href="/theme.css">'
        '<script type="module" src="/colloquy.js"></script></head>'
        "<body><main><h1>t</h1><section id=s><p>words</p></section></main></body></html>"
    ))
    surface = page.evaluate("""() => {
        const sheet = [...document.styleSheets].find(
            s => { try { return [...s.cssRules].some(r => r instanceof CSSScopeRule); }
                   catch { return false; } });
        const classes = sel => [...(sel || "").matchAll(/\\.([A-Za-z0-9_-]+)/g)].map(m => m[1]);
        const scoped = new Set(), global_ = new Set();
        const collect = (rules, into) => { for (const r of rules) {
            if (r instanceof CSSScopeRule) collect(r.cssRules, scoped);
            else if (r.selectorText) classes(r.selectorText).forEach(c => into.add(c));
            else if (r.cssRules) collect(r.cssRules, into); } };
        collect(sheet.cssRules, global_);
        const probe = document.createElement("div"), plain = document.createElement("div");
        probe.className = [...scoped].join(" ");
        probe.textContent = plain.textContent = "probe";
        document.getElementById("s").append(plain, probe);
        const cs = el => { const c = getComputedStyle(el), out = {};
                           for (const p of c) out[p] = c.getPropertyValue(p); return out; };
        const a = cs(probe), b = cs(plain);
        return { scoped: [...scoped], global: [...global_],
                 moved: Object.keys(a).filter(p => a[p] !== b[p]) };
    }""")
    assert "cq-live" in surface["scoped"] and len(surface["scoped"]) > 20, (
        "the @scope block is missing or nearly empty — the chrome has lost its rules"
    )
    assert surface["moved"] == [], (
        f"scoped chrome rules reached an element in the page: {surface['moved']}"
    )
    # Every one of these is worn by something the runtime puts inside the page rather than
    # inside its own container, which is exactly why a scoped rule could not reach it.
    assert {c for c in surface["global"] if c.startswith("cq-")} == {
        "cq-ui", "cq-btn", "cq-over-mark", "cq-mark-el", "cq-pending", "cq-ins-block",
        "cq-mark-note",
    }, "the document-level class surface changed: widen the shared vocabulary on purpose"
    page.close()


def test_settled_options_collapse_without_going_out_of_reach(browser, serve):
    """A settled decision reads as one line and the cards behind it stop spending
    the page's height — but they are hidden, not gone, so everything that used to
    reach them still does: the disclosure opens them, and a comment anchored in
    one opens the group on its way to the passage. A collapse a comment can't see
    through is worse than no collapse at all, because the thread still lists the
    quote and clicking it lands nowhere."""
    page, errors = open_page(
        browser, serve(SETTLED_PAGE, anchored=[("opt-strict", "arrives logged out")])
    )
    group = page.locator("#transport")
    height = "el => Math.round(el.getBoundingClientRect().height)"

    assert errors == []
    collapsed = group.evaluate(height)
    assert page.locator("#transport cq-option:visible").count() == 0
    row = page.locator("#transport .cq-settled")
    assert row.inner_text().startswith("Settled: Lax cookie")
    assert row.get_attribute("aria-expanded") == "false"

    row.click()
    opened = group.evaluate(height)
    assert page.locator("#transport cq-option:visible").count() == 3
    assert opened > collapsed * 3, (
        f"collapsing saved {opened - collapsed}px of {opened}px — a settled group "
        f"that still costs most of its open height isn't a sweep"
    )

    row.click()  # closed again, so the reveal below has something to open
    page.get_by_role("button", name="Comments", exact=False).click()
    page.locator(".cq-panel .cq-quote").first.click()
    assert page.locator("#opt-strict").is_visible(), (
        "clicking a thread's quote must open the group holding it"
    )
    page.close()


def test_a_printed_page_says_which_option_carries_the_pick(browser, serve):
    """Print drops the runtime's own layer as one thing, and the controls a widget
    injects with it: on paper there is nothing to press. The pick's mark is a control
    and a statement at once, though, so dropping it takes the statement too — and a
    settled group loses its summary row the same way, leaving a printed decision
    stated in the ok ring alone, a colour greyscale drops.

    So on paper a choose group renders as one that was never choosable: the marks
    offering a pick go, the one on the card carrying it stays and says so, and the
    strip of room the marks need is reserved where a mark shows rather than on
    every card. Which of the two a mark is saying is the label's own declaration
    (relabel), so paper needs no rule naming this widget — the same reason a tab
    strip goes while each panel's label comes back."""
    page, errors = open_page(browser, serve(SETTLED_PAGE))
    row = page.locator("#transport .cq-settled")
    expect(row).to_contain_text("Settled: Lax cookie")
    expect(page.locator(".cq-banner")).to_be_visible()

    # The strip the mark sits in: what the card's bottom padding holds over its own
    # base, so the measure follows the theme's spacing instead of pinning a number.
    strip = """el => parseFloat(getComputedStyle(el).paddingBottom) -
                     parseFloat(getComputedStyle(el).paddingLeft)"""
    pick = page.locator("#opt-lax .cq-pick")
    page.emulate_media(media="print")
    expect(page.locator(".cq-banner")).to_be_hidden()  # the whole layer, by its own root
    expect(row).to_be_hidden()  # the disclosure is a screen affordance; paper has the cards
    expect(pick).to_be_visible()
    expect(pick).to_have_text("chosen")
    expect(page.locator("#opt-strict .cq-pick")).to_be_hidden()
    assert page.locator("#opt-strict").evaluate(strip) == 0, (
        "a card whose mark can't print is holding room for it — an empty strip "
        "under a card the printed page says nothing about"
    )

    page.emulate_media(media="screen")
    row.click()
    expect(page.locator("#opt-strict")).to_be_visible()
    assert page.locator("#opt-strict").evaluate(strip) > 0, (
        "on screen the pick can still land here, and the card has to already hold "
        "the room or picking it moves the box"
    )
    assert errors == []
    page.close()


def test_a_pick_the_page_only_reports_can_still_be_pointed_at(browser, serve):
    """A group with no `choose` still says which option the document carries, and
    that word is a thing to say rather than a thing to work. So it goes the way
    every other word the page says goes: past the gate that hunts words on screen
    no selection can reach, and under a drag that raises the Comment button.

    It shipped the other way round. The mark is one element in two shapes — a
    button where there is a pick to make, a span where there isn't — and the span
    wore the button's `.cq-ui`, which anchoring skips, so a reviewer could read
    "chosen" and not point at it. Every shipped example declares `choose`, so the
    render suite never rendered the span and nothing said so.

    Quotable is half a pair, so the other half is here too: the diff parses the
    base version unupgraded, where no mark exists at all, and must not read this
    one as a change nobody wrote."""
    url = serve(CARRIED_PAGE)
    assert interact.render_version(browser, url) == []

    page, errors = open_page(browser, url)
    mark = page.locator("#c-lax .cq-pick")
    assert mark.evaluate("el => el.tagName") == "SPAN", "nothing to press means no button"
    box = mark.bounding_box()
    page.mouse.move(box["x"] + 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] - 2, box["y"] + box["height"] / 2, steps=8)
    page.mouse.up()
    assert page.evaluate("() => getSelection().toString()").strip() == "chosen", (
        "a drag across the mark selected nothing — the state is painted, not said"
    )

    page.locator(".cq-fab").click()
    page.wait_for_function("() => document.querySelector('.cq-composer').style.display === 'block'")
    assert composer_quote(page)["text"].strip("“”") == "chosen"
    page.locator(".cq-composer textarea").fill("say which version chose it")
    page.get_by_role("button", name="Comment", exact=True).click()
    page.wait_for_function("() => (CSS.highlights.get('cq-mark')?.size ?? 0) > 0")
    assert painted(page, "cq-mark") == "chosen"

    # A second version rewording the option nobody picked. The mark is written by
    # the runtime and stands in no version file, so the anchor on it has to be
    # found again in the page the reviewer now has — and read as no change,
    # since the base version this diff loads has no mark in it at all.
    d = serve.page_dir
    (d / "versions" / "v2.html").write_text(
        CARRIED_PAGE.replace("Suits the mobile client", "Suits the mobile client best")
    )
    interact.append_event(d, {"kind": "note", "author": "claude", "version": 2, "text": "two"})
    page.wait_for_url("**/v2.html", timeout=10_000)
    page.wait_for_function("() => (CSS.highlights.get('cq-mark')?.size ?? 0) > 0")
    expect(page.locator(".cq-thread .cq-quote.detached")).to_have_count(0)

    page.locator(".cq-banner button", has_text="Δ").click()
    page.wait_for_function("() => document.querySelectorAll('.cq-ins-block').length > 0")
    assert page.evaluate(
        "() => [...document.querySelectorAll('.cq-ins-block')].map(e => e.id)"
    ) == ["c-bearer"], "the diff read the mark as text the base version lacked"
    assert errors == []
    page.close()


def test_a_quoted_widget_exhibits_without_taking_input(browser, serve):
    """A specimen is a mention, not a use. The exhibited widgets render at full
    fidelity — that is the whole point of showing one — but wire nothing that
    would carry the reader's edits back, so an example decision can't be
    answered and an example board can't be dragged. The unquoted copies on the
    same page are the control: they prove the affordances are missing because
    the specimen suppressed them, not because the upgrade failed.

    Presentation and view state are not input, so they still run: a quoted
    settled group collapses like any other."""
    page, errors = open_page(browser, serve(SPECIMEN_PAGE))
    assert errors == []
    assert page.locator(".cq-error").count() == 0

    # The exhibit rendered: the gutter's caption, and cards with real size. The label is
    # the page's own word, so the runtime says it as text a reviewer can quote; only the
    # "specimen · " in front of it is the theme's, and only that is still pseudo-content.
    label = page.locator('#spec > [data-cq-said="label"]')
    assert label.text_content() == "a decision"
    assert label.evaluate("el => getComputedStyle(el, '::before').content") == '"specimen · "'
    assert page.locator("#quoted-group cq-option").count() == 2
    assert page.locator("#quoted-group cq-option").first.evaluate(
        "el => Math.round(el.getBoundingClientRect().height)"
    ) > 20

    # …but takes nothing back. Nothing pressable: no grips, and no mark that is
    # a button — an unpicked quoted card carries no mark at all, exactly as a
    # group that never declared `choose`. A click chooses nothing either (the
    # choose path sets `chosen` before it sends, so a pick would show here).
    assert page.locator("#quoted-group button.cq-pick").count() == 0
    assert page.locator("#quoted-board .cq-grip").count() == 0
    page.locator("#q-shim").click()
    assert page.locator("#quoted-group cq-option[chosen]").count() == 0

    # The document's own state still reads: the settled group's authored pick
    # wears its mark, as a span.
    assert page.locator("#quoted-settled span.cq-pick").count() == 1

    # A quoted suggestion shows what a pending change looks like — both slots
    # marked — and grows nothing to settle it with, so it is also not the
    # banner's to count or Accept all's to decide.
    assert page.locator("#quoted-suggestion cq-old").is_visible()
    assert page.locator("#quoted-suggestion .cq-sug-actions").count() == 0
    expect(page.get_by_role("button", name="Accept all (1)")).to_be_visible()

    # The control: the same markup unquoted wires all of it.
    assert page.locator("#live-group button.cq-pick").count() == 2
    assert page.locator("#live-board .cq-grip").count() == 1
    assert page.locator("#live-suggestion .cq-sug-actions").count() == 1

    # Nor the room for one. A quoted card stands at the height of a card in a
    # group that never declared `choose`, because that is what it is; reserving
    # the mark strip would leave every exhibit trailing 32px of space that,
    # quoted, nothing can ever fill.
    pad = "el => getComputedStyle(el).paddingBottom"
    assert page.locator("#q-shim").evaluate(pad) != page.locator("#l-shim").evaluate(pad)

    # View state still runs inside a specimen: the settled group collapsed.
    assert page.locator("#quoted-settled cq-option:visible").count() == 0
    page.locator("#quoted-settled .cq-settled").click()
    assert page.locator("#quoted-settled cq-option:visible").count() == 2

    # The exception, once that group is open: the card the document marks does
    # carry a mark, so it keeps the strip a live pick would.
    assert page.locator("#q-lax").evaluate(pad) == page.locator("#l-shim").evaluate(pad)
    page.close()


def test_the_specimen_gutter_is_painted_in_both_schemes(browser, serve):
    """The gutter is the whole marking, and it is the one part of a specimen with
    a color of its own: a token the dark block forgot would leave the bar
    transparent and the quoting silently gone. Nothing else catches that. No
    shipped example carries a specimen, so the sweep that drives the examples
    through render_version in both palettes never reaches one — and render_version
    would not object anyway, since a transparent border is not an error, resizes
    no box, and leaves every word selectable."""
    url = serve(SPECIMEN_PAGE)
    for scheme in ("light", "dark"):
        page = browser.new_page(color_scheme=scheme)
        page.goto(url, wait_until="networkidle")
        gutter = page.locator("#spec").evaluate("el => getComputedStyle(el).borderLeftColor")
        assert gutter not in ("rgba(0, 0, 0, 0)", "transparent"), f"[{scheme}] {gutter}"
        page.close()


def test_a_specimen_in_a_reply_is_quoted_there_too(browser, serve):
    """The panel is where a live question actually gets put — Claude's replies
    carry widget markup — so it is also where a quoted one has to stay quoted.
    One reply holds both: the question wires up and its pick reaches the log,
    the exhibit beside it does neither, and the gutter marking it renders in the
    panel's narrower column as it does in the document. The theme's specimen
    rules and quoted()'s closest() both have to reach outside <main>, and
    nothing else in the suite renders a specimen there."""
    url = serve(REPLY_HOST_PAGE)
    d = serve.page_dir
    interact.append_event(d, {"kind": "comment", "id": "c-ask", "author": "user",
                              "version": 1, "text": "What would the alternative look like?"})
    interact.append_event(d, {"kind": "reply", "author": "claude", "parent": "c-ask",
                              "version": 1, "text": SPECIMEN_REPLY})
    page, errors = open_page(browser, url)
    page.get_by_role("button", name="Comments", exact=False).click()
    page.wait_for_selector("#rp-live button.cq-pick")  # the reply's widgets upgraded
    assert errors == []

    # The gutter renders in the panel: the specimen rules aren't scoped to the
    # document's column, and neither is the label — which reaches the panel only
    # because renderSaid runs over a reply's markup too, where no custom element
    # upgrade would have carried it.
    label = page.locator('#rp-spec > [data-cq-said="label"]')
    assert label.text_content() == "the April thread"
    assert label.evaluate("el => getComputedStyle(el, '::before').content") == '"specimen · "'
    assert page.locator("#rp-spec").evaluate(
        "el => getComputedStyle(el).borderLeftWidth"
    ) == "2px"
    assert page.locator("#rp-quoted cq-option").count() == 2  # and the exhibit is all there

    # The exhibit takes the click first, so anything it sends would reach the log
    # ahead of the live group's pick — then the live group takes its own.
    assert page.locator("#rp-quoted button.cq-pick").count() == 0
    page.locator("#rp-memory").click()
    page.locator("#rp-stage").click()

    deadline = time.time() + 5
    while time.time() < deadline:
        actions = [e for e in interact.read_events(d) if e["kind"] == "action"]
        if actions:
            break

    assert [(e["widget"], e["detail"]) for e in actions] == [("rp-live", {"option": "rp-stage"})]
    assert page.locator("#rp-quoted cq-option[chosen]").count() == 0
    page.close()


def test_a_board_says_which_column_each_card_is_in(browser, serve):
    """Which column a card sits in is the one fact about it that isn't in its own
    text, and columns are three boxes side by side — geometry, which the
    accessibility tree doesn't carry. Flat, this board was six text runs and two
    Move buttons in a row: no boundary between the columns, and no button saying
    where its card was.

    Both halves are asserted from the tree itself rather than from the attributes
    behind it, because that is where they can be wrong: the column heading is CSS
    generated content, so the name reaching the tree once (as the list's) rather
    than twice depends on its alt text. Then a card moves, and the assertion is
    the second snapshot — a name set where the move happens goes stale on
    whichever path forgets to restate it, and there are four such paths."""
    page, errors = open_page(browser, serve(BOARD_PAGE))
    board = page.locator("#sprint")

    assert board.aria_snapshot() == (
        '- list "Todo":\n'
        "  - listitem:\n"
        "    - strong: Heated perch\n"
        "    - 'button \"Move: Heated perch — Todo\"': ⠿\n"
        "  - listitem:\n"
        "    - strong: Squirrel baffle\n"
        "    - 'button \"Move: Squirrel baffle — Todo\"': ⠿\n"
        '- list "Done"'  # empty, and still announced: it is a drop target
    )

    # Grab the second card and push it into the next column, the keyboard's path.
    board.get_by_role("button", name="Move: Squirrel baffle — Todo").focus()
    page.keyboard.press("Enter")
    page.keyboard.press("ArrowRight")
    page.keyboard.press("Enter")
    page.wait_for_selector("#col-done #card-baffle")

    assert board.aria_snapshot() == (
        '- list "Todo":\n'
        "  - listitem:\n"
        "    - strong: Heated perch\n"
        "    - 'button \"Move: Heated perch — Todo\"': ⠿\n"
        '- list "Done":\n'
        "  - listitem:\n"
        "    - strong: Squirrel baffle\n"
        "    - 'button \"Move: Squirrel baffle — Done\"': ⠿"
    )
    assert errors == []
    page.close()


def test_composer_grows_with_its_text_without_script(browser, serve):
    """The comment box fits its content, caps, and shrinks back — and no script
    touches its height. That last part is the point: sizing a textarea from JS
    means shrinking it to re-measure on every keystroke, and a box briefly too
    small for its own text flashes a scrollbar."""
    page, _ = open_page(browser, serve(LONG_PAGE))
    page.get_by_role("button", name="Comments", exact=False).click()
    box = page.locator(".cq-general textarea")

    page.evaluate("""() => {
        const ta = document.querySelector('.cq-general textarea');
        window.__styled = 0;
        new MutationObserver(() => window.__styled++)
            .observe(ta, { attributes: true, attributeFilter: ['style'] });
    }""")

    def state():
        return box.evaluate("""ta => ({ h: Math.round(ta.getBoundingClientRect().height),
                                        scrollable: ta.scrollHeight > ta.clientHeight })""")

    empty = state()
    box.type("A comment long enough to wrap onto a second line and then a third.")
    grown = state()
    box.fill("x " * 900)  # far past the ceiling
    capped = state()
    box.fill("short again")
    shrunk = state()

    assert grown["h"] > empty["h"], "the box must grow with its content"
    assert not grown["scrollable"], "a box that fits its text must not be scrollable"
    assert capped["h"] == 200, f"the box must stop at its ceiling, got {capped['h']}px"
    assert capped["scrollable"], "past the ceiling the scrollbar is real and belongs there"
    assert shrunk["h"] == empty["h"], "and it must shrink back"
    assert page.evaluate("window.__styled") == 0, "nothing may size the box from script"
    page.close()


# Two pending changes a line apart, and a third inside a widget that positions
# its own contents — the case where `left: 100%` would resolve against the card
# rather than the column and drop the controls back into the text.
SUGGESTION_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>suggestions</title>
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<h1 id="h">Feeder notes</h1>
<p id="replace">The camera survey found two dead zones.
  <cq-suggestion id="sug-refill">
    <cq-old>Refill every feeder each morning.</cq-old>
    <cq-new>Refill a feeder when its camera shows it half-empty.</cq-new>
  </cq-suggestion></p>
<p id="insert">Seed mix stays through the migration.
  <cq-suggestion id="sug-thistle">
    <cq-new>Switch the north feeder to thistle in autumn.</cq-new>
  </cq-suggestion></p>
<cq-board id="feeders">
  <cq-column id="col-todo" label="To do">
    <cq-card id="card-heater"><strong>Heated perch</strong>
      <cq-suggestion id="sug-in-card">
        <cq-old>Wire the south feeder.</cq-old>
        <cq-new>Wire the south feeder to the porch circuit.</cq-new>
      </cq-suggestion></cq-card>
  </cq-column>
  <cq-column id="col-done" label="Done"></cq-column>
</cq-board>
</main>
</body>
</html>
"""


def test_suggestion_controls_stay_out_of_the_column(browser, serve):
    """Review chrome hangs in the page margin, so the prose keeps the full column
    and reads as it will once the change is settled. Two things can pull the
    controls back into the text and neither is visible to the lint: a positioned
    ancestor, which `left: 100%` resolves against instead of the column, and a
    window too narrow to have a margin at all. Both must dock the row into flow
    rather than leave it overlapping the page."""
    page, errors = open_page(browser, serve(SUGGESTION_PAGE))
    assert errors == []
    column = page.locator("main").evaluate("el => el.getBoundingClientRect().right")
    box = "el => el.getBoundingClientRect()"

    margin_rows = page.locator("#sug-refill .cq-sug-actions, #sug-thistle .cq-sug-actions")
    assert margin_rows.count() == 2
    for i in range(2):
        assert margin_rows.nth(i).evaluate(box)["left"] > column, (
            "a control row overlapping the column re-wraps the prose it reviews"
        )
    # Two changes a line apart, so the rows would collide at their natural offsets.
    first, second = (margin_rows.nth(i).evaluate(box) for i in range(2))
    assert first["bottom"] <= second["top"], "control rows must not stack on each other"

    # Inside the card the row has no margin to hang in: it docks into flow, which
    # keeps it inside the card rather than over the column beside it.
    docked = page.locator("#sug-in-card .cq-sug-actions")
    assert docked.evaluate("el => el.classList.contains('cq-docked')")
    card = page.locator("#card-heater").evaluate(box)
    assert docked.evaluate(box)["right"] <= card["right"] + 1

    # No margin anywhere: every row docks, and nothing spills sideways.
    page.set_viewport_size({"width": 820, "height": 900})
    page.wait_for_function(
        "() => [...document.querySelectorAll('.cq-sug-actions')]"
        ".every(r => r.classList.contains('cq-docked'))"
    )
    assert page.evaluate("() => document.body.scrollWidth <= document.body.clientWidth")
    page.close()


def test_accepting_a_suggestion_settles_it_and_reaches_claude(browser, serve):
    """Accepting collapses the change to the proposal as ordinary prose — no
    tint, no strike, no leftover chrome — because the live view is the version
    plus the reviewer's actions, and the honoring version only has to catch up.
    The outcome has to reach the log too: what the reviewer sees settle and what
    Claude is told must be the same event."""
    page, errors = open_page(browser, serve(SUGGESTION_PAGE))
    accept = page.locator("#sug-refill .cq-sug-accept")
    assert accept.get_attribute("aria-label").startswith(
        "Accept the suggested change: Refill a feeder when"
    ), "the button names the proposal, not the text being replaced"

    accept.click()
    expect(page.locator("#sug-refill cq-old")).to_be_hidden()
    expect(page.locator("#sug-refill cq-new")).to_be_visible()
    assert page.locator("#sug-refill .cq-sug-actions").is_hidden()
    settled = page.locator("#sug-refill cq-new").evaluate(
        "el => getComputedStyle(el).textDecorationLine + ' ' + getComputedStyle(el).backgroundColor"
    )
    assert "line-through" not in settled and "rgba(0, 0, 0, 0)" in settled, (
        f"settled text still wears a pending mark: {settled}"
    )
    # The banner's count follows the page: three pending, one decided.
    expect(page.get_by_role("button", name="Accept all (2)")).to_be_visible()

    page.wait_for_function(
        "() => fetch('/api/state').then(r => r.json())"
        ".then(s => s.events.some(e => e.kind === 'action' && e.action === 'accept'))"
    )
    logged = [e for e in interact.read_events(serve.page_dir) if e["kind"] == "action"]
    assert [(e["widget"], e["action"], e["author"]) for e in logged] == [
        ("sug-refill", "accept", "user")
    ]
    page.close()


SHORT_SUGGESTION = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>short suggestion</title>
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<h1 id="t">Short</h1>
<section id="s">
<cq-suggestion id="sug">
  <cq-old><p id="was">Retry twice.</p></cq-old>
  <cq-new><p id="now">Retry three times.</p></cq-new>
</cq-suggestion>
</section>
</main>
</body>
</html>
"""


@pytest.mark.parametrize("outcome,verb", [("accept", "Accepted"), ("reject", "Rejected")])
def test_a_widget_naming_its_own_words_does_not_read_the_runtimes(browser, serve, outcome, verb):
    """The line saying a block carries a comment goes in the block, and a block inside a
    widget is still a block — so `textContent` on a widget's own slot now returns the
    author's words with the runtime's appended. A suggestion labels itself from that slot,
    and offered to accept “Retry three times. 1 comment”. It reads the slot the way the
    page is read instead, which is what `says` is for — read before deciding, because a
    reject retires the very slot the label comes from, and a retired slot says nothing:
    the toast then named the widget's id instead of the words the reviewer judged. Short
    on purpose: the label cuts at 48 characters, which hid this on every shipped example."""
    url = serve(SHORT_SUGGESTION, anchored=[("now", "Retry three times")])
    page, errors = open_page(browser, url)
    page.wait_for_function("() => (CSS.highlights.get('cq-mark')?.size ?? 0) > 0")
    # Vacuous otherwise: the line has to be inside the slot the label is read from.
    assert page.locator("cq-new #now > .cq-mark-note").count() == 1
    page.locator(f"#sug .cq-sug-{outcome}").click()
    expect(page.locator(".cq-toast")).to_have_text(
        f"{verb} “Retry three times.” — sent to Claude"
    )
    assert errors == []
    page.close()


def test_accept_all_decides_every_pending_suggestion(browser, serve):
    """The banner's button is a shortcut for the reviewer who has read the page
    and wants all of it, so it has to reach the ones their eye didn't: the
    suggestion inside a widget, whose controls dock in flow rather than hang in
    the margin. Each is decided individually, so the log records what was
    consented to one change at a time rather than one blanket yes."""
    page, errors = open_page(browser, serve(SUGGESTION_PAGE))
    page.get_by_role("button", name="Accept all (3)").click()

    for widget in ("sug-refill", "sug-thistle", "sug-in-card"):
        expect(page.locator(f"#{widget} cq-new")).to_be_visible()
        # Waited for, not read once: each is decided by its own round trip, so the
        # last of them is still in flight when the first has settled.
        expect(page.locator(f"#{widget} .cq-sug-actions")).to_be_hidden()
    for widget in ("sug-refill", "sug-in-card"):  # the two that replace rather than insert
        expect(page.locator(f"#{widget} cq-old")).to_be_hidden()
    # Nothing left to accept, so the button says nothing rather than saying zero.
    expect(page.get_by_role("button", name=re.compile("Accept all"))).to_be_hidden()

    logged = [e for e in interact.read_events(serve.page_dir) if e["kind"] == "action"]
    assert [(e["widget"], e["action"]) for e in logged] == [
        ("sug-refill", "accept"),
        ("sug-thistle", "accept"),
        ("sug-in-card", "accept"),
    ]
    assert errors == []
    page.close()


def test_a_decision_the_server_never_took_goes_back_to_pending(browser, serve):
    """The page settles a decision before the server has taken it, so the reviewer
    sees their own click land. That optimism is only honest if a send that fails
    puts it back: a suggestion that reads as settled while the log has nothing is
    a change the next version won't carry and the reviewer won't know to repeat."""
    page, errors = open_page(browser, serve(SUGGESTION_PAGE))
    page.route("**/api/event", lambda route: route.abort())
    page.locator("#sug-refill .cq-sug-accept").click()

    expect(page.locator("#sug-refill cq-old")).to_be_visible()
    expect(page.locator("#sug-refill .cq-sug-actions")).to_be_visible()
    assert page.locator("#sug-refill").get_attribute("data-cq-state") is None
    # And the page's own count is derived from that, so it comes back too.
    expect(page.get_by_role("button", name="Accept all (3)")).to_be_visible()
    expect(page.locator(".cq-toast")).to_contain_text("Couldn't send")
    assert [e for e in interact.read_events(serve.page_dir) if e["kind"] == "action"] == []

    # The retry is a second click, not a reload: the widget is pending again.
    page.unroute("**/api/event")
    page.locator("#sug-refill .cq-sug-accept").click()
    expect(page.locator("#sug-refill cq-old")).to_be_hidden()
    # The refused POST is the one thing the console may carry, and it is this test's
    # own doing — anything else means the page broke on the way back to pending.
    assert errors == ["Failed to load resource: net::ERR_FAILED"]
    page.close()


def test_a_decision_travels_between_tabs_and_the_log_has_the_last_word(browser, serve):
    """Two windows on one page are two views of one log, not two documents. A
    decision taken in either arrives in the other by the same replay that keeps a
    reload's drag — and deciding takes the controls away, so the tab that receives
    one has to settle it without the click that settled the tab that sent it. Where
    the two disagree, the later entry in the log is what both end on."""
    url = serve(SUGGESTION_PAGE)
    first, first_errors = open_page(browser, url)
    second, second_errors = open_page(browser, url)

    first.locator("#sug-refill .cq-sug-accept").click()
    expect(second.locator("#sug-refill cq-old")).to_be_hidden()
    expect(second.locator("#sug-refill cq-new")).to_be_visible()
    expect(second.locator("#sug-refill .cq-sug-actions")).to_be_hidden()  # nothing left to decide
    expect(second.get_by_role("button", name="Accept all (2)")).to_be_visible()

    # Now the race the controls make possible: a window cut off from the log still
    # shows both buttons, so the reviewer can decide the other way there. Two
    # decisions on one change, and the log's order — not either tab's belief —
    # settles it for both once the cut-off one catches up.
    third, third_errors = open_page(browser, url)
    third.route("**/api/state", lambda route: route.abort())
    first.locator("#sug-thistle .cq-sug-accept").click()
    # In the log before the reject is clicked, so which one is later is this test's
    # to decide rather than the network's.
    expect(second.get_by_role("button", name="Accept all (1)")).to_be_visible()
    third.locator("#sug-thistle .cq-sug-reject").click()
    third.unroute("**/api/state")
    for tab in (first, second, third):
        expect(tab.locator("#sug-thistle cq-new")).to_be_hidden()
    assert first_errors == [] and second_errors == []
    assert set(third_errors) <= {"Failed to load resource: net::ERR_FAILED"}, (
        f"the cut-off tab broke on more than the requests this test refused: {third_errors}"
    )
    for tab in (first, second, third):
        tab.close()


def test_render_reports_markup_the_log_replays_over(browser, serve):
    """The static gate refuses a version that rewords what a decision rests on,
    but `chosen`, a card's column, and their kind say nothing a text diff can
    see — a version asserting them against the log used to lose silently, replay
    painting the reviewer's state back over the author's intent. The render gate
    reports exactly that: an id the author changed since the previous version
    and replay then wrote. Silence (carrying the old markup forward) and honor
    (authoring the decided state) both stay clean, because silence changes no
    id and honor makes the replay a no-op."""
    url = serve(REPLAYED_PAGE)
    d = serve.page_dir
    for widget, action, detail in [
        ("approach", "choose", {"option": "opt-shim"}),
        ("work", "move", {"card": "card-importer", "to": "col-done", "index": 0}),
    ]:
        interact.append_event(d, {"kind": "action", "author": "user", "version": 1,
                                  "widget": widget, "action": action, "detail": detail})

    def publish(n, html):
        (d / "versions" / f"v{n}.html").write_text(html)
        interact.append_event(d, {"kind": "note", "author": "claude", "version": n, "text": "t"})
        return url.replace("v1.html", f"v{n}.html")

    # v2 says nothing about either decision; both stand, and nothing is reported.
    assert interact.render_version(browser, publish(2, REPLAYED_PAGE)) == []

    # v3 honors both: the pick authored, the card in its dragged-to column.
    honored = REPLAYED_PAGE.replace('id="opt-shim"', 'id="opt-shim" chosen')
    honored = honored.replace(IMPORTER_CARD, "").replace(
        'label="Done">', f'label="Done">{IMPORTER_CARD}'
    )
    assert interact.render_version(browser, publish(3, honored)) == []

    # v4 asserts the other option and re-authors the card into Doing: both
    # widgets changed since v3 and replay overrides both — the author must hear.
    contradicted = REPLAYED_PAGE.replace('id="opt-stage"', 'id="opt-stage" chosen')
    failures = interact.render_version(browser, publish(4, contradicted))
    assert len(failures) == 2, failures
    assert any("id=approach" in f and "opt-stage" in f for f in failures), failures
    assert any("id=work" in f and "card-importer" in f for f in failures), failures


def test_a_moved_card_wears_its_pending_state_until_honored(browser, serve):
    """A move outlives its toast: the card the reviewer moved stays marked as
    recorded-but-unwritten, in the tab that moved it and in a fresh replay
    alike, because the runtime compares the page's state against the version's
    own snapshot rather than remembering who wrote what. The card the move
    displaced stays unmarked — the log named one card, not its neighbours. The
    honoring version says the state itself, so on it the disagreement and the
    mark are gone."""
    url = serve(REPLAYED_PAGE)
    page, errors = open_page(browser, url)

    # The keyboard gesture takes the same #send path as a drag. The sender's own
    # replay is a no-op, which is exactly the case the version snapshot covers.
    page.get_by_role("button", name="Move: Wire the importer — Doing").focus()
    page.keyboard.press("Enter")
    page.keyboard.press("ArrowRight")
    page.keyboard.press("Enter")
    expect(page.locator("#card-importer")).to_have_attribute("data-cq-pending", "1")
    expect(page.locator("#card-notes")).not_to_have_attribute("data-cq-pending", "1")

    # A fresh tab reads the same fact from replay alone, and paints it.
    second, second_errors = open_page(browser, url)
    expect(second.locator("#card-importer")).to_have_attribute("data-cq-pending", "1")
    assert (
        second.locator("#card-importer").evaluate("el => getComputedStyle(el).outlineStyle")
        == "solid"
    )

    # The honoring version authors the card where the reviewer put it; replay
    # no-ops against it and the mark has nothing left to say.
    d = serve.page_dir
    honored = REPLAYED_PAGE.replace(IMPORTER_CARD, "").replace(
        'label="Done">', f'label="Done">{IMPORTER_CARD}'
    )
    (d / "versions" / "v2.html").write_text(honored)
    interact.append_event(d, {"kind": "note", "author": "claude", "version": 2, "text": "t"})
    third, third_errors = open_page(browser, url.replace("v1.html", "v2.html"))
    expect(third.locator("#col-done #card-importer")).to_be_visible()
    # Absence only counts once replay has decided every action.
    third.wait_for_function("() => document.body.dataset.cqApplied === '1'")
    expect(third.locator("#card-importer")).not_to_have_attribute("data-cq-pending", "1")

    assert errors == [] and second_errors == [] and third_errors == []
    for tab in (page, second, third):
        tab.close()


def test_a_pending_suggestion_can_be_discussed_instead_of_decided(browser, serve):
    """✓ and ✗ are the visible affordances, but a proposal a reviewer half-agrees
    with wants a sentence, not a verdict: the proposed words are ordinary page
    text, so selecting them and commenting works like anywhere else. Then the
    decision they eventually take has to reach the thread — rejecting retires the
    text the comment was made on, and a comment pointing into markup nobody can
    see has to read as detached rather than as a live mark that jumps nowhere."""
    page, errors = open_page(browser, serve(SUGGESTION_PAGE))
    page.evaluate("""() => {
        const r = document.createRange();
        r.selectNodeContents(document.querySelector('#sug-refill cq-new'));
        getSelection().removeAllRanges();
        getSelection().addRange(r);
        document.body.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
    }""")
    page.wait_for_selector(".cq-fab", state="visible")
    page.locator(".cq-fab").click()
    page.wait_for_selector(".cq-composer", state="visible")
    quoted = composer_quote(page)["text"]
    assert quoted.strip("“”") == "Refill a feeder when its camera shows it half-empty."
    page.locator(".cq-composer textarea").fill("Half-empty by whose reading?")
    page.locator(".cq-composer").get_by_role("button", name="Comment").click()

    thread = page.locator(".cq-thread .cq-quote").first
    expect(thread).to_be_visible()
    expect(thread).not_to_have_class(re.compile(r"\bdetached\b"))
    assert painted(page, "cq-mark") == "Refill a feeder when its camera shows it half-empty."

    page.locator("#sug-refill .cq-sug-reject").click()
    expect(thread).to_have_class(re.compile(r"\bdetached\b"))
    assert painted(page, "cq-mark") == "", (
        "a mark stayed painted on text the reviewer's own decision removed"
    )
    assert errors == []
    page.close()


def test_a_decision_already_in_the_log_retires_its_slot_at_load(browser, serve):
    """The test above takes the decision in front of the reviewer, on a page that has
    been up long enough for everything to have arrived. Here the log holds it before
    the page opens, which is what puts the anchor pass's skip list on the clock: the
    registry names the slot a decision retires (x-retired-when), and the registry
    arrives over the network, after the module that reads it has evaluated. Replay
    settles the suggestion on the first poll, so the pass that runs with it has to be
    skipping cq-old already — or the page opens with a live mark on words the reviewer
    accepted away."""
    url = serve(SUGGESTION_PAGE, anchored=[("replace", "Refill every feeder each morning.")])
    interact.append_event(serve.page_dir, {"kind": "action", "author": "user", "version": 1,
                                           "widget": "sug-refill", "action": "accept",
                                           "detail": {}})
    page, errors = open_page(browser, url)
    expect(page.locator("#sug-refill cq-old")).to_be_hidden()
    expect(page.locator(".cq-thread .cq-quote").first).to_have_class(
        re.compile(r"\bdetached\b")
    )
    assert painted(page, "cq-mark") == "", (
        "the first pass anchored inside a slot the reviewer's decision had retired"
    )
    assert errors == []
    page.close()


def test_a_reply_widget_replays_its_action_when_the_page_loads(browser, serve):
    """A widget inside a reply exists only once the panel has rendered the log,
    which is later than everything on the page — so the replay runs at the end of
    a poll, after that render, and an action naming a widget it doesn't find is
    one no version will ever hold (an honored suggestion, whose id the honoring
    version dropped) rather than one to look for again on the next poll."""
    url = serve(REPLY_HOST_PAGE)
    d = serve.page_dir
    interact.append_event(d, {"kind": "comment", "id": "c-ask", "author": "user",
                              "version": 1, "text": "Which of these?"})
    interact.append_event(d, {"kind": "reply", "author": "claude", "parent": "c-ask",
                              "version": 1, "text": SPECIMEN_REPLY})
    interact.append_event(d, {"kind": "action", "author": "user", "version": 1,
                              "widget": "rp-live", "action": "choose",
                              "detail": {"option": "rp-shim"}})
    page, errors = open_page(browser, url)
    page.get_by_role("button", name="Comments", exact=False).click()
    expect(page.locator("#rp-shim")).to_have_attribute("chosen", "")
    assert page.locator("#rp-live cq-option[chosen]").count() == 1
    assert errors == []
    page.close()


def painted(page, name):
    """What the page is painting under a highlight name, whitespace-flattened. Marks are
    ranges in the highlight registry, not elements, so this is where a test looks."""
    return " ".join(page.evaluate("""(name) => {
        const h = CSS.highlights.get(name);
        return h ? [...h].map(r => r.toString()).join('') : '';
    }""", name).split())


def pending_text(page):
    return painted(page, "cq-pending")


def mark_point(page, name, index=0):
    """A point inside a painted range, for a real mouse press. A highlight is not an
    element, so there is nothing for a locator to click."""
    box = page.evaluate("""([name, index]) => {
        const r = [...CSS.highlights.get(name)][index].getClientRects()[0];
        return {x: r.left + r.width / 2, y: r.top + r.height / 2};
    }""", [name, index])
    return box["x"], box["y"]


def composer_quote(page):
    """What the composer says about its own passage, and whether the reader can see it.
    The node stays in the accessibility tree either way — a painted mark has no exposure,
    so it is the box's aria description — which is why this asks the class, not the text."""
    return page.evaluate("""() => {
        const q = document.getElementById('cq-composer-quote');
        return {text: q.textContent, shown: !q.classList.contains('cq-unseen')};
    }""")


def mark_shows_beside_composer(page):
    """Whether any of the composer's own mark is on screen and not behind the box. The mark
    is the only thing naming the passage the box is about, so a box covering all of it is a
    box about nothing — which no state may reach."""
    return page.evaluate("""() => {
        const box = document.querySelector('.cq-composer').getBoundingClientRect();
        const rects = [...(CSS.highlights.get('cq-pending') ?? [])]
            .flatMap(r => [...r.getClientRects()])
            .concat([...document.querySelectorAll('.cq-mark-el.cq-pending')]
                .map(e => e.getBoundingClientRect()));
        const onScreen = (r) => r.right > 0 && r.left < innerWidth
                             && r.bottom > 48 && r.top < innerHeight;
        const behind = (r) => r.left >= box.left && r.right <= box.right
                           && r.top >= box.top && r.bottom <= box.bottom;
        return rects.some(r => onScreen(r) && !behind(r));
    }""")


def test_composer_marks_the_passage_instead_of_quoting_it(browser, serve):
    """The passage stays visible while its comment is written. Focus moves into the
    composer the moment it opens, which drops the browser's own selection, so the
    runtime paints the anchor itself, and repaints it after every pass that redraws
    the posted threads' marks around it — otherwise a comment arriving mid-sentence
    would leave the reader's passage stranded across stale text nodes. It comes down
    with the box, and the whole time it never touches the document.

    And because the mark says which passage the box is on, the box doesn't say it too:
    the quote inside it stays out of sight while the page is marking the passage."""
    url = serve(INLINE_PAGE)
    page, errors = open_page(browser, url)

    page.locator("#p").click(click_count=3)  # a real selection, spanning the inline tags
    page.locator(".cq-fab").click()
    page.wait_for_function("() => document.querySelector('.cq-composer').style.display === 'block'")

    passage = " ".join(page.locator("#p").inner_text().split())
    quote = composer_quote(page)
    assert pending_text(page) == passage, (
        f"the page marks {pending_text(page)!r}, but the composer is anchored to {quote['text']!r}"
    )
    assert not quote["shown"], (
        f"the passage is marked on the page and the composer prints it as well: {quote['text']!r}"
    )
    # Out of sight, not gone: it is what the box's description resolves to, and a screen
    # reader hears nothing from a painted mark.
    assert quote["text"] == f"“{passage}”", (
        f"the composer's description of its passage says {quote['text']!r}"
    )
    assert page.evaluate(
        "() => document.querySelector('.cq-composer textarea').getAttribute('aria-describedby')"
    ) == "cq-composer-quote", "nothing announces what the box is anchored to"
    # Carrying that description costs the node an id, which is what makes it the one piece
    # of injected chrome that could answer "which section of the document is this in" with
    # itself. The reading position rides on that answer, so a reload would scroll to the
    # comment box instead of to the page.
    assert page.evaluate(
        "() => document.getElementById('cq-composer-quote')"
        ".closest('[id]:not(.cq-ui)')?.id ?? null"
    ) is None, "the composer's own quote offers itself as a landmark in the document"

    # A comment landing from elsewhere re-runs the anchor pass, which splits the text
    # nodes the painted range is pinned to. The reader is mid-sentence; their passage
    # can neither blink out nor come back covering the wrong words.
    page.request.post(
        url.rsplit("/versions/", 1)[0] + "/api/event",
        data={"kind": "comment", "version": 1, "text": "arriving mid-sentence",
              "anchor": {"section": "p", "quote": "bold text"}},
    )
    page.wait_for_function("() => (CSS.highlights.get('cq-mark')?.size ?? 0) > 0")
    assert pending_text(page) == passage, "a poll landing while the composer is open disturbed the passage"

    page.get_by_role("button", name="Cancel").click()
    assert pending_text(page) == "", "the highlight outlived its composer"

    # A passage with the runtime's own chrome inside it paints around the chrome, the way
    # the search reads around it — one range per segment, not one spanning the lot.
    # Across both options, so a Choose button falls in the middle of the passage rather
    # than after it — where a single range spanning the whole thing would swallow it.
    chrome = page.locator("#opts .cq-ui").first.text_content().strip()
    assert chrome, "this assertion needs the widget to have rendered chrome inside it"
    page.evaluate("""() => {
        const r = document.createRange();
        r.selectNodeContents(document.querySelector('#opts'));
        const s = getSelection(); s.removeAllRanges(); s.addRange(r);
        document.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
    }""")
    page.locator(".cq-fab").click()
    page.wait_for_function("() => CSS.highlights.get('cq-pending')")
    assert chrome not in pending_text(page), (
        f"the highlight painted the widget's own {chrome!r} control along with the passage"
    )
    page.get_by_role("button", name="Cancel").click()

    # A diagram has no text to quote, so its anchor is the element and its mark is an
    # outline. That one the anchor pass really does take down, so it has to be redrawn.
    page.locator("#fig svg").click()
    page.locator(".cq-fab").click()
    page.locator("#fig.cq-mark-el.cq-pending").wait_for()
    assert not composer_quote(page)["shown"], (
        "the outline is on the figure and the composer names its section as well"
    )
    page.request.post(
        url.rsplit("/versions/", 1)[0] + "/api/event",
        data={"kind": "comment", "version": 1, "text": "and another"},
    )
    page.wait_for_function("() => document.querySelectorAll('.cq-thread').length === 2")
    assert page.locator("#fig.cq-mark-el.cq-pending").count() == 1, (
        "a poll landing while the composer is open dropped the outline"
    )

    # Both classes have to go, asserted apart: leaving .cq-mark-el behind repaints the
    # figure in the posted amber, pointer cursor and all, over no thread to open.
    page.get_by_role("button", name="Cancel").click()
    assert page.locator("#fig.cq-pending").count() == 0, "the outline outlived its composer"
    assert page.locator("#fig.cq-mark-el").count() == 0, (
        "the figure kept a thread's outline over no thread"
    )

    # A drag across the caption ends with the click's target inside the figure, but the
    # selection is what the reader picked: the one decider ranks the quote above the
    # element anchor, so the composer carries the caption's words rather than § fig.
    cap = page.locator("#fig figcaption").bounding_box()
    page.mouse.move(cap["x"] + 2, cap["y"] + cap["height"] / 2)
    page.mouse.down()
    page.mouse.move(cap["x"] + cap["width"] - 2, cap["y"] + cap["height"] / 2, steps=8)
    page.mouse.up()
    page.locator(".cq-fab").click()
    page.wait_for_function("() => CSS.highlights.get('cq-pending')")
    assert "specimen" in pending_text(page), (
        "the click's visual find outranked the selection the drag made"
    )
    assert page.locator("#fig.cq-pending").count() == 0, (
        "the figure got the element outline over a live selection"
    )
    page.get_by_role("button", name="Cancel").click()
    assert errors == []
    page.close()


NOTED_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>noted</title>
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<h1 id="t">Noted</h1>
<p id="p1">The first passage under discussion, with words
enough for two separate remarks to land in it.</p>
<p id="p2">A short second passage.</p>
<figure id="fig"><svg viewBox="0 0 120 40" width="120" height="40" role="img"
aria-label="specimen"><rect x="2" y="2" width="116" height="36" fill="none"
stroke="currentColor"></rect></svg><figcaption>A figure, for element anchors.</figcaption></figure>
</main>
</body>
</html>
"""


def test_a_commented_block_says_so_to_a_screen_reader(browser, serve):
    """A mark is painted, not wrapped, so it builds no accessibility node and a passage
    carrying a comment reads exactly like one that doesn't. No ARIA relation reaches a
    block that isn't focusable, so the pass says it in the one thing every screen reader
    announces — text — counting up per block, riding in on a sent comment's round trip,
    and leaving with its thread. Having put words on the page, it then has to keep them
    out of the document's own: out of a selection, out of the next quote, and out of the
    mutations a screen reader rebuilds its buffer on."""
    url = serve(NOTED_PAGE)
    d = serve.page_dir

    def comment(anchor, text):
        return interact.append_event(
            d, {"kind": "comment", "author": "user", "version": 1, "text": text,
                "anchor": anchor})["id"]

    comment({"quote": "first passage"}, "Sharpen this.")
    comment({"quote": "two separate remarks"}, "Second thought.")
    comment({"section": "fig"}, "The figure too.")
    page, errors = open_page(browser, url)
    page.wait_for_function("() => (CSS.highlights.get('cq-mark')?.size ?? 0) > 0")
    # Two threads on one block count up, and leave one line rather than two.
    assert "2 comments" in page.locator("#p1").aria_snapshot(), (
        "a screen reader reading the block hears nothing about the comments on it"
    )
    assert page.locator("#p1 .cq-mark-note").count() == 1, "one block, one line"
    # Hidden means hidden from the eye, not the tree: a line that paints is the runtime
    # writing visible prose into the author's paragraph.
    assert page.locator("#p1 .cq-mark-note").evaluate(
        "el => { const r = el.getBoundingClientRect(); return r.width <= 1 && r.height <= 1; }"
    ), "the hidden line is painting on screen"
    # An element anchor has no text to paint, and the element it names holds the line.
    assert "1 comment" in page.locator("#fig").aria_snapshot()

    # A pass that finds nothing to change must change nothing: a screen reader rebuilds
    # its buffer on every mutation, and this pass runs on every poll. A comment on no
    # passage at all is what proves a pass ran without touching the block's count.
    page.evaluate("""() => {
        window.__churn = 0;
        new MutationObserver(rs => (window.__churn += rs.length))
            .observe(document.getElementById('p1'),
                     {childList: true, characterData: true, subtree: true});
    }""")
    comment({}, "On the page as a whole.")
    page.wait_for_function("() => document.querySelectorAll('.cq-thread').length === 4")
    assert page.evaluate("() => window.__churn") == 0, (
        "a poll that changed nothing still rewrote the block, so a screen reader re-reads it"
    )

    # The line belongs to the runtime, not the document: a reviewer dragging across it
    # neither copies it nor quotes it.
    page.locator("#p1").click(click_count=3)
    assert "comment" not in page.evaluate("() => getSelection().toString()"), (
        "the hidden line came along in the reviewer's own selection"
    )
    page.locator(".cq-fab").click()
    assert "comment" not in composer_quote(page)["text"], (
        "the hidden line came along in the quote the comment would store"
    )
    page.get_by_role("button", name="Cancel").click()

    # The gesture's own comment reaches the line once the send's round trip lands.
    box = page.locator("#p2").bounding_box()
    page.mouse.move(box["x"] + 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] - 2, box["y"] + box["height"] / 2, steps=8)
    page.mouse.up()
    page.locator(".cq-fab").click()
    page.wait_for_function("() => document.querySelector('.cq-composer').style.display === 'block'")
    page.locator(".cq-composer textarea").fill("Too short.")
    page.get_by_role("button", name="Comment", exact=True).click()
    expect(page.locator("#p2 .cq-mark-note")).to_have_count(1)
    c4 = [e for e in interact.read_events(d) if e.get("kind") == "comment"][-1]["id"]

    # A resolved thread takes its line with it: the pass owns what it wrote.
    interact.append_event(d, {"kind": "resolve", "author": "user", "parent": c4})
    expect(page.locator("#p2 .cq-mark-note")).to_have_count(0)
    assert "2 comments" in page.locator("#p1").aria_snapshot()

    # A passage crossing two blocks says so in both: a reader landing on either block
    # hears about the comment, the way the paint reaches both.
    comment({"quote": "to land in it. A short second"}, "Crosses the boundary.")
    expect(page.locator("#p2 .cq-mark-note")).to_have_count(1)
    assert "3 comments" in page.locator("#p1").aria_snapshot()
    assert "1 comment" in page.locator("#p2").aria_snapshot()
    assert errors == []
    page.close()


def test_the_composer_never_stands_on_its_own_mark(browser, serve):
    """The mark is the only thing naming the passage the box is about, so a box covering
    all of it is a box about nothing. That is not hypothetical: a restored draft reappears
    just under the banner, and the reading position puts the passage it was made on back
    where it was — which, for a passage that was near the top of a narrow column, is
    exactly there. The box has to move off it.

    Not off every pixel of it. The box has always covered the tail of a long passage and
    that reads fine; what may not happen is every rect hidden at once."""
    filler = "\n".join(f"<p id='f{i}'>Filler {i}. " + "Words. " * 20 + "</p>" for i in range(30))
    url = serve(SETTLED_PAGE.replace("</main>", filler + "\n</main>"))
    page, errors = open_page(browser, url)

    page.locator(".cq-settled").click()  # open the settled group, as a reader would
    page.wait_for_selector("#opt-strict:visible")
    # A card in the middle column, scrolled just under the banner: narrower than the 320px
    # box and centred on it, which is the geometry the box can swallow whole.
    page.evaluate("""() => {
        const r = document.querySelector('#opt-strict').getBoundingClientRect();
        document.body.scrollBy({top: r.top - 60, behavior: 'instant'});
    }""")
    page.locator("#opt-strict").click(click_count=3)
    page.locator(".cq-fab").click()
    page.locator(".cq-composer textarea").fill("what did the trial actually show?")
    assert mark_shows_beside_composer(page), "the box covered the passage it just opened on"

    page.reload()
    page.wait_for_function(
        "() => document.querySelector('.cq-composer').style.display === 'block'"
    )
    page.wait_for_function("() => (CSS.highlights.get('cq-pending')?.size ?? 0) > 0")
    assert mark_shows_beside_composer(page), (
        "the restored box came back on top of its own mark, and with the mark hidden "
        "nothing on screen says what the draft is about"
    )
    assert not composer_quote(page)["shown"], (
        "the mark is showing and the composer prints the passage as well"
    )
    assert errors == []
    page.close()


def test_a_draft_that_outlives_its_passage_still_says_what_it_was_about(browser, serve):
    """A draft survives the version it was written against — the reviewer opens the new
    one with unsent text — and the passage it was about may not have. The mark is what
    normally says which passage the box is on, so where there is no passage left to mark
    the quote is the only record there is, and it comes back: dashed and muted, the same
    detached treatment the panel gives a thread this version dropped."""
    url = serve(INLINE_PAGE)
    page, errors = open_page(browser, url)

    page.locator("#p").click(click_count=3)
    page.locator(".cq-fab").click()
    page.locator(".cq-composer textarea").fill("half-written when the version turned over")
    passage = " ".join(page.locator("#p").inner_text().split())
    assert not composer_quote(page)["shown"], "the passage is right here, and marked"

    # Claude ships a version that rewrites the passage out. The page holds still — a
    # draft is mid-composition — and offers the new version as a chip, which the
    # reviewer takes.
    d = serve.page_dir
    (d / "versions" / "v2.html").write_text(
        INLINE_PAGE.replace(
            "A paragraph carrying <strong>bold text</strong> and <em>emphasis</em> inside it,\n"
            "so that a selection across the middle of it lands in more than one text node.",
            "Rewritten, with nothing left of the sentence the draft was about.",
        )
    )
    interact.append_event(d, {"kind": "note", "author": "claude", "version": 2, "text": "two"})
    expect(page.locator(".cq-latest-chip")).to_be_visible()
    page.get_by_role("button", name="New version available", exact=False).click()
    page.wait_for_url("**/v2.html", timeout=15000)
    page.wait_for_function(
        "() => document.querySelector('.cq-composer').style.display === 'block'"
    )

    assert page.locator(".cq-composer textarea").input_value() == (
        "half-written when the version turned over"
    ), "the draft didn't survive the version it was written against"
    assert pending_text(page) == "", "v2 rewrote the passage and the page marked it anyway"
    quote = composer_quote(page)
    assert quote["shown"], (
        "nothing on screen says what the draft is about — no mark, and no quote either"
    )
    assert quote["text"] == f"“{passage}”", f"the quote says {quote['text']!r}"
    assert page.locator(".cq-composer .cq-quote.detached").count() == 1, (
        "the stranded quote reads as one that still points somewhere"
    )

    # A stranded quote is the last copy of that passage anywhere on the page, so it is text
    # a reviewer selects to keep. The anchor pass reruns on every arriving comment, and a
    # rewritten node takes the selection with it.
    page.evaluate("""() => {
        const q = document.getElementById('cq-composer-quote');
        const r = document.createRange();
        r.setStart(q.firstChild, 1);
        r.setEnd(q.firstChild, 20);
        const s = getSelection(); s.removeAllRanges(); s.addRange(r);
    }""")
    held = page.evaluate("() => getSelection().toString()")
    assert len(held) == 19, f"this assertion needs a selection to survive; it made {held!r}"
    page.request.post(
        url.rsplit("/versions/", 1)[0] + "/api/event",
        data={"kind": "comment", "version": 2, "text": "arriving from another tab"},
    )
    page.wait_for_function("() => document.querySelectorAll('.cq-thread').length === 1")
    assert page.evaluate("() => getSelection().toString()") == held, (
        "the anchor pass rewrote the stranded quote and took the reader's selection with it"
    )
    assert errors == []
    page.close()


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda p: p.stem)
def test_every_passage_in_a_real_page_can_be_quoted(browser, serve, example):
    """Anchoring has to work on the pages people actually write, not on a fixture built
    to suit it. Every failure here has been a place where what the reader selects and
    what the search reads come apart — an uppercased header, a widget's own chrome, the
    stylesheet a rendered diagram carries — and a hand-built page has none of them. So
    this drags across every pair of adjacent blocks in every shipped example, which is
    the shape a real selection takes, and asks for the highlight the composer promises."""
    page, errors = open_page(browser, serve(example.read_text()))
    result = page.evaluate("""async () => {
        const tick = () => new Promise(r => setTimeout(r, 0));
        const composer = document.querySelector('.cq-composer');
        const fab = document.querySelector('.cq-fab');
        // A reader reaches everything eventually — opens the details, clicks through to
        // the other tab — so everything is in scope, not just what the page opens on.
        document.querySelectorAll('details').forEach(d => (d.open = true));
        document.querySelectorAll('[hidden]').forEach(e => e.removeAttribute('hidden'));
        const blocks = [...document.querySelectorAll('p,li,h1,h2,h3,td,th,blockquote,'
            + 'figcaption,summary,cq-option,cq-variant,cq-milestone,cq-metric')]
          .filter(b => !b.closest('.cq-ui') && b.checkVisibility()
                    && b.textContent.trim().length > 12);
        const missed = [], skipped = [], astray = [];
        for (let i = 0; i < blocks.length; i++) {
            // Each block alone, then reaching into the next one — a drag rarely stops
            // tidily on a boundary, and spanning two blocks is where the joins show.
            for (const end of [blocks[i], blocks[i + 1]].filter(Boolean)) {
                const range = document.createRange();
                range.setStart(blocks[i], 0);
                range.setEnd(end, end.childNodes.length);
                const sel = getSelection();
                sel.removeAllRanges();
                sel.addRange(range);
                document.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
                await tick();
                // Counted, not shrugged off: a selection the button declines to offer is
                // a passage silently outside this sweep, and the sweep is the coverage.
                if (fab.style.display !== 'block') {
                    skipped.push(range.toString().replace(/\\s+/g, ' ').trim().slice(0, 70));
                    continue;
                }
                fab.click();
                await tick();
                const painted = CSS.highlights.get('cq-pending');
                // The captured quote, read off the node whether or not the reader can
                // see it: the composer shows it only where the page has no mark to give,
                // which is the very case this loop is counting.
                const quoted = document.getElementById('cq-composer-quote').textContent;
                if (!painted || ![...painted].map(r => r.toString()).join('').trim())
                    missed.push(quoted.slice(0, 70));
                // Inside what was selected, not merely somewhere: a matcher that finds
                // the right words in the wrong place paints, and paints a lie.
                else if ([...painted].some(p =>
                        p.compareBoundaryPoints(Range.START_TO_START, range) < 0 ||
                        p.compareBoundaryPoints(Range.END_TO_END, range) > 0))
                    astray.push(quoted.slice(0, 70));
                composer.style.display = 'none';
                sel.removeAllRanges();
            }
        }
        return {missed, skipped, astray};
    }""")
    assert result["missed"] == [], (
        f"{len(result['missed'])} passages in {example.stem} quote text the page "
        f"can't find: {result['missed']}"
    )
    assert result["skipped"] == [], (
        f"{len(result['skipped'])} passages in {example.stem} raised no Comment button, "
        f"so this sweep never tested them: {result['skipped']}"
    )
    assert result["astray"] == [], (
        f"{len(result['astray'])} passages in {example.stem} painted outside what was "
        f"selected: {result['astray']}"
    )
    assert errors == []
    page.close()


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda p: p.stem)
def test_every_x_says_attribute_reaches_the_page_as_text(browser, serve, example):
    """The other half of what interact.UNREACHABLE_WORDS asks of a page — that half is
    in the gate, because a page-local widget is where a heading goes out of reach and the
    gate is what a reviewer's page passes through; test_example_renders drives it over
    these same examples.

    What the gate can't ask is whether the words arrived at all: it works from the
    rendered page, where an attribute that reaches nobody looks exactly like an attribute
    with nothing to say. The registry knows the difference, so this reads x-says back and
    asks each declaration to be somewhere in its element's text — a metric with no number
    is a worse failure than one whose number can't be selected, and the only pass that
    would notice is this one."""
    page, errors = open_page(browser, serve(example.read_text()))
    unsaid = page.evaluate("""async () => {
        const out = [];
        const reg = await (await fetch('/registry.json')).json();
        for (const [tag, entry] of Object.entries(reg))
            for (const attr of Object.keys(entry['x-says'] ?? {}))
                for (const el of document.querySelectorAll(tag)) {
                    const value = el.getAttribute(attr);
                    if (value !== null && !el.textContent.includes(value))
                        out.push(`<${tag}${el.id ? ' id=' + el.id : ''}> never says `
                                 + `${attr}="${value}"`);
                }
        return out;
    }""")
    assert unsaid == [], (
        f"{example.stem} declares attributes as x-says that never reach the page as "
        f"text: {unsaid}"
    )
    assert errors == []
    page.close()


def test_a_widgets_attribute_takes_a_comment_like_any_other_passage(browser, serve):
    """The gesture itself, on the words a widget renders from an attribute: drag across
    a column's heading and the same button, quote, and mark come up as for a paragraph,
    and the comment is still anchored a version later. A real drag, because the whole
    class of bug here is text that looks selectable and isn't — a synthetic Range would
    select what no pointer can.

    Then the other half of the pair, which the same spans decide: the version diff reads
    a block's *authored* text, and the base version it compares against is parsed
    unupgraded, where these spans don't exist. Drop their data-cq-gen and every widget
    holding a said attribute lights up as changed on every revision — a failure that
    looks like a busy page rather than like a bug."""
    page, errors = open_page(browser, serve(SAID_PAGE))

    heading = page.locator('cq-column#col-now > [data-cq-said="label"]')
    box = heading.bounding_box()
    page.mouse.move(box["x"] + 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] - 2, box["y"] + box["height"] / 2, steps=8)
    page.mouse.up()

    # The theme uppercases a column heading, so the selection reads back as the reader
    # sees it and the quote as the document holds it — the asymmetry that makes
    # selectionAnchor read the text nodes rather than the selection's own toString().
    assert page.evaluate("() => getSelection().toString()").strip() == "IN FLIGHT", (
        "a drag across the heading selected nothing — it is painted, not said"
    )
    page.locator(".cq-fab").click()
    page.wait_for_function("() => document.querySelector('.cq-composer').style.display === 'block'")
    quoted = composer_quote(page)["text"]
    assert quoted.strip("“”") == "In flight"
    page.locator(".cq-composer textarea").fill("this column's name is wrong")
    page.get_by_role("button", name="Comment", exact=True).click()
    page.wait_for_function("() => (CSS.highlights.get('cq-mark')?.size ?? 0) > 0")

    thread = page.locator(".cq-thread .cq-quote").first
    assert thread.text_content().strip().strip("“”") == "In flight"

    # A second version reworking one card's prose and nothing else. The page follows it,
    # and the anchor is on a word only the runtime puts there, so it has to be found
    # again in the version the reviewer now has.
    d = serve.page_dir
    (d / "versions" / "v2.html").write_text(
        SAID_PAGE.replace("Waiting on the importer.", "Unblocked; starting Thursday.")
    )
    interact.append_event(d, {"kind": "note", "author": "claude", "version": 2, "text": "two"})
    page.wait_for_url("**/v2.html", timeout=10_000)
    page.wait_for_function("() => (CSS.highlights.get('cq-mark')?.size ?? 0) > 0")
    assert page.locator(".cq-thread .cq-quote.detached").count() == 0, (
        "the comment came loose from the heading when the version turned over"
    )

    page.locator(".cq-banner button", has_text="Δ").click()
    page.wait_for_function("() => document.querySelectorAll('.cq-ins-block').length > 0")
    assert page.evaluate(
        "() => [...document.querySelectorAll('.cq-ins-block')].map(e => e.id)"
    ) == ["c-backfill"], "the diff read the runtime's own spans as text the base lacked"
    assert errors == []
    page.close()


def test_a_quote_finds_its_passage_whatever_its_whitespace(browser, serve):
    """The same passage gets written down several ways. The page holds it with the
    author's line wraps; a selection renders it with a break where two blocks abut and
    none where one wrapped; older versions of this runtime stored a third form again.
    All of them name the same words, so all of them have to find them — otherwise a
    comment made last month hangs off a passage the page insists isn't there."""
    url = serve(INLINE_PAGE)
    page, errors = open_page(browser, url)
    passage = "bold text and emphasis inside it"
    forms = {
        "as the page holds it": passage,
        "wrapped where a source line ended": passage.replace(" and ", "\nand "),
        "broken where a block ended": passage.replace(" and ", "\n\nand\n"),
        "spaced out by an editor": passage.replace(" ", "   "),
        # Reaching across the boundary between two blocks, which the reader sees as a
        # line break, the source writes as a newline, and a rendering may write as neither.
        "spanning two blocks": "more than one text node. A neighbouring block",
    }
    for name, quote in forms.items():
        page.request.post(
            url.rsplit("/versions/", 1)[0] + "/api/event",
            data={"kind": "comment", "version": 1, "text": name,
                  "anchor": {"section": None, "quote": quote}},
        )
    page.get_by_role("button", name="Comments", exact=False).click()
    page.wait_for_function(
        f"() => document.querySelectorAll('.cq-thread').length === {len(forms)}"
    )
    stranded = page.locator(".cq-panel .cq-quote.detached").all_text_contents()
    assert stranded == [], f"quotes naming a passage that is right there: {stranded}"

    # The elasticity runs one way only. A quote is free to have gaps the page lacks; a
    # page's gaps are word boundaries, and a quote that runs across one is naming
    # something the page doesn't say — "never" must not find the tail of "on every".
    page.request.post(
        url.rsplit("/versions/", 1)[0] + "/api/event",
        data={"kind": "comment", "version": 1, "text": "words the page never runs together",
              "anchor": {"section": None, "quote": "boldtext"}},
    )
    page.wait_for_function(
        f"() => document.querySelectorAll('.cq-thread').length === {len(forms) + 1}"
    )
    assert page.locator(".cq-panel .cq-quote.detached").count() == 1, (
        "a quote gluing two of the page's words together still found a passage"
    )

    # Nor may a gap close up onto a compound the page writes as one word. "set up" and
    # "setup" are different words, and the page has both — the anchor has to land on the
    # one that was dragged, and it is stored, so landing wrong is permanent.
    landed = page.evaluate("""async () => {
        const p = document.querySelector('#compound');
        const at = p.firstChild.data.indexOf('set up');
        const r = document.createRange();
        r.setStart(p.firstChild, at); r.setEnd(p.firstChild, at + 6);
        const s = getSelection(); s.removeAllRanges(); s.addRange(r);
        document.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
        await new Promise(x => setTimeout(x, 30));
        document.querySelector('.cq-fab').click();
        await new Promise(x => setTimeout(x, 30));
        const painted = [...(CSS.highlights.get('cq-pending') ?? [])][0];
        return painted && painted.compareBoundaryPoints(Range.START_TO_START, r) === 0;
    }""")
    assert landed, "'set up' anchored onto 'setup', an earlier and different word"
    assert errors == []
    page.close()


def test_the_captured_quote_is_prose_a_file_can_hold(browser, serve):
    """A quote is read back as prose — seeded into the suggestion box, printed in the
    panel, emitted into a Markdown blockquote by `export` — and written to a UTF-8 file
    on the way. Source text is neither: it carries the author's line wraps, which break
    a blockquote open, and cutting it to length by UTF-16 unit can halve a character,
    which no UTF-8 file can hold. The server refuses that write and the reader is told
    it is offline, with no way to ever send the comment."""
    url = serve(INLINE_PAGE)
    page, errors = open_page(browser, url)

    def compose_on(block):
        page.locator(block).click(click_count=3)
        page.locator(".cq-fab").click()
        page.wait_for_function(
            "() => document.querySelector('.cq-composer').style.display === 'block'"
        )

    # Read off the composer's description of its own anchor, which is the captured quote
    # verbatim — the string that goes on to the panel, the file, and the export.
    compose_on("#p")  # authored across two source lines
    wrapped = composer_quote(page)["text"]
    assert "\n" not in wrapped, f"the quote carries the source's line wrap: {wrapped!r}"
    page.get_by_role("button", name="Cancel").click()

    # Measured in the page: a lone surrogate does not survive the trip out to the test
    # runner, which replaces it, so asking out here would always come back clean.
    # Iterating by code point, a character cut in half is left as a single unit in the
    # surrogate range; an intact one comes through as the pair it is.
    compose_on("#cap")
    assert not page.evaluate("""() => [...document.getElementById('cq-composer-quote').textContent]
        .some(c => c.length === 1 && c.charCodeAt(0) >= 0xd800 && c.charCodeAt(0) <= 0xdfff)"""), (
        "the 400-character cap split a character in half"
    )

    # And the round trip that proves it: the server has to accept the quote and write it
    # to a UTF-8 file. A half character fails there, reported to the reader as an offline
    # server, and no retry can ever succeed.
    page.locator(".cq-composer textarea").fill("a comment on the capped passage")
    page.locator(".cq-composer").get_by_role("button", name="Comment").click()
    page.wait_for_function("""() => document.querySelectorAll('.cq-thread').length === 1
        || document.querySelector('.cq-toast').classList.contains('show')""")
    assert page.locator(".cq-thread").count() == 1, (
        f"the comment never posted — the page says {page.locator('.cq-toast').text_content()!r}"
    )
    assert errors == []
    page.close()


def test_an_open_composer_does_not_eat_the_next_click(browser, serve):
    """Clicks keep working while a composer is open. The composer comes down on the
    document's mousedown, and anything that rewrites the page's marks there swaps out
    the node under the pointer between press and release — which is a click the
    browser never dispatches at all. So a thread's highlight stops opening its thread,
    and a link inside a highlighted passage stops navigating. Real button presses,
    because a synthetic click event sails straight past the gap it lives in."""
    url = serve(INLINE_PAGE)
    page, errors = open_page(browser, url)
    page.request.post(
        url.rsplit("/versions/", 1)[0] + "/api/event",
        data={"kind": "comment", "version": 1, "text": "on the passage",
              "anchor": {"section": "p", "quote": "bold text"}},
    )
    page.wait_for_function("() => (CSS.highlights.get('cq-mark')?.size ?? 0) > 0")

    # Open a composer on other text and type nothing, so the next mousedown outside it
    # is the one that takes it down.
    page.locator("#q").click(click_count=3)
    page.locator(".cq-fab").click()
    page.wait_for_function("() => document.querySelector('.cq-composer').style.display === 'block'")

    page.mouse.click(*mark_point(page, "cq-mark"))
    page.wait_for_function("() => document.querySelector('.cq-panel').classList.contains('open')")

    # And the composer's own mark belongs to no thread, so it opens nothing. Its first
    # range runs up to the posted one, so this lands on the draft and nothing else.
    page.get_by_role("button", name="Close comments").click()
    page.locator("#p").click(click_count=3)
    page.locator(".cq-fab").click()
    page.wait_for_function("() => document.querySelector('.cq-composer').style.display === 'block'")
    page.mouse.click(*mark_point(page, "cq-pending"))
    assert not page.locator(".cq-panel").evaluate("el => el.classList.contains('open')"), (
        "clicking the composer's own highlight opened the panel, but it belongs to no thread"
    )
    assert errors == []
    page.close()


def test_a_click_on_a_mark_decides_once(browser, serve):
    """Opening the panel reflows the document, so anything that hit-tests the page after
    the panel opens is testing geometry that has already moved. When two handlers each
    asked where the pointer was, the second missed the mark the first had just opened and
    raised the comment button on top of it — and the element anchor that left behind reads
    as composition in progress, which is what stops a page following new versions. The
    panel starts shut here because a panel already open is the case with no reflow."""
    url = serve(INLINE_PAGE)
    page, errors = open_page(browser, url)
    # A quote inside the figure's caption: a painted range, so opening the panel reflows the
    # text out from under the pointer. An element anchor wouldn't show it — a figure still
    # covers the same point after the column narrows.
    page.request.post(
        url.rsplit("/versions/", 1)[0] + "/api/event",
        data={"kind": "comment", "version": 1, "text": "on the caption",
              "anchor": {"section": "fig", "quote": "A specimen, for element anchors."}},
    )
    page.wait_for_function("() => (CSS.highlights.get('cq-mark')?.size ?? 0) > 0")
    if page.locator(".cq-panel.open").count():
        page.get_by_role("button", name="Close comments").click()
        page.wait_for_function("() => !document.querySelector('.cq-panel').classList.contains('open')")

    page.locator("#fig").scroll_into_view_if_needed()
    spot = page.evaluate("""() => { const r = [...CSS.highlights.get('cq-mark')][0].getClientRects()[0];
                                    return {x: r.left + r.width / 2, y: r.top + r.height / 2}; }""")
    page.mouse.click(spot["x"], spot["y"])
    page.wait_for_function("() => document.querySelector('.cq-panel').classList.contains('open')")
    assert not page.locator(".cq-fab").is_visible(), (
        "the click opened the thread and then offered to comment on it as well"
    )

    # The harm that outlives the stray button: a page mid-composition stays put.
    d = serve.page_dir
    (d / "versions" / "v2.html").write_text(INLINE_PAGE.replace("<h1 id=\"t\">Inline</h1>",
                                                                 "<h1 id=\"t\">Inline II</h1>"))
    interact.append_event(d, {"kind": "note", "author": "claude", "version": 2, "text": "two"})
    page.wait_for_url("**/v2.html", timeout=15000)
    assert errors == []
    page.close()


def test_two_comments_on_one_element_both_stay_anchored(browser, serve):
    """A figure can carry more than one thread. When the page's record of what it drew was
    keyed by the mark, the second comment overwrote the first, and the panel told the
    reader the first one's passage wasn't in this version — while it sat outlined on
    screen for the second."""
    url = serve(INLINE_PAGE)
    page, errors = open_page(browser, url)
    for text in ("first on the figure", "second on the figure"):
        page.request.post(
            url.rsplit("/versions/", 1)[0] + "/api/event",
            data={"kind": "comment", "version": 1, "text": text, "anchor": {"section": "fig"}},
        )
    page.get_by_role("button", name="Comments", exact=False).click()
    page.wait_for_function("() => document.querySelectorAll('.cq-thread').length === 2")
    stranded = page.locator(".cq-panel .cq-quote.detached").all_text_contents()
    assert stranded == [], f"outlined on screen, reported missing: {stranded}"
    assert errors == []
    page.close()


def test_the_pointer_stops_claiming_a_mark_it_scrolled_past(browser, serve):
    """The hover is a function of where the pointer is and where the text is, and scrolling
    moves the second without touching the first. A wrapped <mark> got this from :hover; a
    painted range has to be asked again, so everything that moves the page asks."""
    url = serve(LONG_PAGE)
    page, errors = open_page(browser, url)
    page.request.post(
        url.rsplit("/versions/", 1)[0] + "/api/event",
        data={"kind": "comment", "version": 1, "text": "up top",
              "anchor": {"section": "p0", "quote": "Paragraph 0."}},
    )
    page.wait_for_function("() => (CSS.highlights.get('cq-mark')?.size ?? 0) > 0")
    spot = page.evaluate("""() => { const r = [...CSS.highlights.get('cq-mark')][0].getClientRects()[0];
                                    return {x: r.left + r.width / 2, y: r.top + r.height / 2}; }""")
    page.mouse.move(spot["x"], spot["y"])
    page.wait_for_function("() => document.body.classList.contains('cq-over-mark')")
    page.evaluate("() => document.body.scrollBy({top: 900, behavior: 'instant'})")
    page.wait_for_function(
        "() => !document.body.classList.contains('cq-over-mark')"
        " && (CSS.highlights.get('cq-mark-hover')?.size ?? 0) === 0"
    )
    assert errors == []
    page.close()


# A page that says the same thing twice *within one section*, which is the only case a
# quote alone cannot place — scoping to a section already separates copies that live under
# different ids. A unified diff is the case that matters and the reason the section can't
# help: it holds the changed line on both sides, under one id, so the two occurrences are a
# bug and its fix, and landing on the wrong one inverts what the comment means.
TWICE_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>twice</title>
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<h1 id="t">Twice</h1>
<section id="repeat">
<p>Ahead of the repeat, so the copies have different neighbours before them.</p>
<p>A first copy follows. The version stamp never lands. And a first tail after it.</p>
<p>Something else entirely, so the two copies do not touch each other.</p>
<p>A second copy follows. The version stamp never lands. And a second tail after it.</p>
</section>
<cq-diff id="patch" file="cache.py">@@ -18,7 +18,7 @@ class Bucket:
 def key(self, request):
-    return request.path
+    return request.path, request.headers.get("Accept")
 def store(self, request):</cq-diff>
</main>
</body>
</html>
"""


def test_a_repeated_passage_anchors_where_it_was_picked(browser, serve):
    """A quote names text, not a place. Where one section says the same thing twice, the
    words on either side are what tell the copies apart — so an anchor carries them, and
    the occurrence whose neighbours match wins. Driven through the real button, because
    the context is captured from the live selection and nowhere else."""
    page, errors = open_page(browser, serve(TWICE_PAGE))
    landed = page.evaluate("""async () => {
        const paras = [...document.querySelectorAll('#repeat p')];
        const p = paras.at(-1);
        const phrase = 'The version stamp never lands.';
        const at = p.firstChild.data.indexOf(phrase);
        if (at === -1) return 'phrase missing';
        const want = document.createRange();
        want.setStart(p.firstChild, at); want.setEnd(p.firstChild, at + phrase.length);
        const sel = getSelection(); sel.removeAllRanges(); sel.addRange(want);
        document.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
        await new Promise(r => setTimeout(r, 40));
        const fab = document.querySelector('.cq-fab');
        if (fab.style.display !== 'block') return 'no button';
        fab.click();
        await new Promise(r => setTimeout(r, 40));
        const painted = [...(CSS.highlights.get('cq-pending') ?? [])][0];
        if (!painted) return 'no mark';
        return painted.compareBoundaryPoints(Range.START_TO_START, want) === 0;
    }""")
    assert landed is True, f"the second copy was picked, the mark went elsewhere ({landed})"
    assert errors == []
    page.close()


DRIFT_V1 = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>drift</title>
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<h1 id="t">Drift</h1>
<section id="drift">
<p>Cache warmup runs first. {phrase}. Retries are capped at three.</p>
<p>Queue drain runs first. {phrase}. Retries are capped at four.</p>
</section>
</main>
</body>
</html>
""".replace("{phrase}", "The version stamp never lands")
# v2 rewrites the words on both sides of the *commented* copy and leaves the other alone,
# so the untouched copy is now the better match for the context the comment stored.
DRIFT_V2 = (DRIFT_V1.replace("Cache warmup runs first.", "Cache warmup is gone now.")
                    .replace("lands. Retries are capped at three.", "lands. Backoff is capped at three."))


def test_a_revised_neighbourhood_does_not_hand_the_comment_to_another_copy(browser, serve):
    """Context tells two copies apart; it must not relocate a comment when the page moves
    on. If a later version rewrites the words beside the anchored copy, that copy confirms
    almost nothing while an untouched copy elsewhere still matches what was stored — and
    following that is worse than having stored no context at all, which would have left the
    comment where it was. So a copy has to confirm its neighbours in full to be preferred,
    and otherwise the search falls back to the order it used before context existed."""
    url = serve(DRIFT_V1)
    page, errors = open_page(browser, url)
    landed = page.evaluate("""async () => {
        const p = document.querySelectorAll('#drift p')[0];
        const phrase = 'The version stamp never lands';
        const at = p.firstChild.data.indexOf(phrase);
        const want = document.createRange();
        want.setStart(p.firstChild, at); want.setEnd(p.firstChild, at + phrase.length);
        const sel = getSelection(); sel.removeAllRanges(); sel.addRange(want);
        document.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
        await new Promise(r => setTimeout(r, 40));
        const fab = document.querySelector('.cq-fab');
        if (fab.style.display !== 'block') return 'no button';
        fab.click();
        await new Promise(r => setTimeout(r, 40));
        document.querySelector('.cq-composer textarea').value = 'is this idempotent?';
        document.querySelector('.cq-composer textarea')
            .dispatchEvent(new Event('input', {bubbles: true}));
        document.querySelector('.cq-composer button.primary').click();
        return true;
    }""")
    assert landed is True, f"couldn't post the comment ({landed})"
    page.wait_for_function("() => (CSS.highlights.get('cq-mark')?.size ?? 0) > 0")

    d = serve.page_dir
    (d / "versions" / "v2.html").write_text(DRIFT_V2)
    interact.append_event(d, {"kind": "note", "author": "claude", "version": 2, "text": "revised"})
    page.wait_for_url("**/v2.html", timeout=15000)
    page.wait_for_function("() => (CSS.highlights.get('cq-mark')?.size ?? 0) > 0")
    where = page.evaluate("""() => {
        const r = [...CSS.highlights.get('cq-mark')][0];
        return r.startContainer.parentElement.textContent.slice(0, 24);
    }""")
    assert where.startswith("Cache warmup"), (
        f"the revision moved the comment to a copy it was never made on: {where!r}"
    )
    assert errors == []
    page.close()


# A passage among padded emoji, which is the only shape that catches the seam between how a
# context is stored and how it is compared: astral characters make the stored string longer
# in code units than in the code points the capture counted, and the padding makes the
# search's window collapse to less than it read. Both are needed, and the padding is tuned
# rather than decorative — a marker plus three spaces collapses 5 units to 3, which leaves
# the pre-fix window just short of the stored length. Two spaces and it is already long
# enough; five and the window doubles and overshoots. Tied to CONTEXT = 24, and to markers
# outside the BMP: ✅ and ⚠ are one code unit each and will not do it.
# The two inputs a well-meaning edit would touch, asserted so the fixture can't quietly
# stop guarding: BMP symbols and padding outside the band both leave the pre-fix code
# passing, and neither shows up as a failure anywhere.
MARKERS = '🔴🟢🟡🔵🟣🟤🟠🟥🟩🟦🔴🟢🟡🔵🟣🟤'
PAD = "   "
assert all(ord(c) > 0xFFFF for c in MARKERS), "BMP markers will not reproduce this"
assert len(PAD) in (3, 4), "outside the band the window is long enough either way"
ASTRAL_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>astral</title>
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<h1 id="t">Astral</h1>
<section id="astral">
<p>Ordinary prose ahead of the first copy here. {phrase} and a tail.</p>
<p>A divider paragraph between the copies.</p>
<p>{run}{phrase} and a tail.</p>
</section>
</main>
</body>
</html>
""".replace("{run}", "".join(m + PAD for m in MARKERS)).replace(
    "{phrase}", "TARGET PHRASE")


def test_a_passage_among_padded_emoji_confirms_its_neighbours(browser, serve):
    """A stored context is counted in code points; the comparison counts code units; and an
    astral character is two of the second for one of the first. Ask the page for the first
    number and the window comes up short of what was written down — and short is fatal,
    because a passage confirms its neighbours in full or not at all. The anchor would fall
    back to naming the first copy on that page for good, silently. No shipped example holds
    an astral character, so only a fixture can hold this."""
    page, errors = open_page(browser, serve(ASTRAL_PAGE))
    landed = page.evaluate("""async () => {
        const skip = '.cq-ui, script, style';
        const w = document.createTreeWalker(document.getElementById('astral'),
            NodeFilter.SHOW_TEXT,
            {acceptNode: n => n.parentElement?.closest(skip)
                ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT});
        const phrase = 'TARGET PHRASE';
        const hits = [];
        for (let n = w.nextNode(); n; n = w.nextNode()) {
            let i = n.data.indexOf(phrase);
            while (i !== -1) { hits.push({node: n, at: i}); i = n.data.indexOf(phrase, i + 1); }
        }
        if (hits.length !== 2) return `fixture holds ${hits.length} copies, wanted 2`;
        const h = hits[1];   // the copy among the emoji
        const want = document.createRange();
        want.setStart(h.node, h.at); want.setEnd(h.node, h.at + phrase.length);
        const sel = getSelection(); sel.removeAllRanges(); sel.addRange(want);
        document.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
        await new Promise(r => setTimeout(r, 60));
        const fab = document.querySelector('.cq-fab');
        if (fab.style.display !== 'block') return 'no button';
        fab.click();
        await new Promise(r => setTimeout(r, 60));
        const painted = [...(CSS.highlights.get('cq-pending') ?? [])][0];
        if (!painted) return 'no mark';
        return painted.compareBoundaryPoints(Range.START_TO_START, want) === 0;
    }""")
    assert landed is True, f"the emoji copy was picked, the mark went elsewhere ({landed})"
    assert errors == []
    page.close()


# Two copies of one phrase behind an identical lead, the second closing its section. The
# words that tell them apart are the next section's, which only a capture reading past the
# section edge can store.
EDGE_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>edge</title>
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<h1 id="t">Edge</h1>
<section id="edge">
<p>First pass: when the deploy fails again in the night, the run is retried until it lands. Nothing else moves.</p>
<p>Second pass: when the deploy fails again in the night, the run is retried until it lands.</p>
</section>
<section id="tail">
<p>Rollout resumes once the queue drains completely.</p>
</section>
</main>
</body>
</html>
"""


# The same page with nothing after the section, so the closing copy ends the document —
# the one place no capture can supply a second side. What it stores there is an empty
# suffix, which says the passage had nothing after it anywhere on the page, and only one
# occurrence can be somewhere that is still true of.
TAIL_PAGE = EDGE_PAGE.replace(
    """<section id="tail">
<p>Rollout resumes once the queue drains completely.</p>
</section>
""",
    "",
)
assert TAIL_PAGE != EDGE_PAGE, "the section this removes has moved; the contrast is gone"


@pytest.mark.parametrize(
    "html", [EDGE_PAGE, TAIL_PAGE], ids=["closes-its-section", "ends-the-document"]
)
def test_a_repeated_passage_at_an_edge_anchors_where_it_was_picked(browser, serve, html):
    """A passage closing its section used to store a suffix clipped at the section's
    edge — one character, a bar the identical copy above it also cleared, so the mark
    painted there while the reviewer was still composing. The neighbours now come from
    the whole document and the section only filters where the search may land, so the
    closing copy is told apart by the words of the section after it.

    Where the document itself ends there is no second side to store, and an empty one is
    not an absent constraint: it says nothing followed the passage anywhere, which is true
    of exactly one occurrence. Refusing to read it that way left the same wrong mark."""
    page, errors = open_page(browser, serve(html))
    landed = page.evaluate("""async () => {
        const p = document.querySelectorAll('#edge p')[1];
        // Through the full stop, so that with the section below removed the passage is the
        // last thing the document says and its stored suffix comes out empty.
        const phrase = 'the run is retried until it lands.';
        const at = p.firstChild.data.indexOf(phrase);
        if (at === -1) return 'phrase missing';
        const want = document.createRange();
        want.setStart(p.firstChild, at); want.setEnd(p.firstChild, at + phrase.length);
        const sel = getSelection(); sel.removeAllRanges(); sel.addRange(want);
        document.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
        await new Promise(r => setTimeout(r, 60));
        const fab = document.querySelector('.cq-fab');
        if (fab.style.display !== 'block') return 'no button';
        fab.click();
        await new Promise(r => setTimeout(r, 60));
        const painted = [...(CSS.highlights.get('cq-pending') ?? [])][0];
        if (!painted) return 'no mark';
        if (painted.compareBoundaryPoints(Range.START_TO_START, want) === 0) return true;
        return painted.startContainer.parentElement.textContent.slice(0, 40);
    }""")
    assert landed is True, f"the closing copy was picked, the mark went elsewhere ({landed})"
    assert errors == []
    page.close()


def test_an_anchor_stored_under_the_section_clipped_capture_still_resolves(browser, serve):
    """The bar is however much was stored. An anchor from an older log carries context
    clipped at its section's edge; it confirms at that shorter bar exactly as it did when
    it was written, so nothing already in a log detaches when the capture reaches
    further."""
    url = serve(EDGE_PAGE)
    interact.append_event(serve.page_dir, {
        "kind": "comment", "author": "claude", "version": 1, "text": "old bar",
        "anchor": {"section": "edge", "quote": "the run is retried until it lands",
                   "prefix": "fails again in the night,", "suffix": "."}})
    page, errors = open_page(browser, url)
    page.wait_for_function("() => (CSS.highlights.get('cq-mark')?.size ?? 0) > 0")
    where = page.evaluate("""() => {
        const r = [...CSS.highlights.get('cq-mark')][0];
        return r.startContainer.parentElement.textContent.slice(0, 11);
    }""")
    assert where == "First pass:", (
        f"an old anchor's thin bar changed where it lands: {where!r}"
    )
    assert errors == []
    page.close()


def test_a_one_sided_anchor_from_an_older_capture_falls_back(browser, serve):
    """A capture that stopped at the section root wrote no prefix at all for a passage
    opening its section. Read the way the search now reads an empty side — nothing preceded
    this passage anywhere on the page — that claim is false wherever the section wasn't
    first, so no occurrence confirms it and the comment stays where it always went, on the
    first copy in its section. Taking the one side it does carry as enough would instead
    hand the comment to whichever copy that side happens to fit."""
    url = serve(EDGE_PAGE)
    # A suffix that fits the second copy and nothing else, stored with no prefix beside it.
    interact.append_event(serve.page_dir, {
        "kind": "comment", "author": "claude", "version": 1, "text": "older anchor",
        "anchor": {"section": "edge", "quote": "the run is retried until it lands",
                   "suffix": ". Rollout resumes"}})
    page, errors = open_page(browser, url)
    page.wait_for_function("() => (CSS.highlights.get('cq-mark')?.size ?? 0) > 0")
    where = page.evaluate("""() => {
        const r = [...CSS.highlights.get('cq-mark')][0];
        return r.startContainer.parentElement.textContent.slice(0, 11);
    }""")
    assert where == "First pass:", (
        f"one side was taken as enough, and the comment went to the copy it fits: {where!r}"
    )
    assert errors == []
    page.close()


# A passage past the 400-code-point quote cap whose 400th code point is a space — the cut
# lands where the search's own reading of that spot would begin with whitespace, and it
# trims. Roughly one capped quote in six for English prose.
CAPPED_PASSAGE = 'Note: the migration replays on every deploy because the version stamp never lands, and the guard reads a column the writer never fills, and the whole batch runs again from the top on each release, and the counters disagree with the log and with each other, and the retry budget is spent before anyone looks at it, and the operator reads the dashboard at noon and files the incident, and the fix ships behind a flag nobody remembers to turn on, and the runbook still names a host that was retired last spring.'
CAPPED_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>capped</title>
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<h1 id="t">Capped</h1>
<section id="capped">
<p>Ahead of the first copy sits this line. {passage}</p>
<p>Between the copies sits this other line. {passage}</p>
</section>
</main>
</body>
</html>
""".replace("{passage}", CAPPED_PASSAGE)


def test_a_capped_quote_keeps_a_suffix_the_page_can_show(browser, serve):
    """A quote longer than the cap ends inside the selection, so its neighbours are read
    from after the cut rather than after the selection. The search reads its side through
    the same collapsing that trims leading whitespace — so a cut landing just before a space
    must not store one, or the stored suffix names a string no occurrence can produce and
    every copy fails at the first character."""
    assert CAPPED_PASSAGE[400] == " ", "the fixture no longer cuts on a space"
    page, errors = open_page(browser, serve(CAPPED_PAGE))
    landed = page.evaluate("""async () => {
        const copies = document.querySelectorAll('#capped p');
        if (copies.length !== 2) return `fixture holds ${copies.length} copies, wanted 2`;
        const p = copies[1];
        const text = p.firstChild.data;
        const at = text.indexOf('Note:');
        const want = document.createRange();
        want.setStart(p.firstChild, at); want.setEnd(p.firstChild, text.length);
        const sel = getSelection(); sel.removeAllRanges(); sel.addRange(want);
        document.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
        await new Promise(r => setTimeout(r, 60));
        const fab = document.querySelector('.cq-fab');
        if (fab.style.display !== 'block') return 'no button';
        fab.click();
        await new Promise(r => setTimeout(r, 60));
        const painted = [...(CSS.highlights.get('cq-pending') ?? [])][0];
        if (!painted) return 'no mark';
        return painted.compareBoundaryPoints(Range.START_TO_START, want) === 0;
    }""")
    assert landed is True, f"the second copy was picked, the mark went elsewhere ({landed})"
    assert errors == []
    page.close()


# A passage that opens its section stores no prefix — note there is no whitespace between
# the section tag and the paragraph, which is what makes the copy's leading context empty
# rather than short. Both copies carry the identical tail, so a suffix on its own is a bar
# the other copy clears just as well.
THIN_V1 = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>thin</title>
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<h1 id="t">Thin</h1>
<section id="thin"><p>{phrase}. Retries are capped at three.</p>
<p>An unrelated middle paragraph.</p>
<p>Queue drain runs first. {phrase}. Retries are capped at three.</p>
</section>
</main>
</body>
</html>
""".replace("{phrase}", "The version stamp never lands")
# Only the commented copy's tail changes, so the untouched copy is now the better match for
# the one neighbour the comment stored.
THIN_V2 = THIN_V1.replace(
    "lands. Retries are capped at three.</p>\n<p>An unrelated",
    "lands. Backoff is capped at three.</p>\n<p>An unrelated")


def test_one_neighbour_is_not_enough_to_move_a_comment(browser, serve):
    """Context may place a comment only where both of a passage's neighbours are still
    there. A passage at the edge of its section has just one, and one is a bar another copy
    clears — so a revision that rewrites the commented copy's only neighbour would hand the
    comment to a copy it was never made on, silently, a version after anyone was looking.
    The cost of refusing is visible instead: a passage like this is placed by document
    order, and a reviewer watching sees it land."""
    url = serve(THIN_V1)
    page, errors = open_page(browser, url)
    posted = page.evaluate("""async () => {
        const p = document.querySelectorAll('#thin p')[0];
        const phrase = 'The version stamp never lands';
        const at = p.firstChild.data.indexOf(phrase);
        const want = document.createRange();
        want.setStart(p.firstChild, at); want.setEnd(p.firstChild, at + phrase.length);
        const sel = getSelection(); sel.removeAllRanges(); sel.addRange(want);
        document.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
        await new Promise(r => setTimeout(r, 40));
        const fab = document.querySelector('.cq-fab');
        if (fab.style.display !== 'block') return 'no button';
        fab.click();
        await new Promise(r => setTimeout(r, 40));
        const box = document.querySelector('.cq-composer textarea');
        box.value = 'does this hold?';
        box.dispatchEvent(new Event('input', {bubbles: true}));
        document.querySelector('.cq-composer button.primary').click();
        return true;
    }""")
    assert posted is True, f"couldn't post the comment ({posted})"
    page.wait_for_function("() => (CSS.highlights.get('cq-mark')?.size ?? 0) > 0")

    d = serve.page_dir
    (d / "versions" / "v2.html").write_text(THIN_V2)
    interact.append_event(d, {"kind": "note", "author": "claude", "version": 2, "text": "revised"})
    page.wait_for_url("**/v2.html", timeout=15000)
    page.wait_for_function("() => (CSS.highlights.get('cq-mark')?.size ?? 0) > 0")
    where = page.evaluate("""() => {
        const r = [...CSS.highlights.get('cq-mark')][0];
        return r.startContainer.parentElement.textContent.slice(0, 40);
    }""")
    assert where.startswith("The version stamp never lands. Backoff"), (
        f"one neighbour was enough to move the comment: {where!r}"
    )
    assert errors == []
    page.close()


def test_the_picker_runs_in_number_order_past_v9(browser, serve):
    """A version's number is its identity and its file name only renders it, so the
    runtime parses the number back out of every name the server hands it. Order a
    review by those names instead and v10 lands between v1 and v2: the picker reads
    out of sequence, the diff offers the wrong base, and a reader on the newest
    version is told a newer one is waiting."""
    url = serve(INLINE_PAGE)
    for n in range(2, 11):
        _publish(serve.page_dir, n, INLINE_PAGE, f"cut {n}")
    page, errors = open_page(browser, url.replace("v1.html", "v10.html"))

    options = page.locator(".cq-banner select option")
    expect(options).to_have_count(10)
    assert [t.split(" ")[0] for t in options.all_text_contents()] == [
        f"v{n}" for n in range(1, 11)
    ]
    expect(options.last).to_contain_text("v10 (latest)")
    # The base a diff runs against is the version before this one in that order.
    expect(page.locator(".cq-banner button", has_text="Δ")).to_have_text("Δ v9")
    # Nothing is newer than v10, so no chip offers one.
    expect(page.locator(".cq-latest-chip")).to_be_hidden()
    assert errors == []
    page.close()

    # Pinned to the oldest, the chip naming the newest is the runtime's one place
    # that spells a version out in a sentence.
    page, errors = open_page(browser, url + "?pin")
    expect(page.locator(".cq-latest-chip")).to_have_text(
        "New version available → open v10"
    )
    assert errors == []
    page.close()


def test_a_diff_anchors_to_the_side_it_was_read_on(browser, serve):
    """The case this exists for, and the one a section cannot narrow: a diff carries the
    same line added and removed under a single id, so the reviewer commenting on the fix
    had their comment marked against the bug — stored that way, and shown to Claude that
    way in the next round."""
    page, errors = open_page(browser, serve(TWICE_PAGE))
    landed = page.evaluate("""async () => {
        const skip = '.cq-ui, script, style';
        const w = document.createTreeWalker(document.getElementById('patch'),
            NodeFilter.SHOW_TEXT,
            {acceptNode: n => n.parentElement?.closest(skip)
                ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT});
        const hits = [];
        const phrase = 'return request.path';
        for (let n = w.nextNode(); n; n = w.nextNode()) {
            let i = n.data.indexOf(phrase);
            while (i !== -1) { hits.push({node: n, at: i}); i = n.data.indexOf(phrase, i + 1); }
        }
        if (hits.length < 2) return `only ${hits.length} occurrence(s) — fixture broken`;
        const h = hits.at(-1);   // the added line: the later of the pair
        const want = document.createRange();
        want.setStart(h.node, h.at); want.setEnd(h.node, h.at + phrase.length);
        const sel = getSelection(); sel.removeAllRanges(); sel.addRange(want);
        document.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
        await new Promise(r => setTimeout(r, 40));
        const fab = document.querySelector('.cq-fab');
        if (fab.style.display !== 'block') return 'no button';
        fab.click();
        await new Promise(r => setTimeout(r, 40));
        const painted = [...(CSS.highlights.get('cq-pending') ?? [])][0];
        if (!painted) return 'no mark';
        return painted.compareBoundaryPoints(Range.START_TO_START, want) === 0;
    }""")
    assert landed is True, f"the added line was picked, the mark went elsewhere ({landed})"
    assert errors == []
    page.close()


# The journey's page: a passage to comment on, a board to drag, and a draft to
# edit. In v2 the commented paragraph moves below the notes heading — same text,
# new position — so the anchor has to re-find its passage rather than replay a
# location. The draft's source lines are indented like any other child content;
# the widget owes the reviewer the text without them.
SENTENCE = "The version stamp never lands, so migration 0041 replays on every deploy."
DRAFT_TEXT = "Run the migration before deploying.\nIt is online."
DRAFT_EDITED = "Run the migration before deploying. It takes about a minute."
JOURNEY_SCAFFOLD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>journey</title>
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<h1 id="t">Journey</h1>
{before}
<cq-board id="board">
  <cq-column id="col-todo" label="Todo">
    <cq-card id="card-x"><strong>Guard the session delete</strong> One line.</cq-card>
  </cq-column>
  <cq-column id="col-done" label="Done"></cq-column>
</cq-board>
<cq-draft id="draft-ops">
    Run the migration before deploying.
    It is online.
</cq-draft>
<h2 id="notes">Notes</h2>
{after}
</main>
</body>
</html>
"""
PASSAGE = f'<p id="intro">{SENTENCE}</p>'
JOURNEY_V1 = JOURNEY_SCAFFOLD.format(before=PASSAGE, after="<p id='p-filler'>Filler.</p>")
JOURNEY_V2 = JOURNEY_SCAFFOLD.format(before="<p id='p-filler'>Filler.</p>", after=PASSAGE)


def _draft_says(html, text, attrs=""):
    """The journey page with its draft rewritten — the source's indentation and
    all, since that is what the widget dedents back out."""
    return html.replace(
        '<cq-draft id="draft-ops">\n' + "\n".join(f"    {l}" for l in DRAFT_TEXT.split("\n")),
        f'<cq-draft id="draft-ops"{attrs}>\n    {text}',
    )


def _publish(page_dir, version, html, note):
    """Write a version and publish it the way Claude does — through `note`, which
    lints it and records what it says about the reviewer's decisions."""
    (page_dir / "versions" / f"v{version}.html").write_text(html)
    result = CliRunner().invoke(
        interact.cli,
        ["note", str(page_dir), "--version", str(version), "--text", note],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output


def test_review_round_trip(browser, serve):
    """The loop the product is, driven through the real UI: select a passage and
    comment on it, drag a card to another column, rewrite a draft in place, then
    follow the next version and find the comment still anchored to its
    (relocated) passage and the draft still wearing the reviewer's words. The
    final assertion is the event log — the trail Claude reads — down to the
    anchor's quote, the move's placement, and the edit's text."""
    page, errors = open_page(browser, serve(JOURNEY_V1))

    # Select the passage from the keyboard's path: a real Range, then the keyup
    # the runtime watches for keyboard selections, then the c binding — which
    # runs the same the fab's own click as the floating button's click.
    page.evaluate("""() => {
        const r = document.createRange();
        r.selectNodeContents(document.getElementById('intro'));
        getSelection().removeAllRanges();
        getSelection().addRange(r);
        document.body.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
    }""")
    page.wait_for_selector(".cq-fab", state="visible")  # the selection raised the button
    page.keyboard.press("c")
    page.wait_for_selector(".cq-composer", state="visible")
    page.locator(".cq-composer textarea").fill("Is 0041 idempotent?")
    page.locator(".cq-composer").get_by_role("button", name="Comment").click()
    page.wait_for_selector(".cq-thread")
    # The anchor pass painted the passage — a range in the highlight registry, not an
    # element, so there is no selector for it.
    page.wait_for_function("() => (CSS.highlights.get('cq-mark')?.size ?? 0) > 0")

    # Drag the card between columns through the pointer path — the seam where
    # the vendored SortableJS meets the runtime, which is where drags break.
    grip = page.locator("#card-x .cq-grip").bounding_box()
    dest = page.locator("#col-done").bounding_box()
    page.mouse.move(grip["x"] + grip["width"] / 2, grip["y"] + grip["height"] / 2)
    page.mouse.down()
    page.mouse.move(dest["x"] + dest["width"] / 2, dest["y"] + dest["height"] / 2, steps=15)
    page.mouse.up()
    page.wait_for_selector("#col-done #card-x")  # the drop reparented the card

    # Rewrite the draft through its fast path: double-click opens the text in
    # place (winning over the word-selection the gesture makes — no comment
    # button contests it), Save sends the whole new body. The text must have
    # arrived without the source's indentation.
    draft = page.locator("#draft-ops")
    assert draft.locator(".cq-draft-body").inner_text() == DRAFT_TEXT
    draft.locator(".cq-draft-body").dblclick()
    draft.locator("textarea").fill(DRAFT_EDITED)
    draft.get_by_role("button", name="Save").click()
    page.wait_for_function(
        "t => document.querySelector('#draft-ops .cq-draft-body').textContent === t",
        arg=DRAFT_EDITED,
    )

    # The edit must be in the log before v2's note lands, or the trail below
    # would interleave — the browser posts it, so wait server-side.
    d = serve.page_dir
    deadline = time.time() + 5
    while '"action": "edit"' not in (d / "comments.jsonl").read_text():
        assert time.time() < deadline, "the edit never reached the log"
        time.sleep(0.05)

    # Claude ships v2 with the passage moved; the page follows on its next poll.
    (d / "versions" / "v2.html").write_text(JOURNEY_V2)
    interact.append_event(d, {"kind": "note", "author": "claude", "version": 2, "text": "moved"})
    page.wait_for_url("**/v2.html", timeout=15000)
    # The anchor pass runs at render: a mark now means the quote was re-found in
    # its new position; no mark within the wait means the anchor lost it.
    page.wait_for_function("() => (CSS.highlights.get('cq-mark')?.size ?? 0) > 0", timeout=5000)
    assert not page.evaluate(
        "document.querySelector('.cq-thread .cq-quote').classList.contains('detached')"
    ), "the passage moved and the comment lost it"
    # v2's markup carries the original draft text — Claude hasn't honored the
    # edit — so the reviewer's words must arrive by replay, not visibly revert.
    page.wait_for_function(
        "t => document.querySelector('#draft-ops .cq-draft-body').textContent === t",
        arg=DRAFT_EDITED,
    )

    assert errors == []
    # The trail those gestures left, exactly — kinds, authorship (the server
    # stamps browser events `user`), the anchor, and the move's placement.
    events = [json.loads(line) for line in (d / "comments.jsonl").read_text().splitlines()]
    assert [(e["kind"], e["author"], e["version"]) for e in events] == [
        ("note", "claude", 1),
        ("comment", "user", 1),
        ("action", "user", 1),
        ("action", "user", 1),
        ("note", "claude", 2),
    ]
    assert events[1]["anchor"] == {
        "section": "intro",
        "quote": SENTENCE,
        "prefix": "Journey",
        "suffix": "Todo Guard the session d",
    }
    assert events[1]["text"] == "Is 0041 idempotent?"
    assert {k: events[2][k] for k in ("widget", "action", "detail")} == {
        "widget": "board",
        "action": "move",
        "detail": {"card": "card-x", "to": "col-done", "index": 0},
    }
    assert {k: events[3][k] for k in ("widget", "action", "detail")} == {
        "widget": "draft-ops",
        "action": "edit",
        "detail": {"text": DRAFT_EDITED},
    }
    page.close()


def test_a_comment_inside_a_widget_stays_out_of_what_the_widget_reads(browser, serve):
    """The line that tells a screen reader a block carries a comment is chrome, and chrome
    inside a widget's own content is chrome in the reviewer's text: cq-draft seeds the
    editor they type into from its body div, so a line left in there arrives in the
    textarea and posts with the edit. It goes on the block the passage sits in, or on the
    element the anchor names — never on the inline run or body div in between."""
    url = serve(JOURNEY_V1, anchored=[("draft-ops", "Run the migration before deploying.")])
    page, errors = open_page(browser, url)
    page.wait_for_function("() => (CSS.highlights.get('cq-mark')?.size ?? 0) > 0")
    assert page.locator("#draft-ops > .cq-mark-note").count() == 1, (
        "the line landed inside the draft's body rather than beside it"
    )
    page.locator("#draft-ops .cq-draft-body").dblclick()
    assert page.locator("#draft-ops textarea").input_value() == DRAFT_TEXT, (
        "the reviewer's editor opened on text the runtime had written into"
    )
    assert errors == []
    page.close()


def test_a_decision_claude_has_seen_still_survives_the_next_version(browser, serve):
    """The round trip above, differing in one fact: `wait` has handed the actions
    to Claude before v2 publishes. That is the ordinary case — Claude writes a
    version *because* it was handed the reviewer's edits — and it used to be the
    one that lost them: replay stopped at the delivery cursor, on the premise
    that a version written after seeing an action encodes it. Nothing checks that
    premise, so a version that quietly omits the state re-emitted the widget as
    untouched and the reviewer's work vanished with no error anywhere.

    Delivery is not assent. Only the next version's markup can say what Claude
    did with an edit, and until it says otherwise the log is what the reviewer
    did."""
    url = serve(JOURNEY_V1)
    d = serve.page_dir
    interact.append_event(d, {"kind": "action", "author": "user", "version": 1,
                              "widget": "board", "action": "move",
                              "detail": {"card": "card-x", "to": "col-done", "index": 0}})
    interact.append_event(d, {"kind": "action", "author": "user", "version": 1,
                              "widget": "draft-ops", "action": "edit",
                              "detail": {"text": DRAFT_EDITED}})
    # What `wait` writes on its way out: everything so far is Claude's to answer.
    interact.write_json(d / "cursor.json", {"seq": len(interact.read_events(d))})
    # And Claude answers with a version that carries neither — the page generator
    # emitting its own idea of the board and the draft, as one did for five
    # versions running.
    (d / "versions" / "v2.html").write_text(JOURNEY_V2)
    interact.append_event(d, {"kind": "note", "author": "claude", "version": 2, "text": "v2"})

    page, errors = open_page(browser, url.replace("v1.html", "v2.html"))
    page.wait_for_function(
        "t => document.querySelector('#draft-ops .cq-draft-body').textContent === t",
        arg=DRAFT_EDITED,
    )
    expect(page.locator("#col-done #card-x")).to_have_count(1)
    assert errors == []
    page.close()


def test_restating_a_widget_is_how_a_version_takes_the_pen_back(browser, serve):
    """The other end of the rule above. Since the log outranks the markup, a
    version cannot revise a draft the reviewer has rewritten — replay would paint
    their words straight back over it, and Claude's correction would reach nobody.
    `restated` is the one way markup wins: it retracts what came before it, so
    the new words render and the reviewer sees the widget marked as one whose
    decision this version undid.

    It costs a word, where losing a decision used to cost nothing, which is the
    whole asymmetry: the failure that stays silent is now the one that needs
    saying out loud."""
    url = serve(JOURNEY_V1)
    d = serve.page_dir
    interact.append_event(d, {"kind": "action", "author": "user", "version": 1,
                              "widget": "draft-ops", "action": "edit",
                              "detail": {"text": DRAFT_EDITED}})
    corrected = "Run the migration after deploying — it needs the new column."
    _publish(d, 2, _draft_says(JOURNEY_V2, corrected, " restated"),
             "0041 needs the column; rewrote the draft")

    page, errors = open_page(browser, url.replace("v1.html", "v2.html"))
    body = page.locator("#draft-ops .cq-draft-body")
    expect(body).to_have_text(corrected)
    # And the reviewer is told, rather than left to notice: their edit is gone,
    # which without a mark reads exactly like a draft they never touched.
    expect(page.locator("#draft-ops[data-cq-restated]")).to_have_count(1)
    assert errors == []
    page.close()


def test_a_retraction_outlives_the_version_that_made_it(browser, serve):
    """`restated` belongs to the version that rewrote the words, and to no other:
    v3 has nothing to declare, because it is not the one taking anything back.

    So the retraction cannot live in the markup, or v3's silence would read as
    "carry the decision" and hand the reviewer's edit straight back — the same
    resurrection the branch removed, one version later and just as quiet.
    Publishing records it in the log instead, where it is a fact with a version
    on it and every later version inherits it for free."""
    url = serve(JOURNEY_V1)
    d = serve.page_dir
    interact.append_event(d, {"kind": "action", "author": "user", "version": 1,
                              "widget": "draft-ops", "action": "edit",
                              "detail": {"text": DRAFT_EDITED}})
    corrected = "Run the migration after deploying — it needs the new column."
    _publish(d, 2, _draft_says(JOURNEY_V2, corrected, " restated"), "rewrote the draft")
    # v3 keeps v2's words and says nothing about the retraction, because
    # saying it again would be claiming to undo a decision already undone.
    _publish(d, 3, _draft_says(JOURNEY_V2, corrected), "unrelated copy edits")

    page, errors = open_page(browser, url.replace("v1.html", "v3.html"))
    expect(page.locator("#draft-ops .cq-draft-body")).to_have_text(corrected)
    assert errors == []
    page.close()

    # And the careful author who carries the attribute forward anyway — the habit
    # this whole design exists to break — is told which version already did it.
    (d / "versions" / "v4.html").write_text(
        _draft_says(JOURNEY_V2, corrected, " restated")
    )
    result = CliRunner().invoke(
        interact.cli, ["note", str(d), "--version", "4", "--text", "again"]
    )
    assert result.exit_code != 0
    assert "v2 already took that back" in result.output


_CARD = '<cq-card id="card-x"><strong>Guard the session delete</strong> One line.</cq-card>'


def _card_done(html):
    """The journey page with its card written in Done — the honoring of a
    recorded drag, or the author's own relocation."""
    return html.replace(
        f'    {_CARD}\n  </cq-column>\n  <cq-column id="col-done" label="Done"></cq-column>',
        f'  </cq-column>\n  <cq-column id="col-done" label="Done">{_CARD}</cq-column>',
    )


def test_a_decision_not_yet_honored_wears_the_pending_mark(browser, serve):
    """One pass, every widget alike: a decided-and-unhonored state wears
    data-cq-pending, driven by the registry's x-state rather than remembered per
    widget — choose had its mark, edit its tint, and move had nothing, which is
    how a dragged card's fate stayed invisible once the toast faded. The mark
    clears the moment a version carries the decision, and the diff stays quiet
    about an honored move: the reviewer's own drag is not news to them."""
    page, errors = open_page(browser, serve(JOURNEY_V1))

    # A real drag — the pointer path, where the gesture gate and the poll meet.
    grip = page.locator("#card-x .cq-grip").bounding_box()
    dest = page.locator("#col-done").bounding_box()
    page.mouse.move(grip["x"] + grip["width"] / 2, grip["y"] + grip["height"] / 2)
    page.mouse.down()
    page.mouse.move(dest["x"] + dest["width"] / 2, dest["y"] + dest["height"] / 2, steps=15)
    page.mouse.up()
    expect(page.locator("#card-x[data-cq-pending]")).to_have_count(1)

    draft = page.locator("#draft-ops")
    draft.locator(".cq-draft-body").dblclick()
    draft.locator("textarea").fill(DRAFT_EDITED)
    draft.get_by_role("button", name="Save").click()
    expect(page.locator("#draft-ops[data-cq-pending]")).to_have_count(1)

    # Both actions must be in the log before the honoring version publishes.
    d = serve.page_dir
    deadline = time.time() + 5
    while (d / "comments.jsonl").read_text().count('"kind": "action"') < 2:
        assert time.time() < deadline, "the actions never reached the log"
        time.sleep(0.05)

    _publish(d, 2, _card_done(_draft_says(JOURNEY_V2, DRAFT_EDITED)), "honors the move and the edit")
    page.wait_for_url("**/v2.html", timeout=15000)
    page.wait_for_function("() => document.querySelector('.cq-banner') !== null")
    # A poll has run once the status text resolves, so the pending pass has too.
    page.wait_for_function(
        "() => !document.querySelector('.cq-status-text').textContent.startsWith('Connecting')"
    )
    expect(page.locator("[data-cq-pending]")).to_have_count(0)

    # The diff's state half is quiet about the honored move: base state is the
    # base markup plus the fold as of it, which already has the card in Done.
    page.get_by_role("button", name=re.compile("Δ")).click()
    page.wait_for_function("() => document.querySelector('.cq-banner .cq-btn.on') !== null")
    assert not page.evaluate(
        "document.getElementById('card-x').classList.contains('cq-ins-block')"
    ), "the reviewer's own honored drag marked as a change"
    assert errors == []
    page.close()


def test_the_diff_marks_a_card_the_author_relocated(browser, serve):
    """A pure state change has no text of its own, so the content diff was blind
    to it: a card in a new column read as nothing changed. The state half
    compares declared facets, so the author moving a card between versions —
    with no reviewer action behind it — marks the card itself. The card alone:
    an id'd element nested inside it rode along rather than changing columns,
    and marking it too would double-tint one move."""
    noted = _CARD.replace("</cq-card>", '<p id="card-x-note">A nested aside.</p></cq-card>')
    v1 = JOURNEY_V1.replace(_CARD, noted)
    url = serve(v1)
    d = serve.page_dir
    _publish(d, 2, _card_done(JOURNEY_V1).replace(_CARD, noted), "moved the card to Done")
    page, errors = open_page(browser, url.replace("v1.html", "v2.html"))
    page.get_by_role("button", name=re.compile("Δ")).click()
    page.wait_for_function(
        "() => document.getElementById('card-x').classList.contains('cq-ins-block')"
    )
    assert not page.evaluate(
        "document.getElementById('card-x-note').classList.contains('cq-ins-block')"
    ), "the card's passenger marked as its own move"
    assert errors == []
    page.close()


SUGGEST_BLOCK = (
    '<cq-suggestion id="sug-fix" resolves="c1">'
    '<cq-old><p id="old-claim">It is not online.</p></cq-old>'
    "<cq-new><p>It takes a minute of downtime.</p></cq-new>"
    "</cq-suggestion>"
)


def test_accepting_a_suggestion_resolves_its_thread_in_one_event(browser, serve):
    """Accepting answers the thread the change was written for, and the answer
    rides the accept itself — the wrapper holding the `resolves` mapping is
    retired by the honoring version, and a second POST could fail alone, leaving
    the outcome and the resolution disagreeing with no repair path. One event,
    read by both thread builders."""
    url = serve(JOURNEY_V1.replace('<h2 id="notes">', SUGGEST_BLOCK + '<h2 id="notes">'))
    d = serve.page_dir
    interact.append_event(d, {"kind": "comment", "id": "c1", "author": "user", "version": 1,
                              "text": "does this take downtime?"})
    page, errors = open_page(browser, url)
    page.get_by_role("button", name=re.compile("^Accept the suggested change")).click()
    page.get_by_role("button", name=re.compile("^Comments")).click()
    expect(page.locator(".cq-details summary")).to_have_text("Resolved (1)")
    events = [json.loads(line) for line in (d / "comments.jsonl").read_text().splitlines()]
    accept = next(e for e in events if e.get("kind") == "action")
    assert accept["action"] == "accept" and accept["detail"] == {"resolves": "c1"}
    assert not any(e.get("kind") == "resolve" for e in events)
    assert errors == []
    page.close()


def test_the_help_overlay_answers_to_one_owner(browser, serve):
    """Open or closed is state with one writer now — it was three writers and
    two classList read-backs, the exact shape the first norm forbids. Driven by
    real keys and a real outside click, the gestures those writers served."""
    page, errors = open_page(browser, serve(JOURNEY_V1))
    page.keyboard.press("?")
    expect(page.locator(".cq-help")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator(".cq-help")).to_be_hidden()
    page.keyboard.press("?")
    expect(page.locator(".cq-help")).to_be_visible()
    page.mouse.click(300, 600)
    expect(page.locator(".cq-help")).to_be_hidden()
    assert errors == []
    page.close()


@pytest.fixture(scope="module")
def dead_pid():
    """A pid that is certainly not running, for a page whose session has exited."""
    spent = subprocess.Popen([sys.executable, "-c", ""])
    spent.wait()
    return spent.pid


@contextmanager
def live_watcher(page_dir):
    """Bump heartbeat.json for the duration of the block, as a running `wait` does."""
    stop = threading.Event()

    def pump():
        while True:
            interact.write_json(page_dir / "heartbeat.json", {"t": time.time()})
            if stop.wait(0.5):
                return

    threading.Thread(target=pump, daemon=True).start()
    try:
        yield
    finally:
        stop.set()
        (page_dir / "heartbeat.json").unlink(missing_ok=True)


def test_banner_reports_whether_anyone_is_attending(browser, serve, tmp_path, dead_pid):
    """The banner may claim no more than the page directory can prove. A watch that
    has stopped must read differently from a watch with nothing to report, because
    otherwise the reviewer's only way to tell them apart is to ask."""
    page, _ = open_page(browser, serve(LONG_PAGE, comments=1))
    d = tmp_path / "page"
    text, dot = page.locator(".cq-status-text"), page.locator(".cq-dot")

    def declare(state, detail="", *, handoff=False, quiet_for=0, session_pid=None):
        ts = datetime.now().astimezone() - timedelta(seconds=quiet_for)
        status = {"state": state, "detail": detail, "ts": ts.isoformat(timespec="seconds")}
        if handoff:
            status["handoff"] = True
        interact.write_json(
            d / "session.json", {"id": "s", "pid": session_pid or os.getpid(), "ts": "t"}
        )
        interact.write_json(d / "status.json", status)

    declare("working", "revising the plan")
    expect(text).to_have_text(re.compile(r"^Claude is working — revising the plan \(.+\)$"))
    expect(dot).to_have_class(re.compile(r"\bworking\b"))

    declare("waiting")
    with live_watcher(d):
        expect(text).to_have_text("Claude is listening — select text to comment")
        expect(dot).to_have_class(re.compile(r"\blistening\b"))

    # No watcher, but Claude checked in moments ago, so it is between turns.
    expect(text).to_have_text(
        "Claude isn't watching right now. 1 comment waiting. It picks them up next turn."
    )

    # The failure the whole mechanism exists for: `wait` delivered, set this status,
    # and Claude never came back. The handoff mark is what dates it.
    declare("working", "picking up 1 update", handoff=True, quiet_for=20 * 60)
    expect(text).to_have_text(
        "Claude last checked in 20m ago. 1 comment waiting. Nudge it in the terminal."
    )
    expect(dot).to_have_class(re.compile(r"\baway\b"))

    # Claude's own status gets a far longer rope: the same silence is just a long turn.
    declare("working", "running the migration", quiet_for=10 * 60)
    expect(text).to_have_text(re.compile(r"^Claude is working — running the migration"))

    # A dead session needs no timeout at all — the owning pid is simply gone.
    declare("working", "running the migration", session_pid=dead_pid)
    expect(text).to_have_text(
        "The Claude session reviewing this page has ended. 1 comment waiting."
        " Start one in the terminal to pick it up."
    )

    declare("idle")
    expect(text).to_have_text("Review closed")
    page.close()


# ---------- anchors written without a browser ----------
# `comment` writes an anchor by reading the version file; the runtime resolves it against
# the DOM that file becomes. Nothing static can check that those two readings agree, and
# every way they can come apart — a widget's upgrade, an attribute rendered as text, the
# space a block boundary stands for — only exists once the page is loaded.


def written_anchors(page_dir, html, limit=40):
    """Anchors `comment` would write for windows over a page's own prose. A window the
    page says twice, or one crossing a fence, is refused on purpose — skipping those here
    is that refusal, and what survives is exactly what the command promises to place."""
    registry = interact.load_registry(page_dir)
    text = interact.page_passages(html, registry).text
    words = text.split(" ")
    anchors = []
    for start in range(0, len(words), 3):
        quote = " ".join(words[start:start + 8])
        if len(quote) < 20:
            continue
        try:
            anchors.append((quote, interact.capture_anchor(html, registry, quote, None)))
        except ValueError:
            continue
        if len(anchors) == limit:
            break
    return anchors


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda p: p.stem)
def test_an_anchor_written_from_the_file_lands_on_the_page(browser, serve, example):
    """The claim `comment` makes is that a quote read out of the version file names the
    same passage in the browser. Checked on the pages people actually write, because the
    ways it can fail are all theirs: a diagram that renders to a picture, an attribute the
    runtime turns into text, two paragraphs whose join is a space in one reading and
    nothing in the other."""
    html = example.read_text()
    url = serve(html)
    d = serve.page_dir
    anchors = written_anchors(d, html)
    assert len(anchors) >= 10, f"only {len(anchors)} anchors over {example.stem}; sweep too thin"
    for i, (_, anchor) in enumerate(anchors):
        interact.append_event(d, {"kind": "comment", "author": "claude", "version": 1,
                                  "id": f"written{i}", "anchor": anchor, "text": f"note {i}"})
    page, errors = open_page(browser, url)
    page.wait_for_function("() => (CSS.highlights.get('cq-mark')?.size ?? 0) > 0")

    # The runtime's own record of which threads it found a home for.
    detached = page.eval_on_selector_all(
        ".cq-thread .cq-quote.detached", "els => els.map(e => e.textContent)"
    )
    assert detached == [], f"{len(detached)} anchors resolved to nothing in {example.stem}: {detached}"
    # And that the homes are the right ones. Painted in thread order, one range per
    # segment, so the passages concatenate: whitespace aside, because a quote's is
    # elastic to the search by design — a block boundary is a space in the file's
    # reading and no character at all in the page's.
    painted = re.sub(r"\s", "", page.evaluate(
        "() => [...CSS.highlights.get('cq-mark')].map(r => r.toString()).join('')"
    ))
    wanted = re.sub(r"\s", "", "".join(quote for quote, _ in anchors))
    assert painted == wanted, f"anchors in {example.stem} painted text they don't name"
    assert errors == []
    page.close()


TWIN_V1 = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>twin</title>
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<h1 id="t">Twin</h1>
<section id="twin">
<p id="p-original">Cache warmup runs first. The version stamp never lands. Retries are capped at three.</p>
</section>
</main>
</body>
</html>
"""
# A copy the anchor was not made on, added above it — so first-match now finds the wrong
# one, and only the neighbours the capture stored say which was meant.
TWIN_V2 = TWIN_V1.replace(
    '<p id="p-original">',
    '<p id="p-added">Queue drain runs first. The version stamp never lands. Retries are capped at four.</p>\n'
    '<p id="p-original">',
)


def test_a_written_anchor_keeps_its_copy_when_the_page_grows_another(browser, serve):
    """A quote unique when it was written is not unique forever. The neighbours a written
    anchor stores are what hold it on the passage it was made about — without them the
    search takes the first copy, and a comment ends up on words nobody wrote it about."""
    url = serve(TWIN_V1)
    d = serve.page_dir
    result = CliRunner().invoke(
        interact.cli,
        ["comment", str(d), "--quote", "The version stamp never lands", "--text", "capped where?"],
    )
    assert result.exit_code == 0, result.output
    anchor = json.loads(result.output)["anchor"]
    assert anchor["prefix"] and anchor["suffix"], f"nothing stored to tell copies apart: {anchor}"

    page, errors = open_page(browser, url)
    page.wait_for_function("() => (CSS.highlights.get('cq-mark')?.size ?? 0) > 0")
    (d / "versions" / "v2.html").write_text(TWIN_V2)
    interact.append_event(d, {"kind": "note", "author": "claude", "version": 2, "text": "a twin"})
    page.wait_for_url("**/v2.html", timeout=15000)
    page.wait_for_function("() => (CSS.highlights.get('cq-mark')?.size ?? 0) > 0")
    where = page.evaluate(
        "() => [...CSS.highlights.get('cq-mark')][0].startContainer.parentElement.id"
    )
    assert where == "p-original", f"the new copy took the comment ({where})"
    assert errors == []
    page.close()


def test_a_written_comment_opens_a_thread_the_reviewer_answers(browser, serve):
    """Claude's side of a thread is the reviewer's side with the author flipped: the panel
    names it, counts it as open, and offers the reply box and Resolve that close it."""
    url = serve(TWIN_V1)
    d = serve.page_dir
    assert CliRunner().invoke(
        interact.cli,
        ["comment", str(d), "--quote", "Retries are capped at three", "--text", "is three right?"],
    ).exit_code == 0
    page, errors = open_page(browser, url)
    page.wait_for_function("() => (CSS.highlights.get('cq-mark')?.size ?? 0) > 0")
    toggle = page.locator("button[aria-expanded]")
    expect(toggle).to_have_text("Comments (1)")  # counted as open, like any other thread
    toggle.click()
    thread = page.locator(".cq-thread").first
    expect(thread.locator(".cq-msg.claude .cq-msg-head b")).to_have_text("Claude")
    expect(thread.locator(".cq-quote")).to_have_text("“Retries are capped at three”")

    thread.locator("textarea").fill("three is the retry budget, not a guess")
    thread.get_by_role("button", name="Reply").click()
    expect(page.locator(".cq-msg.user")).to_have_count(1)
    page.locator(".cq-thread").first.get_by_role("button", name="Resolve").click()
    expect(page.locator(".cq-details summary")).to_have_text("Resolved (1)")

    kinds = [(e["kind"], e.get("author")) for e in interact.read_events(d)]
    assert ("comment", "claude") in kinds
    assert ("reply", "user") in kinds and ("resolve", "user") in kinds
    assert errors == []
    page.close()
