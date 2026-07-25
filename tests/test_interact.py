"""Integration tests for interact.py: the check lint, init vendoring, note-gated
serving, the catalog, reply widget validation, and the live server + wait
round-trip that the review loop rides on.

Run from the repo root:

    uv run --with pytest --with click --with jsonschema python -m pytest tests
"""

import importlib.util
import json
import os
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from click.testing import CliRunner

_spec = importlib.util.spec_from_file_location(
    "interact", Path(__file__).parent.parent / "skills" / "colloquy" / "scripts" / "interact.py"
)
interact = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(interact)


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>t</title>
<link rel="stylesheet" href="/theme.css">
</head>
<body>
<main>
<section id="plan">
  <h2>Plan</h2>
  <p>The cutoff lives in <cq-ref src="jobs/backfill.py:88"></cq-ref>.</p>
  <cq-options>
    <cq-option id="flag-first" effort="low" risk="med">
      <strong>Flag first</strong> Ship dark.
    </cq-option>
    <cq-option id="backfill-first" effort="med" risk="low" recommended>
      <strong>Backfill first</strong> Verify, then flip.
    </cq-option>
  </cq-options>
  <cq-diagram id="flow">
graph LR
  A --> B
  </cq-diagram>
</section>
</main>
<script type="module" src="/colloquy.js"></script>
</body>
</html>
"""


@pytest.fixture
def page_dir(tmp_path, monkeypatch):
    """An initialized page directory with a valid v001 written."""
    monkeypatch.chdir(tmp_path)  # keep the project layer out of the overlay
    d = tmp_path / "page"
    result = CliRunner().invoke(interact.cli, ["init", str(d)])
    assert result.exit_code == 0, result.output
    (d / "versions" / "v001.html").write_text(PAGE)
    return d


def check(d, version=None):
    args = ["check", str(d)] + (["--version", str(version)] if version else [])
    return CliRunner().invoke(interact.cli, args)


def test_init_vendors_the_layer(page_dir):
    for name in ["colloquy.js", "theme.css", "registry.json"]:
        assert (page_dir / name).is_file()
    assert (page_dir / "widgets" / "cq-ref.js").is_file()
    assert (page_dir / "widgets" / "cq-diagram.js").is_file()
    assert (page_dir / "vendor" / "mermaid.min.js").is_file()


def test_init_user_layer_applies(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude" / "colloquy" / "widgets").mkdir(parents=True)
    (home / ".claude" / "colloquy" / "theme.css").write_text(":root { --accent: teal }")
    (home / ".claude" / "colloquy" / "widgets" / "cq-foo.js").write_text("// user widget")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "page"
    result = CliRunner().invoke(interact.cli, ["init", str(d)])
    assert result.exit_code == 0, result.output
    assert (d / "theme.css").read_text() == ":root { --accent: teal }"
    assert (d / "widgets" / "cq-foo.js").read_text() == "// user widget"
    assert (d / "widgets" / "cq-ref.js").is_file()  # shipped modules still vendored


def test_init_project_layer_wins(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    (project / ".claude" / "colloquy").mkdir(parents=True)
    (project / ".claude" / "colloquy" / "theme.css").write_text(":root { --accent: red }")
    monkeypatch.chdir(project)
    d = tmp_path / "page"
    CliRunner().invoke(interact.cli, ["init", str(d)])
    assert (d / "theme.css").read_text() == ":root { --accent: red }"
    # Files the project layer doesn't override still come from the shipped defaults.
    assert (d / "registry.json").is_file()


def test_check_accepts_a_valid_page(page_dir):
    result = check(page_dir)
    assert result.exit_code == 0, result.output


def test_check_rejects_widget_violations(page_dir):
    (page_dir / "versions" / "v001.html").write_text(
        PAGE.replace(
            '<cq-ref src="jobs/backfill.py:88"></cq-ref>',
            '<cq-ref src="x.py:1"/>'
            "<cq-bogus></cq-bogus>"
            '<cq-option id="stray" risk="medium"><strong>S</strong></cq-option>'
            '<cq-diagram id="Bad_ID"><em>x</em></cq-diagram>',
        ).replace('<cq-option id="flag-first"', "<cq-option")
    )
    result = check(page_dir)
    assert result.exit_code == 1
    out = result.output
    assert "self-closing" in out
    assert "unknown widget" in out
    assert "'medium' is not one of" in out
    assert "must be a direct child of <cq-options>" in out
    assert "'id' is a required property" in out
    assert "does not match" in out  # id pattern
    assert "its body is data" in out


def test_check_rejects_loose_content_in_items_container(page_dir):
    (page_dir / "versions" / "v001.html").write_text(
        PAGE.replace("<cq-options>", "<cq-options>\nloose text\n<p>stray</p>\n<br/>")
    )
    result = check(page_dir)
    assert result.exit_code == 1
    assert "admits only ['cq-option'] children" in result.output
    assert "'br'" in result.output  # self-closed strays count as children too
    assert "loose text" in result.output


def test_flag_attribute_accepts_both_html_spellings(page_dir):
    (page_dir / "versions" / "v001.html").write_text(PAGE.replace(" recommended>", ' recommended="">'))
    assert check(page_dir).exit_code == 0
    (page_dir / "versions" / "v001.html").write_text(PAGE.replace(" recommended>", ' recommended="yes">'))
    result = check(page_dir)
    assert result.exit_code == 1
    assert "is not of type 'boolean'" in result.output


def test_plan_and_milestones_compose(page_dir):
    nested = """<cq-plan id="plan-x">
  <strong>Rebuild</strong>
  <cq-milestones>
    <cq-milestone id="m-one" status="done" when="week 1"><strong>Survey</strong> Sites.</cq-milestone>
    <cq-milestone id="m-two" status="active" tags="wood,solar"><strong>Build</strong></cq-milestone>
  </cq-milestones>
