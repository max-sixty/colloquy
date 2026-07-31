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
