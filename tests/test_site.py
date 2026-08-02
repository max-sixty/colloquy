"""The published site: what the build assembles, and what a reader gets.

The site is the repo's own pages plus an export of every example, so most of what
could go wrong is a path that meant one thing in a checkout and another on a host.
The build resolves every local link it wrote and stops on one that reaches
nothing, which is the failure a static host answers with a 404 and no other
signal; these tests hold the rest — that the theme a page links is the shipped
file, that an exported example still stands up with its scripts gone, and that a
site claiming to ride the theme's tokens actually changes colour when the
theme's palette does.
"""

import importlib.util
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
ASSETS = ROOT / "plugins" / "colloquy" / "skills" / "colloquy" / "assets"
DOCS = ROOT / "docs"
EXAMPLES = ROOT / "examples"

_spec = importlib.util.spec_from_file_location("site", ROOT / "scripts" / "site.py")
site_build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(site_build)

# The theme's paper, light and dark, as the browser reports a background.
PAPER = {"light": "rgb(250, 249, 245)", "dark": "rgb(25, 24, 21)"}
PHONE = {"width": 390, "height": 844}


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    """One build for the module: it draws nine examples in Chrome."""
    out = tmp_path_factory.mktemp("published") / "site"
    site_build.build(out)
    return out


def test_the_pages_link_the_theme_the_site_serves(site):
    for page in sorted(DOCS.glob("*.html")):
        published = (site / page.name).read_text()
        assert '<link rel="stylesheet" href="theme.css">' in published
        for attribute in ('href="../', 'src="../'):
            assert attribute not in published, f"{page.name} kept a checkout path"
    assert (site / "theme.css").read_text() == (ASSETS / "theme.css").read_text()


def test_every_example_is_published_standalone(site):
    for source in sorted(EXAMPLES.glob("*.html")):
        copy = (site / "examples" / source.name).read_text()
        assert "<script" not in copy, f"{source.name} carries script a host can't serve"
        assert 'href="/theme.css"' not in copy, (
            f"{source.name} still asks for the theme"
        )
        assert 'class="cq-copy"' in copy
        # The theme inlined and the widgets' own output: an example that only
        # copied its source would be a fraction of this.
        assert len(copy) > 40_000


def test_a_link_that_reaches_nothing_stops_the_build(site, tmp_path):
    staged = tmp_path / "staged"
    shutil.copytree(site, staged)
    (staged / "index.html").write_text('<a href="whats-new.html">news</a>')

    with pytest.raises(SystemExit) as stopped:
        site_build.check_links(staged)
    assert "whats-new.html" in str(stopped.value)


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_the_site_takes_its_palette_from_the_theme(site, browser, scheme):
    page = browser.new_page(color_scheme=scheme)
    try:
        for name in sorted(p.name for p in DOCS.glob("*.html")):
            page.goto((site / name).as_uri())
            assert (
                page.evaluate("getComputedStyle(document.body).backgroundColor")
                == (PAPER[scheme])
            ), name
    finally:
        page.close()


def test_the_pages_fit_a_phone(site, browser):
    """Nothing scrolls sideways at 390px — the nav wraps, the screenshots scale,
    and a command too long for the column scrolls inside its own block.

    The site's own pages, not the examples it publishes: a page with a suggestion
    on it hangs the accept/reject controls in the review margin, and at 390px
    there is no margin to hang them in. That is the review page's question rather
    than the site's, and it is not answered here."""
    page = browser.new_page(viewport=PHONE)
    try:
        for name in sorted(p.name for p in DOCS.glob("*.html")):
            page.goto((site / name).as_uri())
            overflow = page.evaluate(
                "() => { const b = document.body;"
                " return b.scrollWidth - b.clientWidth; }"
            )
            assert overflow <= 0, f"{name} scrolls {overflow}px sideways on a phone"
    finally:
        page.close()
