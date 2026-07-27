#!/usr/bin/env python3
"""PreToolUse hook on ExitPlanMode — the opt-in plan-mode prototype (#2C).

Off by default. When the user turns it on with `/colloquy-plans on`, an
ExitPlanMode call is auto-approved and Claude is redirected to present the plan
as a colloquy review page instead of dropping into implementation, so the plan
is reviewed in the browser rather than approved as a terminal wall-of-text.

The toggle lives at ~/.claude/colloquy/config.json ({"plans": true}). Anything
other than an explicit enable — missing file, disabled, malformed, any error —
falls through to the normal plan-mode flow, so a colloquy bug can never block
the user's plans.
"""

import json
import sys
from pathlib import Path

CONFIG = Path.home() / ".claude" / "colloquy" / "config.json"

REDIRECT = (
    "colloquy-plans is on. Do not start implementing yet. Present the plan you "
    "just finalized as a colloquy review page: follow the colloquy skill — init a "
    "directory under ~/.claude/colloquy/<slug>/, write the plan as "
    "versions/v001.html (sections with stable ids; widgets and idioms per the "
    'vendored catalog; <meta name="cq-review" content="sign-off"> in the head — '
    "approval is the point of a plan page), serve it, note the version, "
    "and hand over the URL. Then enter the comment/reply/revise loop. Treat the "
    'user approving in the browser ("✓ Looks good") as the go-ahead to implement.'
)


def plans_enabled() -> bool:
    try:
        return bool(json.loads(CONFIG.read_text(encoding="utf-8")).get("plans"))
    except Exception:
        return False


def main() -> None:
    if not plans_enabled():
        return  # allow normally
    try:
        json.load(sys.stdin)  # drain input; contents unused
    except Exception:
        pass
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": "colloquy-plans: redirecting the plan into a review page",
        },
        "systemMessage": REDIRECT,
    }))


if __name__ == "__main__":
    main()
