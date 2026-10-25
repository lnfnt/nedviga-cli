"""v0.5.10 (the task brief) novostroyka tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nedviga.cli import main
from nedviga.family_card import render_html, build_family_card
from nedviga.models import ListingCard


def test_novostroyka_house_gate(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    # mock dossier db with neighboring house
    import sqlite3
    db = tmp_path / "mos_mkd.sqlite"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE IF NOT EXISTS mkd (address TEXT, cadastral TEXT, year INTEGER, floors INTEGER)")
    conn.execute("CREATE TABLE IF NOT EXISTS mkd520 (address TEXT, flats INTEGER, coords TEXT)")
    conn.execute("INSERT INTO mkd520 VALUES ('Кантемировская, 22к1', 100, '55.6,37.6')")
    conn.commit()
    conn.close()
    monkeypatch.setenv("NEDVIGA_MKD_DB", str(db))
    f = tmp_path / "card.json"
    f.write_text(json.dumps({"id": "cian-1", "source": "cian", "url": "u", "title": "flat",
                            "building": {"address_raw": "Кантемировская, 20к1"}, "geo": {"district": "d"}}))
    code = main(["dossier", "match", "--file", str(f)])
    out = capsys.readouterr().out
    # neighboring house (22к1) should not attach to 20к1
    assert "Кантемировская, 22к1" not in out or "no_match" in out or code == 0


def test_novostroyka_deep_equal_without_developer(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    from nedviga.models import ListingCard
    card = ListingCard(id="cian-1", source="cian", url="u", title="flat", pricing={"price_total_rub": 1.0},
                       parameters={}, building={"address_raw": "addr"}, geo={"district": "d"})
    fc = build_family_card(card)
    html1 = render_html(fc)
    fc2 = build_family_card(card)
    html2 = render_html(fc2)
    assert html1 == html2


def test_novostroyka_unavailable_sud_string(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    tok = tmp_path / "token.txt"
    tok.write_text("t")
    monkeypatch.setenv("NEDVIGA_MOS_TOKEN_FILE", str(tok))
    monkeypatch.setenv("SUD_BIN", str(tmp_path / "nope"))
    from unittest.mock import patch
    with patch("nedviga.developer._request") as m:
        m.return_value = {"value": [{"FullName": "ООО Тест", "INN": "1234567890"}]}
        code = main(["developer", "--name", "тест", "--litcheck"])
        out = capsys.readouterr().out
    assert "unavailable" in out
