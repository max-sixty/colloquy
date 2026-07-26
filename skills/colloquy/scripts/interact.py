#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = ["click>=8", "jsonschema>=4"]
# ///
"""Serve and mediate an interactive colloquy page.

A `uv` script: the PEP 723 header above declares the dependencies, and `uv` is
the one prerequisite for the whole plugin — no venv to create, no build step.
Run it with `uv run interact.py <command> …`.

A page directory holds:
    versions/v001.html…  immutable page versions (Claude writes them). The server
                         exposes a version only once its `note` lands, and `note`
                         itself runs `check` and refuses a failing version — so a
                         half-written or broken file is never live to an open
                         browser.
    colloquy.js          the runtime (widget layer + comment layer), served at /colloquy.js
    theme.css            tokens, element styles, class idioms, element-widget CSS
    registry.json        the widget vocabulary: JSON Schema per cq-* tag, plus $idioms
    widgets/             one ES module per upgraded widget (cq-ref.js, cq-diagram.js)
    vendor/              vendored third-party assets (mermaid.min.js, sortable.esm.js)
    comments.jsonl       append-only event log; an event's seq is its line number (1-based)
    status.json          Claude's declared state: {"state": working|waiting|idle, "detail", "ts"};
                         `wait` writes it working with "handoff": true when it delivers events,
                         covering the gap until Claude's own `status` lands
    heartbeat.json       watcher liveness, bumped by `wait` while it runs
    cursor.json          seq of the last event delivered to Claude, written by `wait` on exit
    server.json          {"port", "pid", "url"} for the running server
    session.json         {"id", "pid"} of the Claude Code session last working on the page

status.json is a claim, and a claim never expires on its own: an agent that
stopped watching renders exactly like one that is watching and has nothing to
say, so a comment can sit unread with the page still reading "Claude is
working". The directory therefore also carries what it can prove — a heartbeat
only a live `wait` bumps, the delivery cursor, and the owning session's pid —
and `/api/state` ships those beside the claim, so the banner can say when the
claim has outlived them. `wait` marks the status it writes on delivery
"handoff", which dates it: Claude's first act on waking is its own `status`, so
the mark surviving is a dropped pickup rather than a long turn, and the banner
gives it a much shorter rope.

The `hook` command closes the same gap from the agent's side. Registered on
Stop, UserPromptSubmit and SessionEnd, it refuses to let a turn end with one of
this session's pages unwatched, surfaces undelivered comments at the next
prompt, and idles the pages and stops their servers when the session exits. It
finds them through ~/.claude/colloquy/.sessions/<session id>.json, which `serve`
and `wait` write from CLAUDE_CODE_SESSION_ID — absent that (interact.py run
outside Claude Code), nothing is claimed and the hooks stand down. Undelivered
events are the one thing `status idle` can't close over: idling is how a review
ends, and a review can't end on comments nobody read.

`init` vendors the runtime, theme, registry, widgets, and vendor assets into the
page directory, overlaying per file by precedence: colloquy's shipped defaults,
then the user layer (~/.claude/colloquy/), then the project layer
(./.claude/colloquy/). The page directory is self-contained, so an approved
version can't change under its reviewer; re-running `init` is the explicit
re-vendor, noted in the next version's changelog.

The registry drives three consumers — the JS runtime (which tags upgrade), this
file's `check` and `reply` validation, and the `catalog` the agent reads. Each
entry is JSON Schema over the instance built from the element's attributes
(values as strings, flag attributes as True). What JSON
Schema has no vocabulary for rides in x- keywords:
    x-parent    the tag this element must be a direct child of
    x-content   the content model: "prose" (flow content, widgets welcome),
                "items" (element children only, no loose text), "data" (a text
                body in the notation the description names), "none" (empty).
                Children that declare this tag as x-parent are admissible under
                any model — that is what x-parent means.
    x-chips     attributes the theme renders as chips (documentation for CSS)
    x-upgrade   true when the runtime imports /widgets/<tag>.js for it
    x-example   one authored example, printed by `catalog`

Event kinds: comment (user; optional anchor {section, quote}), reply (parent=id),
resolve (parent=id), done (user sign-off; the banner offers it only on a page
declaring <meta name="cq-review" content="sign-off">), action (user; a widget reporting the
user editing the document through it — widget=element id, action=verb, detail
per widget, version the edit was made against), note (claude; per-version
changelog). The server stamps every browser-posted event author=user;
`reply`/`note` stamp author=claude. A Claude reply may carry widget markup — `reply` validates it
against the vendored registry, the discussion-side analog of `check`; user
comments stay plain text.

Commands:
    init serve status wait reply note events stop check catalog export

`check` is a deterministic pre-handover lint (no browser, never renders): the
HTML parses with balanced tags; the page carries exactly one external script
(<script type="module" src="/colloquy.js">) and one stylesheet link
(/theme.css); every cq-* element validates against the vendored registry
(schema, nesting, no self-closing form); every cq-* meta is a known page
declaration with an allowed value; ids are unique and every anchor id
from the previous version survives; no fixed-pixel-width element is wider than
the readable column.
"""

import errno
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import time
import zlib
from datetime import datetime
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import click
from jsonschema import Draft202012Validator

HEARTBEAT_FRESH_SECS = 8
BROWSER_EVENT_KINDS = {"comment", "reply", "resolve", "done", "action"}

ASSETS = Path(__file__).resolve().parent.parent / "assets"
VENDORED_FILES = ("colloquy.js", "theme.css", "registry.json")
VENDORED_DIRS = ("widgets", "vendor")
# What the server exposes from a page directory: exactly what init vendors,
# plus the versions.
SERVED_PATH = re.compile(
    r"/(?:colloquy\.js|theme\.css|registry\.json"
    r"|widgets/[a-z0-9-]+\.js|vendor/[A-Za-z0-9._-]+|versions/v[0-9]+\.html)"
)
CONTENT_TYPES = {
    ".js": "application/javascript",
    ".mjs": "application/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".html": "text/html",
    ".svg": "image/svg+xml",
}

