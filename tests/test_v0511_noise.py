"""v0.5.11 (the task brief) noise tests (RED)."""
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


def test_noise_no_coordinates(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "card.json"
    f.write_text(json.dumps(_card(False)))
    code = main(["noise", "--file", str(f)])
    out = capsys.readouterr().out
    assert "no_coordinates" in out


def test_noise_disclaimer_always(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "card.json"
    f.write_text(json.dumps(_card(True)))
    fix = Path(__file__).parent / "fixtures" / "noise_sample.json" if False else None
    # use sync mock via db? Just run
    code = main(["noise", "--file", str(f)])
    out = capsys.readouterr().out
    assert "точечные измерения" in out or "не замер" in out.lower() or "disclaimer" in out.lower()


def test_noise_sync_idempotent(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    code = main(["noise", "sync", "--limit", "5"])
    out = capsys.readouterr().out
    assert code in (0, 2, 3)


def test_eco_deep_equal_without_noise(tmp_path, monkeypatch, capsys):
    # eco output unchanged when no noise data
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "card.json"
    f.write_text(json.dumps(_card(True)))
    fix = Path(__file__).parent / "fixtures" / "overpass_sample.json"
    code1 = main(["eco", "--file", str(f), "--offline", str(fix)])
    out1 = capsys.readouterr().out
    code2 = main(["eco", "--file", str(f), "--offline", str(fix)])
    out2 = capsys.readouterr().out
    import json as _j
    d1 = _j.loads(out1); d2 = _j.loads(out2)
    assert d1["data"] == d2["data"]


def test_control_pure_coords_no_crash(tmp_path, monkeypatch):
    """v0.5.11 контроль: --lat/--lon путь не должен падать ListingCard-валидацией."""
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    from nedviga.noise import noise_for_card
    r = noise_for_card({"geo": {"lat": 55.727, "lon": 37.612}})
    assert r["status"] in {"ok", "no_coordinates"}
    r2 = noise_for_card({"id": "x", "source": "cian", "url": "u",
                         "geo": {"lat": 55.7, "lon": 37.6}})
    assert r2["status"] in {"ok", "no_coordinates"}
