"""Tests for PII sanitisers (F-01)."""

from __future__ import annotations

from nedviga.pii import mask_phones, mask_phones_in_obj


def test_mask_phones_replaces_russian_mobile():
    assert mask_phones("Call +7 999 123-45-67") == "Call +7 *** ***-**-**"


def test_mask_phones_in_obj_recursively():
    obj = {"a": ["tel. 89991234567", "ok"], "b": {"note": "+7(999)123-45-67"}}
    out = mask_phones_in_obj(obj)
    assert out["a"] == ["tel. +7 *** ***-**-**", "ok"]
    assert out["b"]["note"] == "+7 *** ***-**-**"


def test_mask_phones_leaves_prices_intact():
    assert mask_phones("16 000 000 ₽") == "16 000 000 ₽"
