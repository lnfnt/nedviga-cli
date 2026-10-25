"""v0.4.8 (the task brief) F-57: completeness/missing_fields tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nedviga.models import ListingCard


def test_missing_fields_complete_card():
    card = ListingCard(
        id="cian-1",
        source="cian",
        url="u",
        pricing={"price_total_rub": 100.0},
        parameters={"rooms": 2, "area_total_m2": 50.0, "floor": 5, "floors_total": 10},
        building={"address_raw": "addr"},
        geo={"district": "d"},
    )
    assert getattr(card, "missing_fields", None) == []


def test_missing_fields_incomplete():
    card = ListingCard(id="cian-1", source="cian", url="u")
    mf = getattr(card, "missing_fields", None)
    assert isinstance(mf, list)
    assert "price_total_rub" in mf
    assert "address_raw" in mf


def test_missing_fields_serialized():
    card = ListingCard(id="cian-1", source="cian", url="u")
    data = card.model_dump(mode="json")
    assert "missing_fields" in data


def test_family_card_shows_missing(tmp_path):
    # if family_card renders missing line
    from nedviga.family_card import render_html, build_family_card
    card = ListingCard(id="cian-1", source="cian", url="u")
    fc = build_family_card(card)
    html = render_html(fc)
    assert "Не хватает данных" in html or "missing" in html.lower()


def test_missing_deterministic():
    a = ListingCard(id="cian-1", source="cian", url="u")
    b = ListingCard(id="cian-1", source="cian", url="u")
    assert a.missing_fields == b.missing_fields
