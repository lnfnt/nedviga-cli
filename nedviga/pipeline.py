"""v0.4.8 (the task brief) F-04: pipeline funnel storage."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

STATUSES = ["new", "candidate", "shortlist", "call_planned", "showing",
            "feedback", "reserved", "rejected", "bought"]
TERMINAL = {"rejected", "bought"}

_ALLOWED: dict[str, set[str]] = {
    "new": {"candidate", "rejected"},
    "candidate": {"shortlist", "rejected"},
    "shortlist": {"call_planned", "rejected"},
    "call_planned": {"showing", "rejected"},
    "showing": {"feedback", "rejected"},
    "feedback": {"reserved", "rejected", "bought"},
    "reserved": {"bought", "rejected"},
    "rejected": set(),
    "bought": set(),
}

_STATE_DIR = Path(os.environ.get("NEDVIGA_STATE_DIR", str(Path.home() / ".local" / "share" / "nedviga")))
_DB_PATH = _STATE_DIR / "pipeline.sqlite"
_lock = threading.Lock()


def state_dir() -> Path:
    p = Path(os.environ.get("NEDVIGA_STATE_DIR", str(Path.home() / ".local" / "share" / "nedviga")))
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    return state_dir() / "pipeline.sqlite"


def _connect(db: Optional[Path] = None) -> sqlite3.Connection:
    p = db or db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE IF NOT EXISTS pipeline_items ("
        " card_id TEXT PRIMARY KEY,"
        " title TEXT,"
        " price_snapshot REAL,"
        " status TEXT NOT NULL,"
        " updated_at TEXT NOT NULL,"
        " note TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS status_history ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " card_id TEXT NOT NULL,"
        " from_status TEXT,"
        " to_status TEXT NOT NULL,"
        " at TEXT NOT NULL,"
        " note TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS watch_snapshots ("
        " card_id TEXT PRIMARY KEY,"
        " price REAL,"
        " status TEXT,"
        " floors_total INTEGER,"
        " snapshot_at TEXT NOT NULL,"
        " raw_json TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS watch_history ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " card_id TEXT NOT NULL,"
        " price REAL,"
        " status TEXT,"
        " at TEXT NOT NULL)"
    )
    conn.commit()
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _snapshot_from_file(card_id: str, from_file: Optional[str]) -> tuple[Optional[str], Optional[float]]:
    if not from_file:
        return None, None
    try:
        raw = json.loads(Path(from_file).read_text(encoding="utf-8"))
    except Exception as exc:  # v0.4.8 контроль качества: молчание = ложный «снапшота нет»
        raise ValueError(f"snapshot_file_unreadable: {type(exc).__name__}") from exc
    if isinstance(raw, dict):
        if "cards" in raw and isinstance(raw["cards"], list):
            raw = raw["cards"]
        elif "data" in raw:
            d = raw["data"]
            raw = d if isinstance(d, list) else [d] if isinstance(d, dict) else []
        else:
            raw = [raw]
    if not isinstance(raw, list):
        raw = [raw]
    for item in raw:
        if not isinstance(item, dict):
            continue
        if item.get("id") == card_id:
            title = item.get("title")
            pricing = item.get("pricing") or {}
            price = pricing.get("price_total_rub")
            return title, price
    # fallback first
    if raw and isinstance(raw[0], dict):
        item = raw[0]
        title = item.get("title")
        pricing = item.get("pricing") or {}
        price = pricing.get("price_total_rub")
        return title, price
    return None, None


def has_phone(text: Optional[str]) -> bool:
    if not text:
        return False
    from .pii import mask_phones
    return mask_phones(text) != text


def set_status(
    card_id: str,
    status: str,
    note: Optional[str] = None,
    from_file: Optional[str] = None,
    title: Optional[str] = None,
    price: Optional[float] = None,
    db: Optional[Path] = None,
) -> dict[str, Any]:
    if status not in STATUSES:
        return {"ok": False, "reason": "invalid_status", "card_id": card_id}
    snap_title, snap_price = _snapshot_from_file(card_id, from_file)
    if title is not None:
        snap_title = title
    if price is not None:
        snap_price = price

    warning = None
    if has_phone(note):
        warning = "phone_detected_in_note"

    with _lock:
        conn = _connect(db)
        try:
            row = conn.execute("SELECT * FROM pipeline_items WHERE card_id=?", (card_id,)).fetchone()
            now = _now()
            if row is None:
                conn.execute(
                    "INSERT INTO pipeline_items (card_id, title, price_snapshot, status, updated_at, note) VALUES (?,?,?,?,?,?)",
                    (card_id, snap_title, snap_price, status, now, note),
                )
                conn.execute(
                    "INSERT INTO status_history (card_id, from_status, to_status, at, note) VALUES (?,?,?,?,?)",
                    (card_id, None, status, now, note),
                )
                conn.commit()
                return {"ok": True, "card_id": card_id, "status": status, "created": True,
                        "warning": warning}
            current = row["status"]
            if current == status:
                # idempotent: no history
                conn.execute(
                    "UPDATE pipeline_items SET updated_at=?, note=COALESCE(?, note), "
                    "title=COALESCE(?, title), price_snapshot=COALESCE(?, price_snapshot) WHERE card_id=?",
                    (now, note, snap_title, snap_price, card_id),
                )
                conn.commit()
                return {"ok": True, "card_id": card_id, "status": status, "idempotent": True,
                        "warning": warning}
            if status not in _ALLOWED.get(current, set()):
                return {"ok": False, "reason": "invalid_transition", "from": current, "to": status,
                        "card_id": card_id, "warning": warning}
            conn.execute(
                "UPDATE pipeline_items SET status=?, updated_at=?, note=COALESCE(?, note), "
                "title=COALESCE(?, title), price_snapshot=COALESCE(?, price_snapshot) WHERE card_id=?",
                (status, now, note, snap_title, snap_price, card_id),
            )
            conn.execute(
                "INSERT INTO status_history (card_id, from_status, to_status, at, note) VALUES (?,?,?,?,?)",
                (card_id, current, status, now, note),
            )
            conn.commit()
            return {"ok": True, "card_id": card_id, "status": status, "from": current,
                    "warning": warning}
        finally:
            conn.close()


def list_items(status: Optional[str] = None, db: Optional[Path] = None) -> list[dict[str, Any]]:
    with _lock:
        conn = _connect(db)
        try:
            if status:
                rows = conn.execute("SELECT * FROM pipeline_items WHERE status=? ORDER BY updated_at DESC", (status,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM pipeline_items ORDER BY updated_at DESC").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def show_history(card_id: str, db: Optional[Path] = None) -> dict[str, Any]:
    with _lock:
        conn = _connect(db)
        try:
            item = conn.execute("SELECT * FROM pipeline_items WHERE card_id=?", (card_id,)).fetchone()
            hist = conn.execute("SELECT * FROM status_history WHERE card_id=? ORDER BY id", (card_id,)).fetchall()
            return {
                "card_id": card_id,
                "item": dict(item) if item else None,
                "history": [dict(r) for r in hist],
            }
        finally:
            conn.close()


def clear(db: Optional[Path] = None) -> None:
    with _lock:
        conn = _connect(db)
        try:
            conn.execute("DELETE FROM pipeline_items")
            conn.execute("DELETE FROM status_history")
            conn.commit()
        finally:
            conn.close()
