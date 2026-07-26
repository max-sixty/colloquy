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
    flashed a scrollbar on every keystroke.

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
from playwright.sync_api import expect, sync_playwright

from conftest import interact

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


def open_page(browser, url, scheme="light"):
    """A page with its console errors collected, settled enough for mermaid."""
    page = browser.new_page(viewport={"width": 1200, "height": 900}, color_scheme=scheme)
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    # The console's own word for a bad response is "Failed to load resource", which
    # names nothing; carry the status and URL so a failure says what went missing.
    page.on("response", lambda r: errors.append(f"{r.status} {r.url}") if r.status >= 400 else None)
    page.goto(url, wait_until="networkidle")
    page.wait_for_function("() => document.querySelector('.cq-banner') !== null")
    return page, errors


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("example", EXAMPLES, ids=lambda p: p.stem)
def test_example_renders(browser, serve, example, scheme):
    """Every shipped example loads clean and lays out: no fail-soft error box, no
    console error, and every visible widget occupies real space. A widget that
    upgrades into a 1x1 box is the shape of failure a static lint cannot see.
    Both color schemes: the dark theme is real CSS nobody otherwise renders."""
    page, errors = open_page(browser, serve(example.read_text()), scheme)

    assert page.locator(".cq-error").count() == 0, page.locator(".cq-error").all_inner_texts()
    assert errors == []

    # [hidden] needs its own exclusion: hidden="until-found" (what a closed tab
    # wears) resolves to content-visibility, which checkVisibility reports as
    # visible while the box measures zero. That collapse is the point of a closed
    # tab; the collapse being hunted here is the one nothing asked for.
    tiny = page.evaluate("""() => [...document.querySelectorAll('*')]
        .filter(el => el.tagName.toLowerCase().startsWith('cq-')
                   && el.textContent.trim()
                   && el.checkVisibility()
                   && !el.closest('[hidden]'))
        .map(el => ({ tag: el.tagName.toLowerCase(), id: el.id,
                      w: Math.round(el.getBoundingClientRect().width),
                      h: Math.round(el.getBoundingClientRect().height) }))
        .filter(box => box.w < 40 || box.h < 10)""")
    assert tiny == [], f"widgets rendered with no usable size: {json.dumps(tiny)}"

    overflow = page.evaluate("document.body.scrollWidth - document.body.clientWidth")
    assert overflow <= 0, f"page scrolls sideways by {overflow}px"
    page.close()


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

    # View state still runs inside a specimen: the settled group collapsed.
    assert page.locator("#quoted-settled cq-option:visible").count() == 0
    page.locator("#quoted-settled .cq-settled").click()
    assert page.locator("#quoted-settled cq-option:visible").count() == 2
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


# The journey's page: a passage to comment on and a board to drag. In v2 the
# commented paragraph moves below the notes heading — same text, new position —
# so the anchor has to re-find its passage rather than replay a location.
SENTENCE = "The version stamp never lands, so migration 0041 replays on every deploy."
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
    comment on it, drag a card to another column, then follow the next version
    and find the comment still anchored to its (relocated) passage. The final
    assertion is the event log — the trail Claude reads — down to the anchor's
    quote and the move's placement."""
    page, errors = open_page(browser, serve(JOURNEY_V1))

    # Select the passage from the keyboard's path: a real Range, then the keyup
    # the runtime watches for keyboard selections, then the c binding — which
    # runs the same composeSelection as the floating button's click.
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
    page.wait_for_selector(".cq-mark")  # the anchor pass wrapped the passage

    # Drag the card between columns through the pointer path — the seam where
    # the vendored SortableJS meets the runtime, which is where drags break.
    grip = page.locator("#card-x .cq-grip").bounding_box()
    dest = page.locator("#col-done").bounding_box()
    page.mouse.move(grip["x"] + grip["width"] / 2, grip["y"] + grip["height"] / 2)
    page.mouse.down()
    page.mouse.move(dest["x"] + dest["width"] / 2, dest["y"] + dest["height"] / 2, steps=15)
    page.mouse.up()
    page.wait_for_selector("#col-done #card-x")  # the drop reparented the card

    # Claude ships v2 with the passage moved; the page follows on its next poll.
    d = serve.page_dir
    (d / "versions" / "v002.html").write_text(JOURNEY_V2)
    interact.append_event(d, {"kind": "note", "author": "claude", "version": 2, "text": "moved"})
    page.wait_for_url("**/v002.html", timeout=15000)
    # The anchor pass runs at render: a mark now means the quote was re-found in
    # its new position; no mark within the wait means the anchor lost it.
    page.wait_for_selector(".cq-mark", timeout=5000)
    assert not page.evaluate(
        "document.querySelector('.cq-thread .cq-quote').classList.contains('detached')"
    ), "the passage moved and the comment lost it"

    assert errors == []
    # The trail those gestures left, exactly — kinds, authorship (the server
    # stamps browser events `user`), the anchor, and the move's placement.
    events = [json.loads(line) for line in (d / "comments.jsonl").read_text().splitlines()]
    assert [(e["kind"], e["author"], e["version"]) for e in events] == [
        ("note", "claude", 1),
        ("comment", "user", 1),
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
