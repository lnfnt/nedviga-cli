"""v0.4.9 (the task brief) F-10b: bargain analysis."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Optional

from .models import ListingCard


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


def _ppm2(c: ListingCard) -> Optional[float]:
    v = c.pricing.price_per_m2_rub
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    h = (n - 1) * q
    lo = int(h // 1)
    hi = min(lo + 1, n - 1)
    frac = h - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


import re as _re

def _complex_name(card: Any) -> Optional[str]:
    try:
        c = card if not isinstance(card, str) else None
    except Exception:
        c = None
    # try building.complex
    b = getattr(card, "building", None) if not isinstance(card, dict) else card.get("building")
    if isinstance(b, dict):
        cx = b.get("complex")
    else:
        cx = getattr(b, "complex", None) if b else None
    if cx:
        return str(cx).strip().lower().replace("«", "").replace("»", "").replace('"', "")
    # title/address
    text = ""
    if isinstance(card, dict):
        text = (card.get("title") or "") + " " + ((card.get("building") or {}).get("address_raw") or "")
    else:
        text = (getattr(card, "title", "") or "") + " " + ((getattr(card.building, "address_raw", "") or "") if getattr(card, "building", None) else "")
    m = _re.search(r"ЖК\s*[«\"]([^»\"]+)[»\"]", text, _re.IGNORECASE)
    if m:
        return m.group(1).strip().lower()
    m = _re.search(r"ЖК\s+([A-Za-zА-Яа-я0-9\-]+)", text, _re.IGNORECASE)
    if m:
        return m.group(1).strip().lower()
    return None


def analyze(target: Any, corpus_paths: Iterable[str], district: Optional[str] = None,
           rooms: Optional[int] = None, by_complex: bool = False) -> dict[str, Any]:
    if isinstance(target, str):
        t = _load_cards(target)[0]
    elif isinstance(target, ListingCard):
        t = target
    else:
        t = _listing(target)
    cards: list[ListingCard] = []
    for p in corpus_paths:
        cards.extend(_load_cards(p))

    t_district = district or (t.geo.district if t.geo else None)
    t_rooms = rooms if rooms is not None else t.parameters.rooms
    t_complex = _complex_name(t) if by_complex else None

    group = []
    for c in cards:
        cd = c.geo.district if c.geo else None
        cr = c.parameters.rooms
        if not by_complex:
            if t_district is not None and cd != t_district:
                continue
        else:
            cc = _complex_name(c)
            if t_complex is not None and cc != t_complex:
                continue
        if t_rooms is not None and cr is not None and abs(cr - t_rooms) > 1:
            continue
        p = _ppm2(c)
        if p is not None:
            group.append(p)

    n = len(group)
    if n < 20:
        basis = (f"по ЖК «{t_complex}»" if (by_complex and t_complex) else (f"по {t_district}" if t_district else "по группе"))
        return {
            "ok": False,
            "reason": "insufficient_sample",
            "n": n,
            "required": 20,
            "district": t_district,
            "rooms": t_rooms,
            "group_basis": basis + f" (n={n})",
        }

    s = sorted(group)
    median = _percentile(s, 0.5)
    p25 = _percentile(s, 0.25)
    p75 = _percentile(s, 0.75)
    target_price = _ppm2(t)
    deviation = ((target_price - median) / median * 100.0) if median else 0.0

    args_list = []
    if target_price is not None:
        if target_price > median:
            args_list.append(f"медиана рынка этой группы {median:,.0f} ₽/м², объект на {deviation:.1f}% дороже — в торге уместно ссылаться на P25={p25:,.0f}")
        else:
            args_list.append(f"медиана рынка этой группы {median:,.0f} ₽/м², объект на {abs(deviation):.1f}% дешевле — аргументов для торга меньше")
    args_list.append(f"P25={p25:,.0f}, P75={p75:,.0f} — ориентир для переговоров")
    args_list.append("ссылайтесь на реальные аналоги из корпуса")
    if len(args_list) < 3:
        args_list.append("проверьте состояние и документы")
    args_list = args_list[:5]

    basis = (f"по ЖК «{t_complex}»" if (by_complex and t_complex) else (f"по {t_district}" if t_district else "по группе"))
    return {
        "ok": True,
        "n": n,
        "district": t_district,
        "rooms": t_rooms,
        "group_basis": basis + f" (n={n})",
        "median": median,
        "p25": p25,
        "p75": p75,
        "target_price_per_m2": target_price,
        "deviation_percent": deviation,
        "arguments": args_list,
        "disclaimer": "оценка по {} объявлениям площадки Cian, не официальная статистика".format(n),
    }


def render_text(result: dict[str, Any]) -> str:
    if not result.get("ok"):
        return f"insufficient_sample: n={result.get('n')}"
    lines = []
    if result.get("group_basis"):
        lines.append(result["group_basis"])
    lines.append(f"медиана: {result['median']:,.0f} ₽/м²".replace(",", " "))
    lines.append(f"P25: {result['p25']:,.0f} ₽/м²".replace(",", " "))
    lines.append(f"P75: {result['p75']:,.0f} ₽/м²".replace(",", " "))
    lines.append(f"отклонение: {result['deviation_percent']:+.1f}%")
    lines.append("аргументы:")
    for a in result["arguments"]:
        lines.append(f"• {a}")
    lines.append(result["disclaimer"])
    return "\n".join(lines)
