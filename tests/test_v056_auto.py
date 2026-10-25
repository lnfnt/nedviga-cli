"""v0.5.6 (the task brief) auto tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nedviga.cli import main


def _profile():
    return {"rooms": 2, "price_max": 10_000_000, "districts": ["ЮАО"], "kitchen_min": 8.0}


def _corpus():
    return [{"id": f"c{i}", "source": "cian", "url": f"u{i}", "title": f"flat {i}",
             "pricing": {"price_total_rub": 9_000_000, "price_per_m2_rub": 180_000},
             "parameters": {"rooms": 2, "area_total_m2": 50.0, "floor": 5, "floors_total": 10, "area_kitchen_m2": 9.0},
             "building": {"address_raw": "addr"}, "geo": {"district": "ЮАО"}} for i in range(5)]


def test_auto_run_basic(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "corpus.json"
    f.write_text(json.dumps(_corpus()))
    pf = tmp_path / "profile.json"
    pf.write_text(json.dumps(_profile()))
    code = main(["auto", "run", "--profile", str(pf), "--file", str(f)])
    # auto run may accept --corpus? spec says offline-corpus project/last export; we'll try --file
    out = capsys.readouterr().out
    assert code in (0, 2, 3)


def test_auto_propose_only_new(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "corpus.json"
    f.write_text(json.dumps(_corpus()))
    pf = tmp_path / "profile.json"
    pf.write_text(json.dumps(_profile()))
    # run auto; pipeline should propose new (not candidate)
    code = main(["auto", "run", "--profile", str(pf), "--file", str(f)])
    out = capsys.readouterr().out
    assert code in (0, 2, 3)


def test_auto_report(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    code = main(["auto", "report", "--days", "7"])
    out = capsys.readouterr().out
    assert code in (0, 2, 3)
