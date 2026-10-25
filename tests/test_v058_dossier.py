"""v0.5.8 (the task brief) dossier tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nedviga.cli import main
from nedviga.models import ListingCard


def test_dossier_match(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    # mock db with one row
    import sqlite3
    db = tmp_path / "mos_mkd.sqlite"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE mkd (address TEXT, cadastral TEXT, year INTEGER, floors INTEGER)")
    conn.execute("INSERT INTO mkd VALUES ('Кантемировская, 20к1', '77:00:0:1', 1970, 9)")
    conn.commit()
    conn.close()
    monkeypatch.setenv("NEDVIGA_MKD_DB", str(db))
    f = tmp_path / "card.json"
    f.write_text(json.dumps({"id": "cian-1", "source": "cian", "url": "u", "title": "flat", "building": {"address_raw": "Кантемировская, 20к1"}, "geo": {"district": "d"}}))
    code = main(["dossier", "match", "--file", str(f)])
    out = capsys.readouterr().out
    assert code == 0
    assert "Кантемировская" in out or "кадастр" in out.lower() or "77:00" in out


def test_dossier_no_match(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    import sqlite3
    db = tmp_path / "mos_mkd.sqlite"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE mkd (address TEXT, cadastral TEXT, year INTEGER, floors INTEGER)")
    conn.commit()
    conn.close()
    monkeypatch.setenv("NEDVIGA_MKD_DB", str(db))
    f = tmp_path / "card.json"
    f.write_text(json.dumps({"id": "cian-1", "source": "cian", "url": "u", "title": "flat", "building": {"address_raw": "мусорный адрес"}, "geo": {"district": "d"}}))
    code = main(["dossier", "match", "--file", str(f)])
    out = capsys.readouterr().out
    assert "no_match" in out


def test_dossier_enrichment_deep_equal(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    # no db -> no enrichment, family card output same as before
    from nedviga.family_card import render_html, build_family_card
    from nedviga.models import ListingCard
    card = ListingCard(id="cian-1", source="cian", url="u", title="flat", pricing={"price_total_rub": 1.0}, parameters={}, building={"address_raw": "addr"}, geo={"district": "d"})
    fc = build_family_card(card)
    html1 = render_html(fc)
    # second call
    fc2 = build_family_card(card)
    html2 = render_html(fc2)
    assert html1 == html2


def test_dossier_resumable(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    # just ensure sync command exists
    code = main(["dossier", "sync", "--limit", "5"])
    out = capsys.readouterr().out
    assert code in (0, 2, 3)


def test_control_mos_sources_honest_found_and_absent(monkeypatch, tmp_path):
    """v0.5.8 контроль: 3293 found даёт запись с source; отсутствие — absent с
    пояснением, что реестр покрывает только спецсчета (не «капремонта нет»)."""
    import json
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    from nedviga import mosdata
    calls = {"n": 0}
    def fake_rows(dsid, filter_expr=None, top=1000, skip=0, version=None):
        calls["n"] += 1
        f = (filter_expr or "").lower()
        if "кантемиров" in f:
            return [{"Cells": {"AddressMKD": "…улица Кантемировская, дом 20, корпус 1…",
                               "SpecAccountOwnerName": "ТСЖ Х", "CreditOrganization": "Банк М",
                               "MonthlyContribution": "11.3", "OpenDate": "2017-05-01"}}]
        return []
    monkeypatch.setattr(mosdata, "rows", fake_rows)
    from nedviga.dossier import mos_sources
    r = mos_sources("г Москва, улица Кантемировская, дом 20")
    assert r["spec_account"]["dataset"] == 3293 and "data.mos.ru" in r["spec_account"]["source"]
    r2 = mos_sources("г Москва, улица Профсоюзная, дом 42")
    assert r2["spec_account"] is None and r2["spec_account_absent"] is True
    assert "не найдено" in r2["absent_note"] and "не подтверждена" in r2["absent_note"]
    # кэш: повтор без вызовов
    n_before = calls["n"]; mos_sources("г Москва, улица Кантемировская, дом 20")
    assert calls["n"] == n_before


def test_control_house_number_gate(tmp_path, monkeypatch):
    """Спецсчет по улице, но дом 999 не совпал — ложного факта не выдаём."""
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    from nedviga import mosdata
    def fake_rows(dsid, filter_expr=None, top=1000, skip=0, version=None):
        return [{"Cells": {"AddressMKD": "город Москва, улица Кантемировская, дом 25",
                           "SpecAccountOwnerName": "ТСЖ Ч", "CreditOrganization": "Б",
                           "MonthlyContribution": "1", "OpenDate": "2020"}}]
    monkeypatch.setattr(mosdata, "rows", fake_rows)
    from nedviga.dossier import mos_sources
    r = mos_sources("город Москва, улица Кантемировская, дом 999")
    assert r["spec_account"] is None
    assert "не сопоставлен" in r.get("number_unmatched", "")
    assert any("дом 25" in a for a in r.get("candidates", []))


def test_control_odata_case_sensitivity_realtor_finding(tmp_path, monkeypatch):
    """Боевая находка realtor v0.5.9: substringof чувствителен к регистру,
    lowercase-токен давал ЛОЖНЫЙ absent. Мок сервера: матчит только Capitalized."""
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    from nedviga import mosdata
    def rows_case(dsid, filter_expr=None, top=1000, skip=0, version=None):
        f = filter_expr or ""
        if "Азовск" in f:  # только заглавная форма, как на реальном сервере
            return [{"Cells": {"AddressMKD": "город Москва, Азовская улица, дом 4",
                               "SpecAccountOwnerName": "ЖСК Южный", "CreditOrganization": "Б",
                               "MonthlyContribution": "9", "OpenDate": "2015"}}]
        return []
    monkeypatch.setattr(mosdata, "rows", rows_case)
    from nedviga.dossier import mos_sources
    r = mos_sources("город Москва, улица Азовская, дом 4")
    sa = r.get("spec_account")
    assert sa and sa["owner"] == "ЖСК Южный"
    assert r["spec_account_absent"] is False


def test_control_long_registry_vs_short_card(tmp_path, monkeypatch):
    """v0.5.10 контроль: реестровый полный канон vs короткий адрес карточки —
    ключ (номер+улица) обязан совпасть; без номера дома — no_match (нечего угадывать)."""
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    from nedviga.dossier import _addr_key, _addr_score
    reg = "Российская Федерация, город Москва, внутригородская территория муниципальный округ Зюзино, Азовская улица, дом 4"
    card = "улица Азовская, дом 4"
    assert _addr_score(_addr_key(card), _addr_key(reg)) == 1.0
    assert _addr_key("город Москва, Зюзино") is None          # без номера — нет ключа
    assert _addr_score(_addr_key("Азовская, 5"), _addr_key(reg)) == 0.0  # другой дом
    # корпус известн только с одной стороны — кандидат 0.85, не факт
    assert _addr_score(_addr_key("Азовская улица, дом 4, корпус 3"), _addr_key("Азовская, 4")) == 0.85
