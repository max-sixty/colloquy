# TODO

Backlog for improving colloquy. Decided items are design calls already made; roadmap
items are recommendations that stood unchallenged. Each item stands alone.

## Decided

- [ ] Enforce the review loop with hooks rather than trusting the model to remember:
      a `Stop` hook that blocks ending a turn while a page has undelivered user events
      or a non-idle page with no live watcher ("start `wait` or set status idle"), a
      `UserPromptSubmit` hook that injects pending comments at the next turn, and a
      `SessionEnd` hook that idles pages and stops their servers. `hooks/hooks.json`
      currently carries only the plan-mode redirect.

## Roadmap

- [ ] Dark mode: pages and the injected layer honor `prefers-color-scheme` (the skill
      currently mandates a light palette).
- [ ] Version diff: a "changes since vN" toggle with ins/del highlighting, so
      re-reviewing a revision is cheap.
- [ ] Suggested edits: a comment variant proposing replacement text for the selected
      passage, which Claude can accept verbatim into the next version. A reference
      shape: Workbench's suggestion API (`{type: replace|delete|insert, find, text}`
      with accept/reject, and unaccepted suggestions hidden from readers).
- [ ] Export a review thread to Markdown for reuse in a PR description.
- [ ] Anchor coverage beyond text: comments on a diagram or image currently fall back
      to whole-page anchoring.
- [ ] Opt-in tunnel for remote sessions (`cloudflared`/`tailscale` when present),
      gated behind an auth token added to the server first.
- [ ] Plan-mode integration hardening: remove the auto-approve workaround in
      `/colloquy-plans` and settle the default UX before promoting it from
      experimental.
