"""P3-3 acceptance (2026-10-20): fail-closed цена.

Негативка обязательна: до фикса карточка без цены молча уходила с None
(тест price_missing_appends_drift на старом коде падает — фолбэка и журнала нет).
"""
import json
import os

import pytest

from nedviga.price_guard import drift_file, price_from_title, record_price_drift


def test_title_price_full_form():
    assert price_from_title("3-к квартира, 75 м², 12 500 000 ₽") == 12_500_000.0


def test_title_price_nbsp_and_rub():
    assert price_from_title("Студия, 12500000 руб. в центре") == 12_500_000.0


def test_title_without_currency_is_not_price():
    # этажи/комнаты без денежного якоря не цена
    assert price_from_title("2-к квартира, 45 м², 5 из 12 эт.") is None


def test_title_empty_none():
    assert price_from_title(None) is None
    assert price_from_title("") is None


def test_record_drift_appends_line(tmp_path, monkeypatch):
    f = tmp_path / "drift.jsonl"
    monkeypatch.setenv("NEDVIGA_DRIFT_FILE", str(f))
    record_price_drift("cian-123", "https://www.cian.ru/x", "без цены")
    record_price_drift("cian-124", None, None)
    lines = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    assert lines[0]["card_id"] == "cian-123"
    assert lines[1]["event"] == "price_missing_quarantined"
    assert "ts" in lines[0]


def _minimal_card_html(title: str, with_price: bool) -> str:
    price_block = (
        "<span itemprop='price' content='8500000'>8 500 000 ₽</span>"
        if with_price else ""
    )
    return f"""
    <html><head><title>{title}</title></head><body>
    <h1 data-name='OfferTitle'>{title}</h1>
    {price_block}
    <div data-name='OfferTitle'>{title}</div>
    <script>window._offersData = {{"offers":[{{"cianId": 123456, "category": "flatSale"}}]}};</script>
    </body></html>"""


@pytest.mark.parametrize("with_price,title", [(True, "3-к квартира, 75 м²"),
                                              (False, "2-к квартира, 8 700 000 ₽")])
def test_card_price_resolved_no_drift(tmp_path, monkeypatch, with_price, title):
    f = tmp_path / "drift.jsonl"
    monkeypatch.setenv("NEDVIGA_DRIFT_FILE", str(f))
    from nedviga.cian_card import parse_card
    card = parse_card(_minimal_card_html(title, with_price))
    expected = 8_500_000.0 if with_price else 8_700_000.0
    assert card.pricing.price_total_rub == expected
    assert not f.exists()  # тишина допустима только когда цена найдена


def test_price_missing_appends_drift(tmp_path, monkeypatch):
    f = tmp_path / "drift.jsonl"
    monkeypatch.setenv("NEDVIGA_DRIFT_FILE", str(f))
    from nedviga.cian_card import parse_card
    card = parse_card(
        _minimal_card_html("2-к квартира, 45 м²", with_price=False))
    assert card.pricing.price_total_rub is None  # не выдумываем цену
    assert f.exists()  # но и не молчим: карантин-событие записано
    entry = json.loads(f.read_text(encoding="utf-8").splitlines()[0])
    assert entry["card_id"] == "cian-123456"
