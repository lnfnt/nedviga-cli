"""nedviga-cli: Python SDK and CLI for Moscow secondary real estate."""

from __future__ import annotations

from .cian_card import ParseError, parse_card
from .cian_live import get_card, search
from .errors import ChallengeError, FetchError
from .export_html import export_html
from .geo_routing import honest_overclaim, walk_route

__version__ = "0.1.1"


def walk_distance(
    lat: float,
    lon: float,
    target_station: str,
    *,
    claimed_time: int | None = None,
) -> dict:
    """Honest walking distance to the nearest vestibule of ``target_station``.

    Returns a typed dict with ``honest_walk_route`` (a
    :class:`nedviga.models.HonestWalkRoute` instance) and, when
    ``claimed_time`` is provided, ``honest_overclaim``.
    """
    route = walk_route(lat, lon, target_station)
    data: dict = {"honest_walk_route": route}
    if claimed_time is not None and route.get("status") == "ok":
        data["honest_overclaim"] = honest_overclaim(
            int(route["walk_duration_minutes"]), int(claimed_time)
        )
    return data


__all__ = [
    "__version__",
    "search",
    "get_card",
    "export_html",
    "walk_distance",
    "parse_card",
    "ChallengeError",
    "FetchError",
    "ParseError",
]
