"""v0.5.4 (the task brief) feedback tracker."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import pipeline


def _connect(db=None):
    conn = pipeline._connect(db)
    conn.execute("""CREATE TABLE IF NOT EXISTS show_feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        card_id TEXT NOT NULL,
        verdict TEXT NOT NULL,
        reason TEXT,
        note TEXT,
        created_at TEXT NOT NULL,
        snapshot TEXT)""")
    conn.commit()
    return conn


def add_feedback(card_id: str, verdict: str, reason: Optional[str] = None, note: Optional[str] = None, dry: bool = False, db=None) -> dict:
    if dry:
        return {"ok": True, "dry": True, "card_id": card_id, "verdict": verdict}
    conn = _connect(db)
    try:
        conn.execute("INSERT INTO show_feedback (card_id, verdict, reason, note, created_at, snapshot) VALUES (?,?,?,?,?,?)",
                     (card_id, verdict, reason, note, datetime.now(timezone.utc).isoformat(), None))
        conn.commit()
        return {"ok": True, "card_id": card_id, "verdict": verdict}
    finally:
        conn.close()


def list_feedback(card_id: Optional[str] = None, db=None) -> list[dict]:
    conn = _connect(db)
    try:
        if card_id:
            rows = conn.execute("SELECT * FROM show_feedback WHERE card_id=? ORDER BY id", (card_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM show_feedback ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def profile_aggregate(db=None) -> dict[str, Any]:
    items = list_feedback(db=db)
    n = len(items)
    suggested = []
    if n >= 5:
        # naive: one aggregate weight
        liked = sum(1 for x in items if x.get("verdict") == "liked")
        rejected = sum(1 for x in items if x.get("verdict") == "rejected")
        suggested.append({"feature": "overall", "delta": (liked - rejected) / n, "n_backing": n})
    # features with n<5 omitted
    return {"n_feedback": n, "suggested_weights": suggested}


def _overrides_path() -> Path:
    base = Path(os.environ.get("NEDVIGA_STATE_DIR", str(Path.home() / ".local" / "share" / "nedviga")))
    return base / "profile_overrides.json"


def apply_overrides(dry: bool = False, yes: bool = False, db=None) -> dict:
    prof = profile_aggregate(db=db)
    if dry:
        return {"ok": True, "dry": True, "proposed": prof["suggested_weights"]}
    if not yes:
        return {"ok": False, "reason": "requires_yes"}
    path = _overrides_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(prof["suggested_weights"], ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "written": str(path), "overrides": prof["suggested_weights"]}
