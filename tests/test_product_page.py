"""The product pages use the shipped theme and widget vocabulary directly."""

import json
import re
import subprocess
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
        'actionSequence(this, "verb")',
        'watchActions(this, "verb", render)',
    ):
        assert current in customizing


def test_tour_walks_the_interactive_and_live_workflows():
    tour = (DOCS / "index.html").read_text()

    for example in ("triage-board", "live-progress"):
        assert f'href="../examples/{example}.html"' in tour
        assert f"scripts/preview.py {example}" in tour
    assert (
        '"widget":"release-board","action":"move","detail":{"card":"card-export"'
        in tour
    )
    assert 'src="demo.gif"' in tour

    live = (ROOT / "examples" / "live-progress.html").read_text()
    assert "browser is following the newest version" in live.lower()
    for status in ("done", "active", "planned"):
        assert f'status="{status}"' in live
    assert "<h2>Blocked</h2>" in live


def test_demo_recording_drives_the_browser_journey(tmp_path):
    output = tmp_path / "demo.gif"
    recorded = subprocess.run(
        [ROOT / "scripts" / "record-demo.sh", "--output", output],
        check=True,
        capture_output=True,
        text=True,
    )

    assert recorded.stdout.strip() == f"Recorded {output}"
    assert output.read_bytes().startswith(b"GIF89a")
