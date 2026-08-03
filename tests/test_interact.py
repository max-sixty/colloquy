"""Integration tests for interact.py: the check lint, init vendoring, note-gated
serving, the catalog, reply widget validation, and the live server + wait
round-trip that the review loop rides on.

Run from the repo root:

    uv run pytest tests
"""

import http.cookiejar
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from click.testing import CliRunner

ROOT = Path(__file__).parent.parent
PLUGIN_ROOT = ROOT / "plugins" / "colloquy"

_spec = importlib.util.spec_from_file_location(
    "interact", PLUGIN_ROOT / "skills" / "colloquy" / "scripts" / "interact.py"
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
  <p>The cutoff lives in <a href="https://example.test/jobs/backfill.py#L88"><code>jobs/backfill.py:88</code></a>.</p>
  <cq-options>
    <cq-option id="flag-first"><cq-chip>effort: low</cq-chip><cq-chip>risk: med</cq-chip>
      <strong>Flag first</strong> Ship dark.
    </cq-option>
    <cq-option id="backfill-first" recommended><cq-chip>effort: med</cq-chip><cq-chip>risk: low</cq-chip>
      <strong>Backfill first</strong> Verify, then flip.
    </cq-option>
  </cq-options>
  <cq-diagram id="flow"><pre>
graph LR
  A --> B
  </pre></cq-diagram>
</section>
</main>
<script type="module" src="/colloquy.js"></script>
</body>
</html>
"""


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        pytest.param(
            ["--help"],
            """Usage: colloquy [OPTIONS] COMMAND [ARGS]...

  Build and run interactive review pages.

Options:
  --help  Show this message and exit.

Commands:
  customize  Create theme and widget customizations.
  page       Create pages and add media.
  review     Watch and write to a live review.
  server     Run or stop the local server.
  version    Check, publish, and export versions.
""",
            id="root",
        ),
        pytest.param(
            ["customize", "--help"],
            """Usage: colloquy customize [OPTIONS] COMMAND [ARGS]...

  Create theme and widget customizations.

Options:
  --help  Show this message and exit.

Commands:
  theme   Create the theme override file.
  widget  Add a widget scaffold.
""",
            id="customize",
        ),
        pytest.param(
            ["page", "--help"],
            """Usage: colloquy page [OPTIONS] COMMAND [ARGS]...

  Create pages and add media.

Options:
  --help  Show this message and exit.

Commands:
  catalog  Print the widget and theme vocabulary.
  init     Create or re-vendor a page directory.
  media    Add images and print their page paths.
""",
            id="page",
        ),
        pytest.param(
            ["version", "--help"],
            """Usage: colloquy version [OPTIONS] COMMAND [ARGS]...

  Check, publish, and export versions.

Options:
  --help  Show this message and exit.

Commands:
  check    Check a page version.
  export   Export a published version to one HTML file.
  publish  Publish a checked version with a changelog.
""",
            id="version",
        ),
        pytest.param(
            ["server", "--help"],
            """Usage: colloquy server [OPTIONS] COMMAND [ARGS]...

  Run or stop the local server.

Options:
  --help  Show this message and exit.

Commands:
  run   Serve a page and print its URL.
  stop  Stop a page's server.
""",
            id="server",
        ),
        pytest.param(
            ["review", "--help"],
            """Usage: colloquy review [OPTIONS] COMMAND [ARGS]...

  Watch and write to a live review.

Options:
  --help  Show this message and exit.

Commands:
  ack         Acknowledge one complete, untruncated wait batch.
  comment     Open an agent thread on a page passage.
  events      Print the event log as JSON lines.
  reply       Reply to a thread as the agent.
  state       Set the agent's banner state.
  transcript  Print the review as Markdown.
  wait        Print unacknowledged reviewer events, then exit.
""",
            id="review",
        ),
    ],
)
def test_cli_help_groups_commands_with_complete_summaries(args, expected):
    result = CliRunner().invoke(
        interact.cli,
        args,
        prog_name="colloquy",
        terminal_width=80,
    )

    assert result.exit_code == 0
    assert result.output == expected


@pytest.mark.parametrize("command", ["wait", "ack"])
def test_wait_and_ack_help_require_a_complete_batch(command):
    result = CliRunner().invoke(
        interact.cli,
        ["review", command, "--help"],
        terminal_width=200,
    )

    assert result.exit_code == 0
    assert " ".join(interact.ACK_BATCH_INSTRUCTION.split()) in " ".join(
        result.output.split()
    )


def test_ack_batch_instruction_preserves_scalar_cursor_safety():
    assert interact.ACK_BATCH_INSTRUCTION == (
        "If wait output is truncated, acknowledge nothing and rerun with enough output "
        "capacity for the whole batch. After a complete batch enters context, run "
        "`colloquy review ack <page> <highest-seq>`."
    )


def test_hidden_hook_remains_callable():
    result = CliRunner().invoke(interact.cli, ["hook"], input="{}")

    assert result.exit_code == 0
    assert result.output == ""


def test_init_help_names_the_version_file_layout():
    result = CliRunner().invoke(
        interact.cli,
        ["page", "init", "--help"],
        prog_name="colloquy",
        terminal_width=80,
    )

    assert result.exit_code == 0
    assert "Creates PAGE/versions/ for authored vN.html files" in result.output


@pytest.mark.parametrize(
    ("args", "needs_playwright"),
    [
        (["version", "check", "page", "--render"], True),
        (["version", "export", "page", "-o", "export"], True),
        (["version", "check", "export"], False),
        (["review", "reply", "page", "--to", "c1", "--text", "export"], False),
    ],
)
def test_shim_adds_playwright_only_for_browser_commands(
    tmp_path, monkeypatch, args, needs_playwright
):
    fake_uv = tmp_path / "uv"
    fake_uv.write_text(
        '#!/bin/sh\nfor cli_arg in "$@"; do\n  printf "%s\\n" "$cli_arg"\ndone\n'
    )
    fake_uv.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    shim = PLUGIN_ROOT / "bin" / "colloquy"

    result = subprocess.run(
        [shim, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    dispatched = result.stdout.splitlines()

    assert result.returncode == 0, result.stderr
    assert (dispatched[1:3] == ["--with", "playwright"]) is needs_playwright


@pytest.fixture
def page_dir(tmp_path, monkeypatch):
    """An initialized page directory with a valid v1 written."""
    monkeypatch.chdir(tmp_path)  # keep the project layer out of the overlay
    d = tmp_path / "page"
    result = CliRunner().invoke(interact.cli, ["page", "init", str(d)])
    assert result.exit_code == 0, result.output
    (d / "versions" / "v1.html").write_text(PAGE)
    return d


def check(d, version=None):
    args = ["version", "check", str(d)] + (
        ["--version", str(version)] if version else []
    )
    return CliRunner().invoke(interact.cli, args)


def publish(d, version=1):
    """Append the note event that makes a version the reviewer-seen baseline:
    `version check` compares against the last *published* version, and an action
    can only ever be made against one the server exposed."""
    interact.append_event(
        d, {"kind": "note", "author": "claude", "version": version, "text": "published"}
    )


def page_state(d):
    events = interact.read_events(d)
    return interact.full_state(d, events, interact.published_versions(d, events))


def live_versions(d):
    events = interact.read_events(d)
    return interact.published_versions(d, events)


def fragment_errors(html, registry):
    parser = interact._StructParser()
    parser.feed(html)
    parser.close()
    return interact.fragment_errors(parser, registry, registry["$languages"]["names"])


def test_claude_and_codex_load_the_same_plugin_payload():
    claude_marketplace = json.loads(
        (ROOT / ".claude-plugin" / "marketplace.json").read_text()
    )
    codex_marketplace = json.loads(
        (ROOT / ".agents" / "plugins" / "marketplace.json").read_text()
    )
    claude_manifest = json.loads(
        (PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text()
    )
    codex_manifest = json.loads(
        (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text()
    )

    assert claude_marketplace["plugins"][0]["source"] == "./plugins/colloquy"
    assert codex_marketplace["plugins"][0]["source"] == {
        "source": "local",
        "path": "./plugins/colloquy",
    }
    assert codex_marketplace["plugins"][0]["policy"] == {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL",
    }
    assert claude_manifest["name"] == codex_manifest["name"] == "colloquy"
    assert "version" not in claude_manifest
    assert "version" not in codex_manifest
    for relative in [
        "bin/colloquy",
        "hooks/hooks.json",
        "hooks/scripts/review-guard.py",
        "skills/colloquy/SKILL.md",
        "skills/colloquy/scripts/interact.py",
        # The lock only pins what it ships beside; an install that loses it
        # resolves fresh and looks identical from the outside.
        "skills/colloquy/scripts/interact.py.lock",
    ]:
        assert (PLUGIN_ROOT / relative).is_file()
    assert not [path for path in PLUGIN_ROOT.rglob("*") if path.is_symlink()]


def test_an_installed_payload_is_complete_and_launches_outside_the_checkout(tmp_path):
    installed = tmp_path / "host" / "plugins" / "colloquy"
    shutil.copytree(PLUGIN_ROOT, installed)

    conflicts = []
    for path in installed.rglob("*"):
        if not path.is_file() or "vendor" in path.parts:
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            if re.match(r"^(<{7}|={7}|>{7})(?: |$)", line):
                conflicts.append(f"{path.relative_to(installed)}:{line_no}")
    assert conflicts == []

    elsewhere = tmp_path / "unrelated-project"
    elsewhere.mkdir()
    launcher = installed / "bin" / "colloquy"
    page = tmp_path / "state" / "page"

    help_result = subprocess.run(
        [launcher, "--help"],
        cwd=elsewhere,
        capture_output=True,
        text=True,
        check=False,
    )
    assert help_result.returncode == 0, help_result.stderr
    assert "Build and run interactive review pages." in help_result.stdout

    init_result = subprocess.run(
        [launcher, "page", "init", page],
        cwd=elsewhere,
        capture_output=True,
        text=True,
        check=False,
    )
    assert init_result.returncode == 0, init_result.stderr
    (page / "versions" / "v1.html").write_text(PAGE)
    publish_result = subprocess.run(
        [
            launcher,
            "version",
            "publish",
            page,
            "--version",
            "1",
            "--text",
            "installed-payload smoke",
        ],
        cwd=elsewhere,
        capture_output=True,
        text=True,
        check=False,
    )
    assert publish_result.returncode == 0, publish_result.stderr
    assert interact.published_versions(page, interact.read_events(page)) == [1]


def case_alias(path):
    alias = path.with_name(path.name.swapcase())
    if not alias.exists() or not path.samefile(alias):
        pytest.skip("requires a case-insensitive filesystem")
    return alias


def test_init_vendors_the_layer(page_dir):
    for name in ["colloquy.js", "theme.css", "registry.json"]:
        assert (page_dir / name).is_file()
    assert (page_dir / "widgets" / "cq-tabs.js").is_file()
    assert (page_dir / "widgets" / "cq-diagram.js").is_file()
    assert (page_dir / "vendor" / "mermaid.min.js").is_file()


def test_init_user_layer_applies(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".config" / "colloquy" / "widgets").mkdir(parents=True)
    custom_theme = ":root { --accent: teal }\n"
    (home / ".config" / "colloquy" / "theme.css").write_text(custom_theme)
    (home / ".config" / "colloquy" / "widgets" / "cq-foo.js").write_text(
        "// user widget"
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "page"
    result = CliRunner().invoke(interact.cli, ["page", "init", str(d)])
    assert result.exit_code == 0, result.output
    vendored_theme = (d / "theme.css").read_text()
    assert vendored_theme.startswith((interact.ASSETS / "theme.css").read_text())
    assert vendored_theme.endswith(custom_theme)
    assert (d / "widgets" / "cq-foo.js").read_text() == "// user widget"
    assert (d / "widgets" / "cq-tabs.js").is_file()  # shipped modules still vendored


def test_init_project_layer_wins(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    (project / ".colloquy").mkdir(parents=True)
    custom_theme = ":root { --accent: red }\n"
    (project / ".colloquy" / "theme.css").write_text(custom_theme)
    monkeypatch.chdir(project)
    d = tmp_path / "page"
    result = CliRunner().invoke(interact.cli, ["page", "init", str(d)])
    assert result.exit_code == 0, result.output
    theme = (d / "theme.css").read_text()
    assert theme.startswith((interact.ASSETS / "theme.css").read_text())
    assert theme.endswith(custom_theme)
    # Files the project layer doesn't override still come from the shipped defaults.
    assert (d / "registry.json").is_file()


def test_init_merges_registry_layers_by_complete_entry(tmp_path, monkeypatch):
    """A custom widget adds one entry; it need not fork the shipped vocabulary.

    Precedence still belongs to the later layer, but at the entry boundary: the
    project entry replaces the user's whole schema rather than inheriting stale
    fields from it.
    """
    user = tmp_path / "config" / "colloquy"
    project = tmp_path / "project"
    project_layer = project / ".colloquy"
    user.mkdir(parents=True)
    project_layer.mkdir(parents=True)
    user_entry = {
        "description": "user shape",
        "type": "object",
        "properties": {"user-only": {"type": "string"}},
        "additionalProperties": False,
        "x-content": "none",
        "x-upgrade": False,
    }
    project_entry = {
        "description": "project shape",
        "type": "object",
        "properties": {"project-only": {"type": "string"}},
        "additionalProperties": False,
        "x-content": "none",
        "x-upgrade": False,
    }
    project_only = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
        "x-content": "none",
        "x-upgrade": False,
    }
    (user / "registry.json").write_text(json.dumps({"cq-local": user_entry}))
    (project_layer / "registry.json").write_text(
        json.dumps({"cq-local": project_entry, "cq-project-only": project_only})
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.chdir(project)

    page = tmp_path / "page"
    result = CliRunner().invoke(interact.cli, ["page", "init", str(page)])

    assert result.exit_code == 0, result.output
    registry = json.loads((page / "registry.json").read_text())
    assert registry["cq-local"] == project_entry
    assert registry["cq-project-only"] == project_only
    assert "cq-options" in registry and "$events" in registry


def test_customize_scaffolds_a_project_widget_that_init_can_vendor(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    theme = runner.invoke(interact.cli, ["customize", "theme"])
    assert theme.exit_code == 0, theme.output

    widget = runner.invoke(
        interact.cli, ["customize", "widget", "cq-callout", "--upgrade"]
    )
    assert widget.exit_code == 0, widget.output

    layer = tmp_path / ".colloquy"
    registry = json.loads((layer / "registry.json").read_text())
    entry = registry["cq-callout"]
    assert entry["x-content"] == "prose"
    assert entry["x-upgrade"] is True
    assert entry["x-verbatim"] is True
    assert "<cq-callout" in entry["x-example"]
    assert "cq-callout {" in (layer / "theme.css").read_text()
    assert "customElements.define(" in (layer / "widgets" / "cq-callout.js").read_text()

    page = tmp_path / "page"
    initialized = runner.invoke(interact.cli, ["page", "init", str(page)])
    assert initialized.exit_code == 0, initialized.output
    assert "cq-callout {" in (page / "theme.css").read_text()
    assert json.loads((page / "registry.json").read_text())["cq-callout"] == entry
    assert (page / "widgets" / "cq-callout.js").is_file()

    (page / "versions" / "v1.html").write_text(
        PAGE.replace(
            "<h2>Plan</h2>",
            '<h2>Plan</h2><cq-callout id="custom-note">'
            "<strong>Heads up</strong> Custom project guidance."
            "</cq-callout>",
        )
    )
    result = check(page)
    assert result.exit_code == 0, result.output


def test_customize_scaffolds_a_long_widget_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tag = "cq-" + "a" * 237
    module_name = f"{tag}.js"
    try:
        name_max = os.pathconf(tmp_path, "PC_NAME_MAX")
    except (AttributeError, OSError, ValueError):
        name_max = 255
    if len(os.fsencode(module_name)) > name_max:
        pytest.skip("the final module name does not fit this filesystem")

    result = CliRunner().invoke(interact.cli, ["customize", "widget", tag, "--upgrade"])

    assert result.exit_code == 0, result.output
    layer = tmp_path / ".colloquy"
    assert (layer / "widgets" / module_name).is_file()
    assert tag in json.loads((layer / "registry.json").read_text())


def test_customize_never_overwrites_an_existing_layer(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    layer = tmp_path / ".colloquy"
    layer.mkdir(parents=True)
    theme = layer / "theme.css"
    theme.write_text(":root { --accent: rebeccapurple; }\n")

    result = runner.invoke(interact.cli, ["customize", "theme"])
    assert result.exit_code == 0, result.output
    assert theme.read_text() == ":root { --accent: rebeccapurple; }\n"

    assert (
        runner.invoke(interact.cli, ["customize", "widget", "cq-note-card"]).exit_code
        == 0
    )
    registry_before = (layer / "registry.json").read_text()
    theme_before = theme.read_text()

    duplicate = runner.invoke(interact.cli, ["customize", "widget", "cq-note-card"])
    assert duplicate.exit_code != 0
    assert "already exists" in duplicate.output
    assert (layer / "registry.json").read_text() == registry_before
    assert theme.read_text() == theme_before

    shipped = runner.invoke(interact.cli, ["customize", "widget", "cq-options"])
    assert shipped.exit_code != 0
    assert "already exists" in shipped.output
    assert (layer / "registry.json").read_text() == registry_before
    assert theme.read_text() == theme_before


def test_customize_can_target_the_user_layer(tmp_path, monkeypatch):
    config = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        interact.cli, ["customize", "widget", "cq-personal-note", "--user"]
    )

    assert result.exit_code == 0, result.output
    layer = config / "colloquy"
    assert "cq-personal-note" in json.loads((layer / "registry.json").read_text())
    assert (layer / "theme.css").is_file()
    assert not (tmp_path / ".colloquy").exists()


def test_customize_preserves_a_symlinked_registry(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    layer = tmp_path / ".colloquy"
    layer.mkdir(parents=True)
    shared_registry = tmp_path / "shared-registry.json"
    shared_registry.write_text("{}\n")
    registry = layer / "registry.json"
    registry.symlink_to(shared_registry)

    result = CliRunner().invoke(interact.cli, ["customize", "widget", "cq-shared-note"])

    assert result.exit_code == 0, result.output
    assert registry.is_symlink()
    assert "cq-shared-note" in json.loads(shared_registry.read_text())


@pytest.mark.skipif(os.name == "nt", reason="POSIX umask and mode semantics")
def test_staged_writes_honor_umask_without_copying_a_replaced_symlink_mode(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    old_umask = os.umask(0o077)
    try:
        customized = runner.invoke(interact.cli, ["customize", "theme"])
    finally:
        os.umask(old_umask)
    assert customized.exit_code == 0, customized.output
    custom_theme = tmp_path / ".colloquy" / "theme.css"
    assert custom_theme.stat().st_mode & 0o777 == 0o600

    page = tmp_path / "page"
    initialized = runner.invoke(interact.cli, ["page", "init", str(page)])
    assert initialized.exit_code == 0, initialized.output
    external = tmp_path / "external-theme.css"
    external.write_text("external")
    external.chmod(0o600)
    (page / "theme.css").unlink()
    (page / "theme.css").symlink_to(external)
    old_umask = os.umask(0o022)
    try:
        revendored = runner.invoke(interact.cli, ["page", "init", str(page)])
    finally:
        os.umask(old_umask)

    assert revendored.exit_code == 0, revendored.output
    assert not (page / "theme.css").is_symlink()
    assert (page / "theme.css").stat().st_mode & 0o777 == 0o644
    assert external.read_text() == "external"


@pytest.mark.parametrize("alias", ["root", "theme.css", "registry.json", "widgets"])
def test_customize_refuses_targets_aliased_to_another_layer(
    tmp_path, monkeypatch, alias
):
    project = tmp_path / "project"
    project.mkdir()
    config = tmp_path / "config"
    user = config / "colloquy"
    user.mkdir(parents=True)
    (user / "theme.css").write_text(":root { --accent: teal; }\n")
    (user / "registry.json").write_text("{}\n")
    (user / "widgets").mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.chdir(project)
    layer = project / ".colloquy"
    if alias == "root":
        layer.symlink_to(user, target_is_directory=True)
    else:
        layer.mkdir()
        (layer / alias).symlink_to(user / alias, target_is_directory=alias == "widgets")
    before = {
        path.relative_to(user): path.read_bytes()
        for path in user.rglob("*")
        if path.is_file()
    }

    args = ["customize", "widget", "cq-no-scope-alias"]
    if alias in {"root", "widgets"}:
        args.append("--upgrade")
    result = CliRunner().invoke(interact.cli, args)

    assert result.exit_code != 0
    assert "overlaps another layer source" in result.output
    after = {
        path.relative_to(user): path.read_bytes()
        for path in user.rglob("*")
        if path.is_file()
    }
    assert after == before


@pytest.mark.parametrize(
    "args",
    [
        ["customize", "theme"],
        ["customize", "widget", "cq-future-alias"],
        ["customize", "theme", "--user"],
        ["customize", "widget", "cq-future-alias", "--user"],
    ],
    ids=["project-theme", "project-widget", "user-theme", "user-widget"],
)
def test_customize_protects_another_layers_future_root(tmp_path, monkeypatch, args):
    project = tmp_path / "project"
    project.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    (project / ".colloquy").symlink_to(config / "colloquy", target_is_directory=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.chdir(project)

    result = CliRunner().invoke(interact.cli, args)

    assert result.exit_code != 0
    if "--user" in args:
        assert "overlaps another layer source" in result.output
    else:
        assert "must be a directory" in result.output
    assert not (config / "colloquy").exists()


def test_path_case_policy_matches_the_filesystem(tmp_path):
    probe = tmp_path / "CaseProbe"
    probe.mkdir()
    alias_resolves = (tmp_path / "cASEpROBE").exists()

    assert interact._filesystem_case_sensitive(tmp_path) is not alias_resolves


def test_path_overlap_respects_case_sensitive_future_names(tmp_path, monkeypatch):
    upper = tmp_path / "FutureScope"
    lower = tmp_path / "fUTUREsCOPE"
    monkeypatch.setattr(interact, "_filesystem_case_sensitive", lambda path: True)
    assert not interact.paths_overlap(upper, lower)

    monkeypatch.setattr(interact, "_filesystem_case_sensitive", lambda path: False)
    assert interact.paths_same(upper, lower)


def test_customize_refuses_case_aliased_future_roots(tmp_path, monkeypatch):
    project = tmp_path / "Project"
    project.mkdir()
    alias = case_alias(project)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(alias / ".COLLOQUY"))
    monkeypatch.chdir(project)

    result = CliRunner().invoke(interact.cli, ["customize", "theme"])

    assert result.exit_code != 0
    assert "overlaps another layer source" in result.output
    assert not (project / ".colloquy").exists()


def test_customize_refuses_a_broken_case_alias_to_its_future_target(
    tmp_path, monkeypatch
):
    project = tmp_path / "Project"
    project.mkdir()
    alias = case_alias(project)
    config = tmp_path / "Config"
    user_theme = config / "colloquy" / "theme.css"
    user_theme.parent.mkdir(parents=True)
    user_theme.symlink_to(alias / ".COLLOQUY" / "THEME.CSS")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.chdir(project)

    result = CliRunner().invoke(interact.cli, ["customize", "theme"])

    assert result.exit_code != 0
    assert "overlaps another layer source" in result.output
    assert user_theme.is_symlink() and not user_theme.exists()
    assert not (project / ".colloquy" / "theme.css").exists()


def test_customize_refuses_an_existing_member_case_alias(tmp_path, monkeypatch):
    project = tmp_path / "Project"
    project.mkdir()
    config = tmp_path / "Config"
    user_theme = config / "colloquy" / "theme.css"
    user_theme.parent.mkdir(parents=True)
    user_theme.write_text(":root { --accent: teal; }\n")
    config_alias = case_alias(config)
    project_theme = project / ".colloquy" / "theme.css"
    project_theme.parent.mkdir(parents=True)
    project_theme.symlink_to(config_alias / "COLLOQUY" / "THEME.CSS")
    before = user_theme.read_bytes()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.chdir(project)

    result = CliRunner().invoke(interact.cli, ["customize", "widget", "cq-case-member"])

    assert result.exit_code != 0
    assert "overlaps another layer source" in result.output
    assert user_theme.read_bytes() == before
    assert not (project_theme.parent / "registry.json").exists()


@pytest.mark.parametrize("user", [False, True], ids=["project", "user"])
def test_customize_refuses_an_initialized_page_as_a_layer(tmp_path, monkeypatch, user):
    project = tmp_path / "project"
    project.mkdir()
    config = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.chdir(project)
    runner = CliRunner()
    page = tmp_path / "page"
    initialized = runner.invoke(interact.cli, ["page", "init", str(page)])
    assert initialized.exit_code == 0, initialized.output
    before = {
        path.relative_to(page): path.read_bytes()
        for path in page.rglob("*")
        if path.is_file()
    }

    layer = config / "colloquy" if user else project / ".colloquy"
    layer.parent.mkdir(parents=True, exist_ok=True)
    layer.symlink_to(page, target_is_directory=True)
    args = ["customize", "widget", "cq-page-alias", "--upgrade"]
    if user:
        args.append("--user")

    result = runner.invoke(interact.cli, args)

    assert result.exit_code != 0
    assert "owned by initialized page" in result.output
    after = {
        path.relative_to(page): path.read_bytes()
        for path in page.rglob("*")
        if path.is_file()
    }
    assert after == before


@pytest.mark.parametrize(
    "relative",
    ["theme.css", "registry.json", "widgets", "widgets/cq-tabs.js"],
)
def test_customize_refuses_members_aliased_into_an_initialized_page(
    tmp_path, monkeypatch, relative
):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.chdir(project)
    runner = CliRunner()
    page = tmp_path / "page"
    initialized = runner.invoke(interact.cli, ["page", "init", str(page)])
    assert initialized.exit_code == 0, initialized.output
    before = {
        path.relative_to(page): path.read_bytes()
        for path in page.rglob("*")
        if path.is_file()
    }

    layer = project / ".colloquy"
    alias = layer / relative
    alias.parent.mkdir(parents=True, exist_ok=True)
    target = page / relative
    alias.symlink_to(target, target_is_directory=target.is_dir())

    result = runner.invoke(
        interact.cli,
        ["customize", "widget", "cq-page-member-alias", "--upgrade"],
    )

    assert result.exit_code != 0
    assert "owned by initialized page" in result.output
    after = {
        path.relative_to(page): path.read_bytes()
        for path in page.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert not (layer / "theme.css").exists() or relative == "theme.css"
    assert not (layer / "registry.json").exists() or relative == "registry.json"


def test_customize_recognizes_a_page_without_runtime_status(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.chdir(project)
    runner = CliRunner()
    page = tmp_path / "page"
    initialized = runner.invoke(interact.cli, ["page", "init", str(page)])
    assert initialized.exit_code == 0, initialized.output
    (page / "status.json").unlink()
    before = (page / "theme.css").read_bytes()

    layer = project / ".colloquy"
    layer.mkdir(parents=True)
    (layer / "theme.css").symlink_to(page / "theme.css")

    result = runner.invoke(
        interact.cli,
        ["customize", "widget", "cq-page-without-status", "--upgrade"],
    )

    assert result.exit_code != 0
    assert "owned by initialized page" in result.output
    assert (page / "theme.css").read_bytes() == before
    assert not (layer / "registry.json").exists()


@pytest.mark.parametrize(
    ("source_name", "page_name"),
    [
        ("theme.css", "status.json"),
        ("widgets", interact.MEDIA_DIR),
        ("vendor", "versions"),
    ],
)
def test_customize_refuses_sources_aliased_to_page_owned_state(
    tmp_path, monkeypatch, source_name, page_name
):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.chdir(project)
    runner = CliRunner()
    page = tmp_path / "page"
    initialized = runner.invoke(interact.cli, ["page", "init", str(page)])
    assert initialized.exit_code == 0, initialized.output
    target = page / page_name
    if source_name in interact.VENDORED_DIRS:
        target.mkdir(exist_ok=True)
    before = {
        path.relative_to(page): path.read_bytes()
        for path in page.rglob("*")
        if path.is_file()
    }

    layer = project / ".colloquy"
    layer.mkdir(parents=True)
    (layer / source_name).symlink_to(target, target_is_directory=target.is_dir())

    result = runner.invoke(
        interact.cli,
        ["customize", "widget", "cq-page-owned-alias", "--upgrade"],
    )

    assert result.exit_code != 0
    assert "owned by initialized page" in result.output
    after = {
        path.relative_to(page): path.read_bytes()
        for path in page.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert not (layer / "registry.json").exists()


def test_customize_continues_when_the_project_root_is_the_page(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    themed = runner.invoke(interact.cli, ["customize", "theme"])
    assert themed.exit_code == 0, themed.output
    initialized = runner.invoke(interact.cli, ["page", "init", "."])
    assert initialized.exit_code == 0, initialized.output
    page_theme = tmp_path / "theme.css"
    page_registry = tmp_path / "registry.json"
    before_theme = page_theme.read_bytes()
    before_registry = page_registry.read_bytes()
    before_widgets = {
        path.name: path.read_bytes()
        for path in (tmp_path / "widgets").iterdir()
        if path.is_file()
    }

    scaffold = runner.invoke(
        interact.cli,
        ["customize", "widget", "cq-after-init", "--upgrade"],
    )

    assert scaffold.exit_code == 0, scaffold.output
    assert page_theme.read_bytes() == before_theme
    assert page_registry.read_bytes() == before_registry
    assert {
        path.name: path.read_bytes()
        for path in (tmp_path / "widgets").iterdir()
        if path.is_file()
    } == before_widgets
    source = tmp_path / ".colloquy"
    assert (source / "widgets" / "cq-after-init.js").is_file()

    revendored = runner.invoke(interact.cli, ["page", "init", "."])

    assert revendored.exit_code == 0, revendored.output
    assert "cq-after-init" in json.loads(page_registry.read_text())
    assert (tmp_path / "widgets" / "cq-after-init.js").is_file()


@pytest.mark.parametrize(
    "name",
    (
        "comments.jsonl",
        "status.json",
        "heartbeat.json",
        "cursor.json",
        "server.json",
        "access.json",
        "session.json",
    ),
)
def test_initialized_page_owns_runtime_state_paths(tmp_path, monkeypatch, name):
    monkeypatch.chdir(tmp_path)
    page = tmp_path / "page"
    initialized = CliRunner().invoke(interact.cli, ["page", "init", str(page)])
    assert initialized.exit_code == 0, initialized.output

    assert interact.initialized_page_owning(page / name) == page
    assert interact.initialized_page_owning(page / ".colloquy" / name) is None


@pytest.mark.parametrize("directory", ("versions", "widgets", "vendor", "media"))
def test_initialized_page_owns_declared_directory_trees(
    tmp_path, monkeypatch, directory
):
    monkeypatch.chdir(tmp_path)
    page = tmp_path / "page"
    initialized = CliRunner().invoke(interact.cli, ["page", "init", str(page)])
    assert initialized.exit_code == 0, initialized.output

    assert interact.initialized_page_owning(page / directory / "future") == page


def test_customize_allows_a_symlink_managed_external_layer(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    layer = tmp_path / ".colloquy"
    layer.mkdir(parents=True)
    managed = tmp_path / "managed"
    widgets = managed / "widgets"
    widgets.mkdir(parents=True)
    theme = managed / "theme.css"
    theme.write_text(":root { --accent: teal; }\n")
    registry = managed / "registry.json"
    registry.write_text("{}\n")
    (layer / "theme.css").symlink_to(theme)
    (layer / "registry.json").symlink_to(registry)
    (layer / "widgets").symlink_to(widgets, target_is_directory=True)

    result = CliRunner().invoke(
        interact.cli,
        ["customize", "widget", "cq-managed", "--upgrade"],
    )

    assert result.exit_code == 0, result.output
    assert (layer / "theme.css").is_symlink()
    assert (layer / "registry.json").is_symlink()
    assert (layer / "widgets").is_symlink()
    assert "cq-managed {" in theme.read_text()
    assert "cq-managed" in json.loads(registry.read_text())
    assert (widgets / "cq-managed.js").is_file()


def test_replace_files_rejects_case_aliased_future_targets(tmp_path, monkeypatch):
    monkeypatch.setattr(interact, "_filesystem_case_sensitive", lambda path: False)
    first = tmp_path / "Result.css"
    second = tmp_path / "rESULT.CSS"

    with pytest.raises(SystemExit, match="resolve to the same target"):
        interact.replace_files([(first, b"first", False), (second, b"second", False)])

    assert not first.exists() and not second.exists()


def test_customize_widget_names_a_wrong_kind_lower_layer(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    user_layer = config / "colloquy"
    user_layer.write_text("not a directory")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.chdir(project)

    result = CliRunner().invoke(interact.cli, ["customize", "widget", "cq-clear-error"])

    assert result.exit_code != 0
    assert f"{user_layer} must be a directory" in result.output
    assert user_layer.read_text() == "not a directory"
    assert not (project / ".colloquy").exists()


@pytest.mark.parametrize(
    ("relative", "directory"),
    [("vendor", False), ("colloquy.js", True)],
)
def test_customize_widget_validates_the_complete_selected_layer(
    tmp_path, monkeypatch, relative, directory
):
    monkeypatch.chdir(tmp_path)
    layer = tmp_path / ".colloquy"
    layer.mkdir(parents=True)
    malformed = layer / relative
    if directory:
        malformed.mkdir()
    else:
        malformed.write_text("not a directory")

    result = CliRunner().invoke(
        interact.cli, ["customize", "widget", "cq-complete-layer", "--upgrade"]
    )

    assert result.exit_code != 0
    assert str(malformed) in result.output
    assert not (layer / "theme.css").exists()
    assert not (layer / "registry.json").exists()
    assert not (layer / "widgets").exists()


def test_customize_refuses_a_broken_lower_alias_to_its_planned_target(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    config = tmp_path / "config"
    user_layer = config / "colloquy"
    user_layer.mkdir(parents=True)
    project_theme = project / ".colloquy" / "theme.css"
    user_theme = user_layer / "theme.css"
    user_theme.symlink_to(project_theme)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.chdir(project)

    result = CliRunner().invoke(interact.cli, ["customize", "theme"])

    assert result.exit_code != 0
    assert "overlaps another layer source" in result.output
    assert user_theme.is_symlink() and not user_theme.exists()
    assert not project_theme.exists()


def test_customize_refuses_an_existing_member_aliased_to_another_scope(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    config = tmp_path / "config"
    user_module = config / "colloquy" / "widgets" / "cq-shared.js"
    user_module.parent.mkdir(parents=True)
    user_module.write_text("// shared source\n")
    project_module = project / ".colloquy" / "widgets" / "cq-shared.js"
    project_module.parent.mkdir(parents=True)
    project_module.symlink_to(user_module)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.chdir(project)

    result = CliRunner().invoke(interact.cli, ["customize", "theme"])

    assert result.exit_code != 0
    assert "overlaps another layer source" in result.output
    assert project_module.is_symlink()
    assert user_module.read_text() == "// shared source\n"
    assert not (project / ".colloquy" / "theme.css").exists()


@pytest.mark.parametrize("user", [False, True], ids=["project", "user"])
def test_init_refuses_to_overwrite_a_customization_source(tmp_path, monkeypatch, user):
    project = tmp_path / "project"
    project.mkdir()
    config = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.chdir(project)
    runner = CliRunner()
    args = ["customize", "widget", "cq-safe-source", "--upgrade"]
    if user:
        args.append("--user")
    scaffold = runner.invoke(interact.cli, args)
    assert scaffold.exit_code == 0, scaffold.output

    layer = config / "colloquy" if user else project / ".colloquy"
    before = {
        path.relative_to(layer): path.read_bytes()
        for path in layer.rglob("*")
        if path.is_file()
    }
    assert before

    result = runner.invoke(interact.cli, ["page", "init", str(layer)])

    assert result.exit_code != 0
    assert "customization source" in result.output
    after = {
        path.relative_to(layer): path.read_bytes()
        for path in layer.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_init_refuses_overlapping_customization_scopes(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    config = tmp_path / "config"
    user = config / "colloquy"
    user.mkdir(parents=True)
    (user / "theme.css").write_text(":root { --accent: teal; }\n")
    project_layer = project / ".colloquy"
    project_layer.symlink_to(user, target_is_directory=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.chdir(project)
    before = {
        path.relative_to(user): path.read_bytes()
        for path in user.rglob("*")
        if path.is_file()
    }
    page = tmp_path / "page"

    result = CliRunner().invoke(interact.cli, ["page", "init", str(page)])

    assert result.exit_code != 0
    assert "layer scopes must be separate" in result.output
    after = {
        path.relative_to(user): path.read_bytes()
        for path in user.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert not page.exists()


def test_init_refuses_case_aliased_layer_scopes(tmp_path, monkeypatch):
    project = tmp_path / "Project"
    project.mkdir()
    alias = case_alias(project)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(alias / ".COLLOQUY"))
    monkeypatch.chdir(project)
    user_layer = alias / ".COLLOQUY" / "colloquy"
    user_layer.mkdir(parents=True)
    theme = user_layer / "theme.css"
    theme.write_text(":root { --accent: teal; }\n")
    before = theme.read_bytes()
    page = tmp_path / "page"

    result = CliRunner().invoke(interact.cli, ["page", "init", str(page)])

    assert result.exit_code != 0
    assert "layer scopes must be separate" in result.output
    assert theme.read_bytes() == before
    assert not page.exists()


def test_init_refuses_to_write_inside_a_customization_source(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    scaffold = runner.invoke(
        interact.cli, ["customize", "widget", "cq-safe-source", "--upgrade"]
    )
    assert scaffold.exit_code == 0, scaffold.output
    layer = tmp_path / ".colloquy"
    before = {
        path.relative_to(layer): path.read_bytes()
        for path in layer.rglob("*")
        if path.is_file()
    }

    result = runner.invoke(interact.cli, ["page", "init", str(layer / "widgets")])

    assert result.exit_code != 0
    assert "inside the widget-layer customization source" in result.output
    after = {
        path.relative_to(layer): path.read_bytes()
        for path in layer.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_init_refuses_a_case_aliased_page_inside_a_customization_source(
    tmp_path, monkeypatch
):
    project = tmp_path / "Project"
    project.mkdir()
    alias = case_alias(project)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.chdir(project)
    runner = CliRunner()
    scaffold = runner.invoke(
        interact.cli,
        ["customize", "widget", "cq-case-source", "--upgrade"],
    )
    assert scaffold.exit_code == 0, scaffold.output
    layer = project / ".colloquy"
    page = alias / ".COLLOQUY" / "WIDGETS"
    assert page.samefile(layer / "widgets")
    before = {
        path.relative_to(layer): path.read_bytes()
        for path in layer.rglob("*")
        if path.is_file()
    }

    result = runner.invoke(interact.cli, ["page", "init", str(page)])

    assert result.exit_code != 0
    assert "inside the widget-layer customization source" in result.output
    after = {
        path.relative_to(layer): path.read_bytes()
        for path in layer.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_customize_widget_validates_every_target_before_writing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    layer = tmp_path / ".colloquy"
    theme = layer / "theme.css"
    theme.mkdir(parents=True)
    sentinel = theme / "keep.txt"
    sentinel.write_text("keep")

    result = CliRunner().invoke(
        interact.cli, ["customize", "widget", "cq-no-partial", "--upgrade"]
    )

    assert result.exit_code != 0
    assert "theme.css must be a file" in result.output
    assert sentinel.read_text() == "keep"
    assert not (layer / "registry.json").exists()
    assert not (layer / "widgets").exists()


def test_customize_widget_refuses_malformed_css_before_writing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    layer = tmp_path / ".colloquy"
    layer.mkdir(parents=True)
    theme = layer / "theme.css"
    theme.write_text(".bad { color red; }\n")

    result = CliRunner().invoke(
        interact.cli, ["customize", "widget", "cq-no-broken-css", "--upgrade"]
    )

    assert result.exit_code != 0
    assert f"{theme} syntax error" in result.output
    assert theme.read_text() == ".bad { color red; }\n"
    assert not (layer / "registry.json").exists()
    assert not (layer / "widgets").exists()


def test_init_reads_the_complete_layer_before_revendoring(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    page = tmp_path / "page"
    initialized = runner.invoke(interact.cli, ["page", "init", str(page)])
    assert initialized.exit_code == 0, initialized.output
    before = {
        path.relative_to(page): path.read_bytes()
        for path in page.rglob("*")
        if path.is_file()
    }

    layer = tmp_path / ".colloquy"
    layer.mkdir(parents=True)
    (layer / "registry.json").write_text(
        json.dumps(
            {"cq-bad-theme": interact.custom_widget_entry("cq-bad-theme", False)}
        )
    )
    (layer / "theme.css").write_bytes(b"\xff")

    result = runner.invoke(interact.cli, ["page", "init", str(page)])

    assert result.exit_code != 0
    assert "theme.css must be UTF-8" in result.output
    after = {
        path.relative_to(page): path.read_bytes()
        for path in page.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_init_refuses_malformed_layer_css_before_revendoring(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    page = tmp_path / "page"
    initialized = runner.invoke(interact.cli, ["page", "init", str(page)])
    assert initialized.exit_code == 0, initialized.output
    before = {
        path.relative_to(page): path.read_bytes()
        for path in page.rglob("*")
        if path.is_file()
    }
    theme = tmp_path / ".colloquy" / "theme.css"
    theme.parent.mkdir(parents=True)
    theme.write_text(".bad { color red; }\n")

    result = runner.invoke(interact.cli, ["page", "init", str(page)])

    assert result.exit_code != 0
    assert f"{theme} syntax error" in result.output
    after = {
        path.relative_to(page): path.read_bytes()
        for path in page.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_init_does_not_partially_revendor_on_a_destination_conflict(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    page = tmp_path / "page"
    initialized = runner.invoke(interact.cli, ["page", "init", str(page)])
    assert initialized.exit_code == 0, initialized.output
    theme_before = (page / "theme.css").read_bytes()
    registry_before = (page / "registry.json").read_bytes()

    conflict = page / "widgets" / "cq-tabs.js"
    conflict.unlink()
    conflict.mkdir()
    layer = tmp_path / ".colloquy"
    layer.mkdir(parents=True)
    (layer / "theme.css").write_text(":root { --accent: rebeccapurple; }\n")
    (layer / "registry.json").write_text(
        json.dumps(
            {"cq-new-shape": interact.custom_widget_entry("cq-new-shape", False)}
        )
    )

    result = runner.invoke(interact.cli, ["page", "init", str(page)])

    assert result.exit_code != 0
    assert (page / "theme.css").read_bytes() == theme_before
    assert (page / "registry.json").read_bytes() == registry_before


@pytest.mark.parametrize("sub", ["versions", "widgets", "vendor"])
def test_init_refuses_a_symlinked_page_directory(tmp_path, monkeypatch, sub):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    page = tmp_path / "page"
    initialized = runner.invoke(interact.cli, ["page", "init", str(page)])
    assert initialized.exit_code == 0, initialized.output
    original = tmp_path / f"original-{sub}"
    (page / sub).rename(original)
    outside = tmp_path / f"outside-{sub}"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("do not prune or replace files outside the page")
    (page / sub).symlink_to(outside, target_is_directory=True)

    result = runner.invoke(interact.cli, ["page", "init", str(page)])

    assert result.exit_code != 0
    assert "must be a real directory, not a symlink" in result.output
    assert sentinel.read_text() == "do not prune or replace files outside the page"
    assert list(outside.iterdir()) == [sentinel]


@pytest.mark.parametrize(
    ("source_relative", "destination_relative"),
    [("vendor", "widgets"), ("theme.css", "registry.json")],
)
def test_init_refuses_a_layer_source_aliased_to_a_page_destination(
    tmp_path, monkeypatch, source_relative, destination_relative
):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    page = tmp_path / "page"
    initialized = runner.invoke(interact.cli, ["page", "init", str(page)])
    assert initialized.exit_code == 0, initialized.output
    destination = page / destination_relative
    if destination.is_dir():
        (destination / "keep-source.txt").write_text(
            "stale pruning must not delete a customization source"
        )

    source = tmp_path / ".colloquy" / source_relative
    source.parent.mkdir(parents=True)
    source.symlink_to(destination, target_is_directory=destination.is_dir())
    before = {
        path.relative_to(page): path.read_bytes()
        for path in page.rglob("*")
        if path.is_file()
    }

    result = runner.invoke(interact.cli, ["page", "init", str(page)])

    assert result.exit_code != 0
    assert "overlaps page destination" in result.output
    after = {
        path.relative_to(page): path.read_bytes()
        for path in page.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_init_refuses_a_case_aliased_source_at_a_page_destination(
    tmp_path, monkeypatch
):
    project = tmp_path / "Project"
    project.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.chdir(project)
    runner = CliRunner()
    page = tmp_path / "ReviewPage"
    initialized = runner.invoke(interact.cli, ["page", "init", str(page)])
    assert initialized.exit_code == 0, initialized.output
    alias = case_alias(page)
    target = alias / "THEME.CSS"
    assert target.samefile(page / "theme.css")
    before = {
        path.relative_to(page): path.read_bytes()
        for path in page.rglob("*")
        if path.is_file()
    }
    layer_theme = project / ".colloquy" / "theme.css"
    layer_theme.parent.mkdir(parents=True)
    layer_theme.symlink_to(target)

    result = runner.invoke(interact.cli, ["page", "init", str(page)])

    assert result.exit_code != 0
    assert "overlaps page destination" in result.output
    after = {
        path.relative_to(page): path.read_bytes()
        for path in page.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_init_preserves_tmp_files_even_when_a_layer_reads_one(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    page = tmp_path / "page"
    initialized = runner.invoke(interact.cli, ["page", "init", str(page)])
    assert initialized.exit_code == 0, initialized.output
    source = page / f"theme.css.{os.getpid()}.0.tmp"
    source.write_text(":root { --accent: rebeccapurple; }\n")
    layer = tmp_path / ".colloquy"
    layer.mkdir(parents=True)
    (layer / "theme.css").symlink_to(source)

    result = runner.invoke(interact.cli, ["page", "init", str(page)])

    assert result.exit_code == 0, result.output
    assert source.read_text() == ":root { --accent: rebeccapurple; }\n"
    assert (layer / "theme.css").is_symlink()


@pytest.mark.parametrize(
    ("relative", "directory"),
    [
        ("theme.css", True),
        ("registry.json", True),
        ("widgets", False),
        ("vendor", False),
    ],
)
def test_init_refuses_wrong_kind_customization_paths(
    tmp_path, monkeypatch, relative, directory
):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / ".colloquy" / relative
    path.parent.mkdir(parents=True)
    if directory:
        path.mkdir()
    else:
        path.write_text("not a directory")

    result = CliRunner().invoke(interact.cli, ["page", "init", str(tmp_path / "page")])

    assert result.exit_code != 0
    assert str(path) in result.output


def test_init_refuses_an_upgraded_custom_widget_without_its_module(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    scaffold = runner.invoke(interact.cli, ["customize", "widget", "cq-unfinished"])
    assert scaffold.exit_code == 0, scaffold.output

    registry_path = tmp_path / ".colloquy" / "registry.json"
    registry = json.loads(registry_path.read_text())
    registry["cq-unfinished"]["x-upgrade"] = True
    registry["cq-unfinished"]["x-verbatim"] = True
    registry_path.write_text(json.dumps(registry))

    result = runner.invoke(interact.cli, ["page", "init", str(tmp_path / "page")])
    assert result.exit_code != 0
    assert "widgets/cq-unfinished.js" in result.output


def test_init_refuses_a_registry_example_that_violates_its_schema(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    scaffold = runner.invoke(interact.cli, ["customize", "widget", "cq-toned-note"])
    assert scaffold.exit_code == 0, scaffold.output

    registry_path = tmp_path / ".colloquy" / "registry.json"
    registry = json.loads(registry_path.read_text())
    entry = registry["cq-toned-note"]
    entry["properties"]["tone"] = {"enum": ["quiet", "loud"]}
    entry["required"].append("tone")
    registry_path.write_text(json.dumps(registry))

    result = runner.invoke(interact.cli, ["page", "init", str(tmp_path / "page")])

    assert result.exit_code != 0
    assert "<cq-toned-note> x-example is invalid" in result.output
    assert "'tone' is a required property" in result.output


@pytest.mark.parametrize(
    ("example", "message"),
    [
        (
            '<cq-toned-note id="repeat"><p id="repeat">Two</p></cq-toned-note>',
            "duplicate ids",
        ),
        (
            '<cq-toned-note id="cq-example">One</cq-toned-note>',
            "cq- namespace",
        ),
    ],
    ids=["duplicate", "reserved"],
)
def test_init_refuses_invalid_ids_in_a_registry_example(
    tmp_path, monkeypatch, example, message
):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    scaffold = runner.invoke(interact.cli, ["customize", "widget", "cq-toned-note"])
    assert scaffold.exit_code == 0, scaffold.output
    registry_path = tmp_path / ".colloquy" / "registry.json"
    registry = json.loads(registry_path.read_text())
    registry["cq-toned-note"]["x-example"] = example
    registry_path.write_text(json.dumps(registry))

    result = runner.invoke(interact.cli, ["page", "init", str(tmp_path / "page")])

    assert result.exit_code != 0
    assert "<cq-toned-note> x-example is invalid" in result.output
    assert message in result.output


def test_revendoring_removes_files_the_layer_retired(page_dir):
    stale = page_dir / "widgets" / "cq-retired.js"
    stale.write_text("// no longer in any layer")
    result = CliRunner().invoke(interact.cli, ["page", "init", str(page_dir)])
    assert result.exit_code == 0, result.output
    assert not stale.exists()


@pytest.mark.parametrize(
    ("sub", "name"),
    [("widgets", "cq-returned.js"), ("vendor", "returned.js")],
)
def test_revendoring_removes_stale_broken_links_before_a_file_returns(
    page_dir, sub, name
):
    stale = page_dir / sub / name
    stale.symlink_to(page_dir.parent / "missing-target")

    retired = CliRunner().invoke(interact.cli, ["page", "init", str(page_dir)])

    assert retired.exit_code == 0, retired.output
    assert not stale.is_symlink()

    source = page_dir.parent / ".colloquy" / sub / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("// returned\n")
    returned = CliRunner().invoke(interact.cli, ["page", "init", str(page_dir)])

    assert returned.exit_code == 0, returned.output
    assert stale.is_file() and not stale.is_symlink()
    assert stale.read_text() == "// returned\n"
    assert source.read_text() == "// returned\n"


def test_check_accepts_a_valid_page(page_dir):
    result = check(page_dir)
    assert result.exit_code == 0, result.output


def test_check_rejects_widget_violations(page_dir):
    (page_dir / "versions" / "v1.html").write_text(
        PAGE.replace(
            '<a href="https://example.test/jobs/backfill.py#L88"><code>jobs/backfill.py:88</code></a>',
            '<cq-metric id="bad-metric" value="1"/>'
            "<figure/>"
            "<cq-bogus></cq-bogus>"
            '<cq-timeline id="bad-timeline">'
            '<cq-event id="stray-event" kind="medium">S</cq-event></cq-timeline>'
            '<cq-option id="stray"><strong>S</strong></cq-option>'
            '<cq-diagram id="Bad_ID"><pre>graph LR</pre><em>x</em></cq-diagram>'
            '<cq-diagram id="bare-body">graph LR</cq-diagram>',
        ).replace('<cq-option id="flag-first"', "<cq-option")
    )
    result = check(page_dir)
    assert result.exit_code == 1
    out = result.output
    # Both the widget and the plain <figure/>: the slash misleads a browser on
    # any non-void tag, not only on the vocabulary's.
    assert out.count("self-closing") == 2
    assert "unknown widget" in out
    assert "'medium' is not one of" in out
    assert "must be a direct child of <cq-options>" in out
    assert "'id' is a required property" in out
    assert "does not match" in out  # id pattern
    # A stray element beside the <pre>, and a body that never opened one: both are
    # the same rule, since the <pre> is what carries the whitespace the notation needs.
    assert out.count("its body is one <pre> holding the text") == 2
    assert "text outside its <pre>" in out


def test_check_rejects_duplicate_attributes_the_browser_reads_differently(page_dir):
    """A file reading cannot silently choose another id than the live DOM.

    HTML keeps the first duplicate attribute, while HTMLParser reports both and
    ``dict(attrs)`` keeps the last. Accepting this would let the action gate map
    a stateful widget under an id its browser can never send.
    """
    registry = json.loads((page_dir / "registry.json").read_text())
    board = registry["cq-board"]["x-example"].replace(
        'id="feeder-board"', 'id="browser-board" id="file-board"'
    )
    version = page_dir / "versions" / "v1.html"
    version.write_text(
        version.read_text().replace("</section>", board + "\n</section>")
    )

    result = check(page_dir)

    assert result.exit_code == 1
    assert "duplicate attribute" in result.output


def test_check_rejects_a_language_nothing_will_color(page_dir):
    """A declared language the runtime won't honor renders as a plain block, which is
    exactly what a block with no language renders as — so the reviewer sees nothing
    wrong and the author never finds out. Every way of getting it wrong is the lint's,
    because the author is the only one who can still fix any of them: the class somewhere
    other than <pre><code>, an unknown word on the class, and an unknown word on a
    widget attribute that declares itself a language (x-language). The last is checked
    against the same list as the first two rather than by that widget's own schema,
    which is what keeps a second tag taking a language from needing a second reader."""
    (page_dir / "versions" / "v1.html").write_text(
        PAGE.replace(
            "<h2>Plan</h2>",
            "<h2>Plan</h2>\n"
            '<pre><code class="language-pythn">x = 1</code></pre>\n'
            '<div class="note language-python">not a code block</div>\n'
            '<cq-code id="walk-bad" language="pythn"><pre>z = 3\n</pre></cq-code>\n'
            '<pre><code class="language-python">y = 2</code></pre>',
        )
    )
    result = check(page_dir)
    assert result.exit_code == 1
    out = result.output
    assert (
        'class="language-pythn"' in out
        and "not a language this page's layer speaks" in out
    )
    assert 'class="language-python"' in out and "only <pre><code> is colored" in out
    assert '<cq-code language="pythn">' in out, out
    # The well-formed block is not among the complaints.
    assert out.count('class="language-python"') == 1


def test_a_widget_that_declares_a_language_is_checked_by_that_alone(page_dir):
    """The list is the layer's fact, not one widget's, so nothing in the lint knows
    which widget takes a language: a tag whose entry declares x-language is held to
    $languages on the strength of the declaration. A thirteenth widget that colors
    something — a terminal transcript, a diff — is covered without the lint moving."""
    registry = json.loads((page_dir / "registry.json").read_text())
    registry["cq-tree"]["properties"]["dialect"] = {"type": "string"}
    registry["cq-tree"]["x-language"] = "dialect"
    (page_dir / "registry.json").write_text(json.dumps(registry))
    (page_dir / "versions" / "v1.html").write_text(
        PAGE.replace(
            "<h2>Plan</h2>",
            '<h2>Plan</h2>\n<cq-tree id="t" dialect="lisp"><pre>\nfeeders/\n</pre></cq-tree>',
        )
    )
    result = check(page_dir)
    assert result.exit_code == 1
    assert '<cq-tree dialect="lisp">' in result.output
    assert "not a language this page's layer speaks" in result.output


def test_the_block_content_lists_agree_and_cover_the_vocabulary():
    """Four selectors in the theme enumerate what counts as block content: the
    suggestion slots' blockization, the card form's exclusion, and the two
    stacked-group triggers (cq-options, cq-compare). A list like that fails
    quietly — a new block-level widget missing
    from one keeps rendering, just wrong: a suggestion wrapping it stays inline, a
    group holding it keeps the 13rem grid — so the copies are pinned to each other
    and to the registry: every top-level widget appears in each. cq-suggestion is
    the one exemption, display: contents, so the wrapper generates no box and its
    slots answer the block question instead."""
    theme = (interact.ASSETS / "theme.css").read_text()
    lists = re.findall(r":is\((p, h1[^)]*)\)", theme)
    assert len(lists) == 4, (
        "expected the suggestion-slot list, the card form's exclusion, and the two "
        "stacked-group triggers"
    )
    tag_sets = [{t.strip() for t in found.split(",")} for found in lists]
    assert tag_sets[0] == tag_sets[1] == tag_sets[2], (
        "the block-content lists have drifted"
    )
    registry = json.loads((interact.ASSETS / "registry.json").read_text())
    top_level = {
        tag
        for tag, entry in registry.items()
        if tag.startswith("cq-") and "x-parent" not in entry
    } - {"cq-suggestion"}
    assert top_level <= tag_sets[0], (
        f"block-level widgets missing from the theme's block-content lists: "
        f"{sorted(top_level - tag_sets[0])}"
    )


def test_a_tone_the_layer_cannot_paint_is_refused_where_the_author_can_still_fix_it(
    page_dir,
):
    """The same failure a misspelt language has, and caught for the same reason: a
    tone nothing matches paints nothing, so the chip renders neutral on a page that
    otherwise looks perfectly well. The reviewer cannot see it — they never knew it
    was meant to be red — so the only party who can still fix it is whoever wrote
    the word, and the lint is where they are told. This is the whole difference
    between the attribute and a class, which nothing checks."""
    (page_dir / "versions" / "v1.html").write_text(
        PAGE.replace(
            '<cq-option id="flag-first">',
            '<cq-option id="flag-first"><cq-chip tone="dangre">risk: high</cq-chip>',
        )
    )
    result = check(page_dir)
    assert result.exit_code == 1
    assert "not a tone this page's layer paints" in result.output
    assert "'ok', 'warn', 'danger'" in result.output.replace('"', "'")

    # The list is the layer's, so a layer that adds one accepts it with no widget
    # touched — which is the point of $tones over an enum on cq-chip.
    registry = json.loads((page_dir / "registry.json").read_text())
    registry["$tones"]["names"].append("dangre")
    (page_dir / "registry.json").write_text(json.dumps(registry))
    assert check(page_dir).exit_code == 0


def test_a_chip_is_admissible_in_both_its_holders(page_dir):
    """x-parent is a list because one element can belong to two holders, and a chip
    is written in a cq-option and in a cq-variant — the same shape either side of the
    decision. Neither is special-cased anywhere: the nesting check reads the list."""
    (page_dir / "versions" / "v1.html").write_text(
        PAGE.replace(
            "<cq-options>",
            '<cq-compare id="cmp"><cq-variant id="v-a"><cq-chip tone="ok">cheap</cq-chip>'
            "<strong>A</strong> One.</cq-variant></cq-compare>\n  <cq-options>",
        )
    )
    assert check(page_dir).exit_code == 0, check(page_dir).output

    # And refused where neither holder is its parent, naming both.
    (page_dir / "versions" / "v1.html").write_text(
        PAGE.replace("<h2>Plan</h2>", "<h2>Plan</h2><cq-chip>stray</cq-chip>")
    )
    result = check(page_dir)
    assert result.exit_code == 1
    assert "must be a direct child of <cq-option> or <cq-variant>" in result.output


def test_a_layer_naming_no_languages_refuses_every_word_rather_than_none(page_dir):
    """A layer that names none colors none, so a page declaring one is asking for
    something it cannot get. The list is therefore read and indexed, never tested for
    emptiness: an empty list that stood the check down would be a check retiring itself
    the moment its list moved — and this is the check whose failures the reviewer can't
    see either way, so silence is the one outcome it must not have."""
    registry = json.loads((page_dir / "registry.json").read_text())
    registry["$languages"]["names"] = []
    registry["$languages"]["paths"] = {}
    (page_dir / "registry.json").write_text(json.dumps(registry))
    (page_dir / "versions" / "v1.html").write_text(
        PAGE.replace(
            "<h2>Plan</h2>",
            '<h2>Plan</h2>\n<pre><code class="language-python">x = 1</code></pre>\n'
            '<div class="note language-python">not a code block</div>',
        )
    )
    result = check(page_dir)
    assert result.exit_code == 1
    assert "not a language this page's layer speaks" in result.output
    # The placement rule never rested on the list, so it reports here too.
    assert "only <pre><code> is colored" in result.output


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
    (page_dir / "versions" / "v1.html").write_text(
        PAGE.replace(" recommended>", ' recommended="">')
    )
    assert check(page_dir).exit_code == 0
    (page_dir / "versions" / "v1.html").write_text(
        PAGE.replace(" recommended>", ' recommended="yes">')
    )
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
    (page_dir / "versions" / f"v{version}.html").write_text(
        PAGE.replace("<cq-options>", markup)
    )


def decide(page_dir, outcome, widget="sug-refill"):
    interact.append_event(
        page_dir,
        {
            "kind": "action",
            "author": "user",
            "version": 1,
            "widget": widget,
            "action": outcome,
            "detail": {},
        },
    )


def test_suggestion_validates(page_dir):
    suggest(page_dir)
    assert check(page_dir, version=1).exit_code == 0, check(page_dir, version=1).output


def test_suggestion_rejects_malformed_shapes(page_dir):
    for markup, expected in [
        ('<cq-suggestion id="sug-a"></cq-suggestion><cq-options>', "needs a <cq-old>"),
        (
            (
                '<cq-suggestion id="sug-a"><cq-new><p>x</p></cq-new>'
                "<cq-new><p>y</p></cq-new></cq-suggestion><cq-options>"
            ),
            "one at most",
        ),
        (
            (
                '<cq-suggestion id="sug-a"><cq-new>'
                '<cq-suggestion id="sug-b"><cq-new>x</cq-new></cq-suggestion>'
                "</cq-new></cq-suggestion><cq-options>"
            ),
            "don't nest",
        ),
        (
            "<cq-old><p>orphan</p></cq-old><cq-options>",
            "must be a direct child of <cq-suggestion>",
        ),
        (
            (
                '<cq-suggestion id="sug-a" resolves="nosuch"><cq-new><p>x</p></cq-new>'
                "</cq-suggestion><cq-options>"
            ),
            "names no comment in the log",
        ),
    ]:
        (page_dir / "versions" / "v1.html").write_text(
            PAGE.replace("<cq-options>", markup)
        )
        result = check(page_dir, version=1)
        assert result.exit_code == 1, markup
        assert expected in result.output, f"{markup}\n{result.output}"


def test_suggestion_resolves_accepts_a_real_comment(page_dir):
    interact.append_event(
        page_dir, {"kind": "comment", "id": "c1", "author": "user", "text": "hm"}
    )
    markup = '<cq-suggestion id="sug-a" resolves="c1"><cq-new><p>x</p></cq-new></cq-suggestion><cq-options>'
    (page_dir / "versions" / "v1.html").write_text(PAGE.replace("<cq-options>", markup))
    assert check(page_dir, version=1).exit_code == 0


def test_accepting_licenses_retiring_the_replaced_markup(page_dir):
    # v2 honors the accept: the old paragraph and the wrapper are gone, the
    # proposal inlined. Nothing but a logged accept makes that legal.
    suggest(page_dir)
    honored = PAGE.replace(
        "<cq-options>",
        '<p id="refill-camera">Refill when the camera shows it half-empty.</p><cq-options>',
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
        PAGE.replace(
            "<cq-options>",
            '<p id="thistle-plan">Switch the north feeder to thistle in autumn.</p><cq-options>',
        )
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
        PAGE.replace(
            "<cq-options>",
            '<p id="refill-rule">Refill every feeder each morning.</p><cq-options>',
        )
    )
    interact.append_event(
        page_dir,
        {
            "kind": "comment",
            "id": "c1",
            "author": "user",
            "anchor": {"section": "refill-camera"},
            "text": "cameras aren't reliable yet",
        },
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
        PAGE.replace(
            "<cq-options>",
            '<p id="refill-rule">Refill every feeder each morning.</p><cq-options>',
        )
    )
    assert check(page_dir, version=2).exit_code == 0
    interact.append_event(
        page_dir,
        {
            "kind": "comment",
            "id": "c1",
            "author": "user",
            "anchor": {"section": "refill-camera"},
            "text": "why the camera?",
        },
    )
    result = check(page_dir, version=2)
    assert result.exit_code == 1
    assert "refill-camera" in result.output
    interact.append_event(
        page_dir, {"kind": "resolve", "author": "user", "parent": "c1"}
    )
    assert check(page_dir, version=2).exit_code == 0


def test_reply_refuses_a_suggestion(page_dir):
    interact.append_event(
        page_dir, {"kind": "comment", "id": "c1", "author": "user", "text": "hm"}
    )
    result = CliRunner().invoke(
        interact.cli,
        [
            "review",
            "reply",
            str(page_dir),
            "--to",
            "c1",
            "--text",
            "Fixed:",
            "--markup",
            '<cq-suggestion id="sug-x"><cq-new><p>fixed</p></cq-new></cq-suggestion>',
        ],
    )
    assert result.exit_code != 0
    assert "frozen in the log" in result.output


def test_check_rejects_wrong_scaffold(page_dir):
    html = PAGE.replace(
        '<script type="module" src="/colloquy.js"></script>', ""
    ).replace('<link rel="stylesheet" href="/theme.css">', "")
    (page_dir / "versions" / "v1.html").write_text(html)
    result = check(page_dir)
    assert result.exit_code == 1
    assert "exactly one external <script src>" in result.output
    assert "exactly one stylesheet" in result.output


def test_check_owns_the_cq_meta_vocabulary(page_dir):
    # The sign-off declaration: valid on its one value, rejected on a misspelled
    # value or name — either would silently declare nothing in the browser.
    signoff = PAGE.replace(
        "<title>t</title>",
        '<title>t</title>\n<meta name="cq-review" content="sign-off">',
    )
    (page_dir / "versions" / "v1.html").write_text(signoff)
    assert check(page_dir).exit_code == 0

    (page_dir / "versions" / "v1.html").write_text(
        signoff.replace("sign-off", "approve")
    )
    result = check(page_dir)
    assert result.exit_code == 1
    assert "content must be one of ['sign-off'], found 'approve'" in result.output

    (page_dir / "versions" / "v1.html").write_text(
        signoff.replace("cq-review", "cq-signoff")
    )
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
    says so. Whatever v2 does about it, `version check` is what has to notice."""
    (page_dir / "versions" / "v1.html").write_text(
        PAGE.replace(
            "<h2>Plan</h2>",
            f'<h2>Plan</h2><cq-draft id="d1"><pre>{words}</pre></cq-draft>',
        )
    )
    publish(page_dir)
    interact.append_event(
        page_dir,
        {
            "kind": "action",
            "author": "user",
            "version": 1,
            "widget": "d1",
            "action": "edit",
            "detail": {"text": "Cut the flag; backfill first."},
        },
    )
    return lambda words, attrs="": (page_dir / "versions" / "v2.html").write_text(
        PAGE.replace(
            "<h2>Plan</h2>",
            f'<h2>Plan</h2><cq-draft id="d1"{attrs}><pre>{words}</pre></cq-draft>',
        )
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
    assert check(page_dir, version=2).exit_code == 0, (
        "a republish that changes nothing must pass"
    )

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
        PAGE.replace(
            "<h2>Plan</h2>",
            '<h2>Plan</h2><cq-draft id="d1" restated><pre>Words.</pre></cq-draft>',
        )
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
    interact.append_event(
        page_dir,
        {
            "kind": "action",
            "author": "user",
            "version": 1,
            "widget": "b1",
            "action": "move",
            "detail": {"card": "card-x", "to": "c-done", "index": 0},
        },
    )
    assert check(page_dir).exit_code == 0

    # An untouched card rewritten, the moved card's own words left alone.
    write(2, [X, ("card-y", "", "Wire the importer and its backfill")], [])
    assert check(page_dir, version=2).exit_code == 0, (
        "an untouched card is not the gate's business"
    )

    # The card written where the reviewer put it. Redundant now that replay
    # carries the move, but a version that does it anyway is not wrong.
    write(2, [Y], [X])
    assert check(page_dir, version=2).exit_code == 0, (
        "relocating the moved card must pass"
    )

    # The moved card's own words rewritten: now the decision is in question.
    write(2, [("card-x", "", "Guard the delete behind the flag"), Y], [])
    result = check(page_dir, version=2)
    assert result.exit_code == 1
    assert "card-x" in result.output and "move on v1" in result.output
    assert "card-y" not in result.output, (
        "the gate named a card nobody had decided about"
    )

    write(2, [("card-x", " restated", "Guard the delete behind the flag"), Y], [])
    assert check(page_dir, version=2).exit_code == 0

    # And the board itself never takes the attribute: every move names a card, so
    # a board is never what a decision rests on, and offering `restated` there
    # would be a door onto an error message about retracting nothing.
    (page_dir / "versions" / "v2.html").write_text(
        (page_dir / "versions" / "v2.html")
        .read_text()
        .replace('<cq-board id="b1">', '<cq-board id="b1" restated>')
    )
    result = check(page_dir, version=2)
    assert result.exit_code == 1
    assert "restated" in result.output and "cq-board" in result.output


OPTIONS = """<cq-options id="g1" choose>
  <cq-option id="o-shim"{a}>{chip}<strong>Shim it</strong> {shim}</cq-option>
  <cq-option id="o-stage"{b}><strong>Migrate in stages</strong> {stage}</cq-option>
</cq-options>"""


def test_the_gate_reads_a_pick_the_same_way_it_reads_an_edit(page_dir):
    """The rule was built on drafts and boards; a pick is the case it was not
    built on. It lands the same way because nothing in it is per-widget: the
    subject is what the detail names, so a pick rests on the option picked. What
    the other options say is then free to change, and marking the pick `chosen`
    — the one thing every version does after a pick — says nothing, so it is
    invisible to the comparison.

    A chip is content rather than a mark, so writing one onto a picked option is
    changing what they picked and lands in the same comparison its prose does.
    The gate reads the version the way the anchor pass does, which is what keeps
    that true without anything here knowing a chip from a paragraph."""

    def write(version, **kw):
        opts = OPTIONS.format(
            **{
                "a": "",
                "b": "",
                "chip": "",
                "shim": "Fastest to ship.",
                "stage": "Table by table.",
                **kw,
            }
        )
        (page_dir / "versions" / f"v{version}.html").write_text(
            PAGE.replace("<h2>Plan</h2>", "<h2>Plan</h2>" + opts)
        )

    write(1)
    publish(page_dir)
    interact.append_event(
        page_dir,
        {
            "kind": "action",
            "author": "user",
            "version": 1,
            "widget": "g1",
            "action": "choose",
            "detail": {"options": ["o-shim"]},
        },
    )
    assert check(page_dir).exit_code == 0

    # The record the next version owes: the picked card marked, nothing else.
    write(2, a=" chosen")
    assert check(page_dir, version=2).exit_code == 0, (
        "marking the pick is not a rewrite"
    )

    # An option nobody picked, rewritten freely.
    write(2, a=" chosen", stage="One table at a time, behind a flag.")
    assert check(page_dir, version=2).exit_code == 0, (
        "an unpicked option is free to change"
    )

    # The picked one, rewritten — the reviewer chose those words.
    write(2, a=" chosen", shim="Fastest to ship, and we own the shim forever.")
    result = check(page_dir, version=2)
    assert result.exit_code == 1
    assert "o-shim" in result.output and "choose on v1" in result.output

    write(2, a=" chosen restated", shim="Fastest to ship, and we own the shim forever.")
    assert check(page_dir, version=2).exit_code == 0

    # A chip is a word on the page: one appearing on the option they picked reads
    # to them as the option changing, and is caught the same way its prose is.
    write(2, a=" chosen", chip="<cq-chip>effort: high</cq-chip>")
    result = check(page_dir, version=2)
    assert result.exit_code == 1, "a chip is words the reviewer read"
    assert "o-shim" in result.output

    write(2, a=" chosen restated", chip="<cq-chip>effort: high</cq-chip>")
    assert check(page_dir, version=2).exit_code == 0


def test_a_cleared_pick_rests_on_the_group_that_holds_it(page_dir):
    """Clearing a pick names no option (`{"options": []}`), so there is no part
    of the widget for the decision to rest on and it rests on the group. That
    falls out of the subject rule rather than being written for this case — which
    is why the group takes `restated` and a board, whose every move names a card,
    does not."""

    def write(version, shim="Fastest to ship.", attrs=""):
        opts = OPTIONS.format(a="", b="", chip="", shim=shim, stage="Table by table.")
        (page_dir / "versions" / f"v{version}.html").write_text(
            PAGE.replace(
                "<h2>Plan</h2>",
                "<h2>Plan</h2>"
                + opts.replace(
                    '<cq-options id="g1" choose>', f'<cq-options id="g1" choose{attrs}>'
                ),
            )
        )

    write(1)
    publish(page_dir)
    interact.append_event(
        page_dir,
        {
            "kind": "action",
            "author": "user",
            "version": 1,
            "widget": "g1",
            "action": "choose",
            "detail": {"options": []},
        },
    )
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
        opts = OPTIONS.format(a=a, b=b, chip="", shim=shim, stage="Table by table.")
        (page_dir / "versions" / f"v{version}.html").write_text(
            PAGE.replace(
                "<h2>Plan</h2>",
                "<h2>Plan</h2>"
                + opts.replace(
                    '<cq-options id="g1" choose>', f'<cq-options id="g1" choose{attrs}>'
                ),
            )
        )

    write(1)
    publish(page_dir)
    interact.append_event(
        page_dir,
        {
            "kind": "action",
            "author": "user",
            "version": 1,
            "widget": "g1",
            "action": "choose",
            "detail": {"options": ["o-shim"]},
        },
    )

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
        interact.cli,
        [
            "version",
            "publish",
            str(page_dir),
            "--version",
            "2",
            "--text",
            "moved the default",
        ],
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
    the markup, so `version check` says where it lags the log, as advice on a passing
    run. `review transcript` says the same to stderr, where the debt stops being
    fixable."""

    def write(version, a=""):
        opts = OPTIONS.format(
            a=a, b="", chip="", shim="Fastest to ship.", stage="Table by table."
        )
        (page_dir / "versions" / f"v{version}.html").write_text(
            PAGE.replace("<h2>Plan</h2>", "<h2>Plan</h2>" + opts)
        )

    write(1)
    publish(page_dir)
    interact.append_event(
        page_dir,
        {
            "kind": "action",
            "author": "user",
            "version": 1,
            "widget": "g1",
            "action": "choose",
            "detail": {"options": ["o-shim"]},
        },
    )
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

    result = CliRunner().invoke(interact.cli, ["review", "transcript", str(page_dir)])
    assert "record behind the log" in result.output  # CliRunner folds stderr in


def test_check_advises_where_a_reviewers_aim_has_nothing_to_land_on(page_dir):
    """A block a reviewer points at whole needs an id, or the aim falls through to
    the enclosing section — the failure item anchoring's own page shipped. Advice
    on a passing run, not a gate, and quiet where a tight wrapper (a figure around
    a table) already gives the aim something to hold."""
    blocks = (
        "<pre><code>uv run backfill --check</code></pre>"
        '<figure id="fig"><table><tr><td>1</td></tr></table></figure>'
    )
    (page_dir / "versions" / "v1.html").write_text(
        PAGE.replace("<h2>Plan</h2>", "<h2>Plan</h2>" + blocks).replace(
            "</main>", "<section><p>Unnamed aside.</p></section>\n</main>"
        )
    )
    result = check(page_dir)
    assert result.exit_code == 0, result.output
    advice = [line for line in result.output.splitlines() if "unpointable" in line]
    assert len(advice) == 2, result.output
    assert any("<pre>" in line and "#plan" in line for line in advice)
    assert any("<section>" in line for line in advice)
    assert not any(
        "<table>" in line for line in advice
    )  # the figure's id is aim enough

    # Ids minted, debt gone.
    (page_dir / "versions" / "v1.html").write_text(
        PAGE.replace(
            "<h2>Plan</h2>",
            '<h2>Plan</h2><pre id="cmd"><code>uv run backfill --check</code></pre>',
        )
    )
    result = check(page_dir)
    assert result.exit_code == 0, result.output
    assert "unpointable" not in result.output


def test_an_accept_carries_its_thread_resolution(page_dir):
    """One atomic event: the accept snapshots the thread it answers, because the
    honoring version retires the wrapper that held the `resolves` mapping and a
    second POST could fail alone. A reject answers nothing."""
    interact.append_event(
        page_dir,
        {"kind": "comment", "id": "c1", "author": "user", "text": "cameras are flaky"},
    )
    interact.append_event(
        page_dir,
        {
            "kind": "comment",
            "id": "c2",
            "author": "user",
            "text": "and the other thing",
        },
    )
    interact.append_event(
        page_dir,
        {
            "kind": "action",
            "author": "user",
            "version": 1,
            "widget": "sug-a",
            "action": "accept",
            "detail": {"resolves": "c1"},
        },
    )
    interact.append_event(
        page_dir,
        {
            "kind": "action",
            "author": "user",
            "version": 1,
            "widget": "sug-b",
            "action": "reject",
            "detail": {},
        },
    )
    threads = interact.build_threads(interact.read_events(page_dir))
    assert threads["c1"]["resolved"] is True
    assert threads["c2"]["resolved"] is False


def test_init_refuses_a_log_the_incoming_layer_no_longer_speaks(page_dir):
    """The log is append-only and a retired verb has no successor to map to, so
    re-vendoring over one is how recorded decisions fall silent — annabels-drafts
    holds fifteen `decide` events today's widgets would drop on the first reload.
    The re-vendor is refused rather than offering a way to discard that history."""
    # This models a page made under an older registry where cq-draft declared
    # `decide`: the tag and widget id survive, but the incoming verb does not.
    version = page_dir / "versions" / "v1.html"
    version.write_text(
        version.read_text().replace(
            "<h2>Plan</h2>",
            '<h2>Plan</h2><cq-draft id="d1"><pre>A decision.</pre></cq-draft>',
        )
    )
    publish(page_dir)
    interact.append_event(
        page_dir,
        {
            "kind": "action",
            "author": "user",
            "version": 1,
            "widget": "d1",
            "action": "decide",
            "detail": {"decision": "approved"},
        },
    )
    result = CliRunner().invoke(interact.cli, ["page", "init", str(page_dir)])
    assert result.exit_code != 0
    assert "no longer speaks" in result.output
    assert "decide" in result.output


def test_init_refuses_a_logged_event_field_the_incoming_layer_no_longer_speaks(
    page_dir,
):
    """An older or custom layer may have added a field without adding a kind.
    The vocabulary stamp promises both, so retaining the kind alone cannot make
    the recorded field meaningful to the incoming runtime."""
    publish(page_dir)
    interact.append_event(
        page_dir,
        {
            "kind": "comment",
            "author": "claude",
            "agent": "Codex",
            "mood": "uncertain",
            "version": 1,
            "text": "Does this still mean anything?",
        },
    )

    result = CliRunner().invoke(interact.cli, ["page", "init", str(page_dir)])

    assert result.exit_code != 0
    assert "no longer speaks" in result.output
    assert "comment" in result.output and "mood" in result.output


def test_init_tracks_logged_verbs_by_the_widget_that_declared_them(page_dir):
    """Another tag using the same verb cannot keep a retired contract alive."""
    registry = json.loads((page_dir / "registry.json").read_text())
    board = registry["cq-board"]["x-example"]
    version = page_dir / "versions" / "v1.html"
    version.write_text(
        version.read_text().replace("</section>", board + "\n</section>")
    )
    publish(page_dir)
    interact.append_event(
        page_dir,
        {
            "kind": "action",
            "author": "user",
            "version": 1,
            "widget": "feeder-board",
            "action": "move",
            "detail": {"card": "card-baffle", "to": "col-doing", "index": 0},
        },
    )

    move_spec = registry["cq-board"]["x-state"]["move"]
    board_entry = registry["cq-board"]
    board_entry.pop("x-state")
    # Reusing the generic verb on another widget leaves the global verb set
    # unchanged, but cannot make an old cq-board action meaningful there.
    registry["cq-draft"]["x-state"]["move"] = move_spec
    overlay = page_dir.parent / ".colloquy"
    overlay.mkdir(parents=True)
    (overlay / "registry.json").write_text(
        json.dumps(
            {
                "cq-board": board_entry,
                "cq-draft": registry["cq-draft"],
            }
        )
    )

    result = CliRunner().invoke(interact.cli, ["page", "init", str(page_dir)])

    assert result.exit_code != 0
    assert "no longer speaks" in result.output
    assert "cq-board" in result.output and "move" in result.output


def test_init_refuses_an_incoming_detail_contract_that_rejects_logged_actions(
    page_dir,
):
    """Keeping a verb's spelling is not enough if its payload no longer replays."""
    registry = json.loads((page_dir / "registry.json").read_text())
    board = registry["cq-board"]["x-example"]
    version = page_dir / "versions" / "v1.html"
    version.write_text(
        version.read_text().replace("</section>", board + "\n</section>")
    )
    publish(page_dir)
    interact.append_event(
        page_dir,
        {
            "kind": "action",
            "author": "user",
            "version": 1,
            "widget": "feeder-board",
            "action": "move",
            "detail": {"card": "card-baffle", "to": "col-doing", "index": 0},
        },
    )

    registry["cq-board"]["x-state"]["move"]["detail"]["properties"]["index"][
        "minimum"
    ] = 1
    overlay = page_dir.parent / ".colloquy"
    overlay.mkdir(parents=True)
    (overlay / "registry.json").write_text(
        json.dumps({"cq-board": registry["cq-board"]})
    )

    result = CliRunner().invoke(interact.cli, ["page", "init", str(page_dir)])

    assert result.exit_code != 0
    assert "no longer speaks" in result.output
    assert "cq-board" in result.output and "move" in result.output
    assert "detail" in result.output


def test_check_refuses_a_malformed_registry(page_dir):
    (page_dir / "registry.json").write_text("{broken")
    result = check(page_dir)
    assert result.exit_code != 0
    assert "invalid JSON" in result.output


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        (None, "registry entries must be objects"),
        ({"type": "not-a-schema-type"}, "not a valid JSON Schema"),
    ],
)
def test_check_refuses_a_malformed_widget_schema(page_dir, entry, message):
    registry = json.loads((page_dir / "registry.json").read_text())
    registry["cq-options"] = entry
    (page_dir / "registry.json").write_text(json.dumps(registry))
    result = check(page_dir)
    assert result.exit_code != 0
    assert "cq-options" in result.output and message in result.output


