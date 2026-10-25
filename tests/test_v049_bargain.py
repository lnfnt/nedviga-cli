"""v0.4.9 (the task brief) F-10b: bargain tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nedviga.cli import main


def _corpus(n=21):
    out = []
    for i in range(n):
        ppm2 = 100000 + i * 10000
        out.append({
            "id": f"corp-{i}",
            "source": "cian",
            "url": f"u{i}",
            "title": f"flat {i}",
            "pricing": {"price_total_rub": ppm2 * 50.0, "price_per_m2_rub": ppm2},
            "parameters": {"rooms": 2, "area_total_m2": 50.0, "floor": 3, "floors_total": 10},
            "building": {"address_raw": "addr"},
            "geo": {"district": "ЮАО"},
        })
    return out


def _target():
    return {
        "id": "target",
        "source": "cian",
        "url": "ut",
        "title": "target flat",
        "pricing": {"price_total_rub": 216000 * 50.0, "price_per_m2_rub": 216000},
        "parameters": {"rooms": 2, "area_total_m2": 50.0, "floor": 3, "floors_total": 10},
        "building": {"address_raw": "addr"},
        "geo": {"district": "ЮАО"},
    }


def test_bargain_insufficient_sample(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps(_corpus(19)))
    target = tmp_path / "target.json"
    target.write_text(json.dumps(_target()))
    code = main(["bargain", "--file", str(target), "--corpus", str(corpus)])
    out = capsys.readouterr().out
    assert "insufficient_sample" in out
    assert "n=19" in out
    # no typical discount numbers
    assert "типич" not in out.lower()


def test_bargain_sufficient_sample_median(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps(_corpus(21)))
    target = tmp_path / "target.json"
    target.write_text(json.dumps(_target()))
    code = main(["bargain", "--file", str(target), "--corpus", str(corpus)])
    out = capsys.readouterr().out
    assert code == 0
    # median of 100000..300000 step 10000 (21 values) = 200000
    assert "200000" in out or "200 000" in out
    assert "P25" in out and "P75" in out


def test_bargain_number_grep(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    corpus = tmp_path / "corpus.json"
    c = _corpus(21)
    for item in c:
        item["seller"] = {"phones": ["+7 (999) 000-11-22"]}
    corpus.write_text(json.dumps(c))
    target = tmp_path / "target.json"
    t = _target()
    t["seller"] = {"phones": ["+79161234567"]}
    target.write_text(json.dumps(t))
    code = main(["bargain", "--file", str(target), "--corpus", str(corpus)])
    out = capsys.readouterr().out
    import re
    assert re.findall(r"\+?7[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}", out) == []


def test_bargain_out_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps(_corpus(21)))
    target = tmp_path / "target.json"
    target.write_text(json.dumps(_target()))
    outp = tmp_path / "bargain.md"
    code = main(["bargain", "--file", str(target), "--corpus", str(corpus), "--out", str(outp)])
    capsys.readouterr()
    assert code == 0
    assert outp.exists()


def test_bargain_disclaimer(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps(_corpus(21)))
    target = tmp_path / "target.json"
    target.write_text(json.dumps(_target()))
    code = main(["bargain", "--file", str(target), "--corpus", str(corpus)])
    out = capsys.readouterr().out
    assert "не официальная" in out or "оценка по" in out