# On Windows there is no fcntl; the append lock degrades to a no-op. The log is
# append-only and a torn final line is tolerated by read_events, so this only
# loses the belt-and-suspenders against simultaneous writers, which are rare.
try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def write_json(path: Path, obj) -> None:
    # Atomic: the serve process reads these files (cursor.json every poll) while
    # wait/status write them; a torn read of cursor.json would replay declined
    # actions in the browser, stickily. The tmp name carries the pid so two
    # writers (wait's status flip racing a `status` CLI call) can't replace each
    # other's tmp out from under os.replace.
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def append_event(page_dir: Path, event: dict) -> dict:
    event.setdefault("id", secrets.token_hex(4))
    event.setdefault("ts", now_iso())
    with open(page_dir / "comments.jsonl", "a", encoding="utf-8") as f:
        if fcntl is not None:
            fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def read_events(page_dir: Path) -> list:
    path = page_dir / "comments.jsonl"
    if not path.exists():
        return []
    events = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            if i == len(lines) - 1:  # a concurrent append mid-flush; complete on the next read
                break
            raise
        event["seq"] = i + 1
        events.append(event)
    return events


def list_versions(page_dir: Path) -> list:
    versions_dir = page_dir / "versions"
    if not versions_dir.exists():
        return []
    return sorted(p.name for p in versions_dir.glob("v[0-9]*.html"))


def published_versions(page_dir: Path) -> list:
    """Versions the server exposes: those whose `note` has landed. `note` follows a
    passing `check`, so a half-written or failing version is never live to an open
    browser — the file existing is not enough."""
    noted = {e.get("version") for e in read_events(page_dir) if e.get("kind") == "note"}
    return [
        name
        for name in list_versions(page_dir)
        if int(re.search(r"v0*(\d+)", name).group(1)) in noted
    ]


def pid_alive(pid: int) -> bool:
    # A missing pid reads as -1 from callers, and os.kill takes that as "every
    # process I may signal" — which would answer True for a page nobody owns.
    if pid < 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def running_server(page_dir: Path):
    info = read_json(page_dir / "server.json")
    if info and pid_alive(info.get("pid", -1)):
        return info
    return None


def colloquy_home() -> Path:
    """~/.claude/colloquy/ — page directories by convention, the user's overlay
    layer, and .sessions/. A leading dot keeps that last one clear of the
    kebab-case slugs a page can take."""
    return Path.home() / ".claude" / "colloquy"


def claim_page(page_dir: Path) -> None:
    """Record that this Claude Code session is the one working on the page, in
    both directions: the page names its session (so the server can see when that
    session is gone), the session lists its pages (so the hooks can find them
    wherever they live). Claude Code puts the id and its pid in the environment
    of every Bash tool call, so this needs no cooperation from the agent.

    `serve` and `wait` claim; nothing else does. The claim tracks the watch
    obligation the hooks enforce: `serve` puts the page in front of a reviewer
    and so incurs it, `wait` takes it up. Authoring — `init`, `check`, `note`,
    `reply` — neither incurs the obligation nor discharges it, so a directory a
    session only wrote to, like a throwaway page for testing the widget layer,
    owes nobody a watcher."""
    sid, pid = os.environ.get("CLAUDE_CODE_SESSION_ID"), os.environ.get("CLAUDE_PID")
    if not sid or not pid:
        return
    write_json(page_dir / "session.json", {"id": sid, "pid": int(pid), "ts": now_iso()})
    sessions = colloquy_home() / ".sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    # Sessions that died without a SessionEnd hook leave their file behind; drop
    # them here rather than on a timer, the way init drops a killed writer's .tmp.
    for stale in sessions.glob("*.json"):
        entry = read_json(stale)
        if entry and not pid_alive(entry.get("pid", -1)):
            stale.unlink(missing_ok=True)
    entry = read_json(sessions / f"{sid}.json") or {"pages": []}
    pages = sorted({*entry["pages"], str(page_dir)})
    write_json(sessions / f"{sid}.json", {"pid": int(pid), "pages": pages, "ts": now_iso()})


def session_pages(session_id: str) -> list:
    """The page directories a session has worked on, those still on disk."""
    entry = read_json(colloquy_home() / ".sessions" / f"{session_id}.json") or {"pages": []}
    return [d for d in (Path(p) for p in entry["pages"]) if d.is_dir()]


def owned_pages(session_id: str) -> list:
    """The pages a session is answerable for: those it worked on most recently.
    A page another session has since picked up belongs to that one — its watcher,
    its server, its turn to be held to the loop."""
    return [
        d for d in session_pages(session_id)
        if (read_json(d / "session.json") or {}).get("id") == session_id
    ]


def full_state(page_dir: Path) -> dict:
    status = read_json(page_dir / "status.json") or {"state": "idle", "detail": "", "ts": None}
    heartbeat = read_json(page_dir / "heartbeat.json") or {}
    session = read_json(page_dir / "session.json") or {}
    events = read_events(page_dir)
    # What `wait` has delivered to Claude: an action past this seq can't have
    # been seen (so not declined), which is what lets the runtime carry it
    # forward onto versions written without it.
    cursor = (read_json(page_dir / "cursor.json") or {}).get("seq", 0)
    return {
        "versions": published_versions(page_dir),
        "status": status,
        "listening": time.time() - heartbeat.get("t", 0) < HEARTBEAT_FRESH_SECS,
        "cursor": cursor,
        # Posted since the last handoff: Claude has not seen these yet.
        "pending": sum(1 for e in events if e["seq"] > cursor and e.get("author") == "user"),
        # None when nothing claimed the page — interact.py run outside Claude Code.
        "session_alive": pid_alive(session["pid"]) if session.get("pid") else None,
        "events": events,
    }


