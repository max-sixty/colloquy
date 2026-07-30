#!/usr/bin/env python3
"""Serve an example as a real colloquy page, to review how it renders.

An example is a page body, not a page directory: it links /theme.css and
/colloquy.js at the server root, which is where `page init` vendors them. Opening one
from disk gets a dead page, because Chrome refuses ES modules from a file://
origin — nothing upgrades, and a tabbed page renders as every tab at once. So
this builds the directory the runtime expects and hands it to `server run`, the same
path a session takes.

The result is a page, not a picture of one: it takes comments. Served from an
agent session, `review wait` on the same directory carries them to the agent and the
example gets revised like any other page; run from a bare shell, they queue in
the log until an agent next reads it. Which of those happens follows from the
host identity the launcher puts in the environment.

Vendoring runs fresh each time, so an edit to the theme, the registry, or a
widget shows up on the next run. `version publish` lints the example on the way past. The
browser gate a page normally passes before its URL goes out is left to the
suite: `version check --render` and `test_example_renders` drive the same
`render_version` over the same files, so running it here would only repeat what
the suite has already said about these exact pages.

Usage: preview.py [example]  (default: gallery; Ctrl-C to stop)
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COLLOQUY = ROOT / "plugins" / "colloquy" / "bin" / "colloquy"
PAGE = ROOT / ".tmp" / "preview"  # gitignored, and stable so the port persists


def colloquy(*args, check=True):
    return subprocess.run([str(COLLOQUY), *args], check=check)


def main() -> None:
    name = (sys.argv[1] if len(sys.argv) > 1 else "gallery").removesuffix(".html")
    source = ROOT / "examples" / f"{name}.html"
    if not source.exists():
        sys.exit(f"no example named {name}; examples/ holds "
                 + ", ".join(sorted(p.stem for p in (ROOT / "examples").glob("*.html"))))

    if PAGE.exists():  # a previous preview may still hold the port
        colloquy("server", "stop", str(PAGE), check=False)
        shutil.rmtree(PAGE)
    colloquy("page", "init", str(PAGE))
    (PAGE / "versions" / "v1.html").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    colloquy(
        "version",
        "publish",
        str(PAGE),
        "--version",
        "1",
        "--text",
        f"{source.name}, as it stands in the tree",
    )
    colloquy("server", "run", str(PAGE))


if __name__ == "__main__":
    main()
