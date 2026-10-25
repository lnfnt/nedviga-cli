"""v0.5.1 (the task brief) POI accessibility."""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from .models import ListingCard

_CACHE_DIR = Path(os.environ.get("NEDVIGA_STATE_DIR", str(Path.home() / ".local" / "share" / "nedviga"))) / "poi_cache"
_RATE_LIMIT_SECONDS = 5.0
_last_request: float = 0.0

CATEGORIES = {
    "school": lambda t: t.get("amenity") == "school",
    "kindergarten": lambda t: t.get("amenity") == "kindergarten",
    "grocery": lambda t: t.get("shop") in {"supermarket", "convenience", "grocery"},
    "park": lambda t: t.get("leisure") == "park",
    "clinic": lambda t: t.get("amenity") in {"clinic", "doctor", "hospital"},
}

_OVERPASS_URLS = [  # v0.5.4: публичный зеркалируется; single-endpoint = SPOF (урок realtor 406/timeout)
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]


def _haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _cache_key(lat, lon, radius):
    return hashlib.sha256(f"{lat:.6f}:{lon:.6f}:{radius}".encode()).hexdigest()


def _cache_path(key):
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{key}.json"


def _cache_get(key):
    p = _cache_path(key)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    ts = data.get("_ts")
    if ts:
        dt = datetime.fromisoformat(ts)
        if datetime.now(timezone.utc) - dt > timedelta(days=30):
            return None
    return data.get("payload")


def _cache_set(key, payload):
    p = _cache_path(key)
    p.write_text(json.dumps({"_ts": datetime.now(timezone.utc).isoformat(), "payload": payload},
                            ensure_ascii=False), encoding="utf-8")


def _rate_limit():
    global _last_request
    now = time.time()
    wait = _RATE_LIMIT_SECONDS - (now - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.time()


def _query_overpass(lat, lon, radius):
    # rate limit + cache handled by caller; this does network
    from .net_guard import guarded_get
    q = (f"[out:json];"
         f"(node(around:{radius},{lat},{lon})[amenity~\"school|kindergarten|clinic|doctor|hospital\"];"
         f"node(around:{radius},{lat},{lon})[shop~\"supermarket|convenience|grocery\"];"
         f"node(around:{radius},{lat},{lon})[leisure=park];);out;")
    last_err = None
    for base in _OVERPASS_URLS[:2]:
        url = f"{base}?data={q}"
        _rate_limit()
        try:
            resp = guarded_get(url, timeout=25.0)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001 — деградация видима вызывающему
            last_err = exc
            continue
    raise type(last_err)(f"overpass_all_endpoints_failed: {last_err}")


def _classify(elements, lat, lon, radius_m):
    # returns dict category -> list of (distance, mode)
    result = {cat: [] for cat in CATEGORIES}
    for el in elements or []:
        if el.get("type") != "node":
            continue
        elat = el.get("lat")
        elon = el.get("lon")
        if elat is None or elon is None:
            continue
        tags = el.get("tags") or {}
        dist = _haversine(lat, lon, elat, elon)
        # try walking graph
        mode = "по прямой"
        try:
            from . import graph as _g
            r = _g.route(lat, lon, elat, elon)
            if r is not None:
                meters, provider = r
                dist = meters
                mode = "пешком"
        except Exception:
            pass
        # v0.5.1 контроль качества: радиус запроса = фильтр. Школа в 13.9 км
        # «пешком» при radius-min=15 — шум, а не инфраструктура.
        if dist > radius_m:
            continue
        for cat, pred in CATEGORIES.items():
            if pred(tags):
                result[cat].append((dist, mode))
    out = {}
    for cat, items in result.items():
        if not items:
            out[cat] = {"count": 0, "nearest_m": None, "mode": None}
            continue
        nearest = min(items, key=lambda x: x[0])
        out[cat] = {"count": len(items), "nearest_m": int(round(nearest[0])), "mode": nearest[1]}
    return out


def poi_for_card(card: Any, radius_min: int = 15, offline: Optional[str] = None) -> dict:
    from .models import ListingCard
    c = card if isinstance(card, ListingCard) else ListingCard(**card) if isinstance(card, dict) else None
    if c is None:
        raise TypeError("unsupported card")
    geo = c.geo
    lat = geo.lat if geo else None
    lon = geo.lon if geo else None
    if lat is None or lon is None:
        return {"status": "no_coordinates", "categories": {}}
    radius = max(100, radius_min * 80)  # ~80m/min
    key = _cache_key(lat, lon, radius)
    cached = _cache_get(key)
    if cached is not None:
        payload = cached
    elif offline:
        raw = json.loads(Path(offline).read_text(encoding="utf-8"))
        payload = raw
    else:
        payload = _query_overpass(lat, lon, radius)
        _cache_set(key, payload)
    categories = _classify(payload.get("elements", []) if isinstance(payload, dict) else [], lat, lon, radius)
    return {"status": "ok", "lat": lat, "lon": lon, "radius_m": radius, "categories": categories}


def render_text(result: dict) -> str:
    if result.get("status") == "no_coordinates":
        return "no_coordinates"
    cats = result.get("categories", {})
    lines = ["🏫 Инфраструктура (прямая доступность, кэш на 30 дней):"]
    for cat, info in cats.items():
        if info.get("count", 0) == 0:
            lines.append(f"{cat}: нет данных")
        else:
            mode = info.get("mode") or "по прямой"
            lines.append(f"{cat}: {info['count']} шт., ближайший {info['nearest_m']} м ({mode})")
    return "\n".join(lines)
