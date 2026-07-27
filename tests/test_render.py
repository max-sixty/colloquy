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


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        yield b
        b.close()


@pytest.fixture
def serve(tmp_path, monkeypatch):
    """Publish HTML as v001 of a fresh page directory and serve it, as the real
    server does — vendoring included, so the assets under test are this repo's."""

    def go(html, comments=0, anchored=()):
        monkeypatch.chdir(tmp_path)  # keep the project layer out of the overlay
        d = tmp_path / "page"
        assert CliRunner().invoke(interact.cli, ["init", str(d)]).exit_code == 0
        (d / "versions" / "v001.html").write_text(html)
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
        return f"http://127.0.0.1:{httpd.server_address[1]}/versions/v001.html"

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
    space, no sideways scroll. A widget that upgrades into a 1x1 box is the
    shape of failure a static lint cannot see. The invariants themselves live in
    interact.render_version — the pass `check --render` runs on agent-authored
    pages — so this sweep also proves the gate a reviewer's page goes through."""
    assert interact.render_version(browser, serve(example.read_text())) == []


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
    (d / "versions" / "v002.html").write_text(
        LONG_PAGE.replace("</main>", "<div style='width:150vw'>wide</div>\n</main>")
    )
    broken = gate("--version", "2")
    assert broken.returncode == 1
    assert "scrolls sideways" in broken.stderr


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

    # The exhibit rendered: the gutter's label, and cards with real size.
    assert page.locator("#spec").evaluate(
        "el => getComputedStyle(el, '::before').content"
    ) == '"specimen · a decision"'
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

    # The control: the same markup unquoted wires all of it.
    assert page.locator("#live-group button.cq-pick").count() == 2
    assert page.locator("#live-board .cq-grip").count() == 1

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
    # document's column, and neither is the label.
    assert page.locator("#rp-spec").evaluate(
        "el => getComputedStyle(el, '::before').content"
    ) == '"specimen · the April thread"'
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


def test_composer_marks_the_passage_it_is_quoting(browser, serve):
    """The passage stays visible while its comment is written. Focus moves into the
    composer the moment it opens, which drops the browser's own selection, so the
    runtime paints the anchor itself, and repaints it after every pass that redraws
    the posted threads' marks around it — otherwise a comment arriving mid-sentence
    would leave the reader's passage stranded across stale text nodes. It comes down
    with the box, and the whole time it never touches the document."""
    url = serve(INLINE_PAGE)
    page, errors = open_page(browser, url)

    page.locator("#p").click(click_count=3)  # a real selection, spanning the inline tags
    page.locator(".cq-fab").click()
    page.wait_for_function("() => document.querySelector('.cq-composer').style.display === 'block'")

    passage = " ".join(page.locator("#p").inner_text().split())
    quoted = page.evaluate("() => document.querySelector('.cq-composer-quote').textContent")
    assert pending_text(page) == passage, (
        f"the page marks {pending_text(page)!r}, but the composer is quoting {quoted!r}"
    )

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
                const quoted = document.querySelector('.cq-composer-quote').textContent;
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
    stranded = page.locator(".cq-quote.detached").all_text_contents()
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
    assert page.locator(".cq-quote.detached").count() == 1, (
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

    compose_on("#p")  # authored across two source lines
    wrapped = page.evaluate("() => document.querySelector('.cq-composer-quote').textContent")
    assert "\n" not in wrapped, f"the quote carries the source's line wrap: {wrapped!r}"
    page.get_by_role("button", name="Cancel").click()

    # Measured in the page: a lone surrogate does not survive the trip out to the test
    # runner, which replaces it, so asking out here would always come back clean.
    # Iterating by code point, a character cut in half is left as a single unit in the
    # surrogate range; an intact one comes through as the pair it is.
    compose_on("#cap")
    assert not page.evaluate("""() => [...document.querySelector('.cq-composer-quote').textContent]
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
    (d / "versions" / "v002.html").write_text(INLINE_PAGE.replace("<h1 id=\"t\">Inline</h1>",
                                                                 "<h1 id=\"t\">Inline II</h1>"))
    interact.append_event(d, {"kind": "note", "author": "claude", "version": 2, "text": "two"})
    page.wait_for_url("**/v002.html", timeout=15000)
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
    stranded = page.locator(".cq-quote.detached").all_text_contents()
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
    (d / "versions" / "v002.html").write_text(DRIFT_V2)
    interact.append_event(d, {"kind": "note", "author": "claude", "version": 2, "text": "revised"})
    page.wait_for_url("**/v002.html", timeout=15000)
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
    (d / "versions" / "v002.html").write_text(THIN_V2)
    interact.append_event(d, {"kind": "note", "author": "claude", "version": 2, "text": "revised"})
    page.wait_for_url("**/v002.html", timeout=15000)
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
    (d / "versions" / "v002.html").write_text(JOURNEY_V2)
    interact.append_event(d, {"kind": "note", "author": "claude", "version": 2, "text": "moved"})
    page.wait_for_url("**/v002.html", timeout=15000)
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
    assert events[1]["anchor"] == {"section": "intro", "quote": SENTENCE}
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
