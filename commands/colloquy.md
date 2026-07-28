---
description: Present a plan, design, decision, or findings as a commentable HTML page in the browser instead of a terminal wall-of-text.
argument-hint: "[what to present — a plan, design, decision, or findings]"
allowed-tools:
  - Bash(colloquy:*)
---

Read `${CLAUDE_PLUGIN_ROOT}/skills/colloquy/SKILL.md`, which is the whole workflow, and
follow it to present the following as a colloquy page the user reviews in the browser.
This command shares its name with the skill, so invoking it loads this file rather than
that one; the path above is already resolved, so it takes one read and no search.

If nothing is specified below, present whatever the current session is about — the plan
you were about to give, the design under discussion, or the findings you just gathered.

Topic: $ARGUMENTS
