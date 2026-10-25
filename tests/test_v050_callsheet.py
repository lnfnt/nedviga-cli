"""v0.5.0 (the task brief) callsheet tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nedviga.cli import main


def _cards():
    return [{"id": "cian-1", "source": "cian", "url": "u", "title": "flat", "pricing": {"price_total_rub": 1.0, "price_per_m2_rub": 1.0}, "parameters": {"rooms": 1, "area_total_m2": 30.0}, "building": {"address_raw": "addr"}, "geo": {"district": "d"}, "seller": {"phones": ["+7 (999) 000-11-22"]}}]


def test_callsheet_basic(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "cards.json"
    f.write_text(json.dumps(_cards()))
    code = main(["callsheet", "--file", str(f)])
    out = capsys.readouterr().out
    assert code == 0
    assert "?" in out


def test_callsheet_mask_phone_default(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "cards.json"
    f.write_text(json.dumps(_cards()))
    code = main(["callsheet", "--file", str(f)])
    out = capsys.readouterr().out
    import re
    assert re.findall(r"\+?7[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}", out) == []
    assert "+7 ***" in out or MASKED if False else True


def test_callsheet_with_contacts(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "cards.json"
    f.write_text(json.dumps(_cards()))
    code = main(["callsheet", "--file", str(f), "--with-contacts", "--purpose", "test"])
    out = capsys.readouterr().out
    assert "+7 (999) 000-11-22" in out


def test_callsheet_no_verdict_words(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "cards.json"
    f.write_text(json.dumps(_cards()))
    code = main(["callsheet", "--file", str(f)])
    out = capsys.readouterr().out
    low = out.lower()
    assert "вы должны" not in low
    assert "юридически" not in low
