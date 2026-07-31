#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["click>=8", "jsonschema>=4", "tinycss2>=1.4"]
# ///
"""Serve and mediate an interactive colloquy page.

A `uv` script: the PEP 723 header above declares the dependencies, and `uv` is
the one prerequisite for the whole plugin — no venv to create, no build step.
Run it with `uv run interact.py <group> <command> …`, or as
`colloquy <group> <command> …` through the plugin's `bin/colloquy` launcher.
Claude Code puts that launcher on PATH; Codex resolves it from the active skill.

A page directory holds:
    versions/v1.html…    immutable page versions (the agent writes them). The server
                         exposes a version only once `version publish` lands its
                         note, after `version check` passes, so a half-written or
                         broken file is never live to an open browser.
    colloquy.js          the runtime (widget layer + comment layer), served at /colloquy.js
    theme.css            tokens, element styles, class idioms, element-widget CSS
    registry.json        the widget vocabulary: JSON Schema per cq-* tag, plus the
                         layer-wide facts under $ — $idioms, $languages, and the page's
                         vocabulary stamp ($events, x-state): the one statement of what
                         this page's vendored runtime speaks
    widgets/             one ES module per upgraded widget (cq-tabs.js, cq-diagram.js)
    vendor/              vendored third-party assets (mermaid.min.js, sortable.esm.js)
    media/               images the page shows, each named by the hash of its bytes
                         (`page media`). Not vendored — this is the page's content,
                         not the layer's — but served the same way, and
                         content-addressing is what lets content live here at all: a
                         name means one set of bytes forever, so a version the
                         reviewer approved cannot show them different pixels later,
                         and two versions showing the same screenshot share the one
                         file rather than a copy each
    comments.jsonl       append-only event log; an event's seq is its line number (1-based)
    status.json          the agent's declared state: {"state": working|waiting|idle, "detail", "ts"};
                         when delivery wakes a non-working page, `review wait` writes
                         it working with "handoff": true until the agent's own
                         `review state` lands
    heartbeat.json       watcher liveness, bumped by `review wait` while it runs
    cursor.json          seq of the last event delivered to the agent, written by
                         `review wait` on exit
    server.json          {"port", "pid", "url"} for the running server
    access.json          {"host", "token"}: the address the page is served on and the
                         key its URL carries. Minted at the first `server run` and kept,
                         because a restart has to reproduce the URL an open browser is
                         already polling
    session.json         {"id", "pid", "agent"} of the agent session last working on the page

status.json is a claim, and a claim never expires on its own: an agent that
stopped watching renders exactly like one that is watching and has nothing to
say, so a comment can sit unread with the page still reading "Claude is
working". The directory therefore also carries what it can prove — a heartbeat
only a live `review wait` bumps, the delivery cursor, and the owning session's pid —
and `/api/state` ships those beside the claim, so the banner can say when the
claim has outlived them. When delivery wakes a non-working page, `review wait`
marks the status it writes "handoff", which dates it: Claude's first act on
waking is its own `review state`, so the mark surviving is a dropped pickup
rather than a long turn, and the banner gives it a much shorter rope. A
delivery that lands while Claude is already working leaves that claim
untouched; there is no pickup gap to date.

The `hook` command closes the same gap from the agent's side. Registered on
Stop, UserPromptSubmit and SessionEnd, it refuses to let a turn end with one of
this session's pages unwatched, surfaces undelivered comments at the next
prompt, and idles the pages and stops their servers when the session exits. It
finds them through ~/.local/state/colloquy/sessions/<session id>.json, which
`server run` and `review wait` write the host session identity supplied by the launcher —
absent that (interact.py run outside an agent host), nothing is claimed and the
hooks stand down. Undelivered events are the one thing `review state <page> idle`
can't close over: idling is how a review ends, and a review can't end on comments
nobody read.

`page init` vendors the runtime, theme, registry, widgets, and vendor assets into the
page directory, overlaying by precedence: colloquy's shipped defaults, then the
user layer (~/.config/colloquy/), then the project layer
(./.colloquy/). Theme stylesheets concatenate in that order, so a layer
can override one token or rule without copying the defaults. Registry entries
merge by top-level name, with a later layer replacing one complete entry rather
than deep-merging its schema; runtime, widget, and vendor files replace by path.
The page directory itself lives wherever the caller says —
conventionally ~/.local/state/colloquy/pages/<slug>/ — and is self-contained,
so an approved version can't change under its reviewer; re-running `page init`
is the explicit re-vendor, noted in the next version's changelog.

The registry is shared by the JS runtime, the POST and re-vendor action gates,
this file's `version check` and thread-markup validation, the passage reader
`review comment` anchors through, and the `page catalog` the agent reads. Each
entry is JSON Schema over the instance built from the element's attributes
(values as strings, flag attributes as True). What JSON Schema has no
vocabulary for rides in the custom keywords below:
    x-parent    the tag this element must be a direct child of
    x-content   the content model: "prose" (flow content, widgets welcome),
                "items" (element children only, no loose text), "data" (a text
                body in the notation the description names), "none" (empty).
                Children that declare this tag as x-parent are admissible under
                any model — that is what x-parent means.
    x-says      attributes whose values are words the reader sees, mapped to the
                edge they render at ("before" = first child, "after" = last).
                The runtime renders them as real text there, because a reviewer
                can only quote what a text node holds — the theme's matching
                `content: attr()` is the same words for a page with no script.
    x-refers    attributes whose values name another element on the page. The
                reader follows one, so `version check` holds each to an id the
                version actually carries; a reply's fragment is exempt, having no
                page to check against.
    x-language  the attribute whose value names a code language. The layer colors
                what $languages.names holds, so a widget taking one declares which
                attribute carries it and `version check` validates every such
                attribute against that list — the same list a plain <pre><code
                class="language-*"> is held to.
    x-upgrade   true when the runtime imports /widgets/<tag>.js for it
    x-verbatim  true when an upgraded element's body reaches the reader as its own
                words. Otherwise a module may render anything in place of them, so
                `review comment` treats the element as opaque and won't quote
                through it.
    x-state     the widget's action verbs: each verb's detail schema, its fold
                unit, and the record form its state takes in markup. Every
                applyAction is absolute, so the reviewer's standing state is a
                fold — the last surviving action per unit — and one declaration
                drives the POST and re-vendor contract gates, check's state gate,
                the record-lag report, the runtime's pending mark, and the diff's
                state half (see $state in the registry).
    x-example   one authored example, printed by `page catalog`

Event kinds: comment (optional anchor {section, quote, and the neighbouring
text as prefix/suffix where there is any, which is what tells two identical
passages apart), reply (parent=id),
resolve (parent=id), done (user sign-off; the banner offers it only on a page
declaring <meta name="cq-review" content="sign-off">), action (user; a widget reporting the
user editing the document through it — widget=element id, action=verb, detail
per widget, version the edit was made against), note (agent; per-version
changelog, carrying `restated`: the element ids whose decisions the publishing
version took back). The server stamps every browser-posted event author=user;
Agent-side `review comment`, `review reply`, and `version publish` stamp the wire
role author=claude, and comments/replies also carry the originating host's display
name. An agent comment or reply may carry widget markup — both validate it against
the vendored registry, the discussion-side analog of `version check`; user comments
stay plain text.

Either side can open a thread, and `author` is the whole difference between them. The
reviewer selects a passage and the browser writes the anchor from the
selection; `review comment` writes the same anchor from a quote, reading the
version the way the anchor pass reads the DOM (see "passages" below).
Everything downstream already turns on `author`: `review wait` delivers user
events and the banner counts them, so Claude's own comment neither wakes its
watcher nor reads as unanswered. What Claude cannot do is `resolve` — a note's
purpose is discharged by being read, and only the reader knows that happened;
closing one from this side would file it away unread.

Commands:
    page       init catalog media
    customize  theme widget
    version    check publish export
    server     run stop
    review     state wait comment reply events transcript

`version check` is a deterministic pre-handover lint (no browser, near-free;
`version publish` re-runs it on every version): the HTML parses with balanced
tags; the page carries exactly one external script
(<script type="module" src="/colloquy.js">) and one stylesheet link
(/theme.css); every cq-* element validates against the vendored registry
(schema, nesting, no self-closing form); every cq-* meta is a known page
declaration with an allowed value; each cq-suggestion is well formed (at most
one of each slot, at least one of them, no nesting, `resolves` naming a real
comment); ids are unique and every id from the previous version survives
unless the log settled the suggestion holding it; no fixed-pixel-width element
is wider than the readable column.

`version check --render` adds the browser half, run once before a page's URL is first
handed over: the version loads in the machine's installed Chrome (Playwright
`channel="chrome"` — the caller supplies playwright, which `bin/colloquy` does
on seeing `--render`) and the render invariants the static lint cannot reach run
against it — no console or page errors, no fail-soft error box, every visible
widget occupies real space, no sideways scroll, in both color schemes.
The invariants live in render_version, which tests/test_render.py drives over
the shipped examples, so the gate and the suite cannot drift apart.

Passages: an anchor is resolved in the browser and written down here, so
`review comment` reads a version the way the anchor pass reads the DOM — text
in document order, minus the runtime's own words, plus the words a widget says
through an x-says attribute, one space wherever the enclosing text block
changes, whitespace collapsed. What the file cannot know is what a widget's
module will write, so the reading stops where the registry stops telling it:
an upgraded element is opaque unless x-verbatim says its body reaches the
reader as its own words, and an opaque element and each of its children is
fenced. A quote never spans a fence, so "the page has words here that the file
doesn't" is a refusal when the comment is written rather than an anchor that
detaches later in the reviewer's browser. Element-anchor an opaque widget
instead (`--section`), which is the anchor a click on a diagram makes.
"""

import base64
import contextlib
import ctypes
import errno
import hashlib
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
import zlib
from datetime import datetime
from html.parser import HTMLParser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import NamedTuple
from urllib.parse import parse_qs, urlsplit

import click
import tinycss2
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

HEARTBEAT_FRESH_SECS = 8
# A session-managed server gives a replacement session one short poll window to
# claim the page before it closes. The claim itself is the ownership record:
# manual servers have none and therefore remain up until `server stop`.
ORPHAN_GRACE_SECS = 1
# The browser's event kinds, and per kind the fields something downstream reads.
# POST /api/event is the one door they come through, so this is where the shape is
# checked; every reader indexes the fields rather than asking whether they arrived.
BROWSER_EVENT_FIELDS = {
    "comment": {"version": int, "text": str},
    "reply": {"parent": str, "version": int, "text": str},
    "resolve": {"parent": str},
    "done": {"version": int, "text": str},
    "action": {"widget": str, "action": str, "detail": dict, "version": int},
}
# Every field the current browser and CLI may write, beyond append_event's
# id/ts/author/kind and read_events' seq. A registry may grow this vocabulary,
# but it cannot omit a word the producers beside it already speak.
EVENT_VOCABULARY = {
    "comment": {"version", "text", "anchor", "suggestion", "agent"},
    "reply": {"parent", "version", "text", "agent"},
    "resolve": {"parent"},
    "done": {"version", "text"},
    "action": {"widget", "action", "detail", "version"},
    "note": {"version", "text", "restated"},
}
EVENT_BASE_FIELDS = {"id", "ts", "author", "kind", "seq"}
HTML_NAME = r"[a-z][a-z0-9-]*"
WIDGET_NAME = r"cq-[a-z0-9]+(?:-[a-z0-9]+)*"
STATE_SCHEMA = {
    "type": "object",
    "minProperties": 1,
    "propertyNames": {"pattern": f"^{HTML_NAME}$"},
    "additionalProperties": {
        "type": "object",
        "properties": {
            "detail": {"type": "object"},
            "unit": {"type": "string", "minLength": 1},
            "record": {
                "oneOf": [
                    {
                        "type": "object",
                        "properties": {
                            "kind": {"const": "attribute"},
                            "attr": {"type": "string", "pattern": f"^{HTML_NAME}$"},
                            "value": {"type": "string", "minLength": 1},
                        },
                        "required": ["kind", "attr", "value"],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "kind": {"const": "position"},
                            "within": {"type": "string", "pattern": f"^{WIDGET_NAME}$"},
                            "value": {"type": "string", "minLength": 1},
                        },
                        "required": ["kind", "within", "value"],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "kind": {"const": "body"},
                            "value": {"type": "string", "minLength": 1},
                        },
                        "required": ["kind", "value"],
                        "additionalProperties": False,
                    },
                ]
            },
        },
        "required": ["detail"],
        "additionalProperties": False,
    },
}
EXTENSION_SCHEMA = {
    "type": "object",
    "properties": {
        "x-content": {"enum": ["prose", "items", "data", "none"]},
        "x-example": {"type": "string"},
        "x-exhibit": {"type": "boolean"},
        "x-language": {"type": "string", "pattern": f"^{HTML_NAME}$"},
        "x-parent": {"type": "string", "pattern": f"^{WIDGET_NAME}$"},
        "x-refers": {
            "type": "array",
            "items": {"type": "string", "pattern": f"^{HTML_NAME}$"},
        },
        "x-retired-when": {"type": "string", "pattern": f"^{HTML_NAME}$"},
        "x-says": {
            "type": "object",
            "propertyNames": {"pattern": f"^{HTML_NAME}$"},
            "additionalProperties": {"enum": ["before", "after"]},
        },
        "x-state": STATE_SCHEMA,
        "x-upgrade": {"type": "boolean"},
        "x-verbatim": {"type": "boolean"},
        "x-visual": {"type": "boolean"},
    },
    "required": ["x-content", "x-upgrade"],
    "dependentRequired": {"x-retired-when": ["x-parent"]},
    "additionalProperties": False,
}

ASSETS = Path(__file__).resolve().parent.parent / "assets"
VENDORED_FILES = ("colloquy.js", "theme.css", "registry.json")
VENDORED_DIRS = ("widgets", "vendor")
# Images the page shows, named by the hash of their bytes (`page media`). Not vendored
# — they are the page's content, not the layer's — but served like it, and the
# naming is what keeps the directory's promise: same name, same bytes, so a
# version the reviewer approved cannot show them something else later.
MEDIA_DIR = "media"
MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}
NO_KEY = "open the link colloquy printed; it carries this page's key"
PAGE_STATE_FILES = (
    "comments.jsonl",
    "status.json",
    "heartbeat.json",
    "cursor.json",
    "server.json",
    "access.json",
    "session.json",
)
PAGE_OWNED_FILES = (*VENDORED_FILES, *PAGE_STATE_FILES)
PAGE_OWNED_DIRS = ("versions", *VENDORED_DIRS, MEDIA_DIR)
# What the server exposes from a page directory: exactly what init vendors, plus
# the media and the versions — built from the vendoring constants, so growing
# them grows this. The dir patterns are keyed by the directories themselves:
# vendoring a new dir without saying what it may serve fails here, at import.
_DIR_FILES = {
    "widgets": r"[a-z0-9-]+\.js",
    "vendor": r"[A-Za-z0-9._-]+",
    MEDIA_DIR: r"[a-f0-9]{16}(?:" + "|".join(re.escape(e) for e in MEDIA_TYPES) + ")",
}
SERVED_PATH = re.compile(
    "/(?:"
    + "|".join(
        [re.escape(f) for f in VENDORED_FILES]
        + [f"{d}/{_DIR_FILES[d]}" for d in (*VENDORED_DIRS, MEDIA_DIR)]
        + [r"versions/v[1-9][0-9]*\.html"]
    )
    + ")"
)
CONTENT_TYPES = {
    ".js": "application/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".html": "text/html",
    **MEDIA_TYPES,
}
BINARY_TYPES = frozenset(MEDIA_TYPES.values()) - {"image/svg+xml"}

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
    except FileNotFoundError:
        return None


def replace_files(files: list) -> None:
    """Stage every (path, bytes, follow_symlink) write before replacing targets."""
    staged = []
    targets = [
        path.resolve() if follow_symlink and path.is_symlink() else path
        for path, _, follow_symlink in files
    ]
    if any(
        paths_same(left, right)
        for index, left in enumerate(targets)
        for right in targets[index + 1 :]
    ):
        sys.exit("two customization files resolve to the same target")
    try:
        for (path, data, follow_symlink), target in zip(files, targets):
            for _ in range(100):
                tmp = target.with_name(f".{secrets.token_hex(8)}.tmp")
                try:
                    fd = os.open(
                        tmp,
                        os.O_WRONLY
                        | os.O_CREAT
                        | os.O_EXCL
                        | getattr(os, "O_BINARY", 0),
                        0o666,
                    )
                    break
                except FileExistsError:
                    continue
            else:  # pragma: no cover - 64 random bits collided 100 times
                raise FileExistsError(f"could not reserve a temp file beside {target}")
            staged.append((tmp, target))
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
            if target.exists() and (follow_symlink or not path.is_symlink()):
                tmp.chmod(target.stat().st_mode & 0o777)
        for tmp, target in staged:
            os.replace(tmp, target)
    finally:
        for tmp, _ in staged:
            tmp.unlink(missing_ok=True)


def json_bytes(obj, *, indent=None) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=indent) + "\n").encode()


def write_json(path: Path, obj) -> None:
    # Atomic: the serve process reads these files (cursor.json every poll) while
    # wait/status write them; a torn read of cursor.json would replay declined
    # actions in the browser, stickily. Each writer stages through an exclusively
    # created name so simultaneous writers cannot replace one another's temp file.
    replace_files([(path, json_bytes(obj), False)])


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


def build_threads(events: list) -> dict:
    """Fold the chronological log into comment threads by root id."""
    threads = {}
    thread_for = {}
    for e in events:
        if e["kind"] == "comment":
            thread = {"root": e, "msgs": [e], "resolved": False}
            threads[e["id"]] = thread
            thread_for[e["id"]] = thread
            continue
        if e["kind"] == "action" and e["action"] == "accept":
            answered = threads.get(e["detail"].get("resolves"))
            if answered:
                answered["resolved"] = True
            continue
        if e["kind"] == "reply":
            thread = thread_for[e["parent"]]
            thread["msgs"].append(e)
            thread_for[e["id"]] = thread
        elif e["kind"] == "resolve":
            thread = thread_for[e["parent"]]
            thread["resolved"] = True
    return threads


def anchored_ids(events: list) -> set:
    """Element ids an unresolved thread still points at."""
    return {
        (t["root"].get("anchor") or {}).get("section")
        for t in build_threads(events).values()
        if not t["resolved"]
    } - {None}


VERSION_FILE = re.compile(r"v([1-9][0-9]*)\.html")


def version_num(name: str) -> int:
    """A version's number is its identity; its file name only renders it. So
    everything that orders or addresses versions parses the number out rather
    than working on the name, and the names carry no zero padding — padding is
    what you add to make a string comparison come out right, and nothing here
    compares names. `v10.html` precedes `v9.html` in every ordering a string
    has, and follows it in the only one that means anything."""
    return int(VERSION_FILE.fullmatch(name).group(1))


def version_name(version: int) -> str:
    return f"v{version}.html"


def version_path(page_dir: Path, version: int) -> Path:
    return page_dir / "versions" / version_name(version)


def list_versions(page_dir: Path) -> list:
    versions_dir = page_dir / "versions"
    if not versions_dir.exists():
        return []
    return sorted(
        version_num(p.name)
        for p in versions_dir.iterdir()
        if p.is_file() and VERSION_FILE.fullmatch(p.name)
    )


def published_versions(page_dir: Path, events: list) -> list:
    """Versions the server exposes: those whose `note` event has landed. `version
    publish` runs `version check` first, so a half-written or failing version is
    never live to an open browser — the file existing is not enough."""
    noted = {e["version"] for e in events if e["kind"] == "note"}
    return [version for version in list_versions(page_dir) if version in noted]


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def running_server(page_dir: Path):
    info = read_json(page_dir / "server.json")
    if info and pid_alive(info["pid"]):
        return info
    return None


def stop_when_session_ends(httpd: ThreadingHTTPServer, page_dir: Path) -> None:
    """Stop a session-managed server once the page's current claimant is gone.

    Read the claim afresh on every pass: another live session may take over the
    already-running server, and then its pid — not the process that originally
    launched the server — is the one whose lifetime matters. This watcher is
    only started when `server run` has a claim, so a manually launched server
    remains an explicit-stop process.
    """
    orphaned_at = None
    while True:
        session = read_json(page_dir / "session.json")
        if session and pid_alive(session["pid"]):
            orphaned_at = None
        elif orphaned_at is None:
            orphaned_at = time.monotonic()
        elif time.monotonic() - orphaned_at >= ORPHAN_GRACE_SECS:
            httpd.shutdown()
            return
        time.sleep(0.1)


def page_access(page_dir: Path) -> dict:
    """How a page is reached: the address to serve it on, and the key its URL carries.

    The address is read from SSH_CONNECTION, whose third field is this machine as
    the client just reached it — a route the session carrying the request has
    already demonstrated, rather than a guess about what resolves from where. No
    SSH_CONNECTION is the same answer for a reader on this machine: loopback. That
    is two exhaustive cases, not a list of hosts to recognize, which is what keeps
    the next kind of remote session from being one this can silently fail to know.

    Serving anywhere but loopback puts an unauthenticated writer on whatever
    network reached us, and `POST /api/event` appends to a log that outranks the
    document and replays onto every version after. So the address earns a key, and
    the key is minted here rather than at the reader's cost: it rides in the URL
    Claude hands over, and `authorized` puts it in a cookie on arrival.

    Both are minted once and kept. `revive_server` restarts a dead server by
    re-running `server run`, and a fresh address or key there would leave the
    reviewer's open page polling a URL that no longer answers."""
    access = read_json(page_dir / "access.json")
    if access:
        return access
    ssh = os.environ.get("SSH_CONNECTION", "").split()
    access = {
        "host": ssh[2] if len(ssh) == 4 else "127.0.0.1",
        "token": secrets.token_urlsafe(16),
    }
    write_json(page_dir / "access.json", access)
    return access


