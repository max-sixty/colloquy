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
- [ ] Widgets deferred until a page wants them: risks, verdict.
- [ ] Keyboard path for board drags: the grip is HTML5-DnD only (pointer). A
      focusable grip moving its card with arrow keys would cover keyboard-only
      review; do it when a reviewer needs it rather than speculatively.
- [ ] Widget-aware Δ: the version diff is additions-only by text key, so a card that
      moved columns isn't marked. The changelog line carries it today; marking cards
      whose column changed would need the diff to understand board structure.
- [ ] Element deletion vs. anchor survival: `check` requires every id from the
      previous version to survive, which forbids ever deleting a card the reviewer
      dragged to "Done". When users ask for deletion, widen the frame (e.g., an id
      retires once no unresolved thread anchors it) rather than exempting boards.
