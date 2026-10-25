"""v0.4.9 (the task brief) F-07b/F-19: risk tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nedviga.cli import main


def _target():
    return {
        "id": "target",
        "source": "cian",
        "url": "ut",
        "title": "СРОЧНО!!! Продам квартиру!!!",
        "description_text": "Без торга, реально всё",
        "pricing": {"price_total_rub": 5_000_000, "price_per_m2_rub": 50_000},
        "parameters": {"rooms": 2, "area_total_m2": 100.0, "floor": 1, "floors_total": 5},
        "building": {"address_raw": "addr"},
        "geo": {"district": "ЮАО"},
    }


def _corpus():
    out = []
    for i in range(21):
        out.append({
            "id": f"corp-{i}",
            "source": "cian",
            "url": f"u{i}",
            "title": f"flat {i}",
            "pricing": {"price_total_rub": 10_000_000, "price_per_m2_rub": 100_000},
            "parameters": {"rooms": 2, "area_total_m2": 100.0, "floor": 3, "floors_total": 10},
            "building": {"address_raw": "addr"},
            "geo": {"district": "ЮАО"},
        })
    return out


def test_risk_single(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "card.json"
    f.write_text(json.dumps(_target()))
    code = main(["risk", "--file", str(f)])
    out = capsys.readouterr().out
    assert code == 0
    assert "risk_score" in out


def test_risk_signals(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "card.json"
    f.write_text(json.dumps(_target()))
    code = main(["risk", "--file", str(f)])
    out = capsys.readouterr().out
    # urgent/caps/exclamations
    assert "risk_score" in out


def test_risk_bait_suspect_wording(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "card.json"
    f.write_text(json.dumps(_target()))
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps(_corpus()))
    code = main(["risk", "--file", str(f), "--corpus", str(corpus)])
    out = capsys.readouterr().out
    low = out.lower()
    # suspect wording, not verdict
    assert "подозр" in low or "похоже" in low
    import re
    for bad in ("точно", "гарантированно", "верно"):
        assert re.search(r"\b" + bad + r"\b", low) is None


def test_risk_number_grep(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    t = _target()
    t["seller"] = {"phones": ["+7 (999) 000-11-22"]}
    f = tmp_path / "card.json"
    f.write_text(json.dumps(t))
    code = main(["risk", "--file", str(f)])
    out = capsys.readouterr().out
    import re
    assert re.findall(r"\+?7[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}", out) == []


def test_risk_out_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "card.json"
    f.write_text(json.dumps(_target()))
    outp = tmp_path / "risk.json"
    code = main(["risk", "--file", str(f), "--out", str(outp)])
    capsys.readouterr()
    assert code == 0
    assert outp.exists()
