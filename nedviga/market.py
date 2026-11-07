# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 lnfnt <lnfnt@proton.me>

"""v0.5.3 (the task brief) market analytics."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from .bargain import _load_cards, _ppm2, _percentile
from . import pipeline


def _exposure_days(card_id: str) -> Optional[int]:
    try:
        conn = pipeline._connect()
        row = conn.execute("SELECT MIN(snapshot_at) as first_seen FROM watch_snapshots WHERE card_id=?", (card_id,)).fetchone()
        conn.close()
    except Exception:
        return None
    if not row or not row["first_seen"]:
        return None
    try:
        dt = datetime.fromisoformat(str(row["first_seen"]).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).days
    except ValueError:
        return None


def _complex_name(card):
    from .bargain import _complex_name
    return _complex_name(card)


def _recency_ts(card):
    s = getattr(card, "seller", None)
    if s is not None:
        for v in (getattr(s, "edit_date", None), getattr(s, "created_at", None)):
            if v:
                try:
                    dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt
                except ValueError:
                    continue
    return None


def analyze(corpus_paths, district=None, okrug=None, days=30, group_by="district") -> dict[str, Any]:
    cards = []
    for p in corpus_paths:
        cards.extend(_load_cards(p))
    if district:
        cards = [c for c in cards if (c.geo.district if c.geo else None) == district]
    if okrug:
        cards = [c for c in cards if (c.geo.area_name if c.geo else None) == okrug]

    # S2-F13: days раньше игнорировался молча. Честно: отсекаем объявления
    # старше окна по датам публикации/изменения; дат нет — сообщаем, что
    # фильтр не применить, а не выдаём его за применённый.
    with_ts = [c for c in cards if _recency_ts(c) is not None]
    filtered_out = 0
    if with_ts:
        before = len(cards)
        cutoff_exclusive = datetime.now(timezone.utc) - timedelta(days=days)
        cards = [c for c in cards
                 if _recency_ts(c) is None or _recency_ts(c) >= cutoff_exclusive]
        filtered_out = before - len(cards)
        days_applied = True
        days_note = f"фильтр по свежести {days} дн: отсечено {filtered_out}"
    else:
        days_applied = False
        days_note = "days не применён: в корпусе нет дат публикации/изменения"

    prices = [ppm for ppm in (_ppm2(c) for c in cards) if ppm is not None]
    n = len(prices)
    if n < 20:
        return {"ok": False, "reason": "insufficient_sample", "n": n, "required": 20,
                "district": district, "okrug": okrug, "group_basis": "по группе (n={})".format(n),
                "days": days, "days_applied": days_applied, "note": days_note}

    s = sorted(prices)
    median = _percentile(s, 0.5)
    p25 = _percentile(s, 0.25)
    p75 = _percentile(s, 0.75)

    # rooms distribution
    rooms_dist: dict[str, int] = {}
    for c in cards:
        r = c.parameters.rooms
        key = str(r) if r is not None else "unknown"
        rooms_dist[key] = rooms_dist.get(key, 0) + 1

    # exposure
    exposures = []
    for c in cards:
        d = _exposure_days(c.id)
        if d is not None:
            exposures.append(d)
    if exposures:
        exposure = {"min": min(exposures), "max": max(exposures), "median": _percentile(sorted(exposures), 0.5),
                    "n": len(exposures)}
    else:
        exposure = {"status": "insufficient"}

    return {
        "ok": True,
        "n": n,
        "district": district,
        "group_basis": "по {} (n={})".format("ЖК" if group_by == "complex" else (district or "району"), n),
        "okrug": okrug,
        "median": median,
        "p25": p25,
        "p75": p75,
        "rooms_distribution": rooms_dist,
        "exposure": exposure,
        "days": days,
        "days_applied": days_applied,
        "note": days_note,
    }


def render_text(result: dict, fmt: str = "telegram") -> str:
    if not result.get("ok"):
        return f"insufficient_sample: n={result.get('n')}"
    lines = []
    lines.append(f"Рынок: n={result['n']}")
    lines.append(f"медиана ₽/м²: {result['median']:,.0f}".replace(",", " "))
    lines.append(f"P25: {result['p25']:,.0f}  P75: {result['p75']:,.0f}".replace(",", " "))
    lines.append("комнаты: " + ", ".join(f"{k}:{v}" for k, v in result["rooms_distribution"].items()))
    exp = result["exposure"]
    if isinstance(exp, dict) and exp.get("status") == "insufficient":
        lines.append("экспозиция: insufficient")
    else:
        lines.append(f"экспозиция: {exp['min']}-{exp['max']} дн (медиана {exp['median']:.0f}, n={exp['n']})")
    return "\n".join(lines)
