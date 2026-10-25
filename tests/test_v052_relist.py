"""v0.5.2 (the task brief) relist tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timedelta

import pytest

from nedviga.dedup import detect_relist, signature


def _card(cid, addr="addr", area=50.0, rooms=2, floor=5, floors=10, photo="p.jpg", lat=55.6, lon=37.6, created=None):
    return {
        "id": cid, "source": "cian", "url": f"u{cid}", "title": f"flat {cid}",
        "pricing": {"price_total_rub": 100.0, "price_per_m2_rub": 2.0},
        "parameters": {"rooms": rooms, "area_total_m2": area, "floor": floor, "floors_total": floors},
        "building": {"address_raw": addr},
        "geo": {"lat": lat, "lon": lon, "district": "d"},
        "images": [{"url": f"https://cdn/{photo}"}],
        "created_at": created,
    }


def test_relist_suspect_detected():
    old = [_card("old-1", created="2026-01-01")]
    new = [_card("new-1", created="2026-01-20")]  # same signature, within 45 days
    events = detect_relist(old, new, window_days=45)
    assert len(events) >= 1
    assert "relist_suspect" in str(events).lower() or "relist" in str(events).lower()


def test_relist_no_twin_false():
    old = [_card("old-1")]
    new = [_card("new-1", area=80.0, lat=56.0, lon=38.0)]  # different signature
    events = detect_relist(old, new, window_days=45)
    assert events == [] or len(events) == 0


def test_relist_multi_listing():
    # several ids same signature simultaneously
    cards = [_card("a"), _card("b"), _card("c")]
    from nedviga.dedup import detect_multi_listing
    events = detect_multi_listing(cards)
    assert len(events) >= 1
    assert "multi" in str(events).lower()


def test_relist_verdict_words():
    old = [_card("old-1", created="2026-01-01")]
    new = [_card("new-1", created="2026-01-20")]
    events = detect_relist(old, new, window_days=45)
    text = str(events).lower()
    for bad in ("точно", "гарантированно", "верно"):
        import re
        assert re.search(r"\b" + bad + r"\b", text) is None
