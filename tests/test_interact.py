"""Integration tests for interact.py: the check lint, init vendoring, note-gated
serving, the catalog, reply widget validation, and the live server + wait
round-trip that the review loop rides on.

Run from the repo root:

    uv run --with pytest --with click --with jsonschema python -m pytest tests
"""

import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
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
    """An initialized page directory with a valid v1 written."""
    monkeypatch.chdir(tmp_path)  # keep the project layer out of the overlay
    d = tmp_path / "page"
    result = CliRunner().invoke(interact.cli, ["init", str(d)])
    assert result.exit_code == 0, result.output
    (d / "versions" / "v1.html").write_text(PAGE)
    return d


def check(d, version=None):
    args = ["check", str(d)] + (["--version", str(version)] if version else [])
    return CliRunner().invoke(interact.cli, args)


def publish(d, version=1):
    """The note that makes a version the reviewer-seen baseline: `check`
    compares against the last *published* version, and an action can only ever
    be made against one the server exposed."""
    interact.append_event(
        d, {"kind": "note", "author": "claude", "version": version, "text": "published"}
    )


def test_init_vendors_the_layer(page_dir):
    for name in ["colloquy.js", "theme.css", "registry.json"]:
        assert (page_dir / name).is_file()
    assert (page_dir / "widgets" / "cq-ref.js").is_file()
    assert (page_dir / "widgets" / "cq-diagram.js").is_file()
    assert (page_dir / "vendor" / "mermaid.min.js").is_file()