class Handler(BaseHTTPRequestHandler):
    page_dir = None  # set before serving

    def log_message(self, *args):
        pass

    def _send(self, status: int, ctype: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status: int = 200) -> None:
        self._send(status, "application/json", json.dumps(obj, ensure_ascii=False).encode())

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            versions = published_versions(self.page_dir)
            if not versions:
                self._json({"error": "no published versions yet"}, 404)
                return
            self.send_response(302)
            self.send_header("Location", f"/versions/{versions[-1]}")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/api/state":
            self._json(full_state(self.page_dir))
            return
        # Browsers ask for this unprompted. Answering "no content" rather than
        # letting it fall through to 404 keeps the console clean, which is what
        # makes an empty console worth asserting on (tests/test_render.py).
        if path == "/favicon.ico":
            self._send(204, "image/x-icon", b"")
            return
        if SERVED_PATH.fullmatch(path):
            if path.startswith("/versions/") and Path(path).name not in published_versions(
                self.page_dir
            ):
                self._json({"error": "not published yet — `note` the version first"}, 404)
                return
            file = self.page_dir / path.lstrip("/")
            # is_file, not exists: the vendor pattern admits "." and "..", which
            # resolve to directories.
            if file.is_file():
                ctype = CONTENT_TYPES.get(Path(path).suffix, "application/octet-stream")
                self._send(200, f"{ctype}; charset=utf-8", file.read_bytes())
                return
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path != "/api/event":
            self._json({"error": "not found"}, 404)
            return
        try:
            event = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        except json.JSONDecodeError:
            self._json({"error": "invalid JSON"}, 400)
            return
        if not isinstance(event, dict):
            self._json({"error": "event must be a JSON object"}, 400)
            return
        if event.get("kind") not in BROWSER_EVENT_KINDS:
            self._json({"error": f"kind must be one of {sorted(BROWSER_EVENT_KINDS)}"}, 400)
            return
        if event["kind"] == "action" and not (
            isinstance(event.get("widget"), str)
            and event["widget"]
            and isinstance(event.get("action"), str)
            and event["action"]
            and isinstance(event.get("detail"), dict)
            and isinstance(event.get("version"), int)
        ):
            self._json(
                {
                    "error": "action events need non-empty string `widget` and `action`,"
                    " object `detail`, integer `version`"
                },
                400,
            )
            return
        # The server owns identity: a client-supplied id could collide with an
        # existing event's and silently re-root its thread.
        event.pop("id", None)
        event["author"] = "user"
        self._json({"ok": True, "event": append_event(self.page_dir, event)})


def layer_dirs() -> list:
    """Widget-layer sources, lowest precedence first: colloquy's shipped defaults,
    the user layer, the project layer (resolved against the working directory).
    Each mirrors the assets layout: theme.css/registry.json/colloquy.js at the
    top, modules in widgets/, third-party files in vendor/. The user layer shares
    ~/.claude/colloquy/ with page directories, which reserves `widgets` and
    `vendor` as page slugs."""
    return [ASSETS, colloquy_home(), Path.cwd() / ".claude" / "colloquy"]


def cmd_init(page_dir: Path) -> None:
    (page_dir / "versions").mkdir(parents=True, exist_ok=True)
    for stray in page_dir.glob("*.tmp"):  # a killed writer's write_json leftovers
        stray.unlink()
    for layer in layer_dirs():
        if not layer.is_dir() or layer.resolve() == page_dir.resolve():
            continue
        for name in VENDORED_FILES:
            src = layer / name
            if src.is_file():
                (page_dir / name).write_bytes(src.read_bytes())
        for sub in VENDORED_DIRS:
            src_dir = layer / sub
            if not src_dir.is_dir():
                continue
            (page_dir / sub).mkdir(exist_ok=True)
            for src in src_dir.iterdir():
                if src.is_file():
                    (page_dir / sub / src.name).write_bytes(src.read_bytes())
    if not (page_dir / "status.json").exists():
        cmd_status(page_dir, "working", "Writing the page")
    print(f"initialized {page_dir}")


def cmd_serve(page_dir: Path) -> None:
    claim_page(page_dir)
    existing = running_server(page_dir)
    if existing:
        print(existing["url"], flush=True)
        return
    Handler.page_dir = page_dir
    Handler.protocol_version = "HTTP/1.1"
    base = 41000 + zlib.crc32(str(page_dir.resolve()).encode()) % 4000
    httpd = None
    for port in [*range(base, base + 10), 0]:
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError as e:
            if e.errno != errno.EADDRINUSE:
                raise
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    write_json(page_dir / "server.json", {"port": httpd.server_address[1], "pid": os.getpid(), "url": url})
    print(url, flush=True)
    try:
        httpd.serve_forever()
    finally:
        (page_dir / "server.json").unlink(missing_ok=True)


def cmd_status(page_dir: Path, state: str, detail: str, handoff: bool = False) -> None:
    status = {"state": state, "detail": detail, "ts": now_iso()}
    if handoff:
        status["handoff"] = True
    write_json(page_dir / "status.json", status)


def revive_server(page_dir: Path) -> bool:
    """Bring a page back up after its server died. The reviewer's browser has
    been showing "Server offline" since it happened, and `wait` is the only thing
    positioned to notice — so it restarts the server rather than handing the
    diagnosis to Claude and the discovery to the reviewer.

    Detached, because the restarted server has to outlive both this `wait` and
    the background task that started it, exactly as the original `serve` does.
    sys.executable is the resolved uv environment, so this skips uv entirely."""
    (page_dir / "server.json").unlink(missing_ok=True)
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "serve", str(page_dir)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.time() + 5
    while time.time() < deadline:
        time.sleep(0.1)
        if running_server(page_dir):
            return True
    return False


