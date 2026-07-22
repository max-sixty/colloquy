---
description: Toggle the experimental plan-mode integration — redirect plan mode into a colloquy review page (on/off/status).
argument-hint: "[on | off | status]"
allowed-tools:
  - Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/plans.py:*)
---

Run the toggle and report the result to the user:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/plans.py" $ARGUMENTS
```

This controls an **experimental prototype**. When on, exiting plan mode is
auto-approved and the plan is presented as a colloquy review page in the browser
instead of a terminal plan — the user approves there. When off (the default),
plan mode behaves normally. It's global, not per-project.
