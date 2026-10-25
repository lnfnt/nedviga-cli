"""v0.5.6 (the task brief) eco tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nedviga.cli import main


def _card(with_geo=True):
    c = {"id": "cian-1", "source": "cian", "url": "u", "title": "flat",
         "pricing": {"price_total_rub": 1.0}, "parameters": {}, "building": {"address_raw": "addr"}, "geo": {}}
    if with_geo:
        c["geo"] = {"lat": 55.6, "lon": 37.6, "district": "d"}
    return c


def test_eco_no_coordinates(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "card.json"
    f.write_text(json.dumps(_card(False)))
    fix = Path(__file__).parent / "fixtures" / "overpass_sample.json"
    code = main(["eco", "--file", str(f), "--offline", str(fix)])
    out = capsys.readouterr().out
    assert "no_coordinates" in out


def test_eco_proxy_string(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "card.json"
    f.write_text(json.dumps(_card(True)))
    fix = Path(__file__).parent / "fixtures" / "overpass_sample.json"
    code = main(["eco", "--file", str(f), "--offline", str(fix)])
    out = capsys.readouterr().out
    assert "НЕ замер уровня шума" in out or "не замер уровня шума" in out.lower()


def test_eco_highway_distance(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "card.json"
    f.write_text(json.dumps(_card(True)))
    fix = Path(__file__).parent / "fixtures" / "overpass_sample.json"
    code = main(["eco", "--file", str(f), "--offline", str(fix)])
    out = capsys.readouterr().out
    assert code == 0
    assert "шоссе" in out.lower() or "highway" in out.lower() or "по прямой" in out
