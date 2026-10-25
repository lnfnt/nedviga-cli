"""v0.5.6 (the task brief) eco proxy."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .poi import _haversine, _cache_get, _cache_key, _query_overpass, poi_for_card


def _classify_eco(elements, lat, lon):
    categories = {
        "highway": [],
        "rail": [],
        "aerodrome": [],
        "industrial": [],
    }
    for el in elements or []:
        if el.get("type") != "node":
            continue
        elat = el.get("lat"); elon = el.get("lon")
        if elat is None or elon is None:
            continue
        tags = el.get("tags") or {}
        dist = _haversine(lat, lon, elat, elon)
        hw = tags.get("highway")
        if hw in {"motorway", "trunk"}:
            categories["highway"].append(dist)
        if tags.get("railway") in {"station"} or tags.get("amenity") == "railway_station":
            categories["rail"].append(dist)
        if tags.get("aeroway") == "aerodrome" or tags.get("amenity") == "aerodrome":
            categories["aerodrome"].append(dist)
        if tags.get("landuse") == "industrial":
            categories["industrial"].append(dist)
    out = {}
    for cat, dists in categories.items():
        if not dists:
            out[cat] = {"count": 0, "nearest_m": None}
        else:
            out[cat] = {"count": len(dists), "nearest_m": int(round(min(dists)))}
    return out


def eco_for_card(card, radius_min=15, offline=None):
    from .models import ListingCard
    c = card if isinstance(card, ListingCard) else ListingCard(**card) if isinstance(card, dict) else None
    if c is None:
        raise TypeError("unsupported card")
    geo = c.geo
    lat = geo.lat if geo else None
    lon = geo.lon if geo else None
    if lat is None or lon is None:
        return {"status": "no_coordinates", "categories": {}}
    radius = max(100, radius_min * 80)
    key = _cache_key(lat, lon, radius)
    cached = _cache_get(key)
    if cached is not None:
        payload = cached
    elif offline:
        import json
        payload = json.loads(Path(offline).read_text(encoding="utf-8"))
    else:
        payload = _query_overpass(lat, lon, radius)
        from .poi import _cache_set
        _cache_set(key, payload)
    cats = _classify_eco(payload.get("elements", []) if isinstance(payload, dict) else [], lat, lon)
    return {"status": "ok", "categories": cats}


def render_text(result: dict) -> str:
    if result.get("status") == "no_coordinates":
        return "no_coordinates"
    cats = result.get("categories", {})
    lines = []
    names = {"highway": "шоссе", "rail": "ж/д", "aerodrome": "аэропорт", "industrial": "промзона"}
    for cat, info in cats.items():
        if info.get("count", 0) == 0:
            lines.append(f"{names[cat]}: нет данных")
        else:
            lines.append(f"{names[cat]}: {info['nearest_m']} м (по прямой)")
    lines.append("это проксимити-прокси по OSM, НЕ замер уровня шума; официальный источник — data.mos.ru (ждёт токен владельца)")
    return "\n".join(lines)
