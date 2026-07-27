---
description: Present a plan, design, decision, or findings as a commentable HTML page in the browser instead of a terminal wall-of-text.
argument-hint: "[what to present — a plan, design, decision, or findings]"
allowed-tools:
  - Bash(colloquy:*)
---

Present the following as a colloquy page the user reviews in the browser, following the
`colloquy` skill (its SKILL.md is the full workflow: `init`, read the `catalog`, write
`versions/v001.html`, `serve`, `note`, hand over the URL, then the
comment/reply/revise loop).

If nothing is specified below, present whatever the current session is about — the plan
you were about to give, the design under discussion, or the findings you just gathered.

Topic: $ARGUMENTS
