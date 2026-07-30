"""The product pages use the shipped theme and widget vocabulary directly."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
ASSETS = ROOT / "skills" / "colloquy" / "assets"
DOCS = ROOT / "docs"


def test_docs_pages_link_the_shipped_theme():
    target = "../skills/colloquy/assets/theme.css"
    assert (ROOT / "skills" / "colloquy" / "assets" / "theme.css").is_file()
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