</cq-plan>
<cq-options>"""
    (page_dir / "versions" / "v001.html").write_text(PAGE.replace("<cq-options>", nested))
    result = check(page_dir)
    assert result.exit_code == 0, result.output
    (page_dir / "versions" / "v001.html").write_text(
        PAGE.replace(
            "<cq-options>",
            '<cq-milestone id="m-stray" status="done"><strong>X</strong></cq-milestone><cq-options>',
        )
    )
    result = check(page_dir)
    assert result.exit_code == 1
    assert "must be a direct child of <cq-milestones>" in result.output


def test_tabs_validate_and_compose(page_dir):
    tabs = """<cq-tabs id="ws">
  <cq-tab id="ws-ingest" label="Ingest"><p>Pipeline notes.</p></cq-tab>
  <cq-tab id="ws-search" label="Search">
    <cq-metrics><cq-metric id="k-lat" value="118 ms"></cq-metric></cq-metrics>
  </cq-tab>
</cq-tabs>
<cq-options>"""
    (page_dir / "versions" / "v001.html").write_text(PAGE.replace("<cq-options>", tabs))
    result = check(page_dir)
    assert result.exit_code == 0, result.output


def test_tabs_reject_structural_violations(page_dir):
    # A label-less panel, a stray panel outside cq-tabs, and loose text between
    # panels are each refused.
    bad = """<cq-tabs id="ws">
  loose text
  <cq-tab id="ws-a"><p>x</p></cq-tab>