def access_cookie(page_dir: Path) -> str:
    """The cookie a page's key lives in. Cookies are scoped by host and ignore the
    port, so two pages served from one machine share a jar and a shared name would
    have the second overwrite the first."""
    return "cq_" + hashlib.sha256(str(page_dir.resolve()).encode()).hexdigest()[:8]


def page_url(access: dict, port: int) -> str:
    """The handover URL. A bare IPv6 address is bracketed, since the authority
    already separates its port with a colon."""
    host = f"[{access['host']}]" if ":" in access["host"] else access["host"]
    return f"http://{host}:{port}/?t={access['token']}"


def config_home() -> Path:
    """$XDG_CONFIG_HOME/colloquy (~/.config/colloquy/) — the user's overlay layer."""
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "colloquy"


def state_home() -> Path:
    """$XDG_STATE_HOME/colloquy (~/.local/state/colloquy/) — pages/ holds page
    directories by convention, sessions/ the live-session registry. State, not
    config: page directories carry pids, ports, and absolute paths, so they are
    bound to this machine."""
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "colloquy"


def claim_page(page_dir: Path) -> bool:
    """Record that this agent session is the one working on the page, in
    both directions: the page names its session (so the server can see when that
    session is gone), the session lists its pages (so the hooks can find them
    wherever they live). The host identity reaches this process through the
    environment, so this needs no cooperation from the agent.

    `server run` and `review wait` claim; nothing else does. The claim tracks
    the watch obligation the hooks enforce: `server run` puts the page in front
    of a reviewer and incurs it, while `review wait` takes it up. Authoring
    commands neither incur the obligation nor discharge it, so a directory a
    session only wrote to, like a throwaway page for testing the widget layer,
    owes nobody a watcher. Return whether this invocation made a claim, so a
    bare-shell server never inherits a stale claim's lifetime."""
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("COLLOQUY_SESSION_ID")
    pid = os.environ.get("CLAUDE_PID") or os.environ.get("COLLOQUY_SESSION_PID")
    if not sid or not pid:
        return False
    agent = "Claude" if os.environ.get("CLAUDE_CODE_SESSION_ID") else os.environ["COLLOQUY_AGENT"]
    write_json(
        page_dir / "session.json",
        {"id": sid, "pid": int(pid), "agent": agent, "ts": now_iso()},
    )
    sessions = state_home() / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    # Sessions that died without a SessionEnd hook leave their file behind; drop
    # them here when the next live session makes a claim rather than on a timer.
    for stale in sessions.glob("*.json"):
        entry = read_json(stale)
        if entry and not pid_alive(entry["pid"]):
            stale.unlink(missing_ok=True)
    entry = read_json(sessions / f"{sid}.json") or {"pages": []}
    pages = sorted({*entry["pages"], str(page_dir)})
    write_json(sessions / f"{sid}.json", {"pid": int(pid), "pages": pages, "ts": now_iso()})
    return True


def session_pages(session_id: str) -> list:
    """The page directories a session has worked on, those still on disk."""
    entry = read_json(state_home() / "sessions" / f"{session_id}.json") or {"pages": []}
    return [d for d in (Path(p) for p in entry["pages"]) if d.is_dir()]


def owned_pages(session_id: str) -> list:
    """The pages a session is answerable for: those it worked on most recently.
    A page another session has since picked up belongs to that one — its watcher,
    its server, its turn to be held to the loop."""
    return [
        d for d in session_pages(session_id)
        if (read_json(d / "session.json") or {"id": None})["id"] == session_id
    ]


def undelivered(events: list, cursor: int) -> list:
    """The reviewer's events past the handoff cursor: posted, and not yet in
    Claude's hands. The one predicate for that — the banner's pending count and
    `review wait`'s delivery must agree on which events those are."""
    return [e for e in events if e["seq"] > cursor and e["author"] == "user"]


def full_state(page_dir: Path, events: list, versions: list) -> dict:
    # A file that isn't there stands in as its whole record, so every read below
    # indexes rather than asking twice whether the field arrived.
    status = read_json(page_dir / "status.json") or {"state": "idle", "detail": "", "ts": None}
    heartbeat = read_json(page_dir / "heartbeat.json") or {"t": 0}
    session = read_json(page_dir / "session.json")
    # What `review wait` has delivered to Claude: an action past this seq can't have
    # been seen (so not declined), which is what lets the runtime carry it
    # forward onto versions written without it.
    cursor = (read_json(page_dir / "cursor.json") or {"seq": 0})["seq"]
    return {
        "versions": versions,
        "status": status,
        "listening": time.time() - heartbeat["t"] < HEARTBEAT_FRESH_SECS,
        "cursor": cursor,
        "pending": len(undelivered(events, cursor)),
        "agent": session.get("agent", "Claude") if session else "Claude",
        # None when nothing claimed the page — interact.py run outside an agent host.
        "session_alive": pid_alive(session["pid"]) if session else None,
        "events": events,
    }


class Handler(BaseHTTPRequestHandler):
    page_dir = None
    token = None
    cookie = None
    # Set by `authorized` when the key arrived in the query, cleared by the one
    # writer that spends it.
    set_cookie = False
    # The render gate previews a version before its `note` publishes it —
    # refusing the note is the gate's whole job. Set to that version's number,
    # the handler exposes on-disk versions up to it, previewed one included as
    # latest, so the runtime neither 404s the preview nor follows the published
    # latest away from it mid-check. None — every server a reviewer reaches —
    # exposes noted versions only.
    preview_upto = None

    def versions_live(self, events):
        if self.preview_upto is None:
            return published_versions(self.page_dir, events)
        return [version for version in list_versions(self.page_dir) if version <= self.preview_upto]

    def log_message(self, *args):
        pass

    def authorized(self) -> bool:
        """The page's key, from the handover URL or from the cookie an earlier
        request set out of it. One arrival is enough: the runtime's own fetches are
        relative and carry no query, and a reader who reloads or bookmarks the bare
        address is the same reader. So nothing has to thread the key through the
        page, and `colloquy.js` never learns there is one."""
        if secrets.compare_digest(parse_qs(urlsplit(self.path).query).get("t", [""])[0], self.token):
            self.set_cookie = True
            return True
        jar = SimpleCookie(self.headers.get("Cookie", ""))
        return self.cookie in jar and secrets.compare_digest(jar[self.cookie].value, self.token)

    def end_headers(self):
        # Every response ends here — answered, redirected, or refused — so the
        # cookie has one writer rather than one per path that sends a header.
        if self.set_cookie:
            self.send_header(
                "Set-Cookie",
                f"{self.cookie}={self.token}; Path=/; HttpOnly; SameSite=Strict",
            )
            self.set_cookie = False
        super().end_headers()

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
        if not self.authorized():
            self._json({"error": NO_KEY}, 403)
            return
        path = urlsplit(self.path).path
        if path == "/":
            versions = self.versions_live(read_events(self.page_dir))
            if not versions:
                self._json({"error": "no published versions yet"}, 404)
                return
            self.send_response(302)
            self.send_header("Location", f"/versions/{version_name(versions[-1])}")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/api/state":
            # versions through the handler's own view, so a preview server's
            # state agrees with what it serves (identical when not previewing).
            events = read_events(self.page_dir)
            self._json(full_state(self.page_dir, events, self.versions_live(events)))
            return
        # Browsers ask for this unprompted. Answering "no content" rather than
        # letting it fall through to 404 keeps the console clean, which is what
        # makes an empty console worth asserting on (tests/test_render.py).
        if path == "/favicon.ico":
            self._send(204, "image/x-icon", b"")
            return
        if SERVED_PATH.fullmatch(path):
            if path.startswith("/versions/"):
                version = version_num(Path(path).name)
                if version not in self.versions_live(read_events(self.page_dir)):
                    self._json(
                        {"error": "not published yet; run `colloquy version publish` first"},
                        404,
                    )
                    return
            file = self.page_dir / path.lstrip("/")
            # is_file, not exists: the vendor pattern admits "." and "..", which
            # resolve to directories.
            if file.is_file():
                ctype = CONTENT_TYPES.get(Path(path).suffix, "application/octet-stream")
                # charset describes an encoding, so it rides on the types that
                # have one. On a PNG it is noise.
                if ctype not in BINARY_TYPES:
                    ctype += "; charset=utf-8"
                self._send(200, ctype, file.read_bytes())
                return
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        if not self.authorized():
            self._json({"error": NO_KEY}, 403)
            return
        if urlsplit(self.path).path != "/api/event":
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
        kind = event.get("kind")
        if not isinstance(kind, str) or kind not in BROWSER_EVENT_FIELDS:
            self._json({"error": f"kind must be one of {sorted(BROWSER_EVENT_FIELDS)}"}, 400)
            return
        # Identity, authorship, and time belong to the server. Drop client copies
        # before checking the kind's declared payload, so none can be forged into
        # the append-only record.
        for field in ("id", "author", "agent", "ts"):
            event.pop(field, None)
        unexpected = set(event) - {"kind"} - EVENT_VOCABULARY[kind]
        if unexpected:
            self._json(
                {"error": f"{event['kind']} events have unexpected fields {sorted(unexpected)}"},
                400,
            )
            return
        wrong = [
            f"`{name}` ({typ.__name__})"
            for name, typ in BROWSER_EVENT_FIELDS[kind].items()
            if type(event.get(name)) is not typ or event[name] == ""
        ]
        if wrong:
            self._json({"error": f"{kind} events need {', '.join(wrong)}"}, 400)
            return
        if kind == "comment" and "anchor" in event:
            anchor = event["anchor"]
            fields = {"section", "quote", "prefix", "suffix"}
            invalid = (
                not isinstance(anchor, dict)
                or set(anchor) - fields
                or any(
                    name in anchor
                    and not (
                        isinstance(anchor[name], str)
                        or (name == "section" and anchor[name] is None)
                    )
                    for name in fields
                )
                or not (anchor.get("section") or anchor.get("quote"))
            )
            if invalid:
                self._json(
                    {
                        "error": "comment anchor must contain a string section or quote, "
                        "with optional string prefix/suffix"
                    },
                    400,
                )
                return
        if (
            kind == "comment"
            and "suggestion" in event
            and type(event["suggestion"]) is not bool
        ):
            self._json({"error": "comment suggestion must be boolean"}, 400)
            return
        events = read_events(self.page_dir)
        if "version" in event:
            live_versions = self.versions_live(events)
            if event["version"] not in live_versions:
                self._json(
                    {"error": f"{kind} version must be one of {live_versions}"},
                    400,
                )
                return
        if kind == "action":
            registry = load_registry(self.page_dir)
            if registry is None:
                self._json({"error": "the page has no registry.json"}, 400)
                return
            if error := action_contract_error(self.page_dir, event, events, registry):
                self._json({"error": error}, 400)
                return
        # A parent names a message in a thread, the same rule `review reply` holds Claude
        # to. Enforced here so a walk up the log always terminates at a comment.
        if "parent" in event and event["parent"] not in {
            e["id"] for e in events if e["kind"] in {"comment", "reply"}
        }:
            self._json({"error": f"unknown parent {event['parent']!r}"}, 400)
            return
        event["author"] = "user"
        self._json({"ok": True, "event": append_event(self.page_dir, event)})


def handler_for(page_dir: Path, token: str, preview_upto=None, protocol_version="HTTP/1.0"):
    """A request handler bound to one page, publication view, and key. The key has no
    default: every server over a page directory is reachable by whatever reached the
    machine, so there is no construction that should quietly go without one."""
    return type(
        "PageHandler",
        (Handler,),
        {
            "page_dir": page_dir,
            "token": token,
            "cookie": access_cookie(page_dir),
            "preview_upto": preview_upto,
            "protocol_version": protocol_version,
        },
    )


def layer_dirs() -> list:
    """Widget-layer sources, lowest precedence first: colloquy's shipped defaults,
    the user layer, the project layer (resolved against the working directory).
    Each mirrors the assets layout: theme.css/registry.json/colloquy.js at the
    top, modules in widgets/, third-party files in vendor/. Theme files form one
    cascade, registry files are additive by top-level entry, and every other
    file replaces by path."""
    return [ASSETS, config_home(), Path.cwd() / ".colloquy"]


def checked_layers(sources: list) -> list:
    """Existing, structurally complete layer roots.

    An overlay path of the wrong kind is authored input, not an absent
    customization. Refuse it here once so every merger can assume the layer
    shape the public guide describes.
    """
    layers = []
    for layer in sources:
        if not (layer.exists() or layer.is_symlink()):
            continue
        if not layer.is_dir():
            sys.exit(f"{layer} must be a directory")
        for name in VENDORED_FILES:
            path = layer / name
            if (path.exists() or path.is_symlink()) and not path.is_file():
                sys.exit(f"{path} must be a file")
        for sub in VENDORED_DIRS:
            directory = layer / sub
            if not (directory.exists() or directory.is_symlink()):
                continue
            if not directory.is_dir():
                sys.exit(f"{directory} must be a directory")
            for path in directory.iterdir():
                if not path.is_file():
                    sys.exit(f"{path} must be a file")
        layers.append(layer)
    return layers


def layer_source_paths(layers: list) -> list:
    """Every path a layer reads, including the targets of nested symlinks."""
    paths = []
    for layer in layers:
        paths.append(layer.resolve())
        paths.extend(
            path.resolve()
            for name in VENDORED_FILES
            if (
                (path := layer / name).exists()
                or path.is_symlink()
            )
        )
        for sub in VENDORED_DIRS:
            directory = layer / sub
            if not (directory.exists() or directory.is_symlink()):
                continue
            paths.append(directory.resolve())
            if directory.is_dir():
                paths.extend(path.resolve() for path in directory.iterdir())
    return paths


def _path_location(path: Path) -> tuple:
    """Deepest existing ancestor and the unresolved path components below it."""
    ancestor = path.resolve()
    tail = []
    while True:
        try:
            ancestor.stat()
        except (FileNotFoundError, NotADirectoryError):
            tail.append(ancestor.name)
            ancestor = ancestor.parent
            continue
        return ancestor, tuple(reversed(tail))


def _filesystem_case_sensitive(path: Path) -> bool:
    """Whether new names on path's filesystem distinguish letter case."""
    if sys.platform != "darwin":
        return os.path.normcase("A") != os.path.normcase("a")

    # Darwin exposes this per volume rather than through normcase: APFS can be
    # mounted either way, and normcase leaves names unchanged in both cases.
    class AttrList(ctypes.Structure):
        _fields_ = [
            ("bitmapcount", ctypes.c_uint16),
            ("reserved", ctypes.c_uint16),
            ("commonattr", ctypes.c_uint32),
            ("volattr", ctypes.c_uint32),
            ("dirattr", ctypes.c_uint32),
            ("fileattr", ctypes.c_uint32),
            ("forkattr", ctypes.c_uint32),
        ]

    class VolumeCapabilities(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_uint32),
            ("capabilities", ctypes.c_uint32 * 4),
            ("valid", ctypes.c_uint32 * 4),
        ]

    attr_vol_info = 0x80000000
    attr_vol_capabilities = 0x00020000
    case_sensitive = 0x00000100
    attributes = AttrList(
        5, 0, 0, attr_vol_info | attr_vol_capabilities, 0, 0, 0
    )
    result = VolumeCapabilities()
    getattrlist = ctypes.CDLL(None, use_errno=True).getattrlist
    getattrlist.argtypes = [
        ctypes.c_char_p,
        ctypes.POINTER(AttrList),
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_ulong,
    ]
    getattrlist.restype = ctypes.c_int
    if getattrlist(
        os.fsencode(path),
        ctypes.byref(attributes),
        ctypes.byref(result),
        ctypes.sizeof(result),
        0,
    ):
        return True
    if not result.valid[0] & case_sensitive:
        return True
    return bool(result.capabilities[0] & case_sensitive)


def _same_existing_path(left: Path, right: Path) -> bool:
    try:
        return left.samefile(right)
    except (FileNotFoundError, NotADirectoryError):
        return False


def path_is_within(path: Path, root: Path) -> bool:
    """Filesystem-aware containment, including not-yet-created descendants."""
    path_ancestor, path_tail = _path_location(path)
    root_ancestor, root_tail = _path_location(root)
    if not root_tail:
        return any(
            _same_existing_path(candidate, root_ancestor)
            for candidate in (path_ancestor, *path_ancestor.parents)
        )
    if not _same_existing_path(path_ancestor, root_ancestor):
        return False
    if not _filesystem_case_sensitive(root_ancestor):
        path_tail = tuple(part.casefold() for part in path_tail)
        root_tail = tuple(part.casefold() for part in root_tail)
    return path_tail[: len(root_tail)] == root_tail


def paths_same(left: Path, right: Path) -> bool:
    return path_is_within(left, right) and path_is_within(right, left)


def paths_overlap(left: Path, right: Path) -> bool:
    return path_is_within(left, right) or path_is_within(right, left)


def overlapping_layer_sources(layers: list):
    """The first resolved path shared by two precedence scopes."""
    sources = [(layer, layer_source_paths([layer])) for layer in layers]
    return next(
        (
            (left_layer, left, right_layer, right)
            for index, (left_layer, left_paths) in enumerate(sources)
            for right_layer, right_paths in sources[index + 1 :]
            for left in left_paths
            for right in right_paths
            if paths_overlap(left, right)
        ),
        None,
    )


def layered_dir_files(layers: list, sub: str) -> dict:
    """The winning source for every file in one overlaid directory."""
    sources = {}
    for layer in layers:
        source_dir = layer / sub
        if not source_dir.is_dir():
            continue
        for source in sorted(source_dir.iterdir()):
            if source.is_file():
                sources[source.name] = source
    return sources


def layered_theme(layers: list) -> str:
    """One stylesheet whose source order is the layer precedence."""
    sources = [layer / "theme.css" for layer in layers if (layer / "theme.css").is_file()]
    if not sources:
        sys.exit("the incoming layer has no theme.css")
    parts = []
    for source in sources:
        try:
            css = source.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            sys.exit(f"{source} must be UTF-8")
        if errors := css_syntax_errors(css, str(source)):
            sys.exit(errors[0])
        parts.append(css if css.endswith("\n") else css + "\n")
    return "".join(parts)


def cmd_init(page_dir: Path) -> None:
    # Re-vendoring is the one moment a page's vocabulary changes hands, so it is
    # where drift has to be caught: a tag or verb the new layer omits, or a
    # detail schema that no longer accepts an old payload, makes a recorded
    # action foreign on the first reload — the lost-decision bug reintroduced
    # through vocabulary drift instead of version-scoping.
    sources = layer_dirs()
    page_target = page_dir.resolve()
    if source := next(
        (layer for layer in sources if path_is_within(page_target, layer)),
        None,
    ):
        sys.exit(
            f"{page_dir} is inside the widget-layer customization source "
            f"{source}, not a page directory"
        )
    layers = checked_layers(sources)
    if overlap := overlapping_layer_sources(layers):
        left_layer, left, right_layer, right = overlap
        sys.exit(
            f"widget-layer sources {left_layer} and {right_layer} overlap "
            f"at {left} and {right}; layer scopes must be separate"
        )
    destinations = [
        *(page_target / name for name in VENDORED_FILES),
        *(page_target / sub for sub in ("versions", *VENDORED_DIRS)),
    ]
    if overlap := next(
        (
            (source, destination)
            for source in layer_source_paths(layers)
            for destination in destinations
            if paths_overlap(source, destination)
        ),
        None,
    ):
        source, destination = overlap
        sys.exit(
            f"widget-layer source {source} overlaps page destination "
            f"{destination}; source and vendored page paths must be separate"
        )
    incoming = incoming_registry(layers)
    directory_sources = {
        sub: layered_dir_files(layers, sub) for sub in VENDORED_DIRS
    }
    missing_modules = sorted(
        tag
        for tag, entry in incoming.items()
        if tag.startswith("cq-")
        and entry["x-upgrade"]
        and f"{tag}.js" not in directory_sources["widgets"]
    )
    if missing_modules:
        sys.exit(
            "the incoming registry marks widgets as upgraded but their modules "
            "are missing:\n"
            + "\n".join(f"  - widgets/{tag}.js" for tag in missing_modules)
        )
    events = read_events(page_dir)
    gaps = vocabulary_gaps(page_dir, events, incoming)
    if gaps:
        sys.exit(
            "this page's log holds vocabulary the incoming layer no longer speaks:\n"
            + "\n".join(f"  - {g}" for g in gaps)
            + "\nre-vendoring would silently stop these replaying — the reviewer's"
            " recorded decisions among them."
        )

    # Resolve and read the complete incoming layer before the first page write.
    # A bad late source must not leave the registry newer than the theme or its
    # modules.
    top_files = {"theme.css": layered_theme(layers).encode()}
    for name in VENDORED_FILES:
        if name == "registry.json" or name in top_files:
            continue
        source = next(
            (layer / name for layer in reversed(layers) if (layer / name).is_file()),
            None,
        )
        if source is None:
            sys.exit(f"the incoming layer has no {name}")
        top_files[name] = source.read_bytes()
    # The registry makes the theme and modules live, so it commits last.
    top_files["registry.json"] = json_bytes(incoming)
    directory_files = {
        sub: {name: source.read_bytes() for name, source in directory_sources[sub].items()}
        for sub in VENDORED_DIRS
    }

    # Resolve every destination conflict before touching the page. A directory
    # where one vendored file belongs must not leave the top-level layer newer
    # than its modules.
    if (page_dir.exists() or page_dir.is_symlink()) and not page_dir.is_dir():
        sys.exit(f"{page_dir} must be a directory")
    directories = [page_dir / "versions"] + [
        page_dir / sub for sub in VENDORED_DIRS
    ]
    for destination in directories:
        if destination.is_symlink():
            sys.exit(f"{destination} must be a real directory, not a symlink")
        if (
            destination.exists() or destination.is_symlink()
        ) and not destination.is_dir():
            sys.exit(f"{destination} must be a directory")
    file_targets = [
        *(page_dir / name for name in top_files),
        *(
            page_dir / sub / name
            for sub in VENDORED_DIRS
            for name in directory_files[sub]
        ),
    ]
    for target in file_targets:
        if (target.exists() or target.is_symlink()) and not target.is_file():
            sys.exit(f"{target} must be a file")

    (page_dir / "versions").mkdir(parents=True, exist_ok=True)
    for sub in VENDORED_DIRS:
        (page_dir / sub).mkdir(exist_ok=True)

    # Stage the whole layer together. The registry is the declaration that
    # makes every other file live, so it is the final replacement.
    writes = [
        (page_dir / name, data, False)
        for name, data in top_files.items()
        if name != "registry.json"
    ]
    writes.extend(
        (page_dir / sub / name, data, False)
        for sub in VENDORED_DIRS
        for name, data in directory_files[sub].items()
    )
    writes.append((page_dir / "registry.json", top_files["registry.json"], False))
    replace_files(writes)

    for sub in VENDORED_DIRS:
        destination = page_dir / sub
        for stale in destination.iterdir():
            if (
                stale.name not in directory_files[sub]
                and (stale.is_symlink() or stale.is_file())
            ):
                stale.unlink()
    if not (page_dir / "status.json").exists():
        cmd_status(page_dir, "working", "Writing the page")
    print(f"initialized {page_dir}")


