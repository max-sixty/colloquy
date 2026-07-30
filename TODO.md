# TODO

Backlog for improving colloquy: recommendations that stood unchallenged. Each item
stands alone.

- [ ] Consider worktree-local pages. Today every page lives under
      `~/.local/state/colloquy/pages/`; a page reviewing a branch's work could
      instead live in that branch's worktree, keeping the review beside the code
      it discusses and dying with the worktree when the work lands. What that
      has to answer: the review record vanishes on merge (today it outlives the
      branch), the vendored layer and event log would need gitignoring, and
      repo-less pages (personal-admin topics) still need the global home — so it
      would be a second convention beside it, not a replacement.
- [ ] A server outlives a session killed hard enough to skip its `SessionEnd` hook,
      so a page's port stays held by a process nothing will revisit. The banner
      already reports the page as orphaned (the owning pid is gone), so this costs a
      stray process rather than a misled reviewer. Closing it properly means deciding
      whether a server may outlive the session that started it at all — a fresh
      session running an old page's server is the case that says yes.
- [ ] Opt-in tunnel for remote sessions (`cloudflared`/`tailscale` when present),
      gated behind an auth token added to the server first.
- [ ] A written anchor can't quote across a widget's parts, or reach a label a module
      writes. `review comment` reads the version
      file, so it can't know the words a module writes between an element's children — a
      milestone's chips sit after its title, a tab's name sits in the strip and a settled
      group's summary in its disclosure row, and no registry keyword can say where a
      mid-element row lands (x-says reaches an element's first and last child, which is
      all a pseudo-element could ever have been). The reviewer can point at all of them;
      Claude can't quote them, which is the smaller half of the asymmetry — Claude has
      the words in front of it either way and can say "the tab called X" in prose.
      Fences make that a refusal rather than
      an anchor that detaches in the reviewer's browser, so the cost is a quote Claude
      has to shorten. Closing it properly means either a placement vocabulary richer than
      two edges, or resolving the anchor in the browser at post time, which
      `review comment` can't afford — it runs every round of the loop, and the browser
      is `version check --render`'s once-per-page budget.
- [ ] A comment on a repeated passage goes back to naming the first copy once the page is
      revised around it. Context places a comment only where the neighbours it stored are
      still there in full on both sides; anything less falls back to document order — right
      where the comment was made on the first copy, wrong where it was made on a later one.
      Both halves of that rule are deliberate. A partial match is evidence the page moved on
      rather than weak evidence for a copy, and preferring the best partial handed comments
      to copies they were never made on. The capture reads neighbours from the whole body,
      stopping only at a fence, so a side comes up short only against the document's own
      ends or beside a widget's seam rather than at every section edge — and that cost
      fails visibly, the mark painting on the wrong copy while the reviewer is still
      composing, where the failure the rule closes is silent a version later with nobody
      watching. Closing the remainder wants a similarity that survives an edit (Hypothesis
      scores an approximate match over quote, prefix and suffix together) rather than a
      lower bar. Two copies that are identical *and* identically surrounded can't be told
      apart at all, and no page here has a pair.
- [ ] The two captures stop at different walls. The browser's reads a passage's
      neighbours straight through a fence, while `review comment`'s stops at one — the
      fence is where the file stops modelling the page, so the file-side capture has
      nothing to read past it. Beside a widget's seam the same passage therefore stores
      longer context from the browser than from `review comment`, and the norm that both
      captures write the same text under the same rules is false by exactly that margin.
      The only alignment on offer is the browser stopping at fences too, since the file
      cannot learn to read through one; the cost is context the browser could
      legitimately use.
- [ ] The hidden line that tells a screen reader a block carries a comment can't be
      followed to the thread it counts: whoever hears "2 comments" goes to the panel to
      find which passage each one is on. Making it followable means a focusable element
      inside the author's prose, which is either a visible affordance on focus or an
      invisible tab stop, and neither is obviously worth it while j/k walks every thread
      with its quote.
- [ ] Re-record `docs/demo.gif`: its step 2 is a select-and-comment, which now lights
      the passage while the composer is open and no longer repeats it inside the box, so
      the hero image shows the old behavior twice over.
      `scripts/record-demo.sh` prints a shot list for a human to drive.
- [ ] The tour walks one example and it is the review loop. `docs/index.html` names four
      things a page does — explain, collaborate, interact, track — and then walks only the
      second, so the other three are claims a reader takes on trust. Two more worked
      examples would cover them: an interactive one (a draft the reader rewrites and
      approves, a board they re-prioritize) and a live one (a dashboard whose items tick
      over as the work moves). The live example wants a page in `examples/` to point at
      first — the corpus is seven documents about something and nothing that keeps up
      with work, so a model writing its first dashboard has nothing to imitate either.