</cq-tabs>
<cq-tab id="ws-stray" label="Stray"><p>y</p></cq-tab>
<cq-options>"""
    (page_dir / "versions" / "v001.html").write_text(PAGE.replace("<cq-options>", bad))
    result = check(page_dir)
    assert result.exit_code == 1
    assert "'label' is a required property" in result.output
    assert "must be a direct child of <cq-tabs>" in result.output
    assert "loose text" in result.output


def test_check_rejects_wrong_scaffold(page_dir):
    html = PAGE.replace('<script type="module" src="/colloquy.js"></script>', "").replace(
        '<link rel="stylesheet" href="/theme.css">', ""
    )
    (page_dir / "versions" / "v001.html").write_text(html)
    result = check(page_dir)
    assert result.exit_code == 1
    assert "exactly one external <script src>" in result.output
    assert "exactly one stylesheet" in result.output


def test_check_owns_the_cq_meta_vocabulary(page_dir):
    # The sign-off declaration: valid on its one value, rejected on a misspelled
    # value or name — either would silently declare nothing in the browser.
    signoff = PAGE.replace(
        "<title>t</title>", '<title>t</title>\n<meta name="cq-review" content="sign-off">'
    )
    (page_dir / "versions" / "v001.html").write_text(signoff)
    assert check(page_dir).exit_code == 0

    (page_dir / "versions" / "v001.html").write_text(signoff.replace("sign-off", "approve"))
    result = check(page_dir)
    assert result.exit_code == 1
    assert "content must be one of ['sign-off'], found 'approve'" in result.output

    (page_dir / "versions" / "v001.html").write_text(signoff.replace("cq-review", "cq-signoff"))
    result = check(page_dir)
    assert result.exit_code == 1
    assert "unknown cq- meta" in result.output
    assert "cq-review" in result.output  # the error names the known vocabulary


def test_check_rejects_duplicate_ids_and_dropped_ids(page_dir):
    result = check(page_dir)
    assert result.exit_code == 0, result.output
    (page_dir / "versions" / "v002.html").write_text(
        PAGE.replace('id="backfill-first"', 'id="flag-first"')
    )
    result = check(page_dir, version=2)
    assert result.exit_code == 1
    assert "duplicate ids" in result.output
    assert "dropped in v002.html" in result.output
    assert "backfill-first" in result.output


def test_check_requires_the_vendored_layer(tmp_path):
    d = tmp_path / "bare"
    (d / "versions").mkdir(parents=True)
    (d / "versions" / "v001.html").write_text(PAGE)
    result = check(d)
    assert result.exit_code == 1
    assert "run `init` to vendor the layer" in result.output


def test_check_takes_column_width_from_vendored_theme(page_dir):
    # theme.css sets a 760px main column; a wider fixed-width element must fail.
    (page_dir / "versions" / "v001.html").write_text(
        PAGE.replace("<h2>Plan</h2>", '<h2>Plan</h2><svg width="900" height="10"></svg>')
    )
    result = check(page_dir)
    assert result.exit_code == 1
    assert "exceeds column (760px)" in result.output


@pytest.fixture
def server(page_dir):
    """A real HTTP server over the page directory, on an ephemeral port."""
    interact.Handler.page_dir = page_dir
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), interact.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def fetch(url, data=None):
    try:
        with urllib.request.urlopen(url, data=data) as res:
            return res.status, res.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_server_round_trip(server, page_dir):
    # Unnoted version: nothing published yet.
    status, _ = fetch(f"{server}/")
    assert status == 404
    status, _ = fetch(f"{server}/versions/v001.html")
    assert status == 404
    CliRunner().invoke(interact.cli, ["note", str(page_dir), "--version", "1", "--text", "cut"])
    status, body = fetch(f"{server}/")  # urllib follows the 302
    assert status == 200 and b"cq-options" in body
    # Vendored files serve; the log and directory paths don't.
    for path in ["/colloquy.js", "/theme.css", "/registry.json", "/widgets/cq-ref.js"]:
        assert fetch(server + path)[0] == 200, path
    for path in ["/comments.jsonl", "/vendor/..", "/status.json", "/../secret"]:
        assert fetch(server + path)[0] == 404, path
    # A browser-posted comment lands stamped author=user, with a server-minted id
    # (client ids are dropped — a reused one would re-root an existing thread).
    status, body = fetch(
        f"{server}/api/event",
        data=json.dumps({"kind": "comment", "id": "c9", "text": "hm", "author": "claude"}).encode(),
    )
    assert status == 200
    posted = interact.read_events(page_dir)[-1]
    assert posted["author"] == "user" and posted["id"] != "c9"
    status, body = fetch(f"{server}/api/state")
    state = json.loads(body)
    assert state["versions"] == ["v001.html"]
    assert state["cursor"] == 0  # nothing delivered to Claude yet
    assert state["events"][-1]["id"] == posted["id"]
    # A widget action rides the same channel; half-formed ones are refused at the edge.
    status, _ = fetch(
        f"{server}/api/event",
        data=json.dumps(
            {
                "kind": "action",
                "version": 1,
                "widget": "feeder-board",
                "action": "move",
                "detail": {"card": "card-baffle", "to": "col-doing", "index": 0},
            }
        ).encode(),
    )
    assert status == 200
    moved = interact.read_events(page_dir)[-1]
    assert moved["author"] == "user" and moved["detail"]["to"] == "col-doing"
    for bad in [
        {"kind": "action", "action": "move"},  # no widget
        {"kind": "action", "widget": "", "action": "move", "detail": {}, "version": 1},
        {"kind": "action", "widget": "b", "action": "move", "version": 1},  # no detail
        {"kind": "action", "widget": "b", "action": "move", "detail": None, "version": 1},
        {"kind": "action", "widget": "b", "action": "move", "detail": {}, "version": "1"},
        ["not", "an", "object"],
    ]:
        status, body = fetch(f"{server}/api/event", data=json.dumps(bad).encode())
        assert status == 400, bad


def test_concurrent_posts_never_tear_the_log(server, page_dir):
    def post(i):
        fetch(
            f"{server}/api/event",
            data=json.dumps({"kind": "comment", "text": f"c{i} " + "x" * 500}).encode(),
        )

    threads = [threading.Thread(target=post, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    events = interact.read_events(page_dir)  # raises on any torn non-final line
    assert {e["text"].split()[0] for e in events} == {f"c{i}" for i in range(20)}
    assert len({e["id"] for e in events}) == 20  # server-minted, all distinct


def test_wait_delivers_new_user_events_and_flips_status(page_dir, capsys):
    # A live server.json (our own pid) satisfies wait's liveness probe.
    interact.write_json(page_dir / "server.json", {"port": 1, "pid": os.getpid(), "url": "x"})
    interact.append_event(page_dir, {"kind": "comment", "id": "c1", "author": "user", "text": "hi"})
    interact.append_event(
        page_dir,
        {
            "kind": "action",
            "author": "user",
            "version": 1,
            "widget": "b",
            "action": "move",
            "detail": {"card": "x", "to": "y", "index": 0},
        },
    )
    assert interact.cmd_wait(page_dir) == 0
    delivered = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]
    assert [e["kind"] for e in delivered] == ["comment", "action"]
    assert delivered[1]["detail"]["to"] == "y"
    assert interact.read_json(page_dir / "cursor.json")["seq"] == 2
    assert interact.read_json(page_dir / "status.json")["state"] == "working"
    # Already-delivered events don't re-deliver; a dead server ends the wait.
    (page_dir / "server.json").unlink()
    assert interact.cmd_wait(page_dir) == 2


def test_versions_publish_only_once_noted(page_dir):
    assert interact.published_versions(page_dir) == []
    assert interact.full_state(page_dir)["versions"] == []
    result = CliRunner().invoke(
        interact.cli, ["note", str(page_dir), "--version", "1", "--text", "first cut"]
    )
    assert result.exit_code == 0, result.output
    assert interact.published_versions(page_dir) == ["v001.html"]
    # The next version stays unpublished until its own note lands.
    (page_dir / "versions" / "v002.html").write_text(PAGE)
    assert interact.published_versions(page_dir) == ["v001.html"]


def test_choose_requires_an_id(page_dir):
    # Actions name their widget by id, so an interactive group can't go without one.
    registry = interact.load_registry(page_dir)
    errs = interact.fragment_errors(
        '<cq-options choose><cq-option id="o1"><strong>A</strong></cq-option></cq-options>',
        registry,
    )
    assert errs and "'id' is a dependency of 'choose'" in " ".join(errs)


def test_registry_examples_validate(page_dir):
    reg = json.loads((page_dir / "registry.json").read_text())
    registry = interact.load_registry(page_dir)
    examples = {t: e["x-example"] for t, e in reg.items() if t.startswith("cq-") and "x-example" in e}
    assert examples  # the shipped registry documents by example
    for tag, example in examples.items():
        errs = interact.fragment_errors(example, registry)
        assert not errs, f"{tag} x-example doesn't validate: {errs}"


def test_examples_pass_check(tmp_path, monkeypatch):
    """Every gallery page in examples/ lints clean against the shipped layer."""
    monkeypatch.chdir(tmp_path)  # keep the project layer out of the overlay
    examples = sorted((Path(__file__).parent.parent / "examples").glob("*.html"))
    assert examples
    for example in examples:
        d = tmp_path / example.stem
        CliRunner().invoke(interact.cli, ["init", str(d)])
        (d / "versions" / "v001.html").write_text(example.read_text())
        result = check(d)
        assert result.exit_code == 0, f"{example.name}: {result.output}"


def test_gallery_is_generated_from_the_examples():
    """examples/gallery.html is derived; a commit that lets it drift fails here."""
    spec = importlib.util.spec_from_file_location(
        "gallery", Path(__file__).parent.parent / "scripts" / "gallery.py"
    )
    gallery = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gallery)
    committed = (Path(__file__).parent.parent / "examples" / "gallery.html").read_text()
    assert gallery.build() == committed, "examples changed — rerun scripts/gallery.py"


def test_catalog_prints_widgets_and_idioms(page_dir):
    result = CliRunner().invoke(interact.cli, ["catalog", str(page_dir)])
    assert result.exit_code == 0
    assert "cq-options" in result.output
    assert "x-example" in result.output
    assert ".callout" in result.output
    assert "$idioms" not in result.output  # sections are split out, not dumped raw


def test_reply_validates_widget_markup(page_dir):
    interact.append_event(page_dir, {"kind": "comment", "id": "c1", "author": "user", "text": "hm"})
    bad = CliRunner().invoke(
        interact.cli,
        ["reply", str(page_dir), "--to", "c1", "--text", '<cq-diagram id="f"><b>x</b></cq-diagram>'],
    )
    assert bad.exit_code != 0
    assert "its body is data" in bad.output
    good = CliRunner().invoke(
        interact.cli,
        ["reply", str(page_dir), "--to", "c1", "--text", 'See:\n<cq-diagram id="f">\ngraph LR\n  A --> B\n</cq-diagram>'],
    )
    assert good.exit_code == 0, good.output
    events = interact.read_events(page_dir)
    assert events[-1]["kind"] == "reply"
    assert events[-1]["author"] == "claude"


def test_widget_ids_are_one_universe_across_page_and_replies(page_dir):
    """The runtime resolves actions document-wide by id, so a reply widget must not
    reuse a page id — and a later version must not take a reply's."""
    interact.append_event(page_dir, {"kind": "comment", "id": "c1", "author": "user", "text": "hm"})
    reply = lambda markup: CliRunner().invoke(
        interact.cli, ["reply", str(page_dir), "--to", "c1", "--text", markup]
    )
    # `flow` is the page's cq-diagram id (PAGE fixture) — refused.
    clash = reply('<cq-options id="flow" choose><cq-option id="o1"><strong>A</strong></cq-option></cq-options>')
    assert clash.exit_code != 0 and "flow" in clash.output
    fresh = reply('<cq-options id="q1" choose><cq-option id="q1-a"><strong>A</strong></cq-option></cq-options>')
    assert fresh.exit_code == 0, fresh.output
    # A second reply can't reuse the first reply's ids either, nor its own within itself.
    again = reply('<cq-options id="q1" choose><cq-option id="q1-b"><strong>B</strong></cq-option></cq-options>')
    assert again.exit_code != 0 and "q1" in again.output
    selfdup = reply('<cq-options id="q2" choose><cq-option id="q2"><strong>B</strong></cq-option></cq-options>')
    assert selfdup.exit_code != 0 and "within itself" in selfdup.output
    # A USER reply quoting markup renders as plain text and claims no ids — it must
    # not poison the universe (the log is append-only; a false claim would deadlock
    # every future version).
    interact.append_event(
        page_dir,
        {"kind": "reply", "author": "user", "parent": "c1", "text": 'why not <cq-diagram id="quoted"> here?'},
    )
    ok = reply('<cq-options id="quoted" choose><cq-option id="quoted-a"><strong>A</strong></cq-option></cq-options>')
    assert ok.exit_code == 0, ok.output
    # And a new version taking the reply's id fails check.
    (page_dir / "versions" / "v002.html").write_text(
        PAGE.replace('<section id="plan">', '<section id="plan"><p id="q1">stolen</p>')
    )
    result = check(page_dir, version=2)
    assert result.exit_code == 1
    assert "taken by widget markup in a reply" in result.output and "q1" in result.output