@pytest.mark.parametrize(("subschema", "exit_code"), [(True, 0), (False, 1)])
def test_boolean_attribute_subschemas_validate_without_crashing(
    page_dir, subschema, exit_code
):
    registry = json.loads((page_dir / "registry.json").read_text())
    registry["cq-options"]["properties"]["choose"] = subschema
    (page_dir / "registry.json").write_text(json.dumps(registry))
    version = page_dir / "versions" / "v1.html"
    version.write_text(
        version.read_text().replace("<cq-options>", '<cq-options id="opts" choose>')
    )

    result = check(page_dir)
    assert result.exit_code == exit_code, result.output
    assert not isinstance(result.exception, AttributeError)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("x-content", "words"),
        ("x-parent", []),
        ("x-says", []),
        ("x-state", []),
        ("x-upgrade", "yes"),
        ("x-verbatim", "false"),
        ("x-unknown", True),
    ],
)
def test_check_refuses_malformed_registry_extensions(page_dir, key, value):
    """Custom registry keywords are executable contracts, not schema comments."""
    registry = json.loads((page_dir / "registry.json").read_text())
    registry["cq-options"][key] = value
    (page_dir / "registry.json").write_text(json.dumps(registry))

    result = check(page_dir)
    assert result.exit_code != 0
    assert "<cq-options> registry extensions are invalid" in result.output