- [ ] Widgets deferred until a page wants them: risks, verdict.
- [ ] A `cq-shot` pair has no difference view. The script this came from toggled in an
      ImageMagick heat-map of the changed pixels and printed the count, and its own
      documentation then said not to trust either: downscale and anti-aliasing inflate
      the count with no real change, and a reflow paints everything below it red. The
      flip does that job better and needs nothing on PATH — a change the heat-map would
      have marked is a change the flip makes move. Worth revisiting only if a real pair
      defeats the eye, and then in Python (`uv` stays the one prerequisite) rather than
      on a canvas, which a page with no script can't paint.
- [ ] A full-page screenshot is illegible in a 760px column — a 1300px desktop shot lands
      at 58%, and body text in it is unreadable at any color scheme. `cq-shot` says so and
      tells the author to crop, which works, but the advice is the whole answer: there is
      no zoom, and the reader's way to the pixels is the browser's own "open image in new
      tab". A link would be the obvious affordance and is what the first draft had; it came
      out because a click on the image is how a comment on it opens, and the two gestures
      were competing for the same pixels. Wants either an affordance outside the frame or a
      widget allowed to exceed the column, which nothing else on a page may do.
- [ ] `cq-shot` isn't in `examples/`, so the render suite covers it through its own
      fixtures rather than through the corpus every other widget shares. An example would
      mean committing screenshots and regenerating `gallery.html` around them; worth doing
      the next time an example page has a real before/after to show, rather than staging
      one for the sake of the corpus.
- [ ] Render tests, next tier — deferred while the chrome is still being
      designed, because each is a baseline that re-records on every deliberate
      restyle: a per-example box dump (id/tag, position, size on a 4px grid —
      the text-snapshot equivalent for layout) and per-example ARIA snapshots
      (`aria_snapshot()`, which caught cq-board announcing itself flat — one
      board's tree is pinned in the render suite now, the corpus's is not);
      an axe-core pass (`axe-core-python` ships the JS in the wheel, no npm);
      print output (the gate now reports words a printed page drops, so what is
      left unguarded is pagination — assert the PDF paginates); keyboard bindings
      (assert colloquy leaves the browser's scroll keys alone, not that Chrome
      scrolls); and the narrow viewport's box dump (its scroll ownership is
      asserted in the suite).
- [ ] What the runtime writes onto the page's own elements is a hand-list. `shallowSigs`
      looks away from `class` and `data-cq-*` so the replay gate doesn't read the
      runtime's paint as disagreement — a list a future runtime-written attribute
      must join, or it starts seeing ghosts. One declaration beside the writers
      would give the list an owner.
- [ ] `@scope` can't contain `@keyframes` names, so `cq-pulse` and `cq-flash` stay
      document-global — the one pinhole in the chrome's scoping, live only if a widget
      both coins the name and animates with it.
- [ ] Within-column reorders are invisible to the state layer: the fold compares
      position at column granularity (indexes compose across cards, so a finer
      comparison would blame innocent versions), which leaves a pure reorder
      unmarked by the pending pass and the diff's state half, and outside the
      restatement gate. A stated degradation rather than a bug; closing it wants a
      per-column sequence facet with its own composition rules.
- [ ] Widget-aware suggestions: `cq-suggestion` proposes markup, so a change to a
      widget's own state (a card moved between columns, an option marked `chosen`)
      has no form yet — proposing it means re-stating the whole widget in both
      slots. Whether that wants a per-widget proposal shape or nothing at all
      waits for a page that needs it.
- [ ] Un-decide a suggestion: a pick can be cleared by clicking its mark again,
      but an accept or reject is final until the next version, because settling
      collapses the suggestion to ordinary prose and leaves nothing to click.
      Reversing it would mean keeping some mark on settled text, which is exactly
      what settling is for — so the two widgets diverge here on purpose. Revisit
      if a reviewer actually misclicks one.
- [ ] A rewritten draft shows the new words and nothing about the change. Both layers
      already say *that* one happened — the runtime marks the draft `data-cq-pending`
      until a version honors it, the version diff marks the whole block — and neither
      says *what*, so a reviewer returning to a page they edited yesterday re-reads a
      paragraph to find their own sentence in it. Half the pieces are here:
      `authoredFacets` captures every unit's markup state before the first replay, so
      authored-against-standing is a lookup, and `Intl.Segmenter` is already assumed, so
      the words are already cut. The missing half is the alignment itself — the version
      diff compares whole blocks by multiset membership and `cq-diff` renders a unified
      diff someone else computed, so nothing in this layer has ever lined two strings up.
      Editing *inside* that view is the larger ask and wants its own answer: the widget's
      premise is that reading and editing are one box, and a diff is a third rendering
      that is neither.
- [ ] A draft can't be walked back. The record is already complete — every `edit` carries
      the whole new body, so the log holds each state the draft has been in, and the page
      holds the log — and restoring one needs no new verb, since an absolute `edit`
      naming an older text is an ordinary edit that replay converges on like any other.
      What is missing is a way for a widget to read its own past (modules are handed the
      fold, never the sequence) and a shape for showing it that a one-box widget can hold
      — the same rendering question as the diff above, which a history view would want
      anyway to say how two entries differ. The reading half belongs on the runtime's
      helper surface rather than in `cq-draft`, because the second widget to want it
      would otherwise copy it.