def test_export_prints_threads_and_versions(page_dir):
    CliRunner().invoke(interact.cli, ["note", str(page_dir), "--version", "1", "--text", "first cut"])
    interact.append_event(
        page_dir,
        {"kind": "comment", "id": "c1", "author": "user", "anchor": {"quote": "flip reads"}, "text": "why?"},
    )
    interact.append_event(
        page_dir, {"kind": "reply", "id": "r1", "author": "claude", "parent": "c1", "text": "reversibility"}
    )
    interact.append_event(page_dir, {"kind": "resolve", "id": "x1", "author": "user", "parent": "r1"})
    interact.append_event(
        page_dir,
        {"kind": "comment", "id": "c2", "author": "user", "anchor": {"section": "flow"}, "text": "arrow?"},
    )
    interact.append_event(
        page_dir,
        {
            "kind": "action",
            "author": "user",
            "version": 1,
            "widget": "b",
            "action": "move",
            "detail": {"card": "card-x", "to": "col-done", "index": 0},
        },
    )
    result = CliRunner().invoke(interact.cli, ["export", str(page_dir)])
    assert result.exit_code == 0, result.output
    assert "- v1: first cut" in result.output
    # The reviewer's direct edits are review outcomes, not just events.
    assert "### Edits" in result.output
    assert "- `b`: move card=card-x to=col-done index=0 (on v1)" in result.output
    assert "> “flip reads”  — resolved" in result.output
    assert "- **User**: why?" in result.output
    assert "- **Claude**: reversibility" in result.output
    assert "> § flow" in result.output  # element-anchored comments keep their target


def test_plain_reply_needs_no_registry(page_dir):
    interact.append_event(page_dir, {"kind": "comment", "id": "c1", "author": "user", "text": "hm"})
    result = CliRunner().invoke(
        interact.cli, ["reply", str(page_dir), "--to", "c1", "--text", "plain answer, x < y"]
    )
    assert result.exit_code == 0, result.output


def test_widget_reply_requires_a_registry(page_dir):
    (page_dir / "registry.json").unlink()
    interact.append_event(page_dir, {"kind": "comment", "id": "c1", "author": "user", "text": "hm"})
    result = CliRunner().invoke(
        interact.cli,
        ["reply", str(page_dir), "--to", "c1", "--text", '<cq-ref src="a.py:1"></cq-ref>'],
    )
    assert result.exit_code != 0
    assert "no registry.json" in result.output


def test_note_refuses_a_version_that_fails_check(page_dir):
    (page_dir / "versions" / "v001.html").write_text(PAGE.replace("</section>", ""))
    result = CliRunner().invoke(
        interact.cli, ["note", str(page_dir), "--version", "1", "--text", "broken"]
    )
    assert result.exit_code != 0
    assert "refusing to publish" in result.output
    assert interact.published_versions(page_dir) == []