def cmd_wait(page_dir: Path) -> int:
    claim_page(page_dir)
    cursor = (read_json(page_dir / "cursor.json") or {}).get("seq", 0)
    server_check_at = 0.0
    revived = False
    try:
        while True:
            write_json(page_dir / "heartbeat.json", {"t": time.time()})
            events = read_events(page_dir)
            new_user = [e for e in events if e["seq"] > cursor and e.get("author") == "user"]
            if new_user:
                for event in new_user:
                    print(json.dumps(event, ensure_ascii=False), flush=True)
                # cursor after print: a kill mid-wait redelivers rather than drops
                write_json(page_dir / "cursor.json", {"seq": events[-1]["seq"]})
                # flip status here, not in Claude's next turn: the handoff gap
                # between this exit and Claude's pickup must not show "waiting".
                # handoff=True dates the claim — Claude's own `status` clears it,
                # so this detail still standing minutes later means the pickup
                # never happened, and the banner says so.
                # "update", not "comment": the batch may mix comments and widget actions
                n = len(new_user)
                cmd_status(
                    page_dir, "working", f"picking up {n} update{'s' if n != 1 else ''}", handoff=True
                )
                return 0
            if time.time() > server_check_at:
                server_check_at = time.time() + 5
                if not running_server(page_dir):
                    # An idle page has no reviewer to keep online, and the
                    # SessionEnd hook idles then stops: without this the watcher
                    # it raced would put the server straight back up.
                    if (read_json(page_dir / "status.json") or {}).get("state") == "idle":
                        print("the review is closed; not restarting the server", file=sys.stderr)
                        return 2
                    # One revival per wait: a server that dies the moment it comes
                    # up would otherwise respawn every five seconds forever.
                    if revived or not revive_server(page_dir):
                        print("server is not running; restart it with `serve`", file=sys.stderr)
                        return 2
                    revived = True
                    print(
                        f"server had died; restarted at {running_server(page_dir)['url']}",
                        file=sys.stderr,
                        flush=True,
                    )
            time.sleep(1)
    finally:
        (page_dir / "heartbeat.json").unlink(missing_ok=True)


def read_text_arg(text) -> str:
    body = text if text is not None else sys.stdin.read()
    if not body.strip():
        sys.exit("empty text (pass --text or pipe via stdin)")
    return body.strip()


def reply_widget_ids(page_dir: Path) -> set:
    """Ids claimed by widget markup in logged replies. Reply markup is frozen in
    the log and rendered into the thread panel, so its ids share one universe
    with page ids — the runtime resolves actions document-wide by id, and a
    collision would silently redirect a thread widget's replay to the page."""
    ids = set()
    for e in read_events(page_dir):
        # author gate mirrors the renderer: only Claude's replies inject HTML — a
        # user reply merely quoting markup renders as text and claims nothing.
        if (
            e.get("kind") == "reply"
            and e.get("author") == "claude"
            and "<cq-" in (e.get("text") or "")
        ):
            p = _StructParser()
            p.feed(e["text"])
            ids |= p.ids
    return ids


def version_ids(page_dir: Path) -> set:
    ids = set()
    for name in list_versions(page_dir):
        p = _StructParser()
        p.feed((page_dir / "versions" / name).read_text(encoding="utf-8"))
        ids |= p.ids
    return ids


def cmd_reply(page_dir: Path, to: str, text) -> None:
    known = {e["id"] for e in read_events(page_dir) if e.get("kind") in {"comment", "reply"}}
    if to not in known:
        sys.exit(f"unknown comment id {to!r}; known: {sorted(known)}")
    body = read_text_arg(text)
    # A reply carrying widget markup renders live in the thread, so it validates
    # against the vendored registry at post time — the discussion-side `check`.
    if "<cq-" in body:
        registry = load_registry(page_dir)
        if registry is None:
            sys.exit("reply carries widget markup but the page has no registry.json; run `init`")
        errs = fragment_errors(body, registry)
        if errs:
            sys.exit("reply widget markup doesn't validate:\n" + "\n".join(f"  - {e}" for e in errs))
        frag = _StructParser()
        frag.feed(body)
        if frag.duplicate_ids:
            sys.exit(f"reply widget markup reuses an id within itself: {frag.duplicate_ids}")
        clash = sorted(frag.ids & (version_ids(page_dir) | reply_widget_ids(page_dir)))
        if clash:
            sys.exit(f"reply widget ids already taken by the page or an earlier reply: {clash}")
    event = append_event(page_dir, {"kind": "reply", "author": "claude", "parent": to, "text": body})
    print(json.dumps(event, ensure_ascii=False))


def cmd_note(page_dir: Path, version: int, text) -> None:
    name = f"v{version:03d}.html"
    if name not in list_versions(page_dir):
        sys.exit(f"no {name} in {page_dir / 'versions'}; write the version file first")
    # `note` publishes (the server exposes only noted versions), so it is the one
    # gate: a version that fails `check` can't go live.
    if cmd_check(page_dir, version) != 0:
        sys.exit(f"refusing to publish {name}: `check` failed (issues above)")
    event = append_event(
        page_dir, {"kind": "note", "author": "claude", "version": version, "text": read_text_arg(text)}
    )
    print(json.dumps(event, ensure_ascii=False))


def cmd_events(page_dir: Path, after: int) -> None:
    for event in read_events(page_dir):
        if event["seq"] > after:
            print(json.dumps(event, ensure_ascii=False))


def cmd_export(page_dir: Path) -> None:
    """The review thread as Markdown, for reuse in a PR description."""
    events = read_events(page_dir)
    versions = list_versions(page_dir)
    title = ""
    if versions:
        m = re.search(r"<title>(.*?)</title>", (page_dir / "versions" / versions[-1]).read_text(encoding="utf-8"), re.S)
        title = m.group(1).strip() if m else ""
    print(f"## Review: {title or page_dir.name}")

    notes = [e for e in events if e.get("kind") == "note"]
    if notes:
        print("\n### Versions\n")
        for e in notes:
            print(f"- v{e['version']}: {e['text']}")

    # The reviewer's direct edits are review outcomes; without them the export
    # understates the review whenever a changelog note doesn't restate them.
    # Widget-agnostic rendering: verb + detail pairs, against the version edited.
    actions = [e for e in events if e.get("kind") == "action"]
    if actions:
        print("\n### Edits\n")
        for e in actions:
            detail = " ".join(f"{k}={v}" for k, v in (e.get("detail") or {}).items())
            print(f"- `{e.get('widget')}`: {e.get('action')} {detail} (on v{e.get('version')})")

    threads = {}
    for e in events:
        if e.get("kind") == "comment":
            threads[e["id"]] = {"root": e, "msgs": [e], "resolved": False}
    index = {e["id"]: e for e in events if "id" in e}
    for e in events:
        if e.get("kind") not in ("reply", "resolve"):
            continue
        cur = e
        for _ in range(50):
            cur = index.get(cur.get("parent"))
            if cur is None or cur.get("kind") == "comment":
                break
        thread = cur and threads.get(cur["id"])
        if not thread:
            continue
        if e["kind"] == "reply":
            thread["msgs"].append(e)
        else:
            thread["resolved"] = True

    if threads:
        print("\n### Threads\n")
    for t in threads.values():
        anchor = t["root"].get("anchor") or {}
        if anchor.get("quote"):
            head = f"> “{anchor['quote']}”"
        elif anchor.get("section"):
            head = f"> § {anchor['section']}"
        else:
            head = "> (page-level)"
        print(head + ("  — resolved" if t["resolved"] else ""))
        for m in t["msgs"]:
            who = "Claude" if m.get("author") == "claude" else "User"
            body = (m.get("text") or "").replace("\n", "\n  ")
            print(f"- **{who}**: {body}")
        print()
    for e in events:
        if e.get("kind") == "done":
            print(f"Approved at {e.get('ts', '?')}.")
            break


