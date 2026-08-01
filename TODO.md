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

- (2026-07-31) An unsent draft dies with the tab. sessionStorage carries one through a
  reload, a version navigation, and a server restart — the port is derived from the page
  directory, so a re-serve lands on the same origin — and a closed tab is the one case
  it doesn't cover. That is the ordinary case here rather than a rare one: each round's
  reply hands the URL over again and the reviewer opens the page from the turn in front
  of them, so a page's tabs accumulate. Swapping the store for localStorage trades the
  gap for a worse failure, since one store shared across those tabs means a send or a
  Cancel in an old tab clears text being typed in the new one. The build that avoids
  both is localStorage for durability plus a channel (`BroadcastChannel`) that says what
  happened, so every tab renders one copy and a cleared draft arrives as "sent" rather
  than as words going missing — a value diff cannot tell those apart. What it costs is
  an index from a draft's context to the box showing it, which nothing needs today: each
  box closes over its own context where it is built, and the panel rebuilds its reply
  boxes on every render, so the index has to be built in that same pass or it is one
  more thing to keep in step. The server is where Slack keeps drafts and the one place
  these cannot go: here the server is the agent, and an unsent draft would be words the
  reviewer has not decided to say, sitting where the next `review wait` can read them.

- (2026-08-01) The review loop's wake-up is unverified on Codex, one of the two hosts the
  plugin ships for, and the skill instructs both of them in Claude Code's vocabulary.
  `SKILL.md` says to start `server run` and `review wait` "as a background task
  (`run_in_background`)", naming a Claude Code tool parameter in a payload both hosts
  read, and says the wait "exits — re-invoking you — when the user comments", which is
  one host's behaviour stated as though it were universal. Claude Code turns a finished
  background task into input on its own; Codex has no unprompted completion notification
  at all, so `review wait` exiting there delivers to nobody and the agent has to come
  back and look. Which failure that produces is unobserved. A wait run in the foreground
  holds the turn until a comment lands or the shell tool times out, and `cmd_wait` writes
  its cursor after printing, so a killed wait redelivers rather than drops. A wait run in
  the background has nothing reading its stdout, and whether anything then says so rests
  on the Stop hook, which refuses to end a turn that leaves a page unwatched but stands
  down silently when the session id in its payload doesn't match the record
  `bin/colloquy` wrote. That identity mapping is the only Codex-specific code in the
  plugin, and the tests reach no further than the claim record it writes. Whether this
  wants host-conditional instructions, a wait Codex can drive itself, or first running
  one round under Codex to find out which of the two failures it has, is open.
