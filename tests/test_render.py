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

Chrome is driven through Playwright's `channel="chrome"`, which attaches to the
installed browser: no download, no build step, `uv` still the one prerequisite.
"""

import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from click.testing import CliRunner
from playwright.sync_api import sync_playwright

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
        return f"http://127.0.0.1:{httpd.server_address[1]}/versions/v001.html"

    servers = []
    yield go
    for httpd in servers:
        httpd.shutdown()


def open_page(browser, url):
    """A page with its console errors collected, settled enough for mermaid."""
    page = browser.new_page(viewport={"width": 1200, "height": 900})
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
    """Every shipped example loads clean and lays out: no fail-soft error box, no
    console error, and every visible widget occupies real space. A widget that
    upgrades into a 1x1 box is the shape of failure a static lint cannot see."""
    page, errors = open_page(browser, serve(example.read_text()))

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
