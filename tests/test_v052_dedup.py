"""v0.5.2 (the task brief) dedup tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nedviga.cli import main
from nedviga.dedup import dedup_cards


def _card(cid, addr="addr", area=50.0, rooms=2, floor=5, floors=10, photo="p.jpg", lat=55.6, lon=37.6):
    return {
        "id": cid, "source": "cian", "url": f"u{cid}", "title": f"flat {cid}",
        "pricing": {"price_total_rub": 100.0, "price_per_m2_rub": 2.0},
        "parameters": {"rooms": rooms, "area_total_m2": area, "floor": floor, "floors_total": floors},
        "building": {"address_raw": addr},
        "geo": {"lat": lat, "lon": lon, "district": "d"},
        "images": [{"url": f"https://cdn/{photo}"}],
    }


def test_dedup_duplicate_pair(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    cards = [_card("a"), _card("b")]  # same signature
    f = tmp_path / "cards.json"
    f.write_text(json.dumps(cards))
    code = main(["dedup", "--file", str(f)])
    out = capsys.readouterr().out
    assert code == 0
    assert "a" in out and "b" in out


def test_dedup_non_duplicate(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    cards = [_card("a"), _card("b", area=80.0, lat=56.0, lon=38.0)]
    f = tmp_path / "cards.json"
    f.write_text(json.dumps(cards))
    code = main(["dedup", "--file", str(f)])
    out = capsys.readouterr().out
    # no groups
    assert "[]" in out or "groups" in out.lower()


def test_dedup_signals_listed(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    cards = [_card("a"), _card("b")]
    f = tmp_path / "cards.json"
    f.write_text(json.dumps(cards))
    code = main(["dedup", "--file", str(f)])
    out = capsys.readouterr().out
    assert "адрес" in out or "площадь" in out or "photo" in out or "сигнал" in out.lower()


def test_dedup_number_grep(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    cards = [_card("a"), _card("b")]
    for c in cards:
        c["seller"] = {"phones": ["+7 (999) 000-11-22"]}
    f = tmp_path / "cards.json"
    f.write_text(json.dumps(cards))
    code = main(["dedup", "--file", str(f)])
    out = capsys.readouterr().out
    import re
    assert re.findall(r"\+?7[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}", out) == []


def test_dedup_module():
    cards = [_card("a"), _card("b")]
    groups = dedup_cards(cards)
    assert isinstance(groups, list)
    assert len(groups) >= 1
