"""v0.5.0 (the task brief) call-sheet."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .legal_triage import triage
from .models import ListingCard
from .pii import PHONE_MASK


def _listing(card: Any) -> ListingCard:
    if isinstance(card, ListingCard):
        return card
    if isinstance(card, dict):
        return ListingCard(**card)
    raise TypeError("unsupported card")


def _load_cards(path: str) -> list[ListingCard]:
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
    return [_listing(x) for x in raw if isinstance(x, (dict, ListingCard))]


def build_callsheet(cards: list[ListingCard], with_contacts: bool = False) -> str:
    lines: list[str] = []
    for c in cards:
        t = triage(c)
        phones = [str(p) for p in (c.seller.phones if c.seller else []) if str(p or "").strip()]
        if with_contacts:
            phone_str = " · ".join(phones) if phones else "нет"
        else:
            phone_str = " · ".join(PHONE_MASK for _ in phones) if phones else "нет"
        lines.append(f"📞 {c.title or c.id}")
        lines.append(f"Телефон: {phone_str}")
        lines.append(f"Цена: {c.pricing.price_total_rub} ₽ ({c.pricing.price_per_m2_rub} ₽/м²)")
        lines.append(f"Район: {c.geo.district or 'нет данных'}")
        lines.append("Вопросы:")
        lines.append("• Почему цена отличается от медианы группы? (если применимо)")
        lines.append("• История цены объявления?")
        lines.append("• Кто собственник, сколько владеет?")
        lines.append("• Есть обременения/аресты?")
        lines.append("• Альтернатива? Ключи/показы в будни?")
        lines.append("• Торг возможен?")
        if t["flags"]:
            lines.append("⚠ Аккуратно: " + ", ".join(f["code"] for f in t["flags"]) + " — уточнить статус")
        lines.append("")
    return "\n".join(lines).strip()


def render_telegram(text: str) -> str:
    return text
