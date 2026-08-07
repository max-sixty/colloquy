#!/usr/bin/env python3
"""Assemble the published site (https://max-sixty.github.io/colloquy/) into .tmp/site.

The site is the pages the repo already holds. `docs/` is written to be opened from
a checkout — the theme arrives by a relative path into the plugin payload, and an
example link points at the example — so publishing is three substitutions plus the
files those paths then name. Nothing here templates or generates a page: what is
on the web is the file in the tree, which is why the pages can double as specimens
of the theme.

The examples cannot be copied. An example links /theme.css and /colloquy.js at a
server root, and half of what it says is written by the widget layer in the browser
— a mermaid diagram becomes an SVG only once mermaid has drawn it. So each one is
exported through the shipped path (`page init`, `version publish`,
`version export`), which is Chrome drawing the page and then copying it: the widgets'
own output, the comment layer gone with every script, since there is no session
behind a static host for it to reach.

A dead link is the failure a static host cannot report, so the build resolves every
local href and src it wrote and refuses a site holding one that names no file.

Usage: site.py  (no arguments; writes .tmp/site)
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
COLLOQUY = ROOT / "plugins" / "colloquy" / "bin" / "colloquy"
THEME = ROOT / "plugins" / "colloquy" / "skills" / "colloquy" / "assets" / "theme.css"
DOCS = ROOT / "docs"
EXAMPLES = ROOT / "examples"
OUT = (
    ROOT / ".tmp" / "site"
)  # gitignored; the workflow uploads it as the Pages artifact

REPO = "https://github.com/max-sixty/colloquy"

# The stylesheet is a path into the payload like any other, and the one exception to
# what happens to those: the site serves its own copy rather than sending the reader to
# GitHub. So it is rewritten first and on its own, and the rule has to say *the link
# element's* href — `customizing.html` also links that same file as source to read, and
# a match on the path alone would send a reader after the token block to the stylesheet
# the site serves instead of to the source.
#
# A pattern rather than a literal, because the literal is the same rule with a
# formatter's opinion baked into it. It read as the whole <link> tag until prettier
# started writing the void element `<link … />` and splitting this one over four lines;
# the literal quietly stopped matching, the generic ../plugins/ rule below took the href
# instead, and every page shipped with its stylesheet pointing at a GitHub blob view —
# a link that resolves, so the dead-link check has nothing to say, over a page with no
# theme on it.
THEME_LINK = re.compile(
    rf'(<link\b[^>]*?)"\.\./{re.escape(str(THEME.relative_to(ROOT)))}"'
)

# What a checkout path becomes once the site is one directory, in order. Everything a
# page reaches into the payload for is source to read. Both sides are literal, so a page
# naming something else keeps what it named and the link check below is what notices.
REWRITES = {
    "../plugins/": f"{REPO}/blob/main/plugins/",
    "../examples/": "examples/",
}


class Links(HTMLParser):
    """Every href/src/srcset in a document, in source order."""

    def __init__(self):
        super().__init__()
        self.found: list[str] = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if not value:
                continue
            if name in ("href", "src"):
                self.found.append(value)
            elif name == "srcset":
                self.found += [
                    c.strip().split()[0] for c in value.split(",") if c.strip()
                ]


def local_targets(html: str) -> list[str]:
    """The links a static host has to serve itself: same-origin, and naming a file."""
    parser = Links()
    parser.feed(html)
    targets = []
    for link in parser.found:
        parts = urlsplit(link)
        if parts.scheme or parts.netloc or not parts.path:
            continue  # absolute, protocol-relative, data:, or a bare #fragment
        targets.append(unquote(parts.path))
    return targets


def resolves(out: Path, page: Path, target: str) -> bool:
    """A leading slash is the site's root; anything else is where it was written."""
    base = out if target.startswith("/") else page.parent
    return (base / target.lstrip("/")).exists()


def check_links(out: Path) -> None:
    dead = [
        f"{page.relative_to(out)} → {target}"
        for page in sorted(out.rglob("*.html"))
        for target in local_targets(page.read_text(encoding="utf-8"))
        if not resolves(out, page, target)
    ]
    if dead:
        sys.exit(
            "the site would publish links that reach nothing:\n  " + "\n  ".join(dead)
        )


def colloquy(env: dict, *args: str) -> None:
    subprocess.run(
        [str(COLLOQUY), *args], check=True, env=env, stdout=subprocess.DEVNULL
    )


def export_examples(out: Path, env: dict) -> None:
    """Each example as one self-contained file, drawn by the browser first."""
    (out / "examples").mkdir()
    for source in sorted(EXAMPLES.glob("*.html")):
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "page"
            colloquy(env, "page", "init", str(page))
            (page / "versions" / "v1.html").write_text(
                source.read_text(encoding="utf-8"), encoding="utf-8"
            )
            shutil.copytree(EXAMPLES / "media", page / "media", dirs_exist_ok=True)
            colloquy(
                env,
                "version",
                "publish",
                str(page),
                "--version",
                "1",
                "--text",
                f"{source.name}, as it stands in the tree",
            )
            colloquy(
                env,
                "version",
                "export",
                str(page),
                "-o",
                str(out / "examples" / source.name),
            )
        print(f"  {source.stem}")


def build(out: Path) -> None:
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)

    for source in sorted(DOCS.iterdir()):
        target = out / source.name
        if source.suffix == ".html":
            text = THEME_LINK.sub(r'\1"theme.css"', source.read_text(encoding="utf-8"))
            for checkout, published in REWRITES.items():
                text = text.replace(checkout, published)
            target.write_text(text, encoding="utf-8")
        else:
            shutil.copy2(source, target)
    shutil.copy2(THEME, out / "theme.css")

    # The layer a visitor gets is the shipped one, plus this project's: a page dir
    # vendors the user's ~/.config/colloquy overlay too, and that one belongs to
    # whoever is running the build. An empty config home is what withholds it —
    # HOME stays, because uv keeps its cache there and a moved HOME re-downloads
    # Playwright on every build. Dropping the session leaves these throwaway page
    # directories nobody's, and so out of the watch guard.
    env = {k: v for k, v in os.environ.items() if not k.startswith("COLLOQUY_")}
    env.pop("CLAUDE_CODE_SESSION_ID", None)
    with tempfile.TemporaryDirectory() as config_home:
        env["XDG_CONFIG_HOME"] = config_home
        export_examples(out, env)

    check_links(out)


def main() -> None:
    build(OUT)
    print(f"✓ {len(list(OUT.rglob('*.html')))} pages → {OUT}")


if __name__ == "__main__":
    main()