CUSTOM_THEME = """\
/* Appended after Colloquy's defaults by `page init`.
 * Override tokens for broad changes and selectors for specific elements. */
:root {
  /* --accent: #7c3aed; */
}
"""


def customization_dir(user: bool) -> Path:
    return config_home() if user else Path.cwd() / ".colloquy"


def custom_theme_content(layer: Path) -> tuple:
    path = layer / "theme.css"
    if path.exists() or path.is_symlink():
        if not path.is_file():
            sys.exit(f"{path} must be a file")
        try:
            return path, path.read_text(encoding="utf-8"), True
        except UnicodeDecodeError:
            sys.exit(f"{path} must be UTF-8")
    return path, CUSTOM_THEME, False


def customization_protected_paths(layer: Path) -> list:
    """Resolved paths owned by every layer other than the selected write scope."""
    paths = []
    for source in layer_dirs():
        if source == layer:
            continue
        paths.append(source.resolve())
        if source.is_dir():
            paths.extend(layer_source_paths([source]))
    return paths


def customization_overlap(targets: list, protected: list):
    return next(
        (
            (target.resolve(), source)
            for target in targets
            for source in protected
            if paths_overlap(target.resolve(), source)
        ),
        None,
    )


def initialized_page_owning(path: Path):
    """The initialized page that owns path, if there is one."""
    resolved = path.resolve()
    for root in (resolved, *resolved.parents):
        # Runtime state is disposable and regenerated; it cannot identify the
        # page whose owned paths this gate protects.
        if (
            (root / "versions").is_dir()
            and all((root / name).is_file() for name in VENDORED_FILES)
            and all((root / name).is_dir() for name in VENDORED_DIRS)
        ):
            if (
                paths_same(resolved, root)
                or any(
                    paths_same(resolved, root / name)
                    for name in PAGE_OWNED_FILES
                )
                or any(
                    path_is_within(resolved, root / name)
                    for name in PAGE_OWNED_DIRS
                )
            ):
                return root
    return None


def customization_page_overlap(paths: list):
    for path in paths:
        resolved = path.resolve()
        if page := initialized_page_owning(resolved):
            return resolved, page
    return None


def validate_customization_dir(layer: Path) -> list:
    if (layer.exists() or layer.is_symlink()) and not layer.is_dir():
        sys.exit(f"{layer} must be a directory")
    if layer.is_dir():
        checked_layers([layer])
    protected = customization_protected_paths(layer)
    selected = layer_source_paths([layer]) if layer.is_dir() else [layer]
    if overlap := customization_page_overlap(selected):
        target, page = overlap
        sys.exit(
            f"customization path {target} is owned by initialized page {page}; "
            "customization sources must stay separate from page-owned paths, "
            "then run `page init` to re-vendor the page"
        )
    if overlap := customization_overlap(selected, protected):
        target, source = overlap
        sys.exit(
            f"customization target {target} overlaps another layer source "
            f"{source}; customization scopes must be separate"
        )
    return protected


def cmd_customize_theme(user: bool) -> Path:
    layer = customization_dir(user)
    protected = validate_customization_dir(layer)
    path, css, exists = custom_theme_content(layer)
    if overlap := customization_overlap([path], protected):
        target, source = overlap
        sys.exit(
            f"customization target {target} overlaps another layer source "
            f"{source}; customization scopes must be separate"
        )
    if exists:
        print(f"using {path}")
        return path
    layer.mkdir(parents=True, exist_ok=True)
    replace_files([(path, css.encode(), True)])
    print(f"created {path}")
    return path


def custom_widget_entry(tag: str, upgrade: bool) -> dict:
    stem = tag.removeprefix("cq-")
    entry = {
        "description": f"A custom <{tag}> block.",
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "pattern": "^[a-z0-9][a-z0-9-]*$",
            }
        },
        "required": ["id"],
        "additionalProperties": False,
        "x-content": "prose",
        "x-upgrade": upgrade,
        "x-example": (
            f'<{tag} id="{stem}-example"><strong>Example</strong> '
            f"Replace this content.</{tag}>"
        ),
    }
    if upgrade:
        entry["x-verbatim"] = True
    return entry


def custom_widget_css(tag: str) -> str:
    return f"""\
/* <{tag}> */
{tag} {{
  display: block;
  margin: var(--sp-3) 0;
  padding: var(--sp-3);
  border: 1px solid var(--rule);
  border-radius: var(--r);
  background: var(--card);
}}
"""


def custom_widget_module(tag: str) -> str:
    return f"""\
import {{ once }} from "/colloquy.js";

customElements.define(
  "{tag}",
  class extends HTMLElement {{
    connectedCallback() {{
      if (!once(this)) return;
    }}
  }},
);
"""


def cmd_customize_widget(tag: str, user: bool, upgrade: bool) -> None:
    if re.fullmatch(WIDGET_NAME, tag) is None:
        sys.exit("widget tag must start with `cq-` and use lowercase kebab-case")

    layer = customization_dir(user)
    protected = validate_customization_dir(layer)
    registry_path = layer / "registry.json"
    registry_layers = layer_dirs()[:2] if user else layer_dirs()
    checked_layers(registry_layers[:-1])
    for source_layer in registry_layers:
        source_path = source_layer / "registry.json"
        source_entries = read_registry_entries(source_path) or {}
        if tag in source_entries:
            sys.exit(f"<{tag}> already exists in {source_path}")

    widgets_dir = layer / "widgets"
    if (
        widgets_dir.exists() or widgets_dir.is_symlink()
    ) and not widgets_dir.is_dir():
        sys.exit(f"{widgets_dir} must be a directory")
    module_path = layer / "widgets" / f"{tag}.js"
    if module_path.exists() or module_path.is_symlink():
        sys.exit(f"{module_path} already exists")

    entries = read_registry_entries(registry_path) or {}
    entries[tag] = custom_widget_entry(tag, upgrade)
    merged = {}
    for source_layer in registry_layers:
        source_entries = (
            entries
            if source_layer.resolve() == layer.resolve()
            else read_registry_entries(source_layer / "registry.json") or {}
        )
        merged.update(source_entries)
    source = f"custom widget <{tag}>"
    validate_registry_examples(validate_registry(merged, source), source)

    theme_path, css, _ = custom_theme_content(layer)
    if css and not css.endswith("\n"):
        css += "\n"
    css += "\n" + custom_widget_css(tag)
    if errors := css_syntax_errors(css, str(theme_path)):
        sys.exit(errors[0])

    layer.mkdir(parents=True, exist_ok=True)
    writes = [(theme_path, css.encode(), True)]
    created = [registry_path, theme_path]
    if upgrade:
        writes.append((module_path, custom_widget_module(tag).encode(), False))
        created.append(module_path)
    # The registry is the declaration that makes the other files live, so it
    # commits last after every target has been staged.
    writes.append((registry_path, json_bytes(entries, indent=2), True))
    if overlap := customization_overlap(
        [path for path, _, _ in writes], protected
    ):
        target, source = overlap
        sys.exit(
            f"customization target {target} overlaps another layer source "
            f"{source}; customization scopes must be separate"
        )
    if upgrade:
        widgets_dir.mkdir(parents=True, exist_ok=True)
    replace_files(writes)
    print("custom widget scaffold:")
    for path in created:
        print(f"  {path}")


def cmd_media(page_dir: Path, files: list) -> list:
    """Copy images into the page's media directory, named by the hash of their
    bytes; returns (source, served path) per file, in the order given.

    Content-addressing is doing two jobs. It keeps the directory's promise —
    a name can only ever mean one set of bytes, so a version the reviewer
    approved shows them the same picture forever, which is the same guarantee
    vendoring gives the layer. And it de-duplicates for free: a version that
    re-shows last version's screenshot re-uses the file rather than a second
    copy of it, which is what makes the review history cheap to keep."""
    out = []
    (page_dir / MEDIA_DIR).mkdir(exist_ok=True)
    for src in files:
        if src.suffix.lower() not in MEDIA_TYPES:
            sys.exit(f"{src}: not an image colloquy serves — {', '.join(sorted(MEDIA_TYPES))}")
        data = src.read_bytes()
        name = hashlib.sha256(data).hexdigest()[:16] + src.suffix.lower()
        (page_dir / MEDIA_DIR / name).write_bytes(data)
        out.append((str(src), f"/{MEDIA_DIR}/{name}"))
    return out


def cmd_serve(page_dir: Path) -> None:
    claimed = claim_page(page_dir)
    existing = running_server(page_dir)
    if existing:
        print(existing["url"], flush=True)
        return
    access = page_access(page_dir)
    base = 41000 + zlib.crc32(str(page_dir.resolve()).encode()) % 4000
    httpd = None
    for port in [*range(base, base + 10), 0]:
        try:
            httpd = ThreadingHTTPServer(
                (access["host"], port),
                handler_for(page_dir, access["token"], protocol_version="HTTP/1.1"),
            )
            break
        except OSError as e:
            if e.errno == errno.EADDRINUSE:
                continue
            # The address outlived the session that derived it — a page created
            # over SSH and served again from elsewhere, or from a box that has
            # since moved. Naming where it was recorded is the whole fix.
            sys.exit(
                f"can't serve {page_dir} on {access['host']}: {e}\n"
                f"that address came from the session that first served this page and is "
                f"kept in {page_dir / 'access.json'}; delete that file to derive the "
                "address again from this one."
            )
    url = page_url(access, httpd.server_address[1])
    write_json(page_dir / "server.json", {"port": httpd.server_address[1], "pid": os.getpid(), "url": url})
    print(url, flush=True)
    if claimed:
        threading.Thread(
            target=stop_when_session_ends,
            args=(httpd, page_dir),
            daemon=True,
        ).start()
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
    been showing "Server offline" since it happened, and `review wait` is the
    only thing positioned to notice — so it restarts the server rather than
    handing the diagnosis to Claude and the discovery to the reviewer.

    Detached, because the restarted server has to outlive both this
    `review wait` and the background task that started it, exactly as the
    original `server run` does. sys.executable is the resolved uv environment,
    so this skips uv entirely."""
    (page_dir / "server.json").unlink(missing_ok=True)
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "server", "run", str(page_dir)],
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
    cursor = (read_json(page_dir / "cursor.json") or {"seq": 0})["seq"]
    server_check_at = 0.0
    revived = False
    try:
        while True:
            write_json(page_dir / "heartbeat.json", {"t": time.time()})
            events = read_events(page_dir)
            new_user = undelivered(events, cursor)
            if new_user:
                for event in new_user:
                    print(json.dumps(event, ensure_ascii=False), flush=True)
                # cursor after print: a kill mid-wait redelivers rather than drops
                write_json(page_dir / "cursor.json", {"seq": events[-1]["seq"]})
                status = read_json(page_dir / "status.json") or {"state": "idle"}
                if status["state"] != "working":
                    # Flip before Claude's next turn: the handoff gap between this
                    # exit and pickup must not show "waiting". handoff=True dates
                    # that claim; Claude's own `review state` clears it. Mid-work delivery
                    # has no pickup gap, so leave the existing claim byte-for-byte
                    # untouched instead of shortening its freshness window.
                    # "update", not "comment": a batch may mix comments and actions.
                    n = len(new_user)
                    cmd_status(
                        page_dir,
                        "working",
                        f"picking up {n} update{'s' if n != 1 else ''}",
                        handoff=True,
                    )
                return 0
            if time.time() > server_check_at:
                server_check_at = time.time() + 5
                if not running_server(page_dir):
                    # An idle page has no reviewer to keep online, and the
                    # SessionEnd hook idles then stops: without this the watcher
                    # it raced would put the server straight back up.
                    if (read_json(page_dir / "status.json") or {"state": "idle"})["state"] == "idle":
                        print("the review is closed; not restarting the server", file=sys.stderr)
                        return 2
                    # One revival per wait: a server that dies the moment it comes
                    # up would otherwise respawn every five seconds forever.
                    if revived or not revive_server(page_dir):
                        print(
                            "server is not running; restart it with `colloquy server run`",
                            file=sys.stderr,
                        )
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


def thread_widget_ids(events: list) -> set:
    """Ids claimed by widget markup in Claude's logged messages. Thread markup is frozen
    in the log and rendered into the panel, so its ids share one universe with page ids —
    the runtime resolves actions document-wide by id, and a collision would silently
    redirect a thread widget's replay to the page."""
    ids = set()
    for e in events:
        # author gate mirrors the renderer: only Claude's messages inject HTML — a user
        # comment or reply merely quoting markup renders as text and claims nothing.
        if e["kind"] in ("comment", "reply") and e["author"] == "claude" and "<cq-" in e["text"]:
            p = _StructParser()
            p.feed(e["text"])
            ids |= p.ids
    return ids


def action_widget_tags(page_dir: Path, version: int, events: list) -> dict:
    """Widget id → tag in the document that sent an action.

    Page widgets come from the action's own published version, not whichever
    version is newest now. Claude-authored thread widgets are the other live
    document the runtime renders; user messages quote markup as text and do not
    join this map. Both readings use _StructParser, the same structure reading
    `version check` and thread-markup validation already trust.
    """
    sources = [version_path(page_dir, version).read_text(encoding="utf-8")]
    sources.extend(
        e["text"]
        for e in events
        if e["kind"] in ("comment", "reply")
        and e["author"] == "claude"
        and "<cq-" in e["text"]
    )
    widgets = {}
    for source in sources:
        parser = _StructParser()
        parser.feed(source)
        parser.close()
        widgets.update(
            (rec["attrs"]["id"], rec["tag"])
            for rec in parser.cq_elements
            if rec["attrs"].get("id")
        )
    return widgets


def action_contract_error(page_dir: Path, event: dict, events: list, registry: dict):
    """Why a structurally complete action violates its sending widget's contract."""
    tag = action_widget_tags(page_dir, event["version"], events).get(event["widget"])
    if tag is None:
        return (
            f"unknown action widget {event['widget']!r} in v{event['version']} "
            "or agent-authored thread markup"
        )
    entry = registry.get(tag)
    if entry is None:
        return (
            f"registry no longer declares <{tag}> for action widget "
            f"{event['widget']!r}"
        )
    state = entry.get("x-state", {})
    if event["action"] not in state:
        return f"<{tag}> does not declare action verb {event['action']!r}"
    errors = sorted(
        Draft202012Validator(state[event["action"]]["detail"]).iter_errors(event["detail"]),
        key=str,
    )
    if errors:
        return f"<{tag}> action {event['action']!r} detail is invalid: {errors[0].message}"
    return None


def version_ids(page_dir: Path) -> set:
    ids = set()
    for version in list_versions(page_dir):
        p = _StructParser()
        p.feed(version_path(page_dir, version).read_text(encoding="utf-8"))
        ids |= p.ids
    return ids


def reserved_ids_error(ids: list) -> str:
    """The one sentence for an authored id in the runtime's own namespace, shared by the
    version lint and the thread-markup one — page ids and a reply's are one universe, so
    what keeps both clear of the runtime's is one rule. colloquy.js coins document ids
    under `cq-` (`cq-msg-<event id>` for a message body, `cq-composer-quote`) and points
    ARIA at them, so an authored id there redirects the reference to the page."""
    return (
        "ids in the runtime's own cq- namespace (it coins cq-msg-… and cq-composer-quote "
        f"there, and points ARIA at them): {ids}"
    )


def check_thread_markup(
    page_dir: Path, kind: str, body: str, events: list, registry: dict | None
) -> None:
    """An agent comment or reply carrying widget markup renders live in the panel, so
    it validates against the vendored registry at post time — the discussion-side
    `version check`. Exits with what's wrong; returns on plain text, which is most
    of them."""
    if "<cq-" not in body:
        return
    if registry is None:
        sys.exit(
            f"{kind} carries widget markup but the page has no registry.json; "
            "run `colloquy page init`"
        )
    frag = _StructParser()
    frag.feed(body)
    frag.close()
    errs = fragment_errors(frag, registry, registry["$languages"]["names"])
    if errs:
        sys.exit(f"{kind} widget markup doesn't validate:\n" + "\n".join(f"  - {e}" for e in errs))
    if frag.suggestions:
        sys.exit(
            f"a {kind} can't carry <cq-suggestion>: thread markup is frozen in the "
            "log, so no version could ever settle it — put the change in the next "
            "version instead"
        )
    if frag.duplicate_ids:
        sys.exit(f"{kind} widget markup reuses an id within itself: {frag.duplicate_ids}")
    if frag.reserved_ids:
        sys.exit(f"{kind} widget markup takes " + reserved_ids_error(frag.reserved_ids))
    clash = sorted(frag.ids & (version_ids(page_dir) | thread_widget_ids(events)))
    if clash:
        sys.exit(f"{kind} widget ids already taken by the page or an earlier message: {clash}")


def message_agent(page_dir: Path) -> str:
    """The agent originating a new message, or a generic label when no host
    session has claimed the page."""
    return (read_json(page_dir / "session.json") or {}).get("agent", "Agent")


def cmd_comment(page_dir: Path, quote: str, section: str, text) -> None:
    """Open a thread on a passage, as the reviewer's own selection does. The anchor is
    captured against the version they are looking at — the newest published one, since a
    version no `note` has released is a passage nobody can be pointed at — and read as
    they see it: a slot their decision retired is off the page, and a draft they edited
    holds their words, so a quote is met here the way it would land there."""
    if not quote and not section:
        sys.exit("a comment points at something: pass --quote, --section, or both")
    events = read_events(page_dir)
    published = published_versions(page_dir, events)
    if not published:
        sys.exit("no published version to anchor in; run `colloquy version publish` first")
    version = published[-1]
    html = version_path(page_dir, version).read_text(encoding="utf-8")
    registry = load_registry(page_dir)
    if registry is None:
        sys.exit(f"no registry.json in {page_dir}; run `colloquy page init` first")
    fold, _, _ = page_fold(html, events, registry, version)
    decided = decisions(fold, registry)
    edited = rewritten_bodies(fold)
    try:
        anchor = capture_anchor(html, registry, quote, section, decided, edited)
    except ValueError as err:
        sys.exit(f"can't anchor in v{version}: {err}")
    body = read_text_arg(text)
    check_thread_markup(page_dir, "comment", body, events, registry)
    event = append_event(
        page_dir,
        {
            "kind": "comment",
            "author": "claude",
            "agent": message_agent(page_dir),
            "version": version,
            "anchor": anchor,
            "text": body,
        },
    )
    print(json.dumps(event, ensure_ascii=False))


def cmd_reply(page_dir: Path, to: str, text) -> None:
    events = read_events(page_dir)
    known = {e["id"] for e in events if e["kind"] in {"comment", "reply"}}
    if to not in known:
        sys.exit(f"unknown comment id {to!r}; known: {sorted(known)}")
    body = read_text_arg(text)
    registry = load_registry(page_dir) if "<cq-" in body else None
    check_thread_markup(page_dir, "reply", body, events, registry)
    event = append_event(
        page_dir,
        {
            "kind": "reply",
            "author": "claude",
            "agent": message_agent(page_dir),
            "parent": to,
            "text": body,
        },
    )
    print(json.dumps(event, ensure_ascii=False))


