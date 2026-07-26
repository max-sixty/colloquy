"""The product pages (docs/*.html) dogfood the shipped layer: their theme.css
must stay byte-identical to the theme the plugin vendors, and every cq-* tag
they use must exist in the shipped registry."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
ASSETS = ROOT / "skills" / "colloquy" / "assets"
DOCS = ROOT / "docs"


def test_docs_theme_is_the_shipped_theme():
    assert (DOCS / "theme.css").read_bytes() == (ASSETS / "theme.css").read_bytes()


def test_docs_pages_use_only_registered_widgets():
    registry = json.loads((ASSETS / "registry.json").read_text())
    used = {
        tag
        for page in DOCS.glob("*.html")
        for tag in re.findall(r"<(cq-[a-z-]+)", page.read_text())
    }
    assert used and used <= set(registry)
