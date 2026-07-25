# TODO

Backlog for improving colloquy. Decided items are design calls already made; roadmap
items are recommendations that stood unchallenged. Each item stands alone.

## Decided

- [ ] Enforce the review loop with hooks rather than trusting the model to remember:
      a `Stop` hook that blocks ending a turn while a page has undelivered user events
      or a non-idle page with no live watcher ("start `wait` or set status idle"), a
      `UserPromptSubmit` hook that injects pending comments at the next turn, and a
      `SessionEnd` hook that idles pages and stops their servers. `hooks/hooks.json`
      currently carries only the plan-mode redirect. **Decided 2026-07-24: blocked
      until Claude Code exports a session id to tool subprocesses.** Hooks must act
      only on the invoking session's pages, and CLI commands can't tag pages with a
      session today (`CLAUDE_SESSION_ID` isn't in the Bash environment — verified).
      The only workaround is process-ancestry matching, and interact.py runs under
      claude → shell → uv → python, so it means walking `ps` ancestry on both sides —
      a heuristic, and a misattributed `Stop` hook blocks every session. Revisit the
      moment the session id reaches subprocesses; the hook designs above stand.

## Roadmap

- [ ] Opt-in tunnel for remote sessions (`cloudflared`/`tailscale` when present),
      gated behind an auth token added to the server first.
- [ ] Plan-mode integration hardening: remove the auto-approve workaround in
      `/colloquy-plans` and settle the default UX before promoting it from
      experimental.
- [ ] Widgets after v1, committed: `cq-plan` + `cq-milestones` (the composition test
      case), then `cq-timeline`, `cq-compare`, `cq-metrics` (element-widgets) and
      `cq-diff`, `cq-code`, `cq-tree` (upgraded body-parsers, prototyped standalone
      first). Deferred until a page wants them: risks, verdict.