def cmd_publish(page_dir: Path, version: int, text) -> None:
    name = version_name(version)
    path = version_path(page_dir, version)
    if not path.is_file():
        sys.exit(f"no v{version}.html in {page_dir / 'versions'}; write the version file first")
    # Publishing makes the note the server's visibility gate, so a version that
    # fails the check cannot go live.
    if cmd_check(page_dir, version) != 0:
        sys.exit(f"refusing to publish {name}: `colloquy version check` failed (issues above)")
    # Publishing is also where a `restated` declaration becomes a fact. The
    # attribute is how the author says it while writing the version — beside the
    # words they rewrote, where it can't be forgotten — and the log is where it
    # has to live, because the retraction outlives the version declaring it and
    # no later version should have to repeat it (see retractions). It rides the
    # note itself rather than a second event: `note` is one act, and two appends
    # can be torn by a crash into a retraction for a version that never published.
    parser = _StructParser()
    parser.feed(path.read_text(encoding="utf-8"))
    parser.close()
    retracts = sorted(parser.restated)
    event = {"kind": "note", "author": "claude", "version": version, "text": read_text_arg(text)}
    if retracts:
        event["restated"] = retracts
    print(json.dumps(append_event(page_dir, event), ensure_ascii=False))


def cmd_events(page_dir: Path, after: int) -> None:
    for event in read_events(page_dir):
        if event["seq"] > after:
            print(json.dumps(event, ensure_ascii=False))


def cmd_transcript(page_dir: Path) -> None:
    """The review thread as Markdown, for reuse in a PR description."""
    events = read_events(page_dir)
    versions = list_versions(page_dir)
    title = ""
    if versions:
        parser = _StructParser()
        parser.feed(version_path(page_dir, versions[-1]).read_text(encoding="utf-8"))
        parser.close()
        title = parser.title.strip()
    print(f"## Review: {title or page_dir.name}")

    notes = [e for e in events if e["kind"] == "note"]
    if notes:
        print("\n### Versions\n")
        for e in notes:
            print(f"- v{e['version']}: {e['text']}")

    # The reviewer's direct edits are review outcomes; without them the transcript
    # understates the review whenever a changelog note doesn't restate them. So
    # is a version taking one back, which is the same understatement the other
    # way round — an edit shown as final that a later version overruled.
    # Widget-agnostic rendering: verb + detail pairs, against the version edited.
    edits = [
        e for e in events
        if e["kind"] == "action" or (e["kind"] == "note" and e.get("restated"))
    ]
    if edits:
        print("\n### Edits\n")
        for e in edits:
            if e["kind"] == "note":
                for wid in e["restated"]:
                    print(f"- `{wid}`: rewritten by v{e['version']}, retracting what was decided on it")
                continue
            detail = " ".join(f"{k}={v}" for k, v in e["detail"].items())
            verb = f"{e['action']} {detail}".strip()  # a bare reject carries no detail
            print(f"- `{e['widget']}`: {verb} (on v{e['version']})")

    threads = build_threads(events)
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
            who = m.get("agent", "Agent") if m["author"] == "claude" else "User"
            body = m["text"].replace("\n", "\n  ")
            print(f"- **{who}**: {body}")
        print()
    for e in events:
        if e["kind"] == "done":
            print(f"Approved at {e['ts']}.")
            break

    # To stderr — stdout is the artifact. A transcript is a review's closing act,
    # and the record debt it reports here is about to stop being fixable.
    published = published_versions(page_dir, events)
    registry = load_registry(page_dir)
    if published and registry:
        html = version_path(page_dir, published[-1]).read_text(encoding="utf-8")
        for line in record_lag(html, events, registry):
            print(f"record behind the log — {line}", file=sys.stderr)


CATALOG_PREAMBLE = """\
# Widget vocabulary, vendored for this page — `version check` validates against it.
#
# Widgets are cq-* elements in the authored HTML; attributes carry scalars
# (enums, flags), children carry prose, and an item's title is a leading
# <strong> child. Every cq-* element takes an explicit end tag — never
# <cq-foo/>. Ids are authored (lowercase kebab), unique, stable across
# versions. Each entry is JSON Schema over the attributes; x-parent names the
# required parent, x-content the content model (prose | items | data | none).
# A "data" body is text in the notation the description names, < > escaped.
# x-upgrade marks tags a JS module enhances in the browser — the interactive
# widgets and the data-body renderers; x-says names the attributes whose values
# the reader sees as words, and the edge each renders at, so the reviewer can
# select and comment on them like any other text on the page. x-verbatim marks
# an upgraded element whose body reaches the reader as its own words, which is
# what makes it quotable — a body without it is source the widget renders.
# x-language names the attribute carrying a code language, which is checked
# against the one list this page colors from (printed below).
"""


def cmd_catalog(page_dir: Path) -> None:
    reg = load_registry(page_dir)
    if reg is None:
        sys.exit(f"no registry.json in {page_dir}; run `colloquy page init` first")
    print(CATALOG_PREAMBLE)
    print(json.dumps({k: v for k, v in reg.items() if not k.startswith("$")}, indent=2, ensure_ascii=False))
    restated = reg.get("$restated")
    if restated:
        print("\n# `restated` — the one attribute that spans widgets; read it before revising one.\n")
        print(json.dumps(restated, indent=2, ensure_ascii=False))
    state = reg.get("$state")
    if state:
        print("\n# x-state — how a widget's action verbs and their record forms are declared.\n")
        print(json.dumps(state, indent=2, ensure_ascii=False))
    languages = reg.get("$languages")
    if languages:
        print("\n# The languages this page colors, in a code block's class or an x-language attribute.\n")
        print(json.dumps(languages, indent=2, ensure_ascii=False))
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
        events = read_events(page_dir)
        state = full_state(page_dir, events, published_versions(page_dir, events))
        if state["listening"]:
            # A live `review wait` is the watch, and it delivers what's pending on its own.
            # Reporting the page here would have Claude start a second one, and two
            # waiters race the cursor and deliver the same events twice.
            continue
        n = state["pending"]
        if n:
            reasons.append(
                f"{page_dir}: {n} user event{'s' if n != 1 else ''} you haven't picked up."
                " `colloquy review wait` prints them; address every one."
            )
        elif state["status"]["state"] != "idle":
            reasons.append(
                f"{page_dir}: no watcher. Start `colloquy review wait` on it as a "
                "background task, or run `colloquy review state <page> idle` if the "
                "review is over."
            )
    return reasons


def cmd_hook(payload: dict) -> None:
    event, sid = payload.get("hook_event_name"), payload.get("session_id") or ""
    if event == "SessionEnd":
        for page_dir in owned_pages(sid):
            cmd_status(page_dir, "idle", "the session that opened this page has ended")
            cmd_stop(page_dir)
        (state_home() / "sessions" / f"{sid}.json").unlink(missing_ok=True)
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
# …and closes its own kind: a start tag ends the open siblings it can't nest inside.
SIBLING_CLOSERS = {
    "li": ("li",),
    "dt": ("dt", "dd"),
    "dd": ("dt", "dd"),
    "td": ("td", "th"),
    "th": ("td", "th"),
    "tr": ("td", "th", "tr"),
    "thead": ("td", "th", "tr", "thead", "tbody", "tfoot"),
    "tbody": ("td", "th", "tr", "thead", "tbody", "tfoot"),
    "tfoot": ("td", "th", "tr", "thead", "tbody", "tfoot"),
    "option": ("option",),
    "optgroup": ("option", "optgroup"),
}


# How a plain code block names its language, matching colloquy.js's own pattern. The
# class is the universal one every Markdown renderer emits, so a block Claude wrote
# elsewhere lands here unchanged.
LANGUAGE_CLASS = re.compile(r"(?:^|\s)language-([\w+.#-]+)(?=\s|$)")

# Container selectors whose max-width defines the readable column.
COLUMN_SELECTORS = ("main", "body", "article", ".container", ".wrap", ".content", ".page")
COLUMN_FALLBACK = 780
# Attribute widths only count as pixels on these elements.
PIXEL_WIDTH_TAGS = {"img", "svg", "table", "canvas", "iframe", "video", "object"}
# The properties that overflow a column when pinned in pixels. max-width defines the
# column instead, so it is read there and never counted here.
OVERFLOW_PROPS = ("width", "min-width")
# Page-level declarations the runtime reads from <meta name="cq-*"> in the head,
# name → allowed content values (None = free-form). A misspelled name or value
# would silently declare nothing in the browser, so `version check` owns this
# vocabulary the way the registry owns cq-* elements.
CQ_META = {"cq-review": frozenset({"sign-off"})}


def implicit_closes(open_tags: list, tag: str) -> int:
    """How many elements at the top of an open-element stack this start tag closes,
    under HTML's optional-end-tag rules. Two parsers walk the same documents — the
    structure lint and the passage reader — and `version check` accepts an omitted
    </p>, so a tree they disagreed about would be a passage one of them puts in the
    wrong section."""
    closed = 0
    top = lambda: open_tags[-1 - closed] if closed < len(open_tags) else None
    if tag in P_CLOSERS:
        while top() == "p":
            closed += 1
    siblings = SIBLING_CLOSERS.get(tag, ())
    while top() in siblings:
        closed += 1
    return closed


class _StructParser(HTMLParser):
    """Tracks a tag stack to catch unclosed and mismatched tags, and collects what the
    rest of `version check` reads off a version: element ids, every <script src> tag,
    stylesheet links, each cq-* element (attributes, direct parent, direct children,
    direct text) for registry validation, the page's title, and everything it says
    about width. Foreign markup inside <svg> is skipped (SVG has its own self-closing
    rules that don't matter here)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []  # (tag, lineno, cq_record | None)
        self.errors = []
        self.all_ids = []
        self.external_scripts = []  # (src, type)
        self.stylesheets = []  # hrefs of rel=stylesheet links
        self.cq_metas = []  # {"name", "content", "line"} for <meta name="cq-*">
        # /media/ paths any attribute points at, so the check that the file is
        # there reads references and not mentions: a page documenting colloquy
        # writes one of these paths in prose, and a raw scan of the markup
        # would send its author hunting for a screenshot nothing asks for.
        self.media_refs = set()
        # What the version says about width, each where a document says it: CSS is
        # what a <style> block holds, and a fixed width is what a rule, a style="" or
        # a width="" states. The column check reads these three and nothing else.
        self.css = ""
        self.inline_styles = []  # each style="" declaration list
        self.attr_widths = []  # (tag, value) per width="" that counts as pixels
        self.title = ""  # what <title> says, for the transcript's heading
        # {"tag", "line", "attrs", "parent", "children", "text"}
        self.cq_elements = []
        # {"id", "resolves", "line", "slots", "old_ids", "new_ids", "nested"} per
        # cq-suggestion: which slots it carries and which ids live in each, so a
        # version's outcome can license retiring exactly the ids it settles.
        self.suggestions = []
        # {"tag", "parent", "lang", "line"} per element claiming a language — the
        # coloring the runtime honors on a plain <pre><code>, checked here because a
        # class it doesn't honor is a request that silently isn't answered.
        self.language_blocks = []
        self._svg_depth = 0

    @property
    def ids(self) -> set:
        return set(self.all_ids)

    @property
    def restated(self) -> set:
        """Ids this version declares it has rewritten, retracting whatever the
        reviewer had recorded on them."""
        return {
            rec["attrs"]["id"]
            for rec in self.cq_elements
            if rec["attrs"].get("id") and "restated" in rec["attrs"]
        }

    @property
    def duplicate_ids(self) -> list:
        seen, dupes = set(), set()
        for i in self.all_ids:
            (dupes if i in seen else seen).add(i)
        return sorted(dupes)

    @property
    def reserved_ids(self) -> list:
        """Ids that trespass on the runtime's own namespace (see reserved_ids_error)."""
        return sorted({i for i in self.all_ids if i.startswith("cq-")})

    def _implicit_close(self, tag):
        for _ in range(implicit_closes([t for t, _, _ in self.stack], tag)):
            self.stack.pop()

    def _open_suggestion(self):
        """The innermost cq-suggestion still open and which of its slots we are
        in: (record, "cq-old" | "cq-new" | None), or (None, None) outside one."""
        slot = None
        for tag, _, record in reversed(self.stack):
            if tag in ("cq-old", "cq-new"):
                slot = tag
            elif tag == "cq-suggestion":
                return record, slot
        return None, None

    def _harvest(self, tag, attrs_d):
        if attrs_d.get("id"):
            self.all_ids.append(attrs_d["id"])
            suggestion, slot = self._open_suggestion()
            if tag in ("cq-old", "cq-new"):
                slot = tag  # the slot's own id belongs to the slot
            if suggestion and slot:
                suggestion["old_ids" if slot == "cq-old" else "new_ids"].add(attrs_d["id"])
        if tag == "script" and attrs_d.get("src"):
            self.external_scripts.append((attrs_d["src"], attrs_d.get("type")))
        if tag == "link" and "stylesheet" in (attrs_d.get("rel") or ""):
            self.stylesheets.append(attrs_d.get("href"))
        if tag == "meta" and (attrs_d.get("name") or "").startswith("cq-"):
            self.cq_metas.append(
                {"name": attrs_d["name"], "content": attrs_d.get("content"), "line": self.getpos()[0]}
            )
        if attrs_d.get("style"):
            self.inline_styles.append(attrs_d["style"])
        if tag in PIXEL_WIDTH_TAGS and attrs_d.get("width"):
            self.attr_widths.append((tag, attrs_d["width"]))
        self.media_refs.update(
            v for v in attrs_d.values() if v and v.startswith(f"/{MEDIA_DIR}/")
        )

    def _attributes(self, tag, attrs):
        """The browser's attribute reading: first value wins, duplicates are invalid."""
        values = {}
        duplicates = set()
        for name, value in attrs:
            if name in values:
                duplicates.add(name)
            else:
                values[name] = value
        if duplicates:
            self.errors.append(
                f"<{tag}> at line {self.getpos()[0]} has duplicate attribute "
                f"names {sorted(duplicates)}; HTML keeps the first value"
            )
        return values

    def handle_starttag(self, tag, attrs):
        attrs_d = self._attributes(tag, attrs)
        # Before _harvest, whose id attribution reads the open suggestion: a
        # slot's contents belong to the suggestion that encloses them.
        if tag in ("cq-old", "cq-new"):
            suggestion, _ = self._open_suggestion()
            if suggestion:
                suggestion["slots"].append(tag)
        self._harvest(tag, attrs_d)
        if tag == "svg":
            self._svg_depth += 1
            self.stack.append((tag, self.getpos()[0], None))
            return
        if self._svg_depth:  # don't tag-balance inside SVG
            return
        # Before the void check: <hr> is void and closes an open <p>, and a void tag
        # left inside a paragraph it ended puts the rest of the section in it.
        self._implicit_close(tag)
        # After it, so the parent recorded here is the one the browser will see.
        lang = LANGUAGE_CLASS.search(attrs_d.get("class") or "")
        if lang:
            self.language_blocks.append({
                "tag": tag,
                "parent": self.stack[-1][0] if self.stack else None,
                "lang": lang.group(1),
                "line": self.getpos()[0],
            })
        if tag in VOID_TAGS:
            if self.stack and self.stack[-1][2] is not None:
                self.stack[-1][2]["children"].append(tag)
            return
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
            if tag == "cq-suggestion":
                enclosing, _ = self._open_suggestion()
                record.update(
                    id=attrs_d.get("id"),
                    resolves=attrs_d.get("resolves"),
                    slots=[],
                    old_ids=set(),
                    new_ids=set(),
                    nested=enclosing is not None,
                )
                self.suggestions.append(record)
        self.stack.append((tag, self.getpos()[0], record))

    def handle_startendtag(self, tag, attrs):
        # <foo/> — self-closing; still harvest but never pushed. For cq-* the
        # slash is a trap: HTML ignores it, the element stays open in a browser
        # and swallows the rest of its parent, so reject the form outright.
        self._harvest(tag, self._attributes(tag, attrs))
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
        holder = self.stack[-1][0] if self.stack else None
        if holder == "style":
            self.css += data
        elif holder == "title":
            self.title += data

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


# ---------- passages: the text an anchor points at ----------
# The runtime resolves an anchor against the DOM; `review comment` writes one down
# against the file. The two have to read the same page or the anchor lands somewhere it
# was never made, so this mirrors colloquy.js's capture rather than approximating it:
# the same skip list, the same block-boundary space, the same collapse, the same caps.
#
# What the file cannot know is what a widget's module will write, and the registry is
# where that is declared rather than guessed at per widget. Three keywords carry what
# can be declared, and a fence carries the rest:
#
#   x-says      attribute values the reader sees. renderSaid puts them in the DOM, so
#               they go in here too, at the edge the registry names.
#   x-verbatim  an upgraded element whose body reaches the reader as its own words
#               (cq-draft renders the authored text into a plain div, deliberately
#               unmarked so anchoring can see it). Without it, an upgraded element is
#               opaque: a mermaid body is a picture by the time it is read.
#   x-retired-when  the outcome under which this element leaves the page: a decided
#               suggestion's losing slot. The browser builds its anchor pass's skip
#               list from this key too (`quotable` in colloquy.js), so a reading given
#               the log's outcomes drops here exactly what drops there — and a widget
#               whose decision leaves nothing showing goes with its slots (settledAway
#               there, `gone` here). Its values are also the vocabulary's decision
#               verbs, which is where `decisions` reads them from.
#   x-state, record kind "body"  the verb whose detail text becomes this element's
#               body once the reviewer sends one (cq-draft's `edit`): replay writes
#               the newest surviving one into the DOM verbatim (applyAction is
#               absolute), so a reading given the fold's word (rewritten_bodies)
#               holds their words in the authored body's place. It asks nothing of
#               the browser, whose page already shows the text this substitutes.
#
# A module writes between the children of the element it upgrades — a column's heading, a
# milestone's chips, a diff's gutters — so an opaque element and each of its children is
# fenced. A quote never spans a fence, which turns "the page has words here that the file
# doesn't" from an anchor that silently detaches in the reviewer's browser into a refusal
# at the moment it is written, addressed to the one party who can still fix it.

