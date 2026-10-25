"""v0.5.3 (the task brief) stale tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nedviga.cli import main


def _cards():
    return [{"id": "cian-1", "source": "cian", "url": "u", "title": "flat",
             "pricing": {"price_total_rub": 1.0}, "parameters": {}, "building": {"address_raw": "addr"},
             "geo": {"district": "d"}}]


def test_stale_basic(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "cards.json"
    f.write_text(json.dumps(_cards()))
    code = main(["stale", "--file", str(f)])
    out = capsys.readouterr().out
    assert code == 0
    assert "stale" in out.lower() or "gone" in out.lower() or "relisted" in out.lower()


def test_stale_statuses(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "cards.json"
    f.write_text(json.dumps(_cards()))
    code = main(["stale", "--file", str(f)])
    out = capsys.readouterr().out
    assert code == 0


def test_stale_number_grep(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    cards = _cards()
    cards[0]["seller"] = {"phones": ["+7 (999) 000-11-22"]}
    f = tmp_path / "cards.json"
    f.write_text(json.dumps(cards))
    code = main(["stale", "--file", str(f)])
    out = capsys.readouterr().out
    import re
    assert re.findall(r"\+?7[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}", out) == []
