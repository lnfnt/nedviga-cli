"""v0.5.0 (the task brief) legal triage tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nedviga.cli import main


def _card(text=""):
    return {
        "id": "cian-1",
        "source": "cian",
        "url": "u",
        "title": "flat",
        "description_text": text,
        "pricing": {"price_total_rub": 100.0, "price_per_m2_rub": 10.0},
        "parameters": {"rooms": 1, "area_total_m2": 30.0},
        "building": {"address_raw": "addr"},
        "geo": {"district": "d"},
        "seller": {"phones": ["+7 (999) 000-11-22"]},
    }


def test_triage_flag_with_basis(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "card.json"
    f.write_text(json.dumps(_card("продается доля в квартире")))
    code = main(["triage", "--file", str(f)])
    out = capsys.readouterr().out
    assert code == 0
    assert "SHARE_IN_RIGHT" in out
    assert "доля" in out


def test_triage_no_markers_empty(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "card.json"
    f.write_text(json.dumps(_card("обычная квартира")))
    code = main(["triage", "--file", str(f)])
    out = capsys.readouterr().out
    assert code == 0
    # flags empty
    assert "[]" in out or "flags" in out


def test_triage_disclaimer_present(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "card.json"
    f.write_text(json.dumps(_card("доля")))
    code = main(["triage", "--file", str(f)])
    out = capsys.readouterr().out
    assert "не являются юридическим заключением" in out or "профильным юристом" in out


def test_triage_number_grep(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "card.json"
    f.write_text(json.dumps(_card("доля")))
    code = main(["triage", "--file", str(f)])
    out = capsys.readouterr().out
    import re
    assert re.findall(r"\+?7[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}", out) == []


def test_control_flags_are_our_own_text_not_spotlighted():
    # v0.5.0 контроль качества: юридические label/check из legal_flags.json —
    # НАШИ статичные тексты; эвристический spotlight по имени поля "title"
    # не должен их оборачивать. Поле переименовано в label; проверяем контракт.
    import json
    from nedviga.models import ListingCard
    from nedviga.legal_triage import triage
    c = ListingCard.model_validate({
        "id": "cian-1", "source": "cian", "url": "https://www.cian.ru/sale/flat/1/",
        "title": "продажа доли", "pricing": {"price_total_rub": 5000000},
        "description_text": "доля в праве"})
    out = triage(c)
    assert out["flags"] and "label" in out["flags"][0]
    assert "title" not in out["flags"][0]
    blob = json.dumps(out, ensure_ascii=False)
    assert "external_untrusted_data" not in blob
    assert "не являются юридическим заключением" in out["disclaimer"]
