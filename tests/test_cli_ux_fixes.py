# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 lnfnt <lnfnt@proton.me>

"""TASK_UX_FIXES: --json у noise, --text у triage, гибкие аргументы walk-distance."""
from __future__ import annotations

import json
import re
from unittest.mock import patch

import pytest

from nedviga.cli import main


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path / "state"))


# --- noise: --json ---


def test_noise_latlon_json_flag(capsys):
    code = main(["noise", "--lat", "55.75", "--lon", "37.61", "--json"])
    out = capsys.readouterr().out
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "ok"
    result = payload["data"]["result"]
    assert result["status"] == "ok"
    assert result["measurements"] == []


def test_noise_json_to_file(capsys, tmp_path):
    p = tmp_path / "noise.json"
    code = main(["noise", "--lat", "55.75", "--lon", "37.61", "--json", str(p)])
    assert code == 0
    payload = json.loads(p.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"


def test_noise_usage_error_unchanged(capsys):
    code = main(["noise", "--json"])
    out = capsys.readouterr().out
    assert code == 4
    payload = json.loads(out)
    assert payload["reason"] == "usage_error"


def test_noise_old_file_path_still_works(tmp_path, capsys):
    card = {"id": "cian-1", "source": "cian", "url": "u",
            "geo": {"lat": 55.75, "lon": 37.61}}
    f = tmp_path / "card.json"
    f.write_text(json.dumps(card), encoding="utf-8")
    code = main(["noise", "--file", str(f), "--json"])
    out = capsys.readouterr().out
    assert code == 0
    assert json.loads(out)["data"]["result"]["status"] == "ok"


# --- triage: --text ---


def test_triage_text_flag_returns_flags(capsys):
    code = main(["triage", "--text", "срочная продажа, прописан несовершеннолетний ребенок",
                 "--json"])
    out = capsys.readouterr().out
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "ok"
    data = payload["data"]
    assert "flags" in data and "disclaimer" in data
    codes = [fl["code"] for fl in data["flags"]]
    assert "MINOR_OWNERS" in codes


def test_triage_text_no_phone_leak(capsys):
    code = main(["triage", "--text", "срочная продажа, прописан несовершеннолетний ребенок",
                 "--json"])
    out = capsys.readouterr().out
    assert re.findall(r"\+?7[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}", out) == []


def test_triage_text_usage_error_without_input(capsys):
    code = main(["triage", "--json"])
    out = capsys.readouterr().out
    assert code == 4
    assert json.loads(out)["reason"] == "usage_error"


def test_triage_old_file_path_still_works(tmp_path, capsys):
    card = {"id": "cian-1", "source": "cian", "url": "u",
            "description_text": "продается доля в квартире"}
    f = tmp_path / "card.json"
    f.write_text(json.dumps(card), encoding="utf-8")
    code = main(["triage", "--file", str(f), "--json"])
    out = capsys.readouterr().out
    assert code == 0
    payload = json.loads(out)
    assert any(fl["code"] == "SHARE_IN_RIGHT" for fl in payload["data"]["flags"])


# --- walk-distance: --file / optional lat-lon ---


def test_walk_distance_from_file(tmp_path, capsys):
    card = {"id": "cian-1", "source": "cian", "url": "u",
            "geo": {"lat": 55.6405, "lon": 37.6025}}
    f = tmp_path / "card.json"
    f.write_text(json.dumps(card), encoding="utf-8")

    def fake_walk_route(lat, lon, metro):
        assert (lat, lon) == (55.6405, 37.6025)
        return {"status": "ok", "target_station": metro, "target_vestibule": "v",
                "walk_distance_meters": 800, "walk_duration_minutes": 10,
                "routing_provider": "test", "route_verified": True}

    with patch("nedviga.cli.walk_route", side_effect=fake_walk_route):
        code = main(["walk-distance", "--file", str(f),
                     "--metro", "Чертановская", "--json"])
    out = capsys.readouterr().out
    assert code == 0, out
    payload = json.loads(out)
    assert payload["data"]["honest_walk_route"]["target_station"] == "Чертановская"


def test_walk_distance_itself_wrapped_in_envelope(tmp_path, capsys):
    card = {"id": "cian-1", "source": "cian", "url": "u",
            "geo": {"lat": 55.6405, "lon": 37.6025,
                    "cian_claimed_metro": {"station": "Чертановская",
                                            "claimed_time_minutes": 10}}}
    f = tmp_path / "card.json"
    f.write_text(json.dumps(card), encoding="utf-8")

    def fake_walk_route(lat, lon, metro, **kw):
        return {"status": "ok", "target_station": metro, "target_vestibule": "v",
                "walk_distance_meters": 800, "walk_duration_minutes": 10,
                "routing_provider": "test", "route_verified": True}

    with patch("nedviga.cli.walk_route", side_effect=fake_walk_route):
        code = main(["walk-distance", "--file", str(f), "--metro", "Чертановская",
                     "--claimed-time", "6", "--json"])
    out = capsys.readouterr().out
    assert code == 0
    payload = json.loads(out)
    assert payload["data"]["honest_overclaim"]["overclaim_minutes"] == 4


def test_walk_distance_usage_error_without_anything(capsys):
    code = main(["walk-distance", "--metro", "Чертановская", "--json"])
    out = capsys.readouterr().out
    assert code == 4
    assert json.loads(out)["reason"] == "usage_error"


def test_walk_distance_card_without_coords(capsys, tmp_path):
    card = {"id": "cian-1", "source": "cian", "url": "u", "geo": {}}
    f = tmp_path / "card.json"
    f.write_text(json.dumps(card), encoding="utf-8")
    code = main(["walk-distance", "--file", str(f), "--metro", "Чертановская",
                 "--json"])
    out = capsys.readouterr().out
    assert code == 4
    assert json.loads(out)["reason"] == "usage_error"


def test_walk_distance_legacy_latlon_still_works(capsys):
    def fake_walk_route(lat, lon, metro):
        assert (float(lat), float(lon)) == (55.75, 37.61)
        return {"status": "ok", "target_station": metro, "target_vestibule": "v",
                "walk_distance_meters": 800, "walk_duration_minutes": 10,
                "routing_provider": "test", "route_verified": True}

    with patch("nedviga.cli.walk_route", side_effect=fake_walk_route):
        code = main(["walk-distance", "--lat", "55.75", "--lon", "37.61",
                     "--metro", "Чертановская", "--json"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert json.loads(out)["data"]["honest_walk_route"]["walk_distance_meters"] == 800
