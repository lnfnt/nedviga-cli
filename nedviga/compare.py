"""v0.4.9 (the task brief) F-12: comparison matrix."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional

from .models import ListingCard


def _listing(card: Any) -> ListingCard:
    if isinstance(card, ListingCard):
        return card
    if isinstance(card, dict):
        return ListingCard(**card)
    raise TypeError("unsupported card")




from .family_card import _human as _decoat  # v0.4.9 контроль качества: тот же контракт очистки


def _md_cell(s):
    return _decoat(str(s)).replace("|", "\|")


def _html_cell(s):
    from html import escape
    return escape(_decoat(str(s)))


def load_cards(path: str, ids: Optional[str] = None) -> list[ListingCard]:
    raw = __import__("json").loads(Path(path).read_text(encoding="utf-8"))
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
    cards = [_listing(x) for x in raw if isinstance(x, (dict, ListingCard))]
    if ids:
        wanted = {x.strip() for x in ids.split(",") if x.strip()}
        cards = [c for c in cards if c.id in wanted]
    return cards


def _ppm2(c: ListingCard) -> float:
    v = c.pricing.price_per_m2_rub
    return float(v) if v is not None else float("inf")


def _walk(c: ListingCard) -> str:
    w = c.geo.honest_walk_route
    if w and w.walk_duration_minutes is not None:
        return f"{int(w.walk_duration_minutes)} мин ({w.walk_distance_meters} м)"
    claimed = c.geo.cian_claimed_metro.claimed_time_minutes if c.geo.cian_claimed_metro else None
    if claimed is not None:
        return f"заявлено {claimed} мин"
    return "нет данных"


def _missing(c: ListingCard) -> str:
    mf = getattr(c, "missing_fields", None) or []
    return ", ".join(mf) if mf else ""


def _risk_str(c: ListingCard) -> str:
    try:
        from .risk import score_card
        r = score_card(c)
        if r.get("risk_score", 0) >= 0.5:
            return "⚠ risk"
    except Exception:
        pass
    return ""


def sort_cards(cards: list[ListingCard]) -> list[ListingCard]:
    return sorted(cards, key=_ppm2)


def _best_worst(cards: list[ListingCard]) -> tuple[Optional[str], Optional[str]]:
    if not cards:
        return None, None
    s = sort_cards(cards)
    return s[0].id, s[-1].id


def render_markdown(cards: list[ListingCard]) -> str:
    if not cards:
        return "empty_input"
    cards = sort_cards(cards)
    best, worst = _best_worst(cards)
    lines = ["| # | Адрес/ID | Цена | ₽/м² | Район | Этаж | Пешком | Площадь | Серия/год | ⚠ |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for i, c in enumerate(cards, 1):
        mark = ""
        if c.id == best:
            mark = " (best)"
        if c.id == worst:
            mark = " (worst)"
        price = f"{c.pricing.price_total_rub:,.0f}".replace(",", " ") if c.pricing.price_total_rub else "—"
        ppm2 = f"{c.pricing.price_per_m2_rub:,.0f}".replace(",", " ") if c.pricing.price_per_m2_rub else "—"
        floor = f"{c.parameters.floor}/{c.parameters.floors_total}" if c.parameters.floor else "—"
        series = c.building.house_series or ""
        year = c.building.year_built or ""
        series_year = f"{series} {year}".strip() or "—"
        missing = _missing(c)
        risk = _risk_str(c)
        triage = _triage_str(c)
        from collections import Counter
        # compute dup inns once outside? do here cheap
        dev_marker = ""
        try:
            inns = Counter(_developer_inn(x) for x in cards)
            if _developer_inn(c) and inns[_developer_inn(c)] > 1:
                dev_marker = "≈застр. " + _developer_inn(c)
        except Exception:
            pass
        warn = "; ".join(x for x in (missing, risk, triage, dev_marker) if x) or "—"
        lines.append(
            f"| {i} | {_md_cell(c.title or c.id)}{mark} | {price} | {ppm2} | {c.geo.district or '—'} | {floor} | {_walk(c)} | {c.parameters.area_total_m2 or '—'} | {_md_cell(series_year)} | {_md_cell(warn)} |"
        )
    return "\n".join(lines)


def render_telegram(cards: list[ListingCard]) -> str:
    if not cards:
        return "empty_input"
    cards = sort_cards(cards)
    best, worst = _best_worst(cards)
    lines = []
    for c in cards:
        mark = ""
        if c.id == best:
            mark = " ⭐"
        if c.id == worst:
            mark = " ⬇"
        ppm2 = f"{c.pricing.price_per_m2_rub:,.0f}".replace(",", " ") if c.pricing.price_per_m2_rub else "—"
        price = f"{c.pricing.price_total_rub:,.0f}".replace(",", " ") if c.pricing.price_total_rub else "—"
        lines.append(f"• {_decoat(c.title or c.id)}{mark}: {price} ₽, {ppm2} ₽/м², {c.geo.district or '—'}, {_walk(c)}")
        mf = _missing(c)
        if mf:
            lines.append(f"  ⚠ Не хватает данных: {mf}")
        rs = _risk_str(c)
        if rs:
            lines.append(f"  {rs}")
    return "\n".join(lines)


def render_html(cards: list[ListingCard]) -> str:
    if not cards:
        return "empty_input"
    cards = sort_cards(cards)
    best, worst = _best_worst(cards)
    rows = ""
    for c in cards:
        mark = ""
        if c.id == best:
            mark = " (best)"
        if c.id == worst:
            mark = " (worst)"
        price = f"{c.pricing.price_total_rub:,.0f}".replace(",", " ") if c.pricing.price_total_rub else "—"
        ppm2 = f"{c.pricing.price_per_m2_rub:,.0f}".replace(",", " ") if c.pricing.price_per_m2_rub else "—"
        rows += f"<tr><td>{_html_cell(c.title or c.id)}{mark}</td><td>{price}</td><td>{ppm2}</td><td>{_html_cell(c.geo.district if c.geo else '')}</td><td>{c.parameters.floor or ''}/{c.parameters.floors_total or ''}</td><td>{_walk(c)}</td></tr>\n"
    return f"<!DOCTYPE html><html><body><table>{rows}</table></body></html>"


def render(cards: list[ListingCard], fmt: str = "md") -> str:
    if not cards:
        return "empty_input"
    if fmt == "telegram":
        return render_telegram(cards)
    if fmt == "html":
        return render_html(cards)
    return render_markdown(cards)


def _developer_inn(c: ListingCard) -> str:
    try:
        import re
        text = (c.description_text or "") + " " + (c.title or "")
        m = re.search(r"(?<!\d)(\d{10}|\d{12})(?!\d)", text)
        if m and ("застройщик" in text.lower() or "девелопер" in text.lower()):
            return m.group(1)
    except Exception:
        pass
    return ""


def _triage_str(c: ListingCard) -> str:
    try:
        from .legal_triage import triage
        t = triage(c)
        codes = [f["code"] for f in t.get("flags", [])]
        if codes:
            return "⚠ " + ", ".join(codes)
    except Exception:
        pass
    return ""