# What a text node's "block" resolves to, matching the runtime's TEXT_BLOCK: one space
# goes wherever two runs of text sit in different blocks, and none where they share one,
# so `<p>a</p><p>b</p>` reads "a b" and `set<em>up</em>` reads "setup".
TEXT_BLOCK_TAGS = {
    "p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "pre",
    "blockquote", "dd", "dt", "figcaption", "summary",
}
# Text no anchor can reach. script/style are the anchor pass's own skip list; head is
# outside the tree it searches at all, the runtime rooting a section-less anchor at
# document.body — without it a page's <title> would be quotable and land nowhere.
UNQUOTABLE_TAGS = {"script", "style", "head"}
# The caps colloquy.js captures at: how much quote an anchor stores, and how much of the
# surrounding text it stores to tell two identical passages apart.
QUOTE_CAP = 400
CONTEXT = 24
class _PassageParser(HTMLParser):
    """A version's prose as the anchor pass reads it. `text` is the whole page collapsed
    the way a captured quote is; `owner[i]` is the ids enclosing text[i], outermost
    first, so a match can name the section it fell in and be re-read within it.

    `decided` is the accept/reject each suggestion stands under (`decisions`).
    A decision retires a slot — the registry's `x-retired-when` names which outcome —
    and the browser's anchor pass reads the same key (`quotable` in colloquy.js), so
    this reading drops it the same way. A decision that leaves its
    widget with nothing — a deletion accepted, an insertion refused — empties the
    wrapper too (`gone`), because an element showing nothing is one nobody can point
    at, however present its markup. `rewrites` is the reviewer's
    standing text per element whose registry entry records a verb as the body
    (`rewritten_bodies`): their words stand in the authored body's place, because
    replay writes exactly that into the DOM. Without either, the reading is the
    version as authored — every slot pending, every body Claude's."""

    def __init__(self, registry=None, decided=None, rewrites=None):
        super().__init__(convert_charrefs=True)
        self.registry = registry or {}
        self.decided = decided or {}
        self.rewrites = rewrites or {}
        self.text = ""
        self.owner = []  # per character: the tuple of enclosing ids
        self.fences = set()  # indices a quote may not span
        self.retired = {}  # id under a retired slot → the suggestion whose decision did it
        self.rewritten = {}  # id whose body the reviewer rewrote → the verb that did it
        self.gone = {}  # decided id whose decision left it empty → the outcome that did it
        self.bearing = set()  # ids still showing something: text under them, or a surviving child
        self.stack = []  # [{"tag", "id", "ids", "skip", "sub", "opaque", "fenced", "retired_by", "tb", "block", "tail"}]
        self._uid = 0
        self._block = None  # the block the last character came from
        self._space = False  # a separator waiting for a character to follow it

    def _fresh(self) -> int:
        self._uid += 1
        return self._uid

    def _write(self, data: str, block: int, ids: tuple) -> None:
        """Text into the collapsed run, one space per whitespace run and none leading."""
        if data.strip():
            self.bearing.update(ids)
        if self.text and block != self._block:
            self._space = True
        self._block = block
        for ch in data:
            if ch.isspace():
                self._space = bool(self.text)
                continue
            if self._space:
                self.text += " "
                self.owner.append(ids)
                self._space = False
            self.text += ch
            self.owner.append(ids)

    def _fence(self) -> None:
        """Words may stand here that this reading knows nothing about. Recorded as a
        position rather than written into the text, so `text` stays the page's own words
        and no quote can be built out of one."""
        self.fences.add(len(self.text))

    def _said(self, frame: dict, values: list) -> None:
        # renderSaid puts each value in its own <span>, so each is its own block wherever
        # the widget sits outside a text block — the same rule, applied to the span.
        for value in values:
            self._write(value, frame["tb"] if frame["tb"] else self._fresh(), frame["ids"])

    def _close(self, frame: dict) -> None:
        """Everything an element's end does, whether it was written or inferred — an
        omitted </p> inside a widget still ends what the element was saying."""
        if not frame["skip"]:
            self._said(frame, frame["tail"])
        if frame["fenced"]:
            self._fence()
        # A decided element closing with nothing shown left the page with its decision:
        # a deletion accepted, an insertion refused. Everything it held is either a
        # retired slot or silent, so there is nothing on screen for an anchor to reach.
        if frame["id"] in self.decided and not frame["skip"] and frame["id"] not in self.bearing:
            self.gone[frame["id"]] = self.decided[frame["id"]]

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        # Before the void check, unlike the structure lint's: <hr> is both void and a
        # paragraph closer, and text after it is in a different block.
        for _ in range(implicit_closes([f["tag"] for f in self.stack], tag)):
            self._close(self.stack.pop())
        if tag in VOID_TAGS:
            return
        parent = self.stack[-1] if self.stack else None
        entry = self.registry.get(tag) or {}
        # The innermost open text block, if any: the runtime's `closest(TEXT_BLOCK)`.
        tb = self._fresh() if tag in TEXT_BLOCK_TAGS else (parent["tb"] if parent else None)
        # A module may write anywhere inside the element it upgrades, unless the registry
        # says the body reaches the reader as its own words.
        opaque = bool(entry.get("x-upgrade") and not entry.get("x-verbatim"))
        # A slot a decision retired: its words left the page with the outcome the
        # registry names, and everything under it goes too. Looked up by the parent's
        # own id — the same child-of-suggestion shape as the browser's selector.
        retired_by = (parent["retired_by"] if parent else None) or (
            parent["id"]
            if parent and entry.get("x-retired-when")
            and self.decided.get(parent["id"]) == entry["x-retired-when"]
            else None
        )
        # Silenced from above: the element shows nothing of its own, so a rewrite of
        # its body has nothing to stand in for — an edited draft inside a slot the
        # reviewer accepted away left the page with the slot.
        silenced = bool(
            (parent and parent["skip"])
            or retired_by
            or tag in UNQUOTABLE_TAGS
            or "cq-ui" in (attrs_d.get("class") or "").split()
        )
        # A surviving child keeps its parent on the page even where it holds no text —
        # a kept slot whose only content is an image. The text case marks every
        # enclosing id in _write.
        if parent and not silenced:
            self.bearing.add(parent["id"])
        # A body the reviewer rewrote. `rewritten_bodies` already resolved the verb
        # through this element's x-state, so an id in the dict is the whole test:
        # the fold decides, this pass only applies.
        sub = self.rewrites.get(attrs_d.get("id")) if not silenced else None
        frame = {
            "tag": tag,
            "id": attrs_d.get("id"),
            "ids": (parent["ids"] if parent else ()) + ((attrs_d["id"],) if attrs_d.get("id") else ()),
            "skip": silenced or sub is not None or (opaque and entry.get("x-content") == "data"),
            "sub": sub,
            "retired_by": retired_by,
            "opaque": opaque,
            "fenced": opaque or bool(parent and parent["opaque"]),
            "tb": tb,
            # …and where there is none, the element is its own text node's parent, which
            # is what the runtime falls back to. Fresh per element, so `a<em>b</em>c`
            # under a <div> reads as three blocks and under a <p> as one.
            "block": tb if tb else self._fresh(),
            "tail": [],
        }
        # Each x-says value at the edge its pseudo-element occupied. renderSaid prepends,
        # so the last "before" attribute in registry order ends up first in the DOM.
        head = []
        for attr, edge in (entry.get("x-says") or {}).items():
            value = attrs_d.get(attr)
            if value is None:
                continue
            if edge == "before":
                head.insert(0, value)
            else:
                frame["tail"].append(value)
        if frame["fenced"]:
            self._fence()
        if retired_by and frame["id"]:
            self.retired[frame["id"]] = retired_by
        self.stack.append(frame)
        if not frame["skip"]:
            self._said(frame, head)
        elif sub is not None:
            # The body's own write path, so a quote across the element's edge sees
            # the same adjacency the screen shows — no fence, nothing withheld.
            verb, their_text = sub
            self._write(their_text, frame["block"], frame["ids"])
            self.rewritten[frame["id"]] = verb

    def handle_data(self, data):
        frame = self.stack[-1] if self.stack else None
        if frame and not frame["skip"]:
            self._write(data, frame["block"], frame["ids"])

    def handle_endtag(self, tag):
        if tag in VOID_TAGS:
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]["tag"] == tag:
                # Innermost first, so an element closing over unclosed children ends them
                # in the order they were opened in.
                while len(self.stack) > i:
                    self._close(self.stack.pop())
                return


class Passages(NamedTuple):
    """A version's words, and what a search over them needs to know."""

    text: str  # collapsed the way a captured quote is
    owner: list  # per character: the tuple of enclosing ids, outermost first
    fences: set  # indices a quote may not span: where a module may write
    retired: dict  # id under a retired slot → the suggestion whose decision did it
    rewritten: dict  # id whose body the reviewer rewrote → the verb that did it
    gone: dict  # decided id whose decision left it empty → the outcome that did it


def page_passages(html: str, registry=None, decided=None, rewrites=None) -> Passages:
    parser = _PassageParser(registry, decided, rewrites)
    parser.feed(html)
    parser.close()
    return Passages(
        parser.text, parser.owner, parser.fences, parser.retired, parser.rewritten, parser.gone
    )


def section_span(owner: list, section: str):
    """The half-open range of characters inside `section`, or None when the version has
    no such element with text in it. An element is contiguous in document order, so its
    characters are too — which is what lets a search be scoped by slicing."""
    inside = [i for i, ids in enumerate(owner) if section in ids]
    return (inside[0], inside[-1] + 1) if inside else None


class Spoken(NamedTuple):
    """What one element says, and where it sits."""

    words: str  # the words under it, as the anchor pass reads them
    within: tuple  # the ids enclosing it, outermost first, itself last


# An element the version has no words for — nothing said, nothing enclosing it.
EMPTY = Spoken("", ())


def spoken(html: str, registry: dict) -> dict:
    """id → Spoken, for every element with words under it.

    This is the version's own reading of itself, so it is `page_passages` sliced by
    id rather than a second walk: chrome skipped, x-says attributes counted (a
    picked option's `effort` is a word on the page now, so changing it changes what
    the reviewer decided about), whitespace collapsed the way a captured quote is.
    Asking whether two versions still say the same thing has to mean the same text a
    reviewer could have selected, or the question is about something else.

    `section_span` answers this for one id by scanning the page; every id at once is
    that same scan, done once."""
    p = page_passages(html, registry)
    first, last = {}, {}
    for i, ids in enumerate(p.owner):
        for wid in ids:
            first.setdefault(wid, i)
            last[wid] = i
    # Stripped: the separator `_write` puts between blocks lands inside whichever
    # element the next block opens, so a slice can start or end on one. It marks a
    # boundary rather than saying anything.
    return {
        wid: Spoken(p.text[lo:last[wid] + 1].strip(), p.owner[lo])
        for wid, lo in first.items()
    }


def enclosing_section(owner: list, lo: int, hi: int):
    """The innermost id enclosing every character of [lo, hi) — the runtime's
    `closest("[id]")` on the passage's common ancestor."""
    first, last = owner[lo], owner[hi - 1]
    shared = 0
    while shared < min(len(first), len(last)) and first[shared] == last[shared]:
        shared += 1
    return first[shared - 1] if shared else None


def occurrences(text: str, quote: str, lo: int, hi: int, fences=frozenset()) -> list:
    """Where `quote` sits in text[lo:hi], as absolute indices. A match that runs across a
    fence is not one: the page has words there that this text doesn't."""
    found = []
    at = text.find(quote, lo, hi)
    while at != -1:
        if not any(at < f < at + len(quote) for f in fences):
            found.append(at)
        at = text.find(quote, at + len(quote), hi)
    return found


def capture_anchor(html: str, registry, quote: str, section: str, decided=None, rewrites=None) -> dict:
    """The anchor a quote makes, written the way a selection's is. Raises ValueError with
    what to do about it — a quote the file doesn't hold, or holds twice, is a question
    with an answer, and asking now beats posting a comment that lands nowhere.

    `decided` and `rewrites` make this the reading the reviewer is looking at rather
    than the version as authored: a slot their decision retired is off the page, and a
    body their edit rewrote holds their words — so an anchor is met here the way it
    would land there, instead of detaching in front of them."""
    text, owner, fences, retired, rewritten, gone = page_passages(html, registry, decided, rewrites)
    if section:
        # Against the structure, not the text: an element anchor is the one a click makes
        # on a diagram or an image, and those hold no text to look for.
        structure = _StructParser()
        structure.feed(html)
        if section not in structure.ids:
            raise ValueError(f"no element id {section!r} in this version")
        if section in retired:
            sid = retired[section]
            raise ValueError(
                f"§ {section} left the page when the reviewer chose to {decided[sid]} "
                f"§ {sid} — a decided suggestion's losing slot is retired, and an anchor "
                "on it would reach nobody. Anchor on the settled text instead."
            )
        if section in gone:
            raise ValueError(
                f"§ {section} settled to nothing when the reviewer chose to {gone[section]} "
                "it — the decision removed everything it held from the page, and an anchor "
                "on it would reach nobody. Anchor on the surrounding text instead."
            )
    if not quote:
        return {"section": section}

    wanted = " ".join(quote.split())
    lo_bound, hi_bound = 0, len(text)
    if section:
        span = section_span(owner, section)
        if span is None:
            raise ValueError(
                f"§ {section} holds no quotable text — a widget's data body is its source, "
                "not its words. Drop --quote to anchor on the element itself."
            )
        lo_bound, hi_bound = span
    where = "the page" if not section else f"§ {section}"
    hits = occurrences(text, wanted, lo_bound, hi_bound, fences)
    if not hits:
        if occurrences(text, wanted, lo_bound, hi_bound):
            raise ValueError(
                f"{wanted!r} runs across a widget's parts, and a widget writes words of "
                "its own between them — a column's heading, a milestone's chips, a "
                "diagram in place of its source. Quote within one part, or --section the "
                "widget to point at the whole of it."
            )
        was = _removed_by(html, registry, wanted, section, decided or {}, rewritten)
        if was:
            raise ValueError(f"{where} said {wanted!r} until {was}")
        raise ValueError(
            f"{where} doesn't say {wanted!r} — quote it as the version file holds it. A "
            "widget's data body is the widget's source, not its words (a diagram's body "
            "is a picture by the time it is read), so --section the element instead."
        )
    if len(hits) > 1:
        shown = [f"  - …{text[max(lo_bound, at - 30):at + len(wanted) + 30]}…" for at in hits[:4]]
        if len(hits) > len(shown):
            shown.append(f"  - …and {len(hits) - len(shown)} more")
        raise ValueError(
            f"{where} says {wanted!r} {len(hits)} times, so this quote names no one "
            "passage. Extend it, or scope it with --section:\n" + "\n".join(shown)
        )

    lo = hits[0]
    hi = lo + len(wanted)
    section = section or enclosing_section(owner, lo, hi)
    stored = wanted[:QUOTE_CAP]
    tail = lo + len(stored)  # a quote cut to the cap ends inside itself
    # The neighbours come from the whole reading, as the browser's do — the section
    # filters where the search may land, never what surrounds a passage — so a passage
    # closing its section still stores a full suffix. Each side reaches only to the
    # nearest fence, because past one the page holds words this doesn't: context the
    # runtime can never confirm leaves every copy equally unconfirmed, which is where
    # an anchor carrying none starts anyway.
    # Both are trimmed before they are cut, since the runtime reads its side back through
    # the same collapse, which trims — a stored space no occurrence produces fails at the
    # first comparison.
    prefix = text[max([0] + [f for f in fences if f <= lo]):lo].strip()[-CONTEXT:]
    suffix = text[tail:min([len(text)] + [f for f in fences if f >= tail])].strip()[:CONTEXT]
    return {
        "section": section,
        "quote": stored,
        **({"prefix": prefix} if prefix else {}),
        **({"suffix": suffix} if suffix else {}),
    }


def _removed_by(html, registry, wanted: str, section: str, decided, rewritten):
    """What took `wanted` off the reviewer's page, when the version as authored still
    holds it: the decision that retired the slot it sat in, or the edit that rewrote
    the element saying it. Naming that act beats telling the writer the page never
    said it."""
    if not (decided or rewritten):
        return None
    p = page_passages(html, registry)
    lo, hi = 0, len(p.text)
    if section:
        span = section_span(p.owner, section)
        if span is None:
            return None
        lo, hi = span
    for at in occurrences(p.text, wanted, lo, hi, p.fences):
        for ids in p.owner[at:at + len(wanted)]:
            sid = next((wid for wid in ids if wid in decided), None)
            if sid:
                return (
                    f"the reviewer chose to {decided[sid]} § {sid} — that decision "
                    "retired these words from the page. Quote it as it now stands."
                )
            wid = next((wid for wid in ids if wid in rewritten), None)
            if wid:
                return (
                    f"the reviewer rewrote § {wid} — their {rewritten[wid]} replaced "
                    "these words. Quote the text as they left it."
                )
    return None


# ---------- the readable column ----------
# A rule, a style="" and a width="" are the three places a document states a width.
# The first two are CSS, so tinycss2 reads them; the third is an attribute, so the
# markup parser does.


def css_block(css):
    """What a block holds: the declarations it states, and the rules nested inside it. A
    style="" attribute is a block written without the braces around it."""
    return tinycss2.parse_blocks_contents(css, skip_comments=True, skip_whitespace=True)


def css_rules(css: str):
    """(selector, block, conditional) per qualified rule, at every depth — a rule that
    holds both declarations and a nested rule states one of its own. `conditional` is
    true for a rule inside an at-rule, which applies only when a condition this check
    never evaluates holds: `@media print`, a viewport query. Nesting alone is not a
    condition, so a rule nested in a conditional one is conditional and no more."""
    yield from _rules(tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True))


def css_syntax_errors(css: str, source: str, *, block=False) -> list:
    """Every parse error in a stylesheet or declaration block, including nested rules."""
    parse = css_block if block else lambda value: tinycss2.parse_stylesheet(
        value, skip_comments=True, skip_whitespace=True
    )
    errors = []
    seen = set()

    def record(node):
        key = (node.source_line, node.source_column, node.message)
        if key in seen:
            return
        seen.add(key)
        errors.append(
            f"{source} syntax error at "
            f"{node.source_line}:{node.source_column}: {node.message}"
        )

    def walk_tokens(tokens):
        for token in tokens:
            if token.type == "error":
                record(token)
            for attr in ("arguments", "content"):
                nested = getattr(token, attr, None)
                if isinstance(nested, list):
                    walk_tokens(nested)

    def walk_rules(nodes):
        for node in nodes:
            if node.type == "error":
                record(node)
            for attr in ("prelude", "value"):
                tokens = getattr(node, attr, None)
                if isinstance(tokens, list):
                    walk_tokens(tokens)
            if node.type in {"qualified-rule", "at-rule"} and node.content is not None:
                walk_tokens(node.content)
                walk_rules(css_block(node.content))

    walk_rules(parse(css))
    return errors


def _rules(nodes, conditional=False):
    """`nodes` and every rule nested inside them, as (selector, block, conditional)."""
    for node in nodes:
        if node.type == "qualified-rule":
            block = css_block(node.content)
            yield tinycss2.serialize(node.prelude).strip(), block, conditional
            yield from _rules(block, conditional)
        elif node.type == "at-rule" and node.content:
            yield from _rules(css_block(node.content), True)


def _number(text: str):
    """`text` as a number, or None when it is not one. A width="" attribute states a
    bare count of pixels, so it has no unit for the CSS parser to read."""
    try:
        return float(text)
    except ValueError:
        return None


def _px(declaration):
    """The pixel length a declaration states, or None where it states something else: a
    percentage, a vw, a calc() with a px term inside it. Only a fixed pixel length is a
    hard overflow, and only a lone length is fixed. A value keeps the whitespace around
    it, which is a token like any other and not part of what the value says."""
    value = [t for t in declaration.value if t.type != "whitespace"]
    if len(value) == 1 and value[0].type == "dimension" and value[0].lower_unit == "px":
        return value[0].value
    return None


def _px_widths(declarations, props: tuple):
    """(property, pixels) per declaration in `props` pinned to a fixed pixel length."""
    for declaration in declarations:
        if declaration.type == "declaration" and declaration.lower_name in props:
            px = _px(declaration)
            if px is not None:
                yield declaration.lower_name, px


def _column_width(page_css: str, theme_css: str) -> int:
    """Best-effort readable-column width from the max-width of a container rule.
    A page's own <style> wins over the vendored theme, which wins over the fallback.

    Only what a stylesheet states outright counts: a column is the baseline everything
    else is measured against, so it has to be certain, and a conditional rule states a
    column for some condition rather than for the page. Reading them too let a page
    disable this check with one line of print CSS — `@media print { main { max-width:
    2000px } }` measured every screen element against 2000px."""
    for css in (page_css, theme_css):
        widths = [
            px
            for selector, block, conditional in css_rules(css)
            if not conditional and any(sel in selector for sel in COLUMN_SELECTORS)
            for _, px in _px_widths(block, ("max-width",))
        ]
        if widths:
            return int(max(widths))
    return COLUMN_FALLBACK


def _overwide_elements(parser: _StructParser, column: int) -> list:
    """Everything a version pins wider than the column: its own rules, its inline
    styles, and the width="" attributes that count as pixels.

    A conditional rule counts here, where it cannot define the column: a pin is a risk
    rather than a baseline, and it overflows whenever its condition holds."""
    hits = []
    for selector, block, _ in css_rules(parser.css):
        for prop, px in _px_widths(block, OVERFLOW_PROPS):
            if px > column:
                hits.append(f"rule `{selector}` sets {prop}: {px:g}px (column is {column}px)")
    for style in parser.inline_styles:
        for prop, px in _px_widths(css_block(style), OVERFLOW_PROPS):
            if px > column:
                hits.append(f"inline style {prop}: {px:g}px (column is {column}px)")
    for tag, value in parser.attr_widths:
        px = _number(value)
        if px is not None and px > column:
            hits.append(f'<{tag} width="{value}"> exceeds column ({column}px)')
    return hits


def read_registry_entries(path: Path):
    """Read the top-level entries one registry layer contributes."""
    if (path.exists() or path.is_symlink()) and not path.is_file():
        sys.exit(f"{path}: registry.json must be a file")
    try:
        registry = read_json(path)
    except json.JSONDecodeError as error:
        sys.exit(f"{path}: invalid JSON ({error.msg}, line {error.lineno})")
    except UnicodeDecodeError:
        sys.exit(f"{path} must be UTF-8")
    if registry is None:
        if not path.is_file():
            return None
        sys.exit(f"{path}: registry must be a JSON object")
    if not isinstance(registry, dict):
        sys.exit(f"{path}: registry must be a JSON object")
    non_objects = [name for name, entry in registry.items() if not isinstance(entry, dict)]
    if non_objects:
        sys.exit(f"{path}: registry entries must be objects: {non_objects}")
    return registry