def test_init_user_layer_applies(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".config" / "colloquy" / "widgets").mkdir(parents=True)
    (home / ".config" / "colloquy" / "theme.css").write_text(":root { --accent: teal }")
    (home / ".config" / "colloquy" / "widgets" / "cq-foo.js").write_text("// user widget")
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
    (page_dir / "versions" / "v1.html").write_text(
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


def test_check_rejects_a_language_nothing_will_color(page_dir):
    """A declared language the runtime won't honor renders as a plain block, which is
    exactly what a block with no language renders as — so the reviewer sees nothing
    wrong and the author never finds out. Both ways of getting it wrong are the lint's,
    because the author is the only one who can still fix either: the class somewhere
    other than <pre><code>, and a language this page's vendored layer doesn't speak."""
    (page_dir / "versions" / "v1.html").write_text(
        PAGE.replace(
            "<h2>Plan</h2>",
            "<h2>Plan</h2>\n"
            '<pre><code class="language-pythn">x = 1</code></pre>\n'
            '<div class="note language-python">not a code block</div>\n'
            '<pre><code class="language-python">y = 2</code></pre>',
        )
    )
    result = check(page_dir)
    assert result.exit_code == 1
    out = result.output
    assert 'class="language-pythn"' in out and "not a language this page's layer speaks" in out
    assert 'class="language-python"' in out and "only <pre><code> is colored" in out
    # The well-formed block is not among the complaints.
    assert out.count('class="language-python"') == 1


def test_check_rejects_loose_content_in_items_container(page_dir):
    (page_dir / "versions" / "v1.html").write_text(
        PAGE.replace("<cq-options>", "<cq-options>\nloose text\n<p>stray</p>\n<br/>")
    )
    result = check(page_dir)
    assert result.exit_code == 1
    assert "admits only ['cq-option'] children" in result.output
    assert "'br'" in result.output  # self-closed strays count as children too
    assert "loose text" in result.output


def test_flag_attribute_accepts_both_html_spellings(page_dir):
    (page_dir / "versions" / "v1.html").write_text(PAGE.replace(" recommended>", ' recommended="">'))
    assert check(page_dir).exit_code == 0
    (page_dir / "versions" / "v1.html").write_text(PAGE.replace(" recommended>", ' recommended="yes">'))
    result = check(page_dir)
    assert result.exit_code == 1
    assert "is not of type 'boolean'" in result.output


def test_milestones_compose(page_dir):
    nested = """<cq-milestones>
    <cq-milestone id="m-one" status="done" when="week 1"><strong>Survey</strong> Sites.</cq-milestone>
    <cq-milestone id="m-two" status="active" tags="wood,solar"><strong>Build</strong></cq-milestone>
  </cq-milestones>
<cq-options>"""
    (page_dir / "versions" / "v1.html").write_text(PAGE.replace("<cq-options>", nested))
    result = check(page_dir)
    assert result.exit_code == 0, result.output
    (page_dir / "versions" / "v1.html").write_text(
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
    (page_dir / "versions" / "v1.html").write_text(PAGE.replace("<cq-options>", tabs))
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
    (page_dir / "versions" / "v1.html").write_text(PAGE.replace("<cq-options>", bad))
    result = check(page_dir)
    assert result.exit_code == 1
    assert "'label' is a required property" in result.output
    assert "must be a direct child of <cq-tabs>" in result.output
    assert "loose text" in result.output


SUGGESTION = """<cq-suggestion id="sug-refill">
  <cq-old><p id="refill-rule">Refill every feeder each morning.</p></cq-old>
  <cq-new><p id="refill-camera">Refill when the camera shows it half-empty.</p></cq-new>
</cq-suggestion>
<cq-options>"""


def suggest(page_dir, version=2, markup=SUGGESTION):
    """Write and publish v1 carrying a suggestion, and an unchanged v2 to
    check against."""
    (page_dir / "versions" / "v1.html").write_text(PAGE.replace("<cq-options>", markup))
    publish(page_dir)
    (page_dir / "versions" / f"v{version}.html").write_text(PAGE.replace("<cq-options>", markup))


def decide(page_dir, outcome, widget="sug-refill"):
    interact.append_event(
        page_dir,
        {"kind": "action", "author": "user", "version": 1, "widget": widget,
         "action": outcome, "detail": {}},
    )


def test_suggestion_validates(page_dir):
    suggest(page_dir)
    assert check(page_dir, version=1).exit_code == 0, check(page_dir, version=1).output


def test_suggestion_rejects_malformed_shapes(page_dir):
    for markup, expected in [
        ('<cq-suggestion id="sug-a"></cq-suggestion><cq-options>', "needs a <cq-old>"),
        (
            '<cq-suggestion id="sug-a"><cq-new><p>x</p></cq-new>'
            '<cq-new><p>y</p></cq-new></cq-suggestion><cq-options>',
            "one at most",
        ),
        (
            '<cq-suggestion id="sug-a"><cq-new>'
            '<cq-suggestion id="sug-b"><cq-new>x</cq-new></cq-suggestion>'
            "</cq-new></cq-suggestion><cq-options>",
            "don't nest",
        ),
        ('<cq-old><p>orphan</p></cq-old><cq-options>', "must be a direct child of <cq-suggestion>"),
        (
            '<cq-suggestion id="sug-a" resolves="nosuch"><cq-new><p>x</p></cq-new>'
            "</cq-suggestion><cq-options>",
            "names no comment in the log",
        ),
    ]:
        (page_dir / "versions" / "v1.html").write_text(PAGE.replace("<cq-options>", markup))
        result = check(page_dir, version=1)
        assert result.exit_code == 1, markup
        assert expected in result.output, f"{markup}\n{result.output}"


def test_suggestion_resolves_accepts_a_real_comment(page_dir):
    interact.append_event(page_dir, {"kind": "comment", "id": "c1", "author": "user", "text": "hm"})
    markup = '<cq-suggestion id="sug-a" resolves="c1"><cq-new><p>x</p></cq-new></cq-suggestion><cq-options>'
    (page_dir / "versions" / "v1.html").write_text(PAGE.replace("<cq-options>", markup))
    assert check(page_dir, version=1).exit_code == 0


def test_accepting_licenses_retiring_the_replaced_markup(page_dir):
    # v2 honors the accept: the old paragraph and the wrapper are gone, the
    # proposal inlined. Nothing but a logged accept makes that legal.
    suggest(page_dir)
    honored = PAGE.replace(
        "<cq-options>", '<p id="refill-camera">Refill when the camera shows it half-empty.</p><cq-options>'
    )
    (page_dir / "versions" / "v2.html").write_text(honored)
    result = check(page_dir, version=2)
    assert result.exit_code == 1
    assert "refill-rule" in result.output

    decide(page_dir, "accept")
    assert check(page_dir, version=2).exit_code == 0, check(page_dir, version=2).output


def test_an_unanswered_proposal_cant_be_kept_as_settled_content(page_dir):
    # Self-accepting: the wrapper goes but its proposal stays, presented as
    # ordinary prose the reviewer never agreed to. Withdrawal is whole or not.
    insert = """<cq-suggestion id="sug-thistle">
  <cq-new><p id="thistle-plan">Switch the north feeder to thistle in autumn.</p></cq-new>
</cq-suggestion>
<cq-options>"""
    suggest(page_dir, markup=insert)
    (page_dir / "versions" / "v2.html").write_text(
        PAGE.replace("<cq-options>", '<p id="thistle-plan">Switch the north feeder to thistle in autumn.</p><cq-options>')
    )
    result = check(page_dir, version=2)
    assert result.exit_code == 1
    assert "sug-thistle" in result.output
    # A refused version never published, so it is nobody's baseline: v3 stands
    # against v1 — the page the reviewer was actually looking at — and there a
    # whole withdrawal is fine. So is honoring a logged accept.
    (page_dir / "versions" / "v3.html").write_text(PAGE)
    assert check(page_dir, version=3).exit_code == 0
    decide(page_dir, "accept", widget="sug-thistle")
    assert check(page_dir, version=2).exit_code == 0


def test_rejecting_licenses_retiring_the_proposal(page_dir):
    # A reject is consent to drop the proposal, so it retires even while a
    # thread about it is open — the reviewer has already answered.
    suggest(page_dir)
    (page_dir / "versions" / "v2.html").write_text(
        PAGE.replace("<cq-options>", '<p id="refill-rule">Refill every feeder each morning.</p><cq-options>')
    )
    interact.append_event(
        page_dir,
        {"kind": "comment", "id": "c1", "author": "user",
         "anchor": {"section": "refill-camera"}, "text": "cameras aren't reliable yet"},
    )
    assert check(page_dir, version=2).exit_code == 1
    decide(page_dir, "reject")
    assert check(page_dir, version=2).exit_code == 0
    # The other slot is not licensed: dropping the markup a reject kept is refused.
    (page_dir / "versions" / "v3.html").write_text(PAGE)
    result = check(page_dir, version=3)
    assert result.exit_code == 1
    assert "refill-rule" in result.output


def test_an_unanswered_deletion_cant_delete(page_dir):
    # The mirror of self-accepting an insertion: dropping the markup a pending
    # deletion wraps, without the accept that consents to losing it.
    delete = """<cq-suggestion id="sug-drop">
  <cq-old><p id="hand-log">The manual sightings log.</p></cq-old>
</cq-suggestion>
<cq-options>"""
    suggest(page_dir, markup=delete)
    (page_dir / "versions" / "v2.html").write_text(PAGE)
    result = check(page_dir, version=2)
    assert result.exit_code == 1
    assert "hand-log" in result.output
    decide(page_dir, "accept", widget="sug-drop")
    assert check(page_dir, version=2).exit_code == 0


def test_withdrawing_an_unanswered_suggestion_needs_no_consent(page_dir):
    # Nothing was decided, so Claude may take the proposal back — but not while
    # an unresolved thread is anchored in it.
    suggest(page_dir)
    (page_dir / "versions" / "v2.html").write_text(
        PAGE.replace("<cq-options>", '<p id="refill-rule">Refill every feeder each morning.</p><cq-options>')
    )
    assert check(page_dir, version=2).exit_code == 0
    interact.append_event(
        page_dir,
        {"kind": "comment", "id": "c1", "author": "user",
         "anchor": {"section": "refill-camera"}, "text": "why the camera?"},
    )
    result = check(page_dir, version=2)
    assert result.exit_code == 1
    assert "refill-camera" in result.output
    interact.append_event(page_dir, {"kind": "resolve", "author": "user", "parent": "c1"})
    assert check(page_dir, version=2).exit_code == 0


def test_reply_refuses_a_suggestion(page_dir):
    interact.append_event(page_dir, {"kind": "comment", "id": "c1", "author": "user", "text": "hm"})
    result = CliRunner().invoke(
        interact.cli,
        ["reply", str(page_dir), "--to", "c1", "--text",
         '<cq-suggestion id="sug-x"><cq-new><p>fixed</p></cq-new></cq-suggestion>'],
    )
    assert result.exit_code != 0
    assert "frozen in the log" in result.output


def test_check_rejects_wrong_scaffold(page_dir):
    html = PAGE.replace('<script type="module" src="/colloquy.js"></script>', "").replace(
        '<link rel="stylesheet" href="/theme.css">', ""
    )
    (page_dir / "versions" / "v1.html").write_text(html)
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
    (page_dir / "versions" / "v1.html").write_text(signoff)
    assert check(page_dir).exit_code == 0

    (page_dir / "versions" / "v1.html").write_text(signoff.replace("sign-off", "approve"))
    result = check(page_dir)
    assert result.exit_code == 1
    assert "content must be one of ['sign-off'], found 'approve'" in result.output

    (page_dir / "versions" / "v1.html").write_text(signoff.replace("cq-review", "cq-signoff"))
    result = check(page_dir)
    assert result.exit_code == 1
    assert "unknown cq- meta" in result.output
    assert "cq-review" in result.output  # the error names the known vocabulary


def test_check_rejects_duplicate_ids_and_dropped_ids(page_dir):
    result = check(page_dir)
    assert result.exit_code == 0, result.output
    publish(page_dir)
    (page_dir / "versions" / "v2.html").write_text(
        PAGE.replace('id="backfill-first"', 'id="flag-first"')
    )
    result = check(page_dir, version=2)
    assert result.exit_code == 1
    assert "duplicate ids" in result.output
    assert "dropped in v2.html" in result.output
    assert "backfill-first" in result.output


def _decided(page_dir, words):
    """v1 carrying a draft the reviewer has since rewritten, and the log that
    says so. Whatever v2 does about it, `check` is what has to notice."""
    (page_dir / "versions" / "v1.html").write_text(
        PAGE.replace("<h2>Plan</h2>", f'<h2>Plan</h2><cq-draft id="d1">{words}</cq-draft>')
    )
    publish(page_dir)
    interact.append_event(page_dir, {"kind": "action", "author": "user", "version": 1,
                                     "widget": "d1", "action": "edit",
                                     "detail": {"text": "Cut the flag; backfill first."}})
    return lambda words, attrs="": (page_dir / "versions" / "v2.html").write_text(
        PAGE.replace("<h2>Plan</h2>", f'<h2>Plan</h2><cq-draft id="d1"{attrs}>{words}</cq-draft>')
    )


def test_a_version_may_not_quietly_rewrite_what_the_reviewer_decided(page_dir):
    """The runtime replays a recorded action onto every later version, so the
    reviewer's edit stands over whatever v2's markup says about that widget.
    Which makes a rewritten widget a version talking to nobody — its new words
    could never reach the reader. `restated` is how a version says it means to
    take the decision back, and this is the gate that makes it say so."""
    v2 = _decided(page_dir, "Ship the flag dark, then backfill.")
    assert check(page_dir).exit_code == 0

    # Re-emitting what v1 said is the ordinary republish, and costs nothing:
    # the reviewer's edit is already on screen over it.
    v2("Ship the flag dark, then backfill.")
    assert check(page_dir, version=2).exit_code == 0, "a republish that changes nothing must pass"

    # Writing their own words back is the other quiet case, and the commoner
    # one: the version agrees with the edit rather than overruling it. A gate
    # that fired here would fire on almost every version an author writes, and
    # a gate that fires on correct work is one they learn to silence.
    v2("Cut the flag; backfill first.")
    assert check(page_dir, version=2).exit_code == 0, "honoring an edit must pass"

    # Rewriting the words under the edit is the case that needs a decision.
    v2("Ship the flag dark, then backfill. Roll back with one flag.")
    result = check(page_dir, version=2)
    assert result.exit_code == 1
    assert "its words changed" in result.output
    assert "edit on v1" in result.output
    assert "restated" in result.output

    # Said out loud, the same version publishes.
    v2("Ship the flag dark, then backfill. Roll back with one flag.", attrs=" restated")
    assert check(page_dir, version=2).exit_code == 0, "a restated rewrite is allowed"


def test_restating_on_the_first_version_is_refused(page_dir):
    """There is nothing before v1 to take back, so `restated` there can only be
    a misreading of what the word does — and one that would record a retraction
    of nothing into the log."""
    (page_dir / "versions" / "v1.html").write_text(
        PAGE.replace("<h2>Plan</h2>", '<h2>Plan</h2><cq-draft id="d1" restated>Words.</cq-draft>')
    )
    result = check(page_dir)
    assert result.exit_code == 1
    assert "nothing to retract" in result.output
    assert "recorded nothing on it" in result.output


def test_restating_a_widget_that_kept_its_words_is_refused(page_dir):
    """`restated` discards what the reviewer recorded, so a version may only
    spend it where there is a rewrite to justify it. Unpoliced, it is the one
    word that turns the gate back into the silence it replaced."""
    v2 = _decided(page_dir, "Ship the flag dark, then backfill.")
    v2("Ship the flag dark, then backfill.", attrs=" restated")
    result = check(page_dir, version=2)
    assert result.exit_code == 1
    assert "nothing to retract" in result.output
    assert "unchanged since v1" in result.output


def _board(todo, done):
    """A two-column board, each column given its cards as (id, attrs, title)."""
    card = lambda c: f'<cq-card id="{c[0]}"{c[1]}><strong>{c[2]}</strong></cq-card>'
    return (
        '<cq-board id="b1">'
        f'<cq-column id="c-todo" label="Todo">{"".join(map(card, todo))}</cq-column>'
        f'<cq-column id="c-done" label="Done">{"".join(map(card, done))}</cq-column>'
        "</cq-board>"
    )


X = ("card-x", "", "Guard the delete")
Y = ("card-y", "", "Wire the importer")


def test_the_gate_asks_about_the_card_that_was_moved_and_not_the_board(page_dir):
    """A `move` names the board, but what the reviewer decided about is the card:
    where it belongs. Holding the version to the board's whole contents would
    refuse it for editing an untouched card or adding a new one — a rule that
    fires on innocent versions is one authors learn to silence.

    So the subject is the card, and `restated` on it retracts that card's moves
    alone. The rest of the board stays where the reviewer put it, which is what
    keeps a typo fix from costing them an afternoon's arrangement."""
    def write(version, todo, done):
        (page_dir / "versions" / f"v{version}.html").write_text(
            PAGE.replace("<h2>Plan</h2>", "<h2>Plan</h2>" + _board(todo, done))
        )

    write(1, [X, Y], [])
    publish(page_dir)
    interact.append_event(page_dir, {"kind": "action", "author": "user", "version": 1,
                                     "widget": "b1", "action": "move",
                                     "detail": {"card": "card-x", "to": "c-done", "index": 0}})
    assert check(page_dir).exit_code == 0

    # An untouched card rewritten, the moved card's own words left alone.
    write(2, [X, ("card-y", "", "Wire the importer and its backfill")], [])
    assert check(page_dir, version=2).exit_code == 0, "an untouched card is not the gate's business"

    # The card written where the reviewer put it. Redundant now that replay
    # carries the move, but a version that does it anyway is not wrong.
    write(2, [Y], [X])
    assert check(page_dir, version=2).exit_code == 0, "relocating the moved card must pass"

    # The moved card's own words rewritten: now the decision is in question.
    write(2, [("card-x", "", "Guard the delete behind the flag"), Y], [])
    result = check(page_dir, version=2)
    assert result.exit_code == 1
    assert "card-x" in result.output and "move on v1" in result.output
    assert "card-y" not in result.output, "the gate named a card nobody had decided about"

    write(2, [("card-x", " restated", "Guard the delete behind the flag"), Y], [])
    assert check(page_dir, version=2).exit_code == 0

    # And the board itself never takes the attribute: every move names a card, so
    # a board is never what a decision rests on, and offering `restated` there
    # would be a door onto an error message about retracting nothing.
    (page_dir / "versions" / "v2.html").write_text(
        (page_dir / "versions" / "v2.html").read_text().replace('<cq-board id="b1">',
                                                                  '<cq-board id="b1" restated>')
    )
    result = check(page_dir, version=2)
    assert result.exit_code == 1
    assert "restated" in result.output and "cq-board" in result.output


OPTIONS = """<cq-options id="g1" choose>
  <cq-option id="o-shim"{a}><strong>Shim it</strong> {shim}</cq-option>
  <cq-option id="o-stage"{b}><strong>Migrate in stages</strong> {stage}</cq-option>
</cq-options>"""


def test_the_gate_reads_a_pick_the_same_way_it_reads_an_edit(page_dir):
    """The rule was built on drafts and boards; a pick is the case it was not
    built on. It lands the same way because nothing in it is per-widget: the
    subject is what the detail names, so a pick rests on the option picked. What
    the other options say is then free to change, and marking the pick `chosen`
    — the one thing every version does after a pick — says nothing, so it is
    invisible to the comparison.

    `effort` and `risk` do say something (x-says renders them as text the reviewer
    can select), so changing one on a picked option is changing what they picked.
    The gate reads the version the way the anchor pass does, which is what keeps
    that true without anything here knowing those two attributes exist."""
    def write(version, **kw):
        opts = OPTIONS.format(**{"a": "", "b": "", "shim": "Fastest to ship.",
                                 "stage": "Table by table.", **kw})
        (page_dir / "versions" / f"v{version}.html").write_text(
            PAGE.replace("<h2>Plan</h2>", "<h2>Plan</h2>" + opts)
        )

    write(1)
    publish(page_dir)
    interact.append_event(page_dir, {"kind": "action", "author": "user", "version": 1,
                                     "widget": "g1", "action": "choose",
                                     "detail": {"option": "o-shim"}})
    assert check(page_dir).exit_code == 0

    # The record the next version owes: the picked card marked, nothing else.
    write(2, a=" chosen")
    assert check(page_dir, version=2).exit_code == 0, "marking the pick is not a rewrite"

    # An option nobody picked, rewritten freely.
    write(2, a=" chosen", stage="One table at a time, behind a flag.")
    assert check(page_dir, version=2).exit_code == 0, "an unpicked option is free to change"

    # The picked one, rewritten — the reviewer chose those words.
    write(2, a=" chosen", shim="Fastest to ship, and we own the shim forever.")
    result = check(page_dir, version=2)
    assert result.exit_code == 1
    assert "o-shim" in result.output and "choose on v1" in result.output

    write(2, a=" chosen restated", shim="Fastest to ship, and we own the shim forever.")
    assert check(page_dir, version=2).exit_code == 0

    # An x-says attribute is a word on the page: "low" becoming "high" on the
    # option they picked reads to them as the option changing, and is caught the
    # same way its prose is.
    write(2, a=' chosen effort="high"')
    result = check(page_dir, version=2)
    assert result.exit_code == 1, "an x-says attribute is words the reviewer read"
    assert "o-shim" in result.output

    write(2, a=' chosen restated effort="high"')
    assert check(page_dir, version=2).exit_code == 0


def test_a_cleared_pick_rests_on_the_group_that_holds_it(page_dir):
    """Clearing a pick names no option (`{"option": null}`), so there is no part
    of the widget for the decision to rest on and it rests on the group. That
    falls out of the subject rule rather than being written for this case — which
    is why the group takes `restated` and a board, whose every move names a card,
    does not."""
    def write(version, shim="Fastest to ship.", attrs=""):
        opts = OPTIONS.format(a="", b="", shim=shim, stage="Table by table.")
        (page_dir / "versions" / f"v{version}.html").write_text(
            PAGE.replace("<h2>Plan</h2>", "<h2>Plan</h2>" + opts.replace(
                '<cq-options id="g1" choose>', f'<cq-options id="g1" choose{attrs}>'))
        )

    write(1)
    publish(page_dir)
    interact.append_event(page_dir, {"kind": "action", "author": "user", "version": 1,
                                     "widget": "g1", "action": "choose",
                                     "detail": {"option": None}})
    write(2, shim="Fastest to ship, and we own the shim forever.")
    result = check(page_dir, version=2)
    assert result.exit_code == 1
    assert "cq-options id='g1'" in result.output

    write(2, shim="Fastest to ship, and we own the shim forever.", attrs=" restated")
    assert check(page_dir, version=2).exit_code == 0


def test_a_version_may_not_quietly_move_the_pick(page_dir):
    """The words gate can't see `chosen` — the attribute says nothing — so this
    is the state gate's own case: a version marking a different option than the
    reviewer picked is overruling them as surely as a rewrite is, and says so
    with the group's `restated` or not at all. After the retraction the state is
    the author's again: the next version moves the pick freely, because a unit
    with no surviving folded action is exempt — that exemption is what keeps
    the retract-and-ask-again flow from deadlocking one version later."""
    def write(version, a="", b="", attrs="", shim="Fastest to ship."):
        opts = OPTIONS.format(a=a, b=b, shim=shim, stage="Table by table.")
        (page_dir / "versions" / f"v{version}.html").write_text(
            PAGE.replace("<h2>Plan</h2>", "<h2>Plan</h2>" + opts.replace(
                '<cq-options id="g1" choose>', f'<cq-options id="g1" choose{attrs}>'))
        )

    write(1)
    publish(page_dir)
    interact.append_event(page_dir, {"kind": "action", "author": "user", "version": 1,
                                     "widget": "g1", "action": "choose",
                                     "detail": {"option": "o-shim"}})

    # The author's markup contradicting the recorded pick, words untouched.
    write(2, b=" chosen")
    result = check(page_dir, version=2)
    assert result.exit_code == 1
    assert "its state changed" in result.output
    assert "'o-stage'" in result.output and "'o-shim'" in result.output

    # Said out loud — on the group, the unit the fold keys the pick by.
    write(2, b=" chosen", attrs=" restated")
    assert check(page_dir, version=2).exit_code == 0, check(page_dir, version=2).output
    result = CliRunner().invoke(
        interact.cli, ["note", str(page_dir), "--version", "2", "--text", "moved the default"]
    )
    assert result.exit_code == 0, result.output

    # The retraction handed the state back: v3 owns it, no ritual to repeat.
    write(3, a=" chosen")
    assert check(page_dir, version=3).exit_code == 0, check(page_dir, version=3).output

    # And the words gate agrees the pick is dead: the group's retraction floors
    # everything resting inside it, so rewriting the once-picked option's words
    # is free — one key space for liveness, or the gate would demand a second
    # `restated` for a decision the browser already dropped.
    publish(page_dir, 3)
    write(4, a=" chosen", shim="Fastest to ship, and the shim is ours to keep.")
    assert check(page_dir, version=4).exit_code == 0, check(page_dir, version=4).output


def test_check_reports_record_lag_without_erroring(page_dir):
    """Silence is blessed — replay resolves it — but a log-less reader sees only
    the markup, so `check` says where it lags the log, as advice on a passing
    run. `export` says the same to stderr, where the debt stops being fixable."""
    def write(version, a=""):
        opts = OPTIONS.format(a=a, b="", shim="Fastest to ship.", stage="Table by table.")
        (page_dir / "versions" / f"v{version}.html").write_text(
            PAGE.replace("<h2>Plan</h2>", "<h2>Plan</h2>" + opts)
        )

    write(1)
    publish(page_dir)
    interact.append_event(page_dir, {"kind": "action", "author": "user", "version": 1,
                                     "widget": "g1", "action": "choose",
                                     "detail": {"option": "o-shim"}})
    write(2)
    result = check(page_dir, version=2)
    assert result.exit_code == 0
    assert "record behind the log" in result.output
    assert "g1" in result.output and "o-shim" in result.output

    # Honored, the debt is gone and so is the advice.
    write(2, a=" chosen")
    result = check(page_dir, version=2)
    assert result.exit_code == 0
    assert "record behind the log" not in result.output

    result = CliRunner().invoke(interact.cli, ["export", str(page_dir)])
    assert "record behind the log" in result.output  # CliRunner folds stderr in


def test_an_accept_carries_its_thread_resolution(page_dir):
    """One atomic event: the accept snapshots the thread it answers, because the
    honoring version retires the wrapper that held the `resolves` mapping and a
    second POST could fail alone. A reject answers nothing."""
    interact.append_event(page_dir, {"kind": "comment", "id": "c1", "author": "user",
                                     "text": "cameras are flaky"})
    interact.append_event(page_dir, {"kind": "comment", "id": "c2", "author": "user",
                                     "text": "and the other thing"})
    interact.append_event(page_dir, {"kind": "action", "author": "user", "version": 1,
                                     "widget": "sug-a", "action": "accept",
                                     "detail": {"resolves": "c1"}})
    interact.append_event(page_dir, {"kind": "action", "author": "user", "version": 1,
                                     "widget": "sug-b", "action": "reject", "detail": {}})
    threads = interact.build_threads(interact.read_events(page_dir))
    assert threads["c1"]["resolved"] is True
    assert threads["c2"]["resolved"] is False


def test_init_refuses_a_log_the_incoming_layer_no_longer_speaks(page_dir):
    """The log is append-only and a retired verb has no successor to map to, so
    re-vendoring over one is how recorded decisions fall silent — annabels-drafts
    holds fifteen `decide` events today's widgets would drop on the first reload.
    The choice is the human's, made loudly."""
    interact.append_event(page_dir, {"kind": "action", "author": "user", "version": 1,
                                     "widget": "d1", "action": "decide",
                                     "detail": {"decision": "approved"}})
    result = CliRunner().invoke(interact.cli, ["init", str(page_dir)])
    assert result.exit_code != 0
    assert "no longer speaks" in result.output
    assert "decide" in result.output
    result = CliRunner().invoke(interact.cli, ["init", str(page_dir), "--retire-vocabulary"])
    assert result.exit_code == 0, result.output


def test_a_stampless_overlay_reads_as_the_pre_stamp_vocabulary(page_dir, tmp_path):
    """A user or project overlay predating the stamp replaces registry.json
    wholesale, so the incoming layer arrives with no $events — which means the
    pre-stamp vocabulary, not an empty one. Plain comments pass; only genuinely
    retired vocabulary refuses."""
    overlay = tmp_path / ".claude" / "colloquy"
    overlay.mkdir(parents=True)
    reg = json.loads((page_dir / "registry.json").read_text())
    del reg["$events"]
    for entry in reg.values():
        if isinstance(entry, dict):
            entry.pop("x-state", None)
    (overlay / "registry.json").write_text(json.dumps(reg))

    interact.append_event(page_dir, {"kind": "comment", "author": "user", "text": "hm"})
    interact.append_event(page_dir, {"kind": "action", "author": "user", "version": 1,
                                     "widget": "g1", "action": "choose",
                                     "detail": {"option": "o-shim"}})
    result = CliRunner().invoke(interact.cli, ["init", str(page_dir)])
    assert result.exit_code == 0, result.output

    interact.append_event(page_dir, {"kind": "action", "author": "user", "version": 1,
                                     "widget": "d1", "action": "decide",
                                     "detail": {"decision": "approved"}})
    result = CliRunner().invoke(interact.cli, ["init", str(page_dir)])
    assert result.exit_code != 0
    assert "decide" in result.output and "comment" not in result.output


def test_note_refuses_a_restated_shape_an_old_layer_would_drop(page_dir):
    """The bin shim runs the newest CLI against pages vendored at any age, and an
    old runtime keys retractions off a shape it doesn't read — so the write site
    is where the drift is caught. A stampless registry predates the stamp, and
    the pre-stamp vocabulary is exactly what it reads: plain notes pass, a
    retraction-carrying one is refused until `init` re-vendors."""
    v2 = _decided(page_dir, "Ship the flag dark, then backfill.")
    v2("Ship the flag dark, then backfill. Roll back with one flag.", attrs=" restated")

    reg = json.loads((page_dir / "registry.json").read_text())
    stamped = dict(reg)
    del reg["$events"]
    (page_dir / "registry.json").write_text(json.dumps(reg))
    result = CliRunner().invoke(
        interact.cli, ["note", str(page_dir), "--version", "2", "--text", "rewrote it"]
    )
    assert result.exit_code != 0
    assert "predates" in result.output

    (page_dir / "registry.json").write_text(json.dumps(stamped))
    result = CliRunner().invoke(
        interact.cli, ["note", str(page_dir), "--version", "2", "--text", "rewrote it"]
    )
    assert result.exit_code == 0, result.output


def test_a_widget_nobody_has_touched_is_not_the_gate_s_business(page_dir):
    """The gate is about decisions, so it holds nothing against a version that
    rewrites a widget the reviewer never acted on."""
    (page_dir / "versions" / "v1.html").write_text(
        PAGE.replace("<h2>Plan</h2>", '<h2>Plan</h2><cq-draft id="d1">First words.</cq-draft>')
    )
    publish(page_dir)
    (page_dir / "versions" / "v2.html").write_text(
        PAGE.replace("<h2>Plan</h2>", '<h2>Plan</h2><cq-draft id="d1">Quite different words.</cq-draft>')
    )
    assert check(page_dir, version=2).exit_code == 0


def test_check_requires_the_vendored_layer(tmp_path):
    d = tmp_path / "bare"
    (d / "versions").mkdir(parents=True)
    (d / "versions" / "v1.html").write_text(PAGE)
    result = check(d)
    assert result.exit_code == 1
    assert "run `init` to vendor the layer" in result.output


def test_check_takes_column_width_from_vendored_theme(page_dir):
    # theme.css sets a 760px main column; a wider fixed-width element must fail.
    (page_dir / "versions" / "v1.html").write_text(
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
    status, _ = fetch(f"{server}/versions/v1.html")
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
    assert state["versions"] == ["v1.html"]
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
        {"kind": "comment"},  # no text: a blank thread nobody can read
        {"kind": "reply", "parent": "nope", "text": "hi"},  # parent names no message
        {"kind": "resolve", "parent": "nope"},
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
    # Delivered means delivered: the cursor has moved past them, so nothing is pending.
    assert interact.read_json(page_dir / "cursor.json")["seq"] == 2
    assert interact.full_state(page_dir)["pending"] == 0
    # The delivery status is marked a handoff, which dates the claim: Claude's own
    # `status` clears the mark, so the mark surviving is a pickup that never landed.
    status = interact.read_json(page_dir / "status.json")
    assert (status["state"], status["handoff"]) == ("working", True)
    interact.cmd_status(page_dir, "working", "revising the plan")
    assert "handoff" not in interact.read_json(page_dir / "status.json")


def test_wait_restarts_a_server_that_died_under_it(page_dir, capsys):
    """A page whose server died is offline in the reviewer's browser and nowhere
    else — so `wait`, the one thing positioned to notice, brings it back rather
    than exiting and leaving the discovery to the reviewer."""

    def comment_once_served():
        for _ in range(100):
            time.sleep(0.1)
            if interact.running_server(page_dir):
                interact.append_event(page_dir, {"kind": "comment", "author": "user", "text": "hi"})
                return

    threading.Thread(target=comment_once_served, daemon=True).start()
    try:
        assert interact.cmd_wait(page_dir) == 0  # no server.json at all when it starts
        info = interact.running_server(page_dir)
        assert info and urllib.request.urlopen(info["url"] + "api/state").status == 200
        assert "server had died; restarted" in capsys.readouterr().err
    finally:
        interact.cmd_stop(page_dir)


def test_wait_leaves_a_closed_review_down(page_dir):
    """SessionEnd idles the page and stops its server, so a watcher still winding
    down must not put it straight back up."""
    interact.cmd_status(page_dir, "idle", "the session that opened this page has ended")
    assert interact.cmd_wait(page_dir) == 2
    assert interact.running_server(page_dir) is None


@pytest.fixture
def claimed(page_dir, monkeypatch):
    """A page claimed by session s1, the way Claude Code's environment claims one:
    it puts the session id and its pid into every Bash tool call."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s1")
    monkeypatch.setenv("CLAUDE_PID", str(os.getpid()))
    interact.claim_page(page_dir)
    return page_dir


def test_stop_hook_blocks_a_turn_that_leaves_a_page_unwatched(claimed, capsys):
    """Between turns a page is either watched or idle. The failure this prevents:
    a `wait` exits, its notification is buried behind the next thing the user
    types, and the page keeps saying "Claude is working" over nobody."""
    interact.cmd_status(claimed, "waiting", "")
    interact.cmd_hook({"hook_event_name": "Stop", "session_id": "s1"})
    answer = json.loads(capsys.readouterr().out)
    assert answer["decision"] == "block"
    assert "no watcher" in answer["reason"] and str(claimed) in answer["reason"]

    # Blocking twice in a row is how a Stop hook loops, so a block already in
    # flight stands down.
    interact.cmd_hook({"hook_event_name": "Stop", "session_id": "s1", "stop_hook_active": True})
    assert capsys.readouterr().out == ""

    # A live watcher, and a closed review, each end the turn cleanly.
    interact.write_json(claimed / "heartbeat.json", {"t": time.time()})
    interact.cmd_hook({"hook_event_name": "Stop", "session_id": "s1"})
    assert capsys.readouterr().out == ""
    (claimed / "heartbeat.json").unlink()
    interact.cmd_status(claimed, "idle", "")
    interact.cmd_hook({"hook_event_name": "Stop", "session_id": "s1"})
    assert capsys.readouterr().out == ""

    # A page a second session has since picked up is that session's to watch, so
    # s1 is no longer held to it.
    interact.cmd_status(claimed, "waiting", "")
    interact.write_json(claimed / "session.json", {"id": "s2", "pid": os.getpid(), "ts": "t"})
    interact.cmd_hook({"hook_event_name": "Stop", "session_id": "s1"})
    assert capsys.readouterr().out == ""


def test_prompt_hook_surfaces_comments_claude_never_picked_up(claimed, capsys):
    interact.cmd_status(claimed, "working", "revising")
    interact.append_event(claimed, {"kind": "comment", "author": "user", "text": "hi"})
    assert interact.full_state(claimed)["pending"] == 1
    interact.cmd_hook({"hook_event_name": "UserPromptSubmit", "session_id": "s1"})
    context = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
    assert "1 user event you haven't picked up" in context

    # Not while a watcher is live: it delivers them itself, and sending Claude to
    # start a second `wait` would race the cursor and deliver everything twice.
    interact.write_json(claimed / "heartbeat.json", {"t": time.time()})
    interact.cmd_hook({"hook_event_name": "UserPromptSubmit", "session_id": "s1"})
    assert capsys.readouterr().out == ""


def test_only_serving_or_watching_a_page_puts_the_session_under_the_guard(
    page_dir, monkeypatch, capsys
):
    """Verifying a change to the page layer means driving throwaway pages, and the
    guard must not read a handful of test fixtures as a handful of abandoned
    reviews. A directory this session only built and linted was handed to nobody.
    Listening on one is what puts a reviewer on the other end, and from there the
    guard holds the session to it."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s7")
    monkeypatch.setenv("CLAUDE_PID", str(os.getpid()))
    assert check(page_dir).exit_code == 0
    assert CliRunner().invoke(interact.cli, ["catalog", str(page_dir)]).exit_code == 0
    assert interact.session_pages("s7") == []
    # `init` left the page "working", which is the state the guard blocks on — but
    # only for a page some session answers for, and none does.
    interact.cmd_hook({"hook_event_name": "Stop", "session_id": "s7"})
    assert capsys.readouterr().out == ""

    interact.append_event(page_dir, {"kind": "comment", "author": "user", "text": "hi"})
    assert CliRunner().invoke(interact.cli, ["wait", str(page_dir)]).exit_code == 0
    assert interact.session_pages("s7") == [page_dir.resolve()]
    interact.cmd_hook({"hook_event_name": "Stop", "session_id": "s7"})
    assert "no watcher" in json.loads(capsys.readouterr().out)["reason"]


def test_hook_scripts_agree_with_interact_on_homes(tmp_path, monkeypatch):
    """review-guard.py, plan-mode-redirect.py, and plans.py run under plain
    python3, so they inline the XDG resolution interact.py owns rather than
    importing the uv script; this holds the copies to it."""
    root = Path(__file__).parent.parent

    def load(path):
        spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    for env in (
        {},
        {"XDG_CONFIG_HOME": str(tmp_path / "cfg"), "XDG_STATE_HOME": str(tmp_path / "st")},
    ):
        for key in ("XDG_CONFIG_HOME", "XDG_STATE_HOME"):
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        guard = load(root / "hooks" / "scripts" / "review-guard.py")
        redirect = load(root / "hooks" / "scripts" / "plan-mode-redirect.py")
        plans = load(root / "scripts" / "plans.py")
        assert guard.SESSIONS == interact.state_home() / "sessions"
        assert redirect.CONFIG == plans.CONFIG == interact.config_home() / "config.json"


def test_idle_cannot_close_a_review_over_events_nobody_read(claimed, capsys):
    """`status idle` is the way out of the guard's other case, so it reads as the
    way out of this one too. The events are the reviewer's: a page idled over them
    ends the review on someone still waiting for an answer, and from the browser
    that looks exactly like a review that ran its course."""
    interact.append_event(claimed, {"kind": "comment", "author": "user", "text": "hi"})
    refused = CliRunner().invoke(interact.cli, ["status", str(claimed), "idle"])
    assert refused.exit_code == 1
    assert "1 user event nobody has picked up" in refused.output
    assert interact.read_json(claimed / "status.json")["state"] != "idle"

    # `wait` is the way through, and it returns at once when events already wait.
    assert CliRunner().invoke(interact.cli, ["wait", str(claimed)]).exit_code == 0
    assert CliRunner().invoke(interact.cli, ["status", str(claimed), "idle"]).exit_code == 0
    interact.cmd_hook({"hook_event_name": "Stop", "session_id": "s1"})
    assert capsys.readouterr().out == ""


def test_session_end_idles_the_page_and_stops_its_server(claimed):
    assert interact.revive_server(claimed)  # a real detached server to clean up
    interact.cmd_status(claimed, "waiting", "")
    interact.cmd_hook({"hook_event_name": "SessionEnd", "session_id": "s1"})
    assert interact.read_json(claimed / "status.json")["state"] == "idle"
    assert interact.running_server(claimed) is None
    assert interact.session_pages("s1") == []


def test_state_reports_whether_the_owning_session_still_exists(claimed):
    """The banner's one hard fact: a status.json claim outlives its session, the
    owning pid doesn't."""
    assert interact.full_state(claimed)["session_alive"] is True
    dead = subprocess.Popen([sys.executable, "-c", ""])
    dead.wait()
    interact.write_json(claimed / "session.json", {"id": "s1", "pid": dead.pid, "ts": "t"})
    assert interact.full_state(claimed)["session_alive"] is False


def test_versions_publish_only_once_noted(page_dir):
    assert interact.published_versions(page_dir) == []
    assert interact.full_state(page_dir)["versions"] == []
    result = CliRunner().invoke(
        interact.cli, ["note", str(page_dir), "--version", "1", "--text", "first cut"]
    )
    assert result.exit_code == 0, result.output
    assert interact.published_versions(page_dir) == ["v1.html"]
    # The next version stays unpublished until its own note lands.
    (page_dir / "versions" / "v2.html").write_text(PAGE)
    assert interact.published_versions(page_dir) == ["v1.html"]


def test_versions_run_in_number_order_past_v9(page_dir):
    """Everything downstream reads "the latest version" off the end of this list —
    what `note` lints against, what the server redirects to, what `check` diffs
    the new version with. Sorted as names, v10 would land before v2 and every one
    of those would quietly answer with the wrong version."""
    for n in range(2, 12):
        (page_dir / "versions" / f"v{n}.html").write_text(PAGE)
    assert interact.list_versions(page_dir) == [f"v{n}.html" for n in range(1, 12)]
    for n in range(1, 12):
        result = CliRunner().invoke(
            interact.cli, ["note", str(page_dir), "--version", str(n), "--text", f"cut {n}"]
        )
        assert result.exit_code == 0, result.output
    assert interact.published_versions(page_dir) == [f"v{n}.html" for n in range(1, 12)]


def test_choose_requires_an_id(page_dir):
    # Actions name their widget by id, so an interactive group can't go without one.
    registry = interact.load_registry(page_dir)
    errs = interact.fragment_errors(
        '<cq-options choose><cq-option id="o1"><strong>A</strong></cq-option></cq-options>',
        registry,
    )
    assert errs and "'id' is a dependency of 'choose'" in " ".join(errs)


def test_specimen_admits_interactive_widgets(page_dir):
    # The registry marks a specimen's content quoted; the runtime leaves the
    # interactive widgets inside unwired. Validation is unchanged by the
    # wrapper: nesting rules (cq-option under cq-options) still hold.
    registry = interact.load_registry(page_dir)
    errs = interact.fragment_errors(
        '<cq-specimen id="sp" label="a decision">'
        '<cq-options id="g" choose><cq-option id="o1"><strong>A</strong></cq-option></cq-options>'
        '<cq-board id="b"><cq-column id="c" label="To do">'
        '<cq-card id="k"><strong>Card</strong></cq-card></cq-column></cq-board>'
        "</cq-specimen>",
        registry,
    )
    assert errs == []


def test_settling_a_decision_drops_no_ids(page_dir):
    """Retiring a settled decision is a collapse, not a deletion — which is the
    whole reason it's expressible: `check` forbids dropping an id, and the
    alternatives behind the disclosure keep both their ids and the anchors on
    them. A group can't be settled without an id either; the reader's open/closed
    state is remembered against it."""
    registry = interact.load_registry(page_dir)
    assert "'id' is a dependency of 'settled'" in " ".join(
        interact.fragment_errors(
            '<cq-options settled><cq-option id="o1"><strong>A</strong></cq-option></cq-options>',
            registry,
        )
    )

    group = '<cq-options id="pick" choose{}><cq-option id="opt-a"{}><strong>A</strong></cq-option>'
    group += '<cq-option id="opt-b"><strong>B</strong></cq-option></cq-options>'
    (page_dir / "versions" / "v1.html").write_text(PAGE.replace("</main>", group.format("", "") + "</main>"))
    publish(page_dir)
    (page_dir / "versions" / "v2.html").write_text(
        PAGE.replace("</main>", group.format(" settled", " chosen") + "</main>")
    )
    assert interact.cmd_check(page_dir, 2) == 0

    # Deleting the alternatives instead is what check is there to stop.
    (page_dir / "versions" / "v2.html").write_text(PAGE)
    assert interact.cmd_check(page_dir, 2) == 1


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
        (d / "versions" / "v1.html").write_text(example.read_text())
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
    (page_dir / "versions" / "v2.html").write_text(
        PAGE.replace('<section id="plan">', '<section id="plan"><p id="q1">stolen</p>')
    )
    result = check(page_dir, version=2)
    assert result.exit_code == 1
    assert "taken by widget markup in a reply" in result.output and "q1" in result.output


def test_the_runtimes_cq_id_namespace_is_off_limits(page_dir):
    """colloquy.js coins document ids under cq- for its own chrome — cq-msg-<event> on a
    message body, cq-composer-quote — and points ARIA at them. An authored id there would
    aim those references at the page instead, silently. One rule over both places an id
    can be authored: a version, and the widget markup in Claude's reply."""
    (page_dir / "versions" / "v2.html").write_text(
        PAGE.replace('<section id="plan">', '<section id="plan"><p id="cq-msg-7">mine</p>')
    )
    result = check(page_dir, version=2)
    assert result.exit_code == 1
    assert "cq- namespace" in result.output and "cq-msg-7" in result.output

    interact.append_event(page_dir, {"kind": "comment", "id": "c1", "author": "user", "text": "hm"})
    reply = CliRunner().invoke(
        interact.cli,
        ["reply", str(page_dir), "--to", "c1", "--text",
         '<cq-options id="cq-pick" choose><cq-option id="o1"><strong>A</strong></cq-option></cq-options>'],
    )
    assert reply.exit_code != 0
    assert "cq- namespace" in reply.output and "cq-pick" in reply.output


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
    (page_dir / "versions" / "v1.html").write_text(PAGE.replace("</section>", ""))
    result = CliRunner().invoke(
        interact.cli, ["note", str(page_dir), "--version", "1", "--text", "broken"]
    )
    assert result.exit_code != 0
    assert "refusing to publish" in result.output
    assert interact.published_versions(page_dir) == []


# ---------- comment: the anchor written without a browser ----------


def published(page_dir):
    assert CliRunner().invoke(
        interact.cli, ["note", str(page_dir), "--version", "1", "--text", "first"]
    ).exit_code == 0
    return page_dir


def comment(page_dir, *args):
    return CliRunner().invoke(interact.cli, ["comment", str(page_dir), *args])


def test_comment_anchors_on_a_quote_and_posts_as_claude(page_dir):
    result = comment(published(page_dir), "--quote", "Ship dark", "--text", "dark for how long?")
    assert result.exit_code == 0, result.output
    event = json.loads(result.output)
    assert event["kind"] == "comment" and event["author"] == "claude" and event["version"] == 1
    assert event["anchor"]["quote"] == "Ship dark"
    # The section is derived the way the browser derives it — the nearest enclosing id.
    assert event["anchor"]["section"] == "flag-first"
    assert event["text"] == "dark for how long?"


def test_a_comment_carries_the_neighbours_that_tell_two_copies_apart(page_dir):
    """The context is the whole reason a later version can't hand the comment to another
    copy of the same words, so a written anchor stores it exactly as a selection does."""
    event = json.loads(comment(published(page_dir), "--quote", "Verify, then flip", "--text", "ok").output)
    anchor = event["anchor"]
    # Read out of the whole collapsed text and stopped by the fences around the option
    # row — the runtime writes controls between options, words this reading doesn't
    # hold. The runtime reads its side back the same way, and only a full match counts.
    assert anchor["prefix"] == "med Backfill first"
    assert anchor["suffix"] == ". low"  # the option's risk, said at its trailing edge


def test_a_quote_closing_its_section_stores_the_next_sections_words(page_dir):
    """A suffix clipped at the section's edge could be one character, a bar an identical
    copy elsewhere might clear; the whole reading gives a closing passage a full side.
    The section the anchor names scopes where the search may land, never what surrounds
    the passage."""
    two = PAGE.replace(
        '  <cq-diagram id="flow">\ngraph LR\n  A --> B\n  </cq-diagram>\n',
        "  <p>Deploys pause overnight.</p>\n",
    ).replace(
        "</main>",
        '<section id="rollout">\n  <p>The rollout resumes.</p>\n</section>\n</main>',
    )
    (page_dir / "versions" / "v1.html").write_text(two)
    event = json.loads(
        comment(published(page_dir), "--quote", "Deploys pause overnight.", "--text", "x").output
    )
    assert event["anchor"]["section"] == "plan"
    assert event["anchor"]["suffix"] == "The rollout resumes."


def test_a_comment_refuses_a_quote_the_version_does_not_hold(page_dir):
    result = comment(published(page_dir), "--quote", "ship it on Friday", "--text", "x")
    assert result.exit_code != 0
    assert "doesn't say" in result.output


def test_a_comment_refuses_a_quote_the_version_holds_twice(page_dir):
    """Which copy was meant is a question with an answer, and there is someone to ask.
    The browser has to guess because the reviewer has already gone; this doesn't."""
    twice = PAGE.replace("<h2>Plan</h2>", "<h2>Plan</h2>\n  <p>Ship dark.</p>")
    (page_dir / "versions" / "v1.html").write_text(twice)
    result = comment(published(page_dir), "--quote", "Ship dark", "--text", "x")
    assert result.exit_code != 0
    assert "2 times" in result.output
    # Scoping it to one of them is the way out the message offers.
    scoped = comment(page_dir, "--quote", "Ship dark", "--section", "flag-first", "--text", "x")
    assert scoped.exit_code == 0, scoped.output
    assert json.loads(scoped.output)["anchor"]["section"] == "flag-first"


def test_a_widgets_data_body_is_not_quotable_but_the_widget_is(page_dir):
    """A diagram's source is a picture by the time the reader sees it, so quoting the
    source anchors on text no search will find. Pointing at the element is what a click
    on that diagram does in the browser, and that is the anchor offered instead."""
    body = comment(published(page_dir), "--quote", "graph LR", "--text", "x")
    assert body.exit_code != 0 and "--section" in body.output
    element = comment(page_dir, "--section", "flow", "--text", "the retry edge is missing")
    assert element.exit_code == 0, element.output
    assert json.loads(element.output)["anchor"] == {"section": "flow"}


def test_a_quote_may_not_run_across_a_widgets_parts(page_dir):
    """A module writes words of its own where the file has none — a cq-ref is empty in the
    source and renders the reference it links to, a column gets a heading, a milestone a
    row of chips. A quote spanning one of those joins would resolve to nothing in the
    reviewer's browser, so it's refused here, where someone can still do something about
    it. Either side of the join quotes fine."""
    published(page_dir)
    across = comment(page_dir, "--quote", "The cutoff lives in .", "--text", "x")
    assert across.exit_code != 0
    assert "across a widget's parts" in across.output
    assert comment(page_dir, "--quote", "The cutoff lives in", "--text", "x").exit_code == 0


DRAFTED = PAGE.replace(
    "<h2>Plan</h2>",
    '<h2>Plan</h2>\n  <cq-draft id="note">\nAdds --dry-run to every mutating command.\n  </cq-draft>',
)


def drafted(page_dir):
    """A published v1 carrying the note draft, its body still Claude's."""
    (page_dir / "versions" / "v1.html").write_text(DRAFTED)
    return published(page_dir)


def edit(page_dir, text, widget="note", version=1):
    interact.append_event(
        page_dir,
        {"kind": "action", "author": "user", "version": version, "widget": widget,
         "action": "edit", "detail": {"text": text}},
    )


def test_a_verbatim_body_is_quotable_where_a_source_body_is_not(page_dir):
    """The registry draws the line: cq-draft renders the authored text into a plain div
    the anchor pass can see (x-verbatim), and cq-diagram renders a picture instead."""
    result = comment(drafted(page_dir), "--quote", "every mutating command", "--text", "which ones?")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["anchor"]["section"] == "note"


def test_an_edited_draft_reads_as_the_reviewers_words(page_dir):
    """An `edit` is absolute — the log carries the whole new body, and replay writes
    exactly that into the DOM the anchor pass searches — so the reading `comment`
    captures against holds the reviewer's words in the authored body's place:
    quotable, collapsed like any passage, genuinely adjacent to the prose around
    them (no fence — the screen shows that adjacency too)."""
    drafted(page_dir)
    edit(page_dir, "Adds --dry-run to purge\nand rebuild only.")
    result = comment(page_dir, "--quote", "purge and rebuild only", "--text", "x")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["anchor"]["section"] == "note"
    across = comment(page_dir, "--quote", "Plan Adds --dry-run to purge", "--text", "x")
    assert across.exit_code == 0, across.output


def test_a_quote_of_words_an_edit_replaced_is_refused_naming_the_edit(page_dir):
    """The authored body is still in the file, but the reviewer is no longer reading
    it — posted, the comment would detach in front of them. Refused at write time
    naming what removed the words, the retired slot's own treatment; a quote merely
    reaching into the replaced body from outside is the same detachment."""
    drafted(page_dir)
    edit(page_dir, "Adds --dry-run to purge and rebuild only.")
    result = comment(page_dir, "--quote", "every mutating command", "--text", "x")
    assert result.exit_code != 0
    assert "rewrote § note" in result.output and "their edit" in result.output
    across = comment(page_dir, "--quote", "Plan Adds --dry-run to every", "--text", "x")
    assert across.exit_code != 0 and "rewrote § note" in across.output


def test_a_restated_draft_takes_the_pen_back_from_the_reading(page_dir):
    """`restated` retracts the edit, so replay stops painting it and the reading
    returns to the version as authored: the new body quotable, the retracted edit's
    text nowhere — not even a refusal names it, since nothing removed it from this
    version's page. A fresh edit on the new version stands again."""
    drafted(page_dir)
    edit(page_dir, "Adds --dry-run to purge and rebuild only.")
    revised = DRAFTED.replace(
        '<cq-draft id="note">\nAdds --dry-run to every mutating command.',
        '<cq-draft id="note" restated>\nOnly purge gets a dry-run; the rest apply live.',
    )
    (page_dir / "versions" / "v2.html").write_text(revised)
    noted = CliRunner().invoke(
        interact.cli, ["note", str(page_dir), "--version", "2", "--text", "took the pen back"]
    )
    assert noted.exit_code == 0, noted.output
    kept = comment(page_dir, "--quote", "the rest apply live", "--text", "x")
    assert kept.exit_code == 0, kept.output
    gone = comment(page_dir, "--quote", "purge and rebuild only", "--text", "x")
    assert gone.exit_code != 0 and "doesn't say" in gone.output
    edit(page_dir, "Fine, but default the flag on.", version=2)
    again = comment(page_dir, "--quote", "default the flag on", "--text", "x")
    assert again.exit_code == 0, again.output


def test_a_verb_the_registry_no_longer_speaks_moves_nothing(page_dir):
    """The registry is the gate, not the payload's shape: a logged action whose
    verb this page's vendored x-state doesn't declare — a verb a later layer
    retired — folds to nothing, so the reading stays the version as authored
    rather than trusting whatever text the event carried."""
    drafted(page_dir)
    interact.append_event(
        page_dir,
        {"kind": "action", "author": "user", "version": 1, "widget": "note",
         "action": "scribble", "detail": {"text": "Words no layer speaks."}},
    )
    kept = comment(page_dir, "--quote", "every mutating command", "--text", "x")
    assert kept.exit_code == 0, kept.output
    gone = comment(page_dir, "--quote", "Words no layer speaks", "--text", "x")
    assert gone.exit_code != 0 and "doesn't say" in gone.output


def test_an_unhonored_edit_outlives_a_republish(page_dir):
    """v2 re-emits the authored body with no `restated`, so the reviewer's words
    still stand over it — replay carries them, and the reading follows: silence
    retracts nothing. This is the drift the whole mechanism closes: the file holds
    words the page stopped showing a version ago."""
    drafted(page_dir)
    edit(page_dir, "Adds --dry-run to purge and rebuild only.")
    (page_dir / "versions" / "v2.html").write_text(DRAFTED)
    noted = CliRunner().invoke(
        interact.cli, ["note", str(page_dir), "--version", "2", "--text", "changes elsewhere"]
    )
    assert noted.exit_code == 0, noted.output
    kept = comment(page_dir, "--quote", "purge and rebuild only", "--text", "x")
    assert kept.exit_code == 0, kept.output
    gone = comment(page_dir, "--quote", "every mutating command", "--text", "x")
    assert gone.exit_code != 0 and "rewrote § note" in gone.output


def test_a_widgets_x_says_attribute_is_quotable_like_any_other_passage(page_dir):
    """renderSaid puts these words in the DOM, so the anchor pass can find them and this
    has to offer them — otherwise a metric's own number is the one thing on the page
    Claude can't point at. Each lands at the edge the registry gives it: this option's
    effort ("med") opens it and its risk ("low") closes it."""
    published(page_dir)
    for quote in ("med Backfill first", "then flip. low"):
        result = comment(page_dir, "--quote", quote, "--text", "x")
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["anchor"]["section"] == "backfill-first"


SUGGESTED = PAGE.replace("<cq-options>", SUGGESTION)


def suggested(page_dir):
    """A published v1 carrying the sug-refill suggestion, both slots pending."""
    (page_dir / "versions" / "v1.html").write_text(SUGGESTED)
    return published(page_dir)


def test_a_decision_retires_its_losing_slot_from_comments_reach(page_dir):
    """The reviewer's accept removes cq-old from the page (the browser's anchor pass
    skips it), so a quote into it is refused naming the decision — posted, it would
    detach in front of them. The surviving slot quotes as ever, and a re-decision
    moves the line: the reading follows the log the way replay does, last word
    standing."""
    suggested(page_dir)
    decide(page_dir, "accept")
    gone = comment(page_dir, "--quote", "Refill every feeder each morning.", "--text", "x")
    assert gone.exit_code != 0
    assert "accepted § sug-refill" in gone.output and "retired" in gone.output
    kept = comment(page_dir, "--quote", "camera shows it half-empty", "--text", "x")
    assert kept.exit_code == 0, kept.output

    decide(page_dir, "reject")
    gone = comment(page_dir, "--quote", "camera shows it half-empty", "--text", "x")
    assert gone.exit_code != 0 and "rejected § sug-refill" in gone.output
    kept = comment(page_dir, "--quote", "Refill every feeder each morning.", "--text", "x")
    assert kept.exit_code == 0, kept.output


def test_a_section_inside_a_retired_slot_is_refused(page_dir):
    """An element anchor is a click on the element, and a retired slot's children
    are elements nobody can click. The id is still in the file — the refusal has to
    come from the decision, not the structure."""
    suggested(page_dir)
    decide(page_dir, "accept")
    result = comment(page_dir, "--section", "refill-rule", "--text", "x")
    assert result.exit_code != 0
    assert "accepted" in result.output and "sug-refill" in result.output


def test_a_decision_that_empties_its_widget_takes_it_off_sections_reach(page_dir):
    """A deletion accepted and an insertion refused both settle to nothing: the
    wrapper's markup is still in the file, but the reviewer's screen shows nothing
    there, so an element anchor on it would read attached while outlining nothing.
    Pending, the wrapper answers like any element; settled empty, the refusal names
    the decision that emptied it."""
    lone = PAGE.replace(
        "<cq-options>",
        '<cq-suggestion id="sug-drop">\n'
        "  <cq-old><p>The manual sightings log.</p></cq-old>\n"
        "</cq-suggestion>\n"
        '<cq-suggestion id="sug-add">\n'
        "  <cq-new><p>Switch the north feeder to thistle.</p></cq-new>\n"
        "</cq-suggestion>\n<cq-options>",
    )
    (page_dir / "versions" / "v1.html").write_text(lone)
    published(page_dir)
    for wid in ("sug-drop", "sug-add"):
        ok = comment(page_dir, "--section", wid, "--text", "x")
        assert ok.exit_code == 0, ok.output
    decide(page_dir, "accept", widget="sug-drop")
    decide(page_dir, "reject", widget="sug-add")
    for wid, verb in (("sug-drop", "accepted"), ("sug-add", "rejected")):
        gone = comment(page_dir, "--section", wid, "--text", "x")
        assert gone.exit_code != 0
        assert "settled to nothing" in gone.output and verb in gone.output


def test_a_settled_replacement_still_answers_an_element_anchor(page_dir):
    """Deciding a replacement keeps a slot on screen, so the wrapper is still a thing
    to point at — only a decision that leaves nothing takes the element away."""
    suggested(page_dir)
    decide(page_dir, "accept")
    ok = comment(page_dir, "--section", "sug-refill", "--text", "x")
    assert ok.exit_code == 0, ok.output


def test_a_decision_verb_the_registry_no_longer_speaks_settles_nothing(page_dir):
    """The decisions gate is the fold's, the same one the edit gate above reads: an
    outcome whose verb this page's vendored x-state doesn't declare folds to nothing,
    so the reading stays pending — matching a vendored layer whose widgets no longer
    speak the verb — rather than trusting the log's word alone."""
    suggested(page_dir)
    registry = json.loads((page_dir / "registry.json").read_text())
    del registry["cq-suggestion"]["x-state"]["accept"]
    (page_dir / "registry.json").write_text(json.dumps(registry))
    decide(page_dir, "accept")
    kept = comment(page_dir, "--quote", "Refill every feeder each morning.", "--text", "x")
    assert kept.exit_code == 0, kept.output


def test_a_decision_settles_which_copy_a_quote_names(page_dir):
    """The browser counts occurrences on the page as decided, so the file has to
    count the same way — otherwise a passage unique in front of the reviewer reads
    as ambiguous here, and an anchor allowed on the wrong count would carry context
    from words they no longer see."""
    twice = SUGGESTED.replace(
        "<h2>Plan</h2>", "<h2>Plan</h2>\n  <p>Refill every feeder each morning.</p>"
    )
    (page_dir / "versions" / "v1.html").write_text(twice)
    published(page_dir)
    ambiguous = comment(page_dir, "--quote", "Refill every feeder each morning.", "--text", "x")
    assert ambiguous.exit_code != 0 and "2 times" in ambiguous.output
    decide(page_dir, "accept")
    result = comment(page_dir, "--quote", "Refill every feeder each morning.", "--text", "x")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["anchor"]["section"] == "plan"


def test_a_restated_suggestion_hands_its_slot_back(page_dir):
    """A version that rewrites under a decision retracts it (`restated`), and replay
    then shows the suggestion pending again — both slots on the page. The reading
    follows the log all the way, not just to the first decision it finds."""
    suggested(page_dir)
    decide(page_dir, "accept")
    revised = SUGGESTED.replace(
        "Refill when the camera shows it half-empty.",
        "Refill when the camera shows it two-thirds empty.",
    ).replace('<cq-suggestion id="sug-refill">', '<cq-suggestion id="sug-refill" restated>')
    (page_dir / "versions" / "v2.html").write_text(revised)
    noted = CliRunner().invoke(
        interact.cli, ["note", str(page_dir), "--version", "2", "--text", "revised the proposal"]
    )
    assert noted.exit_code == 0, noted.output
    result = comment(page_dir, "--quote", "Refill every feeder each morning.", "--text", "x")
    assert result.exit_code == 0, result.output


def test_what_the_reader_never_sees_is_not_quotable(page_dir):
    """The runtime roots a section-less anchor at document.body, so a <title> is text no
    anchor can reach — and a page's title is often a sentence from the page as well."""
    (page_dir / "versions" / "v1.html").write_text(
        PAGE.replace("<title>t</title>", "<title>Backfill cutover plan</title>")
    )
    result = comment(published(page_dir), "--quote", "Backfill cutover plan", "--text", "x")
    assert result.exit_code != 0
    assert "doesn't say" in result.output


def test_a_comment_needs_a_published_version_to_point_at(page_dir):
    result = comment(page_dir, "--quote", "Ship dark", "--text", "x")
    assert result.exit_code != 0
    assert "no published version" in result.output


def test_a_comment_points_at_something(page_dir):
    result = comment(published(page_dir), "--text", "just a thought")
    assert result.exit_code != 0
    assert "--quote" in result.output


def test_claudes_own_comment_is_not_delivered_back_to_it(page_dir):
    """`wait` and the banner's unread count both turn on author, so a note Claude leaves
    can't wake its own watcher or read as a comment nobody answered."""
    published(page_dir)
    assert comment(page_dir, "--quote", "Ship dark", "--text", "x").exit_code == 0
    assert interact.full_state(page_dir)["pending"] == 0
    assert interact.unattended_pages("") == []


def test_a_comments_widget_markup_shares_one_id_universe_with_replies(page_dir):
    """A Claude comment renders as HTML in the panel exactly as a reply does, so it
    validates the same way and claims ids from the same pool."""
    published(page_dir)
    assert comment(
        page_dir, "--quote", "Ship dark", "--text",
        '<cq-options id="q1" choose><cq-option id="q1-a"><strong>A</strong></cq-option></cq-options>',
    ).exit_code == 0
    interact.append_event(page_dir, {"kind": "comment", "id": "c1", "author": "user", "text": "hm"})
    clash = CliRunner().invoke(
        interact.cli,
        ["reply", str(page_dir), "--to", "c1", "--text", '<cq-diagram id="q1">\ngraph LR\n  A --> B\n</cq-diagram>'],
    )
    assert clash.exit_code != 0 and "q1" in clash.output
