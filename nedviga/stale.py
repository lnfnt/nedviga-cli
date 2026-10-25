"""v0.5.3 (the task brief) stale detection."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import pipeline
from .dedup import _listing, _candidate, signature
from .models import ListingCard


def _age_days(ts: Any) -> Optional[int]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).days
    except ValueError:
        return None


def _last_seen(card_id: str) -> Optional[str]:
    try:
        conn = pipeline._connect()
        row = conn.execute("SELECT MAX(snapshot_at) as last_seen FROM watch_snapshots WHERE card_id=?", (card_id,)).fetchone()
        conn.close()
        return row["last_seen"] if row else None
    except Exception:
        return None


def detect_stale(cards, max_age_days: int = 14, verify_live: bool = False) -> list[dict[str, Any]]:
    lst = [_listing(c) for c in cards]
    # signatures for relist detection
    sig_map: dict[Any, list[ListingCard]] = {}
    for c in lst:
        sig_map.setdefault(signature(c), []).append(c)

    results = []
    for c in lst:
        age = _age_days(_last_seen(c.id))
        status = None
        reason = None
        # relisted: another card same signature different id
        same_sig = [x for x in sig_map.get(signature(c), []) if x.id != c.id]
        if same_sig:
            status = "relisted"
            reason = "подпись совпадает с " + ", ".join(x.id for x in same_sig)
        elif age is not None and age > max_age_days:
            status = "stale_suspect"
            reason = f"последняя видимость {age} дн назад (порог {max_age_days})"
        else:
            # no last_seen data: stale suspect if no snapshot
            if _last_seen(c.id) is None:
                status = "stale_suspect"
                reason = "нет подтверждённой видимости в watch_snapshots"
            else:
                status = "fresh"
                reason = "актуально"

        if status in {"stale_suspect"} and verify_live:
            try:
                from .cian_live import get_card
                get_card(c.id)
            except Exception as exc:
                msg = str(exc).lower()
                if "404" in msg or "not found" in msg or "removed" in msg:
                    status = "confirmed_gone"
                    reason = "live-check: объект недоступен (404)"

        results.append({"card_id": c.id, "status": status, "reason": reason})
    return results


def render_text(results) -> str:
    lines = []
    for r in results:
        lines.append(f"{r['card_id']}: {r['status']} — {r['reason']}")
    return "\n".join(lines)