def validate_registry(registry: dict, source) -> dict:
    """Validate one complete vocabulary after its top-level overlays are merged."""
    path = source
    try:
        kinds = registry["$events"]["kinds"]
        names = registry["$languages"]["names"]
        paths = registry["$languages"]["paths"]
    except (KeyError, TypeError):
        sys.exit(f"{path}: registry must declare $events.kinds and $languages.names/paths")
    if (
        not isinstance(kinds, dict)
        or not all(
            isinstance(kind, str)
            and isinstance(fields, list)
            and all(isinstance(field, str) for field in fields)
            and len(fields) == len(set(fields))
            for kind, fields in kinds.items()
        )
    ):
        sys.exit(f"{path}: $events.kinds must map event names to unique field-name lists")
    missing_events = []
    for kind, required in EVENT_VOCABULARY.items():
        if kind not in kinds:
            missing_events.append(f"kind `{kind}`")
            continue
        fields = required - set(kinds[kind])
        if fields:
            missing_events.append(f"`{kind}` fields {sorted(fields)}")
    if missing_events:
        sys.exit(
            f"{path}: $events.kinds omits vocabulary the current layer writes: "
            + ", ".join(missing_events)
        )
    if (
        not isinstance(names, list)
        or not all(isinstance(name, str) for name in names)
        or len(names) != len(set(names))
    ):
        sys.exit(f"{path}: $languages.names must be a unique list of strings")
    if (
        not isinstance(paths, dict)
        or not all(
            isinstance(extension, str) and language in names
            for extension, language in paths.items()
        )
    ):
        sys.exit(f"{path}: $languages.paths must map extensions to declared languages")
    invalid_names = [
        tag
        for tag in registry
        if not tag.startswith("$") and re.fullmatch(WIDGET_NAME, tag) is None
    ]
    if invalid_names:
        sys.exit(f"{path}: invalid registry entry names: {invalid_names}")
    widgets = {tag: entry for tag, entry in registry.items() if tag.startswith("cq-")}
    # First validate every entry in isolation. Cross-entry checks run only after this
    # pass, so their result cannot depend on which widget happened to be written first.
    for tag, entry in widgets.items():
        try:
            Draft202012Validator.check_schema(entry)
        except SchemaError as error:
            sys.exit(f"{path}: <{tag}> is not a valid JSON Schema: {error.message}")
        extensions = {key: value for key, value in entry.items() if key.startswith("x-")}
        errors = sorted(
            Draft202012Validator(EXTENSION_SCHEMA).iter_errors(extensions), key=str
        )
        if errors:
            sys.exit(f"{path}: <{tag}> registry extensions are invalid: {errors[0].message}")
        for verb, spec in entry.get("x-state", {}).items():
            try:
                Draft202012Validator.check_schema(spec["detail"])
            except SchemaError as error:
                sys.exit(
                    f"{path}: <{tag}> x-state verb `{verb}` has an invalid "
                    f"detail schema: {error.message}"
                )
            if spec["detail"].get("type") != "object":
                sys.exit(
                    f"{path}: <{tag}> x-state verb `{verb}` detail schema "
                    "must declare an object"
                )

    for tag, entry in widgets.items():
        parent = entry.get("x-parent")
        if parent and parent not in widgets:
            sys.exit(f"{path}: <{tag}> x-parent names unknown widget <{parent}>")
        properties = entry.get("properties", {})
        said = set(entry.get("x-says", {}))
        if unknown := sorted(said - set(properties)):
            sys.exit(f"{path}: <{tag}> x-says names undeclared attributes {unknown}")
        if unknown := sorted(set(entry.get("x-refers", [])) - set(properties)):
            sys.exit(f"{path}: <{tag}> x-refers names undeclared attributes {unknown}")
        language = entry.get("x-language")
        if language and language not in properties:
            sys.exit(f"{path}: <{tag}> x-language names undeclared attribute `{language}`")
        needs_upgrade = [
            key
            for key in ("x-state", "x-language", "x-verbatim")
            if entry.get(key) and not entry["x-upgrade"]
        ]
        if needs_upgrade:
            sys.exit(
                f"{path}: <{tag}> declares {', '.join(needs_upgrade)} "
                "but has no upgraded handler"
            )
        for verb, spec in entry.get("x-state", {}).items():
            detail_properties = spec["detail"].get("properties", {})
            required = set(spec["detail"].get("required", []))
            unit = spec.get("unit", "widget")
            fields = [] if unit == "widget" else [unit]
            record = spec.get("record")
            if record:
                fields.append(record["value"])
                if record["kind"] == "position" and record["within"] not in widgets:
                    sys.exit(
                        f"{path}: <{tag}> x-state verb `{verb}` records a position "
                        f"within unknown widget <{record['within']}>"
                    )
            undeclared = [field for field in fields if field not in detail_properties]
            optional = [field for field in fields if field not in required]
            if undeclared or optional:
                problem = (
                    f"does not declare {undeclared}"
                    if undeclared
                    else f"does not require {optional}"
                )
                sys.exit(
                    f"{path}: <{tag}> x-state verb `{verb}` reads detail fields "
                    f"its schema {problem}"
                )
            if unit != "widget" and record and record["kind"] != "position":
                sys.exit(
                    f"{path}: <{tag}> x-state verb `{verb}` records per-part state; "
                    "only position records support that"
                )

            def field_types(field):
                field_schema = detail_properties[field]
                declared = field_schema.get("type") if isinstance(field_schema, dict) else None
                return {declared} if isinstance(declared, str) else set(declared or [])

            if unit != "widget" and field_types(unit) != {"string"}:
                sys.exit(
                    f"{path}: <{tag}> x-state verb `{verb}` fold unit `{unit}` "
                    "must be a string"
                )
            if record:
                value = record["value"]
                schema = detail_properties[value]
                # An attribute record names the set of elements wearing it, so its
                # detail field is a list of ids however many the group allows —
                # nothing downstream has to ask which kind of group it came from.
                if record["kind"] == "attribute":
                    items = schema.get("items") if isinstance(schema, dict) else None
                    if not (
                        isinstance(schema, dict)
                        and schema.get("type") == "array"
                        and isinstance(items, dict)
                        and items.get("type") == "string"
                    ):
                        sys.exit(
                            f"{path}: <{tag}> x-state verb `{verb}` record value `{value}` "
                            "must be an array of strings"
                        )
                elif field_types(value) != {"string"}:
                    sys.exit(
                        f"{path}: <{tag}> x-state verb `{verb}` record value `{value}` "
                        "must be a string"
                    )
        retired = entry.get("x-retired-when")
        if retired is None:
            continue
        parent_entry = widgets[parent]
        parent_state = parent_entry.get("x-state", {})
        if retired not in parent_state:
            sys.exit(
                f"{path}: <{tag}> x-retired-when `{retired}` is invalid: "
                f"<{parent}> does not declare that x-state verb"
            )
        if parent_state[retired].get("unit", "widget") != "widget":
            sys.exit(
                f"{path}: <{tag}> x-retired-when `{retired}` must fold by widget"
            )
    return registry


def validate_registry_examples(registry: dict, source) -> dict:
    """Validate each independent catalog example where registry layers become one."""
    known = registry["$languages"]["names"]
    for tag, entry in registry.items():
        if not tag.startswith("cq-") or (example := entry.get("x-example")) is None:
            continue
        parser = _StructParser()
        parser.feed(example)
        parser.close()
        errors = fragment_errors(parser, registry, known)
        if parser.duplicate_ids:
            errors.append(
                f"duplicate ids (anchors need unique targets): {parser.duplicate_ids}"
            )
        if parser.reserved_ids:
            errors.append(reserved_ids_error(parser.reserved_ids))
        if errors:
            sys.exit(f"{source}: <{tag}> x-example is invalid: {errors[0]}")
    return registry


def read_registry(path: Path):
    """Read and validate one complete registry vocabulary."""
    registry = read_registry_entries(path)
    return None if registry is None else validate_registry(registry, path)


def load_registry(page_dir: Path):
    """The page's complete vendored vocabulary, or None before `page init`."""
    return read_registry(page_dir / "registry.json")


def incoming_registry(layers: list) -> dict:
    """The merged registry `page init` will vendor.

    Layers are additive at the top level. A later entry replaces the earlier
    entry whole; schemas never deep-merge, because a half-old, half-new contract
    is no layer's vocabulary.
    """
    merged = {}
    paths = []
    for layer in layers:
        path = layer / "registry.json"
        if not path.is_file():
            continue
        paths.append(path)
        merged.update(read_registry_entries(path))
    if not paths:
        sys.exit("the incoming layer has no registry.json")
    source = "merged registry (" + ", ".join(str(path) for path in paths) + ")"
    return validate_registry_examples(validate_registry(merged, source), source)


# ---------- the vocabulary stamp ----------
# The registry vendored into a page is also that page's statement of what its
# runtime speaks: $events names the event kinds and the fields each carries,
# x-state (per widget) each tag's verbs and detail schemas. Nothing else on disk
# says so. `page init` refuses a re-vendor that would retire or reshape a contract
# still present in the log.


def vocabulary_gaps(page_dir: Path, events: list, incoming: dict) -> list:
    """What the page's log says that the *incoming* layer no longer speaks:
    event kinds or fields with no $events entry, or actions whose sending tag,
    verb, or detail the incoming x-state contract rejects. Empty for a fresh page.
    Counted, because the number is the cost — each is a recorded event that
    would never replay again."""
    if not events:
        return []
    kind_fields = incoming["$events"]["kinds"]
    missing = {}
    for e in events:
        kind = e["kind"]
        if kind not in kind_fields:
            key = f"kind `{kind}`"
        elif fields := set(e) - EVENT_BASE_FIELDS - set(kind_fields[kind]):
            key = f"kind `{kind}` fields {sorted(fields)}"
        elif kind == "action" and (
            error := action_contract_error(page_dir, e, events, incoming)
        ):
            key = f"action contract: {error}"
        else:
            continue
        missing[key] = missing.get(key, 0) + 1
    return [f"{n} event{'s' if n != 1 else ''} of {key}" for key, n in sorted(missing.items())]


def widget_errors(cq_elements: list, registry: dict) -> list:
    """Validate parsed cq-* elements against the registry: schema over the
    attribute instance, x-parent nesting, and the x-content model."""
    errors = []
    # Containers ("items") admit exactly the tags that declare them as x-parent.
    children_of = {}
    for tag, entry in registry.items():
        if not tag.startswith("cq-"):
            continue
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
        instance = {}
        for name, value in rec["attrs"].items():
            prop = props.get(name)
            is_flag = isinstance(prop, dict) and prop.get("type") == "boolean"
            instance[name] = True if value in (None, "") and is_flag else (value or "")
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
        content = entry["x-content"]
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


def reference_errors(cq_elements: list, registry: dict, ids: set) -> list:
    """An attribute the registry marks as naming another element (x-refers) that names
    nothing this version holds. The reader follows it, so a typo is a reference to
    nowhere and the markup around it is perfectly well-formed — visible to them and to
    nobody else. Asked of the version rather than of a fragment: a reply's markup
    carries no page to check against, and one of its widgets pointing at the version
    beside it is exactly right."""
    return [
        f"<{rec['tag']}> (line {rec['line']}): {attr}=\"{target}\" names no element "
        "in this version"
        for rec in cq_elements
        for attr in registry.get(rec["tag"], {}).get("x-refers", [])
        if (target := rec["attrs"].get(attr)) and target not in ids
    ]


def language_errors(blocks: list, cq_elements: list, registry: dict, known: list) -> list:
    """A declared language the runtime won't honor. Nothing here is visible to the
    reviewer either way — a class in the wrong place and a misspelt language both render
    as an ordinary uncolored block — so the failure is routed to the one party who can
    still fix it, which is whoever wrote the word.

    One list answers both spellings, and it is the page's ($languages) rather than any
    widget's: a plain <pre><code class="language-…"> belongs to no widget at all, and a
    tag that takes the word says which of its attributes carries it (x-language) instead
    of being known here by name. The vendored bundle is built from the same list, so a
    page cannot be told a language its own layer doesn't speak.

    The list is indexed rather than tested: a layer naming none colors none, so a word
    declared to it is still one it can't honor, and the placement rule never depended on
    the list at all. A check whose two failures are both invisible on the page is the
    last one that should be able to pass by finding nothing to check against."""
    errors = []
    for block in blocks:
        where = f'class="language-{block["lang"]}" (line {block["line"]})'
        if (block["tag"], block["parent"]) != ("code", "pre"):
            errors.append(
                f"{where}: only <pre><code> is colored, found <{block['tag']}> in "
                f"<{block['parent'] or 'nothing'}> — move it, or use <cq-code language=…> "
                f"for a walkthrough"
            )
        elif block["lang"] not in known:
            errors.append(f"{where}: not a language this page's layer speaks — known: {known}")
    for rec in cq_elements:
        attr = (registry.get(rec["tag"]) or {}).get("x-language")
        word = rec["attrs"].get(attr) if attr else None
        if word is not None and word not in known:
            errors.append(
                f'<{rec["tag"]} {attr}="{word}"> (line {rec["line"]}): not a language '
                f"this page's layer speaks — known: {known}"
            )
    return errors


def suggestion_errors(suggestions: list, comment_ids: set) -> list:
    """What the registry's schema can't say about a suggestion: it holds at most
    one of each slot and at least one of them, it doesn't nest, and `resolves`
    names a comment that exists."""
    errors = []
    for s in suggestions:
        where = f"<cq-suggestion id={s['id']!r}> (line {s['line']})"
        if s["nested"]:
            errors.append(f"{where}: suggestions don't nest")
        if not s["slots"]:
            errors.append(
                f"{where}: needs a <cq-old> (what it replaces), a <cq-new> "
                f"(what it proposes), or both"
            )
        for slot in ("cq-old", "cq-new"):
            if s["slots"].count(slot) > 1:
                errors.append(f"{where}: carries {s['slots'].count(slot)} <{slot}> children, one at most")
        if s["resolves"] and s["resolves"] not in comment_ids:
            errors.append(
                f"{where}: resolves={s['resolves']!r} names no comment in the log"
            )
    return errors


def retirable_ids(suggestions: list, events: list, dropped: set, outcomes: dict) -> set:
    """Ids the previous version's suggestions let the next one drop, given what
    it actually dropped. A logged outcome settles a suggestion: accepting
    retires the markup it replaced, rejecting retires the proposal, and either
    retires the wrapper. A proposal no one has answered can still be withdrawn —
    nothing reviewed was kept — but only whole: the wrapper goes with the
    proposal inside it, so a version can't quietly keep an unanswered proposal
    as settled content, and not while an unresolved thread is anchored in it.

    The outcomes are replay's own (`decisions`, folded over the version these
    suggestions are on), so a decision a later version restated away settles
    nothing here either — replay hands the suggestion back as pending, and the
    slots stay needed."""
    anchored = anchored_ids(events)
    licensed = set()
    for s in suggestions:
        if not s["id"]:
            continue
        outcome = outcomes.get(s["id"])
        retires = {s["id"]} | (s["old_ids"] if outcome == "accept" else s["new_ids"])
        if outcome is None and (retires & anchored or not s["new_ids"] <= dropped):
            continue
        licensed |= retires
    return licensed


def action_subjects(event: dict, byid: dict, now: dict, registry: dict) -> list:
    """What an action was *about*, at the finest grain the vocabulary allows.

    An action names the widget that sent it, but on a container that is rarely
    the thing decided: a `move` names the board and carries {card, to, index}, a
    `choose` names the group and carries {option}. So the subjects are the parts
    of the widget its detail points at, minus containers (x-content "items") —
    the column a card landed in is where the decision *put* it, not what it was
    about, and holding a version to a column's contents would refuse it for
    adding an unrelated card. Where a detail names no part of the widget (an
    `edit` carries text, an `accept` carries nothing) the widget is its own
    subject.

    No verb is interpreted here. A detail value counts when it names an element
    *inside the widget that sent the action* — not merely an id the page has
    somewhere, which would let a literal like "approved" collide with an element
    that happens to be called that."""
    widget = event["widget"]
    parts = action_rests_on(event, now)[1:]
    leaves = [
        v for v in parts
        if registry.get(byid.get(v, {}).get("tag"), {}).get("x-content") != "items"
    ]
    return leaves or [widget]


def retractions(events: list, upto=None) -> dict:
    """id → the version that last took back what was recorded on it.

    A version declares a rewrite with `restated` in its markup and `note` records
    it here, on the note event itself, because the declaration belongs to the one
    version that rewrote the words and a retraction has to outlive it. Left in
    the markup, the version after would have to repeat the attribute to keep the
    retraction standing — the hand-copying this whole design exists to remove,
    and silently resurrecting a decision the moment someone forgot.
    `upto` windows the reading the way the JS twin's retractionFloors(upto)
    does — filter, then max — so an id retracted both early and late keeps its
    early floor inside the window instead of vanishing with the late one."""
    at = {}
    for e in events:
        if e["kind"] == "note" and (upto is None or e["version"] <= upto):
            for wid in e.get("restated", []):
                at[wid] = max(at.get(wid, 0), e["version"])
    return at


def action_rests_on(event: dict, spk: dict) -> list:
    """The runtime's restsOn, read the same way here: the sending widget plus
    every detail id it contains. This is the one key space for liveness — fold
    survival, retraction floors, and the earning of `restated` all go through
    it, in both runtimes — while `action_subjects` stays the words gate's finer,
    leaf-keyed view of the same containment. Two views, one containment test;
    a third keying would fork the JS/Python twin a third way."""
    widget = event["widget"]
    parts = [
        v
        for field in event["detail"].values()
        for v in (field if isinstance(field, list) else [field])
        if isinstance(v, str) and widget in spk.get(v, EMPTY).within
    ]
    return [widget, *parts]


# A verb with no declared record form (accept/reject — the honoring version
# retires the wrapper, so there is no state attribute to compare) has no facet.
NO_RECORD = object()


def state_fold(events: list, byid: dict, spk: dict, registry: dict, upto, floors: dict) -> dict:
    """unit id → (action, spec): the last surviving action per declared unit.

    The registry's x-state names each verb's fold unit — the widget itself for
    a verb absolute across the group (`choose` toggles every sibling, so
    per-option folding would double-count superseded picks), the detail-named
    element for one absolute per part (`move` places one card). Absolute
    placements are what make this a fold at all: the last surviving action per
    unit *is* the state, one linear scan, no replay simulation. Surviving means
    not under a retraction floor keyed on what the action rests on. `upto` is
    the consumer's window — the gate folds to the last published version (an
    action made later belongs to no comparison of these two files), a lag
    report to everything recorded (None)."""
    fold = {}
    for e in events:
        if e["kind"] != "action":
            continue
        if upto is not None and e["version"] > upto:
            continue
        rec = byid.get(e["widget"])
        spec = (registry.get(rec["tag"], {}).get("x-state") or {}).get(e["action"]) if rec else None
        if not spec:
            continue
        if any(floors.get(i, 0) > e["version"] for i in action_rests_on(e, spk)):
            continue
        unit = (
            e["widget"]
            if spec.get("unit", "widget") == "widget"
            else e["detail"].get(spec["unit"])
        )
        if isinstance(unit, str):
            fold[unit] = (e, spec)
    return fold


def markup_facet(unit: str, spec: dict, byid: dict, spk: dict):
    """What one version's markup shows for a unit's declared record form: every
    element inside it carrying the attribute, the declared container enclosing
    it, or its body's words — the empty list where the markup shows no pick.

    An attribute record is a set, never one element: a group taking several
    picks marks several options, and one shape for both is what lets the fold
    compare like with like whatever the group allows."""
    record = spec.get("record")
    if not record:
        return NO_RECORD
    if record["kind"] == "attribute":
        return sorted(
            oid for oid, orec in byid.items()
            if record["attr"] in orec["attrs"] and unit in spk.get(oid, EMPTY).within[:-1]
        )
    if record["kind"] == "position":
        enclosing = [
            i for i in spk.get(unit, EMPTY).within[:-1]
            if byid.get(i, {}).get("tag") == record["within"]
        ]
        return enclosing[-1] if enclosing else None
    return " ".join(spk.get(unit, EMPTY).words.split())  # "body"


def folded_facet(e: dict, spec: dict):
    """The state the folded action left: the detail field the record declares,
    collapsed the way `spoken` collapses where it compares against words, and
    sorted where it compares against a set of marked elements."""
    record = spec.get("record")
    if not record:
        return NO_RECORD
    value = e["detail"].get(record["value"])
    if record["kind"] == "body":
        return " ".join(str(value).split())
    if record["kind"] == "attribute":
        return sorted(value)
    return value


def page_fold(html: str, events: list, registry: dict, upto):
    """state_fold asked of one page: its elements, its words, and the log windowed
    to `upto` — one construction, so its readers (`record_lag`, and the readings
    `decisions` and `rewritten_bodies` give `review comment` and `version check`)
    cannot drift on floors or window. Returns (fold, byid, spk); the extras are
    the page readings the fold was built from, for a caller comparing it back
    against the markup."""
    parser = _StructParser()
    parser.feed(html)
    parser.close()
    byid = {r["attrs"]["id"]: r for r in parser.cq_elements if r["attrs"].get("id")}
    spk = spoken(html, registry)
    return state_fold(events, byid, spk, registry, upto, retractions(events, upto)), byid, spk


def rewritten_bodies(fold: dict) -> dict:
    """id → (verb, text): the reviewer's standing rewrite of each element whose
    registry entry records a verb as the body (x-state record kind "body"), as
    replay leaves it. The fold is state_fold's — the last surviving action per
    unit under the retraction floors — read here for the one record kind whose
    state is words rather than markup, so the passage reading can hold them
    where the authored body was."""
    return {
        unit: (e["action"], e["detail"][spec["record"]["value"]])
        for unit, (e, spec) in fold.items()
        if (spec.get("record") or {}).get("kind") == "body"
    }


def decisions(fold: dict, registry: dict) -> dict:
    """widget id → the accept/reject it stands under, read from the same fold every
    other consumer of declared state reads. Which verbs decide is the registry's word
    too: `x-retired-when` names the outcome under which an element leaves the page, so
    its values are the vocabulary's decision verbs — nothing here knows a widget or a
    verb by name, and a verb a later layer retires folds to nothing rather than
    standing on trust."""
    deciding = {e["x-retired-when"] for e in registry.values() if "x-retired-when" in e}
    return {unit: e["action"] for unit, (e, _) in fold.items() if e["action"] in deciding}


def record_lag(html: str, events: list, registry: dict) -> list:
    """Units whose markup lags the reviewer's standing state — the record debt a
    log-less reader would miss. Advice, never errors: a version is free to stay
    silent (replay resolves it), but SKILL.md's record obligation needs a
    feedback loop, and a finished review's final version is the page that has
    to read right without the log."""
    if not registry:
        return []
    fold, byid, spk = page_fold(html, events, registry, None)
    lag = []
    for unit in sorted(fold):
        e, spec = fold[unit]
        if unit not in byid:
            continue
        f_cur = markup_facet(unit, spec, byid, spk)
        if f_cur is NO_RECORD or f_cur == folded_facet(e, spec):
            continue
        lag.append(
            f"`{unit}`: the log records {e['action']} → {folded_facet(e, spec)!r}; "
            f"the markup still shows {f_cur!r}"
        )
    return lag


