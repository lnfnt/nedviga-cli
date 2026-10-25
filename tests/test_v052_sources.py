"""v0.5.2 (the task brief) sources tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nedviga.cli import main
from nedviga.sources import list_sources, register_source


def test_sources_list_command(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    code = main(["sources", "list"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Cian" in out or "cian" in out
    assert "ready" in out.lower()


def test_sources_only_cian_ready(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    srcs = list_sources()
    names = [s.get("id") if isinstance(s, dict) else getattr(s, "id", None) for s in srcs]
    assert "cian" in [str(n).lower() for n in names]
    # no empty promises: only ready/experimental/blocked statuses
    for s in srcs:
        st = s.get("status") if isinstance(s, dict) else getattr(s, "status", None)
        assert st in {"ready", "experimental", "blocked"}


def test_sources_register_custom():
    class Dummy:
        id = "dummy"
        site_patterns = ["example.com"]
        status = "experimental"
    register_source(Dummy())
    srcs = list_sources()
    ids = [ (s.get("id") if isinstance(s, dict) else getattr(s, "id", None)) for s in srcs]
    assert "dummy" in [str(x).lower() for x in ids]
