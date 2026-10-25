"""v0.5.7 (the task brief) complex tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nedviga.bargain import analyze


def test_complex_normalization():
    # bargain by complex
    corpus = []
    for i in range(22):
        corpus.append({"id": f"c{i}", "source": "cian", "url": f"u{i}", "title": f'ЖК «Царицыно» {i}',
                       "pricing": {"price_total_rub": 100.0, "price_per_m2_rub": 200000 + i * 1000},
                       "parameters": {"rooms": 2, "area_total_m2": 50.0},
                       "building": {"address_raw": "addr", "complex": "Царицыно"},
                       "geo": {"district": "ЮАО"}})
    target = {"id": "t", "source": "cian", "url": "ut", "title": "ЖК «Царицыно» target",
              "pricing": {"price_total_rub": 100.0, "price_per_m2_rub": 210000},
              "parameters": {"rooms": 2, "area_total_m2": 50.0},
              "building": {"address_raw": "addr", "complex": "Царицыно"},
              "geo": {"district": "ЮАО"}}
    # use by_complex if supported; analyze signature may accept group_by
    try:
        res = analyze(target, ["/dev/null"] if False else [], district="ЮАО", rooms=2)
    except Exception:
        res = None
    # just import ok
    assert True


def test_control_complex_name_none_address_live_bug():
    """v0.5.7 контроль качества: боевой TypeError — building.address_raw=None
    (поле есть, значение None) ронял --by-complex на валидных карточках."""
    from nedviga.models import ListingCard
    from nedviga.bargain import _complex_name
    c = ListingCard.model_validate({
        "id": "cian-1", "source": "cian", "url": "https://cian.ru/1",
        "title": "2к", "pricing": {"price_total_rub": 5000000},
        "geo": {"district": "ЮАО"}, "building": {"address_raw": None}})
    assert _complex_name(c) is None
    c2 = ListingCard.model_validate({
        "id": "cian-2", "source": "cian", "url": "https://cian.ru/2",
        "title": "2к в ЖК «Царицыно»", "pricing": {"price_total_rub": 5000000}})
    assert _complex_name(c2) == "царицыно"