@pytest.mark.parametrize("tag", ["cq-options[", "CQ-options", "cq_options"])
def test_check_refuses_a_widget_name_that_cannot_form_a_selector(page_dir, tag):
    registry = json.loads((page_dir / "registry.json").read_text())
    registry[tag] = registry.pop("cq-options")
    (page_dir / "registry.json").write_text(json.dumps(registry))

    result = check(page_dir)
    assert result.exit_code != 0
    assert f"invalid registry entry names: ['{tag}']" in result.output


def test_check_refuses_an_invalid_action_detail_schema(page_dir):
    registry = json.loads((page_dir / "registry.json").read_text())
    registry["cq-options"]["x-state"]["choose"]["detail"]["type"] = "not-a-type"
    (page_dir / "registry.json").write_text(json.dumps(registry))

    result = check(page_dir)
    assert result.exit_code != 0
    assert (
        "<cq-options> x-state verb `choose` has an invalid detail schema"
        in result.output
    )


def test_action_detail_schemas_match_the_post_object_contract(page_dir):
    registry = json.loads((page_dir / "registry.json").read_text())
    registry["cq-suggestion"]["x-state"]["accept"]["detail"] = {"type": "string"}
    (page_dir / "registry.json").write_text(json.dumps(registry))

    result = check(page_dir)
    assert result.exit_code != 0
    assert "detail schema must declare an object" in result.output


