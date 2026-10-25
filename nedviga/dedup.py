"""v0.5.2 (the task brief) dedup."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Optional
from datetime import datetime, timedelta

from .models import ListingCard


def _listing(card: Any) -> ListingCard:
    if isinstance(card, ListingCard):
        return card
    if isinstance(card, dict):
        return ListingCard(**card)
    raise TypeError("unsupported card")


def _norm_addr(addr: Optional[str]) -> str:
    if not addr:
        return ""
    return " ".join(str(addr).lower().split())


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


def _first_photo_url(card: ListingCard) -> str:
    imgs = card.images or []
    if not imgs:
        return ""
    url = getattr(imgs[0], "url", None) or ""
    url = str(url).strip().lower()
    # normalize: strip query
    if "?" in url:
        url = url.split("?")[0]
    if "#" in url:
        url = url.split("#")[0]
    return url


def _layout(c: ListingCard):
    p = c.parameters
    area = p.area_total_m2
    rooms = p.rooms
    floor = p.floor
    floors = p.floors_total
    return rooms, area, floor, floors


def _geo_or_address_match(a: ListingCard, b: ListingCard) -> tuple[bool, str]:
    ca = _coords(a); cb = _coords(b)
    if ca is not None and cb is not None:
        if _haversine(ca, cb) <= 120:
            return True, "geo_anchor"
    # address canonical
    aa = _norm_addr(a.building.address_raw if a.building else None)
    ab = _norm_addr(b.building.address_raw if b.building else None)
    if aa and aa == ab:
        return True, "address_canonical"
    # same complex
    ca_c = a.building.complex if a.building else None
    cb_c = b.building.complex if b.building else None
    if ca_c and ca_c == cb_c:
        return True, "address_canonical"
    return False, ""


def _layout_match(a: ListingCard, b: ListingCard) -> bool:
    pa = a.parameters; pb = b.parameters
    if pa.rooms is not None and pb.rooms is not None and pa.rooms != pb.rooms:
        return False
    # area ±3%
    if pa.area_total_m2 is not None and pb.area_total_m2 is not None:
        if pa.area_total_m2 == 0:
            return False
        diff = abs(pa.area_total_m2 - pb.area_total_m2) / max(pa.area_total_m2, pb.area_total_m2)
        if diff > 0.03:
            return False
    # floor ±1
    if pa.floor is not None and pb.floor is not None and abs(pa.floor - pb.floor) > 1:
        return False
    # floors_total ±1
    if pa.floors_total is not None and pb.floors_total is not None and abs(pa.floors_total - pb.floors_total) > 1:
        return False
    return True


def _photo_match(a: ListingCard, b: ListingCard) -> bool:
    ua = _first_photo_url(a)
    ub = _first_photo_url(b)
    return bool(ua) and ua == ub


def signature(card: Any) -> tuple:
    c = _listing(card)
    ca = _coords(c)
    geo_key = (round(ca[0], 3), round(ca[1], 3)) if ca else None
    addr = _norm_addr(c.building.address_raw if c.building else None)
    p = c.parameters
    photo = _first_photo_url(c)
    return (geo_key, addr, p.rooms, p.area_total_m2, p.floor, p.floors_total, photo)


def _candidate(a: ListingCard, b: ListingCard) -> tuple[bool, list[str]]:
    signals = []
    ok, sig = _geo_or_address_match(a, b)
    if ok:
        signals.append(sig)
    layout_ok = _layout_match(a, b)
    if layout_ok:
        signals.append("layout")
    photo_ok = _photo_match(a, b)
    if photo_ok:
        signals.append("photo_url")
    # candidate requires geo/address + layout
    if ok and layout_ok:
        return True, signals
    return False, signals


def dedup_cards(cards: list, strict: bool = False) -> list[dict]:
    lst = [_listing(c) for c in cards]
    n = len(lst)
    # union-find
    parent = list(range(n))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    pair_signals: dict[tuple[int,int], list[str]] = {}
    for i in range(n):
        for j in range(i+1, n):
            cand, sigs = _candidate(lst[i], lst[j])
            if cand:
                if strict and len(sigs) < 2:
                    continue
                union(i, j)
                pair_signals[(i, j)] = sigs

    # build groups
    groups_map: dict[int, list[int]] = {}
    for i in range(n):
        groups_map.setdefault(find(i), []).append(i)
    groups = []
    for root, idxs in groups_map.items():
        if len(idxs) < 2:
            continue
        # collect signals across pairs in group
        sigs_set = set()
        for (i, j), s in pair_signals.items():
            if i in idxs and j in idxs:
                sigs_set.update(s)
        prices = [c.pricing.price_total_rub for c in [lst[i] for i in idxs] if c.pricing.price_total_rub is not None]
        price_range = [min(prices), max(prices)] if prices else None
        groups.append({
            "cards": [lst[i].id for i in idxs],
            "signals": sorted(sigs_set),
            "price_range": price_range,
            "reason": "кандидат-дубль: " + ", ".join(sorted(sigs_set)),
        })
    return groups


def _created_date(card):
    if isinstance(card, dict):
        v = card.get("created_at") or card.get("created") or (card.get("seller") or {}).get("created_at")
    else:
        v = getattr(card, "created_at", None)
        if v is None and getattr(card, "seller", None) is not None:
            v = getattr(card.seller, "created_at", None)
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def detect_relist(old_cards, new_cards, window_days: int = 45) -> list[dict]:
    old_raw = list(old_cards)
    new_raw = list(new_cards)
    old = [_listing(c) for c in old_raw]
    new = [_listing(c) for c in new_raw]
    events = []
    for oi, oc in enumerate(old):
        for ni, nc in enumerate(new):
            if nc.id == oc.id:
                continue
            cand, sigs = _candidate(oc, nc)
            if not cand:
                continue
            old_date = _created_date(old_raw[oi])
            new_date = _created_date(new_raw[ni])
            if old_date is not None and new_date is not None:
                if (new_date - old_date).days > window_days or (new_date - old_date).days < 0:
                    continue
            events.append({"type": "relist_suspect", "old_id": oc.id, "new_id": nc.id,
                           "reason": "подпись совпадает, окно {} дней".format(window_days)})
    seen = set()
    out = []
    for e in events:
        key = (e["old_id"], e["new_id"])
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def detect_multi_listing(cards) -> list[dict]:
    lst = [_listing(c) for c in cards]
    # group by signature
    groups: dict[Any, list] = {}
    for c in lst:
        groups.setdefault(signature(c), []).append(c)
    events = []
    for sig, grp in groups.items():
        if len(grp) >= 2:
            events.append({"type": "multi_listing", "cards": [c.id for c in grp],
                           "reason": "несколько id с одинаковой подписью"})
    return events
