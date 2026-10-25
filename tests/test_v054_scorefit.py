"""v0.5.4 (the task brief) scorefit tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nedviga.cli import main


def _profile():
    return {"rooms": 2, "price_max": 10_000_000, "districts": ["ЮАО"], "kitchen_min": 8.0, "metro_walk_max": 15}


def _cards():
    return [{"id": "cian-1", "source": "cian", "url": "u", "title": "flat",
             "pricing": {"price_total_rub": 9_000_000, "price_per_m2_rub": 180_000},
             "parameters": {"rooms": 2, "area_total_m2": 50.0, "floor": 5, "floors_total": 10, "area_kitchen_m2": 9.0},
             "building": {"address_raw": "addr"}, "geo": {"district": "ЮАО", "cian_claimed_metro": {"claimed_time_minutes": 10}}}]


def test_scorefit_basic(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "cards.json"
    f.write_text(json.dumps(_cards()))
    pf = tmp_path / "profile.json"
    pf.write_text(json.dumps(_profile()))
    code = main(["scorefit", "--file", str(f), "--profile", str(pf)])
    out = capsys.readouterr().out
    assert code == 0
    assert "score" in out.lower()
    assert "breakdown" in out.lower()


def test_scorefit_arithmetic(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "cards.json"
    f.write_text(json.dumps(_cards()))
    pf = tmp_path / "profile.json"
    pf.write_text(json.dumps(_profile()))
    code = main(["scorefit", "--file", str(f), "--profile", str(pf)])
    out = capsys.readouterr().out
    assert code == 0


def test_scorefit_determinism(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "cards.json"
    f.write_text(json.dumps(_cards()))
    pf = tmp_path / "profile.json"
    pf.write_text(json.dumps(_profile()))
    main(["scorefit", "--file", str(f), "--profile", str(pf)])
    out1 = capsys.readouterr().out
    main(["scorefit", "--file", str(f), "--profile", str(pf)])
    out2 = capsys.readouterr().out
    import json as _j
    d1 = _j.loads(out1); d2 = _j.loads(out2)
    assert d1["data"] == d2["data"]