def restatement_errors(cur, prev, was: dict, now: dict, events: list, prev_num: int, registry: dict) -> list:
    """The other half of the id-survival rule. That one keeps a republish from
    dropping the anchors a reviewer hung on the page; this one keeps it from
    dropping the decisions they recorded on it. CLAUDE.md carries why the log
    outranks the markup and what that cost.

    The runtime replays every action onto every later version, so a version
    cannot revise what a reviewer acted on: replay would paint their recorded
    state back over the revision and the new words would reach nobody. A version
    that means to revise says so — `restated` on what it rewrote — and one that
    changes those words in silence is refused here. An unearned `restated` is an
    error too: a decision thrown away for nothing, and, left unchecked, the
    one-word ritual that would make this gate meaningless.

    The comparison is the words each version says (`spoken`), because words are
    what a decision is about. Re-indenting a draft, marking the picked option
    `chosen`, or relocating a card the reviewer already moved is not a revision,
    and neither is writing their own edit back — a version that says what they
    said is agreeing with them.

    Words are one divergence kind; declared state is the other. For each verb
    the registry declares (x-state), the fold gives the reviewer's standing
    state per unit, and a version whose markup actively changes that unit's
    record away from both the previous version's and the fold is refused the
    same way a silent rewrite of words is. Writing the folded state is the
    state-level echo (honoring); re-emitting the previous version's state is
    blessed silence, which replay resolves; a unit with no surviving folded
    action is exempt — never decided, or retracted back to the author. And
    `restated` is earned by either divergence kind: a words-unchanged
    relocation earns it at the unit even though no leaf's words moved."""
    errors = []
    declared = cur.restated
    # Retractions up to prev — never this version's own, which is what it is
    # here to declare, so re-checking a published version reaches the same
    # verdict as checking it did.
    taken_back = retractions(events, prev_num)
    byid = {r["attrs"]["id"]: r for r in cur.cq_elements if r["attrs"].get("id")}

    decided = {}  # subject id → the actions resting on it
    for e in events:
        if e["kind"] != "action":
            continue
        # One key space for liveness: an action is dead when any id it rests on
        # was floored — replay skips it by this same containment, so a finer,
        # leaf-keyed floor here would keep alive a decision the browser has
        # already dropped (a group-level retraction never names the option the
        # pick rested on, and the pick must die with the group all the same).
        if any(taken_back.get(i, 0) > e["version"] for i in action_rests_on(e, now)):
            continue
        for subject in action_subjects(e, byid, now, registry):
            # Only what the reviewer had recorded by the time they were looking
            # at prev.
            if subject in was and e["version"] <= prev_num:
                decided.setdefault(subject, []).append(e)

    # The state gate, beside the words gate: one gate, two divergence kinds.
    prev_byid = {r["attrs"]["id"]: r for r in prev.cq_elements if r["attrs"].get("id")}
    fold = state_fold(events, byid, now, registry, prev_num, taken_back)
    facet_earned = set()
    for unit in sorted(fold):
        e, spec = fold[unit]
        rec = byid.get(unit)
        # A unit either version lacks is id-survival's business, not this gate's.
        if rec is None or unit not in prev_byid:
            continue
        f_cur = markup_facet(unit, spec, byid, now)
        f_prev = markup_facet(unit, spec, prev_byid, was)
        if f_cur is NO_RECORD or f_cur == f_prev:
            continue  # no record form, or no active change — replay resolves silence
        f_fold = folded_facet(e, spec)
        if f_cur == f_fold:
            continue  # writing the folded state is honoring: the state-level echo
        if unit in declared:
            facet_earned.add(unit)
            continue
        where = f"<{rec['tag']} id={unit!r}> (line {rec['line']})"
        errors.append(
            f"{where}: its state changed under the reviewer's decision — the markup "
            f"shows {f_cur!r} where their {e['action']} (on v{e.get('version', 0)}) "
            f"left {f_fold!r}. Their decision is what the page shows, so this state "
            f"would never reach them — add `restated` to retract it and ask again, "
            f"or leave it as v{prev_num} had it."
        )

    for sid, rec in sorted(byid.items()):
        live, restated = decided.get(sid, []), sid in declared
        # A version that writes back what the reviewer themselves recorded is
        # agreeing with them, not overruling them — an honored `edit` is the
        # commonest and most correct thing an author does with a draft, and the
        # gate has to stay quiet for it or it fires on nearly every version and
        # teaches authors to reach for `restated` by reflex. No verb is special-
        # cased: it is enough that the words on the page are words the reviewer
        # sent.
        echoed = {
            " ".join(str(v).split())
            for e in live
            for v in e["detail"].values()
            if isinstance(v, str)
        }
        said = now.get(sid, EMPTY).words
        changed = sid in was and said != was[sid].words and said not in echoed
        where = f"<{rec['tag']} id={sid!r}> (line {rec['line']})"
        # `restated` is earned by either divergence kind — words on the leaf, or
        # declared state at the unit — else a words-unchanged relocation would
        # be refused both with the attribute and without it.
        if restated and not ((live and changed) or sid in facet_earned):
            # An already-retracted widget is the case an author lands on by being
            # careful — carrying the attribute forward the way state used to have
            # to be carried — so it gets its own answer rather than the
            # never-decided one, which would read as if the reviewer had done
            # nothing.
            if sid in taken_back:
                errors.append(
                    f"{where}: restated, but v{taken_back[sid]} already took that "
                    f"back — a retraction is recorded when it is published and holds "
                    f"without being repeated. Drop the attribute."
                )
            else:
                why = (
                    f"its words are unchanged since v{prev_num}"
                    if live
                    else "the reviewer has recorded nothing on it"
                )
                errors.append(
                    f"{where}: restated, but there is nothing to retract — {why}. "
                    f"Drop the attribute; `restated` discards their decision."
                )
        elif changed and live and not restated:
            did = ", ".join(f"{e['action']} on v{e.get('version')}" for e in live[-3:])
            errors.append(
                f"{where}: its words changed, and the reviewer has already acted "
                f"on it ({did}). Their decision is what the page shows, so these "
                f"words would never reach them — add `restated` to retract it and "
                f"ask again, or leave the text as v{prev_num} had it."
            )
    return errors


def structure_errors(parser: _StructParser) -> list:
    """A fed parser's structural complaints, plus the tags it was left holding
    open at the end of its input."""
    errors = list(parser.errors)
    leftover = [(t, ln) for t, ln, _ in parser.stack if t not in OPTIONAL_END]
    if leftover:
        errors.append("unclosed tags: " + ", ".join(f"<{t}> (line {ln})" for t, ln in leftover))
    return errors


def fragment_errors(parser: _StructParser, registry: dict, known: list) -> list:
    """Structural + registry validation of a markup fragment (an agent reply
    carrying widgets): the discussion-side analog of `version check`. The language
    check comes along because the schema stopped carrying the list: a reply's
    <cq-code language=…> is colored by the same tokenizer a version's is, and nothing
    else would now refuse it a word that tokenizer doesn't know."""
    return (
        structure_errors(parser)
        + widget_errors(parser.cq_elements, registry)
        + language_errors(parser.language_blocks, parser.cq_elements, registry, known)
    )


