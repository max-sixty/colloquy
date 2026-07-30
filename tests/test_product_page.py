"""The product pages use the shipped theme and widget vocabulary directly."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
ASSETS = ROOT / "plugins" / "colloquy" / "skills" / "colloquy" / "assets"
DOCS = ROOT / "docs"


def test_docs_pages_link_the_shipped_theme():
    target = "../plugins/colloquy/skills/colloquy/assets/theme.css"
    assert (ASSETS / "theme.css").is_file()
    for page in DOCS.glob("*.html"):
        assert f'<link rel="stylesheet" href="{target}">' in page.read_text()


def test_docs_pages_use_only_registered_widgets():
    registry = json.loads((ASSETS / "registry.json").read_text())
    used = {
        tag
        for page in DOCS.glob("*.html")
        for tag in re.findall(r"<(cq-[a-z-]+)", page.read_text())
    }
    assert used and used <= set(registry)


def test_customizing_guide_sits_beside_how_it_works():
    customizing = (DOCS / "customizing.html").read_text()
    assert 'href="how-it-works.html"' in customizing
    for source in ("index.html", "how-it-works.html"):
        assert 'href="customizing.html"' in (DOCS / source).read_text()


def test_customizing_guide_uses_the_current_layer_and_cli_names():
    customizing = (DOCS / "customizing.html").read_text()

    assert ".claude/colloquy" not in customizing
    assert "<code>.colloquy/</code>" in customizing
    for stale in (
        "colloquy init ",
        "colloquy catalog ",
        "colloquy check ",
    ):
        assert stale not in customizing
    for current in (
        "colloquy page init ",
        "colloquy page catalog ",
        "colloquy version check ",
    ):
        assert current in customizing
