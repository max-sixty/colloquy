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
- [ ] Give class names an owner. Tags, attributes, nesting, and ids are all
      registry-driven so the renderer, the linter, and the catalog can't drift
      apart. CSS classes are the one part of the vocabulary with no owner, which
      is how `cq-tabs` came to mark itself with a class the runtime's chrome had
      already claimed, clipping every tabbed page to a pixel. Either the registry
      grows a class list per widget that `check` can collide-detect, or the
      chrome's rules get scoped so a widget's classes can't reach them.
- [ ] Widgets deferred until a page wants them: risks, verdict.
- [ ] Narrow viewports still stack the two scrollbars. Under 720px the panel
      covers the page rather than squeezing it, so `body` keeps its full width
      and its scrollbar shares the window's right edge with the thread list's.
      The wide layout fixed this by giving each region its own column; the
      covering layout needs its own answer (the page behind a sheet arguably
      shouldn't scroll at all).
- [ ] Un-choose: a pick can only be switched, not cleared, and there's no explicit
      "unchoose" action verb. Widen the action space when a page needs it.
- [ ] Pending-state marker for board moves: after the toast fades, nothing shows
      which moves await the honoring version (choose has its badge; move has
      nothing). Toasts also coalesce — rapid moves show only the last.
- [ ] Widget-aware Δ: the version diff is additions-only by text key, so a card that
      moved columns isn't marked. The changelog line carries it today; marking cards
      whose column changed would need the diff to understand board structure.
- [ ] Element deletion vs. anchor survival: `check` requires every id from the
      previous version to survive, which forbids ever deleting a card the reviewer
      dragged to "Done". When users ask for deletion, widen the frame (e.g., an id
      retires once no unresolved thread anchors it) rather than exempting boards.
