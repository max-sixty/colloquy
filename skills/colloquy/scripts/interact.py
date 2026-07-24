#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.8"
# dependencies = ["click>=8"]
# ///
"""Serve and mediate an interactive colloquy page.

A `uv` script: the PEP 723 header above declares the one dependency
(`click`), and `uv` is the one prerequisite for the whole plugin — no venv to
create, no build step. Run it with `uv run interact.py <command> …`.

A page directory holds:
    versions/v001.html…  immutable page versions (Claude writes them; the server lists them)
    interact.js          comment/status layer, served at /interact.js (copied by `init`)
    comments.jsonl       append-only event log; an event's seq is its line number (1-based)
    status.json          Claude's declared state: {"state": working|waiting|idle, "detail", "ts"};
                         `wait` flips it to working when it delivers events, covering the handoff gap
    heartbeat.json       watcher liveness, bumped by `wait` while it runs
    cursor.json          seq of the last event delivered to Claude, written by `wait` on exit
    server.json          {"port", "pid", "url"} for the running server

Event kinds: comment (user; optional anchor {section, quote}), reply (parent=id),
resolve (parent=id), done (user sign-off), note (claude; per-version changelog).
The server stamps every browser-posted event author=user; `reply`/`note` stamp
author=claude.

Commands:
    init serve status wait reply note events stop check

`check` is a deterministic pre-handover lint (no browser needed): the HTML
parses with balanced tags, there is exactly one external <script> tag, every
anchor id from the previous version survives, and no fixed-pixel-width element
is wider than the readable column.
"""

import errno
import json
import os
import re
import secrets
import signal
import sys
import time
import zlib
from datetime import datetime
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import click

HEARTBEAT_FRESH_SECS = 8
BROWSER_EVENT_KINDS = {"comment", "reply", "resolve", "done"}

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
    path.write_text(json.dumps(obj, ensure_ascii=False) + "\n", encoding="utf-8")


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
    if info and pid_alive(info.get("pid", -1)):
        return info
    return None


