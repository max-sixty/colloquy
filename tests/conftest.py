"""Shared fixtures. interact.py is loaded by path because it is a `uv` script,
not an installed module."""

import importlib.util
import subprocess
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

# uv keeps its cache under the developer's home, and the fixture below moves that
# home, so every `bin/colloquy` subprocess would otherwise resolve its
# dependencies from scratch — a second per call. Pinning the cache leaves the
# isolation to the thing it is for, which is the colloquy overlay.
#
# `--color never` because uv colours this path even into a pipe, and a cache
# directory wearing an escape sequence is a relative path starting with one: the
# pinning silently stopped happening, and every run built a second cache inside
# the checkout under a directory named for the escape itself.
UV_CACHE = subprocess.run(
    ["uv", "--color", "never", "cache", "dir"],
    capture_output=True,
    text=True,
    check=True,
).stdout.strip()

_spec = importlib.util.spec_from_file_location(
    "interact",
    Path(__file__).parent.parent
    / "plugins"
    / "colloquy"
    / "skills"
    / "colloquy"
    / "scripts"
    / "interact.py",
)
interact = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(interact)


@pytest.fixture(autouse=True)
def isolated_session(tmp_path_factory, monkeypatch):
    """Keep the developer's session out of every fixture. Their real
    ~/.config/colloquy overlay would otherwise change what init vendors and check
    measures, and a page tagged with the session running the tests is a page the
    review-guard hook reports as an unattended review at the end of every turn —
    a dozen throwaway fixtures per run. An untagged page is nobody's, which is
    what a fixture should be."""
    monkeypatch.setenv("HOME", str(tmp_path_factory.mktemp("home")))
    monkeypatch.setenv("UV_CACHE_DIR", UV_CACHE)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("CLAUDE_PID", raising=False)
    monkeypatch.delenv("COLLOQUY_SESSION_ID", raising=False)
    monkeypatch.delenv("COLLOQUY_SESSION_PID", raising=False)
    monkeypatch.delenv("COLLOQUY_AGENT", raising=False)


@pytest.fixture(scope="module")
def browser():
    """The Chrome already on the machine, driven for the tests a static read
    can't answer: what a widget upgrades into, and what the site fits on."""
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        yield b
        b.close()
