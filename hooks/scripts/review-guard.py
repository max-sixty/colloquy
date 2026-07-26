#!/usr/bin/env python3
"""Stop / UserPromptSubmit / SessionEnd hook — keeps the review loop honest.

The review loop asks Claude to restart `wait` after every round, and a page
whose watcher never came back is invisible from the browser: it looks exactly
like a page whose reviewer has said nothing yet. These hooks make the loop the
harness's business rather than the model's memory — Stop refuses to end a turn
that leaves one of this session's pages unwatched, UserPromptSubmit surfaces
comments Claude hasn't picked up, and SessionEnd idles the pages and stops
their servers.

The decision lives in interact.py, which owns the page-directory model. This
script exists to keep the common case cheap: it fires on every turn of every
session that has the plugin installed, so it checks whether this session has
served or watched a colloquy page at all before paying for a `uv run`.

Anything unexpected — missing session file, a broken interact.py, a timeout —
falls through silently and the turn proceeds. A Stop hook is the worst possible
place for a colloquy bug to strand the user.
"""

import json
import subprocess
import sys
from pathlib import Path

INTERACT = Path(__file__).resolve().parents[2] / "skills" / "colloquy" / "scripts" / "interact.py"
SESSIONS = Path.home() / ".claude" / "colloquy" / ".sessions"


def main() -> None:
    try:
        raw = sys.stdin.read()
        session_id = json.loads(raw)["session_id"]
        if not (SESSIONS / f"{session_id}.json").is_file():
            return  # this session has no colloquy pages; nothing to guard
        answer = subprocess.run(
            ["uv", "run", str(INTERACT), "hook"],
            input=raw,
            capture_output=True,
            text=True,
            timeout=15,
        )
        sys.stdout.write(answer.stdout)
    except Exception:
        return


if __name__ == "__main__":
    main()
