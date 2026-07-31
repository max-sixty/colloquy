# TODO

- (2026-07-30) The g leader shipped with digits only (`g 1` reaches the nth open
  thread's reply box) and the namespace open. Settle its shape before growing it:
  should the sequence carry a verb (`g r 1`, leaving `g` room for other nouns), or
  stay flat? Should `g c` reach the general comment box, or is that `c`'s job?
  And how do widgets join — a board's grips, a group's pick marks, a draft's ✎
  have no addresses today; if they get them, the registry should declare it (an
  `x-` key the leader dispatches on), not modules registering keys, per the
  never-closed widget list.
- (2026-07-30) Nothing notices a handover that never landed. A page reached over
  SSH is served on the address `SSH_CONNECTION` reports, which a jump host or NAT
  between the reviewer and the box can leave unroutable — and the reviewer can't
  report a page they never got. An open page polls `/api/state` every two seconds,
  so recording the last request would make an absent browser observable:
  `review wait` already notices a dead server and restarts it, and would report
  this the same way, to Claude rather than to the reviewer. Reads the same for a
  page nobody has opened yet, which is why it belongs in the terminal and not in a
  diagnosis.
- (2026-07-30) Serve on a host the session can't derive (`--host NAME`, binding
  `0.0.0.0`), for where the address `SSH_CONNECTION` reports isn't the one the
  reviewer's machine routes to. Today the recourse is deleting `access.json` to
  re-derive it. The flag would have to be recorded there rather than passed, since
  `revive_server` restarts a page by re-running `server run` with no arguments of
  its own.
- (2026-07-30) Opt-in tunnel for remote sessions (`cloudflared`/`tailscale` when
  present), for a reviewer with no route to the box at all — a phone, or a machine
  off the VPN.

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

- (2026-07-30) The banner's right-hand group moves when nothing was pressed, and the
  press sweep cannot see it because no gesture causes it. Three of those controls come
  and go on what the poll finds — the latest-version chip, `✓ Accept all (N)`, the diff
  Δ — and the Comments button's count widens by about 14px when it crosses a digit. The
  row is packed to the right against a `flex: 1` spacer, so each of those shoves every
  control to its left, in the middle of whatever the reviewer was doing. Reserving for
  the digit alone is the small end and would read as a fix; a chip that appears is worth
  far more than 14px, and holding room for three sometimes-absent buttons leaves a gappy
  banner on the pages that never show them. So this is a question about what the banner
  owes a reviewer who is not looking at it — announce in place, or somewhere that costs
  the row nothing — rather than a width to state. Whatever it becomes needs a check that
  drives the poll rather than a press, since that is the half the sweep structurally
  can't reach.
- (2026-07-30) A diagram lands after the page does. `cq-diagram` loads the vendored
  mermaid bundle lazily and renders asynchronously, so the SVG replaces the source
  block around 100ms after the first paint (146ms against 46ms on
  `examples/incident-report.html`), growing its element by up to 93px and carrying
  everything below it down — a page the reader can already read, and then a jump in
  the middle of it. Nothing can reserve the room: the SVG's height is a fact only the
  render knows, and the source block's height bears no relation to it. The one honest
  fix is to hold the first paint until `settling` resolves, which the runtime already
  awaits before restoring the view — and that trades a jump for a blank page on any
  startup that throws before the stamp, where today the reviewer gets a readable page
  with broken chrome. Which of those is worse is a judgment about page-load feel
  rather than a defect with a right answer, which is why it is here rather than fixed.
