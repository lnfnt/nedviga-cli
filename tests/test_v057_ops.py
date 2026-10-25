"""v0.5.7 (the task brief) ops tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nedviga.cli import main


def test_ops_offline_no_network(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    code = main(["ops"])
    out = capsys.readouterr().out
    assert code == 0


def test_ops_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    code = main(["ops", "--json"])
    out = capsys.readouterr().out
    assert code == 0
    import json
    d = json.loads(out)
    assert isinstance(d, dict)


def test_ops_precheck_offline(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    code = main(["ops", "--precheck"])
    out = capsys.readouterr().out
    assert code == 0