@pytest.mark.parametrize("subschema", [True, False])
def test_state_reader_fields_reject_boolean_subschemas(page_dir, subschema):
    registry = json.loads((page_dir / "registry.json").read_text())
    registry["cq-options"]["x-state"]["choose"]["detail"]["properties"]["options"] = (
        subschema
    )
    (page_dir / "registry.json").write_text(json.dumps(registry))

    result = check(page_dir)
    assert result.exit_code != 0
    assert "record value `options` must be an array of strings" in result.output


def test_fold_units_are_required_strings(page_dir):
    registry = json.loads((page_dir / "registry.json").read_text())
    card = registry["cq-board"]["x-state"]["move"]["detail"]["properties"]["card"]
    card["type"] = "integer"
    (page_dir / "registry.json").write_text(json.dumps(registry))

    result = check(page_dir)
    assert result.exit_code != 0
    assert "fold unit `card` must be a string" in result.output


@pytest.mark.parametrize(
    ("tag", "verb", "field"),
    [
        ("cq-options", "choose", "options"),
        ("cq-draft", "edit", "text"),
    ],
)
def test_per_part_state_records_positions(page_dir, tag, verb, field):
    registry = json.loads((page_dir / "registry.json").read_text())
    spec = registry[tag]["x-state"][verb]
    spec["unit"] = field
    spec["detail"]["properties"][field]["type"] = "string"
    (page_dir / "registry.json").write_text(json.dumps(registry))

    result = check(page_dir)
    assert result.exit_code != 0
    assert f"<{tag}> x-state verb `{verb}` records per-part state" in result.output
    assert "only position records support that" in result.output


