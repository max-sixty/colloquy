#!/usr/bin/env python3
"""Stop / UserPromptSubmit / SessionEnd hook — keeps the loop honest.

The loop asks the agent to restart `colloquy wait` after every round, and a page
whose watcher never came back is invisible from the browser: it looks exactly like a
page whose user has said nothing yet. These hooks make the loop the harness's
business rather than the model's memory. Stop protects Claude Code's background wait
and keeps Codex inside the active turn that polls its exact unified-exec session;
UserPromptSubmit surfaces unacknowledged events; SessionEnd idles the pages and stops
their servers.

The decision lives in interact.py, which owns the page-directory model. This
script exists to keep the common case cheap: it fires on every turn of every
session that has the plugin installed, so it checks whether this session has
served or watched a colloquy page at all before paying for a `uv run`.

Anything unexpected — missing session file, a broken interact.py, a timeout —
falls through silently and the turn proceeds. A Stop hook is the worst possible
place for a colloquy bug to strand the user.

The sessions path assumes the hook's environment and the Bash tool's agree on
XDG_STATE_HOME: `server run` and `colloquy wait` write the registry from a shell
initialized by the user's profile, while this script reads it from the agent
host's process environment.
A value set only in the shell profile makes the guard silently stand down —
fail-open, like everything else here.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

INTERACT = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "colloquy"
    / "scripts"
    / "interact.py"
)
# Must match interact.py's state_home(): this script runs under plain python3
# and can't import the uv script it fronts.
SESSIONS = (
    Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    / "colloquy"
    / "sessions"
)


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
            check=False,
        )
        sys.stdout.write(answer.stdout)
    except Exception:  # noqa: BLE001 — a hook that raises stops the turn it guards
        return


if __name__ == "__main__":
    main()
