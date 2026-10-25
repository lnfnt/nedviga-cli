"""v0.4.8 (the task brief) F-08: price/state monitoring."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from . import pipeline


def _extract_price(card: dict) -> Optional[float]:
    if not isinstance(card, dict):
        return None
    if "price_total_rub" in card and card.get("price_total_rub") is not None:
        try:
            return float(card["price_total_rub"])
        except (TypeError, ValueError):
            pass
    pricing = card.get("pricing")
    if isinstance(pricing, dict):
        v = pricing.get("price_total_rub")
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
    return None


def _extract_status(card: dict) -> Optional[str]:
    if not isinstance(card, dict):
        return None
    for key in ("status", "sale_status"):
        if card.get(key):
            return str(card[key])
    return None


def _extract_floors(card: dict) -> Optional[int]:
    if not isinstance(card, dict):
        return None
    params = card.get("parameters") or {}
    if isinstance(params, dict):
        v = params.get("floors_total")
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
    v = card.get("floors_total")
    if v is not None:
        try:
            return int(v)
        except (TypeError, ValueError):
            pass
    return None


def add(card_id: Optional[str] = None, file: Optional[str] = None, price: Optional[float] = None,
        status: str = "active", floors_total: Optional[int] = None, db=None) -> dict[str, Any]:
    conn = pipeline._connect(db)
    try:
        if file:
            raw = json.loads(Path(file).read_text(encoding="utf-8"))
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
            added = []
            for item in raw:
                if not isinstance(item, dict):
                    continue
                cid = item.get("id")
                if not cid:
                    continue
                p = price if price is not None else _extract_price(item)
                st = status if status else (_extract_status(item) or "active")
                fl = floors_total if floors_total is not None else _extract_floors(item)
                now = pipeline._now()
                conn.execute(
                    "INSERT OR REPLACE INTO watch_snapshots (card_id, price, status, floors_total, snapshot_at, raw_json) VALUES (?,?,?,?,?,?)",
                    (str(cid), p, st, fl, now, json.dumps(item, ensure_ascii=False)),
                )
                conn.execute(
                    "INSERT INTO watch_history (card_id, price, status, at) VALUES (?,?,?,?)",
                    (str(cid), p, st, now),
                )
                added.append(str(cid))
            conn.commit()
            return {"ok": True, "added": added}
        if not card_id:
            return {"ok": False, "reason": "missing_card_id"}
        now = pipeline._now()
        conn.execute(
            "INSERT OR REPLACE INTO watch_snapshots (card_id, price, status, floors_total, snapshot_at, raw_json) VALUES (?,?,?,?,?,?)",
            (card_id, price, status, floors_total, now, None),
        )
        conn.execute(
            "INSERT INTO watch_history (card_id, price, status, at) VALUES (?,?,?,?)",
            (card_id, price, status, now),
        )
        conn.commit()
        return {"ok": True, "added": [card_id]}
    finally:
        conn.close()


def list_items(db=None) -> list[dict[str, Any]]:
    conn = pipeline._connect(db)
    try:
        rows = conn.execute("SELECT * FROM watch_snapshots ORDER BY card_id").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def remove(card_id: str, db=None) -> dict[str, Any]:
    conn = pipeline._connect(db)
    try:
        conn.execute("DELETE FROM watch_snapshots WHERE card_id=?", (card_id,))
        conn.commit()
        return {"ok": True, "removed": card_id}
    finally:
        conn.close()


def _normalize_fresh(raw) -> dict[str, dict]:
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
    out = {}
    for item in raw:
        if isinstance(item, dict) and item.get("id"):
            out[str(item["id"])] = item
    return out


def check(offline: Optional[str] = None, db=None) -> list[dict[str, Any]]:
    conn = pipeline._connect(db)
    try:
        rows = conn.execute("SELECT * FROM watch_snapshots").fetchall()
    finally:
        conn.close()

    fresh_map: dict[str, dict] = {}
    if offline:
        try:
            raw = json.loads(Path(offline).read_text(encoding="utf-8"))
            fresh_map = _normalize_fresh(raw)
        except Exception as exc:
            # v0.4.8 контроль качества: битый файл раньше молча превращался в {} и
            # каждая карточка получала ложное "disappeared". Только явный degraded.
            return [{"card_id": "*", "type": "source_degraded",
                     "reason": f"offline_file_unreadable: {type(exc).__name__}"}]

    events: list[dict[str, Any]] = []

    for row in rows:
        cid = row["card_id"]
        if offline:
            fresh = fresh_map.get(cid)
            if fresh is None:
                events.append({"card_id": cid, "type": "disappeared"})
                _h = pipeline._connect(db)
                try:
                    _h.execute("INSERT INTO watch_history (card_id, price, status, at) VALUES (?,?,?,?)",
                               (cid, None, "disappeared", pipeline._now()))
                    _h.commit()
                finally:
                    _h.close()
                continue
            old_price = row["price"]
            new_price = _extract_price(fresh)
            if old_price is not None and new_price is not None:
                if new_price < old_price:
                    events.append({"card_id": cid, "type": "price_down", "amount": old_price - new_price})
                elif new_price > old_price:
                    events.append({"card_id": cid, "type": "price_up", "amount": new_price - old_price})
            st = _extract_status(fresh)
            if st and st.lower() in {"sold", "removed", "inactive"}:
                events.append({"card_id": cid, "type": "sold" if st.lower() == "sold" else "removed"})
            title = str(fresh.get("title") or "").lower()
            if "продан" in title or "снят" in title:
                events.append({"card_id": cid, "type": "sold"})
            _h = pipeline._connect(db)
            try:
                _h.execute("INSERT INTO watch_history (card_id, price, status, at) VALUES (?,?,?,?)",
                           (cid, new_price, st or "active", pipeline._now()))
                _h.commit()
            finally:
                _h.close()
            continue

        # live path
        try:
            from .cian_live import get_card
            card = get_card(cid)
        except Exception as exc:
            msg = str(exc).lower()
            if "404" in msg or "not found" in msg or "removed" in msg:
                events.append({"card_id": cid, "type": "disappeared"})
            else:
                events.append({"card_id": cid, "type": "source_degraded", "reason": str(exc)})
            continue
        # extract from card
        try:
            data = card.model_dump(mode="json", exclude_none=False) if hasattr(card, "model_dump") else {}
        except Exception:
            data = {}
        new_price = _extract_price(data)
        old_price = row["price"]
        if old_price is not None and new_price is not None:
            if new_price < old_price:
                events.append({"card_id": cid, "type": "price_down", "amount": old_price - new_price})
            elif new_price > old_price:
                events.append({"card_id": cid, "type": "price_up", "amount": new_price - old_price})
        st = _extract_status(data)
        if st and st.lower() in {"sold", "removed", "inactive"}:
            events.append({"card_id": cid, "type": "sold" if st.lower() == "sold" else "removed"})

    return events
