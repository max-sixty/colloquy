# TODO

Backlog for improving colloquy: recommendations that stood unchallenged. Each item
stands alone.

- [ ] Resolve config and state locations — probably XDG paths, not `.claude`.
      `~/.claude/colloquy/` holds three unlike things today: the user overlay layer
      (theme.css, registry.json, widgets/, vendor/), every page directory (versions
      plus event log), and the `/colloquy-plans` toggle (`config.json`) — and the
      sharing is why `widgets` and `vendor` are reserved as page slugs. Splitting by
      kind (overlay and config to `$XDG_CONFIG_HOME/colloquy/`, page directories to
      `$XDG_STATE_HOME` or `$XDG_DATA_HOME`) dissolves the reserved-slug rule. The
      project layer (`./.claude/colloquy/`) is a separate question.
- [ ] Additive overlay: customizing one token, or adding one widget or idiom, means
      forking a whole file today — init's overlay replaces theme.css and
      registry.json per file. Let the overlay add rather than replace (token
      overrides folded into the vendored theme, registry entries merged by tag,
      idiom classes appended) so a one-line customization doesn't go stale as the
      shipped layer evolves.
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
- [ ] A comment on a repeated passage goes back to naming the first copy once the page is
      revised around it. Context places a comment only where the neighbours it stored are
      still there in full on both sides; anything less falls back to document order — right
      where the comment was made on the first copy, wrong where it was made on a later one.
      Both halves of that rule are deliberate. A partial match is evidence the page moved on
      rather than weak evidence for a copy, and preferring the best partial handed comments
      to copies they were never made on. Requiring both sides costs the passages that open or
      close their section, since those store one neighbour: one of the 259 ambiguous
      selections across the shipped examples, `"minutes."` ending a section in
      `incident-report.html`. It fails visibly — the mark paints on the wrong copy while the
      reviewer is still composing — where the case it closes fails silently a version later
      with nobody watching. Closing the remainder wants a similarity that
      survives an edit (Hypothesis scores an approximate match over quote, prefix and suffix
      together) rather than a lower bar. Two copies that are identical *and* identically
      surrounded can't be told apart at all, and no page here has a pair.
- [ ] A passage at the edge of its section gets thin context, and thin context is a weak
      bar. The search refuses one-sided context outright, but a side of one character — a
      passage closing its section stores everything before it and a `"."` — clears the gate
      and can still be matched by an earlier copy. A length threshold would be a tuning knob
      this file has otherwise avoided, and any number for it is arbitrary. The structural
      answer: the context is thin only because the capture clips to the section root, while
      the body has text on both sides. Build the search string over the body and restrict
      candidates to those inside the section element, and every passage gets two full sides
      except at the very ends of the document. That wants a containment test per candidate,
      so it is a real change rather than a small one.
- [ ] The 💬 button has two writers. `updateFab` decides it from the selection, and the
      click handler that spots a diagram or image writes it directly — so `updateFab` needs
      `else if (fabAnchor?.quote)` to avoid clobbering what the click just set, across an
      ordering constraint ("its handler runs before this queued update") stated only in a
      comment. That is the shape the file's first norm names, thirty lines below where it
      names it: a guard reading state another function wrote means the two are one
      function. The fix is to route the visual path through `updateFab` as well, so one
      function decides what the button is on. Not a one-liner — the click runs before the
      queued update, so the merged decider needs the click's find as an input rather than
      an output — which is why it is here rather than done.
- [ ] A commented passage is no longer announced. Marks are painted through the highlight
      registry rather than wrapped in `<mark>`, and a highlight has no accessibility
      exposure — Chrome's tree shows a `mark` node for the wrapper and nothing at all for
      the paint. The spec's own answer, `Highlight.type`, doesn't help: it sets cleanly and
      Chrome 150 still exposes nothing, and its enum has no value meaning "a comment" in
      any case. The comment itself is still reachable — the panel lists every thread with
      its quote, and j/k walks them — so what's gone is the correspondence while reading
      the page. Wrapping can't come back (it splits text nodes, which is what let a redraw
      eat a click), so the fix is to carry the fact on the block rather than the passage:
      `aria-describedby` from the block a thread anchors in to that thread in the panel,
      coarser than the mark but saying the same thing.
- [ ] Re-record `docs/demo.gif`: its step 2 is a select-and-comment, which now lights
      the passage while the composer is open and no longer repeats it inside the box, so
      the hero image shows the old behavior twice over.
      `scripts/record-demo.sh` prints a shot list for a human to drive.
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
- [ ] Pending-state marker for board moves: after the toast fades, nothing shows
      which moves await the honoring version (choose has its mark; move has
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
