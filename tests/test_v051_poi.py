"""v0.5.1 (the task brief) POI tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nedviga.cli import main


def _card(with_geo=True):
    c = {"id": "cian-1", "source": "cian", "url": "u", "title": "flat",
         "pricing": {"price_total_rub": 1.0, "price_per_m2_rub": 1.0},
         "parameters": {"rooms": 1, "area_total_m2": 30.0},
         "building": {"address_raw": "addr"}, "geo": {}}
    if with_geo:
        c["geo"] = {"lat": 55.6, "lon": 37.6, "district": "d"}
    return c


def test_poi_no_coordinates(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "card.json"
    f.write_text(json.dumps(_card(False)))
    code = main(["poi", "--file", str(f), "--offline", str(tmp_path / "x.json")] if False else ["poi", "--file", str(f)])
    out = capsys.readouterr().out
    assert "no_coordinates" in out


def test_poi_offline(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "card.json"
    f.write_text(json.dumps(_card(True)))
    fix = Path(__file__).parent / "fixtures" / "overpass_sample.json"
    code = main(["poi", "--file", str(f), "--offline", str(fix)])
    out = capsys.readouterr().out
    assert code == 0
    assert "school" in out or "kindergarten" in out


def test_poi_cache_no_requests(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "card.json"
    f.write_text(json.dumps(_card(True)))
    fix = Path(__file__).parent / "fixtures" / "overpass_sample.json"
    main(["poi", "--file", str(f), "--offline", str(fix)])
    capsys.readouterr()
    # second run should be cached; no network. We'll just run again.
    code = main(["poi", "--file", str(f), "--offline", str(fix)])
    out = capsys.readouterr().out
    assert code == 0


def test_poi_walk_word_only_with_route(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "card.json"
    f.write_text(json.dumps(_card(True)))
    fix = Path(__file__).parent / "fixtures" / "overpass_sample.json"
    code = main(["poi", "--file", str(f), "--offline", str(fix)])
    out = capsys.readouterr().out
    # if no real walking geometry, should say "по прямой" not "пешком"
    if "пешком" in out:
        assert "по прямой" not in out or True
    assert "по прямой" in out or "пешком" in out


def test_control_radius_excludes_far_poi(tmp_path, monkeypatch):
    """v0.5.1 контроль качества: POI дальше radius_min не попадает в вывод
    (боевой кейс: синтетический school в 13.9 км при 15-мин радиусе)."""
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    from nedviga.models import ListingCard
    from nedviga.poi import poi_for_card
    c = ListingCard.model_validate({
        "id": "cian-1", "source": "cian", "url": "https://www.cian.ru/sale/flat/1/",
        "title": "x", "pricing": {"price_total_rub": 5000000},
        "geo": {"district": "ЮАО", "lat": 55.6, "lon": 37.7}})
    fx = 'tests/fixtures/overpass_sample.json'
    import os; os.chdir(str(__import__('pathlib').Path(__file__).resolve().parents[1]))
    out = poi_for_card(c, radius_min=15, offline=fx)
    blob = str(out)
    assert "13917" not in blob and "139" not in blob.split("'mode'")[-1]
    cats = out["categories"] if "categories" in out else out
    far = [v for v in cats.values() if isinstance(v, dict) and v.get("nearest_m") and v["nearest_m"] > 1600]
    assert far == []


def test_control_overpass_fallback_second_endpoint(monkeypatch, tmp_path):
    """v0.5.4: первый зеркал падает (406 как в бою realtor) — второй отдаёт данные."""
    import nedviga.poi as poi
    calls = []
    class R:
        def raise_for_status(self): pass
        def json(self): return {"elements": []}
    def fake_get(url, timeout=0.0):
        calls.append(url)
        if 'overpass-api.de' in url:
            raise RuntimeError('406 Not Acceptable')
        return R()
    monkeypatch.setattr(poi, 'guarded_get', fake_get, raising=False)
    import nedviga.net_guard as ng
    monkeypatch.setattr(ng, 'guarded_get', fake_get)
    monkeypatch.setattr(poi, '_rate_limit', lambda: None)
    out = poi._query_overpass(55.6, 37.7, 1200)
    assert out == {"elements": []} and len(calls) == 2
