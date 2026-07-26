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
- [ ] Render tests, next tier — deferred while the chrome is still being
      designed, because each is a baseline that re-records on every deliberate
      restyle: a per-example box dump (id/tag, position, size on a 4px grid —
      the text-snapshot equivalent for layout) and per-example ARIA snapshots
      (`aria_snapshot()`, which caught cq-board's flat announcement below);
      an axe-core pass (`axe-core-python` ships the JS in the wheel, no npm);
      print output (the @media print rule is load-bearing and unguarded —
      assert the PDF paginates); keyboard bindings (assert colloquy leaves the
      browser's scroll keys alone, not that Chrome scrolls); and the narrow
      viewport, once the covering-layout scrollbar item above is settled.
- [ ] `check --render`: run the render invariants against agent-authored pages
      at handover, not only the shipped examples — the suite currently protects
      colloquy's developers, not the reviewer of a fresh page. A product
      decision, not just a test: it puts Playwright and Chrome in the handover
      path, where `uv` is today the whole prerequisite story.
- [ ] cq-board is flat to assistive tech: columns don't group or label their
      cards (the ARIA snapshot shows bare text runs), so a screen reader hears
      seven cards and seven Move buttons with no column boundaries — and the
      Move button's label doesn't say which column the card is in. The one fact
      a non-visual user needs about a card is the thing never announced.
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
      Settled options took the other route — keep every id, collapse the height —
      which is right where the alternatives are the record of why the pick won, and
      leaves this open for the case where the content itself is spent: a "Done" card
      is not a record anyone rereads. Whichever way that lands, retirement is the
      author's declaration, never a side effect of the reviewer's action.
