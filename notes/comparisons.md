# Notes on nearby projects

Maintainer notes rather than a published page. Everything here was read from each
project's own documentation on 2026-07-31, and nothing in it is checked by CI, so it
dates from the day it was written and will drift.

Anything that hands an agent's work to a person in a browser answers three questions:
what the document is made of, where it lives, and how the reader's reply gets back to the
agent. Colloquy's answers are authored HTML, a directory on your machine, and a
host-specific wait inside the session: background completion in Claude Code, an exact
unified-exec session kept inside the active turn in Codex.

## Workbench

[Workbench](https://workbench.md/) is a hosted, multiplayer markdown workspace: a doc at
its own private link that agents and people edit together, with comments anchored to exact
text, suggestion mode, a board agents claim cards off, live cursors, and an append-only
activity feed. Its premise is that the document is the interface — "it's all markdown
underneath", and "the doc is the API".

|              | Workbench                                                                                                                | colloquy                                                                                                                                                                          |
| ------------ | ------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Document     | Markdown with fenced components — board, chat, sheet, chart, custom widget — edited in place, with named versions to restore from | Authored HTML, any structure the page needs, changed by the agent publishing a new version — each with a changelog note to step back to — or by the user working an affordance it offers |
| Home         | Hosted, at a private link                                                                                                  | A directory on your machine, served where your session reached it, behind a key                                                                                                     |
| Return path  | An HTTP long-poll the agent holds open                                                                                     | A background task that wakes Claude Code; an exact unified-exec wait Codex polls inside the active turn                                                                             |
| Reach        | Anything that speaks HTTP                                                                                                  | Claude Code and Codex                                                                                                                                                               |
| Built for    | A team of agents and people coordinating                                                                                   | One session presenting to one person                                                                                                                                                            |

The two return paths are closer than the hosting difference suggests. An agent watches a
Workbench doc by holding an HTTP long-poll open: `GET /api/docs/DOC_ID/events?since=SEQ&wait=55`,
which "returns the moment an event lands past `since`". Colloquy's `wait` tails the
page directory on disk and exits on the first event the agent hasn't seen. Different
transport, same bargain: one call that blocks until the user does something. Colloquy
acknowledges the event separately, only after a complete, untruncated wait result enters
model context.
Workbench also offers webhooks and a supervised watcher, for wake-ups that outlive the
agent's process.

What the HTTP surface gives Workbench is reach: "any agent that can fetch a URL can work
here — no SDK, no plugin", which covers Claude, Codex, Cursor and curl alike. Colloquy's
coupling to the agent host is the opposite bet, and what it gets in return is arrival in
model context: on Claude Code a finished background wait wakes or joins the session; on
Codex the agent keeps the handover turn active and polls the exact wait session. Either
can take "skip that one" into account before the next decision. It costs a host-specific
loop, and Colloquy runs on those two hosts and no others.

## html-effectiveness

[html-effectiveness](https://github.com/anthropics/html-effectiveness) is a gallery of
standalone HTML examples — code review, status reports, slide decks, diagrams, small
editing UIs — each "a self-contained `.html` page (no build step, no dependencies)". It
shares colloquy's premise that a page carries more than a wall of terminal text, and it
closes the loop through the reader: the editing UIs hold their state client-side and
"always end with an export button that turns whatever you did in the UI back into
something you can paste into the agent or commit". Colloquy replaces that paste with a
live return path.

## When colloquy is the wrong choice

- **More than one person, or agents coordinating with each other.** A colloquy page is
  one session presenting to one person. The log tells the agent from the user and no
  further: two people commenting are one voice, there are no live cursors, and nothing
  merges concurrent edits.
- **An agent that is only an HTTP client.** The loop is a command the agent runs and gets
  back into model context, so an agent that cannot run one cannot drive it — and the
  hooks that hold a session to the loop exist only in the two hosts.
- **An artifact that has to last.** The server and the wait go down with the session. The
  page directory stays on disk and `version export` makes a standalone copy, but
  nothing is live past the session, and a document a team will edit for months belongs
  in the repository.
- **Editing the document yourself.** The user works the affordances the page offers —
  comment, drag a card, pick an option, rewrite a draft, accept a proposed change — and
  prose the page didn't offer for change is the agent's until it publishes the next
  version. Where you would rather just fix the sentence, that round trip is the wrong
  shape.

## Not covered here

Two projects is not the landscape. A survey on 2026-08-01 named these as the ones a
fuller note would have to reach, roughly in order of how badly the omission dates this
one:

- **Claude Code Artifacts** (June 2026) — first-party, same medium, versioned pages that
  update in place, and the docs state there is no reply path: the user presses "Copy
  as prompt" and pastes into the terminal. The sharpest comparison available.
- **crit** — a local single Go binary, bound to loopback, no config or login; the agent
  launches it and blocks on the review rather than serving a page and watching it.
- **reviewable-html-workbench** — a Claude Code and Codex plugin running nearly this loop,
  down to the agent replying in-thread in the browser.
- **MCP Apps** — the first official MCP extension (January 2026), built on MCP-UI: a tool
  declares a `ui://` resource, the host renders it in a sandboxed iframe, and the UI pushes
  structured context back into the turn.
- **AG-UI** and **A2UI** — wire protocols and event vocabularies you build a UI on top of,
  rather than a surface.
- **`gh pr review`** — the incumbent, and what most people actually use.
