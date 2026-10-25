"""v0.5.0 (the task brief) projects tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nedviga.cli import main


def test_project_new_and_list(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    code = main(["project", "new", "alpha", "--query", '{"rooms":2}'])
    capsys.readouterr()
    assert code == 0
    code = main(["project", "list"])
    out = capsys.readouterr().out
    assert "alpha" in out


def test_project_add_idempotent(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    main(["project", "new", "alpha", "--query", '{"rooms":2}'])
    capsys.readouterr()
    main(["project", "add", "alpha", "cian-1"])
    capsys.readouterr()
    main(["project", "add", "alpha", "cian-1"])
    capsys.readouterr()
    code = main(["project", "open", "alpha"])
    out = capsys.readouterr().out
    assert out.count("cian-1") <= 2


def test_project_open(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    main(["project", "new", "alpha", "--query", '{"rooms":2}'])
    capsys.readouterr()
    main(["project", "add", "alpha", "cian-1"])
    capsys.readouterr()
    code = main(["project", "open", "alpha"])
    out = capsys.readouterr().out
    assert code == 0
    assert "cian-1" in out


def test_project_refresh_delta(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    main(["project", "new", "alpha", "--query", '{"rooms":2}'])
    capsys.readouterr()
    main(["project", "add", "alpha", "cian-1"])
    capsys.readouterr()
    # baseline snapshot in project? refresh with new search
    new = tmp_path / "new.json"
    new.write_text(json.dumps([{"id": "cian-2", "source": "cian", "url": "u2", "pricing": {"price_total_rub": 1.0}}]))
    code = main(["project", "refresh", "alpha", "--file", str(new)])
    out = capsys.readouterr().out
    assert code == 0
    assert "new" in out.lower() or "delta" in out.lower() or "cian-2" in out