@pytest.mark.parametrize(
    ("tag", "verb", "field", "wanted"),
    [
        # An attribute record names the set of elements wearing it, so its detail field
        # is a list whatever the widget allows at once; the other two name one thing.
        ("cq-options", "choose", "options", "must be an array of strings"),
        ("cq-board", "move", "to", "must be a string"),
        ("cq-draft", "edit", "text", "must be a string"),
    ],
)
def test_record_values_have_the_type_the_reader_uses(
    page_dir, tag, verb, field, wanted
):
    registry = json.loads((page_dir / "registry.json").read_text())
    spec = registry[tag]["x-state"][verb]
    spec["detail"]["properties"][field] = {"type": "integer"}
    (page_dir / "registry.json").write_text(json.dumps(registry))

    result = check(page_dir)
    assert result.exit_code != 0
    assert f"<{tag}> x-state verb `{verb}` record value `{field}`" in result.output
    assert wanted in result.output


def test_registry_cross_entry_checks_wait_for_every_entry_to_validate(page_dir):
    """A child appearing first must not inspect a malformed parent half-validated."""
    registry = json.loads((page_dir / "registry.json").read_text())
    child = registry.pop("cq-old")
    registry["cq-suggestion"]["x-state"] = 42
    registry = {"cq-old": child, **registry}
    (page_dir / "registry.json").write_text(json.dumps(registry))

    result = check(page_dir)
    assert result.exit_code != 0
    assert "<cq-suggestion> registry extensions are invalid" in result.output


def test_state_requires_an_upgraded_widget(page_dir):
    registry = json.loads((page_dir / "registry.json").read_text())
    registry["cq-options"]["x-upgrade"] = False
    (page_dir / "registry.json").write_text(json.dumps(registry))

    result = check(page_dir)
    assert result.exit_code != 0
    assert "<cq-options> declares x-state but has no upgraded handler" in result.output


def test_retirement_requires_a_parent(page_dir):
    registry = json.loads((page_dir / "registry.json").read_text())
    del registry["cq-old"]["x-parent"]
    (page_dir / "registry.json").write_text(json.dumps(registry))

    result = check(page_dir)
    assert result.exit_code != 0
    assert "<cq-old> registry extensions are invalid" in result.output


def test_check_refuses_a_retirement_verb_its_parent_does_not_declare(page_dir):
    """A retirement outcome is a cross-entry reference, not a free-form label.

    If it names no verb on the parent widget, the browser's selector can never
    match and the file reading can disagree with what that widget knows how to
    settle. Refuse that vocabulary at its one ingress instead of leaving every
    consumer to rediscover the broken reference.
    """
    registry = json.loads((page_dir / "registry.json").read_text())
    registry["cq-old"]["x-retired-when"] = "approve"
    (page_dir / "registry.json").write_text(json.dumps(registry))

    result = check(page_dir)
    assert result.exit_code != 0
    assert "<cq-old> x-retired-when `approve`" in result.output
    assert "<cq-suggestion> does not declare that x-state verb" in result.output


def test_retirement_verbs_fold_by_the_parent_widget(page_dir):
    registry = json.loads((page_dir / "registry.json").read_text())
    accept = registry["cq-suggestion"]["x-state"]["accept"]
    accept["unit"] = "resolves"
    accept["detail"]["required"] = ["resolves"]
    (page_dir / "registry.json").write_text(json.dumps(registry))

    result = check(page_dir)
    assert result.exit_code != 0
    assert "<cq-old> x-retired-when `accept` must fold by widget" in result.output


@pytest.mark.parametrize("section", ["$events", "$languages", "$tones"])
def test_init_requires_the_complete_registry_contract(page_dir, tmp_path, section):
    overlay = tmp_path / ".colloquy"
    overlay.mkdir(parents=True)
    # Omission inherits the lower layer; supplying an entry replaces it whole,
    # so this incomplete replacement must fail merged-registry validation.
    (overlay / "registry.json").write_text(json.dumps({section: {}}))

    result = CliRunner().invoke(interact.cli, ["page", "init", str(page_dir)])
    assert result.exit_code != 0
    assert "$events.kinds, $languages.names/paths and $tones.names" in result.output


@pytest.mark.parametrize("names", ["ok", ["ok", "ok"], ["ok", 1]])
def test_init_requires_tones_to_be_a_list_membership_can_be_tested_against(
    page_dir, tmp_path, names
):
    """Presence is not enough, because the tone check asks this list for membership.
    A string answers by substring, so a layer declaring `"names": "ok"` would pass
    `tone="o"` and paint nothing — the invisible failure the tone check exists to
    catch, arriving through the very entry that declares the vocabulary."""
    overlay = tmp_path / ".colloquy"
    overlay.mkdir(parents=True)
    (overlay / "registry.json").write_text(json.dumps({"$tones": {"names": names}}))

    result = CliRunner().invoke(interact.cli, ["page", "init", str(page_dir)])
    assert result.exit_code != 0
    assert "$tones.names must be a unique list of strings" in result.output


@pytest.mark.parametrize("field", [None, "restated"])
def test_init_requires_the_event_vocabulary_the_layer_writes(page_dir, tmp_path, field):
    overlay = tmp_path / ".colloquy"
    overlay.mkdir(parents=True)
    registry = json.loads((page_dir / "registry.json").read_text())
    if field is None:
        del registry["$events"]["kinds"]["note"]
    else:
        registry["$events"]["kinds"]["note"].remove(field)
    (overlay / "registry.json").write_text(json.dumps(registry))

    result = CliRunner().invoke(interact.cli, ["page", "init", str(page_dir)])
    assert result.exit_code != 0
    assert "current layer writes" in result.output
    assert "note" in result.output
    if field:
        assert field in result.output


def test_a_widget_nobody_has_touched_is_not_the_gate_s_business(page_dir):
    """The gate is about decisions, so it holds nothing against a version that
    rewrites a widget the reviewer never acted on."""
    (page_dir / "versions" / "v1.html").write_text(
        PAGE.replace(
            "<h2>Plan</h2>",
            '<h2>Plan</h2><cq-draft id="d1"><pre>First words.</pre></cq-draft>',
        )
    )
    publish(page_dir)
    (page_dir / "versions" / "v2.html").write_text(
        PAGE.replace(
            "<h2>Plan</h2>",
            '<h2>Plan</h2><cq-draft id="d1"><pre>Quite different words.</pre></cq-draft>',
        )
    )
    assert check(page_dir, version=2).exit_code == 0


def test_check_requires_the_vendored_layer(tmp_path):
    d = tmp_path / "bare"
    (d / "versions").mkdir(parents=True)
    (d / "versions" / "v1.html").write_text(PAGE)
    result = check(d)
    assert result.exit_code == 1
    assert "run `colloquy page init` to vendor the layer" in result.output


def test_check_takes_column_width_from_vendored_theme(page_dir):
    # theme.css sets a 720px main column; a wider fixed-width element must fail.
    (page_dir / "versions" / "v1.html").write_text(
        PAGE.replace(
            "<h2>Plan</h2>", '<h2>Plan</h2><svg width="900" height="10"></svg>'
        )
    )
    result = check(page_dir)
    assert result.exit_code == 1
    assert "exceeds column (720px)" in result.output


def test_media_names_a_file_by_its_bytes_and_serves_it(page_dir, tmp_path, server):
    """An image reaches a page by reference, because the page's author is a language
    model and a screenshot is a megabyte of base64 it cannot type. The name is the
    hash of the bytes, which is what lets the page directory keep its promise while
    holding content: two versions showing the same screenshot share the one file, and
    a name the reviewer has already approved can never come to mean different pixels."""
    shot = tmp_path / "nav.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"pretend pixels")
    (url,) = [u for _, u in interact.cmd_media(page_dir, [shot])]
    assert re.fullmatch(r"/media/[a-f0-9]{16}\.png", url)
    # Re-adding the same bytes is the same file, not a second copy of it.
    assert interact.cmd_media(page_dir, [shot])[0][1] == url
    assert len(list((page_dir / "media").iterdir())) == 1

    status, body = fetch(server + url)
    assert (status, body) == (200, shot.read_bytes())
    # And nothing else out of the directory: the log is not a served path.
    assert fetch(server + "/comments.jsonl")[0] == 404


def test_check_names_a_media_reference_the_directory_cannot_answer(page_dir):
    """A broken image is silent in the file and obvious on the page. The render gate
    would see the 404, but it runs once; this runs on every version, and whether a
    file is there is as deterministic as whether an id is."""
    (page_dir / "versions" / "v1.html").write_text(
        PAGE.replace(
            "<h2>Plan</h2>",
            '<h2>Plan</h2><p><img alt="x" src="/media/deadbeefdeadbeef.png"></p>',
        )
    )
    result = check(page_dir)
    assert result.exit_code == 1
    assert "/media/deadbeefdeadbeef.png isn't in the page directory" in result.output

    # A mention is not a reference: a page explaining colloquy writes one of these
    # paths in its prose, and reading the markup rather than the attributes would
    # send its author hunting for a screenshot the page never asks for.
    (page_dir / "versions" / "v1.html").write_text(
        PAGE.replace(
            "<h2>Plan</h2>",
            '<h2>Plan</h2><p>Write it as <code>"/media/deadbeefdeadbeef.png"</code>.</p>',
        )
    )
    assert check(page_dir).exit_code == 0


def test_check_reads_only_the_page_stylesheet_and_stays_near_free(page_dir):
    """A version's CSS is what its <style> blocks hold. Reading the whole file as one
    made a megabyte of base64 (one screenshot as a data: URI) into a stylesheet to
    tokenize, and the rule scanner reading it used to backtrack quadratically across any
    long brace-free run, which took the better part of an hour. The clock bound is three
    orders of magnitude above the fixed cost, so it fails on a re-introduced quadratic
    and not on a slow machine; the assertion above it fails on the shape that fed it the
    page."""
    blob = "A" * 1_000_000
    html = PAGE.replace(
        "<h2>Plan</h2>",
        f'<h2>Plan</h2><p><img alt="shot" src="data:image/png;base64,{blob}"></p>',
    )
    (page_dir / "versions" / "v1.html").write_text(html)
    parser = interact._StructParser()
    parser.feed(html)
    parser.close()
    assert parser.css == ""

    started = time.monotonic()
    assert check(page_dir).exit_code == 0
    assert time.monotonic() - started < 10


def styled(css, body='<svg width="10" height="10"></svg>'):
    """PAGE with `css` as its own stylesheet and `body` after the first heading."""
    return PAGE.replace("</head>", f"<style>{css}</style></head>").replace(
        "<h2>Plan</h2>", f"<h2>Plan</h2>{body}"
    )


def test_check_reads_a_page_stylesheet_as_css(page_dir):
    """Grammar, not brace-counting. A `}` inside a string is a character, and counting it
    as the end of a block drops every declaration after it in that rule. A comment's
    braces are not braces either. And an @media wraps rules of its own, which a walk that
    read the sheet as one flat run of blocks would attribute to the query."""

    def checked(css):
        (page_dir / "versions" / "v1.html").write_text(styled(css))
        return check(page_dir)

    assert (
        "sets width: 900px" in checked("@media print { .wide { width: 900px } }").output
    )
    assert (
        "sets width: 900px"
        in checked('.wide::before { content: "}"; width: 900px }').output
    )
    assert checked("/* .wide { width: 900px } */").exit_code == 0


def test_check_reports_css_syntax_errors_in_every_authored_source(page_dir):
    theme = page_dir / "theme.css"
    theme.write_text(theme.read_text() + "\n.theme { color red; }\n")
    (page_dir / "versions" / "v1.html").write_text(
        styled(
            '.page { color: "unterminated\n; }',
            '<p style="color red">All three CSS inputs are malformed.</p>',
        )
    )

    result = check(page_dir)

    assert result.exit_code == 1
    assert "page <style> syntax error" in result.output
    assert "inline style #1 syntax error" in result.output
    assert "theme.css syntax error" in result.output
    assert result.output.count("syntax error") == 3


def test_check_takes_its_column_from_what_a_page_states_outright(page_dir):
    """A rule inside an at-rule applies only when a condition this check never evaluates
    holds, which cuts both ways. It cannot set the column, because the column is the
    baseline everything else is measured against — reading it there let one line of print
    CSS measure every screen element against 2000px and pass the page. It can overflow
    one, because a pin is a risk rather than a baseline: it is too wide whenever its
    condition holds."""
    (page_dir / "versions" / "v1.html").write_text(
        styled(
            "main { max-width: 760px } @media print { main { max-width: 2000px } }",
            '<svg width="900" height="10"></svg>',
        )
    )
    result = check(page_dir)
    assert result.exit_code == 1
    assert '<svg width="900"> exceeds column (760px)' in result.output

    # And nesting is not a condition: a column stated on a rule that also wraps one stands.
    (page_dir / "versions" / "v1.html").write_text(
        styled(
            "main { max-width: 1000px; & p { color: red } }",
            '<svg width="900" height="10"></svg>',
        )
    )
    assert check(page_dir).exit_code == 0


def test_check_counts_only_a_width_fixed_in_pixels(page_dir):
    """A length is a typed value, not a string ending in `px`. A percentage or a vw
    scales to whatever contains it, and a calc() with a px term inside it is arithmetic
    rather than a pin — only a lone pixel length can overflow the column."""
    (page_dir / "versions" / "v1.html").write_text(
        styled(".a { width: 200% } .b { width: 90vw } .c { width: calc(100% - 900px) }")
    )
    assert check(page_dir).exit_code == 0

    (page_dir / "versions" / "v1.html").write_text(
        styled(".d { width: 900px !important }")
    )
    assert "sets width: 900px" in check(page_dir).output


def test_check_measures_against_the_column_the_page_sets_for_itself(page_dir):
    """A page-local <style> is the page's own answer to how wide it reads, so it wins
    over the vendored theme's 720px and an element wider than the theme allows passes."""
    (page_dir / "versions" / "v1.html").write_text(
        styled("main { max-width: 1000px }", '<svg width="900" height="10"></svg>')
    )
    assert check(page_dir).exit_code == 0


def test_check_reads_widths_where_the_document_states_them(page_dir):
    """A width is what an attribute or a <style> block states. Scanning the file's text
    for one instead read a rule quoted in the page's prose as a rule the page applies,
    and never saw a style="" written with the other quote character."""
    (page_dir / "versions" / "v1.html").write_text(
        PAGE.replace(
            "<h2>Plan</h2>", "<h2>Plan</h2><div style='width:900px'>wide</div>"
        )
    )
    result = check(page_dir)
    assert result.exit_code == 1
    assert "inline style width: 900px (column is 720px)" in result.output

    (page_dir / "versions" / "v1.html").write_text(
        PAGE.replace(
            "<h2>Plan</h2>",
            "<h2>Plan</h2><p>Write it as <code>.wide { width: 900px }</code>.</p>",
        )
    )
    assert check(page_dir).exit_code == 0


# A page's key is minted per page; fixed here so a test can build a URL for a
# server it did not start.
TOKEN = "test-page-key"


