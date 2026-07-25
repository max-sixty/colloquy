# TODO

Backlog for improving colloquy: recommendations that stood unchallenged. Each item
stands alone.

- [ ] A server outlives a session killed hard enough to skip its `SessionEnd` hook,
      so a page's port stays held by a process nothing will revisit. The banner
      already reports the page as orphaned (the owning pid is gone), so this costs a
      stray process rather than a misled reviewer. Closing it properly means deciding
      whether a server may outlive the session that started it at all — a fresh
      session `serve`-ing an old page is the case that says yes.
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
