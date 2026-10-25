"""Honest walking-distance router to the nearest Moscow metro vestibule.

Public OSRM demo server is used when available; otherwise the module
falls back to a haversine estimate with an urban winding factor.
"""

from __future__ import annotations

import math
from typing import Any

import requests

from .metro_vestibules import get_vestibules

OSRM_BASE_URL = "https://router.project-osrm.org/route/v1"
OSRM_TIMEOUT_SECONDS = 15

WALK_SPEED_M_PER_MIN = 80.0  # 4.8 km/h
URBAN_HAVERSINE_FACTOR = 1.35


def _normalize_station_name(name: str) -> str:
    return name.strip().casefold().replace("ё", "е")


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS-84 points in meters."""
    earth_radius_m = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return earth_radius_m * c


def _duration_minutes(distance_meters: float) -> int:
    """Walking duration at 4.8 km/h (80 m/min), rounded up."""
    return math.ceil(distance_meters / WALK_SPEED_M_PER_MIN)


def _osrm_distance(
    lat1: float, lon1: float, lat2: float, lon2: float, profile: str
) -> float:
    """Ask OSRM for a route distance in meters.

    Raises ``requests.RequestException`` or ``RuntimeError`` on any failure.
    """
    url = (
        f"{OSRM_BASE_URL}/{profile}/{lon1},{lat1};{lon2},{lat2}"
        f"?overview=false&alternatives=false&steps=false"
    )
    # v0.3.5: netguard (egress-guard + breaker) на внешние маршрутизаторы
    from .net_guard import guarded_get

    response = guarded_get(url, timeout=OSRM_TIMEOUT_SECONDS)
    response.raise_for_status()
    payload = response.json()

    if payload.get("code") != "Ok":
        message = payload.get("message", "unknown OSRM error")
        raise RuntimeError(f"OSRM {profile} error: {message}")

    return float(payload["routes"][0]["distance"])


def _route_distance(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> tuple[float, str, bool]:
    """Return (distance_meters, provider, route_verified).

    Provider ladder (v0.2.0, self-contained):
      1. graph_local — встроенный пешеходный граф Москвы (route_verified=True)
      2. cache — ранее посчитанный маршрут (route_verified=True, cached=True)
      3. osrm_foot / osrm_driving_fallback — legacy, только если граф недоступен
         (публичный OSRM не является зависимостью)
      4. haversine_fallback — прикидка
    """
    # 1. Локальный граф
    try:
        from . import graph as _graph_mod

        res = _graph_mod.route(lat1, lon1, lat2, lon2)
        if res is not None:
            meters, provider = res
            return meters, "graph_local", True
    except Exception:
        pass  # граф не установлен/не загрузился — идём дальше по лестнице

    # 2. OSRM (legacy path; не является обязательной инфрой)
    try:
        distance = _osrm_distance(lat1, lon1, lat2, lon2, "foot")
        return distance, "osrm_foot", True
    except Exception:
        try:
            distance = _osrm_distance(lat1, lon1, lat2, lon2, "driving")
            return distance, "osrm_driving_fallback", False
        except Exception:
            pass

    # 3. Haversine
    distance = _haversine(lat1, lon1, lat2, lon2) * URBAN_HAVERSINE_FACTOR
    return distance, "haversine_fallback", False


def walk_route(lat: float, lon: float, target_station: str) -> dict[str, Any]:
    """Route from (lat, lon) to the nearest vestibule of ``target_station``.

    Returns a dict that follows the ``HonestWalkRoute`` schema with a few
    extra operational keys:

    * ``target_station`` – requested station name
    * ``target_vestibule`` – name of the nearest vestibule
    * ``walk_distance_meters`` – integer meters
    * ``walk_duration_minutes`` – integer minutes at 4.8 km/h
    * ``routing_provider`` – e.g. ``osrm_foot``, ``osrm_driving``,
      ``haversine_fallback``
    * ``route_verified`` – ``True`` when OSRM returned a real route
    * ``status`` – ``ok`` or ``degraded``
    * ``reason`` – ``None`` normally, ``STATION_NOT_IN_DIRECTORY`` for unknown
      stations
    """
    vestibules = get_vestibules(target_station)
    if vestibules is None:
        return {
            "target_station": target_station,
            "target_vestibule": None,
            "walk_distance_meters": None,
            "walk_duration_minutes": None,
            "routing_provider": "station_directory",
            "route_verified": False,
            "status": "degraded",
            "reason": "STATION_NOT_IN_DIRECTORY",
        }

    # 0. Кеш: ранее посчитанный маршрут (station-level, до перебора вестибюлей)
    try:
        from . import routing_cache

        cached = routing_cache.get(lat, lon, target_station)
        if cached is not None:
            return {
                "target_station": target_station,
                "target_vestibule": None,
                "walk_distance_meters": int(round(cached)),
                "walk_duration_minutes": _duration_minutes(cached),
                "routing_provider": "cache",
                "route_verified": True,
                "status": "ok",
                "reason": None,
                "cached": True,
            }
    except Exception:
        pass  # кеш не критичен

    best: dict[str, Any] | None = None

    for vestibule_name, vlat, vlon in vestibules:
        distance, provider, verified = _route_distance(lat, lon, vlat, vlon)
        if best is None or distance < best["distance"]:
            best = {
                "distance": distance,
                "provider": provider,
                "verified": verified,
                "vestibule": vestibule_name,
            }

    assert best is not None

    distance_m = int(round(best["distance"]))
    duration_min = _duration_minutes(best["distance"])

    result: dict[str, Any] = {
        "target_station": target_station,
        "target_vestibule": best["vestibule"],
        "walk_distance_meters": distance_m,
        "walk_duration_minutes": duration_min,
        "routing_provider": best["provider"],
        "route_verified": best["verified"],
        "status": "ok",
        "reason": None,
    }
    if not best["verified"]:
        result["fallback_reason"] = "osrm_unavailable"
    # Кешируем успешный маршрут (graph_local / osrm_foot) для будущих запросов
    if best["provider"] in ("graph_local", "osrm_foot"):
        try:
            from . import routing_cache

            routing_cache.put(lat, lon, target_station, float(distance_m),
                              provider=best["provider"])
        except Exception:
            pass
    return result


def honest_overclaim(honest_minutes: int, claimed_minutes: int) -> dict[str, Any]:
    """Compare honest walking time with a platform claim.

    Returns ``{"overclaim_minutes": N, "flag": bool}`` where ``flag`` is
    ``True`` when the honest time exceeds the claimed time by more than
    three minutes.
    """
    overclaim = max(0, honest_minutes - claimed_minutes)
    return {
        "overclaim_minutes": overclaim,
        "flag": honest_minutes > claimed_minutes + 3,
    }