CATALOG_PREAMBLE = """\
# Widget vocabulary, vendored for this page — `check` validates against it.
#
# Widgets are cq-* elements in the authored HTML; attributes carry scalars
# (enums, flags), children carry prose, and an item's title is a leading
# <strong> child. Every cq-* element takes an explicit end tag — never
# <cq-foo/>. Ids are authored (lowercase kebab), unique, stable across
# versions. Each entry is JSON Schema over the attributes; x-parent names the
# required parent, x-content the content model (prose | items | data | none).
# A "data" body is text in the notation the description names, < > escaped.
# x-upgrade marks tags a JS module enhances in the browser — the interactive
# widgets and the data-body renderers; x-chips names attributes the theme
# renders as chips.
"""


def cmd_catalog(page_dir: Path) -> None:
    reg = read_json(page_dir / "registry.json")
    if reg is None:
        sys.exit(f"no registry.json in {page_dir}; run `init` first")
    print(CATALOG_PREAMBLE)
    print(json.dumps({k: v for k, v in reg.items() if not k.startswith("$")}, indent=2, ensure_ascii=False))
    idioms = reg.get("$idioms")
    if idioms:
        print("\n# Theme idioms — shapes the theme styles directly; no registry entry, no JS.\n")
        print(json.dumps(idioms, indent=2, ensure_ascii=False))


def cmd_stop(page_dir: Path) -> str:
    info = running_server(page_dir)
    if info:
        os.kill(info["pid"], signal.SIGTERM)
        outcome = f"stopped server pid {info['pid']}"
    else:
        outcome = "no server running"
    (page_dir / "server.json").unlink(missing_ok=True)
    return outcome


# ---------- hook: the review loop, enforced rather than remembered ----------


def unattended_pages(session_id: str) -> list:
    """This session's pages the reviewer is looking at with nobody on the other
    end, each with what to do about it. The invariant is that a page is either
    watched or idle: between turns there is no third state, so anything else is
    a review that has quietly stopped."""
    reasons = []
    for page_dir in owned_pages(session_id):
        state = full_state(page_dir)
        if state["listening"]:
            # A live `wait` is the watch, and it delivers what's pending on its own.
            # Reporting the page here would have Claude start a second one, and two
            # waiters race the cursor and deliver the same events twice.
            continue
        n = state["pending"]
        if n:
            reasons.append(
                f"{page_dir}: {n} user event{'s' if n != 1 else ''} you haven't picked up."
                " `wait` prints them; address every one."
            )
        elif state["status"]["state"] != "idle":
            reasons.append(
                f"{page_dir}: no watcher. Start `wait` on it as a background task,"
                " or `status <dir> idle` if the review is over."
            )
    return reasons


def cmd_hook(payload: dict) -> None:
    event, sid = payload.get("hook_event_name"), payload.get("session_id") or ""
    if event == "SessionEnd":
        for page_dir in owned_pages(sid):
            cmd_status(page_dir, "idle", "the session that opened this page has ended")
            cmd_stop(page_dir)
        (colloquy_home() / ".sessions" / f"{sid}.json").unlink(missing_ok=True)
        return
    # stop_hook_active means this hook already blocked once and Claude is running
    # again on the strength of it; blocking a second time is how a hook loops.
    if event == "Stop" and payload.get("stop_hook_active"):
        return
    reasons = unattended_pages(sid)
    if not reasons:
        return
    message = "colloquy — a review page of this session's is unattended:\n" + "\n".join(
        f"- {r}" for r in reasons
    )
    if event == "Stop":
        print(json.dumps({"decision": "block", "reason": message}))
    else:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": message,
                    }
                }
            )
        )


# ---------- check: deterministic pre-handover lint ----------

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}
# Elements whose end tag HTML lets you omit — leaving one "unclosed" is valid,
# so the balance check must not flag them (only genuinely-open structural
# elements like <div>/<section> point at a real layout bug).
OPTIONAL_END = {
    "p", "li", "dd", "dt", "td", "th", "tr", "thead", "tbody", "tfoot",
    "option", "optgroup", "caption", "colgroup", "rp", "rt",
    "html", "head", "body",
}
# A start tag on the left implicitly closes matching open elements on the right.
P_CLOSERS = {
    "address", "article", "aside", "blockquote", "details", "div", "dl",
    "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3",
    "h4", "h5", "h6", "header", "hgroup", "hr", "main", "menu", "nav", "ol",
    "p", "pre", "section", "table", "ul",
}
# Container selectors whose max-width defines the readable column.
COLUMN_SELECTORS = ("main", "body", "article", ".container", ".wrap", ".content", ".page")
COLUMN_FALLBACK = 780
# Attribute widths only count as pixels on these elements.
PIXEL_WIDTH_TAGS = {"img", "svg", "table", "canvas", "iframe", "video", "object"}
# Page-level declarations the runtime reads from <meta name="cq-*"> in the head,
# name → allowed content values (None = free-form). A misspelled name or value
# would silently declare nothing in the browser, so `check` owns this vocabulary
# the way the registry owns cq-* elements.
CQ_META = {"cq-base": None, "cq-review": frozenset({"sign-off"})}


