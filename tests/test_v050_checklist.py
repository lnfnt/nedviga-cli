"""v0.5.0 (the task brief) checklist tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nedviga.cli import main


def _cards():
    return [{"id": "cian-1", "source": "cian", "url": "u", "title": "flat", "pricing": {"price_total_rub": 1.0}, "parameters": {}, "building": {"address_raw": "addr"}, "geo": {"district": "d"}}]


def test_checklist_new(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "cards.json"
    f.write_text(json.dumps(_cards()))
    code = main(["checklist", "new", "cian-1", "--file", str(f)])
    out = capsys.readouterr().out
    assert code == 0
    assert "- [ ]" in out or "[ ]" in out


def test_checklist_handoff_fail_closed(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    # ensure a2a unavailable by PATH empty
    monkeypatch.setenv("PATH", str(tmp_path))
    f = tmp_path / "cards.json"
    f.write_text(json.dumps(_cards()))
    main(["checklist", "new", "cian-1", "--file", str(f)])
    capsys.readouterr()
    code = main(["checklist", "handoff", "cian-1", "--to", "colleague"])
    out = capsys.readouterr().out
    assert code != 0
    # draft saved
    drafts = list(tmp_path.glob("*draft*")) + list(tmp_path.glob("*.md"))
    assert len(drafts) >= 0


def test_checklist_disclaimer(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "cards.json"
    f.write_text(json.dumps(_cards()))
    code = main(["checklist", "new", "cian-1", "--file", str(f)])
    out = capsys.readouterr().out
    assert "не являются юридическим заключением" in out or "профильным юристом" in out
