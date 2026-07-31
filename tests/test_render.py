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

import base64
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import zlib
from contextlib import contextmanager
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from axe_playwright_python.sync_playwright import Axe
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


# A page's key is minted per page; fixed here so a test can build a URL for a
# server it did not start.
TOKEN = "test-page-key"


@pytest.fixture
def serve(tmp_path, monkeypatch):
    """Publish HTML as v1 of a fresh page directory and serve it, as the real
    server does — vendoring included, so the assets under test are this repo's."""

    def go(html, comments=0, anchored=()):
        monkeypatch.chdir(tmp_path)  # keep the project layer out of the overlay
        d = tmp_path / "page"
        assert CliRunner().invoke(interact.cli, ["page", "init", str(d)]).exit_code == 0
        (d / "versions" / "v1.html").write_text(html)
        interact.append_event(d, {"kind": "note", "author": "claude", "version": 1, "text": "t"})
        for i in range(comments):
            interact.append_event(d, {"kind": "comment", "author": "user", "version": 1,
                                      "text": f"Comment {i}. " + "Long enough to wrap. " * 4})
        for section, quote in anchored:
            interact.append_event(d, {"kind": "comment", "author": "user", "version": 1,
                                      "text": "About this bit.",
                                      "anchor": {"section": section, "quote": quote}})
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), interact.handler_for(d, TOKEN))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        servers.append(httpd)
        go.page_dir = d  # for tests that publish a v2 or read the event log
        # The key rides in the URL exactly as it does in a handover, so the first
        # navigation of each browser context earns the cookie the rest of the
        # page's own fetches go out under.
        return f"http://127.0.0.1:{httpd.server_address[1]}/versions/v1.html?t={TOKEN}"

    servers = []
    yield go
    for httpd in servers:
        httpd.shutdown()


def open_page(browser, url, *, pin=False, init_script=None, wait_until="networkidle", context=None):
    """A page with its console errors collected, settled enough for mermaid.

    `pin` asks for the version the URL names rather than the newest, and is a keyword
    because the URL a handover carries already has a query holding the page's key: a
    test appending its own `?pin` overwrote that key and got a page that never loaded."""
    page = (
        context.new_page()
        if context
        else browser.new_page(viewport={"width": 1200, "height": 900}, color_scheme="light")
    )
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    # The console's own word for a bad response is "Failed to load resource", which
    # names nothing; carry the status and URL so a failure says what went missing.
    page.on("response", lambda r: errors.append(f"{r.status} {r.url}") if r.status >= 400 else None)
    if init_script:
        page.add_init_script(init_script)
    if pin:
        url += ("&" if "?" in url else "?") + "pin"
    page.goto(url, wait_until=wait_until)
    page.wait_for_function("() => document.querySelector('.cq-banner') !== null")
    return page, errors


def panel_settled(page, open=True):
    """Wait for the panel to reach `open` and the page to finish making room for it.

    Two things happen, and they don't finish together: the class flips at once and the
    document slides into its new width over about a fifth of a second (syncLayout). A
    geometry read taken on the flip is a read of the page mid-flight — its right edge
    still under the panel, its column still the width it had — so an assertion fed by
    one is about a layout that exists for a sixth of a second and then doesn't.

    Two consecutive frames at the same margin is the transition finishing, said in the
    transition's own terms: it interpolates on every frame while it runs and holds
    still after. Waiting a duration instead would encode a number the stylesheet is
    free to change, and would still be a guess on a loaded machine."""
    page.wait_for_function(
        "(open) => document.querySelector('.cq-panel').classList.contains('open') === open",
        arg=open,
    )
    page.evaluate("() => { window.__cqMargin = null; }")
    page.wait_for_function(
        """() => { const m = getComputedStyle(document.body).marginRight;
                   const settled = window.__cqMargin === m;
                   window.__cqMargin = m;
                   return settled; }"""
    )


CUSTOM_WIDGET_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>custom widget</title>
<link rel="stylesheet" href="/theme.css">
</head>
<body>
<main>
<h1 id="title">Project vocabulary</h1>
<cq-callout id="custom-note">
  <strong>Heads up</strong> This widget came from the project layer.
