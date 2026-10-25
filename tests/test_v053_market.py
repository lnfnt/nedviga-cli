"""v0.5.3 (the task brief) market tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nedviga.cli import main


def _corpus():
    out = []
    for i in range(25):
        out.append({
            "id": f"c{i}", "source": "cian", "url": f"u{i}", "title": f"flat {i}",
            "pricing": {"price_total_rub": 10_000_000 + i * 100_000, "price_per_m2_rub": 200_000 + i * 1000},
            "parameters": {"rooms": 2 if i % 2 == 0 else 3, "area_total_m2": 50.0 + i, "floor": 3, "floors_total": 10},
            "building": {"address_raw": "addr"},
            "geo": {"district": "ЮАО"},
        })
    return out


def test_market_basic(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "corpus.json"
    f.write_text(json.dumps(_corpus()))
    code = main(["market", "--corpus", str(f), "--district", "ЮАО"])
    out = capsys.readouterr().out
    assert code == 0
    assert "n=" in out or "n =" in out or "\"n\"" in out


def test_market_insufficient(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "corpus.json"
    f.write_text(json.dumps(_corpus()[:5]))
    code = main(["market", "--corpus", str(f), "--district", "ЮАО"])
    out = capsys.readouterr().out
    assert "insufficient" in out.lower()


def test_market_number_grep(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "corpus.json"
    c = _corpus()
    for x in c:
        x["seller"] = {"phones": ["+7 (999) 000-11-22"]}
    f.write_text(json.dumps(c))
    code = main(["market", "--corpus", str(f)])
    out = capsys.readouterr().out
    import re
    assert re.findall(r"\+?7[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}", out) == []


def test_market_out_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "corpus.json"
    f.write_text(json.dumps(_corpus()))
    outp = tmp_path / "market.md"
    code = main(["market", "--corpus", str(f), "--out", str(outp)])
    capsys.readouterr()
    assert code == 0
    assert outp.exists()
