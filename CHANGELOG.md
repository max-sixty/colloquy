# Changelog

## Unreleased

- Pages follow the newest version automatically. Picking an older version in the picker
  pins the view (`?pin`); previously every page stayed put and only showed a "new
  version available" chip.

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
