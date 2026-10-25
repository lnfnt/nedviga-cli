"""v0.4.8 (the task brief) F-14b: family digest."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from . import pipeline

STATE_DIR = lambda: Path(os.environ.get("NEDVIGA_STATE_DIR", str(Path.home() / ".local" / "share" / "nedviga")))


def _cutoff(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _parse_dt(s: Any) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _pipeline_items(db=None) -> list[dict]:
    return pipeline.list_items(db=db)


def _status_history(db=None, days: int = 7) -> list[dict]:
    conn = pipeline._connect(db)
    try:
        rows = conn.execute("SELECT * FROM status_history ORDER BY id").fetchall()
    finally:
        conn.close()
    cutoff = _cutoff(days)
    out = []
    for r in rows:
        d = dict(r)
        dt = _parse_dt(d.get("at"))
        if dt is None or dt >= cutoff:
            out.append(d)
    return out


def _watch_history(db=None, days: int = 7) -> list[dict]:
    conn = pipeline._connect(db)
    try:
        rows = conn.execute("SELECT * FROM watch_history ORDER BY id").fetchall()
    finally:
        conn.close()
    cutoff = _cutoff(days)
    out = []
    for r in rows:
        d = dict(r)
        dt = _parse_dt(d.get("at"))
        if dt is None or dt >= cutoff:
            out.append(d)
    return out


def _fmt_money(v) -> str:
    return f"{float(v):,.0f}".replace(",", " ")


def _price_reductions(db=None, days: int = 7) -> list[dict]:
    # group watch_history by card, find drops between consecutive snapshots
    hist = _watch_history(db=db, days=days)
    by_card: dict[str, list[dict]] = {}
    for h in hist:
        by_card.setdefault(h["card_id"], []).append(h)
    res = []
    for cid, items in by_card.items():
        items.sort(key=lambda x: x.get("at") or "")
        # v0.4.8 контроль качества: дайджест = ЧИСТАЯ дельта периода (первый снимок ->
        # последний), повторные check одного и того же снижения не плодят строк.
        prices = [it.get("price") for it in items if it.get("price") is not None]
        if len(prices) >= 2 and prices[-1] < prices[0]:
            res.append({"card_id": cid, "amount": prices[0] - prices[-1], "price": prices[-1]})
    return res


def _new_shortlist(db=None, days: int = 7) -> list[dict]:
    hist = _status_history(db=db, days=days)
    seen = set()
    out = []
    for h in hist:
        if h.get("to_status") == "shortlist":
            cid = h["card_id"]
            if cid not in seen:
                seen.add(cid)
                out.append({"card_id": cid, "at": h.get("at")})
    return out


def _removed_sold(db=None, days: int = 7) -> list[dict]:
    # pipeline terminal + watch status sold/removed/disappeared
    res = []
    seen = set()
    for h in _status_history(db=db, days=days):
        if h.get("to_status") in {"rejected", "bought"}:
            cid = h["card_id"]
            if cid not in seen:
                seen.add(cid)
                res.append({"card_id": cid, "status": h.get("to_status")})
    # watch
    hist = _watch_history(db=db, days=days)
    for h in hist:
        st = (h.get("status") or "").lower()
        if st in {"sold", "removed", "disappeared", "inactive"}:
            cid = h["card_id"]
            if cid not in seen:
                seen.add(cid)
                res.append({"card_id": cid, "status": st})
    return res


def _pipeline_moves(db=None, days: int = 7) -> list[dict]:
    return _status_history(db=db, days=days)


def build_digest(days: int = 7, db=None) -> dict[str, Any]:
    reductions = _price_reductions(db=db, days=days)
    new_sl = _new_shortlist(db=db, days=days)
    removed = _removed_sold(db=db, days=days)
    moves = _pipeline_moves(db=db, days=days)
    return {
        "days": days,
        "reductions": reductions,
        "new_shortlist": new_sl,
        "removed": removed,
        "moves": moves,
    }


def render_telegram(digest: dict[str, Any]) -> str:
    days = digest["days"]
    lines: list[str] = []
    if digest["reductions"]:
        lines.append("🔻Снижения:")
        for r in digest["reductions"]:
            lines.append(f"• {r['card_id']}: -{_fmt_money(r['amount'])} ₽ (теперь {_fmt_money(r['price'])})")
        lines.append("")
    if digest["new_shortlist"]:
        lines.append("✨Новое в шорт-листе:")
        for r in digest["new_shortlist"]:
            lines.append(f"• {r['card_id']}")
        lines.append("")
    if digest["removed"]:
        lines.append("❌Снято/продано:")
        for r in digest["removed"]:
            lines.append(f"• {r['card_id']} ({r['status']})")
        lines.append("")
    if digest["moves"]:
        lines.append("📋Движения воронки:")
        for m in digest["moves"]:
            lines.append(f"• {m['card_id']}: {m.get('from_status') or 'старт'} → {m.get('to_status')}")
        lines.append("")
    if not (digest["reductions"] or digest["new_shortlist"] or digest["removed"] or digest["moves"]):
        lines.append(f"за {days} дней без изменений")
    return "\n".join(lines).strip()


def render_md(digest: dict[str, Any]) -> str:
    days = digest["days"]
    from ._wm import render_line as _wl
    try:
        from . import __version__ as _ver
    except Exception:
        _ver = "0"
    lines: list[str] = ["# " + _wl("digest_header", _ver, {"days": days}), ""]
    if digest["reductions"]:
        lines.append("## 🔻 Снижения")
        for r in digest["reductions"]:
            lines.append(f"- {r['card_id']}: -{_fmt_money(r['amount'])} ₽")
        lines.append("")
    if digest["new_shortlist"]:
        lines.append("## ✨ Новое в шорт-листе")
        for r in digest["new_shortlist"]:
            lines.append(f"- {r['card_id']}")
        lines.append("")
    if digest["removed"]:
        lines.append("## ❌ Снято/продано")
        for r in digest["removed"]:
            lines.append(f"- {r['card_id']} ({r['status']})")
        lines.append("")
    if digest["moves"]:
        lines.append("## 📋 Движения воронки")
        for m in digest["moves"]:
            lines.append(f"- {m['card_id']}: {m.get('from_status') or 'старт'} → {m.get('to_status')}")
        lines.append("")
    if not (digest["reductions"] or digest["new_shortlist"] or digest["removed"] or digest["moves"]):
        lines.append(f"за {days} дней без изменений")
    return "\n".join(lines).strip()


def render(digest: dict[str, Any], fmt: str = "telegram") -> str:
    if fmt == "md":
        return render_md(digest)
    return render_telegram(digest)