def cmd_check(page_dir: Path, version, render: bool = False) -> int:
    versions = list_versions(page_dir)
    if not versions:
        sys.exit(f"no versions in {page_dir / 'versions'}; write versions/v1.html first")
    selected = version if version is not None else versions[-1]
    if selected not in versions:
        sys.exit(f"no v{version}.html in {page_dir / 'versions'}")
    name = version_name(selected)
    html = version_path(page_dir, selected).read_text(encoding="utf-8")

    errors = []

    for missing in [f for f in VENDORED_FILES if not (page_dir / f).exists()]:
        errors.append(
            f"{missing} missing from the page directory; run `colloquy page init` "
            "to vendor the layer"
        )

    parser = _StructParser()
    parser.feed(html)
    parser.close()
    errors.extend(structure_errors(parser))

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
    if parser.reserved_ids:
        errors.append(reserved_ids_error(parser.reserved_ids))

    registry = load_registry(page_dir)
    if registry is not None:
        errors.extend(widget_errors(parser.cq_elements, registry))
        errors.extend(reference_errors(parser.cq_elements, registry, parser.ids))
        errors.extend(
            language_errors(
                parser.language_blocks,
                parser.cq_elements,
                registry,
                registry["$languages"]["names"],
            )
        )
        for tag, entry in registry.items():
            if not tag.startswith("cq-"):
                continue
            if entry["x-upgrade"] and not (page_dir / "widgets" / f"{tag}.js").is_file():
                errors.append(
                    f"registry marks <{tag}> as upgraded but widgets/{tag}.js "
                    f"isn't vendored; run `colloquy page init`"
                )

    events = read_events(page_dir)
    errors.extend(
        suggestion_errors(
            parser.suggestions, {e["id"] for e in events if e["kind"] == "comment"}
        )
    )

    # "Previous" is the last *published* version before this one — the page the
    # reviewer was actually looking at, which is what `review comment` anchors
    # against and what the browser diffs against. The file before it on disk may be an
    # abandoned draft no note ever released: ids nobody saw, words nobody could
    # have decided on. The first published version has no predecessor, so it
    # stands against an empty one: nothing of its can have been dropped and
    # nothing decided, which is exactly what makes a `restated` on it an error
    # like any other unearned one.
    noted = {e["version"] for e in events if e["kind"] == "note"}
    earlier = [candidate for candidate in versions if candidate < selected and candidate in noted]
    prev, prev_num, was = _StructParser(), 0, {}
    prev.close()
    if earlier:
        prev_num = earlier[-1]
        prev_name = version_name(prev_num)
        prev_html = version_path(page_dir, prev_num).read_text(encoding="utf-8")
        prev = _StructParser()
        prev.feed(prev_html)
        prev.close()
        was = spoken(prev_html, registry or {})
        # An id may retire when the log has settled what holds it; everything
        # else must survive, or the anchors on it break.
        gone = prev.ids - parser.ids
        fold, _, _ = page_fold(prev_html, events, registry or {}, None)
        dropped = sorted(
            gone - retirable_ids(prev.suggestions, events, gone, decisions(fold, registry or {}))
        )
        if dropped:
            errors.append(
                f"ids present in {prev_name} but dropped in {name} "
                f"(anchors on them will break): {dropped}"
            )
    # And the decisions recorded on the ids that stayed.
    errors.extend(
        restatement_errors(
            parser, prev, was, spoken(html, registry or {}), events, prev_num, registry or {}
        )
    )

    # Thread markup is frozen in the log and rendered into the panel; a page id
    # colliding with one would steal its action replays (see thread_widget_ids).
    taken = sorted(parser.ids & thread_widget_ids(events))
    if taken:
        errors.append(f"ids already taken by widget markup in a reply: {taken}")

    # A /media/ reference the directory can't answer renders as a broken image.
    # The render gate would catch it as a 404, but that runs once a page; this
    # runs on every version, and a missing file is as deterministic as a missing
    # id.
    for ref in sorted(parser.media_refs):
        if not (page_dir / ref.lstrip("/")).is_file():
            errors.append(
                f"{ref} isn't in the page directory; `colloquy page media` puts it there"
            )

    theme_css = (page_dir / "theme.css").read_text(encoding="utf-8") if (page_dir / "theme.css").exists() else ""
    errors.extend(css_syntax_errors(parser.css, "page <style>"))
    for number, style in enumerate(parser.inline_styles, 1):
        errors.extend(css_syntax_errors(style, f"inline style #{number}", block=True))
    errors.extend(css_syntax_errors(theme_css, "theme.css"))
    column = _column_width(parser.css, theme_css)
    errors.extend(_overwide_elements(parser, column))

    if errors:
        print(f"✗ {name}: {len(errors)} issue(s)", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(
        f"✓ {name}: parses, widgets validate, one module script + theme link, "
        f"ids and decisions carried over, nothing overflows the {column}px column"
    )
    # Advice, never a gate: silence is blessed and replay resolves it, but a
    # log-less reader (a printout, a transcript's audience) sees only the markup,
    # so say where it lags the log. Loudest at the end of a review — the final
    # version is the page that must read right without the log.
    for line in record_lag(html, events, registry or {}):
        print(f"  · record behind the log — {line}")
    # Render only what passed the static half: an unparseable page would drown
    # the browser's report in consequences of what the lint already named.
    return render_check(page_dir, selected) if render else 0


# ---------- check --render: the browser half of the gate ----------

RENDER_VIEWPORT = {"width": 1200, "height": 900}


# Words the page shows that no reviewer can select, and so no comment can be
# anchored on. A widget has two ways to leave them there, neither of which a
# static lint can see, and a page-local widget is where both keep happening.
#
# It can paint them: `content: attr(label)` puts a heading on screen and in no
# text node, so a selection can't cover it. The runtime says the attributes the
# registry marks x-says, and a widget's module says the rest (a chip row, a
# heading that doubles as a list's accessible name); either way, none of an
# element's own attribute values should still be reaching the reader as
# generated content.
#
# Or it can leave them under .cq-ui with nothing said about whose words they are.
# That class is the chrome face, a look — reaching for it as a general "this is
# chrome" marker is how a reviewer ends up unable to comment on a heading they can
# see. The declaration is made where the label is written: data-cq-said for the page
# speaking, which the anchor pass reads over the box around it, data-cq-offer for a
# thing to work. So inside a widget, every word under .cq-ui has to be declared the
# page's, be a control's own label, or be the line the paint pass writes to say how
# many comments a block carries: that one is about the document rather than of it,
# which is the same reason it wears .cq-ui at all, and it lands inside a widget
# whenever a comment does. The comment panel is out of scope: a widget in a reply is
# markup frozen in the event log, not the document.
#
# And a declared label inside a form control is out of reach whatever it is marked:
# Chrome starts no pointer selection inside one, which is why `offer` builds a press
# as a span wearing role="button". A widget reaching for <button> anyway is the one
# mistake the marker cannot fix, so it is reported separately and says why.
UNREACHABLE_WORDS = """() => {
    const found = [];
    const at = el => `<${el.tagName.toLowerCase()}${el.id ? ' id=' + el.id : ''}>`;
    for (const el of document.querySelectorAll('*')) {
        if (!el.tagName.startsWith('CQ-')) continue;
        const shown = ['::before', '::after']
            .map(w => getComputedStyle(el, w).content)
            .filter(c => c && c.startsWith('"'));
        for (const { name, value } of el.attributes)
            if (value.length > 1 && shown.some(c => c.includes(value)))
                found.push(`${at(el)} paints ${name}="${value}" rather than saying it`);
    }
    // A widget's chrome is the .cq-ui inside a cq-* element; the runtime's own
    // layer is appended to body and sits inside none of them.
    const widget = el => { for (let a = el; a; a = a.parentElement)
                               if (a.tagName.startsWith('CQ-')) return a; };
    // The anchor pass's own rule: the nearest element that answers wins.
    const speaks = el => Boolean(el.closest('.cq-ui, [data-cq-said]')?.matches('[data-cq-said]'));
    const FORM = 'button, textarea, input, select';
    // Where a control's own words may sit: the control a widget declared (data-cq-offer,
    // asked instead of the role it wears, because cq-tabs overwrites `offer`'s
    // role="button" with "tab" and a Δ badge in a tab then read as a heading somebody
    // hid while the identical badge in a settled row read as chrome), or a native
    // control. `label` is among those because a radio and a checkbox have nowhere else
    // to put their words: a button holds its own, an input cannot, and HTML's answer is
    // an element beside it. cq-shot's flip is radios, so that it keeps working in a page
    // whose script is gone.
    const CONTROL = `${FORM}, label, [data-cq-offer]`;
    const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
        const el = n.parentElement;
        if (!n.data.trim() || !el.closest('.cq-ui') || !widget(el)) continue;
        if (speaks(el) || el.closest(`${CONTROL}, .cq-mark-note`)) continue;
        found.push(`${at(widget(el))} puts ${JSON.stringify(n.data.trim().slice(0, 40))} `
                   + `under .cq-ui, where no comment can reach it`);
    }
    // FORM rather than CONTROL: a <label>'s words select like any others, and a widget
    // that declared a box a control has said nothing about what element it is.
    for (const el of document.querySelectorAll('[data-cq-said]')) {
        if (!el.closest(FORM) || !widget(el)) continue;
        found.push(`${at(widget(el))} says ${JSON.stringify(el.textContent.trim().slice(0, 40))} `
                   + `inside a form control, where no selection can reach it`);
    }
    return [...new Set(found)];
}"""


# A version whose markup asserts a state the log replays over — `chosen` moved
# to another option, a card re-authored into a column the reviewer dragged it
# out of. Replay resolves it in the reviewer's favor, so what needs reporting is
# the author's intent going down silently. The static half can't say which
# attribute is a verb's state — that lives in each widget's applyAction, and a
# table here would be the second copy the registry exists to prevent — so the
# browser compares: applyActions records the ids replay wrote on the body
# (data-cq-replay-wrote), and this pass asks which of them the author also
# changed since the previous version, reading both files with the runtime's own
# shallowSigs. An authored change replay then overrode is a conflict; an
# unchanged id is the initial condition the log is supposed to outrank. For the
# message, each conflicting id is laid at the door of the widget whose replay
# wrote it — its nearest ancestor with an applyAction.
REPLAY_OVERRIDES = """async () => {
    const ids = (document.body.dataset.cqReplayWrote ?? '').split(' ').filter(Boolean);
    if (!ids.length) return [];
    const current = Number(location.pathname.match(/\\/versions\\/v([1-9]\\d*)\\.html$/)[1]);
    const versions = (await (await fetch('/api/state')).json()).versions;
    const i = versions.indexOf(current);
    if (i <= 0) return [];
    const { shallowSigs } = await import('/colloquy.js');
    const sigs = async (v) => shallowSigs(new DOMParser().parseFromString(
        await (await fetch(`/versions/v${v}.html`)).text(), 'text/html').body);
    const cur = await sigs(current), prev = await sigs(versions[i - 1]);
    const groups = new Map();
    for (const id of ids) {
        if ((cur.get(id) ?? '') === (prev.get(id) ?? '')) continue;
        let widget = null;
        for (let a = document.getElementById(id); a; a = a.parentElement)
            if (a.applyAction) { widget = a; break; }
        const key = widget ? `<${widget.tagName.toLowerCase()} id=${widget.id}>` : `id=${id}`;
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(id);
    }
    return [...groups].map(([who, asserted]) =>
        `${who} authors state the log replays over (${asserted.join(', ')}): `
        + `the reviewer's decision stands — either carry it in the markup, or `
        + `rewrite the passage and declare restated`);
}"""


# What the page says, and whether each run of it is showing. Read once in each medium
# and compared by walk order: media change what is displayed, never the DOM, so the nth
# run on screen is the nth run on paper. What a page says has to survive being printed,
# and the ways it can fail to are all silent — a widget's control that is a statement as
# well as a thing to press (the pick mark, which took the only words naming the option a
# group carried), a rule of the page's own that hides its content in print. The whole
# page rather than the widgets in it, because a reviewer's printout losing a paragraph is
# no better than losing a widget's word. Declared offers are excluded because paper has
# nothing to press; the runtime's own layer is excluded because it was never the
# document, and a widget rendered inside it (a reply's markup) is the panel's, not the
# page's.
PAPER_WORDS = """() => {
    const out = [];
    const at = el => { const named = el.closest('[id]');
                       return named ? `<${named.tagName.toLowerCase()} id=${named.id}>`
                                    : `<${el.tagName.toLowerCase()}>`; };
    const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
        const el = n.parentElement;
        if (!n.data.trim() || el.closest('.cq-chrome, [data-cq-offer]')) continue;
        out.push({ at: at(el), text: n.data.trim().slice(0, 40),
                   shown: el.checkVisibility() });
    }
    return out;
}"""


# Words the page draws in the same place as other words. A copy went out with a settled
# group's cards laid across the heading above them — the cards kept the collapsed
# padding, which is the room the group is laid out in — and the reviewer saw it in the
# first second while every assertion passed: the words were all present, all shown, and
# all of a usable size. They were in the same place, and nothing was asking about place.
#
# Boxes rather than a hit test, which is the other way to ask: a press landing on the
# wrong element is a different fault with its own test, and the medium this has to hold
# up in is the copy, where there is nothing left to press. Text against text, because
# text over a background, a border, or a picture is how a page is built.
#
# A pair where one element contains the other is skipped: a paragraph and the <em>
# inside it are one run of words that the flow lays out together, and their boxes
# overlap by construction. Two pixels of slack, since a line box carries its leading and
# adjacent blocks can round into each other by a hair. The runtime's layer is skipped
# too: it floats over the document on purpose, and where that costs the reviewer a press
# it is the hit test that says so.
COVERED_WORDS = """() => {
    const runs = [];
    const at = el => { const named = el.closest('[id]');
                       return named ? `<${named.tagName.toLowerCase()} id=${named.id}>`
                                    : `<${el.tagName.toLowerCase()}>`; };
    const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
        const el = n.parentElement;
        if (!n.data.trim() || el.closest('.cq-chrome')) continue;
        if (!el.checkVisibility({ visibilityProperty: true, opacityProperty: true })) continue;
        const range = document.createRange();
        range.selectNodeContents(n);
        for (const box of range.getClientRects())
            if (box.width > 1 && box.height > 1)
                runs.push({ el, box, text: n.data.trim().slice(0, 40) });
    }
    const found = [];
    for (let i = 0; i < runs.length; i++) for (let j = i + 1; j < runs.length; j++) {
        const a = runs[i], b = runs[j];
        if (a.el === b.el || a.el.contains(b.el) || b.el.contains(a.el)) continue;
        const across = Math.min(a.box.right, b.box.right) - Math.max(a.box.left, b.box.left);
        const down = Math.min(a.box.bottom, b.box.bottom) - Math.max(a.box.top, b.box.top);
        if (across <= 2 || down <= 2) continue;
        found.push(`${at(a.el)} draws ${JSON.stringify(a.text)} in the same place as `
                   + `${at(b.el)}'s ${JSON.stringify(b.text)}`);
    }
    return [...new Set(found)];
}"""


def render_version(browser, url: str) -> list:
    """Everything wrong with a served version that only a browser can see: a
    console or page error, a request that 404s, a fail-soft error box, an upgrade
    module that never defines its declared element, a widget upgraded into a box
    of no usable size, the page scrolling sideways, words the reviewer can read
    and can't select, words drawn on top of other words — each
    in both color schemes, because the dark theme is real CSS nobody otherwise
    renders — plus, in one scheme, a version that authors widget state the log
    replays over (replay isn't CSS) and, on paper, words the page drops that it
    says on screen, or draws over each other (print is scheme-blind).
    Returns human-readable failures; [] is a pass.

    One implementation with two callers — `version check --render` on the page an agent
    just wrote, and the render suite on the shipped examples
    (tests/test_render.py) — so the gate and the suite hold one set of
    invariants. `browser` is a live Playwright browser; nothing here imports
    playwright at module level, so the module stays importable without it."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    def in_scheme(scheme):
        page = browser.new_page(viewport=RENDER_VIEWPORT, color_scheme=scheme)
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        # The console's own word for a bad response is "Failed to load resource",
        # which names nothing; carry the status and URL so a failure says what
        # went missing.
        page.on("response", lambda r: errors.append(f"{r.status} {r.url}") if r.status >= 400 else None)
        try:
            page.goto(url, wait_until="networkidle")
            page.wait_for_function("() => document.querySelector('.cq-banner') !== null")
        except PlaywrightTimeout:
            page.close()
            return [
                f"[{scheme}] the runtime never injected its banner — "
                + ("; ".join(errors) or "and no console error explains why")
            ]
        # Every reading below is of a settled page. The widget layer writes half the
        # document, so a box measured while it is still drawing belongs to no version of
        # the page — which is the stamp `version export` waits on for the same reason.
        try:
            page.wait_for_function("() => document.body.dataset.cqUpgraded === '1'")
        except PlaywrightTimeout:
            page.close()
            return [
                f"[{scheme}] the widget layer never finished upgrading — "
                + ("; ".join(errors) or "and no console error explains why")
            ]
        failsoft = page.evaluate(
            "[...document.querySelectorAll('.cq-error')].map(e => e.textContent.trim())"
        )
        missing_upgrades = page.evaluate("""() => fetch('/registry.json')
            .then(r => r.json())
            .then(registry => Object.entries(registry)
                .filter(([tag, entry]) => tag.startsWith('cq-')
                    && entry['x-upgrade'] && !customElements.get(tag))
                .map(([tag]) => tag))""")
        # [hidden] needs its own exclusion: hidden="until-found" (what a closed
        # tab wears) resolves to content-visibility, which checkVisibility
        # reports as visible while the box measures zero. That collapse is the
        # point of a closed tab; the collapse being hunted here is the one
        # nothing asked for.
        tiny = page.evaluate("""() => [...document.querySelectorAll('*')]
            .filter(el => el.tagName.toLowerCase().startsWith('cq-')
                       && el.textContent.trim()
                       && el.checkVisibility()
                       && !el.closest('[hidden]'))
            .map(el => ({ tag: el.tagName.toLowerCase(), id: el.id,
                          w: Math.round(el.getBoundingClientRect().width),
                          h: Math.round(el.getBoundingClientRect().height) }))
            .filter(box => box.w < 40 || box.h < 10)""")
        overflow = page.evaluate("document.body.scrollWidth - document.body.clientWidth")
        unreachable = page.evaluate(UNREACHABLE_WORDS)
        covered = page.evaluate(COVERED_WORDS)
        # Replay is scheme-blind, so one scheme's reading covers both. The wait
        # is for the runtime's own caught-up stamp: reading the replay's record
        # mid-replay would miss whatever hadn't landed yet.
        conflicts = []
        if scheme == "light":
            n_actions = page.evaluate(
                "fetch('/api/state').then(r => r.json())"
                ".then(s => s.events.filter(e => e.kind === 'action').length)"
            )
            if n_actions:
                try:
                    page.wait_for_function(
                        f"() => Number(document.body.dataset.cqApplied ?? -1) >= {n_actions}"
                    )
                    conflicts = page.evaluate(REPLAY_OVERRIDES)
                except PlaywrightTimeout:
                    conflicts = [
                        f"the runtime never finished replaying the log ({n_actions} action(s))"
                    ]
        # Last, and in one scheme: paper has no color scheme, and the medium has to be
        # put back before anything else reads a box.
        on_paper = []
        if scheme == "light":
            screen = page.evaluate(PAPER_WORDS)
            page.emulate_media(media="print")
            paper = page.evaluate(PAPER_WORDS)
            # Paper is laid out by rules no other medium runs, and it is the medium
            # nobody looks at, so the overlap reading is taken here too while it holds.
            on_paper = [f"[print] {c}" for c in page.evaluate(COVERED_WORDS)]
            page.emulate_media(media="screen")
            # Paired on the words as well as the position: the page is live, and a poll
            # landing between the two readings would otherwise shift one against the
            # other and report whatever happened to line up. A pair that disagrees says
            # nothing, which is the right way round — the next run reads it again.
            on_paper += [
                f"[print] {s['at']} drops {json.dumps(s['text'])}, which it says on screen"
                for s, p in zip(screen, paper)
                if s["text"] == p["text"] and s["shown"] and not p["shown"]
            ]
        page.close()
        found = [f"[{scheme}] console: {e}" for e in errors]
        found += [f"[{scheme}] a widget failed soft: {t}" for t in failsoft]
        if missing_upgrades:
            found.append(
                f"[{scheme}] upgraded widgets did not define their elements: "
                + ", ".join(f"<{tag}>" for tag in missing_upgrades)
            )
        if tiny:
            found.append(f"[{scheme}] widgets rendered with no usable size: {json.dumps(tiny)}")
        if overflow > 0:
            found.append(f"[{scheme}] the page scrolls sideways by {overflow}px")
        found += [f"[{scheme}] {w}" for w in unreachable]
        found += [f"[{scheme}] {c}" for c in covered]
        found += [f"[{scheme}] {c}" for c in conflicts]
        found += on_paper
        return found

    return [*in_scheme("light"), *in_scheme("dark")]


@contextlib.contextmanager
def preview_server(page_dir: Path, version: int):
    """The page directory on a loopback port, exposing versions up to this one, for
    the length of a `with`. Two callers need a browser to see a version the reviewer
    may not have (`version check --render` before its note lands, `version export`
    on any published one), and the preview window is what lets them: the server's
    own liveness rule is the reviewer's, and this widens it for exactly one process."""
    # Its own key, not the page's: this server is loopback-only and lives for the
    # length of a `with`, so it neither needs nor should mint the page's access.
    token = secrets.token_urlsafe(16)
    httpd = ThreadingHTTPServer(
        ("127.0.0.1", 0), handler_for(page_dir, token, preview_upto=version)
    )
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/versions/{version_name(version)}?t={token}"
    finally:
        httpd.shutdown()


def render_check(page_dir: Path, version: int) -> int:
    """Serve the page directory to the machine's installed Chrome and run the
    render invariants on this version.

    Playwright is the gate's own extra, not the script's: declaring it in the
    PEP 723 header would put its wheel in every `server run`, `review wait`, and
    `version publish`, so the import happens here and its absence names the
    invocation that supplies it. Chrome is part of this gate: if it cannot
    launch, the gate fails."""
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "version check --render needs Playwright; run it as\n"
            "  colloquy version check <page> --render\n"
            "or, from a checkout,\n"
            "  plugins/colloquy/bin/colloquy version check <page> --render",
            file=sys.stderr,
        )
        return 1
    name = version_name(version)
    with preview_server(page_dir, version) as url:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel="chrome")
            except PlaywrightError as error:
                print(
                    "✗ render check failed — Chrome did not launch: "
                    + str(error).strip().splitlines()[0],
                    file=sys.stderr,
                )
                return 1
            try:
                failures = render_version(browser, url)
            finally:
                browser.close()
    if failures:
        print(f"✗ {name}: renders broken — {len(failures)} issue(s)", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print(
        f"✓ {name}: renders clean in Chrome, light and dark — no console errors, "
        "every widget takes space, no words on top of other words, no sideways scroll"
    )
    return 0


# ---------- export: the page as one file ----------

# What a standalone copy drops. Scripts go because there is no server behind a file
# and nothing left for them to reach; the runtime's own layer goes with them, since a
# comment box that swallows what you type and a banner claiming someone is listening
# are worse than no chrome at all — a copy that lies about being a review. What stays
# is everything the widgets built, the controls they injected among it: a control whose
# state the browser owns still works with no script running, which is why a `cq-shot`
# flips on radios.
#
# `cq-copy` is the medium, declared the way `@media print` is and read the same way —
# by the theme, per widget. A widget whose control needed a handler puts the affordance
# behind a guard this class fails, so a copy gets the page its markup describes; one
# whose control the browser owns has no guard and keeps working. That is why no widget
# is named here: this marks the medium, and the widgets answer for themselves.
BAKE = """() => {
    document.documentElement.classList.add('cq-copy');
    document.querySelectorAll('script, .cq-chrome').forEach(el => el.remove());
    // hidden="until-found" is the page saying "collapsed, but the reader can still
    // get here" — a tab's inactive panel, a settled group's cards. In a copy the
    // control that would get them there is inert, so the attribute is a promise
    // nothing can keep, and it takes the collapsed element's layout down with it:
    // the theme zeroes a hidden card's padding, which is the room its chips are
    // positioned into. Dropping it opens the element on the terms it was authored
    // with, which is the layout the theme's live-page guard was withholding anyway.
    document.querySelectorAll('[hidden="until-found"]')
        .forEach(el => el.removeAttribute('hidden'));
    return document.documentElement.outerHTML;
}"""


def inline_assets(html: str, page_dir: Path) -> str:
    """Fold the served assets into the markup. The theme's link becomes the stylesheet
    itself and each image becomes its own bytes, which is everything the document still
    reaches the server for: the runtime's stylesheet arrived as a `<style>` in the DOM,
    the widget modules were imports rather than elements, and a `cq-ref`'s link was
    always somewhere else."""
    theme = (page_dir / "theme.css").read_text(encoding="utf-8")
    html, n = re.subn(r'<link[^>]+href="/theme\.css"[^>]*>', lambda _: f"<style>{theme}</style>", html, count=1)
    if not n:
        sys.exit("the rendered page carried no /theme.css link — it would open unstyled")
    for src in sorted(set(re.findall(r"/" + MEDIA_DIR + r"/[a-f0-9]{16}\.[a-z]+", html))):
        file = page_dir / src.lstrip("/")
        data = base64.b64encode(file.read_bytes()).decode()
        html = html.replace(src, f"data:{MEDIA_TYPES[file.suffix]};base64,{data}")
    return html


def export_page(browser, url: str, page_dir: Path) -> str:
    """The served version at `url`, copied as one self-contained document.

    One implementation with two callers, as `render_version` is: `version export`
    supplies a browser of its own, and the suite drives this over the shipped
    examples with the one it already has, so the copy a reviewer gets and the copy
    the suite asserts on cannot drift.

    The reviewer's decisions come with it. Replay is what puts them on the page, so
    this waits for the runtime's caught-up stamp exactly as the gate does, and a page
    whose board was rearranged copies rearranged."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    page = browser.new_page(viewport=RENDER_VIEWPORT)
    try:
        page.goto(url, wait_until="networkidle")
        try:
            page.wait_for_function("() => document.body.dataset.cqUpgraded === '1'")
            n_actions = len([e for e in read_events(page_dir) if e["kind"] == "action"])
            if n_actions:
                page.wait_for_function(
                    f"() => Number(document.body.dataset.cqApplied ?? -1) >= {n_actions}"
                )
        except PlaywrightTimeout:
            sys.exit(
                f"{url.rsplit('/', 1)[-1]} never finished upgrading in the browser, so a copy "
                "would be half-drawn. `colloquy version check <page> --render` says what "
                "is wrong with it."
            )
        return inline_assets(page.evaluate(BAKE), page_dir)
    finally:
        page.close()


def cmd_export(page_dir: Path, out: Path, version) -> int:
    """One published version as a standalone HTML file.

    The copy is the page as the browser finished drawing it, which is the only way to
    get one: half the document is written by the widget layer at runtime, a mermaid
    diagram becomes an SVG only once mermaid has drawn it, and a code block is colored
    by the vendored tokenizer in the page rather than by anything that can read the
    file. So Chrome is not an optimisation here and no `x-` key exempts a widget from
    it; without a browser there is nothing to copy at all."""
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit(
            "export needs Playwright; run it as\n"
            "  colloquy version export <page> -o <file>\n"
            "or, from a checkout,\n"
            "  plugins/colloquy/bin/colloquy version export <page> -o <file>"
        )
    published = published_versions(page_dir, read_events(page_dir))
    if not published:
        sys.exit(
            f"{page_dir} has no published version to export; "
            "run `colloquy version publish` first"
        )
    version = version if version else published[-1]
    if version not in published:
        sys.exit(
            f"v{version} is not published — published: "
            + ", ".join(f"v{v}" for v in published)
        )
    name = version_name(version)

    with preview_server(page_dir, version) as url:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel="chrome")
            except PlaywrightError as e:
                sys.exit(
                    f"export needs Chrome, and it didn't launch ({str(e).strip().splitlines()[0]}). "
                    "A copy is the drawn page, so there is nothing to write without one."
                )
            try:
                html = export_page(browser, url, page_dir)
            finally:
                browser.close()

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"✓ {name} → {out} ({out.stat().st_size // 1024} KB, opens with no server)")
    return 0


def resolve_dir(dir_arg: str, must_exist: bool = True) -> Path:
    page_dir = Path(dir_arg).expanduser().resolve()
    if must_exist and not page_dir.is_dir():
        sys.exit(f"{page_dir} does not exist; run `colloquy page init` first")
    return page_dir


@click.group()
def cli() -> None:
    """Build and run interactive review pages."""


@cli.group(short_help="Create pages and add media.")
def page() -> None:
    """Create pages and add media."""


@page.command(short_help="Create or re-vendor a page directory.")
@click.argument("dir", metavar="PAGE")
def init(dir: str) -> None:
    """Create or re-vendor a page directory.

    Creates PAGE/versions/ for authored vN.html files and vendors the widget
    layer. Re-running replaces that layer, unless the page log uses vocabulary
    the incoming layer cannot read.
    """
    cmd_init(resolve_dir(dir, must_exist=False))


@cli.group(short_help="Create theme and widget customizations.")
def customize() -> None:
    """Create theme and widget customizations."""


@customize.command("theme", short_help="Create the theme override file.")
@click.option("--user", is_flag=True, help="Use the user layer instead of this project.")
def customize_theme(user: bool) -> None:
    """Create the CSS override file without replacing one that exists."""
    cmd_customize_theme(user)


@customize.command("widget", short_help="Add a widget scaffold.")
@click.argument("tag")
@click.option("--user", is_flag=True, help="Use the user layer instead of this project.")
@click.option("--upgrade", is_flag=True, help="Also create an ES-module upgrade.")
def customize_widget(tag: str, user: bool, upgrade: bool) -> None:
    """Add a registry entry and CSS scaffold for a cq-* widget."""
    cmd_customize_widget(tag, user, upgrade)


@page.command(short_help="Add images and print their page paths.")
@click.argument("dir", metavar="PAGE")
@click.argument(
    "files",
    nargs=-1,
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    metavar="IMAGE...",
)
def media(dir: str, files) -> None:
    """Add images and print their page paths.

    Copies each image into the page under a content-addressed name and prints
    its page path followed by its source file.
    """
    for src, url in cmd_media(resolve_dir(dir), [Path(f) for f in files]):
        print(f"{url}\t{src}")


@page.command(short_help="Print the widget and theme vocabulary.")
@click.argument("dir", metavar="PAGE")
def catalog(dir: str) -> None:
    """Print the page's widget and theme vocabulary."""
    cmd_catalog(resolve_dir(dir))


@cli.group(short_help="Check, publish, and export versions.")
def version() -> None:
    """Check, publish, and export versions."""


@version.command(short_help="Check a page version.")
@click.argument("dir", metavar="PAGE")
@click.option(
    "--version",
    type=int,
    default=None,
    metavar="N",
    help="version to check (default: latest)",
)
@click.option("--render", is_flag=True, help="also check the rendered page in Chrome")
def check(dir: str, version: int, render: bool) -> None:
    """Check a page version.

    Runs deterministic markup checks. --render also checks the drawn page in
    the installed Chrome.
    """
    sys.exit(cmd_check(resolve_dir(dir), version, render))


@version.command(short_help="Publish a checked version with a changelog.")
@click.argument("dir", metavar="PAGE")
@click.option("--version", type=int, required=True, metavar="N", help="version to publish")
@click.option("--text", help="changelog text (default: stdin)")
def publish(dir: str, version: int, text: str) -> None:
    """Publish a checked version with a changelog.

    Checks the version first, then makes it visible to the page server.
    """
    cmd_publish(resolve_dir(dir), version, text)


@version.command(short_help="Export a published version to one HTML file.")
@click.argument("dir", metavar="PAGE")
@click.option(
    "-o",
    "--out",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="output HTML file",
)
@click.option(
    "--version",
    type=int,
    metavar="N",
    help="published version to export (default: latest)",
)
def export(dir: str, out: Path, version: int) -> None:
    """Export a published version to one HTML file.

    Renders the version in Chrome, then writes a standalone copy.
    """
    sys.exit(cmd_export(resolve_dir(dir), out, version))


@cli.group(short_help="Run or stop the local server.")
def server() -> None:
    """Run or stop the local server."""


@server.command(short_help="Serve a page and print its URL.")
@click.argument("dir", metavar="PAGE")
def run(dir: str) -> None:
    """Serve a page and print its URL.

    Runs until stopped. If the page already has a live server, prints its URL
    and exits.
    """
    cmd_serve(resolve_dir(dir))


@server.command(short_help="Stop a page's server.")
@click.argument("dir", metavar="PAGE")
def stop(dir: str) -> None:
    """Stop a page's server."""
    print(cmd_stop(resolve_dir(dir)))


@cli.group(short_help="Watch and write to a live review.")
def review() -> None:
    """Watch and write to a live review."""


@review.command(short_help="Set the agent's banner state.")
@click.argument("dir", metavar="PAGE")
@click.argument("state", type=click.Choice(["working", "waiting", "idle"]))
@click.argument("detail", required=False, default="")
def state(dir: str, state: str, detail: str) -> None:
    """Set the agent's banner state."""
    page_dir = resolve_dir(dir)
    # Idling over undelivered events ends the review on a reviewer still owed an
    # answer. Here rather than in cmd_status because SessionEnd idles pages whose
    # session is already gone, where nothing is left to pick them up.
    events = read_events(page_dir)
    pending = (
        full_state(page_dir, events, published_versions(page_dir, events))["pending"]
        if state == "idle"
        else 0
    )
    if pending:
        sys.exit(
            f"{pending} user event{'s' if pending != 1 else ''} nobody has picked up; "
            "idling closes the review over them. `colloquy review wait` prints them "
            "and returns at once when events are already waiting."
        )
    cmd_status(page_dir, state, detail)


@review.command(short_help="Print new reviewer events, then exit.")
@click.argument("dir", metavar="PAGE")
def wait(dir: str) -> None:
    """Print new reviewer events, then exit.

    Waits for undelivered reviewer events, prints them as JSON lines, and marks
    them delivered.
    """
    sys.exit(cmd_wait(resolve_dir(dir)))


@review.command(short_help="Open an agent thread on a page passage.")
@click.argument("dir", metavar="PAGE")
@click.option("--quote", help="passage text from the published version")
@click.option("--section", metavar="ID", help="element ID to anchor or scope --quote")
@click.option("--text", help="comment text (default: stdin)")
def comment(dir: str, quote: str, section: str, text: str) -> None:
    """Open a thread on a passage as the agent (--text or stdin).

    The reviewer answers it in the browser and resolves it there. Refuses a quote the
    published version does not hold, or holds more than once.
    """
    cmd_comment(resolve_dir(dir), quote, section, text)


@review.command(short_help="Reply to a thread as the agent.")
@click.argument("dir", metavar="PAGE")
@click.option("--to", required=True, metavar="ID", help="comment or reply ID to answer")
@click.option("--text", help="reply text (default: stdin)")
def reply(dir: str, to: str, text: str) -> None:
    """Post a threaded reply as the agent (--text or stdin)."""
    cmd_reply(resolve_dir(dir), to, text)


@review.command(short_help="Print the event log as JSON lines.")
@click.argument("dir", metavar="PAGE")
@click.option(
    "--after",
    type=int,
    default=0,
    metavar="SEQ",
    help="print events after this sequence",
)
def events(dir: str, after: int) -> None:
    """Print the event log as JSON lines.

    This is read-only and does not mark reviewer events delivered.
    """
    cmd_events(resolve_dir(dir), after)


@review.command(short_help="Print the review as Markdown.")
@click.argument("dir", metavar="PAGE")
def transcript(dir: str) -> None:
    """Print the review as Markdown."""
    cmd_transcript(resolve_dir(dir))


@cli.command(hidden=True)
def hook() -> None:
    """Answer an agent-host hook on stdin."""
    cmd_hook(json.load(sys.stdin))


if __name__ == "__main__":
    # `colloquy` is the name the skill hands an agent and the name on PATH, so it is
    # the name the usage lines have to say back, whichever way the script was reached.
    cli(prog_name="colloquy")
