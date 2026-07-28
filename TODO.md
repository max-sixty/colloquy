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
- [ ] Additive registry overlay: adding one widget means forking the whole
      registry.json today — init's overlay replaces the file, and the fork goes
      stale as the shipped vocabulary evolves. Merge overlay entries by tag
      instead. The theme needs no counterpart: a page-local `<style>` block
      already customizes tokens and idioms without forking theme.css.
- [ ] A server outlives a session killed hard enough to skip its `SessionEnd` hook,
      so a page's port stays held by a process nothing will revisit. The banner
      already reports the page as orphaned (the owning pid is gone), so this costs a
      stray process rather than a misled reviewer. Closing it properly means deciding
      whether a server may outlive the session that started it at all — a fresh
      session `serve`-ing an old page is the case that says yes.
- [ ] Opt-in tunnel for remote sessions (`cloudflared`/`tailscale` when present),
      gated behind an auth token added to the server first.
- [ ] A written anchor can't quote across a widget's parts. `comment` reads the version
      file, so it can't know the words a module writes between an element's children — a
      milestone's chips sit after its title, and no registry keyword can say where a
      mid-element row lands (x-says reaches an element's first and last child, which is
      all a pseudo-element could ever have been). Fences make that a refusal rather than
      an anchor that detaches in the reviewer's browser, so the cost is a quote Claude
      has to shorten. Closing it properly means either a placement vocabulary richer than
      two edges, or resolving the anchor in the browser at post time, which `comment`
      can't afford — it runs every round of the loop, and the browser is `check --render`'s
      once-per-page budget.
- [ ] Plan-mode integration hardening: remove the auto-approve workaround in
      `/colloquy-plans` and settle the default UX before promoting it from
      experimental.
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
      neighbours straight through a fence, while `comment`'s stops at one — the fence is
      where the file stops modelling the page, so the file-side capture has nothing to
      read past it. Beside a widget's seam the same passage therefore stores longer
      context from the browser than from `comment`, and the norm that both captures
      write the same text under the same rules is false by exactly that margin. The only
      alignment on offer is the browser stopping at fences too, since the file cannot
      learn to read through one; the cost is context the browser could legitimately use.
- [ ] A tab's name can't be commented on. Every other word a widget renders from an
      authored attribute is text a reviewer can select (`x-says`), but `cq-tab`'s
      `label` renders into the strip button the upgrade builds, and a control's label
      is `.cq-ui` — the anchor pass skips it, and rightly, since "Save" and "choose"
      are the runtime's words. The panel heading it also renders as (`cq-tab::before`)
      is switched off the moment the strip exists, so after upgrade the name is
      nowhere quotable. Making the button's label a non-`.cq-ui` span would let a drag
      inside it select — and switch tabs on the mouseup, since the button is still a
      button; `cq-options` already carries the guard for that shape ("a click that
      lands inside a selection is that selection's"), so the pieces exist. A settled
      `cq-options` row is the same shape — it names the chosen card in a button while
      collapsing the card itself, so the decision is quotable only once the group is
      opened. Worth doing when someone actually wants to comment on a tab's name or a
      settled line; until then the asymmetry is small and stated rather than hidden.
- [ ] A move's awaiting mark is visual only: `data-cq-awaiting` outlines the card, and a
      screen reader hears the move announced when it is made but nothing durable after.
      The grip's label (the board module's names pass) is the natural place to say it,
      and the board module is that label's one writer.
- [ ] The toast steps aside for the panel (`right:` panel width + 18px), which beside a
      covering sheet on a very narrow window puts it off-canvas. The covering layout
      wants its own answer here, as it got for scrolling, rather than the wide
      layout's offset.
- [ ] Re-record `docs/demo.gif`: its step 2 is a select-and-comment, which now lights
      the passage while the composer is open and no longer repeats it inside the box, so
      the hero image shows the old behavior twice over.
      `scripts/record-demo.sh` prints a shot list for a human to drive.
- [ ] Widgets deferred until a page wants them: risks, verdict.
- [ ] Render tests, next tier — deferred while the chrome is still being
      designed, because each is a baseline that re-records on every deliberate
      restyle: a per-example box dump (id/tag, position, size on a 4px grid —
      the text-snapshot equivalent for layout) and per-example ARIA snapshots
      (`aria_snapshot()`, which caught cq-board announcing itself flat — one
      board's tree is pinned in the render suite now, the corpus's is not);
      an axe-core pass (`axe-core-python` ships the JS in the wheel, no npm);
      print output (the @media print rules are load-bearing and near-unguarded —
      one printed group's pick is asserted, the pagination they exist for is not);
      keyboard bindings (assert colloquy leaves the browser's scroll keys alone,
      not that Chrome scrolls); and the narrow viewport's box dump (its scroll
      ownership is asserted in the suite).
- [ ] What the runtime writes onto the page's own elements is a hand-list. `shallowSigs`
      looks away from `class`, `aria-describedby`, and `data-cq-*` so the replay gate
      and the awaiting marker don't read the runtime's paint as disagreement — a list a
      future runtime-written attribute must join, or both start seeing ghosts. One
      declaration beside the writers would give the list an owner.
- [ ] An overlaid registry can name an `x-retired-when` the runtime's `DECIDED_VERB`
      doesn't know, and the generated selector then matches nothing — a retired slot
      silently quotable again. Unreachable in the shipped registry; the vendored-registry
      loop in `cmd_check` already reports keys a page can't honor, and this one belongs
      with them.
- [ ] `@scope` can't contain `@keyframes` names, so `cq-pulse` and `cq-flash` stay
      document-global — the one pinhole in the chrome's scoping, live only if a widget
      both coins the name and animates with it.
- [ ] Widget-aware Δ: the version diff is additions-only by text key, so a card that
      moved columns isn't marked. The changelog line carries it today; marking cards
      whose column changed would need the diff to understand board structure.
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