class _StructParser(HTMLParser):
    """Tracks a tag stack to catch unclosed and mismatched tags, and collects
    element ids, every <script src> tag, stylesheet links, and each cq-* element
    (attributes, direct parent, direct children, direct text) for registry
    validation. Foreign markup inside <svg> is skipped (SVG has its own
    self-closing rules that don't matter here)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []  # (tag, lineno, cq_record | None)
        self.errors = []
        self.all_ids = []
        self.external_scripts = []  # (src, type)
        self.stylesheets = []  # hrefs of rel=stylesheet links
        self.cq_metas = []  # {"name", "content", "line"} for <meta name="cq-*">
        self.cq_elements = []  # {"tag", "line", "attrs", "parent", "children", "text"}
        self._svg_depth = 0

    @property
    def ids(self) -> set:
        return set(self.all_ids)

    @property
    def duplicate_ids(self) -> list:
        seen, dupes = set(), set()
        for i in self.all_ids:
            (dupes if i in seen else seen).add(i)
        return sorted(dupes)

    def _implicit_close(self, tag):
        """Pop open elements that this start tag implicitly closes (HTML's
        optional-end-tag rules for p / list items / table cells)."""
        top = lambda: self.stack[-1][0] if self.stack else None
        if tag in P_CLOSERS:
            while top() == "p":
                self.stack.pop()
        if tag == "li":
            while top() == "li":
                self.stack.pop()
        elif tag in ("dt", "dd"):
            while top() in ("dt", "dd"):
                self.stack.pop()
        elif tag in ("td", "th"):
            while top() in ("td", "th"):
                self.stack.pop()
        elif tag == "tr":
            while top() in ("td", "th", "tr"):
                self.stack.pop()
        elif tag in ("thead", "tbody", "tfoot"):
            while top() in ("td", "th", "tr", "thead", "tbody", "tfoot"):
                self.stack.pop()
        elif tag == "option":
            while top() == "option":
                self.stack.pop()
        elif tag == "optgroup":
            while top() in ("option", "optgroup"):
                self.stack.pop()

    def _harvest(self, tag, attrs_d):
        if attrs_d.get("id"):
            self.all_ids.append(attrs_d["id"])
        if tag == "script" and attrs_d.get("src"):
            self.external_scripts.append((attrs_d["src"], attrs_d.get("type")))
        if tag == "link" and "stylesheet" in (attrs_d.get("rel") or ""):
            self.stylesheets.append(attrs_d.get("href"))
        if tag == "meta" and (attrs_d.get("name") or "").startswith("cq-"):
            self.cq_metas.append(
                {"name": attrs_d["name"], "content": attrs_d.get("content"), "line": self.getpos()[0]}
            )

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        self._harvest(tag, attrs_d)
        if tag == "svg":
            self._svg_depth += 1
            self.stack.append((tag, self.getpos()[0], None))
            return
        if self._svg_depth:  # don't tag-balance inside SVG
            return
        if tag in VOID_TAGS:
            if self.stack and self.stack[-1][2] is not None:
                self.stack[-1][2]["children"].append(tag)
            return
        self._implicit_close(tag)
        if self.stack and self.stack[-1][2] is not None:
            self.stack[-1][2]["children"].append(tag)
        record = None
        if tag.startswith("cq-"):
            record = {
                "tag": tag,
                "line": self.getpos()[0],
                "attrs": attrs_d,
                "parent": self.stack[-1][0] if self.stack else None,
                "children": [],
                "text": False,
            }
            self.cq_elements.append(record)
        self.stack.append((tag, self.getpos()[0], record))

    def handle_startendtag(self, tag, attrs):
        # <foo/> — self-closing; still harvest but never pushed. For cq-* the
        # slash is a trap: HTML ignores it, the element stays open in a browser
        # and swallows the rest of its parent, so reject the form outright.
        self._harvest(tag, dict(attrs))
        if self._svg_depth:  # SVG has real self-closing syntax
            return
        if tag.startswith("cq-"):
            self.errors.append(
                f"<{tag}/> at line {self.getpos()[0]} is self-closing: HTML ignores "
                f"the slash and the element would swallow what follows — write "
                f"<{tag} …></{tag}>"
            )
        elif self.stack and self.stack[-1][2] is not None:
            self.stack[-1][2]["children"].append(tag)

    def handle_data(self, data):
        if self.stack and self.stack[-1][2] is not None and data.strip():
            self.stack[-1][2]["text"] = True

    def handle_endtag(self, tag):
        if tag == "svg":
            while self.stack and self.stack[-1][0] != "svg":
                self.stack.pop()
            if self.stack:
                self.stack.pop()
            self._svg_depth = max(0, self._svg_depth - 1)
            return
        if self._svg_depth or tag in VOID_TAGS:
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                orphaned = [(t, ln) for t, ln, _ in self.stack[i + 1:] if t not in OPTIONAL_END]
                if orphaned:
                    unclosed = ", ".join(f"<{t}> (line {ln})" for t, ln in orphaned)
                    self.errors.append(f"</{tag}> at line {self.getpos()[0]} closes over unclosed: {unclosed}")
                del self.stack[i:]
                return
        if tag not in OPTIONAL_END:
            self.errors.append(f"stray </{tag}> at line {self.getpos()[0]} with no matching open tag")


def _column_width(html: str, theme_css: str = "") -> int:
    """Best-effort readable-column width from the max-width of a container rule.
    A page's own <style> wins over the vendored theme, which wins over the fallback."""
    for css in (html, theme_css):
        widths = []
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
            selector, body = m.group(1), m.group(2)
            if not any(sel in selector for sel in COLUMN_SELECTORS):
                continue
            mw = re.search(r"max-width\s*:\s*(\d+(?:\.\d+)?)px", body)
            if mw:
                widths.append(float(mw.group(1)))
        if widths:
            return int(max(widths))
    return COLUMN_FALLBACK


