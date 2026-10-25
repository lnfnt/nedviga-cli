"""v0.5.2 (the task brief) pluggable source adapters."""
from __future__ import annotations

from typing import Any, Callable, Optional, Protocol, runtime_checkable

_REGISTRY: list[Any] = []


@runtime_checkable
class SourceAdapter(Protocol):
    id: str
    site_patterns: list[str]
    status: str

    def parse_listing(self, payload: Any) -> Any: ...
    def search_url(self, params: dict) -> str: ...
    def fetch(self, params: dict) -> list: ...


def register_source(adapter: Any) -> None:
    _REGISTRY.append(adapter)


def list_sources() -> list[dict[str, Any]]:
    out = []
    for a in _REGISTRY:
        out.append({
            "id": getattr(a, "id", None),
            "site_patterns": getattr(a, "site_patterns", []),
            "status": getattr(a, "status", "experimental"),
        })
    return out


class CianAdapter:
    id = "cian"
    site_patterns = ["cian.ru"]
    status = "ready"

    def parse_listing(self, payload):
        from .models import ListingCard
        if isinstance(payload, dict):
            return ListingCard(**payload)
        return payload

    def search_url(self, params):
        return "https://www.cian.ru/cat.php"

    def fetch(self, params):
        from .cian_live import search
        return search(**params) if params else []


# register default
register_source(CianAdapter())
