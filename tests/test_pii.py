# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 lnfnt <lnfnt@proton.me>

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


def test_mask_phones_bare_mobile_masked():
    assert mask_phones("звоните 9161234567") == "звоните +7 *** ***-**-**"


def test_mask_phones_bare_mobile_not_masked_without_nine():
    assert mask_phones("1234567890") == "1234567890"


def test_mask_phones_price_intact_bare():
    assert mask_phones("цена 1234567890 руб") == "цена 1234567890 руб"
