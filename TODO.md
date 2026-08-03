# TODO

- (2026-07-30) The g leader shipped with digits only (`g 1` reaches the nth open
  thread's reply box) and the namespace open. Settle its shape before growing it:
  should the sequence carry a verb (`g r 1`, leaving `g` room for other nouns), or
  stay flat? And how do widgets join — a board's grips, a group's pick marks, a
  draft's ✎ have no addresses today; if they get them, the registry should
  declare it (an `x-` key the leader dispatches on), not modules registering
  keys, per the never-closed widget list. Bare `r` resolves the focused thread
  now, so a verb vocabulary should keep the bare keys' meanings — `g r 1`
  reading "reply" would give one letter two verbs.
- (2026-07-30) A reader can't walk a page's open questions from the keyboard, and the
  design for it is agreed but unbuilt. `x-awaits` on a registry entry says an instance
  of this tag is a standing request to the reader; unanswered then needs no new
  bookkeeping, being the fold the runtime already computes — a widget with no surviving
  action for its unit. One declaration drives a banner count, a key that steps
  unanswered questions the way `j`/`k` steps threads, and the `?` overlay, with no
  consumer naming a tag. Three declare it on day one (a group that takes picks, an
  undecided `cq-suggestion`, and the box for words), and the banner's
  `✓ Accept all (N)`, which counts suggestions by naming the tag, goes with them.
  That is the registry-declared address the leader item above wants, reached from the
  other end, so the two want settling together. Inside a group the affordance is half
  there already — each option's mark is a press, so Tab reaches it and Enter picks —
  and what is missing is ↑/↓ between options and 1–9 to pick, the number riding the
  mark the option already carries so that nothing appears on a page nobody is
  answering.

- (2026-07-30) A widget can't own a conversation. The box for words a question group
  carries posts an ordinary comment anchored on the widget, which is the right
  transport — threading, draft persistence, resolve, and the transcript all come free,
  and the log gains no second kind — but the panel is then the only place the words
  appear. The answer to a question the page asked reads as a remark *about* the widget
  rather than as the thing it asked for, and the box that asked shows nothing of what
  was said in it. What closing it properly has to answer: that a thread rendered inside
  a widget is a second *view* of one thread and never a second store, since two stores
  is the bug this codebase keeps not having; what the panel shows for an owned thread,
  because a reader scanning comments should still find every word they wrote; how
  ownership is declared, which has to be a registry key rather than a tag any consumer
  names, so the twelfth widget can claim a conversation without core hearing of it; and
  whether ownership is a property of the anchor or of the widget, which decides what
  happens to the thread when a later version drops the element it was anchored on.

- (2026-07-31) An unsent draft dies with the tab. sessionStorage carries one through a
  reload, a version navigation, and a server restart — the port is derived from the page
  directory, so a re-serve lands on the same origin — and a closed tab is the one case
  it doesn't cover. That is the ordinary case here rather than a rare one: each round's
  reply hands the URL over again and the user opens the page from the turn in front
  of them, so a page's tabs accumulate. Swapping the store for localStorage trades the
  gap for a worse failure, since one store shared across those tabs means a send or a
  Cancel in an old tab clears text being typed in the new one. The build that avoids
  both is localStorage for durability plus a channel (`BroadcastChannel`) that says what
  happened, so every tab renders one copy and a cleared draft arrives as "sent" rather
  than as words going missing — a value diff cannot tell those apart. What it costs is
  an index from a draft's context to the box showing it, which nothing needs today: each
  box closes over its own context where it is built, and the reconciled panel keeps
  that box for its thread's life, so the index would be one more store to hold in step
  with the list. The server is where Slack keeps drafts and the one place
  these cannot go: here the server is the agent, and an unsent draft would be words the
  user has not decided to say, sitting where the next `colloquy wait` can read them.

- (2026-08-02) Probably rename to `leaf`, taking `leaf.page` with it. Not settled.
  `/colloquy` comes late in Claude Code's completion menu, and the rule behind that is
  three keys: the length of the displayed name ascending, then use count descending
  between names of equal length, then registration order. A plugin skill displays as
  `plugin:skill`, so this one ranks as `/colloquy:colloquy` at seventeen characters —
  alone in its length bucket, which is why reaching for it has never moved it and
  can't. Keystrokes come from being the only command on a two-letter prefix rather
  than from being short: `/le` reaches leaf in three, and `/ap` would reach a
  seven-letter `apostil` in the same three. `leaf` names the gesture as well as the
  object, since to leaf through a document is to move over its pages looking for a
  line.

  What to weigh before committing: `leaf` is a term of art in this territory — a leaf
  node ends a tree, and a versioned document is one — and its live trademarks run from
  Nissan to a candy company. That it is taken on npm, PyPI and crates.io separates it
  from nothing, since every candidate is. `gloss` is the alternative whose meaning is
  what the product does and whose collisions all sit outside this field, at the cost
  of `gloss over` meaning to skim. The rename is avoidable too: setting the skill's
  `name:` to `cq` is one frontmatter line, keeps `/coll` working, and takes the
  unclaimed `/cq` at three keystrokes — at the price of Codex's `$colloquy`, if that
  host reads the same field, which is unchecked. `colloquy.dev` and `colloquy.page`
  are both free either way.
