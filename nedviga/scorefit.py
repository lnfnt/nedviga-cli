"""v0.5.4 (the task brief) scorefit."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .models import ListingCard


def _listing(card: Any) -> ListingCard:
    if isinstance(card, ListingCard):
        return card
    if isinstance(card, dict):
        return ListingCard(**card)
    raise TypeError("unsupported card")


def _load_profile(profile) -> dict:
    if isinstance(profile, dict):
        return profile
    if isinstance(profile, str):
        # could be path or profile name
        p = Path(profile)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        # builtin profiles
        from .profiles import get_profile
        try:
            return get_profile(profile)
        except Exception:
            return {}
    return {}


def score_card(card: Any, profile: Any = None) -> dict[str, Any]:
    c = _listing(card)
    prof = _load_profile(profile)
    breakdown = []
    total_weight = 0.0
    total_score = 0.0

    # district
    w = 20.0
    total_weight += w
    expected = prof.get("districts") or prof.get("geo_districts")
    actual = c.geo.district if c.geo else None
    ok = (expected is None) or (actual in (expected if isinstance(expected, list) else [expected]))
    contrib = w if ok else 0.0
    total_score += contrib
    breakdown.append({"criterion": "district", "value": actual, "expected": expected, "weight": w, "contribution": contrib})

    # budget (price <= price_max)
    w = 20.0
    total_weight += w
    price_max = prof.get("price_max")
    price = c.pricing.price_total_rub
    if price_max is None or price is None or price <= price_max:
        ok = True
    else:
        ok = False
    contrib = w if ok else 0.0
    total_score += contrib
    breakdown.append({"criterion": "budget", "value": price, "expected": f"<= {price_max}", "weight": w, "contribution": contrib})

    # rooms
    w = 15.0
    total_weight += w
    exp_rooms = prof.get("rooms")
    actual_rooms = c.parameters.rooms
    ok = (exp_rooms is None) or (actual_rooms == exp_rooms)
    contrib = w if ok else 0.0
    total_score += contrib
    breakdown.append({"criterion": "rooms", "value": actual_rooms, "expected": exp_rooms, "weight": w, "contribution": contrib})

    # metro walk
    w = 15.0
    total_weight += w
    max_walk = prof.get("metro_walk_max")
    walk = None
    if c.geo and c.geo.honest_walk_route:
        walk = c.geo.honest_walk_route.walk_duration_minutes
    elif c.geo and c.geo.cian_claimed_metro:
        walk = c.geo.cian_claimed_metro.claimed_time_minutes
    ok = (max_walk is None) or (walk is None) or (walk <= max_walk)
    contrib = w if ok else 0.0
    total_score += contrib
    breakdown.append({"criterion": "metro_walk", "value": walk, "expected": f"<= {max_walk}", "weight": w, "contribution": contrib})

    # kitchen
    w = 10.0
    total_weight += w
    kitchen_min = prof.get("kitchen_min")
    kitchen = c.parameters.area_kitchen_m2
    ok = (kitchen_min is None) or (kitchen is None) or (kitchen >= kitchen_min)
    contrib = w if ok else 0.0
    total_score += contrib
    breakdown.append({"criterion": "kitchen", "value": kitchen, "expected": f">= {kitchen_min}", "weight": w, "contribution": contrib})

    # floor not first
    w = 10.0
    total_weight += w
    floor = c.parameters.floor
    ok = (floor is None) or (floor != 1)
    contrib = w if ok else 0.0
    total_score += contrib
    breakdown.append({"criterion": "floor_not_first", "value": floor, "expected": "!=1", "weight": w, "contribution": contrib})

    # area total
    w = 10.0
    total_weight += w
    # no explicit expected; give full if present
    ok = c.parameters.area_total_m2 is not None
    contrib = w if ok else 0.0
    total_score += contrib
    breakdown.append({"criterion": "area_total", "value": c.parameters.area_total_m2, "expected": "present", "weight": w, "contribution": contrib})

    score = (total_score / total_weight * 100.0) if total_weight else 0.0
    return {"score": round(score, 2), "breakdown": breakdown}


def score_cards(cards, profile=None) -> list[dict]:
    out = []
    for c in cards:
        r = score_card(c, profile=profile)
        out.append({"id": getattr(c, "id", None), "score": r["score"], "breakdown": r["breakdown"]})
    return out
