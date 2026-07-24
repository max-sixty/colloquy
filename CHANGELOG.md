# Changelog

## Unreleased

- `interact.py` runs as a `uv` script: a PEP 723 inline-metadata header declares its one
  dependency, `click`, and the CLI is built on `click` instead of `argparse`. `uv` is now
  the one declared prerequisite for the plugin, replacing the plain-`python3`,
  standard-library-only invocation the previous release shipped. Behavior and subcommands
  (`init serve status wait reply note events stop check`) are unchanged.
- Pages follow the newest version automatically. Picking an older version in the picker
  pins the view (`?pin`); previously every page stayed put and only showed a "new
  version available" chip.
- Comment boxes grow with what you type, and ⌘/Ctrl+Enter sends from all three (the
  general box, a thread reply, the selection composer). Send buttons disable while the
  box is empty or a send is in flight.
- A reply arriving while you type no longer scrolls the panel or drops the cursor, and
  sending a reply clears its box.
- The selection composer shows the passage it quotes, which a `display` bug had been
  hiding, and stays on screen clear of the banner and the open panel.
- A thread whose passage isn't in the version on screen shows a dimmed, dashed quote
  instead of a link that goes nowhere.
- Sign-off comes from the event log, so "✓ Approved" survives a reload rather than
  inviting a second approval.
- The panel remembers whether it was open across version switches, Escape closes it,
  and the "Claude replied" toast opens it.
- With no watcher, the banner says comments are saved and delivered next turn; the
  nudge-the-terminal wording is now reserved for a status stale by ten minutes.
- Keyboard selections raise the comment button, and the panel fits windows too narrow
  for a fixed 360px sidebar.

## 0.1.0

Initial release.

- `colloquy` skill: Claude presents a plan, design, decision, or findings as a
  commentable HTML page served on localhost, watches for selection-anchored comments,
  replies in-thread, and ships immutable revised versions with one-line changelogs.
- `/colloquy [topic]` command for explicit invocation.
- `interact.py`: standard-library Python 3 (no `uv`, no dependencies). Subcommands
  `init serve status wait reply note events stop check`.
- `check`: deterministic pre-handover lint (HTML parses, exactly one external script
  tag, anchor ids carried over from the previous version, no fixed-width overflow).
- `/colloquy-plans on|off` (experimental): redirect plan mode into a colloquy review
  page. Off by default.
- No-server fallback: a single self-contained `file://` HTML page when the browser
  can't reach localhost.