def full_state(page_dir: Path) -> dict:
    status = read_json(page_dir / "status.json") or {"state": "idle", "detail": "", "ts": None}
    heartbeat = read_json(page_dir / "heartbeat.json") or {}
    listening = time.time() - heartbeat.get("t", 0) < HEARTBEAT_FRESH_SECS
    return {
        "versions": list_versions(page_dir),
        "status": status,
        "listening": listening,
        "events": read_events(page_dir),
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
            versions = list_versions(self.page_dir)
            if not versions:
                self._json({"error": "no versions yet"}, 404)
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
        if re.fullmatch(r"/interact\.js|/versions/v[0-9]+\.html", path):
            file = self.page_dir / path.lstrip("/")
            if file.exists():
                ctype = "application/javascript" if path.endswith(".js") else "text/html"
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
        if event.get("kind") not in BROWSER_EVENT_KINDS:
            self._json({"error": f"kind must be one of {sorted(BROWSER_EVENT_KINDS)}"}, 400)
            return
        event["author"] = "user"
        self._json({"ok": True, "event": append_event(self.page_dir, event)})


def cmd_init(page_dir: Path) -> None:
    (page_dir / "versions").mkdir(parents=True, exist_ok=True)
    layer = Path(__file__).resolve().parent.parent / "assets" / "interact.js"
    (page_dir / "interact.js").write_bytes(layer.read_bytes())
    if not (page_dir / "status.json").exists():
        write_json(page_dir / "status.json", {"state": "working", "detail": "Writing the page", "ts": now_iso()})
    print(f"initialized {page_dir}")


def cmd_serve(page_dir: Path) -> None:
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


def cmd_status(page_dir: Path, state: str, detail: str) -> None:
    write_json(page_dir / "status.json", {"state": state, "detail": detail, "ts": now_iso()})


def cmd_wait(page_dir: Path) -> int:
    cursor = (read_json(page_dir / "cursor.json") or {}).get("seq", 0)
    server_check_at = 0.0
    try:
        while True:
            (page_dir / "heartbeat.json").write_text(json.dumps({"t": time.time()}))
            events = read_events(page_dir)
            new_user = [e for e in events if e["seq"] > cursor and e.get("author") == "user"]
            if new_user:
                for event in new_user:
                    print(json.dumps(event, ensure_ascii=False), flush=True)
                # cursor after print: a kill mid-wait redelivers rather than drops
                write_json(page_dir / "cursor.json", {"seq": events[-1]["seq"]})
                # flip status here, not in Claude's next turn: the handoff gap
                # between this exit and Claude's pickup must not show "waiting"
                n = len(new_user)
                cmd_status(page_dir, "working", f"picking up {n} comment{'s' if n != 1 else ''}")
                return 0
            if time.time() > server_check_at:
                server_check_at = time.time() + 5
                if not running_server(page_dir):
                    print("server is not running; restart it with `serve`", file=sys.stderr)
                    return 2
            time.sleep(1)
    finally:
        (page_dir / "heartbeat.json").unlink(missing_ok=True)


def read_text_arg(text) -> str:
    body = text if text is not None else sys.stdin.read()
    if not body.strip():
        sys.exit("empty text (pass --text or pipe via stdin)")
    return body.strip()


def cmd_reply(page_dir: Path, to: str, text) -> None:
    known = {e["id"] for e in read_events(page_dir) if e.get("kind") in {"comment", "reply"}}
    if to not in known:
        sys.exit(f"unknown comment id {to!r}; known: {sorted(known)}")
    event = append_event(page_dir, {"kind": "reply", "author": "claude", "parent": to, "text": read_text_arg(text)})
    print(json.dumps(event, ensure_ascii=False))


def cmd_note(page_dir: Path, version: int, text) -> None:
    name = f"v{version:03d}.html"
    if name not in list_versions(page_dir):
        sys.exit(f"no {name} in {page_dir / 'versions'}; write the version file first")
    event = append_event(
        page_dir, {"kind": "note", "author": "claude", "version": version, "text": read_text_arg(text)}
    )
    print(json.dumps(event, ensure_ascii=False))


def cmd_events(page_dir: Path, after: int) -> None:
    for event in read_events(page_dir):
        if event["seq"] > after:
            print(json.dumps(event, ensure_ascii=False))


def cmd_stop(page_dir: Path) -> None:
    info = running_server(page_dir)
    if info:
        os.kill(info["pid"], signal.SIGTERM)
        print(f"stopped server pid {info['pid']}")
    else:
        print("no server running")
    (page_dir / "server.json").unlink(missing_ok=True)


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


class _StructParser(HTMLParser):
    """Tracks a tag stack to catch unclosed and mismatched tags, and collects
    element ids and every <script src> tag. Foreign markup inside <svg> is
    skipped (SVG has its own self-closing rules that don't matter here)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []  # (tag, lineno)
        self.errors = []
        self.ids = set()
        self.external_scripts = []  # src values
        self._svg_depth = 0

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

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if "id" in attrs_d and attrs_d["id"]:
            self.ids.add(attrs_d["id"])
        if tag == "script" and attrs_d.get("src"):
            self.external_scripts.append(attrs_d["src"])
        if tag == "svg":
            self._svg_depth += 1
            self.stack.append((tag, self.getpos()[0]))
            return
        if self._svg_depth:  # don't tag-balance inside SVG
            return
        if tag not in VOID_TAGS:
            self._implicit_close(tag)
            self.stack.append((tag, self.getpos()[0]))

    def handle_startendtag(self, tag, attrs):
        # <foo/> — self-closing; still harvest id/script but never pushed.
        attrs_d = dict(attrs)
        if "id" in attrs_d and attrs_d["id"]:
            self.ids.add(attrs_d["id"])
        if tag == "script" and attrs_d.get("src"):
            self.external_scripts.append(attrs_d["src"])

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
                orphaned = [(t, ln) for t, ln in self.stack[i + 1:] if t not in OPTIONAL_END]
                if orphaned:
                    unclosed = ", ".join(f"<{t}> (line {ln})" for t, ln in orphaned)
                    self.errors.append(f"</{tag}> at line {self.getpos()[0]} closes over unclosed: {unclosed}")
                del self.stack[i:]
                return
        if tag not in OPTIONAL_END:
            self.errors.append(f"stray </{tag}> at line {self.getpos()[0]} with no matching open tag")


def _column_width(html: str) -> int:
    """Best-effort readable-column width from the max-width of a container rule."""
    widths = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", html):
        selector, body = m.group(1), m.group(2)
        if not any(sel in selector for sel in COLUMN_SELECTORS):
            continue
        mw = re.search(r"max-width\s*:\s*(\d+(?:\.\d+)?)px", body)
        if mw:
            widths.append(float(mw.group(1)))
    return int(max(widths)) if widths else COLUMN_FALLBACK


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


def cmd_check(page_dir: Path, version) -> int:
    versions = list_versions(page_dir)
    if not versions:
        sys.exit(f"no versions in {page_dir / 'versions'}; write versions/v001.html first")
    name = f"v{version:03d}.html" if version is not None else versions[-1]
    if name not in versions:
        sys.exit(f"no {name} in {page_dir / 'versions'}")
    html = (page_dir / "versions" / name).read_text(encoding="utf-8")

    errors = []

    parser = _StructParser()
    parser.feed(html)
    parser.close()
    errors.extend(parser.errors)
    leftover = [(t, ln) for t, ln in parser.stack if t not in OPTIONAL_END]
    if leftover:
        unclosed = ", ".join(f"<{t}> (line {ln})" for t, ln in leftover)
        errors.append(f"unclosed tags at end of document: {unclosed}")

    n_ext = len(parser.external_scripts)
    if n_ext != 1:
        errors.append(
            f"expected exactly one external <script src> tag, found {n_ext}"
            + (f": {parser.external_scripts}" if parser.external_scripts else "")
        )
    elif parser.external_scripts[0] != "/interact.js":
        errors.append(
            f'the external script should be src="/interact.js", found {parser.external_scripts[0]!r}'
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

    column = _column_width(html)
    errors.extend(_overwide_elements(html, column))

    if errors:
        print(f"✗ {name}: {len(errors)} issue(s)", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(f"✓ {name}: parses, one external script, ids carried over, nothing overflows the {column}px column")
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
    """Create the page directory layout and copy in interact.js."""
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
    cmd_status(resolve_dir(dir), state, detail)


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
    cmd_stop(resolve_dir(dir))


@cli.command()
@click.argument("dir")
@click.option("--version", type=int, default=None, help="version to check (default: latest)")
def check(dir: str, version: int) -> None:
    """Deterministic pre-handover lint of a version."""
    sys.exit(cmd_check(resolve_dir(dir), version))


if __name__ == "__main__":
    cli()