def _overwide_elements(html: str, column: int) -> list:
    """Fixed pixel widths (width/min-width) that exceed the column. Percentages,
    vw, and unitless viewBox numbers are ignored — only px is a hard overflow."""
    hits = []
    # CSS rules: width / min-width in px (not max-width).
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", html):
        selector, body = m.group(1).strip(), m.group(2)
        for prop in ("width", "min-width"):
            wm = re.search(rf"(?<!-){prop}\s*:\s*(\d+(?:\.\d+)?)px", body)
            if wm and float(wm.group(1)) > column:
                hits.append(f"rule `{selector}` sets {prop}: {wm.group(1)}px (column is {column}px)")
    # Inline style="… width: Npx …".
    for m in re.finditer(r'style\s*=\s*"([^"]*)"', html):
        css = m.group(1)
        for prop in ("width", "min-width"):
            wm = re.search(rf"(?<!-){prop}\s*:\s*(\d+(?:\.\d+)?)px", css)
            if wm and float(wm.group(1)) > column:
                hits.append(f'inline style {prop}: {wm.group(1)}px (column is {column}px)')
    # width="N" attributes on raster/media elements (treated as px).
    for m in re.finditer(r"<(\w+)\b([^>]*)>", html):
        tag, rest = m.group(1).lower(), m.group(2)
        if tag not in PIXEL_WIDTH_TAGS:
            continue
        wm = re.search(r'\bwidth\s*=\s*"(\d+(?:\.\d+)?)"', rest)
        if wm and float(wm.group(1)) > column:
            hits.append(f'<{tag} width="{wm.group(1)}"> exceeds column ({column}px)')
    return hits


def load_registry(page_dir: Path):
    """The vendored vocabulary: tag → schema entry. None when the page has no
    vendored registry.json (an un-initialized directory)."""
    reg = read_json(page_dir / "registry.json")
    if reg is None:
        return None
    return {tag: entry for tag, entry in reg.items() if tag.startswith("cq-")}


def widget_errors(cq_elements: list, registry: dict) -> list:
    """Validate parsed cq-* elements against the registry: schema over the
    attribute instance, x-parent nesting, and the x-content model."""
    errors = []
    # Containers ("items") admit exactly the tags that declare them as x-parent.
    children_of = {}
    for tag, entry in registry.items():
        parent = entry.get("x-parent")
        if parent:
            children_of.setdefault(parent, set()).add(tag)

    for rec in cq_elements:
        tag, where = rec["tag"], f"<{rec['tag']}> (line {rec['line']})"
        entry = registry.get(tag)
        if entry is None:
            errors.append(f"{where}: unknown widget — not in the vendored registry.json")
            continue
        # The element validates as the instance built from its attributes:
        # values as strings, flag attributes as True. HTML's two flag spellings
        # (bare and ="") both mean true; a literal value on a flag stays a string
        # so it fails loudly rather than silently meaning true.
        props = entry.get("properties", {})
        instance = {
            name: True
            if value in (None, "") and props.get(name, {}).get("type") == "boolean"
            else (value or "")
            for name, value in rec["attrs"].items()
        }
        for err in sorted(Draft202012Validator(entry).iter_errors(instance), key=str):
            errors.append(f"{where}: {err.message}")

        want_parent = entry.get("x-parent")
        if want_parent and rec["parent"] != want_parent:
            actual = f", found <{rec['parent']}>" if rec["parent"] else ""
            errors.append(f"{where}: must be a direct child of <{want_parent}>{actual}")
        # Tags declaring this one as x-parent are admissible children under any
        # content model — that is what x-parent means. "data" forbids all others
        # (the body is text in a notation), "items" also forbids loose text,
        # "none" forbids everything.
        content = entry.get("x-content", "prose")
        allowed = children_of.get(tag, set())
        stray = sorted({c for c in rec["children"] if c not in allowed})
        if content == "none" and (rec["children"] or rec["text"]):
            errors.append(f"{where}: takes no content — write <{tag} …></{tag}>")
        elif content == "data" and stray:
            errors.append(
                f"{where}: its body is data (text only; escape < and >), "
                f"found element children: {stray}"
            )
        elif content == "items":
            if stray:
                errors.append(f"{where}: admits only {sorted(allowed)} children, found {stray}")
            if rec["text"]:
                errors.append(f"{where}: loose text between its items isn't allowed")
    return errors


def fragment_errors(html: str, registry: dict) -> list:
    """Structural + registry validation of a markup fragment (a Claude reply
    carrying widgets): the discussion-side analog of `check`."""
    parser = _StructParser()
    parser.feed(html)
    parser.close()
    errors = list(parser.errors)
    leftover = [(t, ln) for t, ln, _ in parser.stack if t not in OPTIONAL_END]
    if leftover:
        errors.append("unclosed tags: " + ", ".join(f"<{t}>" for t, _ in leftover))
    errors.extend(widget_errors(parser.cq_elements, registry))
    return errors


