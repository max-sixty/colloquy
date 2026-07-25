"""Shared fixtures. interact.py is loaded by path because it is a `uv` script,
not an installed module."""

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "interact", Path(__file__).parent.parent / "skills" / "colloquy" / "scripts" / "interact.py"
)
interact = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(interact)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path_factory, monkeypatch):
    """Keep the developer's real ~/.claude/colloquy overlay out of every fixture:
    a personal theme.css would otherwise change what init vendors and check
    measures."""
    monkeypatch.setenv("HOME", str(tmp_path_factory.mktemp("home")))
