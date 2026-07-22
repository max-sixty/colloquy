#!/usr/bin/env python3
"""Toggle the opt-in plan-mode prototype (#2C).

Reads/writes ~/.claude/colloquy/config.json, the same file the ExitPlanMode
hook checks. Usage: plans.py [on|off|status]  (no arg = status).
"""

import json
import sys
from pathlib import Path

CONFIG = Path.home() / ".claude" / "colloquy" / "config.json"


def load() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save(cfg: dict) -> None:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    action = (sys.argv[1] if len(sys.argv) > 1 else "status").lower()
    cfg = load()
    if action in ("on", "off"):
        cfg["plans"] = action == "on"
        save(cfg)
    elif action != "status":
        sys.exit("usage: plans.py [on|off|status]")
    state = "on" if cfg.get("plans") else "off"
    if state == "on":
        print("colloquy-plans is ON — plan-mode exits are redirected into a review page.")
    else:
        print("colloquy-plans is OFF — plan mode behaves normally.")


if __name__ == "__main__":
    main()