@pytest.fixture
def server(page_dir):
    """A real HTTP server over the page directory, on an ephemeral port."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), interact.handler_for(page_dir, TOKEN))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def fetch(url, data=None, token=TOKEN):
    """A request arriving the way a reviewer's does: the key in the query, and a
    cookie jar to carry it onward — `/` redirects to the latest version, and the
    followed request is authorized by the cookie the redirect set, not by the query
    it drops. Pass token=None for the reader who never had the link."""
    if token:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode({"t": token})
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    try:
        with opener.open(url, data=data) as res:
            return res.status, res.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_server_round_trip(server, page_dir):
    registry = json.loads((page_dir / "registry.json").read_text())
    version = page_dir / "versions" / "v1.html"
    version.write_text(
        version.read_text().replace(
            "</section>", registry["cq-board"]["x-example"] + "\n</section>"
        )
    )
    # Unnoted version: nothing published yet.
    status, _ = fetch(f"{server}/")
    assert status == 404
    status, _ = fetch(f"{server}/versions/v1.html")
    assert status == 404
    CliRunner().invoke(
        interact.cli,
        ["version", "publish", str(page_dir), "--version", "1", "--text", "cut"],
    )
    status, body = fetch(f"{server}/")  # urllib follows the 302
    assert status == 200 and b"cq-options" in body
    # Vendored files serve; the log and directory paths don't.
    for path in ["/colloquy.js", "/theme.css", "/registry.json", "/widgets/cq-tabs.js"]:
        assert fetch(server + path)[0] == 200, path
    for path in ["/comments.jsonl", "/vendor/..", "/status.json", "/../secret"]:
        assert fetch(server + path)[0] == 404, path
    # A browser-posted comment lands stamped author=user, with a server-minted id
    # (client ids are dropped — a reused one would re-root an existing thread).
    status, body = fetch(
        f"{server}/api/event",
        data=json.dumps(
            {
                "kind": "comment",
                "id": "c9",
                "author": "claude",
                "agent": "Codex",
                "ts": "1900-01-01T00:00:00Z",
                "version": 1,
                "text": "hm",
            }
        ).encode(),
    )
    assert status == 200
    posted = interact.read_events(page_dir)[-1]
    assert posted["author"] == "user" and posted["id"] != "c9"
    assert "agent" not in posted
    assert posted["ts"] != "1900-01-01T00:00:00Z"
    status, body = fetch(f"{server}/api/state")
    state = json.loads(body)
    assert state["versions"] == [1]
    assert state["cursor"] == 0  # no reviewer event acknowledged yet
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
        {"kind": []},
        {"kind": "action", "action": "move"},  # no widget
        {"kind": "action", "widget": "", "action": "move", "detail": {}, "version": 1},
        {"kind": "action", "widget": "b", "action": "move", "version": 1},  # no detail
        {
            "kind": "action",
            "widget": "b",
            "action": "move",
            "detail": None,
            "version": 1,
        },
        {
            "kind": "action",
            "widget": "b",
            "action": "move",
            "detail": {},
            "version": "1",
        },
        {
            "kind": "action",
            "widget": "b",
            "action": "move",
            "detail": {},
            "version": True,
        },
        {"kind": "action", "widget": "b", "action": "move", "detail": {}, "version": 0},
        {"kind": "action", "widget": "b", "action": "move", "detail": {}, "version": 2},
        {"kind": "comment", "version": 1},  # no text: a blank thread nobody can read
        {"kind": "comment", "version": 1, "text": "x", "anchor": "intro"},
        {"kind": "comment", "version": 1, "text": "x", "anchor": {"quote": 7}},
        {"kind": "comment", "version": 1, "text": "x", "anchor": {}},
        {
            "kind": "comment",
            "version": 1,
            "text": "x",
            "anchor": {"quote": "x", "extra": "y"},
        },
        {"kind": "comment", "version": 1, "text": "x", "suggestion": "yes"},
        {
            "kind": "reply",
            "parent": posted["id"],
            "version": 1,
            "text": "hi",
            "suggestion": True,
        },
        {"kind": "reply", "parent": "nope", "version": 1, "text": "hi"},
        {"kind": "resolve", "parent": "nope"},
        ["not", "an", "object"],
    ]:
        status, body = fetch(f"{server}/api/event", data=json.dumps(bad).encode())
        assert status == 400, bad


def test_server_keeps_approval_separate_from_ending_comments(server, page_dir):
    publish(page_dir, version=1)

    status, body = fetch(
        f"{server}/api/event",
        data=json.dumps({"kind": "done", "version": 1, "text": "Looks good"}).encode(),
    )
    assert status == 400
    assert json.loads(body)["error"] == (
        "version 1 uses 'close' for ending its comments-only review"
    )

    signoff = PAGE.replace(
        "<title>t</title>",
        '<title>t</title>\n<meta name="cq-review" content="sign-off">',
    )
    (page_dir / "versions" / "v2.html").write_text(signoff)
    publish(page_dir, version=2)
    status, body = fetch(
        f"{server}/api/event",
        data=json.dumps({"kind": "close", "version": 2}).encode(),
    )
    assert status == 400
    assert json.loads(body)["error"] == "version 2 uses 'done' for sign-off"


def test_server_validates_an_action_against_its_version_and_widget(server, page_dir):
    registry = json.loads((page_dir / "registry.json").read_text())
    board = registry["cq-board"]["x-example"]
    v1 = page_dir / "versions" / "v1.html"
    v1.write_text(v1.read_text().replace("</section>", board + "\n</section>"))
    publish(page_dir, version=1)
    (page_dir / "versions" / "v2.html").write_text(PAGE)
    publish(page_dir, version=2)

    invalid = [
        (
            {
                "kind": "action",
                "version": 2,
                "widget": "feeder-board",
                "action": "move",
                "detail": {"card": "card-baffle", "to": "col-doing", "index": 0},
            },
            "unknown action widget",
        ),
        (
            {
                "kind": "action",
                "version": 1,
                "widget": "flow",
                "action": "move",
                "detail": {"card": "card-baffle", "to": "col-doing", "index": 0},
            },
            "<cq-diagram> does not declare action verb",
        ),
        (
            {
                "kind": "action",
                "version": 1,
                "widget": "feeder-board",
                "action": "move",
                "detail": {"card": "card-baffle", "to": "col-doing", "index": -1},
            },
            "detail is invalid",
        ),
    ]
    before = len(interact.read_events(page_dir))
    for event, message in invalid:
        status, body = fetch(f"{server}/api/event", data=json.dumps(event).encode())
        assert status == 400, event
        assert message in json.loads(body)["error"]
    assert len(interact.read_events(page_dir)) == before

    # The page may have advanced since the gesture, so resolve the sender from
    # the action's own published version rather than the newest document.
    valid = {
        "kind": "action",
        "version": 1,
        "widget": "feeder-board",
        "action": "move",
        "detail": {"card": "card-baffle", "to": "col-doing", "index": 0},
    }
    assert fetch(f"{server}/api/event", data=json.dumps(valid).encode())[0] == 200


def test_server_resolves_actions_from_claude_thread_widgets(server, page_dir):
    publish(page_dir)
    interact.append_event(
        page_dir,
        {
            "kind": "comment",
            "id": "c1",
            "author": "user",
            "version": 1,
            "text": "pick one",
        },
    )
    reply = CliRunner().invoke(
        interact.cli,
        [
            "review",
            "reply",
            str(page_dir),
            "--to",
            "c1",
            "--text",
            "Pick one:",
            "--markup",
            (
                '<cq-options id="thread-pick" choose>'
                '<cq-option id="thread-a"><strong>A</strong></cq-option>'
                "</cq-options>"
            ),
        ],
    )
    assert reply.exit_code == 0, reply.output
    interact.append_event(
        page_dir,
        {
            "kind": "reply",
            "author": "user",
            "parent": "c1",
            "version": 1,
            "text": '<cq-options id="quoted-pick" choose></cq-options>',
        },
    )

    choose = {
        "kind": "action",
        "version": 1,
        "action": "choose",
        "detail": {"options": ["thread-a"]},
    }
    status, _ = fetch(
        f"{server}/api/event",
        data=json.dumps({**choose, "widget": "thread-pick"}).encode(),
    )
    assert status == 200
    status, body = fetch(
        f"{server}/api/event",
        data=json.dumps({**choose, "widget": "quoted-pick"}).encode(),
    )
    assert status == 400
    assert "unknown action widget" in json.loads(body)["error"]


def test_server_rejects_an_action_from_a_widget_removed_by_revendoring(
    server, page_dir
):
    """An open old tab may outlive the custom layer that upgraded its widget."""
    shipped = json.loads((page_dir / "registry.json").read_text())
    overlay = page_dir.parent / ".colloquy"
    (overlay / "widgets").mkdir(parents=True)
    (overlay / "registry.json").write_text(
        json.dumps({"cq-local-draft": shipped["cq-draft"]})
    )
    (overlay / "widgets" / "cq-local-draft.js").write_text(
        "customElements.define('cq-local-draft', class extends HTMLElement {});"
    )
    assert (
        CliRunner().invoke(interact.cli, ["page", "init", str(page_dir)]).exit_code == 0
    )
    version = page_dir / "versions" / "v1.html"
    version.write_text(
        version.read_text().replace(
            "<h2>Plan</h2>",
            '<h2>Plan</h2><cq-local-draft id="local-draft"><pre>Words.</pre>'
            "</cq-local-draft>",
        )
    )
    noted = CliRunner().invoke(
        interact.cli,
        [
            "version",
            "publish",
            str(page_dir),
            "--version",
            "1",
            "--text",
            "custom widget",
        ],
    )
    assert noted.exit_code == 0, noted.output

    # The explicit re-vendor is allowed because no recorded action rests on this
    # tag yet. A browser that loaded it before the re-vendor can still send one.
    (overlay / "registry.json").unlink()
    (overlay / "widgets" / "cq-local-draft.js").unlink()
    assert (
        CliRunner().invoke(interact.cli, ["page", "init", str(page_dir)]).exit_code == 0
    )

    status, body = fetch(
        f"{server}/api/event",
        data=json.dumps(
            {
                "kind": "action",
                "version": 1,
                "widget": "local-draft",
                "action": "edit",
                "detail": {"text": "New words."},
            }
        ).encode(),
    )

    assert status == 400
    assert "no longer declares" in json.loads(body)["error"]


def test_concurrent_posts_never_tear_the_log(server, page_dir):
    CliRunner().invoke(
        interact.cli,
        ["version", "publish", str(page_dir), "--version", "1", "--text", "cut"],
    )

    def post(i):
        fetch(
            f"{server}/api/event",
            data=json.dumps(
                {"kind": "comment", "version": 1, "text": f"c{i} " + "x" * 500}
            ).encode(),
        )

    threads = [threading.Thread(target=post, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    events = [
        e for e in interact.read_events(page_dir) if e["kind"] == "comment"
    ]  # read_events raises on any torn non-final line
    assert {e["text"].split()[0] for e in events} == {f"c{i}" for i in range(20)}
    assert len({e["id"] for e in events}) == 20  # server-minted, all distinct


def test_a_reader_without_the_key_reads_and_writes_nothing(server, page_dir):
    """The page is served wherever the SSH session reached this machine, so the
    port is open to whatever else is on that network. Reading is half of it: the
    log outranks the document and takes appends from anyone who can POST."""
    CliRunner().invoke(
        interact.cli,
        ["version", "publish", str(page_dir), "--version", "1", "--text", "cut"],
    )

    assert fetch(f"{server}/versions/v1.html", token=None)[0] == 403
    assert fetch(f"{server}/api/state", token=None)[0] == 403
    assert fetch(f"{server}/", token=None)[0] == 403
    assert (
        fetch(
            f"{server}/api/event",
            data=json.dumps(
                {"kind": "comment", "version": 1, "text": "not mine"}
            ).encode(),
            token=None,
        )[0]
        == 403
    )
    assert fetch(f"{server}/versions/v1.html", token="not-the-key")[0] == 403

    assert [e for e in interact.read_events(page_dir) if e["kind"] == "comment"] == []


def test_the_key_arrives_in_the_query_and_stays_in_the_cookie(server, page_dir):
    """What makes the key invisible: it is in the link once, and the cookie carries
    it from there. The runtime's own fetches are relative and hold no query, and a
    reviewer who reloads the bare address is the same reviewer — so nothing has to
    thread it through the page, and `colloquy.js` never learns there is one."""
    CliRunner().invoke(
        interact.cli,
        ["version", "publish", str(page_dir), "--version", "1", "--text", "cut"],
    )
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    with opener.open(f"{server}/versions/v1.html?t={TOKEN}") as arrival:
        assert arrival.status == 200
    assert [c.value for c in jar] == [TOKEN]

    # No query this time: the runtime's own fetches never carry one.
    with opener.open(f"{server}/api/state") as polled:
        assert polled.status == 200


def test_a_page_is_reached_where_the_ssh_session_reached_this_machine(
    page_dir, monkeypatch
):
    """SSH_CONNECTION is "client_ip client_port server_ip server_port" — the third
    field is the address that carried the session, so it is a route the reviewer has
    already used rather than a hostname guessed from this end. The server binds that
    address alone: the open port faces only the network the session crossed."""
    monkeypatch.setenv("SSH_CONNECTION", "10.1.1.9 51234 10.20.30.40 22")
    access = interact.page_access(page_dir)
    assert (access["host"], access["bind"]) == ("10.20.30.40", "10.20.30.40")


def test_a_local_session_is_served_on_loopback(page_dir, monkeypatch):
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    access = interact.page_access(page_dir)
    assert (access["host"], access["bind"]) == ("127.0.0.1", "127.0.0.1")


def test_a_stated_host_binds_every_interface_and_keeps_the_key(page_dir, monkeypatch):
    """The name a reviewer routes to need not resolve to an address this machine
    could bind — a jump host or NAT is the case `--host` exists for — nor say
    which family they reach it by, so a stated name binds the wildcard of both
    families and goes in the URL as given. Re-stating keeps the key, and the URL
    a browser already holds stays keyed; a bare re-serve (`revive_server`) reads
    the stated record back unchanged."""
    monkeypatch.setenv("SSH_CONNECTION", "10.1.1.9 51234 10.20.30.40 22")
    derived = interact.page_access(page_dir)

    stated = interact.page_access(page_dir, host="devbox.corp.example")
    assert (stated["host"], stated["bind"]) == ("devbox.corp.example", "::")
    assert stated["token"] == derived["token"]
    assert interact.page_access(page_dir) == stated


def test_a_stated_host_is_a_hostname_or_ip_and_nothing_else(page_dir):
    """A scheme, a port, or a path pasted into --host would mint a URL no browser
    resolves, recorded permanently and handed to the one reader who can't report
    it — so the record's one door refuses what was never a hostname. An IPv6
    literal is a name a reviewer can route to, and it must not be mistaken for a
    host:port."""
    for junk in ("devbox:8443", "http://devbox", "devbox/page", "devbox one"):
        with pytest.raises(SystemExit):
            interact.page_access(page_dir, host=junk)
    assert not (page_dir / "access.json").exists()

    assert interact.page_access(page_dir, host="fd7a:115c:a1e0::1")["bind"] == "::"


def test_the_stated_host_wildcard_serves_both_families(page_dir):
    """The URL promises whatever the stated name resolves to, so the socket must
    answer both: "::" with V6ONLY off reaches IPv4 as ::ffff:... — an AF_INET
    0.0.0.0 would leave an IPv6-only reviewer a URL nothing listens on."""
    httpd = interact.DualStackHTTPServer(
        ("::", 0), interact.handler_for(page_dir, TOKEN)
    )
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    try:
        for loopback in ("127.0.0.1", "[::1]"):
            assert fetch(f"http://{loopback}:{port}/api/state")[0] == 200, loopback
    finally:
        httpd.shutdown()


def test_the_address_and_key_outlive_the_session_that_minted_them(
    page_dir, monkeypatch
):
    """`revive_server` restarts a dead server by re-running `server run`. The
    reviewer's browser has been polling one URL since it died, so a fresh address or
    key there would leave the page it reopens talking to nothing."""
    monkeypatch.setenv("SSH_CONNECTION", "10.1.1.9 51234 10.20.30.40 22")
    minted = interact.page_access(page_dir)

    monkeypatch.setenv("SSH_CONNECTION", "10.1.1.9 51235 172.16.0.1 22")
    assert interact.page_access(page_dir) == minted


def test_two_pages_on_one_machine_get_their_own_cookie(page_dir, tmp_path):
    """Cookies are scoped by host and ignore the port, so two pages share a jar —
    under one name the second page served would sign the reviewer out of the first."""
    other = tmp_path / "other-page"
    other.mkdir()
    assert interact.access_cookie(page_dir) != interact.access_cookie(other)


def test_a_bare_ipv6_address_is_bracketed_in_the_url():
    """A v6 address is colons all the way down, and the authority separates its port
    with one too."""
    assert interact.page_url({"host": "fd00::1", "token": "k"}, 41999) == (
        "http://[fd00::1]:41999/?t=k"
    )
    assert interact.page_url({"host": "10.20.30.40", "token": "k"}, 41999) == (
        "http://10.20.30.40:41999/?t=k"
    )


def test_wait_prints_unacknowledged_user_events_and_flips_status(page_dir, capsys):
    # A live server.json (our own pid) satisfies wait's liveness probe.
    interact.write_json(
        page_dir / "server.json", {"port": 1, "pid": os.getpid(), "url": "x"}
    )
    interact.cmd_status(page_dir, "waiting", "")
    interact.append_event(
        page_dir, {"kind": "comment", "id": "c1", "author": "user", "text": "hi"}
    )
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
    shown = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]
    assert [e["kind"] for e in shown] == ["comment", "action"]
    assert shown[1]["detail"]["to"] == "y"
    # Printing is not acknowledgement: a detached Codex command can finish without
    # putting its output in the model's context, so wait leaves both events pending.
    assert interact.read_json(page_dir / "cursor.json") is None
    assert page_state(page_dir)["pending"] == 2

    # An event posted between wait and acknowledgement is beyond the highest sequence
    # the model saw. Acknowledging that visible batch therefore leaves the newcomer.
    interact.append_event(
        page_dir, {"kind": "comment", "id": "c2", "author": "user", "text": "later"}
    )
    interact.cmd_ack(page_dir, 2)
    interact.cmd_ack(page_dir, 2)  # retries are harmless
    assert interact.read_json(page_dir / "cursor.json")["seq"] == 2
    assert page_state(page_dir)["pending"] == 1

    assert interact.cmd_wait(page_dir) == 0
    assert [
        json.loads(line)["id"] for line in capsys.readouterr().out.splitlines()
    ] == ["c2"]
    interact.cmd_ack(page_dir, 3)
    assert page_state(page_dir)["pending"] == 0
    # The wait status is marked a handoff, which dates the claim: the agent's own
    # `review state` clears the mark, so the mark surviving is a pickup that never landed.
    status = interact.read_json(page_dir / "status.json")
    assert (status["state"], status["handoff"]) == ("working", True)
    interact.cmd_status(page_dir, "working", "revising the plan")
    assert "handoff" not in interact.read_json(page_dir / "status.json")


def test_ack_checks_its_target_and_advances_monotonically(page_dir):
    interact.append_event(
        page_dir,
        {"kind": "note", "author": "claude", "version": 1, "text": "published"},
    )
    interact.append_event(
        page_dir, {"kind": "comment", "id": "c1", "author": "user", "text": "hi"}
    )
    interact.append_event(
        page_dir, {"kind": "comment", "id": "c2", "author": "user", "text": "later"}
    )
    runner = CliRunner()

    missing = runner.invoke(interact.cli, ["review", "ack", str(page_dir), "4"])
    assert missing.exit_code == 1
    assert "event 4 does not exist" in missing.output

    agent_event = runner.invoke(interact.cli, ["review", "ack", str(page_dir), "1"])
    assert agent_event.exit_code == 1
    assert "event 1 is not a reviewer event" in agent_event.output

    first = runner.invoke(interact.cli, ["review", "ack", str(page_dir), "3"])
    retry = runner.invoke(interact.cli, ["review", "ack", str(page_dir), "3"])
    older = runner.invoke(interact.cli, ["review", "ack", str(page_dir), "2"])
    assert first.exit_code == retry.exit_code == older.exit_code == 0
    assert interact.read_json(page_dir / "cursor.json") == {"seq": 3}


def test_wait_preserves_a_working_status_on_mid_work_output(page_dir, capsys):
    interact.write_json(
        page_dir / "server.json", {"port": 1, "pid": os.getpid(), "url": "x"}
    )
    interact.cmd_status(page_dir, "working", "running the browser suite")
    status_path = page_dir / "status.json"
    before = status_path.read_bytes()
    interact.append_event(
        page_dir,
        {"kind": "comment", "id": "c1", "author": "user", "text": "one more thing"},
    )

    assert interact.cmd_wait(page_dir) == 0
    assert [
        json.loads(line)["id"] for line in capsys.readouterr().out.splitlines()
    ] == ["c1"]
    assert status_path.read_bytes() == before


def test_wait_restarts_a_server_that_died_under_it(page_dir, capsys):
    """A page whose server died is offline in the reviewer's browser and nowhere
    else — so `review wait`, the one thing positioned to notice, brings it back
    rather than exiting and leaving the discovery to the reviewer."""

    def comment_once_served():
        for _ in range(100):
            time.sleep(0.1)
            if interact.running_server(page_dir):
                interact.append_event(
                    page_dir, {"kind": "comment", "author": "user", "text": "hi"}
                )
                return

    threading.Thread(target=comment_once_served, daemon=True).start()
    try:
        assert interact.cmd_wait(page_dir) == 0  # no server.json at all when it starts
        info = interact.running_server(page_dir)
        # The revived server has to answer on the URL it published, key included:
        # the reviewer's browser has been polling that address since it died.
        assert info
        state = urllib.parse.urlsplit(info["url"])
        assert (
            urllib.request.urlopen(state._replace(path="/api/state").geturl()).status
            == 200
        )
        assert "server had died; restarted" in capsys.readouterr().err
    finally:
        interact.cmd_stop(page_dir)


def test_wait_leaves_a_closed_review_down(page_dir):
    """SessionEnd idles the page and stops its server, so a watcher still winding
    down must not put it straight back up."""
    interact.cmd_status(page_dir, "idle", "the session that opened this page has ended")
    assert interact.cmd_wait(page_dir) == 2
    assert interact.running_server(page_dir) is None


def test_wait_holds_a_page_nobody_has_opened(page_dir, capsys):
    """Nothing the server can observe tells a page the reviewer hasn't opened yet
    from one they can't reach, so the wait doesn't guess between them: over a page
    no request has ever touched it holds for the reviewer exactly as it would for
    one reading, and reports nothing of its own."""
    interact.write_json(
        page_dir / "server.json", {"port": 1, "pid": os.getpid(), "url": "x"}
    )
    interact.cmd_status(page_dir, "waiting", "")
    threading.Timer(
        0.2,
        lambda: interact.append_event(
            page_dir, {"kind": "comment", "id": "c1", "author": "user", "text": "hi"}
        ),
    ).start()

    assert interact.cmd_wait(page_dir) == 0
    printed = capsys.readouterr()
    assert [json.loads(line)["id"] for line in printed.out.splitlines()] == ["c1"]
    assert printed.err == ""


@pytest.fixture
def claimed(page_dir, monkeypatch):
    """A page claimed by session s1, the way Claude Code's environment claims one:
    it puts the session id and its pid into every Bash tool call."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s1")
    monkeypatch.setenv("CLAUDE_PID", str(os.getpid()))
    interact.claim_page(page_dir)
    return page_dir


