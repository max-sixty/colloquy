"""Shared fixtures. interact.py is loaded by path because it is a `uv` script,
not an installed module."""

import importlib.util
from pathlib import Path

import pytest

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
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("COLLOQUY_SESSION_ID", raising=False)
    monkeypatch.delenv("COLLOQUY_SESSION_PID", raising=False)
    monkeypatch.delenv("COLLOQUY_AGENT", raising=False)
