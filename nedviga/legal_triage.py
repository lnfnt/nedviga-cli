"""v0.5.0 (the task brief) legal red-flag triage (data-driven)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .models import ListingCard


def _data_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "legal_flags.json"


def load_legal_data() -> dict[str, Any]:
    return json.loads(_data_path().read_text(encoding="utf-8"))


def _listing(card: Any) -> ListingCard:
    if isinstance(card, ListingCard):
        return card
    if isinstance(card, dict):
        return ListingCard(**card)
    if isinstance(card, str):
        import json as _j
        raw = _j.loads(Path(card).read_text(encoding="utf-8"))
        if isinstance(raw, list):
            raw = raw[0]
        if isinstance(raw, dict) and "cards" in raw:
            raw = raw["cards"][0]
        return ListingCard(**raw)
    raise TypeError("unsupported card")


def _card_text(card: ListingCard) -> str:
    parts = [card.title or "", card.description_text or "", card.building.building_type or "",
             card.building.address_raw or "", card.category or ""]
    # include seller type etc
    if card.seller and card.seller.seller_type:
        parts.append(card.seller.seller_type)
    return " ".join(p for p in parts if p)


def _quote(text: str, marker: str) -> str:
    low = text.lower()
    idx = low.find(marker.lower())
    if idx < 0:
        return marker
    start = max(0, idx - 60)
    end = min(len(text), idx + len(marker) + 60)
    snippet = text[start:end].strip()
    # trim to word boundaries roughly
    return snippet if snippet else marker


def _severity(flag: dict, text: str) -> str:
    sev = flag.get("severity", "amber")
    rule = flag.get("severity_rule")
    if not rule:
        return sev
    # conditional
    low = text.lower()
    if rule.get("if_text") in low:
        # find number before 'лет'
        import re
        m = re.search(r"(\d+)\s*лет", low)
        if m:
            years = int(m.group(1))
            threshold = rule.get("threshold_years", 3)
            if years < threshold and rule.get("red_if_under"):
                return "red"
            return rule.get("else", "amber")
    return rule.get("else", sev)


def triage(card: Any) -> dict[str, Any]:
    data = load_legal_data()
    c = _listing(card)
    text = _card_text(c)
    low = text.lower()
    flags = []
    for flag in data.get("flags", []):
        markers = flag.get("markers", [])
        found_marker = None
        for m in markers:
            if m.lower() in low:
                found_marker = m
                break
        if not found_marker:
            continue
        text_basis = _quote(text, found_marker)
        sev = _severity(flag, text)
        flags.append({
            "code": flag["code"],
            "label": flag.get("title"),
            "severity": sev,
            "text_basis": text_basis,
            "check": flag.get("check"),
        })
    return {
        "flags": flags,
        "disclaimer": data.get("disclaimer"),
        "legal_data_version": data.get("version"),
        "approved_by": data.get("approved_by"),
    }
