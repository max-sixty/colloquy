# colloquy

**Stop reading Claude's plans in the terminal.** Review them like a document instead:
Claude hands you a web page, you select any line and comment on it like a Google Doc, and
a revised version arrives with the change. Comment threads, a live "Claude is working /
listening" banner, and a version picker are all built in.

![colloquy demo](docs/demo.gif)

It works for anything Claude would otherwise dump as a wall of text: a migration plan, an
architecture write-up, an incident diagnosis, a PR walkthrough, a review. The plan case is
the wedge; nothing in the tool is narrowed to it.

## Install

```
/plugin marketplace add max-sixty/colloquy
/plugin install colloquy@colloquy
```

That's it. No dependencies to install, no config, no accounts. The one requirement is a
`python3` on your PATH (macOS ships one with the Command Line Tools; nearly every Linux
has one), and a browser on the same machine as the session.

## Using it

**Just ask.** "Write up the migration options as a page", "explain this design in HTML",
or "I want to see the options" all trigger it. Claude also reaches for it on its own when
a plan or write-up would be easier to review as a page than as terminal text.

**`/colloquy [topic]`** is the explicit entry point. With no argument it presents whatever
the session is currently about.

Once a page is up, Claude prints a `http://127.0.0.1:…` URL. Open it, then:

- **Select any text** to comment on that exact passage. Your comment anchors to it and
  stays anchored across new versions.
- **Reply in the thread** when Claude answers. The banner shows whether Claude is working
  on your comments or listening for new ones.
- **Switch versions** with the picker. Each revision is immutable and carries a one-line
  changelog, so the picker is the history.
- **"✓ Looks good"** signs off and closes the review.

### Experimental: plan-mode integration

`/colloquy-plans on` redirects Claude's plan mode into a colloquy page: instead of
approving a plan in the terminal, you review it in the browser. It's off by default and
global. This one is a prototype (it auto-approves the plan-mode exit so the page can be
built), so try it deliberately. `/colloquy-plans off` restores normal plan mode.

## How it works

No daemon, no database, no build step. A ~400-line standard-library Python script serves
the page on a loopback port and mediates an append-only event log; a ~550-line vanilla-JS
layer the page loads provides the comments, threads, banner, and picker.

The load-bearing trick is that Claude's turn ends on a background `wait` that exits the
moment you comment, which re-invokes Claude. So there is nothing running between rounds
and nothing to push: your comment itself wakes Claude up.

```
Claude session  ──writes versions, replies──▶  interact.py server  ──serves page──▶  browser
      ▲                                                                                   │
      └──────────── wait exits on your comment, re-invoking Claude ◀────POST comment──────┘
```

### Remote sessions

The server binds `127.0.0.1`, so the browser must be on the same machine. Local terminals
and the desktop app work directly. VS Code Remote-SSH and devcontainers forward localhost
ports automatically, so the URL opens as-is. In a session that can't reach localhost (a
cloud session, bare SSH with no forwarding), colloquy degrades to handing over a single
self-contained HTML file you open with `file://`. The page is still readable; the comment
loop is what's lost.

## Pre-handover check

Before handing over a page, Claude runs `interact.py check`, a deterministic lint that
needs no browser: the HTML parses with balanced tags, there is exactly one external script
tag, every comment anchor from the previous version survives, and nothing has a fixed
pixel width wider than the readable column (the class of bug that makes a page scroll
sideways). It's near-free, so it runs on every version.

## Recording the demo

`scripts/record-demo.sh` prints a shot list and the setup for capturing the README GIF
against a real colloquy page. Drop the result at `docs/demo.gif`.

## License

MIT. See [LICENSE](LICENSE).