def cmd_check(page_dir: Path, version) -> int:
    versions = list_versions(page_dir)
    if not versions:
        sys.exit(f"no versions in {page_dir / 'versions'}; write versions/v001.html first")
    name = f"v{version:03d}.html" if version is not None else versions[-1]
    if name not in versions:
        sys.exit(f"no {name} in {page_dir / 'versions'}")
    html = (page_dir / "versions" / name).read_text(encoding="utf-8")

    errors = []

    for missing in [f for f in VENDORED_FILES if not (page_dir / f).exists()]:
        errors.append(f"{missing} missing from the page directory — run `init` to vendor the layer")

    parser = _StructParser()
    parser.feed(html)
    parser.close()
    errors.extend(parser.errors)
    leftover = [(t, ln) for t, ln, _ in parser.stack if t not in OPTIONAL_END]
    if leftover:
        unclosed = ", ".join(f"<{t}> (line {ln})" for t, ln in leftover)
        errors.append(f"unclosed tags at end of document: {unclosed}")

    scripts = parser.external_scripts
    if len(scripts) != 1:
        errors.append(
            f"expected exactly one external <script src> tag, found {len(scripts)}"
            + (f": {[s for s, _ in scripts]}" if scripts else "")
        )
    elif scripts[0] != ("/colloquy.js", "module"):
        errors.append(
            'the external script must be <script type="module" src="/colloquy.js">, '
            f"found src={scripts[0][0]!r} type={scripts[0][1]!r}"
        )
    if parser.stylesheets != ["/theme.css"]:
        errors.append(
            'the page must link exactly one stylesheet, <link rel="stylesheet" '
            f'href="/theme.css">, found {parser.stylesheets}'
        )

    for meta in parser.cq_metas:
        where = f'<meta name="{meta["name"]}"> (line {meta["line"]})'
        if meta["name"] not in CQ_META:
            errors.append(f"{where}: unknown cq- meta — known: {sorted(CQ_META)}")
            continue
        allowed = CQ_META[meta["name"]]
        if allowed is not None and meta["content"] not in allowed:
            errors.append(
                f"{where}: content must be one of {sorted(allowed)}, found {meta['content']!r}"
            )

    if parser.duplicate_ids:
        errors.append(f"duplicate ids (anchors need unique targets): {parser.duplicate_ids}")

    registry = load_registry(page_dir)
    if registry is not None:
        errors.extend(widget_errors(parser.cq_elements, registry))
        for tag, entry in registry.items():
            if entry.get("x-upgrade") and not (page_dir / "widgets" / f"{tag}.js").is_file():
                errors.append(
                    f"registry marks <{tag}> as upgraded but widgets/{tag}.js "
                    f"isn't vendored — run `init`"
                )

    idx = versions.index(name)
    if idx > 0:
        prev_name = versions[idx - 1]
        prev = _StructParser()
        prev.feed((page_dir / "versions" / prev_name).read_text(encoding="utf-8"))
        prev.close()
        dropped = sorted(prev.ids - parser.ids)
        if dropped:
            errors.append(
                f"ids present in {prev_name} but dropped in {name} "
                f"(anchors on them will break): {dropped}"
            )

    # Reply markup is frozen in the log and rendered into the panel; a page id
    # colliding with one would steal its action replays (see reply_widget_ids).
    taken = sorted(parser.ids & reply_widget_ids(page_dir))
    if taken:
        errors.append(f"ids already taken by widget markup in a reply: {taken}")

    theme_css = (page_dir / "theme.css").read_text(encoding="utf-8") if (page_dir / "theme.css").exists() else ""
    column = _column_width(html, theme_css)
    errors.extend(_overwide_elements(html, column))

    if errors:
        print(f"✗ {name}: {len(errors)} issue(s)", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(
        f"✓ {name}: parses, widgets validate, one module script + theme link, "
        f"ids carried over, nothing overflows the {column}px column"
    )
    return 0


def resolve_dir(dir_arg: str, must_exist: bool = True) -> Path:
    page_dir = Path(dir_arg).expanduser().resolve()
    if must_exist and not page_dir.is_dir():
        sys.exit(f"{page_dir} does not exist; run `init` first")
    return page_dir


@click.group()
def cli() -> None:
    """Serve and mediate an interactive colloquy page."""


@cli.command()
@click.argument("dir")
def init(dir: str) -> None:
    """Create the page directory layout and vendor the widget layer into it.

    Re-running it is the explicit re-vendor for a live page; note the re-vendor
    in the next version's changelog."""
    cmd_init(resolve_dir(dir, must_exist=False))


@cli.command()
@click.argument("dir")
def serve(dir: str) -> None:
    """Serve the page on localhost (reuses a live server); prints the URL."""
    cmd_serve(resolve_dir(dir))


@cli.command()
@click.argument("dir")
@click.argument("state", type=click.Choice(["working", "waiting", "idle"]))
@click.argument("detail", required=False, default="")
def status(dir: str, state: str, detail: str) -> None:
    """Declare Claude's state for the banner."""
    page_dir = resolve_dir(dir)
    # Idling over undelivered events ends the review on a reviewer still owed an
    # answer. Here rather than in cmd_status because SessionEnd idles pages whose
    # session is already gone, where nothing is left to pick them up.
    pending = full_state(page_dir)["pending"] if state == "idle" else 0
    if pending:
        sys.exit(
            f"{pending} user event{'s' if pending != 1 else ''} nobody has picked up; "
            "idling closes the review over them. `wait` prints them and returns at "
            "once when events are already waiting."
        )
    cmd_status(page_dir, state, detail)


@cli.command()
@click.argument("dir")
def wait(dir: str) -> None:
    """Block until new user events arrive, print them as JSON lines, exit."""
    sys.exit(cmd_wait(resolve_dir(dir)))


@cli.command()
@click.argument("dir")
@click.option("--to", required=True, help="id of the comment or reply being answered")
@click.option("--text")
def reply(dir: str, to: str, text: str) -> None:
    """Post a threaded reply as Claude (--text or stdin)."""
    cmd_reply(resolve_dir(dir), to, text)


@cli.command()
@click.argument("dir")
@click.option("--version", type=int, required=True)
@click.option("--text")
def note(dir: str, version: int, text: str) -> None:
    """Post a one-line changelog for a version (--text or stdin)."""
    cmd_note(resolve_dir(dir), version, text)


@cli.command()
@click.argument("dir")
@click.option("--after", type=int, default=0, help="only events with seq greater than this")
def events(dir: str, after: int) -> None:
    """Print the event log as JSON lines."""
    cmd_events(resolve_dir(dir), after)


@cli.command()
@click.argument("dir")
def stop(dir: str) -> None:
    """Stop the server."""
    print(cmd_stop(resolve_dir(dir)))


@cli.command()
def hook() -> None:
    """Answer a Claude Code hook: event JSON on stdin, hook response on stdout.

    Registered in hooks/hooks.json for Stop, UserPromptSubmit and SessionEnd,
    which it tells apart by the payload's hook_event_name."""
    cmd_hook(json.load(sys.stdin))


@cli.command()
@click.argument("dir")
@click.option("--version", type=int, default=None, help="version to check (default: latest)")
def check(dir: str, version: int) -> None:
    """Deterministic pre-handover lint of a version."""
    sys.exit(cmd_check(resolve_dir(dir), version))


@cli.command()
@click.argument("dir")
def catalog(dir: str) -> None:
    """Print the page's vendored vocabulary: widget schemas, then theme idioms."""
    cmd_catalog(resolve_dir(dir))


@cli.command()
@click.argument("dir")
def export(dir: str) -> None:
    """Print the review thread as Markdown, for reuse in a PR description."""
    cmd_export(resolve_dir(dir))


if __name__ == "__main__":
    cli()