@pytest.fixture
def codex_claimed_page(tmp_path, request):
    page = tmp_path / "codex-page"
    launcher = PLUGIN_ROOT / "bin" / "colloquy"
    env = os.environ | {"CODEX_THREAD_ID": "codex-thread"}

    # Uncaptured, so `check=True` reports something: a CalledProcessError over
    # captured streams names the command and the exit status and takes colloquy's
    # own message down with it, and nothing here reads either stream. Left to
    # pytest, the message is in the failure it belongs to.
    subprocess.run([launcher, "page", "init", page], env=env, check=True)
    server = subprocess.Popen(
        [launcher, "server", "run", page],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    def stop():
        subprocess.run([launcher, "server", "stop", page], env=env, check=True)
        server.wait(timeout=5)

    request.addfinalizer(stop)
    assert server.stdout.readline().startswith("http://127.0.0.1:")
    return page


def test_codex_launcher_claims_the_page_for_its_thread(codex_claimed_page):
    session = interact.read_json(codex_claimed_page / "session.json")
    assert session["id"] == "codex-thread"
    assert session["pid"] == os.getpid()
    assert session["agent"] == "Codex"
    assert page_state(codex_claimed_page)["agent"] == "Codex"


def test_stop_hook_keeps_codex_inside_the_exact_wait_session(
    codex_claimed_page, capsys
):
    page = codex_claimed_page
    interact.cmd_status(page, "waiting", "")
    interact.write_json(page / "heartbeat.json", {"t": time.time()})

    # A fresh heartbeat means Claude may end its turn, but Codex must keep this one
    # active and poll the unified-exec session whose output can enter this context.
    interact.cmd_hook({"hook_event_name": "Stop", "session_id": "codex-thread"})
    reason = json.loads(capsys.readouterr().out)["reason"]
    assert "poll the existing" in reason and "write_stdin" in reason

    # The existing one-shot escape still prevents a hook recursion.
    interact.cmd_hook(
        {
            "hook_event_name": "Stop",
            "session_id": "codex-thread",
            "stop_hook_active": True,
        }
    )
    assert capsys.readouterr().out == ""

    # With no waiter, the remedy names both halves of the Codex loop.
    (page / "heartbeat.json").unlink()
    interact.cmd_hook({"hook_event_name": "Stop", "session_id": "codex-thread"})
    reason = json.loads(capsys.readouterr().out)["reason"]
    assert "Start `colloquy review wait`" in reason
    assert "unified exec" in reason and "write_stdin" in reason

    # Pending output still has to cross context and be acknowledged before handling.
    interact.append_event(page, {"kind": "comment", "author": "user", "text": "hi"})
    interact.write_json(page / "heartbeat.json", {"t": time.time()})
    interact.cmd_hook({"hook_event_name": "Stop", "session_id": "codex-thread"})
    reason = json.loads(capsys.readouterr().out)["reason"]
    assert "review ack" in reason and "address every one" in reason
    assert interact.ACK_BATCH_INSTRUCTION in reason

    interact.cmd_ack(page, 1)
    interact.cmd_status(page, "idle", "")
    interact.cmd_hook({"hook_event_name": "Stop", "session_id": "codex-thread"})
    assert capsys.readouterr().out == ""


def test_stop_hook_blocks_a_turn_that_leaves_a_page_unwatched(claimed, capsys):
    """Between turns a page is either watched or idle. The failure this prevents:
    a `review wait` exits, its notification is buried behind the next thing the
    user types, and the page keeps saying "Claude is working" over nobody."""
    interact.cmd_status(claimed, "waiting", "")
    interact.cmd_hook({"hook_event_name": "Stop", "session_id": "s1"})
    answer = json.loads(capsys.readouterr().out)
    assert answer["decision"] == "block"
    assert "no watcher" in answer["reason"] and str(claimed) in answer["reason"]

    # Blocking twice in a row is how a Stop hook loops, so a block already in
    # flight stands down.
    interact.cmd_hook(
        {"hook_event_name": "Stop", "session_id": "s1", "stop_hook_active": True}
    )
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
    interact.write_json(
        claimed / "session.json", {"id": "s2", "pid": os.getpid(), "ts": "t"}
    )
    interact.cmd_hook({"hook_event_name": "Stop", "session_id": "s1"})
    assert capsys.readouterr().out == ""


def test_prompt_hook_surfaces_comments_claude_never_picked_up(claimed, capsys):
    interact.cmd_status(claimed, "working", "revising")
    interact.append_event(claimed, {"kind": "comment", "author": "user", "text": "hi"})
    assert page_state(claimed)["pending"] == 1
    interact.cmd_hook({"hook_event_name": "UserPromptSubmit", "session_id": "s1"})
    context = json.loads(capsys.readouterr().out)["hookSpecificOutput"][
        "additionalContext"
    ]
    assert "1 user event you haven't picked up" in context

    # Not while a watcher is live: it prints them itself, and sending Claude to start a
    # second `review wait` would print every unacknowledged event twice.
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
    assert (
        CliRunner().invoke(interact.cli, ["page", "catalog", str(page_dir)]).exit_code
        == 0
    )
    assert interact.session_pages("s7") == []
    # `page init` left the page "working", which is the state the guard blocks on —
    # but only for a page some session answers for, and none does.
    interact.cmd_hook({"hook_event_name": "Stop", "session_id": "s7"})
    assert capsys.readouterr().out == ""

    interact.append_event(page_dir, {"kind": "comment", "author": "user", "text": "hi"})
    assert (
        CliRunner().invoke(interact.cli, ["review", "wait", str(page_dir)]).exit_code
        == 0
    )
    assert interact.session_pages("s7") == [page_dir.resolve()]

    # If wait's process finished without its output entering model context, the event
    # remains recoverable and the next hook names it rather than calling it delivered.
    interact.cmd_hook({"hook_event_name": "Stop", "session_id": "s7"})
    assert "1 user event" in json.loads(capsys.readouterr().out)["reason"]

    interact.cmd_ack(page_dir, 1)
    interact.cmd_hook({"hook_event_name": "Stop", "session_id": "s7"})
    assert "no watcher" in json.loads(capsys.readouterr().out)["reason"]


def test_review_guard_agrees_with_interact_on_state_home(tmp_path, monkeypatch):
    """The plain-Python hook inlines the uv script's XDG state resolution."""

    def load(path):
        spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    for env in (
        {},
        {"XDG_STATE_HOME": str(tmp_path / "st")},
    ):
        monkeypatch.delenv("XDG_STATE_HOME", raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        guard = load(PLUGIN_ROOT / "hooks" / "scripts" / "review-guard.py")
        assert guard.SESSIONS == interact.state_home() / "sessions"


def test_idle_cannot_close_a_review_over_events_nobody_read(claimed, capsys):
    """`review state PAGE idle` is the way out of the guard's other case, so it
    reads as the way out of this one too. The events are the reviewer's: a page
    idled over them ends the review on someone still waiting for an answer, and
    from the browser that looks exactly like a review that ran its course."""
    interact.append_event(claimed, {"kind": "comment", "author": "user", "text": "hi"})
    refused = CliRunner().invoke(
        interact.cli, ["review", "state", str(claimed), "idle"]
    )
    assert refused.exit_code == 1
    assert "1 user event nobody has picked up" in refused.output
    assert interact.ACK_BATCH_INSTRUCTION in refused.output
    assert interact.read_json(claimed / "status.json")["state"] != "idle"

    # `review wait` returns at once, and acknowledgement records that its output reached
    # model context; only then can idle close the review.
    assert (
        CliRunner().invoke(interact.cli, ["review", "wait", str(claimed)]).exit_code
        == 0
    )
    assert (
        CliRunner().invoke(interact.cli, ["review", "ack", str(claimed), "1"]).exit_code
        == 0
    )
    assert (
        CliRunner()
        .invoke(interact.cli, ["review", "state", str(claimed), "idle"])
        .exit_code
        == 0
    )
    interact.cmd_hook({"hook_event_name": "Stop", "session_id": "s1"})
    assert capsys.readouterr().out == ""


def test_session_end_idles_the_page_and_stops_its_server(claimed):
    assert interact.revive_server(claimed)  # a real detached server to clean up
    interact.cmd_status(claimed, "waiting", "")
    interact.cmd_hook({"hook_event_name": "SessionEnd", "session_id": "s1"})
    assert interact.read_json(claimed / "status.json")["state"] == "idle"
    assert interact.running_server(claimed) is None
    assert interact.session_pages("s1") == []


def start_managed_server(page_dir, session_id, session_pid):
    env = os.environ | {
        "COLLOQUY_SESSION_ID": session_id,
        "COLLOQUY_SESSION_PID": str(session_pid),
        "COLLOQUY_AGENT": "Codex",
    }
    process = subprocess.Popen(
        [
            sys.executable,
            str(interact.__file__),
            "server",
            "run",
            str(page_dir),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout.readline().startswith("http://127.0.0.1:")
    return process


def test_a_server_exits_when_its_session_is_hard_killed(page_dir):
    owner = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    server = start_managed_server(page_dir, "abandoned", owner.pid)
    owner.terminate()
    owner.wait(timeout=5)

    server.wait(timeout=5)
    assert server.returncode == 0, server.stderr.read()
    assert not (page_dir / "server.json").exists()


def test_a_live_session_can_take_over_an_existing_server(page_dir):
    first = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    second = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    server = start_managed_server(page_dir, "first", first.pid)
    try:
        interact.write_json(
            page_dir / "session.json",
            {"id": "second", "pid": second.pid, "agent": "Codex", "ts": "t"},
        )
        first.terminate()
        first.wait(timeout=5)
        assert server.poll() is None

        second.terminate()
        second.wait(timeout=5)
        server.wait(timeout=5)
        assert server.returncode == 0, server.stderr.read()
    finally:
        for process in (first, second, server):
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)


def test_a_sessionless_server_ignores_a_stale_claim_and_requires_explicit_stop(
    page_dir,
):
    dead = subprocess.Popen([sys.executable, "-c", ""])
    dead.wait(timeout=5)
    interact.write_json(
        page_dir / "session.json",
        {"id": "old-session", "pid": dead.pid, "agent": "Codex", "ts": "t"},
    )
    env = os.environ.copy()
    for name in (
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_PID",
        "COLLOQUY_SESSION_ID",
        "COLLOQUY_SESSION_PID",
        "COLLOQUY_AGENT",
    ):
        env.pop(name, None)
    server = subprocess.Popen(
        [
            sys.executable,
            str(interact.__file__),
            "server",
            "run",
            str(page_dir),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert server.stdout.readline().startswith("http://127.0.0.1:")
    try:
        # The only held window in the suite, because it is the only assertion with nothing
        # to consume: a watcher that never starts states nothing, and the server going on
        # living is not an event to wait for (tests/CLAUDE.md, "A wait consumes a fact the
        # system states"). So the window is the grace a watcher would have acted after,
        # plus room to act — long enough that the bug, had it been here, would have shown.
        time.sleep(interact.ORPHAN_GRACE_SECS + 0.5)
        assert server.poll() is None, (
            "a manual server inherited the stale session claim"
        )
        assert "stopped server" in interact.cmd_stop(page_dir)
        server.wait(timeout=5)
    finally:
        if server.poll() is None:
            server.terminate()
            server.wait(timeout=5)


def test_state_reports_whether_the_owning_session_still_exists(claimed):
    """The banner's one hard fact: a status.json claim outlives its session, the
    owning pid doesn't."""
    assert page_state(claimed)["session_alive"] is True
    dead = subprocess.Popen([sys.executable, "-c", ""])
    dead.wait()
    interact.write_json(
        claimed / "session.json", {"id": "s1", "pid": dead.pid, "ts": "t"}
    )
    assert page_state(claimed)["session_alive"] is False


def test_versions_publish_only_once_noted(page_dir):
    assert live_versions(page_dir) == []
    assert page_state(page_dir)["versions"] == []
    result = CliRunner().invoke(
        interact.cli,
        ["version", "publish", str(page_dir), "--version", "1", "--text", "first cut"],
    )
    assert result.exit_code == 0, result.output
    assert live_versions(page_dir) == [1]
    # The next version stays unpublished until its own note lands.
    (page_dir / "versions" / "v2.html").write_text(PAGE)
    assert live_versions(page_dir) == [1]


def test_versions_run_in_number_order_past_v9(page_dir):
    """Everything downstream reads "the latest version" off the end of this list —
    what `version publish` exposes, what the server redirects to, what
    `version check` diffs the new version with. Sorted as names, v10 would land
    before v2 and every one of those would quietly answer with the wrong version."""
    for n in range(2, 12):
        (page_dir / "versions" / f"v{n}.html").write_text(PAGE)
    assert interact.list_versions(page_dir) == list(range(1, 12))
    for n in range(1, 12):
        result = CliRunner().invoke(
            interact.cli,
            [
                "version",
                "publish",
                str(page_dir),
                "--version",
                str(n),
                "--text",
                f"cut {n}",
            ],
        )
        assert result.exit_code == 0, result.output
    assert live_versions(page_dir) == list(range(1, 12))


def test_version_filenames_are_canonical(page_dir, server):
    """Only an ASCII, unpadded file can identify a positive version."""
    (page_dir / "versions" / "v01.html").write_text("<h1>shadow</h1>")
    (page_dir / "versions" / "v1٢.html").write_text("<h1>Unicode alias</h1>")
    (page_dir / "versions" / "v2.html").mkdir()
    assert interact.list_versions(page_dir) == [1]
    assert check(page_dir, version=1).exit_code == 0
    assert fetch(f"{server}/versions/v01.html")[0] == 404


def test_choose_requires_an_id(page_dir):
    # Actions name their widget by id, so an interactive group can't go without one.
    registry = interact.load_registry(page_dir)
    errs = fragment_errors(
        '<cq-options choose><cq-option id="o1"><strong>A</strong></cq-option></cq-options>',
        registry,
    )
    assert errs and "'id' is a dependency of 'choose'" in " ".join(errs)


def test_specimen_admits_interactive_widgets(page_dir):
    # The registry marks a specimen's content quoted; the runtime leaves the
    # interactive widgets inside unwired. Validation is unchanged by the
    # wrapper: nesting rules (cq-option under cq-options) still hold.
    registry = interact.load_registry(page_dir)
    errs = fragment_errors(
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
    whole reason it's expressible: `version check` forbids dropping an id, and
    the alternatives behind the disclosure keep both their ids and the anchors
    on them. A group can't be settled without an id either; the reader's
    open/closed state is remembered against it."""
    registry = interact.load_registry(page_dir)
    assert "'id' is a dependency of 'settled'" in " ".join(
        fragment_errors(
            '<cq-options settled><cq-option id="o1"><strong>A</strong></cq-option></cq-options>',
            registry,
        )
    )

    group = '<cq-options id="pick" choose{}><cq-option id="opt-a"{}><strong>A</strong></cq-option>'
    group += '<cq-option id="opt-b"><strong>B</strong></cq-option></cq-options>'
    (page_dir / "versions" / "v1.html").write_text(
        PAGE.replace("</main>", group.format("", "") + "</main>")
    )
    publish(page_dir)
    (page_dir / "versions" / "v2.html").write_text(
        PAGE.replace("</main>", group.format(" settled", " chosen") + "</main>")
    )
    assert interact.cmd_check(page_dir, 2) == 0

    # Deleting the alternatives instead is what check is there to stop.
    (page_dir / "versions" / "v2.html").write_text(PAGE)
    assert interact.cmd_check(page_dir, 2) == 1


def test_registry_examples_validate(page_dir):
    registry = interact.load_registry(page_dir)
    assert any(
        tag.startswith("cq-") and "x-example" in entry
        for tag, entry in registry.items()
    )
    assert (
        interact.validate_registry_examples(registry, "vendored registry") is registry
    )


def test_registry_example_ids_are_independent_between_entries(page_dir):
    registry = interact.load_registry(page_dir)
    registry["cq-diff"]["x-example"] = (
        '<cq-diff id="shared"><pre>one changed line</pre></cq-diff>'
    )
    registry["cq-tree"]["x-example"] = (
        '<cq-tree id="shared"><pre>one/file.py</pre></cq-tree>'
    )

    assert (
        interact.validate_registry_examples(registry, "independent examples")
        is registry
    )


def test_every_path_a_diff_resolves_names_a_language_the_bundle_carries(page_dir):
    """The language vocabulary has two halves and they have to agree. `names` is the half
    an author writes and the half scripts/vendor-highlight.sh builds the tokenizer bundle
    from; `paths` is what a filename means, which is how a diff colours a file nobody
    declared a language for. A path resolving outside `names` would resolve to a language
    the vendored bundle doesn't carry, and the whole hunk would fall back to plain text
    with a console error — visible only on a page that happens to diff that extension."""
    reg = json.loads((page_dir / "registry.json").read_text())
    names = set(reg["$languages"]["names"])
    paths = reg["$languages"]["paths"]
    assert (
        paths
    )  # a table with nothing in it would pass the check below and colour nothing
    assert set(paths.values()) <= names, (
        f"no bundle for {sorted(set(paths.values()) - names)}"
    )


def test_examples_pass_check(tmp_path, monkeypatch):
    """Every gallery page in examples/ lints clean against the shipped layer."""
    monkeypatch.chdir(tmp_path)  # keep the project layer out of the overlay
    examples = sorted((Path(__file__).parent.parent / "examples").glob("*.html"))
    assert examples
    for example in examples:
        d = tmp_path / example.stem
        CliRunner().invoke(interact.cli, ["page", "init", str(d)])
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
    result = CliRunner().invoke(interact.cli, ["page", "catalog", str(page_dir)])
    assert result.exit_code == 0
    assert "cq-options" in result.output
    assert "x-example" in result.output
    assert ".callout" in result.output
    assert "$idioms" not in result.output  # sections are split out, not dumped raw


def test_reply_validates_widget_markup(page_dir):
    interact.append_event(
        page_dir, {"kind": "comment", "id": "c1", "author": "user", "text": "hm"}
    )
    reply = lambda markup: CliRunner().invoke(
        interact.cli,
        [
            "review",
            "reply",
            str(page_dir),
            "--to",
            "c1",
            "--text",
            "See:",
            "--markup",
            markup,
        ],
    )
    bad = reply('<cq-diagram id="f"><pre>graph LR</pre><b>x</b></cq-diagram>')
    assert bad.exit_code != 0
    assert "its body is one <pre> holding the text" in bad.output
    duplicate = reply(
        '<cq-diagram id="browser-id" id="file-id"><pre>graph LR\nA --> B</pre></cq-diagram>'
    )
    assert duplicate.exit_code != 0
    assert "duplicate attribute" in duplicate.output
    # Prose belongs in --text, where it renders as Markdown; a markup field
    # holding none is a wrong turn, not an empty widget list.
    prose = reply("just words")
    assert prose.exit_code != 0
    assert "carries no widget" in prose.output
    good = reply('<cq-diagram id="f"><pre>\ngraph LR\n  A --> B\n</pre></cq-diagram>')
    assert good.exit_code == 0, good.output
    event = interact.read_events(page_dir)[-1]
    assert event["kind"] == "reply"
    assert event["author"] == "claude"
    assert event["text"] == "See:"
    assert event["markup"].startswith("<cq-diagram")


def test_widget_ids_are_one_universe_across_page_and_replies(page_dir):
    """The runtime resolves actions document-wide by id, so a reply widget must not
    reuse a page id — and a later version must not take a reply's."""
    interact.append_event(
        page_dir, {"kind": "comment", "id": "c1", "author": "user", "text": "hm"}
    )
    reply = lambda markup: CliRunner().invoke(
        interact.cli,
        [
            "review",
            "reply",
            str(page_dir),
            "--to",
            "c1",
            "--text",
            "Pick:",
            "--markup",
            markup,
        ],
    )
    # `flow` is the page's cq-diagram id (PAGE fixture) — refused.
    clash = reply(
        '<cq-options id="flow" choose><cq-option id="o1"><strong>A</strong></cq-option></cq-options>'
    )
    assert clash.exit_code != 0 and "flow" in clash.output
    fresh = reply(
        '<cq-options id="q1" choose><cq-option id="q1-a"><strong>A</strong></cq-option></cq-options>'
    )
    assert fresh.exit_code == 0, fresh.output
    # A second reply can't reuse the first reply's ids either, nor its own within itself.
    again = reply(
        '<cq-options id="q1" choose><cq-option id="q1-b"><strong>B</strong></cq-option></cq-options>'
    )
    assert again.exit_code != 0 and "q1" in again.output
    selfdup = reply(
        '<cq-options id="q2" choose><cq-option id="q2"><strong>B</strong></cq-option></cq-options>'
    )
    assert selfdup.exit_code != 0 and "within itself" in selfdup.output
    # Text claims no ids however it quotes a tag — only the `markup` field does, and
    # a reviewer's message never carries one (the log is append-only; a false claim
    # would deadlock every future version).
    interact.append_event(
        page_dir,
        {
            "kind": "reply",
            "author": "user",
            "parent": "c1",
            "text": 'why not <cq-diagram id="quoted"> here?',
        },
    )
    ok = reply(
        '<cq-options id="quoted" choose><cq-option id="quoted-a"><strong>A</strong></cq-option></cq-options>'
    )
    assert ok.exit_code == 0, ok.output
    # And a new version taking the reply's id fails check.
    (page_dir / "versions" / "v2.html").write_text(
        PAGE.replace('<section id="plan">', '<section id="plan"><p id="q1">stolen</p>')
    )
    result = check(page_dir, version=2)
    assert result.exit_code == 1
    assert (
        "taken by widget markup in a reply" in result.output and "q1" in result.output
    )


def test_the_runtimes_cq_id_namespace_is_off_limits(page_dir):
    """colloquy.js coins document ids under cq- for its own chrome — cq-composer-quote —
    and points ARIA at them. An authored id there would aim those references at the page
    instead, silently. One rule over both places an id can be authored: a version, and
    the widget markup in Claude's reply."""
    (page_dir / "versions" / "v2.html").write_text(
        PAGE.replace(
            '<section id="plan">', '<section id="plan"><p id="cq-msg-7">mine</p>'
        )
    )
    result = check(page_dir, version=2)
    assert result.exit_code == 1
    assert "cq- namespace" in result.output and "cq-msg-7" in result.output

    interact.append_event(
        page_dir, {"kind": "comment", "id": "c1", "author": "user", "text": "hm"}
    )
    reply = CliRunner().invoke(
        interact.cli,
        [
            "review",
            "reply",
            str(page_dir),
            "--to",
            "c1",
            "--text",
            "Pick:",
            "--markup",
            '<cq-options id="cq-pick" choose><cq-option id="o1"><strong>A</strong></cq-option></cq-options>',
        ],
    )
    assert reply.exit_code != 0
    assert "cq- namespace" in reply.output and "cq-pick" in reply.output


# ---------- messages: text is Markdown for the browser, markup is the gate's ----------


def test_the_wire_ships_a_message_as_logged(page_dir):
    """The wire adds nothing to the log: text is Markdown the page's vendored runtime
    renders (test_render holds that side), markup is the fragment the CLI gate
    validated, and the only vocabulary a page's frozen layer has to keep speaking is
    the log's own, which $events stamps."""
    interact.append_event(
        page_dir,
        {
            "kind": "comment",
            "id": "c1",
            "author": "user",
            "text": "two things:\n\n- one\n- **two**",
        },
    )
    result = CliRunner().invoke(
        interact.cli,
        [
            "review",
            "reply",
            str(page_dir),
            "--to",
            "c1",
            "--text",
            "Fixed in `poll()`.",
            "--markup",
            '<cq-diagram id="fix"><pre>\ngraph LR\n  A --> B\n</pre></cq-diagram>',
        ],
    )
    assert result.exit_code == 0, result.output
    wire = {e["kind"]: e for e in page_state(page_dir)["events"]}
    assert wire["comment"]["text"] == "two things:\n\n- one\n- **two**"
    assert "html" not in wire["comment"] and "html" not in wire["reply"]
    assert wire["reply"]["markup"].startswith("<cq-diagram")


def test_markup_enters_only_through_the_cli_gate(server, page_dir):
    """The browser door refuses the field rather than silently dropping it: everything
    the log holds under `markup` has been through `check_markup`, which is what lets
    thread_widget_ids and the panel index it unasked."""
    publish(page_dir, version=1)
    before = interact.read_events(page_dir)
    status, body = fetch(
        f"{server}/api/event",
        data=json.dumps(
            {
                "kind": "comment",
                "version": 1,
                "text": "hi",
                "markup": '<cq-diagram id="m"><pre>graph LR\n  A --> B</pre></cq-diagram>',
            }
        ).encode(),
    )
    assert status == 400
    assert "markup" in json.loads(body)["error"]
    assert interact.read_events(page_dir) == before


def test_export_prints_threads_and_versions(page_dir):
    # The heading is the page's title as a reader sees it, entities and all.
    (page_dir / "versions" / "v1.html").write_text(
        PAGE.replace("<title>t</title>", "<title>Cutoff &amp; backfill</title>")
    )
    CliRunner().invoke(
        interact.cli,
        ["version", "publish", str(page_dir), "--version", "1", "--text", "first cut"],
    )
    interact.append_event(
        page_dir,
        {
            "kind": "comment",
            "id": "c1",
            "author": "user",
            "anchor": {"quote": "flip reads"},
            "text": "why?",
        },
    )
    interact.append_event(
        page_dir,
        {
            "kind": "reply",
            "id": "r1",
            "author": "claude",
            "agent": "Claude",
            "parent": "c1",
            "text": "reversibility",
            "markup": '<cq-diagram id="why"><pre>graph LR\n  A --> B</pre></cq-diagram>',
        },
    )
    interact.append_event(
        page_dir, {"kind": "resolve", "id": "x1", "author": "user", "parent": "r1"}
    )
    interact.append_event(
        page_dir,
        {
            "kind": "comment",
            "id": "c2",
            "author": "user",
            "anchor": {"section": "flow"},
            "text": "arrow?",
        },
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
    result = CliRunner().invoke(interact.cli, ["review", "transcript", str(page_dir)])
    assert result.exit_code == 0, result.output
    assert "## Review: Cutoff & backfill" in result.output
    assert "- v1: first cut" in result.output
    # The reviewer's direct edits are review outcomes, not just events.
    assert "### Edits" in result.output
    assert "- `b`: move card=card-x to=col-done index=0 (on v1)" in result.output
    assert "> “flip reads”  — resolved" in result.output
    assert "- **User**: why?" in result.output
    # The widget rides its message into the transcript, indented under the words.
    assert "- **Claude**: reversibility\n  <cq-diagram" in result.output
    assert "> § flow" in result.output  # element-anchored comments keep their target


def test_markup_needs_the_registry_and_text_does_not(page_dir):
    """Text renders with every raw tag escaped, so a plain reply has nothing to
    validate and posts without the registry; markup is checked against it, so without
    one the gate refuses rather than guessing."""
    (page_dir / "registry.json").unlink()
    interact.append_event(
        page_dir, {"kind": "comment", "id": "c1", "author": "user", "text": "hm"}
    )
    plain = CliRunner().invoke(
        interact.cli,
        [
            "review",
            "reply",
            str(page_dir),
            "--to",
            "c1",
            "--text",
            "plain answer, x < y",
        ],
    )
    assert plain.exit_code == 0, plain.output
    with_markup = CliRunner().invoke(
        interact.cli,
        [
            "review",
            "reply",
            str(page_dir),
            "--to",
            "c1",
            "--text",
            "See:",
            "--markup",
            '<cq-diagram id="f"><pre>graph LR\n  A --> B</pre></cq-diagram>',
        ],
    )
    assert with_markup.exit_code != 0
    assert "no registry.json" in with_markup.output


def test_comment_requires_the_registry_its_runtime_reads(page_dir):
    published(page_dir)
    (page_dir / "registry.json").unlink()
    before = interact.read_events(page_dir)
    result = comment(page_dir, "--quote", "Ship dark", "--text", "Still posts")
    assert result.exit_code != 0
    assert (
        "no registry.json" in result.output
        and "run `colloquy page init`" in result.output
    )
    assert interact.read_events(page_dir) == before


def test_note_refuses_a_version_that_fails_check(page_dir):
    (page_dir / "versions" / "v1.html").write_text(PAGE.replace("</section>", ""))
    result = CliRunner().invoke(
        interact.cli,
        ["version", "publish", str(page_dir), "--version", "1", "--text", "broken"],
    )
    assert result.exit_code != 0
    assert "refusing to publish" in result.output
    assert live_versions(page_dir) == []


# ---------- comment: the anchor written without a browser ----------


def published(page_dir):
    assert (
        CliRunner()
        .invoke(
            interact.cli,
            ["version", "publish", str(page_dir), "--version", "1", "--text", "first"],
        )
        .exit_code
        == 0
    )
    return page_dir


def comment(page_dir, *args):
    return CliRunner().invoke(interact.cli, ["review", "comment", str(page_dir), *args])


def test_comment_anchors_on_a_quote_and_posts_as_claude(page_dir):
    result = comment(
        published(page_dir), "--quote", "Ship dark", "--text", "dark for how long?"
    )
    assert result.exit_code == 0, result.output
    event = json.loads(result.output)
    assert (
        event["kind"] == "comment"
        and event["author"] == "claude"
        and event["version"] == 1
    )
    assert event["agent"] == "Agent"
    assert event["anchor"]["quote"] == "Ship dark"
    # The section is derived the way the browser derives it — the nearest enclosing id.
    assert event["anchor"]["section"] == "flag-first"
    assert event["text"] == "dark for how long?"


def test_a_comment_carries_the_neighbours_that_tell_two_copies_apart(page_dir):
    """The context is the whole reason a later version can't hand the comment to another
    copy of the same words, so a written anchor stores it exactly as a selection does."""
    event = json.loads(
        comment(
            published(page_dir), "--quote", "Verify, then flip", "--text", "ok"
        ).output
    )
    anchor = event["anchor"]
    # Read out of the whole collapsed text and stopped by the fences around the option
    # row — the runtime writes controls between options, words this reading doesn't
    # hold. The runtime reads its side back the same way, and only a full match counts.
    assert (
        anchor["prefix"] == "risk: low Backfill first"
    )  # the option's own chip band, then its title
    assert (
        anchor["suffix"] == "."
    )  # the option's last words; the fence ends the reading


def test_a_quote_closing_its_section_stores_the_next_sections_words(page_dir):
    """A suffix clipped at the section's edge could be one character, a bar an identical
    copy elsewhere might clear; the whole reading gives a closing passage a full side.
    The section the anchor names scopes where the search may land, never what surrounds
    the passage."""
    two = PAGE.replace(
        '  <cq-diagram id="flow"><pre>\ngraph LR\n  A --> B\n  </pre></cq-diagram>\n',
        "  <p>Deploys pause overnight.</p>\n",
    ).replace(
        "</main>",
        '<section id="rollout">\n  <p>The rollout resumes.</p>\n</section>\n</main>',
    )
    (page_dir / "versions" / "v1.html").write_text(two)
    event = json.loads(
        comment(
            published(page_dir), "--quote", "Deploys pause overnight.", "--text", "x"
        ).output
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
    scoped = comment(
        page_dir, "--quote", "Ship dark", "--section", "flag-first", "--text", "x"
    )
    assert scoped.exit_code == 0, scoped.output
    assert json.loads(scoped.output)["anchor"]["section"] == "flag-first"


def test_a_widgets_data_body_is_not_quotable_but_the_widget_is(page_dir):
    """A diagram's source is a picture by the time the reader sees it, so quoting the
    source anchors on text no search will find. Pointing at the element is what a click
    on that diagram does in the browser, and that is the anchor offered instead."""
    body = comment(published(page_dir), "--quote", "graph LR", "--text", "x")
    assert body.exit_code != 0 and "--section" in body.output
    element = comment(
        page_dir, "--section", "flow", "--text", "the retry edge is missing"
    )
    assert element.exit_code == 0, element.output
    assert json.loads(element.output)["anchor"] == {"section": "flow"}


def test_a_quote_may_not_run_across_a_widgets_parts(page_dir):
    """A module can replace or insert words the file's reading cannot model. A quote
    spanning one of those joins would resolve to nothing in the
    reviewer's browser, so it's refused here, where someone can still do something about
    it. Either side of the join quotes fine."""
    fenced = PAGE.replace(
        '  <cq-diagram id="flow"><pre>\ngraph LR\n  A --> B\n  </pre></cq-diagram>',
        "  <p>Before the diagram.</p>\n"
        '  <cq-diagram id="flow"><pre>\ngraph LR\n  A --> B\n  </pre></cq-diagram>\n'
        "  <p>After the diagram.</p>",
    )
    (page_dir / "versions" / "v1.html").write_text(fenced)
    published(page_dir)
    across = comment(
        page_dir,
        "--quote",
        "Before the diagram. After the diagram.",
        "--text",
        "x",
    )
    assert across.exit_code != 0
    assert "across a widget's parts" in across.output
    assert (
        comment(page_dir, "--quote", "Before the diagram.", "--text", "x").exit_code
        == 0
    )


DRAFTED = PAGE.replace(
    "<h2>Plan</h2>",
    '<h2>Plan</h2>\n  <cq-draft id="note"><pre>\nAdds --dry-run to every mutating command.\n  </pre></cq-draft>',
)


def drafted(page_dir):
    """A published v1 carrying the note draft, its body still Claude's."""
    (page_dir / "versions" / "v1.html").write_text(DRAFTED)
    return published(page_dir)


def edit(page_dir, text, widget="note", version=1):
    interact.append_event(
        page_dir,
        {
            "kind": "action",
            "author": "user",
            "version": version,
            "widget": widget,
            "action": "edit",
            "detail": {"text": text},
        },
    )


def test_a_verbatim_body_is_quotable_where_a_source_body_is_not(page_dir):
    """The registry draws the line: cq-draft renders the authored text into a plain div
    the anchor pass can see (x-verbatim), and cq-diagram renders a picture instead."""
    result = comment(
        drafted(page_dir), "--quote", "every mutating command", "--text", "which ones?"
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["anchor"]["section"] == "note"


def test_an_edited_draft_reads_as_the_reviewers_words(page_dir):
    """An `edit` is absolute — the log carries the whole new body, and replay writes
    exactly that into the DOM the anchor pass searches — so the reading
    `review comment` captures against holds the reviewer's words in the authored body's place:
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
        '<cq-draft id="note"><pre>\nAdds --dry-run to every mutating command.',
        '<cq-draft id="note" restated><pre>\nOnly purge gets a dry-run; the rest apply live.',
    )
    (page_dir / "versions" / "v2.html").write_text(revised)
    noted = CliRunner().invoke(
        interact.cli,
        [
            "version",
            "publish",
            str(page_dir),
            "--version",
            "2",
            "--text",
            "took the pen back",
        ],
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
        {
            "kind": "action",
            "author": "user",
            "version": 1,
            "widget": "note",
            "action": "scribble",
            "detail": {"text": "Words no layer speaks."},
        },
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
        interact.cli,
        [
            "version",
            "publish",
            str(page_dir),
            "--version",
            "2",
            "--text",
            "changes elsewhere",
        ],
    )
    assert noted.exit_code == 0, noted.output
    kept = comment(page_dir, "--quote", "purge and rebuild only", "--text", "x")
    assert kept.exit_code == 0, kept.output
    gone = comment(page_dir, "--quote", "every mutating command", "--text", "x")
    assert gone.exit_code != 0 and "rewrote § note" in gone.output


def test_a_widgets_x_says_attribute_is_quotable_like_any_other_passage(page_dir):
    """renderSaid puts these words in the DOM, so the anchor pass can find them and this
    has to offer them — otherwise a metric's own number is the one thing on the page
    Claude can't point at. Both edges the registry can give one are here: the option's
    chip band opens the element, and the metric's delta closes it."""
    (page_dir / "versions" / "v1.html").write_text(
        PAGE.replace(
            '  <cq-diagram id="flow">',
            '  <cq-metrics><cq-metric id="k-visits" value="312" delta="+41"'
            ' direction="up-good">daily visits</cq-metric></cq-metrics>\n'
            '  <cq-diagram id="flow">',
        )
    )
    published(page_dir)
    for quote, section in (
        ("risk: low Backfill first", "backfill-first"),
        ("daily visits +41", "k-visits"),
    ):
        result = comment(page_dir, "--quote", quote, "--text", "x")
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["anchor"]["section"] == section


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
    gone = comment(
        page_dir, "--quote", "Refill every feeder each morning.", "--text", "x"
    )
    assert gone.exit_code != 0
    assert "chose to accept § sug-refill" in gone.output and "retired" in gone.output
    kept = comment(page_dir, "--quote", "camera shows it half-empty", "--text", "x")
    assert kept.exit_code == 0, kept.output

    decide(page_dir, "reject")
    gone = comment(page_dir, "--quote", "camera shows it half-empty", "--text", "x")
    assert gone.exit_code != 0 and "chose to reject § sug-refill" in gone.output
    kept = comment(
        page_dir, "--quote", "Refill every feeder each morning.", "--text", "x"
    )
    assert kept.exit_code == 0, kept.output


def test_a_section_inside_a_retired_slot_is_refused(page_dir):
    """An element anchor is a click on the element, and a retired slot's children
    are elements nobody can click. The id is still in the file — the refusal has to
    come from the decision, not the structure."""
    suggested(page_dir)
    decide(page_dir, "accept")
    result = comment(page_dir, "--section", "refill-rule", "--text", "x")
    assert result.exit_code != 0
    assert "chose to accept" in result.output and "sug-refill" in result.output


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
    for wid, verb in (("sug-drop", "accept"), ("sug-add", "reject")):
        gone = comment(page_dir, "--section", wid, "--text", "x")
        assert gone.exit_code != 0
        assert "settled to nothing" in gone.output and f"chose to {verb}" in gone.output


def test_a_settled_replacement_still_answers_an_element_anchor(page_dir):
    """Deciding a replacement keeps a slot on screen, so the wrapper is still a thing
    to point at — only a decision that leaves nothing takes the element away."""
    suggested(page_dir)
    decide(page_dir, "accept")
    ok = comment(page_dir, "--section", "sug-refill", "--text", "x")
    assert ok.exit_code == 0, ok.output


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
    ambiguous = comment(
        page_dir, "--quote", "Refill every feeder each morning.", "--text", "x"
    )
    assert ambiguous.exit_code != 0 and "2 times" in ambiguous.output
    decide(page_dir, "accept")
    result = comment(
        page_dir, "--quote", "Refill every feeder each morning.", "--text", "x"
    )
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
    ).replace(
        '<cq-suggestion id="sug-refill">', '<cq-suggestion id="sug-refill" restated>'
    )
    (page_dir / "versions" / "v2.html").write_text(revised)
    noted = CliRunner().invoke(
        interact.cli,
        [
            "version",
            "publish",
            str(page_dir),
            "--version",
            "2",
            "--text",
            "revised the proposal",
        ],
    )
    assert noted.exit_code == 0, noted.output
    result = comment(
        page_dir, "--quote", "Refill every feeder each morning.", "--text", "x"
    )
    assert result.exit_code == 0, result.output


def test_what_the_reader_never_sees_is_not_quotable(page_dir):
    """The runtime roots a section-less anchor at document.body, so a <title> is text no
    anchor can reach — and a page's title is often a sentence from the page as well."""
    (page_dir / "versions" / "v1.html").write_text(
        PAGE.replace("<title>t</title>", "<title>Backfill cutover plan</title>")
    )
    result = comment(
        published(page_dir), "--quote", "Backfill cutover plan", "--text", "x"
    )
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


def test_the_agents_own_comment_is_not_printed_back_to_it(page_dir):
    """`review wait` and the banner's unread count both turn on author, so a note
    Claude leaves can't wake its own watcher or read as a comment nobody answered."""
    published(page_dir)
    assert comment(page_dir, "--quote", "Ship dark", "--text", "x").exit_code == 0
    assert page_state(page_dir)["pending"] == 0
    assert interact.unattended_pages("") == []


def test_a_comments_widget_markup_shares_one_id_universe_with_replies(page_dir):
    """A Claude comment's markup lands in the panel exactly as a reply's does, so it
    validates the same way and claims ids from the same pool."""
    published(page_dir)
    assert (
        comment(
            page_dir,
            "--quote",
            "Ship dark",
            "--text",
            "Pick:",
            "--markup",
            '<cq-options id="q1" choose><cq-option id="q1-a"><strong>A</strong></cq-option></cq-options>',
        ).exit_code
        == 0
    )
    interact.append_event(
        page_dir, {"kind": "comment", "id": "c1", "author": "user", "text": "hm"}
    )
    clash = CliRunner().invoke(
        interact.cli,
        [
            "review",
            "reply",
            str(page_dir),
            "--to",
            "c1",
            "--text",
            "See:",
            "--markup",
            '<cq-diagram id="q1"><pre>\ngraph LR\n  A --> B\n</pre></cq-diagram>',
        ],
    )
    assert clash.exit_code != 0 and "q1" in clash.output