</cq-callout>
</main>
<script type="module" src="/colloquy.js"></script>
</body>
</html>
"""


def test_a_scaffolded_project_widget_loads_through_the_real_layer(
    browser, serve, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        interact.cli, ["customize", "widget", "cq-callout", "--upgrade"]
    )
    assert result.exit_code == 0, result.output

    url = serve(CUSTOM_WIDGET_PAGE)
    page, errors = open_page(browser, url)
    widget = page.locator("#custom-note")
    expect(widget).to_have_attribute("data-cq-done", "1")
    assert widget.evaluate(
        "(el) => ({display: getComputedStyle(el).display, "
        "border: getComputedStyle(el).borderTopWidth})"
    ) == {"display": "block", "border": "1px"}
    assert errors == []
    page.close()


def test_the_render_gate_rejects_an_upgrade_that_defines_no_element(
    browser, serve, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        interact.cli, ["customize", "widget", "cq-callout", "--upgrade"]
    )
    assert result.exit_code == 0, result.output
    module = tmp_path / ".colloquy" / "widgets" / "cq-callout.js"
    module.write_text("// Valid JavaScript, but no custom-element definition.\n")

    failures = interact.render_version(browser, serve(CUSTOM_WIDGET_PAGE))

    assert any(
        "upgraded widgets did not define their elements: <cq-callout>" in failure
        for failure in failures
    )


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda p: p.stem)
def test_example_renders(browser, serve, example):
    """Every shipped example loads clean and lays out, in both color schemes: no
    fail-soft error box, no console error, every visible widget occupies real
    space, no sideways scroll, no words on screen a selection can't reach. A
    widget that upgrades into a 1x1 box, or a heading painted by a pseudo-element,
    is the shape of failure a static lint cannot see. The invariants live in
    interact.render_version — the pass `version check --render` runs on agent-authored
    pages — so this sweep also proves the gate a reviewer's page goes through."""
    assert interact.render_version(browser, serve(example.read_text())) == []


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda p: p.stem)
@pytest.mark.parametrize("color_scheme", ["light", "dark"])
def test_examples_have_no_serious_wcag_a_or_aa_violations(
    browser, serve, example, color_scheme
):
    """Axe covers semantic failures the render gate cannot see: an unnamed control,
    an invalid role relationship, or a contrast failure can occupy a perfectly good
    box and still shut a reviewer out. Keep the scope to WCAG A/AA and actionable
    serious/critical findings; layout and accessibility-tree snapshots belong to
    specific regressions, not a corpus baseline that changes with every restyle."""
    page, errors = open_page(browser, serve(example.read_text()))
    page.emulate_media(color_scheme=color_scheme)
    result = Axe().run(
        page,
        options={
            "runOnly": {
                "type": "tag",
                "values": [
                    "wcag2a",
                    "wcag2aa",
                    "wcag21a",
                    "wcag21aa",
                    "wcag22a",
                    "wcag22aa",
                ],
            },
            "resultTypes": ["violations"],
        },
    )
    violations = [
        violation
        for violation in result.response["violations"]
        if violation["impact"] in {"serious", "critical"}
    ]
    report = "\n\n".join(
        f"{violation['id']} ({violation['impact']}): {violation['help']}\n"
        + "\n".join(
            f"  {', '.join(node['target'])}: {node['failureSummary']}"
            for node in violation["nodes"]
        )
        for violation in violations
    )
    assert violations == [], report
    assert errors == []
    page.close()


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
    """`version check --render` end to end, as the agent runs it: the static lint
    passes both versions, and only the one that renders clean may reach a reviewer.
    The broken version is deliberately unpublished — refusing it before
    `version publish` exposes it is the gate's whole job, so the preview server
    has to expose what no reviewer-facing server would."""
    serve(LONG_PAGE)
    d = serve.page_dir

    def gate(*args):
        return subprocess.run(
            [
                sys.executable,
                str(interact.__file__),
                "version",
                "check",
                str(d),
                "--render",
                *args,
            ],
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


def test_an_installed_payload_passes_its_real_browser_gate(tmp_path):
    """Exercise the copied artifact a host installs, never an import from this checkout."""
    root = Path(__file__).parent.parent
    installed = tmp_path / "host" / "plugins" / "colloquy"
    shutil.copytree(root / "plugins" / "colloquy", installed)
    launcher = installed / "bin" / "colloquy"
    elsewhere = tmp_path / "unrelated-project"
    elsewhere.mkdir()
    page_dir = tmp_path / "state" / "page"

    init = subprocess.run(
        [launcher, "page", "init", page_dir],
        cwd=elsewhere,
        capture_output=True,
        text=True,
        check=False,
    )
    assert init.returncode == 0, init.stderr
    (page_dir / "versions" / "v1.html").write_text(
        (root / "examples" / "release-notes.html").read_text()
    )
    publish = subprocess.run(
        [
            launcher,
            "version",
            "publish",
            page_dir,
            "--version",
            "1",
            "--text",
            "installed-payload smoke",
        ],
        cwd=elsewhere,
        capture_output=True,
        text=True,
        check=False,
    )
    assert publish.returncode == 0, publish.stderr

    rendered = subprocess.run(
        [launcher, "version", "check", page_dir, "--render"],
        cwd=elsewhere,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rendered.returncode == 0, rendered.stderr
    assert "renders clean" in rendered.stdout


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


def solid_png(width: int, height: int, rgb: tuple) -> bytes:
    """A solid-colour PNG, written here rather than committed, so the pair a shot
    test flips between is two files whose only difference is the one the test made."""
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


SHOTS = {"before": solid_png(600, 300, (210, 220, 235)), "after": solid_png(600, 300, (235, 215, 205))}
SHOT_SRC = {k: f"/media/{hashlib.sha256(v).hexdigest()[:16]}.png" for k, v in SHOTS.items()}
SHOT_PAGE = LONG_PAGE.replace(
    "</main>",
    f"""<p id="lede">What moved, in words, because the picture cannot say it.</p>
<cq-shot id="shot-nav" alt="the navigation rail"
         before="{SHOT_SRC['before']}" after="{SHOT_SRC['after']}"></cq-shot>
</main>""",
)


def shown_frames(page):
    return page.evaluate("""() => [...document.querySelectorAll('.cq-shotframe')]
        .filter(f => getComputedStyle(f).visibility === 'visible')
        .map(f => f.dataset.cqState)""")


def test_a_shot_shows_one_frame_and_flips_between_them(browser, serve):
    """The comparison cq-shot makes is a flip: two registered frames in one grid cell,
    one of them showing. What the gate covers on the way past is the rest of the
    widget's bargain — the captions naming each frame are the page's words and stay
    selectable, the radios are chrome and take no space in the reviewer's reading, and
    a printed copy keeps both frames and both captions."""
    url = serve(SHOT_PAGE)
    for name, data in SHOTS.items():
        (serve.page_dir / "media").mkdir(exist_ok=True)
        (serve.page_dir / SHOT_SRC[name].lstrip("/")).write_bytes(data)
    assert interact.render_version(browser, url) == []

    page, errors = open_page(browser, url)
    assert shown_frames(page) == ["before"]
    page.get_by_role("radio", name="after").check()
    expect(page.locator('.cq-shotframe[data-cq-state="after"]')).to_be_visible()
    assert shown_frames(page) == ["after"]
    assert errors == []
    page.close()


def test_a_shot_still_flips_with_every_script_removed(browser, serve, tmp_path):
    """Which is the whole reason the control is a radio group. A standalone copy of a
    colloquy page is its rendered DOM with the script tags dropped — the upgrade has
    already run, so the frames are there, but nothing the runtime bound is. A slider
    would have frozen at whatever the reader left it on; `:has(:checked)` is CSS, and
    the browser owns a radio's state.

    The bug this pins was real: setting `checked` as a property left no attribute to
    serialize, so the copy opened with neither frame chosen and both of them stacked
    in the one cell."""
    url = serve(SHOT_PAGE)
    for name, data in SHOTS.items():
        (serve.page_dir / "media").mkdir(exist_ok=True)
        (serve.page_dir / SHOT_SRC[name].lstrip("/")).write_bytes(data)
    page, _ = open_page(browser, url)
    page.evaluate("() => document.querySelectorAll('script').forEach(s => s.remove())")
    baked = page.evaluate("() => document.documentElement.outerHTML").replace(
        '<link rel="stylesheet" href="/theme.css">',
        "<style>" + (serve.page_dir / "theme.css").read_text() + "</style>",
    )
    for name, data in SHOTS.items():
        baked = baked.replace(
            SHOT_SRC[name], "data:image/png;base64," + base64.b64encode(data).decode()
        )
    page.close()

    standalone = tmp_path / "standalone.html"
    standalone.write_text(baked)
    loose = browser.new_page(viewport={"width": 1200, "height": 900})
    loose.goto(standalone.as_uri(), wait_until="load")
    assert loose.evaluate("document.querySelectorAll('script').length") == 0
    assert shown_frames(loose) == ["before"]
    loose.get_by_role("radio", name="after").check()
    assert shown_frames(loose) == ["after"]
    loose.close()


def test_a_shot_refuses_a_pair_shot_at_two_widths(browser, serve):
    """Both frames render at the frame's width, so a pair captured at two viewports is
    scaled by two different factors and every line in it lands somewhere new — the flip
    then reports that the whole page changed, convincingly and with nothing on screen
    to say otherwise. The one failure worth an error box rather than a caveat."""
    narrow = solid_png(400, 300, (235, 215, 205))
    page_html = SHOT_PAGE.replace(
        SHOT_SRC["after"], f"/media/{hashlib.sha256(narrow).hexdigest()[:16]}.png"
    )
    url = serve(page_html)
    (serve.page_dir / "media").mkdir(exist_ok=True)
    (serve.page_dir / SHOT_SRC["before"].lstrip("/")).write_bytes(SHOTS["before"])
    (serve.page_dir / "media" / f"{hashlib.sha256(narrow).hexdigest()[:16]}.png").write_bytes(narrow)

    assert [f for f in interact.render_version(browser, url) if "600px" in f and "400px" in f], (
        "the gate has to hear about a mismatch, since nobody else will"
    )


# Two ways a widget leaves words on screen that no comment can land on, written into the
# markup because the gate reads the rendered page and cannot tell who put them there — a
# page-local module is where both actually happen, and standing one up here would test the
# module loader rather than the gate. First: a heading inside a chrome-looking row, with
# nothing said about whose words it is. Second: the words declared the page's, and put
# inside a form control, where no pointer can select them however they are marked.
OUT_OF_REACH_PAGE = CARRIED_PAGE.replace(
    "<cq-option id=\"c-lax\" chosen>",
    '<cq-option id="c-lax" chosen><div class="cq-ui"><strong>Session cookies</strong>'
    "</div><button data-cq-said>Lax, host-only</button>",
)


def test_render_reports_words_a_widget_puts_out_of_reach(browser, serve):
    """The reviewer's half of the gate. A reviewer selected a draft's heading, tried to
    comment on it, and got nothing back — twice, months apart, on the same page. The
    heading was the page's word in a row its author had marked as the runtime's, and
    `.cq-ui` is a look rather than a permission, so the class alone can't be the answer:
    the declaration goes on the label (relabel), and an undeclared word under chrome is
    reported here.

    The second one no marker can fix, which is why it reads differently: a word inside a
    form control is unselectable in every engine, so a widget that reaches for <button>
    has put its label somewhere the reviewer cannot go. `offer` builds a press as a span
    for exactly this reason, and this is what says so when a widget doesn't use it."""
    assert interact.render_version(browser, serve(CARRIED_PAGE)) == [], (
        "the same page without the two mistakes has nothing to report"
    )
    found = interact.render_version(browser, serve(OUT_OF_REACH_PAGE))
    assert sorted({f.split("] ", 1)[1] for f in found}) == [
        '<cq-option id=c-lax> puts "Session cookies" under .cq-ui, where no comment '
        "can reach it",
        '<cq-option id=c-lax> says "Lax, host-only" inside a form control, where no '
        "selection can reach it",
    ], found


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
    assert CliRunner().invoke(interact.cli, ["version", "check", str(d)]).exit_code == 0

    shim = (
        Path(__file__).parent.parent
        / "plugins"
        / "colloquy"
        / "bin"
        / "colloquy"
    )
    run = subprocess.run(
        [str(shim), "version", "check", str(d), "--render"],
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
    panel_settled(page)

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
    panel_settled(page)

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
    panel_settled(page, open=False)
    page.wait_for_function(
        """(top) => Math.abs(document.getElementById('p40').getBoundingClientRect().top - top) < 2""",
        arg=mark_top,
    )
    page.mouse.move(120, 300)
    page.mouse.wheel(0, 200)
    page.wait_for_function(f"() => document.body.scrollTop > {at_mark}")

    # The resize path: narrowing onto an open panel locks, widening unlocks.
    page.locator("button[aria-expanded]").click()
    panel_settled(page)
    page.set_viewport_size({"width": 1000, "height": 600})
    page.wait_for_function(
        "() => getComputedStyle(document.body).overflowY !== 'hidden' && document.body.style.marginRight !== ''"
    )
    page.set_viewport_size({"width": 500, "height": 600})
    page.wait_for_function(
        "() => getComputedStyle(document.body).overflowY === 'hidden' && document.body.style.marginRight === ''"
    )
    page.close()


def test_covering_panel_keeps_toasts_on_screen_and_clear_of_the_footer(browser, serve):
    """A covering panel has no beside-panel space for a toast: on a viewport no
    wider than the sheet, the wide layout's panel-width offset puts the whole
    message past the left edge. The toast stays inside that sheet instead, above
    its persistent composer even when that composer grows under a live toast,
    then returns beside it at the first width where the panel stops covering."""
    page, _ = open_page(browser, serve(LONG_PAGE))
    page.set_viewport_size({"width": 320, "height": 600})
    page.locator("button[aria-expanded]").click()
    page.locator(".cq-general textarea").fill("The unsent comment stays here.")

    message = (
        "Couldn't send this detailed comment to Claude — the complete draft "
        "is still here and ready to retry."
    )
    page.evaluate(
        """async message => {
            const {toast} = await import("/colloquy.js");
            toast(message);
        }""",
        message,
    )
    expect(page.locator(".cq-toast")).to_have_text(message)

    def geometry():
        return page.evaluate("""() => {
            const rect = selector => {
                const r = document.querySelector(selector).getBoundingClientRect();
                return {left: r.left, top: r.top, right: r.right, bottom: r.bottom};
            };
            return {
                width: innerWidth,
                height: innerHeight,
                panel: rect(".cq-panel"),
                footer: rect(".cq-general"),
                toast: rect(".cq-toast"),
            };
        }""")

    narrow = geometry()
    assert narrow["toast"]["left"] >= 17 and narrow["toast"]["right"] <= narrow["width"] - 17, (
        f"the toast left the covering viewport: {narrow}"
    )
    assert narrow["toast"]["bottom"] <= narrow["footer"]["top"] - 17, (
        f"the toast covered the panel's persistent composer: {narrow}"
    )

    page.set_viewport_size({"width": 721, "height": 600})
    page.wait_for_function("""() => {
        const toast = document.querySelector(".cq-toast").getBoundingClientRect();
        const panel = document.querySelector(".cq-panel").getBoundingClientRect();
        return Math.abs(toast.right - (panel.left - 18)) < 1
            && Math.abs(toast.bottom - (innerHeight - 18)) < 1;
    }""")

    wide = geometry()
    assert wide["toast"]["left"] >= 0, (
        f"the long toast left the viewport beside the wide panel: {wide}"
    )
    assert abs(wide["toast"]["right"] - (wide["panel"]["left"] - 18)) < 1, (
        f"the wide toast no longer sits beside the panel: {wide}"
    )
    assert abs(wide["toast"]["bottom"] - (wide["height"] - 18)) < 1, (
        f"the wide toast no longer sits in its original bottom corner: {wide}"
    )

    page.set_viewport_size({"width": 320, "height": 600})
    page.wait_for_function("""() => {
        const toast = document.querySelector(".cq-toast").getBoundingClientRect();
        const footer = document.querySelector(".cq-general").getBoundingClientRect();
        return toast.left >= 17 && toast.right <= innerWidth - 17
            && toast.bottom <= footer.top - 17;
    }""")
    before_growth = geometry()
    page.locator(".cq-general textarea").fill(
        "The whole unsent comment stays here.\n" * 4
    )
    page.wait_for_function(
        """beforeTop => {
            const toast = document.querySelector(".cq-toast").getBoundingClientRect();
            const footer = document.querySelector(".cq-general").getBoundingClientRect();
            return footer.top < beforeTop - 1
                && toast.bottom <= footer.top - 17;
        }""",
        arg=before_growth["footer"]["top"],
    )
    expanded = geometry()
    assert expanded["footer"]["top"] < before_growth["footer"]["top"] - 1, (
        f"the composer did not grow under the already-visible toast: "
        f"{before_growth=}, {expanded=}"
    )
    assert expanded["toast"]["bottom"] <= expanded["footer"]["top"] - 17, (
        f"the growing composer rose through an already-visible toast: {expanded}"
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


def test_the_runtime_does_not_replace_a_pages_keyframes(browser, serve):
    """Keyframe names ignore @scope, so the runtime's private animation must be
    globally unique enough to leave a page's own animation alone. The page coins the
    old generic name on purpose; sampling its midpoint makes a collision deterministic
    rather than asking where a running animation happened to be when the test looked."""
    page, errors = open_page(browser, serve(
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>t</title>'
        '<link rel="stylesheet" href="/theme.css"><style>'
        '@keyframes cq-pulse { from { transform: translateX(0px); } '
        'to { transform: translateX(40px); } }'
        '#page-pulse { animation: cq-pulse 10s linear infinite; }'
        '</style><script type="module" src="/colloquy.js"></script></head>'
        '<body><main><h1>t</h1><p id="page-pulse">Page-owned motion.</p></main></body></html>'
    ))
    sampled = page.evaluate("""() => {
        const pageAnimation = document.getElementById("page-pulse").getAnimations()[0];
        pageAnimation.pause();
        pageAnimation.currentTime = pageAnimation.effect.getTiming().duration / 2;
        const transform = getComputedStyle(document.getElementById("page-pulse")).transform;

        const dot = document.querySelector(".cq-dot");
        dot.classList.add("working");
        const runtimeAnimation = dot.getAnimations()[0];
        return {
            pageDistance: transform === "none" ? null : new DOMMatrix(transform).m41,
            runtimeName: runtimeAnimation?.animationName ?? null,
        };
    }""")
    assert sampled["pageDistance"] == pytest.approx(20), (
        f"the runtime replaced the page's cq-pulse keyframes: {sampled}"
    )
    assert sampled["runtimeName"] and sampled["runtimeName"] != "cq-pulse", (
        f"the chrome lost its own private pulse animation: {sampled}"
    )
    assert errors == []
    page.close()


STACKED_OPTIONS_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>stacked options</title>
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<h1 id="h">Clip storage</h1>
<cq-options id="stacked" choose>
  <cq-option id="st-sd" effort="low" risk="high">
    <strong>SD card only</strong>
    <dl class="facts"><dt>Keeps</dt><dd>nine days</dd><dt>Retrieval</dt><dd>a ladder</dd></dl>
    <p>Clips stay on the camera's card and overwrite oldest-first.</p>
  </cq-option>
  <cq-option id="st-pi" effort="med" risk="low" recommended>
    <strong>Pi in the shed</strong>
    <dl class="facts"><dt>Keeps</dt><dd>a season</dd><dt>Retrieval</dt><dd>the couch</dd></dl>
    <p>A nightly pull over the garden wifi; the link is the weak span.</p>
  </cq-option>
</cq-options>
<cq-options id="terse">
  <cq-option id="t-paper" effort="low" risk="high"><strong>Paper maps</strong> Nothing
  to charge.</cq-option>
  <cq-option id="t-gps" effort="med" risk="low"><strong>GPS</strong> A week of
  battery.</cq-option>
</cq-options>
<cq-compare id="pair">
  <cq-variant id="cv-cedar"><strong>Cedar</strong>
    <dl class="facts"><dt>Seal</dt><dd>never</dd></dl>
    <p>Weathers silver; no sealant, no schedule.</p></cq-variant>
  <cq-variant id="cv-pine"><strong>Pine</strong>
    <dl class="facts"><dt>Seal</dt><dd>yearly</dd></dl>
    <p>Cheaper up front; seal it every autumn.</p></cq-variant>
</cq-compare>
</main>
</body>
</html>
"""


def test_substantial_options_stack_and_align_their_facts(browser, serve):
    """Layout follows substance: an option carrying block content turns its group
    into full-width rows — the grid's ~13rem cards were a shape for labels, and a
    page whose options held real argument grew a comparison table and an "in
    detail" section outside the widget it decides in. The rows keep the
    comparison inside the group: every option's `.facts` list docks right at one
    fixed width, so scalars align down the page like that table's column, and the
    chips join the title line (the risk chip measures its offset from the effort
    chip's edge — anchor positioning — rather than guessing a width). A terse
    group on the same page keeps the grid."""
    page, errors = open_page(browser, serve(STACKED_OPTIONS_PAGE))
    assert errors == []

    sd = page.locator("#st-sd").bounding_box()
    pi = page.locator("#st-pi").bounding_box()
    group = page.locator("#stacked").bounding_box()
    assert sd["y"] + sd["height"] <= pi["y"], "substantial options must stack"
    assert sd["width"] > group["width"] * 0.95, "a stacked option takes the whole column"

    rails = [page.locator(f"#{i} > dl.facts").bounding_box() for i in ("st-sd", "st-pi")]
    for rail, card in zip(rails, (sd, pi)):
        assert rail["x"] > card["x"] + card["width"] / 2, "the facts rail docks right"
    assert abs(rails[0]["x"] - rails[1]["x"]) < 1, "rails align down the group"

    title = page.locator("#st-sd > strong").bounding_box()
    effort = page.locator('#st-sd > [data-cq-said="effort"]').bounding_box()
    risk = page.locator('#st-sd > [data-cq-said="risk"]').bounding_box()
    for chip in (effort, risk):
        # Within the title's own band — the corner placement (a 40px header strip
        # above the title) sits ~26px higher and fails this.
        assert abs(chip["y"] - title["y"]) < 8, "chips ride the title line"
    assert risk["x"] + risk["width"] <= effort["x"], "the chip pair must not overlap"

    paper = page.locator("#t-paper").bounding_box()
    gps = page.locator("#t-gps").bounding_box()
    assert abs(paper["y"] - gps["y"]) < 1, "terse options keep the grid row"
    assert paper["x"] + paper["width"] <= gps["x"], "terse options sit side by side"

    # cq-compare is the same shape without the decision, and follows it.
    cedar = page.locator("#cv-cedar").bounding_box()
    pine = page.locator("#cv-pine").bounding_box()
    assert cedar["y"] + cedar["height"] <= pine["y"], "substantial variants stack too"
    rail = page.locator("#cv-cedar > dl.facts").bounding_box()
    assert rail["x"] > cedar["x"] + cedar["width"] / 2, "a variant's facts dock right"
    page.close()


def test_settled_options_collapse_without_going_out_of_reach(browser, serve):
    """A settled decision reads as one line and the cards behind it stop spending
    the page's height — but they are hidden, not gone, so everything that used to
    reach them still does: the disclosure opens them, and a comment anchored in
    one opens the group on its way to the passage. A collapse a comment can't see
    through is worse than no collapse at all, because the thread still lists the
    quote and clicking it lands nowhere.

    The line itself is in reach too, which is the harder half: while the group is
    collapsed it is the only place the decision is stated, and it is written into a
    disclosure — chrome, and a control. And naming the card there means the page now
    says the card's lede twice, so the third part asks the one thing that buys: a
    comment made on the card lands on the card."""
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

    # While it is closed the row is the decision's only visible statement, so the part of
    # it naming the card has to be quotable — and a drag across it must not toggle the
    # disclosure it lives in, which is the mouseup of that drag.
    title = page.locator("#transport .cq-settled [data-cq-said]")
    box = title.bounding_box()
    y = box["y"] + box["height"] / 2
    page.mouse.move(box["x"] + 2, y)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] - 2, y, steps=8)
    page.mouse.up()
    assert page.evaluate("() => getSelection().toString()").strip() == "Settled: Lax cookie"
    expect(page.locator("#opt-strict")).to_be_hidden()
    page.locator(".cq-fab").click()
    expect(page.locator(".cq-composer")).to_be_visible()
    assert composer_quote(page)["text"].strip("“”") == "Settled: Lax cookie"
    page.keyboard.press("Escape")

    # The row names the chosen card, so the page now says "Lax cookie" twice and both
    # copies are quotable. A comment on the card's own lede has to land on the card —
    # the row comes first in document order, which is where a search on the quote alone
    # would put it.
    #
    # Dropping the selection first is the reviewer's own next move: a press that lands
    # inside a live selection is that selection's, so the row would not open under it.
    page.locator("#lede").click()
    row.click()
    expect(page.locator("#opt-lax")).to_be_visible()  # until-found keeps a box either way
    lede = page.locator("#opt-lax > strong")
    box = lede.bounding_box()
    y = box["y"] + box["height"] / 2
    page.mouse.move(box["x"] + 2, y)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] - 2, y, steps=8)
    page.mouse.up()
    page.locator(".cq-fab").click()
    expect(page.locator(".cq-composer")).to_be_visible()
    page.locator(".cq-composer textarea").fill("which copy is this on?")
    page.get_by_role("button", name="Comment", exact=True).click()
    # Two, not one: this page arrived carrying a mark, so waiting for any at all is a
    # wait that was over before the gesture started.
    page.wait_for_function("() => (CSS.highlights.get('cq-mark')?.size ?? 0) >= 2")
    # Both marks on the page: the one this fixture arrived carrying, and the new one.
    assert sorted(page.evaluate(
        "() => [...CSS.highlights.get('cq-mark')].map(r => "
        "r.startContainer.parentElement.closest('[id]').id)"
    )) == ["opt-lax", "opt-strict"], (
        "the comment landed on the summary line rather than the card it was made on"
    )
    row.click()  # closed again, so the reveal below has something to open

    # Sending opened the panel, so the thread is already listed. Its quote is on a card
    # the collapse is hiding, and following it has to bring the card back.
    page.locator(".cq-panel .cq-quote", has_text="arrives logged out").click()
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
    press where there is a pick to make, an inert span where there isn't — and the
    inert one wore the press's `.cq-ui`, which anchoring skipped, so a reviewer
    could read "chosen" and not point at it. Every shipped example declares
    `choose`, so the render suite never rendered the inert shape and nothing said
    so. The press was out of reach for longer and for a different reason, which
    test_a_pick_offered_can_be_pointed_at_too covers.

    Quotable is half a pair, so the other half is here too: the diff parses the
    base version unupgraded, where no mark exists at all, and must not read this
    one as a change nobody wrote."""
    url = serve(CARRIED_PAGE)
    assert interact.render_version(browser, url) == []

    page, errors = open_page(browser, url)
    mark = page.locator("#c-lax .cq-pick")
    assert mark.get_attribute("role") is None, "nothing to press means no button role"
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


def test_a_pick_offered_can_be_pointed_at_too(browser, serve):
    """The same words on the other shape of mark, in a group that takes a pick. This
    one was out of reach for a reason no marker could fix: the mark was a <button>,
    and no engine starts a pointer selection inside a form control, so "chosen" was on
    screen and unselectable however it was declared. A press is a span wearing the role
    now, which is what makes the drag below possible at all.

    Two things then have to hold at once. The drag has to select rather than pick — its
    mouseup lands on the very control it crossed — and the mark has to stay pressable,
    or the fix has traded a word nobody can quote for a decision nobody can make."""
    page, errors = open_page(browser, serve(SETTLED_PAGE))
    page.locator("#transport .cq-settled").click()  # open the group; the cards are hidden
    mark = page.locator("#opt-lax .cq-pick")
    expect(mark).to_have_text("chosen")

    # Where the theme puts it: one line along the card's own bottom edge, the same box
    # whichever word it carries, so a pick shifts nothing. Pinned because the mark now
    # declares itself the page speaking, and the marker it declares with is the one the
    # theme's effort/risk chips are selected by — matched bare, the mark came out a pill
    # in the card's top corner and every assertion here still passed.
    seat = """el => { const r = el.getBoundingClientRect();
                      const card = el.closest('cq-option').getBoundingClientRect();
                      return [Math.round(r.height), Math.round(card.bottom - r.bottom),
                              Math.round(r.left - card.left)]; }"""
    assert mark.evaluate(seat) == page.locator("#opt-strict .cq-pick").evaluate(seat)
    height, up, over = mark.evaluate(seat)
    assert height < 24 and up < 16 and over < 20, (
        f"the mark is not a one-line caption on the card's bottom-left: {mark.evaluate(seat)}"
    )

    box = mark.bounding_box()
    y = box["y"] + box["height"] / 2
    page.mouse.move(box["x"] + box["width"] - 2, y)  # right to left: the ✓ ring is not text
    page.mouse.down()
    page.mouse.move(box["x"] + 2, y, steps=8)
    page.mouse.up()
    assert page.evaluate("() => getSelection().toString()").strip() == "chosen"
    expect(page.locator("#transport > cq-option[chosen]")).to_have_count(1)
    page.locator(".cq-fab").click()
    expect(page.locator(".cq-composer")).to_be_visible()
    assert composer_quote(page)["text"].strip("“”") == "chosen"
    page.keyboard.press("Escape")

    # Still a control: clicking the card that holds the pick clears it, and the keyboard
    # reaches the mark and works it the way the <button> did.
    page.evaluate("() => getSelection().removeAllRanges()")
    page.locator("#opt-strict").click()
    expect(page.locator("#opt-strict[chosen]")).to_have_count(1)
    page.locator("#opt-bearer .cq-pick").focus()
    page.keyboard.press("Enter")
    expect(page.locator("#opt-bearer[chosen]")).to_have_count(1)

    # And the pair the quotable half always comes with. This mark is the one element on
    # any page wearing the chrome class and the page-speaking marker at once, so it is the
    # only case where the anchor pass's reading and the diff's can come apart: the base
    # version is parsed unupgraded and has no mark in it at all. Read as text, the card
    # carrying the pick lights up as changed on every revision.
    #
    # v2 rewords a third card, so the card the diff should mark and the card wearing the
    # mark are different ones — with the pick on the reworded card there is nothing to
    # see, which is how this passed while reading the mark as text.
    d = serve.page_dir
    (d / "versions" / "v2.html").write_text(
        SETTLED_PAGE.replace("arrives logged out", "arrives logged out every time")
    )
    interact.append_event(d, {"kind": "note", "author": "claude", "version": 2, "text": "two"})
    page.wait_for_url("**/v2.html", timeout=10_000)
    expect(page.locator("#opt-bearer[chosen]")).to_have_count(1)  # replay carried the pick
    page.locator(".cq-banner button", has_text="Δ").click()
    page.wait_for_function("() => document.querySelectorAll('.cq-ins-block').length > 0")
    assert page.evaluate(
        "() => [...document.querySelectorAll('.cq-ins-block')].map(e => e.id)"
    ) == ["opt-strict"], "the diff read a pick mark as text the base version lacked"
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

    # …but takes nothing back. Nothing pressable: no grips, and no mark wearing
    # the button role — an unpicked quoted card carries no mark at all, exactly as
    # a group that never declared `choose`. A click chooses nothing either (the
    # choose path sets `chosen` before it sends, so a pick would show here).
    assert page.locator('#quoted-group .cq-pick[role="button"]').count() == 0
    assert page.locator("#quoted-board .cq-grip").count() == 0
    # Nor a box for words: an exhibited question takes no answer of either kind, and
    # a box is the one that would have looked answerable.
    assert page.locator("#quoted-group .cq-say").count() == 0
    page.locator("#q-shim").click()
    assert page.locator("#quoted-group cq-option[chosen]").count() == 0

    # The document's own state still reads: the settled group's authored pick
    # wears its mark, with nothing to press.
    assert page.locator("#quoted-settled .cq-pick:not([role])").count() == 1

    # A quoted suggestion shows what a pending change looks like — both slots
    # marked — and grows nothing to settle it with, so it is also not the
    # banner's to count or Accept all's to decide.
    assert page.locator("#quoted-suggestion cq-old").is_visible()
    assert page.locator("[data-cq-for='quoted-suggestion']").count() == 0
    expect(page.get_by_role("button", name="Accept all (1)")).to_be_visible()

    # The control: the same markup unquoted wires all of it.
    assert page.locator('#live-group .cq-pick[role="button"]').count() == 2
    assert page.locator("#live-board .cq-grip").count() == 1
    assert page.locator("[data-cq-for='live-suggestion']").count() == 1

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


# The other form of a question, on one page beside the first: options that are bare
# labels, naming the blocks of the page they are about, and a group taking more than one.
ASK_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>ask</title>
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<h1 id="h">Three jobs</h1>
<cq-options id="jobs" choose multiple>
  <cq-option id="job-mounts" for="sec-mounts">Replace the mounts</cq-option>
  <cq-option id="job-heater" for="sec-heater">Heat the bird bath</cq-option>
  <cq-option id="job-camera">Neither — the camera first</cq-option>
</cq-options>
<section id="sec-mounts"><h2>The mounts</h2><p id="mounts-p">Plastic, and one came
down in January.</p></section>
<section id="sec-heater"><h2>The bird bath</h2><p id="heater-p">Frozen eleven
mornings last winter.</p></section>
<cq-options id="bracket" choose>
  <cq-option id="br-steel"><strong>Steel</strong> Galvanised, drop-in.</cq-option>
  <cq-option id="br-cedar"><strong>Cedar</strong> Cheap; needs sealing.</cq-option>
</cq-options>
</main>
</body>
</html>
"""


def sent_events(page_dir):
    return [
        json.loads(line) for line in (page_dir / "comments.jsonl").read_text().splitlines()
    ]


def test_a_group_of_bare_labels_reads_as_a_question_about_the_page(browser, serve):
    """Which form a group takes is a fact about its options rather than an attribute
    saying so, and the whole of that fact is whether an option leads with a title. So
    one page carries both and neither knows about the other: the labels lay out as rows
    and the titled pair as a grid.

    Two things the lint cannot see. A row's mark shows its dot and not its word, because
    "choose" on every line of a list is the affordance said once per row where the dots
    have already said it together — and what a *picked* mark says has to survive that,
    since it is the page's only statement of where the pick sits. And a row's name is
    what the author wrote in it: the mark that lands inside the row once it is picked is
    the page speaking (`says`) and must stay out of the row's own name (`wrote`), or a
    question answered reads its answer back as part of what was asked."""
    page, errors = open_page(browser, serve(ASK_PAGE))
    assert errors == []

    assert page.locator("#jobs").evaluate("el => getComputedStyle(el).display") == "block"
    assert page.locator("#bracket").evaluate("el => getComputedStyle(el).display") == "grid"

    # The block a row is about, reachable as a link and written as the id it names —
    # the same way the comment panel writes an element anchor.
    ref = page.locator("#job-mounts .cq-ref")
    expect(ref).to_have_text("§ sec-mounts")
    assert ref.get_attribute("href") == "#sec-mounts"
    assert page.locator("#job-camera .cq-ref").count() == 0

    # An open row's word is off the screen; a card's is not, which is the contrast that
    # says the row form decided this and not the theme forgetting a rule.
    hidden = "el => getComputedStyle(el).fontSize"
    assert page.locator("#job-mounts .cq-pick").evaluate(hidden) == "0px"
    assert page.locator("#br-steel .cq-pick").evaluate(hidden) != "0px"

    page.locator("#job-heater").click()
    expect(page.locator("#job-heater[chosen]")).to_have_count(1)
    expect(page.locator("#job-heater .cq-pick")).to_have_text("your pick")
    assert page.locator("#job-heater .cq-pick").evaluate(hidden) != "0px"
    # The row's name, as the mark reports it back: what the author wrote, and not the
    # word the mark itself just added to the line.
    assert (
        page.locator("#job-heater .cq-pick").get_attribute("aria-label")
        == "your pick: Heat the bird bath"
    )
    page.close()


def test_a_pick_states_the_whole_set(browser, serve):
    """`multiple` is the difference between "which of these" and "which one", and the
    action is the same shape either way: every picked option, absolutely, so replay is
    idempotent and a second tab converges rather than drifting. Without `multiple` the
    set a click toggles from is empty, which is what makes a pick replace instead of
    join — one rule, not two code paths."""
    page, errors = open_page(browser, serve(ASK_PAGE))

    page.locator("#job-mounts").click()
    expect(page.locator("#jobs > cq-option[chosen]")).to_have_count(1)
    page.locator("#job-camera").click()
    expect(page.locator("#jobs > cq-option[chosen]")).to_have_count(2)
    page.locator("#job-mounts").click()
    expect(page.locator("#jobs > cq-option[chosen]")).to_have_count(1)

    # The single-pick group beside it replaces rather than joining, and clicking the
    # pick again empties it.
    page.locator("#br-steel").click()
    expect(page.locator("#bracket > cq-option[chosen]")).to_have_count(1)
    page.locator("#br-cedar").click()
    expect(page.locator("#br-cedar[chosen]")).to_have_count(1)
    expect(page.locator("#br-steel[chosen]")).to_have_count(0)
    page.locator("#br-cedar").click()
    expect(page.locator("#bracket > cq-option[chosen]")).to_have_count(0)

    picks = [(e["widget"], e["detail"]) for e in sent_events(serve.page_dir)
             if e.get("action") == "choose"]
    assert picks == [
        ("jobs", {"options": ["job-mounts"]}),
        ("jobs", {"options": ["job-mounts", "job-camera"]}),
        ("jobs", {"options": ["job-camera"]}),
        ("bracket", {"options": ["br-steel"]}),
        ("bracket", {"options": ["br-cedar"]}),
        ("bracket", {"options": []}),
    ]
    assert errors == []
    page.close()


def test_the_box_for_words_reaches_the_log_as_a_comment_on_the_question(browser, serve):
    """A question can always be answered off its own menu, and without a box that answer
    costs the reader a hunt for some passage to select. What they type is an ordinary
    comment anchored on the group — one store, and everything the comment layer already
    guarantees — so the assertion is where the words land and what the page does after:
    the box empties, and the group wears the mark that says a comment is on it.

    It rides `wireInput` like every other composer, so the send button states whether
    there is anything to send — through aria-disabled, since a widget's press is a span
    and has no `disabled` to set. That one is invisible until it is wrong: the button
    looked live while the guard behind it refused."""
    page, errors = open_page(browser, serve(ASK_PAGE))

    box = page.locator("#jobs .cq-say textarea")
    send = page.locator("#jobs .cq-say [role='button']")
    assert send.get_attribute("aria-disabled") == "true"
    box.fill("Neither, really — do the camera and tell me what it costs.")
    assert send.get_attribute("aria-disabled") == "false"
    send.click()

    expect(page.locator("#jobs.cq-mark-el")).to_have_count(1)
    expect(box).to_have_value("")
    assert send.get_attribute("aria-disabled") == "true"

    said = [e for e in sent_events(serve.page_dir) if e["kind"] == "comment"]
    assert [(e["anchor"], e["text"]) for e in said] == [
        ({"section": "jobs"}, "Neither, really — do the camera and tell me what it costs.")
    ]
    assert errors == []
    page.close()


SETTLED_ASK_PAGE = ASK_PAGE.replace(
    '<cq-options id="jobs" choose multiple>', '<cq-options id="jobs" choose multiple settled>'
)


def test_the_box_is_offered_only_where_something_can_answer_it(browser, serve):
    """A textarea and a Send button with no handler behind them invite the reader to
    type into a page that cannot send it, which is the worst of the three media to be
    wrong in — it looks live. So the box is withheld rather than undone: the offer is
    made once in the live page, and a copy, a printout and a retired question each get
    the page without it by never being handed it.

    The collapse is the same rule at a different scale. A settled group's box goes
    behind the disclosure with its options, because the question is retired until the
    reader opens it again — and `display: flex` on the class would otherwise outrank
    the hidden attribute and leave a box floating under a collapsed group."""
    page, errors = open_page(browser, serve(SETTLED_ASK_PAGE))
    assert errors == []

    box = page.locator("#jobs .cq-say")
    expect(box).to_be_hidden()
    page.locator("#jobs .cq-settled").click()
    expect(box).to_be_visible()

    # The copy medium: the same DOM with the affordance never handed to it.
    page.evaluate("() => document.documentElement.classList.add('cq-copy')")
    expect(box).to_be_hidden()
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
    page.wait_for_selector('#rp-live .cq-pick[role="button"]')  # the reply's widgets upgraded
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
    assert page.locator('#rp-quoted .cq-pick[role="button"]').count() == 0
    page.locator("#rp-memory").click()
    page.locator("#rp-stage").click()

    deadline = time.time() + 5
    while time.time() < deadline:
        actions = [e for e in interact.read_events(d) if e["kind"] == "action"]
        if actions:
            break

    assert [(e["widget"], e["detail"]) for e in actions] == [("rp-live", {"options": ["rp-stage"]})]
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
    whichever path forgets to restate its location or durable pending state."""
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
    expect(
        board.get_by_role(
            "button",
            name="Move: Squirrel baffle — Done — awaiting next version",
            exact=True,
        )
    ).to_be_visible()

    assert board.aria_snapshot() == (
        '- list "Todo":\n'
        "  - listitem:\n"
        "    - strong: Heated perch\n"
        "    - 'button \"Move: Heated perch — Todo\"': ⠿\n"
        '- list "Done":\n'
        "  - listitem:\n"
        "    - strong: Squirrel baffle\n"
        "    - 'button \"Move: Squirrel baffle — Done — awaiting next version\"': ⠿"
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
# its own contents — the case where `left: 100%` resolves against the card rather
# than the column, and drops the controls back into the text, unless the row is
# the column's own child.
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
    and reads as it will once the change is settled. The row is the column's own
    child and takes its line from an anchor inside the change, so how deep the
    change sits costs it nothing: one inside a card — a positioned ancestor, which
    `left: 100%` used to resolve against, dropping the row back into the text —
    hangs in the rail beside its card like any other. What is left is a
    measurement no lint can make: a window with no margin to hold the row docks it
    into flow, under the block it decides rather than overlapping the page.

    The margin the row hangs in is reserved, not left over, and the posture that
    proves it is the one a reviewer reads in: with the comment panel open, a
    centred column left too little beside it and every row docked — above the
    change it decides, which reads as the paragraph before's."""
    page, errors = open_page(browser, serve(SUGGESTION_PAGE))
    assert errors == []
    column = page.locator("main").evaluate("el => el.getBoundingClientRect().right")
    room = page.evaluate("() => document.body.getBoundingClientRect().right")
    box = "el => el.getBoundingClientRect()"

    margin_rows = page.locator("[data-cq-for='sug-refill'], [data-cq-for='sug-thistle']")
    assert margin_rows.count() == 2
    for i in range(2):
        assert margin_rows.nth(i).evaluate(box)["left"] > column, (
            "a control row overlapping the column re-wraps the prose it reviews"
        )
    # Two changes a line apart, so the rows would collide at their natural offsets.
    first, second = (margin_rows.nth(i).evaluate(box) for i in range(2))
    assert first["bottom"] <= second["top"], "control rows must not stack on each other"

    # The card is positioned and the change is three elements down inside it, and
    # the row still hangs in the rail on the line that change starts — which is
    # what the anchor buys, and what a static position never could.
    in_card = page.locator("[data-cq-for='sug-in-card']").evaluate(box)
    assert in_card["left"] > column and in_card["right"] <= room, (
        "a change inside a widget is still a change the reviewer decides in the margin"
    )
    assert abs(in_card["top"] - page.locator("#sug-in-card cq-old").evaluate(box)["top"]) <= 4, (
        "the row must hang on the change's own line, not on the block it follows"
    )

    # The panel takes the right of the window, and the rail survives it: the rows
    # keep their line, clear of the column on one side and of the panel on the
    # other. Measured after the layout has moved, since opening the panel resizes
    # the page and the rows re-place on the frame after that.
    page.get_by_role("button", name="Comments", exact=False).click()
    panel_settled(page)
    page.wait_for_function(
        "() => [...document.querySelectorAll("
        "'[data-cq-for=sug-refill], [data-cq-for=sug-thistle]')]"
        ".every(r => !r.classList.contains('cq-docked'))"
    )
    narrowed = page.locator("main").evaluate("el => el.getBoundingClientRect().right")
    room = page.evaluate("() => document.body.getBoundingClientRect().right")
    for i in range(2):
        rect = margin_rows.nth(i).evaluate(box)
        assert rect["left"] > narrowed and rect["right"] <= room, (
            "with the panel open the row must still hang between column and panel"
        )

    # No margin anywhere: every row docks, and nothing spills sideways. Docked is
    # the same box in flow where the row was hoisted to, so it reads as a control
    # line under the block holding the change and never as the one before's.
    page.get_by_role("button", name="Close comments").click()
    page.set_viewport_size({"width": 820, "height": 900})
    page.wait_for_function(
        "() => [...document.querySelectorAll('.cq-sug-actions')]"
        ".every(r => r.classList.contains('cq-docked'))"
    )
    assert page.evaluate("() => document.body.scrollWidth <= document.body.clientWidth")
    for widget, block in [("sug-refill", "#replace"), ("sug-in-card", "#feeders")]:
        assert (
            page.locator(f"[data-cq-for='{widget}']").evaluate(box)["top"]
            >= page.locator(block).evaluate(box)["bottom"]
        ), "a docked row belongs under the block whose change it decides"
    page.close()


def test_a_moved_change_takes_its_controls_with_it(browser, serve):
    """The row is the column's child, not the change's, so the subtree a card
    travels in no longer carries it: a card dragged to another column, or moved by
    the replay of someone else's drag, leaves and re-enters the document with its
    row unhooked. Re-connection has to hang it again, or the reviewer loses the
    only way to decide a change that is still plainly pending on the page. Replayed
    rather than dragged, because that is the same move with no gesture in the way."""
    url = serve(SUGGESTION_PAGE)
    interact.append_event(serve.page_dir, {
        "kind": "action", "author": "user", "version": 1, "widget": "feeders",
        "action": "move", "detail": {"card": "card-heater", "to": "col-done", "index": 0},
    })
    page, errors = open_page(browser, url)
    expect(page.locator("#col-done #card-heater")).to_be_visible()
    box = "el => el.getBoundingClientRect()"
    row = page.locator("[data-cq-for='sug-in-card']")
    expect(row).to_be_visible()
    change = page.locator("#sug-in-card cq-old").evaluate(box)
    assert abs(row.evaluate(box)["top"] - change["top"]) <= 4, (
        "the row must find the moved change's line again, not the one it left"
    )
    row.locator(".cq-sug-accept").click()
    expect(page.locator("#sug-in-card cq-old")).to_be_hidden()
    assert errors == []
    page.close()


# A change the reader hasn't opened yet. The row hangs off an anchor in the
# change, and a collapsed container reports its content's last rendered geometry
# rather than nothing at all — so a row that trusted a measurement would hang in
# the margin deciding a change nobody can see.
COLLAPSED_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>collapsed</title>
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<h1 id="h">Winter</h1>
<p id="stocked">The feeders are stocked.
  <cq-suggestion id="sug-now">
    <cq-new>Thistle goes out in October.</cq-new>
  </cq-suggestion></p>
<details id="later"><summary id="sum">Deferred</summary>
<p id="deferred">Nest boxes wait for spring.
  <cq-suggestion id="sug-boxes">
    <cq-new>Order them in February.</cq-new>
  </cq-suggestion></p>
</details>
</main>
</body>
</html>
"""


def test_a_row_waits_for_the_change_it_decides_to_be_on_screen(browser, serve):
    """A change inside a collapsed container has no line for its row to hang on,
    and an anchor that isn't rendered is no anchor at all: the row falls back to
    the block it was hoisted to and hangs there in the margin, offering to decide
    something the reader can't see. It waits instead, and arrives on the change's
    own line the moment the container opens — a real click on the summary, because
    opening it is the reader's gesture and the reflow it causes is the point."""
    page, errors = open_page(browser, serve(COLLAPSED_PAGE))
    waiting = page.locator("[data-cq-for='sug-boxes']")
    expect(page.locator("[data-cq-for='sug-now']")).to_be_visible()
    expect(waiting).to_be_hidden()

    page.locator("#sum").click()
    expect(waiting).to_be_visible()
    box = "el => el.getBoundingClientRect()"
    row = waiting.evaluate(box)
    assert row["left"] > page.locator("main").evaluate(box)["right"], (
        "the row must arrive in the margin, not over the prose that just opened"
    )
    assert abs(row["top"] - page.locator("#sug-boxes cq-new").evaluate(box)["top"]) <= 4, (
        "and on the line of the change it decides"
    )
    assert errors == []
    page.close()


def test_the_rail_survives_every_script_being_removed(browser, serve, tmp_path):
    """A standalone copy of a colloquy page is its rendered DOM with the script tags
    dropped, and the pass that placed these rows is script. It doesn't have to run
    again: the row is a child of <main> in the serialized markup, and `left: 100%`
    against the column with `top: anchor(top)` against the change re-solve wherever
    the copy is opened and at whatever width. Including the change inside the card,
    whose positioned ancestor is exactly what a placement done in script would have
    had to correct for — and could not, with no script left to run."""
    page, _ = open_page(browser, serve(SUGGESTION_PAGE))
    page.evaluate("() => document.querySelectorAll('script').forEach(s => s.remove())")
    baked = page.evaluate("() => document.documentElement.outerHTML").replace(
        '<link rel="stylesheet" href="/theme.css">',
        "<style>" + (serve.page_dir / "theme.css").read_text() + "</style>",
    )
    page.close()

    standalone = tmp_path / "standalone.html"
    standalone.write_text(baked)
    loose = browser.new_page(viewport={"width": 1500, "height": 900})
    loose.goto(standalone.as_uri(), wait_until="load")
    assert loose.evaluate("document.querySelectorAll('script').length") == 0
    box = "el => el.getBoundingClientRect()"
    column = loose.locator("main").evaluate(box)["right"]
    for widget in ("sug-refill", "sug-in-card"):
        row = loose.locator(f"[data-cq-for='{widget}']").evaluate(box)
        assert row["left"] > column, f"{widget}'s row lost the rail without its script"
        assert abs(row["top"] - loose.locator(f"#{widget} cq-old").evaluate(box)["top"]) <= 4, (
            f"{widget}'s row lost its change's line without its script"
        )
    loose.close()


def test_accepting_a_suggestion_settles_it_and_reaches_claude(browser, serve):
    """Accepting collapses the change to the proposal as ordinary prose — no
    tint, no strike, no leftover chrome — because the live view is the version
    plus the reviewer's actions, and the honoring version only has to catch up.
    The outcome has to reach the log too: what the reviewer sees settle and what
    Claude is told must be the same event."""
    page, errors = open_page(browser, serve(SUGGESTION_PAGE))
    accept = page.locator("[data-cq-for='sug-refill'] .cq-sug-accept")
    assert accept.get_attribute("aria-label").startswith(
        "Accept the suggested change: Refill a feeder when"
    ), "the button names the proposal, not the text being replaced"

    accept.click()
    expect(page.locator("#sug-refill cq-old")).to_be_hidden()
    expect(page.locator("#sug-refill cq-new")).to_be_visible()
    expect(page.locator("[data-cq-for='sug-refill']")).to_be_hidden()
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
    page.locator(f"[data-cq-for='sug'] .cq-sug-{outcome}").click()
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
        expect(page.locator(f"[data-cq-for='{widget}']")).to_be_hidden()
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
    page.locator("[data-cq-for='sug-refill'] .cq-sug-accept").click()

    expect(page.locator("#sug-refill cq-old")).to_be_visible()
    expect(page.locator("[data-cq-for='sug-refill']")).to_be_visible()
    assert page.locator("#sug-refill").get_attribute("data-cq-state") is None
    # And the page's own count is derived from that, so it comes back too.
    expect(page.get_by_role("button", name="Accept all (3)")).to_be_visible()
    expect(page.locator(".cq-toast")).to_contain_text("Couldn't send")
    assert [e for e in interact.read_events(serve.page_dir) if e["kind"] == "action"] == []

    # The retry is a second click, not a reload: the widget is pending again.
    page.unroute("**/api/event")
    page.locator("[data-cq-for='sug-refill'] .cq-sug-accept").click()
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

    first.locator("[data-cq-for='sug-refill'] .cq-sug-accept").click()
    expect(second.locator("#sug-refill cq-old")).to_be_hidden()
    expect(second.locator("#sug-refill cq-new")).to_be_visible()
    expect(second.locator("[data-cq-for='sug-refill']")).to_be_hidden()  # nothing left to decide
    expect(second.get_by_role("button", name="Accept all (2)")).to_be_visible()

    # Now the race the controls make possible: a window cut off from the log still
    # shows both buttons, so the reviewer can decide the other way there. Two
    # decisions on one change, and the log's order — not either tab's belief —
    # settles it for both once the cut-off one catches up.
    third, third_errors = open_page(browser, url)
    third.route("**/api/state", lambda route: route.abort())
    first.locator("[data-cq-for='sug-thistle'] .cq-sug-accept").click()
    # In the log before the reject is clicked, so which one is later is this test's
    # to decide rather than the network's.
    expect(second.get_by_role("button", name="Accept all (1)")).to_be_visible()
    third.locator("[data-cq-for='sug-thistle'] .cq-sug-reject").click()
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
        ("approach", "choose", {"options": ["opt-shim"]}),
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


def test_replay_signatures_distinguish_widget_state_from_runtime_paint(browser, serve):
    """A widget may use the runtime's namespace for state without making that state
    runtime paint. Replaying a suggestion changes only data-cq-state on its authored
    element, so the replay record must name it; data-cq-pending on the same element is
    the runtime's own annotation and must not change the signature."""
    url = serve(SUGGESTION_PAGE)
    interact.append_event(
        serve.page_dir,
        {
            "kind": "action",
            "author": "user",
            "version": 1,
            "widget": "sug-refill",
            "action": "accept",
            "detail": {},
        },
    )
    page, errors = open_page(browser, url)
    expect(page.locator("#sug-refill")).to_have_attribute("data-cq-state", "accept")
    page.wait_for_function(
        "() => (document.body.dataset.cqReplayWrote ?? '').split(' ').includes('sug-refill')"
    )

    signatures = page.evaluate("""async () => {
        const { shallowSigs } = await import("/colloquy.js");
        const widget = document.getElementById("sug-refill");
        const read = () => shallowSigs(document.body).get(widget.id);
        const decided = read();
        widget.setAttribute("data-cq-pending", "probe");
        const painted = read();
        widget.removeAttribute("data-cq-state");
        const undecided = read();
        return { decided, painted, undecided };
    }""")
    assert signatures["decided"] == signatures["painted"], (
        "runtime-owned pending paint became authored state in the replay signature"
    )
    assert signatures["decided"] != signatures["undecided"], (
        "widget-owned data-cq-state disappeared with the runtime's private attributes"
    )
    assert errors == []
    page.close()


def test_a_moved_card_wears_its_pending_state_until_honored(browser, serve):
    """A move outlives its toast: the card the reviewer moved stays visibly
    marked as recorded-but-unwritten and its grip says so, in the tab that moved
    it and in a fresh replay alike, because the runtime compares the page's state
    against the version's own snapshot rather than remembering who wrote what.
    The card the move displaced stays unmarked — the log named one card, not its
    neighbours. The honoring version says the state itself, so on it the
    disagreement and both renderings are gone."""
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
    expect(
        page.get_by_role(
            "button",
            name="Move: Wire the importer — Done — awaiting next version",
            exact=True,
        )
    ).to_be_visible()

    # A fresh tab reads the same fact from replay alone, and paints both its
    # visible outline and its durable spoken state.
    second, second_errors = open_page(browser, url)
    expect(second.locator("#card-importer")).to_have_attribute("data-cq-pending", "1")
    expect(
        second.get_by_role(
            "button",
            name="Move: Wire the importer — Done — awaiting next version",
            exact=True,
        )
    ).to_be_visible()
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
    expect(
        third.get_by_role(
            "button", name="Move: Wire the importer — Done", exact=True
        )
    ).to_be_visible()

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

    page.locator("[data-cq-for='sug-refill'] .cq-sug-reject").click()
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


# A suggestion whose losing slot holds a widget. cq-old takes prose, and prose takes
# widgets, so the mark on a chosen option can sit inside the half a decision removes.
# `choose`, because that is the shape that bites: a group offering a pick renders the
# mark as a press, which wears the chrome class *and* declares its word the page's.
RETIRED_WIDGET_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>retired</title>
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<h1 id="h">Session transport</h1>
<p id="lede">Replacing the whole decision block below.</p>
<cq-suggestion id="sug-swap">
  <cq-old id="was">
    <cq-options id="old-group" choose>
      <cq-option id="old-lax" chosen><strong>Lax cookie</strong> The way it stands.</cq-option>
    </cq-options>
  </cq-old>
  <cq-new id="now"><p id="p-now">A bearer header, settled elsewhere.</p></cq-new>
</cq-suggestion>
</main>
</body>
</html>
"""


def test_a_label_in_a_retired_slot_leaves_the_page_with_the_slot(browser, serve):
    """A decided suggestion's losing slot is off the page, and a label inside it goes
    too. The label is the one thing that reads back over chrome — a pick mark says
    "chosen" and declares those words the page's, which is what lets a reviewer point at
    it anywhere else — so the rule has to stop at the slot: a marker that outranks a look
    must not outrank a decision, or a quote lands in the half the reviewer removed."""
    url = serve(RETIRED_WIDGET_PAGE, anchored=[("sug-swap", "chosen")])
    interact.append_event(serve.page_dir, {"kind": "action", "author": "user", "version": 1,
                                           "widget": "sug-swap", "action": "accept",
                                           "detail": {}})
    page, errors = open_page(browser, url)
    expect(page.locator("#sug-swap cq-old")).to_be_hidden()
    assert page.locator("#old-lax .cq-pick").evaluate("el => el.textContent") == "chosen", (
        "fixture is not exercising the case — the mark the slot hides never rendered"
    )
    expect(page.locator(".cq-thread .cq-quote").first).to_have_class(
        re.compile(r"\bdetached\b")
    )
    assert painted(page, "cq-mark") == "", (
        "a quote matched inside the half the reviewer accepted away, because the "
        "label there declared itself the page speaking"
    )
    assert errors == []
    page.close()


def test_a_decision_that_empties_its_widget_detaches_the_element_anchor(browser, serve):
    """An element anchor asks whether its section is still on the reviewer's page,
    and for a suggestion that settles to nothing — an insertion refused — the
    markup's presence is the wrong answer: the thread read as attached while its
    outline drew nothing. Pending, the wrapper is a thing to point at; refused, the
    thread detaches like any passage the decision removed."""
    url = serve(SUGGESTION_PAGE)
    interact.append_event(serve.page_dir, {"kind": "comment", "author": "user", "version": 1,
                                           "text": "Is thistle worth a feeder?",
                                           "anchor": {"section": "sug-thistle"}})
    page, errors = open_page(browser, url)
    thread = page.locator(".cq-thread .cq-quote").first
    expect(thread).not_to_have_class(re.compile(r"\bdetached\b"))
    expect(page.locator("#sug-thistle")).to_have_class(re.compile(r"\bcq-mark-el\b"))

    page.locator("[data-cq-for='sug-thistle'] .cq-sug-reject").click()
    expect(thread).to_have_class(re.compile(r"\bdetached\b"))
    expect(page.locator("#sug-thistle")).not_to_have_class(re.compile(r"\bcq-mark-el\b"))
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
                              "detail": {"options": ["rp-shim"]}})
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

    c1 = comment({"quote": "first passage"}, "Sharpen this.")
    c2 = comment({"quote": "two separate remarks"}, "Second thought.")
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
    note = page.locator("#p1 .cq-mark-note")
    expect(note).to_have_role("button")
    note.focus()
    expect(note).to_be_focused()
    assert note.evaluate("el => el.getBoundingClientRect().width > 1"), (
        "the comment path stayed invisible when a keyboard reader reached it"
    )
    note.press("Enter")
    expect(page.locator(f'.cq-thread[data-id="{c1}"]')).to_be_focused()
    page.keyboard.press("j")
    expect(page.locator(f'.cq-thread[data-id="{c2}"]')).to_be_focused()

    # Once the first thread resolves, the same control enters the next one.
    interact.append_event(d, {"kind": "resolve", "author": "user", "parent": c1})
    expect(note).to_have_text("1 comment")
    note.press("Enter")
    expect(page.locator(f'.cq-thread[data-id="{c2}"]')).to_be_focused()
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
    assert "1 comment" in page.locator("#p1").aria_snapshot()

    # A passage crossing two blocks says so in both: a reader landing on either block
    # hears about the comment, the way the paint reaches both.
    comment({"quote": "to land in it. A short second"}, "Crosses the boundary.")
    expect(page.locator("#p2 .cq-mark-note")).to_have_count(1)
    assert "2 comments" in page.locator("#p1").aria_snapshot()
    assert "1 comment" in page.locator("#p2").aria_snapshot()
    assert errors == []
    page.close()


def test_the_leader_key_addresses_reply_boxes(browser, serve):
    """A reply box's send shortcut is focus-scoped, so only the focused box claims it:
    unfocused, the placeholder carries the box's own address — g plus the number its
    thread wears in the corner — and that sequence reaches the box from anywhere
    outside a typing context. Inside one, g and digits are just letters; a non-digit
    after g disarms the leader and keeps its ordinary meaning."""
    url = serve(NOTED_PAGE)
    d = serve.page_dir

    def comment(anchor, text):
        return interact.append_event(
            d, {"kind": "comment", "author": "user", "version": 1, "text": text,
                "anchor": anchor})["id"]

    c1 = comment({"quote": "first passage"}, "Sharpen this.")
    c2 = comment({"quote": "two separate remarks"}, "Second thought.")
    c3 = comment({"section": "fig"}, "The figure too.")
    page, errors = open_page(browser, url)
    page.wait_for_function("() => document.querySelectorAll('.cq-thread').length === 3")

    # g then a digit lands in that thread's reply box, opening the panel on the way.
    page.keyboard.press("g")
    page.keyboard.press("2")
    ta2 = page.locator(f'.cq-thread[data-id="{c2}"] textarea')
    expect(ta2).to_be_focused()
    # The focused box claims the send keys; an unfocused one its own address, which
    # its thread also wears as the corner badge.
    expect(ta2).to_have_attribute("placeholder", re.compile(r"Reply · (⌘⏎|Ctrl\+⏎)$"))
    ta1 = page.locator(f'.cq-thread[data-id="{c1}"] textarea')
    expect(ta1).to_have_attribute("placeholder", "Reply · g 1")
    expect(page.locator(f'.cq-thread[data-id="{c1}"] .cq-thread-num')).to_have_text("1")

    # A digit with no leader is nothing: Esc backs out to the thread, and 3 stays put.
    page.keyboard.press("Escape")
    expect(page.locator(f'.cq-thread[data-id="{c2}"]')).to_be_focused()
    page.keyboard.press("3")
    expect(page.locator(f'.cq-thread[data-id="{c2}"]')).to_be_focused()

    # A non-digit disarms the leader and keeps its ordinary meaning: g j is a thread step.
    page.keyboard.press("g")
    page.keyboard.press("j")
    expect(page.locator(f'.cq-thread[data-id="{c3}"]')).to_be_focused()

    # Typing contexts are untouched: in a box, g and 1 are text, and focus stays put.
    page.keyboard.press("Enter")
    ta3 = page.locator(f'.cq-thread[data-id="{c3}"] textarea')
    expect(ta3).to_be_focused()
    page.keyboard.type("g1")
    expect(ta3).to_have_value("g1")
    expect(ta3).to_be_focused()
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
    the shape a real selection takes, and asks for the highlight the composer promises.

    "Every" includes the words a widget renders into a control, which is why the filter
    below is the runtime's own rule rather than a test for the chrome class: while it was
    the class, the sweep that proves every passage is quotable structurally could not see
    the passages that weren't. It reaches six tab names, two column headings and a settled
    group's summary line in the gallery alone."""
    page, errors = open_page(browser, serve(example.read_text()))
    result = page.evaluate("""async () => {
        const tick = () => new Promise(r => setTimeout(r, 0));
        const composer = document.querySelector('.cq-composer');
        const fab = document.querySelector('.cq-fab');
        // A reader reaches everything eventually — opens the details, clicks through to
        // the other tab — so everything is in scope, not just what the page opens on.
        document.querySelectorAll('details').forEach(d => (d.open = true));
        document.querySelectorAll('[hidden]').forEach(e => e.removeAttribute('hidden'));
        // Declared labels are in scope, and the filter is the runtime's own rule rather
        // than the class: a tab's name and a settled row's title are words the page says
        // from inside chrome, which is exactly the shape a filter on .cq-ui cannot see.
        const speaks = el => {
            const near = el.closest('.cq-ui, [data-cq-said]');
            return !near || near.matches('[data-cq-said]');
        };
        const blocks = [...document.querySelectorAll('p,li,h1,h2,h3,td,th,blockquote,'
            + 'figcaption,summary,cq-option,cq-variant,cq-milestone,cq-metric,[data-cq-said]')]
          .filter(b => speaks(b) && b.checkVisibility()
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


FENCED_CAPTURE_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>fenced capture</title>
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<h1 id="h">Roadmap</h1>
<cq-milestones>
  <cq-milestone id="gate-milestone" status="active" when="week-1" tags="wood,solar">
    <strong>Build feeders</strong> Two classic models.
  </cq-milestone>
</cq-milestones>
<p id="after-milestone">Ready next.</p>
<cq-options id="fence-options">
  <cq-option id="fence-option" effort="low">
    <strong>Classic feeder</strong> Easy to clean.
  </cq-option>
</cq-options>
</main>
</body>
</html>
"""


def test_browser_and_file_captures_stop_at_the_same_widget_fences(browser, serve):
    """Module-only words may sit between authored parts, but they cannot give the
    browser more context than the version file can confirm."""
    page, errors = open_page(browser, serve(FENCED_CAPTURE_PAGE))
    expect(page.locator("#gate-milestone .cq-chips")).to_have_count(1)
    registry = json.loads((serve.page_dir / "registry.json").read_text())
    cases = [
        ("#gate-milestone strong", "Build feeders", "gate-milestone"),
        ("#gate-milestone", "Two classic models.", "gate-milestone"),
        ("#after-milestone", "Ready next.", "after-milestone"),
        ('#fence-option > [data-cq-said="effort"]', "low", "fence-option"),
    ]

    for index, (selector, quote, section) in enumerate(cases, 1):
        expected_anchor = interact.capture_anchor(
            FENCED_CAPTURE_PAGE, registry, quote, section
        )
        selected = page.evaluate(
            """([selector, quote]) => {
                const root = document.querySelector(selector);
                const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
                let node;
                while ((node = walker.nextNode())) {
                    const at = node.data.indexOf(quote);
                    if (at === -1) continue;
                    const range = document.createRange();
                    range.setStart(node, at);
                    range.setEnd(node, at + quote.length);
                    const selection = getSelection();
                    selection.removeAllRanges();
                    selection.addRange(range);
                    return selection.toString();
                }
                return null;
            }""",
            [selector, quote],
        )
        assert selected == quote
        page.dispatch_event("body", "mouseup")
        expect(page.locator(".cq-fab")).to_be_visible()
        page.locator(".cq-fab").click()
        page.locator(".cq-composer textarea").fill(f"fence {index}")
        page.get_by_role("button", name="Comment", exact=True).click()
        expect(page.locator(".cq-thread")).to_have_count(index)
        actual_anchor = [
            event["anchor"]
            for event in interact.read_events(serve.page_dir)
            if event["kind"] == "comment"
        ][-1]
        assert actual_anchor == expected_anchor, (
            f"{selector} captured {actual_anchor}, file captured {expected_anchor}"
        )

    assert errors == []
    page.close()


# A label a widget renders into a control it also built. The tab strip is the case with
# nowhere else to say it: once the strip exists the panel heading stands down, so the
# button is the panel's only name. Every word here is distinct, so a quote can only
# anchor where it was picked, and the panels are long enough that a drag across one of
# these labels is an ordinary drag.
CONTROL_LABEL_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>labels</title>
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<h1 id="h">Aviary projects</h1>
<p id="lede">Two workstreams, one page.</p>
<cq-tabs id="projects">
  <cq-tab id="tab-feeders" label="Winter feeders">
    <p id="p-feeders">Two of the four feeders are mounted; the south pair waits on brackets.</p>
  </cq-tab>
  <cq-tab id="tab-bath" label="Heated bird bath">
    <p id="p-bath">The thermostat arrived cracked and a replacement is on order.</p>
  </cq-tab>
</cq-tabs>
</main>
</body>
</html>
"""


def test_selecting_a_tab_leaves_the_strip_where_it_was(browser, serve):
    """A control says which state it is in with paint, never with metrics.

    The selected tab used to be set in 600 weight, and a bolder label is a wider one:
    every tab after it slid a couple of pixels the instant one was pressed, so the strip
    reshuffled under the pointer that had just pressed it and the next tab along was no
    longer where the reviewer had been aiming. Nothing about that is visible in a
    screenshot of either state — both strips lay out perfectly well — which is why it is
    the two together that get asserted.

    Which panel is showing is content, and content is allowed to change the widget's
    height; the strip is the control, and controls hold still."""
    page, errors = open_page(browser, serve(CONTROL_LABEL_PAGE))
    strip = "() => [...document.querySelectorAll('cq-tabs [role=tab]')].map(e => { \
             const r = e.getBoundingClientRect(); return [e.textContent, r.x, r.width]; })"
    before = page.evaluate(strip)
    assert len(before) == 2, "the strip didn't render, so this asserts nothing"

    page.get_by_role("tab", name="Heated bird bath").click()
    expect(page.locator("#p-bath")).to_be_visible()
    assert page.evaluate(strip) == before, "selecting a tab moved the strip it sits in"
    assert errors == []


def test_a_widgets_label_takes_a_comment_inside_the_control_it_labels(browser, serve):
    """The other half of the pair above: a word the page says that the widget renders
    into a control. A tab's name is the case with nowhere else to go — the panel heading
    the theme paints stands down the moment the strip exists — so if the strip's button
    can't be quoted, the reviewer can read the tab's name and never point at it.

    That is what a reviewer hit, twice, on a draft's heading: the words were the page's
    and the row holding them was marked as the runtime's. `.cq-ui` is a look, and
    anchoring's question is whose words these are — so the label answers it where it is
    written (relabel), and the nearest answer wins over the box around it.

    A real drag, because the whole class of bug is text that looks selectable and
    isn't. Then the republish, because an anchor on a widget's word has to survive a
    version turning over the way one on a paragraph does."""
    page, errors = open_page(browser, serve(CONTROL_LABEL_PAGE))

    tab = page.get_by_role("tab", name="Heated bird bath")
    box = tab.bounding_box()
    y = box["y"] + box["height"] / 2
    page.mouse.move(box["x"] + 6, y)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] - 6, y, steps=8)
    page.mouse.up()

    assert page.evaluate("() => getSelection().toString()").strip() == "Heated bird bath", (
        "a drag across the tab's name selected nothing"
    )
    # The drag ended on a button, and the button still switches tabs — but this mouseup
    # was a selection's, not a press, so the reader is still looking at what they were
    # reading when they reached for the name.
    expect(page.locator("#p-feeders")).to_be_visible()

    page.locator(".cq-fab").click()
    expect(page.locator(".cq-composer")).to_be_visible()
    assert composer_quote(page)["text"].strip("“”") == "Heated bird bath"
    page.locator(".cq-composer textarea").fill("call it the bath, not the bird bath")
    page.get_by_role("button", name="Comment", exact=True).click()
    page.wait_for_function("() => (CSS.highlights.get('cq-mark')?.size ?? 0) > 0")

    thread = page.locator(".cq-thread .cq-quote").first
    assert thread.text_content().strip().strip("“”") == "Heated bird bath"

    # A second version reworking the other panel's prose and nothing else: the name the
    # comment is on is still there, so the comment is still on it.
    d = serve.page_dir
    (d / "versions" / "v2.html").write_text(
        CONTROL_LABEL_PAGE.replace("the south pair waits on brackets", "the brackets arrived")
    )
    interact.append_event(d, {"kind": "note", "author": "claude", "version": 2, "text": "two"})
    page.wait_for_url("**/v2.html", timeout=10_000)
    page.wait_for_function("() => (CSS.highlights.get('cq-mark')?.size ?? 0) > 0")
    assert page.locator(".cq-thread .cq-quote.detached").count() == 0, (
        "the comment came loose from the tab's name when the version turned over"
    )
    assert errors == []
    page.close()


def test_a_selection_around_a_control_does_not_deaden_it(browser, serve):
    """The other side of the guard above, and the one that cost more. A reviewer reads
    the sentence a suggestion sits in, drags across it, and then presses Accept — a
    fresh press, long after that drag's own mouseup.

    Asking whether the live selection *contains* the control is a question about the
    DOM, and a suggestion's row is the column's own child in flow between the block
    holding the change and the next one: a drag across both runs straight over it. So
    Accept did nothing, and kept doing nothing, because a press that refuses a drag
    never collapses the selection that deadened it either. The keyboard still worked,
    which is the shape of a bug nobody reports — it looks like a slip of the mouse.

    Both decisions the product exists to collect go through a press, so this asserts the
    pointer and then the keyboard, with the selection standing throughout."""
    page, errors = open_page(browser, serve(SUGGESTION_PAGE))
    # Across the two paragraphs, so the row deciding the first is inside the selection.
    start = page.locator("#replace").bounding_box()
    end = page.locator("#insert").bounding_box()
    page.mouse.move(start["x"] + 4, start["y"] + 6)
    page.mouse.down()
    page.mouse.move(end["x"] + end["width"] - 6, end["y"] + end["height"] - 6, steps=16)
    page.mouse.up()
    assert page.evaluate(
        "() => getSelection().containsNode(document.querySelector("
        "'[data-cq-for=sug-refill] .cq-sug-reject'), true)"
    ), "the selection doesn't reach the control, so this run tests nothing"

    page.locator("[data-cq-for='sug-refill'] .cq-sug-reject").click()
    expect(page.locator("#sug-refill")).to_have_attribute("data-cq-state", "reject")
    assert page.evaluate("() => !getSelection().isCollapsed"), (
        "the press cleared the selection, so the keyboard half below is untested"
    )
    page.locator("[data-cq-for='sug-in-card'] .cq-sug-accept").focus()
    page.keyboard.press("Enter")
    expect(page.locator("#sug-in-card")).to_have_attribute("data-cq-state", "accept")
    assert errors == []
    page.close()


def test_the_comment_button_stands_on_no_control(browser, serve):
    """And the other way the same press is lost: not deadened but covered. A selection
    fills its lines, so the button placed beside it goes out to the column's right edge —
    into the margin, on the line the change starts, which is exactly where the row
    deciding that change hangs. The reviewer's own gesture put the 💬 over the Accept
    they made it to reach, and the press did the one thing worse than nothing: it hit the
    button and opened a composer, because a press on the 💬 is not the outside click that
    dismisses it.

    Asserted through the hit test rather than the rectangles, since what matters is which
    element the press would reach — and then by making the press, which is the whole
    claim."""
    page, errors = open_page(browser, serve(SUGGESTION_PAGE))
    box = page.locator("#replace").bounding_box()
    page.mouse.move(box["x"] + 4, box["y"] + 6)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] - 8, box["y"] + box["height"] - 6, steps=16)
    page.mouse.up()
    expect(page.locator(".cq-fab")).to_be_visible()

    under = page.evaluate("""() => [...document.querySelectorAll("[data-cq-offer]")]
        .filter(c => !c.closest(".cq-chrome"))
        .filter(c => { const b = c.getBoundingClientRect();
                       const top = document.elementFromPoint((b.left + b.right) / 2,
                                                            (b.top + b.bottom) / 2);
                       return top && !c.contains(top) && top.closest(".cq-chrome"); })
        .map(c => c.className)""")
    assert under == [], f"floating chrome is standing on controls: {under}"

    page.locator("[data-cq-for='sug-refill'] .cq-sug-accept").click()
    expect(page.locator("#sug-refill")).to_have_attribute("data-cq-state", "accept")
    expect(page.locator(".cq-composer")).to_be_hidden()  # the press decided, it didn't compose
    assert errors == []
    page.close()


def test_the_composer_opens_where_the_button_stood(browser, serve):
    """Stepping the button aside is undone if what it opens goes back. The button carries
    the anchor it was raised on, and it used to carry the position it was *asked for*
    alongside — the same point for as long as nothing moved it, and a different one from
    the moment something did. So the 💬 cleared the row and the composer it opened landed
    back on top of it."""
    page, errors = open_page(browser, serve(SUGGESTION_PAGE))
    box = page.locator("#replace").bounding_box()
    page.mouse.move(box["x"] + 4, box["y"] + 6)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] - 8, box["y"] + box["height"] - 6, steps=16)
    page.mouse.up()
    expect(page.locator(".cq-fab")).to_be_visible()
    stood = page.locator(".cq-fab").evaluate("el => el.getBoundingClientRect().top")
    # It moved, or this run would hold whether or not the position were carried along.
    assert stood > page.locator("[data-cq-for='sug-refill']").evaluate(
        "el => el.getBoundingClientRect().bottom"
    ), "the button never stepped aside, so where it stood proves nothing"

    page.locator(".cq-fab").click()
    expect(page.locator(".cq-composer")).to_be_visible()
    opened = page.locator(".cq-composer").evaluate("el => el.getBoundingClientRect().top")
    assert abs(opened - stood) <= 1, (
        f"the composer opened at {opened}, where the button was asked for, not {stood}"
    )
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
    panel, emitted into a Markdown blockquote by `review transcript` — and written to a
    UTF-8 file on the way. Source text is neither: it carries the author's line wraps,
    which break a blockquote open, and cutting it to length by UTF-16 unit can halve a
    character, which no UTF-8 file can hold. The server refuses that write and the
    reader is told it is offline, with no way to ever send the comment."""
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
    panel_settled(page)

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
        panel_settled(page, open=False)

    page.locator("#fig").scroll_into_view_if_needed()
    spot = page.evaluate("""() => { const r = [...CSS.highlights.get('cq-mark')][0].getClientRects()[0];
                                    return {x: r.left + r.width / 2, y: r.top + r.height / 2}; }""")
    page.mouse.click(spot["x"], spot["y"])
    panel_settled(page)
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


CODE_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>code</title>
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<h1 id="t">Code</h1>
<section id="walk">
<p id="lede">The key changes shape:</p>
<cq-code id="walk-code" language="python" hi="2">
def bucket_key(request):
    if request.token:
        return f"tok:{request.token.id}"
    return "anon"
<cq-note at="2">A token id shaped like an address would collide.</cq-note>
</cq-code>
<pre><code class="language-bash"># apply the migration, then run the marked suite
cd gateway &amp;&amp; alembic upgrade head</code></pre>
<cq-code id="plain-code">
$ colloquy version check ./page --render
v1.html: renders clean
</cq-code>
</section>
</main>
</body>
</html>
"""


def test_code_is_colored_without_a_word_moving(browser, serve):
    """Colouring is spans, and the anchor pass is what spans break: the version file holds
    one run of characters where the DOM now holds a dozen nodes. A <span> is no text block,
    so both readings collapse to the same string — which is what lets the runtime color a
    block the file knows nothing about, and what keeps `review comment` able to quote
    into one.

    One pass serves both shapes a page has for code, cq-code's `language` and a plain
    <pre><code class="language-*">, and neither guesses: a cq-code with no `language` stays
    the color of its own ink. The quote below is written the way `review comment` writes
    one — against the file — and spans a token boundary on its way back."""
    url = serve(CODE_PAGE)
    page, errors = open_page(browser, url)
    page.wait_for_function("() => document.querySelector('cq-code.cq-rendered') !== null")

    roles = page.evaluate("""() => {
      const at = sel => [...document.querySelectorAll(sel + ' [data-cq-syn]')]
        .map(e => [e.dataset.cqSyn, e.textContent]);
      return { widget: at('#walk-code'), plain: at('#walk pre > code'),
               undeclared: at('#plain-code') };
    }""")
    assert ["kw", "def"] in roles["widget"] and ["fn", "bucket_key"] in roles["widget"]
    assert {r for r, _ in roles["widget"]} >= {"kw", "st", "fn"}, roles["widget"]
    assert ["cm", "# apply the migration, then run the marked suite"] in roles["plain"]
    assert roles["undeclared"] == [], (
        f"a cq-code with no language was colored anyway: {roles['undeclared']}"
    )

    # The words each block holds, unchanged by the spans: what the file says is what the
    # page says, which is the whole reason a quote written against one lands in the other.
    # The widget numbers lines, so its own newline is the join; the note it docks at line 2
    # is prose and sits outside the code.
    assert page.evaluate("() => document.querySelector('#walk pre > code').textContent") == (
        "# apply the migration, then run the marked suite\ncd gateway && alembic upgrade head"
    )
    assert page.evaluate(
        "() => [...document.querySelectorAll('#walk-code .cq-code-line')]"
        ".map(l => l.textContent).join('')"
    ) == (
        'def bucket_key(request):\n    if request.token:\n'
        '        return f"tok:{request.token.id}"\n    return "anon"\n'
    )

    # A quote across a token boundary — "upgrade" is plain, "head" is a keyword span.
    page.request.post(
        url.rsplit("/versions/", 1)[0] + "/api/event",
        data={"kind": "comment", "version": 1, "text": "does prod want --sql here?",
              "anchor": {"section": "walk", "quote": "alembic upgrade head",
                         "prefix": "on, then run the marked suite cd gateway &&",
                         "suffix": ""}},
    )
    page.get_by_role("button", name="Comments", exact=False).click()
    expect(page.locator(".cq-thread")).to_have_count(1)
    expect(page.locator(".cq-panel .cq-quote.detached")).to_have_count(0)
    # The mark is a painted range, so what it covers is read back off CSS.highlights
    # rather than off the DOM. Waited for, not read: the thread arrives on a poll.
    page.wait_for_function(
        "() => (CSS.highlights.get('cq-mark')?.size ?? 0) > 0",
        timeout=5000,
    )
    marked = page.evaluate("""() => [...CSS.highlights.get('cq-mark').values()]
                                     .map(r => r.toString()).join("")""")
    assert marked == "alembic upgrade head", f"the mark landed on {marked!r}"
    assert errors == []
    page.close()


def test_every_language_returns_the_source_it_was_given(browser, serve):
    """`syntax` promises the tokens partition the source exactly, and cq-code's line
    numbers, `hi`, and every note's `at` are counted off that partition — so a tokenizer
    that dropped a character would slide all three with nothing on screen saying so. The
    promise is checked at the boundary and the check throws; this drives every language
    the registry offers through the real module, including each one against another
    language's source, which is where a lexer meets input it was never written for.

    It is also what a version bump of the vendored bundle has to survive."""
    url = serve(CODE_PAGE)
    page, errors = open_page(browser, url)
    langs = interact.load_registry(serve.page_dir)["$languages"]["names"]
    samples = [
        'def f(x):\n    """doc\n    <b>&amp;</b>\n    """\n    return f"{x!r}"  # ok\n',
        "# c\ncd x && ls -la | grep \"a b\" > /dev/null\n",
        '{"a": [1, 2, {"b": null}], "c": "<>&"}\n',
        "@@ -1 +1 @@\n-a <b>\n+c &d\n",
        "SELECT * FROM t WHERE a = 'x''y'; -- note\n",
        '<!doctype html>\n<a href="x?a=1&b=2">t &amp; u</a>\n',
    ]
    bad = page.evaluate(
        """async ([langs, samples]) => {
          const { syntax } = await import('/colloquy.js');
          const bad = [];
          for (const lang of langs)
            for (const src of samples) {
              try {
                const tokens = await syntax(src, lang);
                const back = tokens.map(t => t.text).join('');
                if (back !== src) bad.push([lang, src, back]);
              } catch (e) { bad.push([lang, src, String(e)]); }
            }
          return bad;
        }""",
        [langs, samples],
    )
    assert bad == [], f"the tokenizer changed the source: {bad}"
    assert errors == []
    page.close()


# A diff of three files, one per thing the colouring has to get right: a Python file
# whose second hunk moves a docstring across lines and whose two sides disagree about
# what is open, a yaml file (the grammar that reads a leading `-` as a sequence bullet
# and a leading `+` as a string, so the prefix column has to be off before it looks),
# and a file whose extension names no language at all.
DIFF_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>diff</title>
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<h1 id="t">Diff</h1>
<cq-diff id="patch">
diff --git a/gateway/limits.py b/gateway/limits.py
--- a/gateway/limits.py
+++ b/gateway/limits.py
@@ -38,7 +38,8 @@ class Limiter:
     def bucket_key(self, request):
-        return request.remote_addr
\\ No newline at end of file
+        if request.token:
+            return f"tok:{request.token.id}"
@@ -71,5 +73,7 @@ class Limiter:
     def reset(self, key):
-        \"\"\"Drop one bucket.
-        Called on logout.\"\"\"
+        \"\"\"Drop one bucket, prefix and all.
+
+        Called on logout, and once per renamed key.
+        \"\"\"
         self.buckets.pop(key, None)
diff --git a/gateway/config.yaml b/gateway/config.yaml
--- a/gateway/config.yaml
+++ b/gateway/config.yaml
@@ -4,6 +4,6 @@ ratelimit:
-  burst: 20
+  burst: 40
   window: 60
diff --git a/deploy/Dockerfile b/deploy/Dockerfile
--- a/deploy/Dockerfile
+++ b/deploy/Dockerfile
@@ -9,2 +9,2 @@ COPY gateway /srv/gateway
-RUN pip install -r requirements.txt
+RUN pip install --no-cache-dir -r requirements.txt
</cq-diff>
</main>
</body>
</html>
"""


def test_a_diff_is_colored_by_each_files_own_path(browser, serve):
    """A diff is the page's most code-dense shape and it sits beside cq-code on the pages
    that carry both, so leaving it plain said the evidence was not code. It has no `language`
    to read — a unified diff spans files — so each file's path is what says what it holds,
    and a path naming nothing leaves that file the colour of its own ink.

    Three things that were each wrong in a draft of this. The +/−/space column is the
    diff's word about a line and not the file's: yaml lexes a leading `-` as a sequence
    bullet and a leading `+` as a string, so a prefix left on restates the widget's own
    signal in the wrong ink. A hunk is tokenized one side at a time, because read straight
    through it interleaves two versions that never coexisted. And each side is tokenized
    whole, because a docstring spans lines — coloured a line at a time, the prose inside
    one comes back as code."""
    page, errors = open_page(browser, serve(DIFF_PAGE))
    page.wait_for_function("() => document.querySelector('cq-diff.cq-rendered') !== null")

    files = page.evaluate("""() => [...document.querySelectorAll('#patch details')].map(d => ({
      path: d.querySelector('summary code').textContent,
      lines: [...d.querySelectorAll('pre > span')].map(l => ({
        kind: l.className,
        text: l.textContent,
        // Whether the line opens inside a syntax span — which is where the +/− column
        // would have gone if it had been handed to the tokenizer along with the source.
        signInSpan: l.firstChild?.nodeType === Node.ELEMENT_NODE,
        roles: [...l.querySelectorAll('[data-cq-syn]')].map(s => [s.dataset.cqSyn, s.textContent]),
      })),
    }))""")
    by_path = {f["path"]: f["lines"] for f in files}
    assert set(by_path) == {"gateway/limits.py", "gateway/config.yaml", "deploy/Dockerfile"}

    py = by_path["gateway/limits.py"]
    assert any(["kw", "if"] in line["roles"] for line in py), py
    assert {r for line in py for r, _ in line["roles"]} >= {"kw", "st", "fn"}

    # The docstring the second hunk rewrites: every line of it is string, on both sides.
    # Colouring line by line instead, `and` inside the prose came back a keyword.
    doc = [l for l in py if "Called on logout" in l["text"]]
    assert len(doc) == 2, [l["text"] for l in py]
    for line in doc:
        assert [r for r, _ in line["roles"]] == ["st"], line

    # yaml, the grammar that would have eaten the prefix: with the column left on, the
    # `-` came back a bullet in keyword ink and the `+` a string. No span opens a line
    # here, and the key is still an attr — so the prefix came off before the lexer looked.
    yml = [l for l in by_path["gateway/config.yaml"] if l["kind"] in ("add", "del")]
    assert len(yml) == 2
    for line in yml:
        assert not line["signInSpan"], line
        assert ["ty", "burst:"] in line["roles"], line

    # `\\ No newline at end of file` is git remarking on the line above, not a line of
    # the file. Shown, because the diff says it, but its own kind — read as context it
    # would go into both reconstructed sides as source the file never held.
    note = [l for l in py if l["kind"] == "note"]
    assert [l["text"] for l in note] == ["\\ No newline at end of file\n"], py
    assert note[0]["roles"] == [], note

    # No extension the table names: plain, the way a cq-code with no `language` is.
    assert all(l["roles"] == [] for l in by_path["deploy/Dockerfile"]), by_path["deploy/Dockerfile"]

    # Every displayed source line still reads exactly as authored, sign column and all.
    # File headers are metadata already represented by the summary, so the widget drops
    # them instead of leaving hidden text in the DOM for anchoring to find.
    assert [l["text"] for l in by_path["gateway/config.yaml"]] == [
        "@@ -4,6 +4,6 @@ ratelimit:\n",
        "-  burst: 20\n", "+  burst: 40\n", "   window: 60\n",
    ]
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
<cq-diff id="patch">
diff --git a/gateway/cache.py b/gateway/cache.py
--- a/gateway/cache.py
+++ b/gateway/cache.py
@@ -18,7 +18,7 @@ class Bucket:
 def key(self, request):
-    return request.path
+    return request.path, request.headers.get("Accept")
 def store(self, request):
</cq-diff>
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


def test_an_ambiguous_revised_passage_detaches_instead_of_guessing(browser, serve):
    """Context tells two copies apart; it must not relocate a comment when the page moves
    on. If a later version rewrites the words beside the anchored copy, that copy confirms
    almost nothing while another copy remains. Neither is now identifiable: document
    order is not evidence, so the comment detaches visibly instead of moving to words it
    was never made on."""
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
    expect(page.locator(".cq-thread .cq-quote.detached")).to_have_count(1)
    assert page.evaluate("() => CSS.highlights.get('cq-mark')?.size ?? 0") == 0
    expect(page.locator(".cq-thread .cq-quote")).to_have_attribute(
        "title", re.compile("can't be identified")
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
                   "prefix": "ails again in the night,",
                   "suffix": ". Nothing else moves."}})
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


def test_an_ambiguous_one_sided_anchor_from_an_older_capture_detaches(browser, serve):
    """A capture that stopped at the section root wrote no prefix at all for a passage
    opening its section. Read the way the search now reads an empty side — nothing preceded
    this passage anywhere on the page — that claim is false wherever the section wasn't
    first, so no occurrence confirms it. With two quote candidates left, the passage is
    ambiguous and detaches rather than using document order."""
    url = serve(EDGE_PAGE)
    # A suffix that fits the second copy and nothing else, stored with no prefix beside it.
    interact.append_event(serve.page_dir, {
        "kind": "comment", "author": "claude", "version": 1, "text": "older anchor",
        "anchor": {"section": "edge", "quote": "the run is retried until it lands",
                   "suffix": ". Rollout resumes"}})
    page, errors = open_page(browser, url)
    expect(page.locator(".cq-thread .cq-quote.detached")).to_have_count(1)
    assert page.evaluate("() => CSS.highlights.get('cq-mark')?.size ?? 0") == 0
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


def test_one_neighbour_is_not_enough_to_identify_a_revised_comment(browser, serve):
    """Context may place a comment only where both of a passage's neighbours are still
    there. A passage at the edge of its section has just one, and one is a bar another copy
    clears — so a revision that rewrites the commented copy's only neighbour would hand the
    comment to a copy it was never made on, silently, a version after anyone was looking.
    The cost of refusing is visible instead: the thread detaches until a later version
    makes its passage unique again."""
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
    expect(page.locator(".cq-thread .cq-quote.detached")).to_have_count(1)
    assert page.evaluate("() => CSS.highlights.get('cq-mark')?.size ?? 0") == 0
    assert errors == []
    page.close()


def test_the_picker_runs_in_number_order_past_v9(browser, serve):
    """A version stays an integer from the server through runtime state; only the
    picker and URL boundary render its file name. Order a review by those names
    instead and v10 lands between v1 and v2: the picker reads out of sequence,
    the diff offers the wrong base, and a reader on the newest version is told a
    newer one is waiting."""
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
    page, errors = open_page(browser, url, pin=True)
    expect(page.locator(".cq-latest-chip")).to_have_text(
        "New version available → open v10"
    )
    assert errors == []
    page.close()


def test_a_diff_anchors_to_the_side_it_was_read_on(browser, serve):
    """The case this exists for, and the one a section cannot narrow: a diff carries the
    same line added and removed under a single id, so the reviewer commenting on the fix
    had their comment marked against the bug — stored that way, and shown to Claude that
    way in the next round.

    The passage is picked out of the rendered widget, where syntax colour has cut the
    line into spans: `return` is a keyword and ` request.path` is the text after it, so
    the selection starts in one node and ends in another. That is the ordinary shape of a
    passage in a coloured block, and the anchor knows nothing about it — a span is no text
    block, so both readings still collapse to the same run of characters."""
    page, errors = open_page(browser, serve(TWICE_PAGE))
    page.wait_for_function("() => document.querySelector('cq-diff.cq-rendered') !== null")
    landed = page.evaluate("""async () => {
        const skip = '.cq-ui, script, style';
        const w = document.createTreeWalker(document.getElementById('patch'),
            NodeFilter.SHOW_TEXT,
            {acceptNode: n => n.parentElement?.closest(skip)
                ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT});
        // One flat run over the widget's text nodes, and where each node started in it,
        // so a phrase is found whether or not a token boundary falls inside it.
        const nodes = [], starts = [];
        let flat = '';
        for (let n = w.nextNode(); n; n = w.nextNode()) {
            starts.push(flat.length); nodes.push(n); flat += n.data;
        }
        const phrase = 'return request.path';
        const hits = [];
        for (let i = flat.indexOf(phrase); i !== -1; i = flat.indexOf(phrase, i + 1)) hits.push(i);
        if (hits.length < 2) return `only ${hits.length} occurrence(s) — fixture broken`;
        const at = (offset) => {
            const i = starts.findLastIndex((s) => s <= offset);
            return [nodes[i], offset - starts[i]];
        };
        const start = hits.at(-1);   // the added line: the later of the pair
        const want = document.createRange();
        want.setStart(...at(start)); want.setEnd(...at(start + phrase.length));
        if (want.startContainer === want.endContainer)
            return 'the phrase sat in one node — colour never split it, so this proves nothing';
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
    """Write a version and publish it through `version publish`, which lints it
    and records a `note` event with what it says about the reviewer's decisions."""
    (page_dir / "versions" / f"v{version}.html").write_text(html)
    result = CliRunner().invoke(
        interact.cli,
        ["version", "publish", str(page_dir), "--version", str(version), "--text", note],
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
    # Posting opened the panel, and the page is sliding into the width that leaves for
    # it. Measuring a column mid-slide aims the drag below at where it was, not where
    # it is going, and the drop lands outside the column it was meant for.
    panel_settled(page)

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
    # The board after the paragraph is module-rendered and therefore an opaque
    # passage cell. Context stops at that shared browser/file fence.
    assert events[1]["anchor"] == {
        "section": "intro",
        "quote": SENTENCE,
        "prefix": "Journey",
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


def test_double_clicking_a_draft_leaves_every_word_where_it_was(browser, serve):
    """Two halves of one gesture, both of them invisible to a static lint.

    The box: reading and editing are the same box, so the words a reviewer
    double-clicked are still under the pointer when the editor opens. They were
    not — the runtime's general textarea rule wraps text in padding and a border
    and floors it at 64px, which moved the first character 9px right and 6px down
    and stretched a two-line draft — and text that jumps out from under a
    double-click is the reviewer's aim thrown away.

    The gesture: the word the browser would select is selected by the second
    mousedown and painted before dblclick arrives, so the handler that cleared it
    afterwards ran a frame late and the reviewer saw a flash. That frame is
    timing, and no assertion here reaches it; what is assertable is the outcome
    on either side of it. Nothing on the page ends up selected, and the word the
    gesture named opens selected in the box — which is what a double-click means
    everywhere else, and what cancelling the default rather than undoing it is
    for.

    The block around them counts too: the whole draft has to keep its shape, or a
    gesture aimed at one word is answered by everything under it moving. Cancel and
    Save join a row the draft always has rather than arriving as one, which is worth
    a measurement because the row is invisible in the diff that matters — both views
    lay out fine on their own, and only the two together say whether the box moved.

    And the swap is the screen's, which is why the widget writes none of it: paper
    drops the box with the other offers, so a draft mid-edit printed as an empty
    frame for as long as the module hid the body itself."""
    page, errors = open_page(browser, serve(JOURNEY_V1))
    metrics = """(sel) => {
      const el = document.querySelector('#draft-ops ' + sel), s = getComputedStyle(el);
      const b = el.getBoundingClientRect();
      return [b.x + parseFloat(s.paddingLeft) + parseFloat(s.borderLeftWidth),
              b.y + parseFloat(s.paddingTop) + parseFloat(s.borderTopWidth), b.width, b.height];
    }"""
    read = page.evaluate(metrics, ".cq-draft-body")
    host = page.locator("#draft-ops").bounding_box()
    # A 4px band above the box, and the box's own top-left corner. The band is where
    # the answer to "did the frame move" lives and no measurement of geometry can
    # reach it: an outset ring is paint, so every rect stayed exactly as asserted
    # below while the frame the reviewer sees grew 2px on every side, corners
    # rounding wider to match. Bytes, not pixels — the same encoder over the same
    # content gives the same file, so identical files are identical paint.
    band = dict(x=host["x"] - 4, y=host["y"] - 4, width=host["width"] + 8, height=4)
    inside = dict(x=host["x"], y=host["y"], width=40, height=40)
    outside_before = page.screenshot(clip=band)
    inside_before = page.screenshot(clip=inside)

    box = page.locator("#draft-ops .cq-draft-body").bounding_box()
    page.mouse.dblclick(box["x"] + 60, box["y"] + 8)
    editor = page.locator("#draft-ops textarea")
    expect(editor).to_be_focused()
    assert page.screenshot(clip=band) == outside_before, (
        "opening the editor painted outside the box the draft already occupied"
    )
    assert page.screenshot(clip=inside) != inside_before, (
        "the open editor is indistinguishable from the read view at the box's edge"
    )
    assert page.evaluate(metrics, "textarea") == read, (
        "the editor's text sits somewhere the read view's text did not"
    )
    assert page.locator("#draft-ops").bounding_box() == host, (
        "the draft changed shape under the pointer when the editor opened"
    )
    assert page.evaluate(
        "() => getSelection().rangeCount > 0 && "
        "getSelection().containsNode(document.querySelector('#draft-ops .cq-draft-body'), true)"
    ) is False, "the gesture left the page's own words selected under the open editor"
    selected = page.evaluate(
        "() => { const t = document.querySelector('#draft-ops textarea');"
        "        return t.value.slice(t.selectionStart, t.selectionEnd); }"
    )
    assert selected == "migration", f"the box opened on {selected!r} rather than the word clicked"

    # Closing states both properties in reverse, and the focus half is a question
    # only because the ✎ is CSS-hidden for as long as the editor is there: #close
    # reaches for it the instant the editor goes, so a style that hadn't caught up
    # would drop a keyboard reviewer back at the top of the page.
    page.keyboard.press("Escape")
    expect(page.locator("#draft-ops .cq-draft-pencil")).to_be_focused()
    assert page.locator("#draft-ops").bounding_box() == host, (
        "the draft came back from an edit a different shape than it went in"
    )

    # Reopened through the other door, because print is where the box has to be
    # gone and its words still there — and print emulation blurs the textarea it
    # hides, so an editor opened before this point is no longer one Escape closes.
    page.locator("#draft-ops .cq-draft-pencil").click()
    expect(page.locator("#draft-ops textarea")).to_be_visible()
    page.emulate_media(media="print")
    assert page.locator("#draft-ops").inner_text() == DRAFT_TEXT, (
        "the printed page lost the draft's words to a box paper hasn't got"
    )
    page.emulate_media(media="screen")
    assert errors == []
    page.close()


def test_a_foreign_edit_waits_for_a_live_draft_and_replays_in_order(browser, serve):
    """Replay never replaces words while the reviewer is typing them.

    Deferring one edit must also hold later edits for that draft: otherwise the
    later absolute value lands first and the deferred earlier value overwrites it
    when the box closes. An unrelated board move proves the poll saw the same
    batch while the editor was open, without making the test depend on time.
    """
    page, errors = open_page(browser, serve(JOURNEY_V1))
    draft = page.locator("#draft-ops")
    draft.locator(".cq-draft-body").dblclick()
    editor = draft.locator("textarea")
    editor.fill("Local unsent words.")

    d = serve.page_dir
    for text in ("Foreign first edit.", "Foreign committed words."):
        interact.append_event(
            d,
            {
                "kind": "action",
                "author": "user",
                "version": 1,
                "widget": "draft-ops",
                "action": "edit",
                "detail": {"text": text},
            },
        )
    interact.append_event(
        d,
        {
            "kind": "action",
            "author": "user",
            "version": 1,
            "widget": "board",
            "action": "move",
            "detail": {"card": "card-x", "to": "col-done", "index": 0},
        },
    )

    expect(page.locator("#col-done #card-x")).to_have_count(1, timeout=10000)
    expect(editor).to_have_value("Local unsent words.")
    expect(draft.locator(".cq-draft-history")).to_have_count(0)

    page.keyboard.press("Escape")
    expect(draft.locator(".cq-draft-body")).to_have_text(
        "Foreign committed words.", timeout=10000
    )
    expect(draft.locator(".cq-draft-history > summary")).to_have_text("Changes · 2 edits")
    expect(page.locator("body")).to_have_attribute("data-cq-applied", "3")
    assert errors == []
    page.close()


def test_an_empty_draft_survives_reload_and_blocks_a_version_switch(browser, serve):
    """Empty text is a real replacement, not the absence of a saved draft. Deleting
    the whole body must survive reload, keep the current version under the active
    editor, and arrive in the log as an ordinary absolute edit."""
    url = serve(JOURNEY_V1)
    page, errors = open_page(browser, url)
    draft = page.locator("#draft-ops")
    draft.locator(".cq-draft-body").dblclick()
    draft.locator("textarea").fill("")
    assert page.evaluate(
        """() => JSON.parse(
          sessionStorage.getItem('cq-draft:edit:draft-ops')
        ).text"""
    ) == ""

    d = serve.page_dir
    (d / "versions" / "v2.html").write_text(JOURNEY_V2)
    interact.append_event(
        d, {"kind": "note", "author": "claude", "version": 2, "text": "v2"}
    )
    expect(page.locator(".cq-latest-chip")).to_be_visible(timeout=10000)
    assert "/v1.html" in page.url, "an empty live edit was mistaken for no composition"

    page.reload(wait_until="networkidle")
    page.wait_for_function("() => document.body.dataset.cqUpgraded === '1'")
    expect(draft.locator("textarea")).to_be_visible()
    expect(draft.locator("textarea")).to_have_value("")

    page.evaluate(
        """() => {
          window.cqActualFetch = window.fetch.bind(window);
          window.cqFailDraft = true;
          window.fetch = (input, init) => {
            const event = String(input).endsWith('/api/event') && init?.body
              ? JSON.parse(init.body) : null;
            if (window.cqFailDraft &&
                event?.kind === 'action' && event.action === 'edit')
              return Promise.resolve(new Response('offline', {status: 503}));
            return window.cqActualFetch(input, init);
          };
        }"""
    )
    draft.get_by_role("button", name="Save").click()
    expect(draft.locator("textarea")).to_be_focused()
    expect(draft.locator("textarea")).to_have_value("")
    assert page.evaluate(
        """() => JSON.parse(
          sessionStorage.getItem('cq-draft:edit:draft-ops')
        ).text"""
    ) == ""

    page.evaluate("window.cqFailDraft = false")
    draft.get_by_role("button", name="Save").click()
    page.wait_for_url("**/v2.html", timeout=10000)
    expect(page.locator("#draft-ops .cq-draft-body")).to_have_text("")
    page.wait_for_function(
        "() => sessionStorage.getItem('cq-draft:edit:draft-ops') === null"
    )
    events = [
        json.loads(line)
        for line in (d / "comments.jsonl").read_text().splitlines()
        if '"kind": "action"' in line
    ]
    assert events[-1]["action"] == "edit"
    assert events[-1]["detail"] == {"text": ""}
    assert errors == []
    page.close()


def test_a_draft_send_owns_the_editor_until_its_response(browser, serve):
    """A second gesture cannot overtake an earlier request or let that request clear
    newer unsent text. Hold the first POST in the browser: while it owns the draft,
    every edit door stays closed and the exact body remains recoverable."""
    page, errors = open_page(browser, serve(JOURNEY_V1))
    page.evaluate(
        """() => {
          const actualFetch = window.fetch.bind(window);
          let held = true;
          window.fetch = (input, init) => {
            const event = String(input).endsWith('/api/event') && init?.body
              ? JSON.parse(init.body) : null;
            if (held && event?.kind === 'action' && event.action === 'edit') {
              return new Promise((resolve, reject) => {
                window.releaseDraftSend = () => {
                  held = false;
                  actualFetch(input, init).then(resolve, reject);
                };
              });
            }
            return actualFetch(input, init);
          };
        }"""
    )
    draft = page.locator("#draft-ops")
    sent = "The first save still owns this body."
    draft.locator(".cq-draft-body").dblclick()
    draft.locator("textarea").fill(sent)
    draft.get_by_role("button", name="Save").click()
    expect(draft).to_have_attribute("aria-busy", "true")
    assert page.evaluate(
        """() => JSON.parse(
          sessionStorage.getItem('cq-draft:edit:draft-ops')
        ).text"""
    ) == sent

    draft.locator(".cq-draft-pencil").click()
    expect(draft.locator("textarea")).to_have_count(0)
    expect(page.locator(".cq-toast")).to_contain_text("Wait for the current edit")

    page.evaluate("window.releaseDraftSend()")
    page.wait_for_function(
        """() => !document.getElementById('draft-ops').hasAttribute('aria-busy')
          && sessionStorage.getItem('cq-draft:edit:draft-ops') === null"""
    )
    events = [
        json.loads(line)
        for line in (serve.page_dir / "comments.jsonl").read_text().splitlines()
        if '"kind": "action"' in line
    ]
    assert [event["detail"]["text"] for event in events] == [sent]

    draft.locator(".cq-draft-pencil").click()
    expect(draft.locator("textarea")).to_be_focused()
    page.keyboard.press("Escape")
    assert errors == []
    page.close()


def test_unsent_draft_recovery_belongs_to_its_tab(browser, serve):
    """Recorded edits converge through the log; unsent words do not. Two pages in
    one BrowserContext are real same-origin tabs, unlike Browser.new_page's isolated
    contexts. A send and a Cancel in one must leave the other's newer empty edit
    recoverable through a reload."""
    context = browser.new_context(
        viewport={"width": 1200, "height": 900}, color_scheme="light"
    )
    try:
        url = serve(JOURNEY_V1)
        first, first_errors = open_page(browser, url, context=context)
        second, second_errors = open_page(browser, url, context=context)
        first_draft = first.locator("#draft-ops")
        second_draft = second.locator("#draft-ops")

        sent = "The first tab submits this body."
        first_draft.locator(".cq-draft-body").dblclick()
        first_draft.locator("textarea").fill(sent)
        second_draft.locator(".cq-draft-body").dblclick()
        second_draft.locator("textarea").fill("")

        first_draft.get_by_role("button", name="Save").click()
        expect(first_draft.locator(".cq-draft-history > summary")).to_have_text(
            "Changes · 1 edit"
        )
        expect(second_draft.locator("textarea")).to_have_value("")
        assert second.evaluate(
            """() => JSON.parse(
              sessionStorage.getItem('cq-draft:edit:draft-ops')
            ).text"""
        ) == ""

        first_draft.locator(".cq-draft-body").dblclick()
        first_draft.locator("textarea").fill("This tab discards these words.")
        first.keyboard.press("Escape")
        assert second.evaluate(
            """() => JSON.parse(
              sessionStorage.getItem('cq-draft:edit:draft-ops')
            ).text"""
        ) == ""

        second.reload(wait_until="networkidle")
        second.wait_for_function("() => document.body.dataset.cqUpgraded === '1'")
        expect(second_draft.locator("textarea")).to_be_visible()
        expect(second_draft.locator("textarea")).to_have_value("")
        events = [
            json.loads(line)
            for line in (serve.page_dir / "comments.jsonl").read_text().splitlines()
            if '"kind": "action"' in line
        ]
        assert [event["detail"]["text"] for event in events] == [sent]
        assert first_errors == []
        assert second_errors == []
    finally:
        context.close()


def test_text_alignment_is_lossless_and_keeps_a_shared_spine(browser, serve):
    """The draft renderer is allowed to choose where an ambiguous repeated word
    aligns, but never to lose or invent a character. The two projections are the
    contract: same+delete is the old text, same+insert the new one. Unicode,
    whitespace and repetition are where a character or regex diff quietly breaks."""
    page, errors = open_page(browser, serve(JOURNEY_V1))
    cases = [
        ("", ""),
        ("one line", "one longer line"),
        ("first\nsecond  line", "first\nsecond line\nthird"),
        ("l’écran est prêt 😀", "l’écran était prêt 🟢"),
        ("迁移完成。再次迁移。", "迁移完成。回滚完成。"),
        ("Retry once. Retry once. Then stop.", "Retry once. Retry twice. Then stop."),
        (
            "shared " + " ".join(f"old-{i}" for i in range(2500)) + " ending",
            "shared " + " ".join(f"new-{i}" for i in range(2500)) + " ending",
        ),
    ]
    aligned = page.evaluate(
        """async (pairs) => {
          const {alignText} = await import('/colloquy.js');
          return pairs.map(([before, after]) => alignText(before, after));
        }""",
        cases,
    )
    for (before, after), runs in zip(cases, aligned):
        assert "".join(run["text"] for run in runs if run["kind"] != "insert") == before
        assert "".join(run["text"] for run in runs if run["kind"] != "delete") == after
        assert all(a["kind"] != b["kind"] for a, b in zip(runs, runs[1:]))

    repeated = aligned[-2]
    assert "".join(r["text"] for r in repeated if r["kind"] == "delete") == "once"
    assert "".join(r["text"] for r in repeated if r["kind"] == "insert") == "twice"
    assert "Then stop." in "".join(r["text"] for r in repeated if r["kind"] == "same")
    assert [run["kind"] for run in aligned[-1]] == ["same", "delete", "insert", "same"]
    assert errors == []
    page.close()


def test_a_draft_explains_its_change_and_restores_history_as_an_edit(browser, serve):
    """One disclosure answers both deferred draft asks. It compares this version's
    authored body with the standing body, retains every absolute edit in log order,
    and walks back by posting another ordinary edit. A second tab proves restore is
    durable replay rather than local history state; copy mode proves the generated
    controls do not survive without their handlers."""
    page, errors = open_page(browser, serve(JOURNEY_V1))
    draft = page.locator("#draft-ops")
    edits = [
        "Run the migration before deploying. It takes one minute.",
        "Run the migration after the backup. It takes two minutes.",
    ]
    for index, text in enumerate(edits, 1):
        draft.locator(".cq-draft-body").dblclick()
        draft.locator("textarea").fill(text)
        draft.get_by_role("button", name="Save").click()
        expect(draft.locator(".cq-draft-history > summary")).to_have_text(
            f"Changes · {index} {'edit' if index == 1 else 'edits'}"
        )

    draft.locator(".cq-draft-history > summary").click()
    current_deleted = "".join(draft.locator(".cq-draft-current del").all_inner_texts())
    current_inserted = "".join(draft.locator(".cq-draft-current ins").all_inner_texts())
    assert "before" in current_deleted and "deploying" in current_deleted
    assert "afterthebackup" in re.sub(r"\s+", "", current_inserted)
    labels = draft.locator(".cq-draft-revision-head strong").all_inner_texts()
    assert labels == ["Version text", "Edit 1 · v1", "Edit 2 · v1"]
    # Adjacent recorded edits are aligned too, rather than rendered as two unrelated
    # snapshots. The first has no knowable predecessor on a later pinned version.
    second_delta = draft.locator(".cq-draft-revisions > li").nth(2)
    second_deleted = "".join(second_delta.locator("del").all_inner_texts())
    second_inserted = "".join(second_delta.locator("ins").all_inner_texts())
    assert "before" in second_deleted and "deploying" in second_deleted
    assert "afterthebackup" in re.sub(r"\s+", "", second_inserted)

    page.evaluate("document.documentElement.classList.add('cq-copy')")
    expect(draft.locator(".cq-draft-history")).not_to_be_visible()
    expect(draft.locator(".cq-draft-controls")).not_to_be_visible()
    expect(draft.locator(".cq-draft-body")).to_be_visible()
    page.evaluate("document.documentElement.classList.remove('cq-copy')")

    draft.get_by_role("button", name="Restore edit 1 · v1").focus()
    page.keyboard.press("Enter")
    expect(draft.locator(".cq-draft-body")).to_have_text(edits[0])
    expect(draft.locator(".cq-draft-history > summary")).to_have_text("Changes · 3 edits")
    expect(draft.locator(".cq-draft-history > summary")).to_be_focused()
    expect(draft).to_have_attribute("data-cq-pending", "1")

    events = [
        json.loads(line)
        for line in (serve.page_dir / "comments.jsonl").read_text().splitlines()
        if '"kind": "action"' in line
    ]
    assert [event["detail"]["text"] for event in events] == [edits[0], edits[1], edits[0]]
    assert [event["action"] for event in events] == ["edit", "edit", "edit"]

    sequence = page.evaluate(
        """async () => {
          const {actionSequence} = await import('/colloquy.js');
          const widget = document.getElementById('draft-ops');
          const first = actionSequence(widget, 'edit');
          first[0].detail.text = 'A widget must not mutate the runtime log.';
          return actionSequence(widget, 'edit')
            .map(event => [event.seq, event.detail.text]);
        }"""
    )
    assert [text for _, text in sequence] == [edits[0], edits[1], edits[0]]
    assert [seq for seq, _ in sequence] == sorted(seq for seq, _ in sequence)

    other, other_errors = open_page(browser, page.url)
    expect(other.locator("#draft-ops .cq-draft-body")).to_have_text(edits[0])
    expect(other.locator("#draft-ops .cq-draft-history > summary")).to_have_text(
        "Changes · 3 edits"
    )
    assert errors == []
    assert other_errors == []
    other.close()
    page.close()


def test_action_history_is_bounded_by_the_pinned_version(browser, serve):
    """A historical page cannot narrate an edit that had not happened yet. The
    helper owns the same version boundary replay does, so every future widget that
    consumes a sequence gets this right without copying the filter."""
    url = serve(JOURNEY_V1)
    d = serve.page_dir
    for version, text in ((1, "First recorded body."), (2, "Second recorded body.")):
        if version == 2:
            (d / "versions" / "v2.html").write_text(JOURNEY_V2)
            interact.append_event(
                d, {"kind": "note", "author": "claude", "version": 2, "text": "v2"}
            )
        interact.append_event(
            d,
            {
                "kind": "action",
                "author": "user",
                "version": version,
                "widget": "draft-ops",
                "action": "edit",
                "detail": {"text": text},
            },
        )

    old, old_errors = open_page(browser, url, pin=True)
    expect(old.locator("#draft-ops .cq-draft-history > summary")).to_have_text(
        "Changes · 1 edit"
    )
    old_sequence = old.evaluate(
        """async () => (await import('/colloquy.js'))
          .actionSequence(document.getElementById('draft-ops'), 'edit')
          .map(event => event.version)"""
    )
    assert old_sequence == [1]

    latest, latest_errors = open_page(browser, url.replace("v1.html", "v2.html"), pin=True)
    expect(latest.locator("#draft-ops .cq-draft-history > summary")).to_have_text(
        "Changes · 2 edits"
    )
    latest_sequence = latest.evaluate(
        """async () => (await import('/colloquy.js'))
          .actionSequence(document.getElementById('draft-ops'), 'edit')
          .map(event => event.version)"""
    )
    assert latest_sequence == [1, 2]
    assert old_errors == []
    assert latest_errors == []
    old.close()
    latest.close()


def test_a_decision_claude_has_seen_still_survives_the_next_version(browser, serve):
    """The round trip above, differing in one fact: `review wait` has handed the actions
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
    # What `review wait` writes on its way out: everything so far is Claude's to answer.
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


def test_a_comment_written_on_an_edited_draft_lands_on_their_words(browser, serve):
    """`review comment` reads the version file plus the log; the reviewer's tab reads
    the DOM replay builds from the same two. An edited draft is where those readings
    used to drift — the file holds words the page stopped showing — so write the anchor
    blind, on the reviewer's own words, and prove the page paints it. The words the edit
    replaced are refused at the CLI, naming the edit, because posted they would detach
    in front of the reviewer."""
    url = serve(JOURNEY_V1)
    d = serve.page_dir
    interact.append_event(d, {"kind": "action", "author": "user", "version": 1,
                              "widget": "draft-ops", "action": "edit",
                              "detail": {"text": DRAFT_EDITED}})
    refused = CliRunner().invoke(
        interact.cli, ["review", "comment", str(d), "--quote", "It is online.", "--text", "x"]
    )
    assert refused.exit_code != 0 and "rewrote § draft-ops" in refused.output
    written = CliRunner().invoke(
        interact.cli,
        ["review", "comment", str(d), "--quote", "It takes about a minute.", "--text", "Measured where?"],
        catch_exceptions=False,
    )
    assert written.exit_code == 0, written.output

    page, errors = open_page(browser, url)
    page.wait_for_function("() => (CSS.highlights.get('cq-mark')?.size ?? 0) > 0")
    thread = page.locator(".cq-thread .cq-quote").first
    expect(thread).not_to_have_class(re.compile(r"\bdetached\b"))
    assert painted(page, "cq-mark") == "It takes about a minute."
    assert errors == []
    page.close()


# The two presses this asks about, on one page: a draft's ✎ (a thing to do) and a pick
# mark (a thing to do that becomes a thing the page says once it is pressed).
KEYS_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>keys</title>
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<h1 id="h">Session store</h1>
<cq-options id="opts" choose>
  <cq-option id="opt-keep"><strong>Keep the store</strong> Sessions stay where they are.</cq-option>
  <cq-option id="opt-token"><strong>Signed tokens</strong> No store at all.</cq-option>
</cq-options>
<cq-draft id="draft-ops">
    Run the migration before deploying.
</cq-draft>
</main>
</body>
</html>
"""


def test_a_press_takes_the_keys_a_button_came_with(browser, serve):
    """A press is a span wearing role="button" (`offer`), so Enter and Space are the
    runtime's to supply — and it supplies them once, for every widget, which is why this
    is one test rather than a leg in each widget's own. What it has to get right is the
    two things a real <button> did for free.

    Activation: the ✎ on a draft is the door a keyboard reviewer uses, and if a span
    swallowed Enter there would be no way in at all.

    And once per press however long the key is held. A real button fired on keyup; a
    keydown listener hears the key repeat, and a mark that toggles per repeat posts a
    `choose` per repeat — a stuck key filling the log with decisions the reviewer never
    made. Repeats are dispatched rather than driven, because no automation holds a key
    down; what the browser delivers is exactly this event with `repeat` set."""
    page, errors = open_page(browser, serve(KEYS_PAGE))

    page.locator("#draft-ops .cq-draft-pencil").focus()
    page.keyboard.press("Enter")
    expect(page.locator("#draft-ops textarea")).to_be_focused()
    page.keyboard.press("Escape")

    mark = page.locator("#opts .cq-pick").first
    mark.focus()
    page.keyboard.press(" ")
    expect(page.locator("#opts > cq-option[chosen]")).to_have_count(1)
    chosen = page.locator("#opts > cq-option[chosen]").get_attribute("id")
    mark.evaluate("""el => {
        for (let i = 0; i < 5; i++)
            el.dispatchEvent(new KeyboardEvent('keydown',
                {key: ' ', repeat: true, bubbles: true, cancelable: true}));
    }""")
    expect(page.locator(f"#{chosen}[chosen]")).to_have_count(1)
    sent = [
        json.loads(line)
        for line in (serve.page_dir / "comments.jsonl").read_text().splitlines()
    ]
    assert [e for e in sent if e.get("action") == "choose"] != [], (
        "the first press sent nothing, so the repeats below had nothing to duplicate"
    )
    assert len([e for e in sent if e.get("action") == "choose"]) == 1, (
        "a held key sent one decision per repeat"
    )
    assert errors == []
    page.close()


def test_global_shortcuts_leave_browser_navigation_keys_alone(browser, serve):
    """The document-level dispatcher owns a few single-character shortcuts, not the
    keyboard. In particular, Space, arrows, Home/End, and PageUp/PageDown must reach
    the browser when focus is in the authored page rather than a widget control.

    Observe `defaultPrevented` on real key events instead of asserting that Chrome
    happened to scroll: scrolling depends on viewport and focus geometry, while
    canceling the event is the runtime decision under test. `?` is the positive
    control proving this observer sees a key the dispatcher intentionally consumes."""
    page, errors = open_page(browser, serve(KEYS_PAGE))
    keys = [
        " ",
        "ArrowUp",
        "ArrowDown",
        "ArrowLeft",
        "ArrowRight",
        "Home",
        "End",
        "PageUp",
        "PageDown",
        "?",
    ]
    page.evaluate(
        """keys => {
          const pageContent = document.querySelector("main");
          pageContent.tabIndex = -1;
          pageContent.focus();
          window.cqObservedKeys = {};
          document.addEventListener("keydown", event => {
            if (keys.includes(event.key))
              window.cqObservedKeys[event.key] = event.defaultPrevented;
          });
        }""",
        keys,
    )
    for key in keys:
        page.keyboard.press(key)

    observed = page.evaluate("() => window.cqObservedKeys")
    assert observed.pop("?") is True, (
        "the positive-control shortcut was not consumed, so the probe did not "
        "observe the runtime dispatcher"
    )
    assert observed == dict.fromkeys(keys[:-1], False)
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
        interact.cli, ["version", "publish", str(d), "--version", "4", "--text", "again"]
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


def test_chrome_is_safe_during_the_registry_fetch(browser, serve):
    """The chrome is wired before the asynchronous registry fetch completes.
    That interval is real state, not a missing-registry fallback: general
    Comments remains usable, but an anchored comment waits until upgrades have
    made the page's final words. The explicit gate proves each assertion runs on
    the intended side of the fetch rather than racing a timer."""
    gate_registry = """
      const nativeFetch = window.fetch.bind(window);
      window.cqRegistryGate = new Promise(resolve => window.cqReleaseRegistry = resolve);
      window.fetch = (...args) => {
        const input = args[0];
        const url = typeof input === 'string' ? input : input.url;
        if (new URL(url, location.href).pathname === '/registry.json') {
          window.cqRegistryBlocked = true;
          return window.cqRegistryGate.then(() => nativeFetch(...args));
        }
        return nativeFetch(...args);
      };
    """
    html = JOURNEY_V1.replace(
        '<h2 id="notes">',
        """
<cq-milestones>
  <cq-milestone id="gate-milestone" status="active" tags="wood,solar">
    <strong>Build feeders</strong> Two classic models.
  </cq-milestone>
</cq-milestones>
<h2 id="notes">""",
    )
    page, errors = open_page(
        browser,
        serve(html, anchored=[("intro", SENTENCE)]),
        init_script=gate_registry,
        wait_until="domcontentloaded",
    )
    page.wait_for_function("() => window.cqRegistryBlocked === true")
    expect(page.locator("#gate-milestone .cq-chips")).to_have_count(0)
    expect(page.locator("#draft-ops .cq-draft-body")).to_have_count(0)

    page.get_by_role("button", name=re.compile("^Comments")).click()
    expect(page.locator(".cq-panel")).to_have_class(re.compile("open"))
    page.locator(".cq-general textarea").fill("General comment during startup")
    page.locator(".cq-general").get_by_role("button", name="Send").click()
    expect(page.locator(".cq-thread")).to_have_count(2)
    assert page.evaluate("() => CSS.highlights.get('cq-mark')?.size ?? 0") == 0

    page.locator("#gate-milestone").select_text()
    page.keyboard.press("c")
    expect(page.locator(".cq-composer")).to_be_hidden()

    page.evaluate("window.cqReleaseRegistry()")
    expect(page.locator("#gate-milestone .cq-chips")).to_have_count(1)
    page.wait_for_function("() => (CSS.highlights.get('cq-mark')?.size ?? 0) > 0")
    expect(page.locator(".cq-fab")).to_be_visible()
    page.locator(".cq-fab").click()
    page.locator(".cq-composer textarea").fill("Still anchored?")
    page.locator(".cq-composer").get_by_role("button", name="Comment").click()

    expect(page.locator(".cq-thread")).to_have_count(3)
    expect(page.locator(".cq-thread .cq-quote.detached")).to_have_count(0)
    assert errors == []
    page.close()


def test_overlapping_polls_never_move_the_log_backwards(browser, serve):
    """A post-triggered poll and the timer can overlap. The append-only event
    sequence makes an older response unambiguously stale."""
    delay_second_state = """
      const nativeFetch = window.fetch.bind(window);
      let stateCalls = 0;
      window.fetch = async (...args) => {
        const input = args[0];
        const url = typeof input === 'string' ? input : input.url;
        const response = await nativeFetch(...args);
        if (new URL(url, location.href).pathname !== '/api/state') return response;
        stateCalls += 1;
        if (stateCalls !== 2) return response;
        const body = await response.text();
        window.cqDelayedPollCaptured = true;
        await new Promise(resolve => setTimeout(resolve, 3000));
        window.cqDelayedPollReleased = true;
        return new Response(body, {
          status: response.status,
          statusText: response.statusText,
          headers: response.headers,
        });
      };
    """
    page, errors = open_page(
        browser,
        serve(JOURNEY_V1),
        init_script=delay_second_state,
    )
    page.get_by_role("button", name=re.compile("^Comments")).click()
    page.locator(".cq-general textarea").fill("Starts the slow poll")
    page.locator(".cq-general button").click()
    page.wait_for_function("() => window.cqDelayedPollCaptured === true")

    interact.append_event(
        serve.page_dir,
        {
            "kind": "comment",
            "id": "newest-snapshot",
            "author": "user",
            "version": 1,
            "text": "Newest snapshot stays rendered",
        },
    )
    expect(page.locator(".cq-thread", has_text="Newest snapshot stays rendered")).to_have_count(
        1, timeout=5000
    )
    page.wait_for_function("() => window.cqDelayedPollReleased === true")
    expect(page.locator(".cq-thread", has_text="Newest snapshot stays rendered")).to_have_count(1)
    assert errors == []
    page.close()


def test_the_help_overlay_answers_to_one_owner(browser, serve):
    """Open or closed is state with one writer now — it was three writers and
    two classList read-backs, the exact shape the first norm forbids. Exact
    registrations deduplicate without making display text a lossy identity."""
    html = JOURNEY_V1.replace(
        "</main>",
        '<cq-draft id="draft-second">A second editable draft.</cq-draft></main>',
    )
    page, errors = open_page(browser, serve(html))
    page.evaluate(
        """async () => {
          const { keyHelp } = await import('/colloquy.js');
          keyHelp('On a draft', [['F2', 'a project widget using the same heading']]);
        }"""
    )
    page.keyboard.press("?")
    expect(page.locator(".cq-help")).to_be_visible()
    expect(page.locator(".cq-help h3", has_text="On a draft")).to_have_count(2)
    expect(page.locator(".cq-help", has_text="a project widget using the same heading")).to_be_visible()
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
    """Bump heartbeat.json for the duration of the block, as `review wait` does."""
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

    def declare(state, detail="", *, agent="Claude", handoff=False, quiet_for=0, session_pid=None):
        ts = datetime.now().astimezone() - timedelta(seconds=quiet_for)
        status = {"state": state, "detail": detail, "ts": ts.isoformat(timespec="seconds")}
        if handoff:
            status["handoff"] = True
        interact.write_json(
            d / "session.json",
            {"id": "s", "pid": session_pid or os.getpid(), "agent": agent, "ts": "t"},
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

    # The failure the whole mechanism exists for: `review wait` delivered, set this
    # status, and Claude never came back. The handoff mark is what dates it.
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

    declare("working", "revising the plan", agent="Codex")
    expect(text).to_have_text(re.compile(r"^Codex is working — revising the plan"))

    declare("idle")
    expect(text).to_have_text("Review closed")
    page.close()


# ---------- anchors written without a browser ----------
# `review comment` writes an anchor by reading the version file; the runtime resolves it
# against the DOM that file becomes. Nothing static can check that those two readings
# agree, and every way they can come apart — a widget's upgrade, an attribute rendered
# as text, the space a block boundary stands for — only exists once the page is loaded.


def written_anchors(page_dir, html, limit=40):
    """Anchors `review comment` would write for windows over a page's own prose. A
    window the page says twice, or one crossing a fence, is refused on purpose —
    skipping those here is that refusal, and what survives is exactly what the command
    promises to place."""
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
    """The claim `review comment` makes is that a quote read out of the version file
    names the same passage in the browser. Checked on the pages people actually write,
    because the ways it can fail are all theirs: a diagram that renders to a picture, an
    attribute the runtime turns into text, two paragraphs whose join is a space in one
    reading and nothing in the other."""
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
        ["review", "comment", str(d), "--quote", "The version stamp never lands", "--text", "capped where?"],
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


def test_a_written_comment_keeps_its_originating_agent(browser, serve):
    """An agent's side of a thread is the reviewer's side with the author flipped.
    Its label belongs to the message, so another host claiming the page later
    cannot rewrite who said it."""
    url = serve(TWIN_V1)
    d = serve.page_dir
    interact.write_json(
        d / "session.json",
        {"id": "codex", "pid": os.getpid(), "agent": "Codex", "ts": "t"},
    )
    assert CliRunner().invoke(
        interact.cli,
        ["review", "comment", str(d), "--quote", "Retries are capped at three", "--text", "is three right?"],
    ).exit_code == 0
    interact.write_json(
        d / "session.json",
        {"id": "claude", "pid": os.getpid(), "agent": "Claude", "ts": "t"},
    )
    page, errors = open_page(browser, url)
    page.wait_for_function("() => (CSS.highlights.get('cq-mark')?.size ?? 0) > 0")
    toggle = page.locator("button[aria-expanded]")
    expect(toggle).to_have_text("Comments (1)")  # counted as open, like any other thread
    toggle.click()
    thread = page.locator(".cq-thread").first
    expect(thread.locator(".cq-msg.claude .cq-msg-head b")).to_have_text("Codex")
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


def test_a_reply_toast_keeps_its_originating_agent(browser, serve):
    url = serve(TWIN_V1)
    d = serve.page_dir
    root = interact.append_event(
        d,
        {
            "kind": "comment",
            "author": "user",
            "version": 1,
            "text": "which host answers?",
        },
    )
    interact.write_json(
        d / "session.json",
        {"id": "claude", "pid": os.getpid(), "agent": "Claude", "ts": "t"},
    )
    page, errors = open_page(browser, url)
    expect(page.locator("button[aria-expanded]")).to_have_text("Comments (1)")

    interact.append_event(
        d,
        {
            "kind": "reply",
            "author": "claude",
            "agent": "Codex",
            "parent": root["id"],
            "text": "this one does",
        },
    )
    expect(page.locator(".cq-toast")).to_have_text(
        "Codex replied — open Comments",
        timeout=5000,
    )
    assert errors == []
    page.close()


PICTURE_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>pictures</title>
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<h1 id="t">Pictures</h1>
<p id="p">Two renderings, neither of them the page's own words.</p>
<cq-diagram id="flow">
graph LR
  A --> B
</cq-diagram>
<cq-tree id="tree">
feeders/
  mount.py  +2 -2
</cq-tree>
</main>
</body>
</html>
"""


def test_a_widget_declaring_it_renders_a_picture_takes_a_click(browser, serve):
    """A rendering has no text of the page's in it to select, so the click anchors on the
    whole element. Which widgets those are is theirs to declare (x-visual): the runtime
    names none of them, so a widget added to the vocabulary is clickable on the strength
    of its entry — the failure this rules out is the quiet one, where a consumer taught
    one widget by name keeps working on that widget and does nothing for the next."""
    url = serve(PICTURE_PAGE)
    registry = json.loads((serve.page_dir / "registry.json").read_text())
    assert registry["cq-diagram"]["x-visual"], "this test needs the shipped declaration"
    registry["cq-tree"]["x-visual"] = True  # a widget the runtime has never heard of
    (serve.page_dir / "registry.json").write_text(json.dumps(registry))
    page, errors = open_page(browser, url)

    # The inner svg is mermaid's, carrying a generated id; the anchor belongs to the
    # widget that holds it, which is the element the page gave a name.
    page.locator("#flow svg").click()
    page.locator(".cq-fab").click()
    page.locator("#flow.cq-mark-el.cq-pending").wait_for()
    assert not composer_quote(page)["shown"], "a picture has no words to quote back"
    page.get_by_role("button", name="Cancel").click()

    page.locator("#tree").click()
    page.locator(".cq-fab").click()
    page.locator("#tree.cq-mark-el.cq-pending").wait_for()
    page.get_by_role("button", name="Cancel").click()

    # And a paragraph is still text: the click reaches no picture and raises nothing.
    page.locator("#p").click()
    assert not page.locator(".cq-fab").is_visible(), (
        "a click on prose was read as a click on a picture"
    )
    assert errors == []
    page.close()


def test_the_handed_over_url_opens_the_latest_version(browser, serve):
    """The URL `server run` prints is the page root carrying the key, so every handover
    arrives through the redirect to the latest version rather than at a version file.
    Two things have to hold across that hop and only a real browser can say so: the
    cookie is set on the redirect and sent on the request it redirects to, and it is
    still sent once the page is polling — the runtime's own fetches are relative, and a
    `SameSite` cookie the browser withheld from them would leave the page open and
    frozen with no console error to show for it."""
    url = serve(INLINE_PAGE)
    root = url.rsplit("/versions/", 1)[0] + f"/?t={TOKEN}"

    page, errors = open_page(browser, root)

    expect(page).to_have_url(url.rsplit("?", 1)[0])
    expect(page.locator(".cq-banner")).to_be_visible()
    # The poll is the page's own fetch, relative and query-less: it answers only if the
    # cookie rode along.
    assert page.evaluate("() => fetch('/api/state').then(r => r.status)") == 200

    # The version switcher and the latest chip leave the document by assigning
    # location.href, which is a fresh top-level navigation carrying no query. A cookie
    # the browser withheld from it would land the reviewer on a refusal.
    page.evaluate("() => { location.href = '/' }")
    page.wait_for_url(url.rsplit("?", 1)[0])
    expect(page.locator(".cq-banner")).to_be_visible()

    assert errors == []
    page.close()


def test_a_page_refuses_a_browser_that_never_had_the_link(browser, serve):
    url = serve(INLINE_PAGE)

    page = browser.new_page()
    page.goto(url.rsplit("?", 1)[0], wait_until="load")

    assert "carries this page's key" in page.locator("body").inner_text()
    page.close()


# ---------- export: the page as one file ----------


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda p: p.stem)
def test_an_exported_example_stands_on_its_own(example, browser, serve, tmp_path):
    """Every shipped example copied to a file and opened from disk, which is the whole
    contract: no server answers, so anything still reaching for one is a hole, and the
    console is where a hole says so. Driven over the corpus rather than one page because
    what a copy loses is per-widget — the gallery alone would pass while the widget only
    it lacks was the broken one."""
    url = serve(example.read_text())
    out = tmp_path / "standalone.html"
    out.write_text(interact.export_page(browser, url, serve.page_dir))

    errors = []
    page = browser.new_page(viewport={"width": 1200, "height": 900})
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("requestfailed", lambda r: errors.append(f"unfetched {r.url}"))
    page.goto(out.as_uri(), wait_until="load")
    state = page.evaluate("""() => ({
        scripts: document.querySelectorAll('script').length,
        chrome: document.querySelectorAll('.cq-chrome').length,
        toServer: [...document.querySelectorAll('[src^="/"], [href^="/"]')]
            .map(e => e.getAttribute('src') ?? e.getAttribute('href')),
        links: document.querySelectorAll('link[rel="stylesheet"]').length,
        column: getComputedStyle(document.querySelector('main')).maxWidth,
        unshown: [...document.querySelectorAll('main *')]
            .filter(el => el.textContent.trim() && !el.checkVisibility()
                          // A disclosure the reader can still work, a control's own
                          // label, and an element with no box by design are all fine;
                          // what is not is the page's words with nothing to reveal them.
                          && !el.closest('details, [data-cq-offer], .cq-ui, style, script')
                          && getComputedStyle(el).display !== 'contents')
            .map(el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '')),
    })""")
    # The gate's own reading, on the medium that most needs it: a copy is laid out by
    # rules no other medium runs, and the last two ways one went out wrong were both a
    # widget's words landing on the page's.
    covered = page.evaluate(interact.COVERED_WORDS)
    page.close()

    assert state["scripts"] == 0, "a copy with no server behind it keeps no script"
    assert state["chrome"] == 0, (
        "the runtime's layer came along — a comment box that swallows what you type"
    )
    assert state["toServer"] == [], "the copy still points at a server that isn't there"
    assert state["links"] == 0, "a stylesheet link survived, pointing at nothing"
    assert state["column"] != "none", "the theme didn't inline; the copy opens unstyled"
    assert state["unshown"] == [], (
        "the copy says less than the page did: content sitting behind a control that "
        f"needed a handler, and nothing in a file can press one — {state['unshown']}"
    )
    assert covered == [], f"the copy draws its own words over each other: {covered}"
    assert errors == [], f"{example.stem} needs a server to render: {errors}"
