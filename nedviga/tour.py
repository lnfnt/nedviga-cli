"""v0.5.1 (the task brief) tour routing."""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from .models import ListingCard
from . import pipeline


def _load_cards(path: Optional[str] = None, project: Optional[str] = None) -> list[ListingCard]:
    cards: list[ListingCard] = []
    if project:
        from .projects import project_cards
        for cid in project_cards(project):
            cards.append(ListingCard(id=cid, source="cian", url=""))
    if path:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            if "cards" in raw and isinstance(raw["cards"], list):
                raw = raw["cards"]
            elif "data" in raw:
                d = raw["data"]
                raw = d if isinstance(d, list) else ([d] if isinstance(d, dict) else [])
            else:
                raw = [raw]
        if not isinstance(raw, list):
            raw = [raw]
        for x in raw:
            if isinstance(x, dict):
                cards.append(ListingCard(**x))
            elif isinstance(x, ListingCard):
                cards.append(x)
    return cards


def _coords(c: ListingCard):
    g = c.geo
    if g and g.lat is not None and g.lon is not None:
        return (g.lat, g.lon)
    return None


def _haversine(a, b):
    R = 6371000.0
    phi1 = math.radians(a[0]); phi2 = math.radians(b[0])
    dphi = math.radians(b[0]-a[0]); dl = math.radians(b[1]-a[1])
    x = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dl/2)**2
    return 2*R*math.asin(math.sqrt(x))


def _pair_distance(a: ListingCard, b: ListingCard):
    ca = _coords(a); cb = _coords(b)
    if ca is None or cb is None:
        return None, True  # unknown -> straight estimate
    # try graph
    try:
        from . import graph as _g
        r = _g.route(ca[0], ca[1], cb[0], cb[1])
        if r is not None:
            meters, provider = r
            return float(meters), False
    except Exception:
        pass
    return _haversine(ca, cb), True


def _allowed_ids(all_flag: bool):
    if all_flag:
        return None
    try:
        items = pipeline.list_items()
    except Exception:
        return None
    allowed = set()
    for it in items:
        if it.get("status") in {"shortlist", "call_planned"}:
            allowed.add(it.get("card_id"))
    return allowed if allowed else None


def _filter(cards, all_flag):
    allowed = _allowed_ids(all_flag)
    if allowed is None or all_flag:
        return cards
    return [c for c in cards if c.id in allowed]


def _order(cards):
    if len(cards) <= 1:
        return list(cards)
    # deterministic start: sorted by id
    remaining = sorted(cards, key=lambda c: c.id)
    # greedy nearest neighbor from first
    route = [remaining.pop(0)]
    while remaining:
        last = route[-1]
        # choose nearest by distance; tie-break by id
        best = min(remaining, key=lambda c: (_pair_distance(last, c)[0] if _pair_distance(last, c)[0] is not None else float("inf"), c.id))
        remaining.remove(best)
        route.append(best)
    # 2-opt
    def total(r):
        s = 0.0
        for i in range(len(r)-1):
            d, _ = _pair_distance(r[i], r[i+1])
            s += d if d is not None else 0.0
        return s
    improved = True
    # limit iterations for determinism
    iters = 0
    while improved and iters < 100:
        improved = False
        iters += 1
        for i in range(1, len(route)-1):
            for j in range(i+1, len(route)):
                new = route[:i] + list(reversed(route[i:j+1])) + route[j+1:]
                if total(new) + 1e-9 < total(route):
                    route = new
                    improved = True
    return route


def build_tour(cards, slot_min=45, start_time="10:00", all_flag=False):
    cards = _filter(cards, all_flag)
    cards = cards[:6]
    ordered = _order(cards)
    slots = []
    t = datetime.strptime(start_time, "%H:%M")
    warnings = []
    for c in ordered:
        ca = None
        if len(slots) > 0:
            prev = ordered[len(slots)-1]
            dist, straight = _pair_distance(prev, c)
            if dist is None:
                warnings.append(f"между {prev.id} и {c.id} — координаты неизвестны, близость не гарантирована")
            elif straight:
                warnings.append(f"между {prev.id} и {c.id} — только по прямой {dist/1000:.1f} км, реальная поездка дольше — проверьте маршрутом")
        slots.append({"time": t.strftime("%H:%M"), "card": c})
        t = t + timedelta(minutes=slot_min)
    return {"slots": slots, "warnings": warnings, "count": len(slots)}


def render_text(tour, fmt="telegram"):
    slots = tour["slots"]
    warnings = tour["warnings"]
    lines = []
    for s in slots:
        c = s["card"]
        district = c.geo.district if c.geo else ""
        metro = ""
        if c.geo and c.geo.cian_claimed_metro:
            metro = c.geo.cian_claimed_metro.station or ""
        loc = f"{district}, {metro}".strip(", ")
        lines.append(f"{s['time']} {c.title or c.id} ({loc})")
    if warnings:
        lines.append("")
        for w in warnings:
            lines.append(f"⚠ {w}")
    # build timeline with arrows
    timeline = " → ".join(f"{s['time']} {s['card'].title or s['card'].id}" for s in slots)
    if fmt == "md":
        out = ["# Маршрут показов", "", timeline, ""]
        for s in slots:
            c = s["card"]
            out.append(f"- {s['time']} {c.title or c.id}")
        if warnings:
            out.append("")
            for w in warnings:
                out.append(f"- ⚠ {w}")
        return "\n".join(out)
    # telegram compact
    out = [timeline]
    for w in warnings:
        out.append(f"⚠ {w}")
    return "\n".join(out)
