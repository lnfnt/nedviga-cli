# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 lnfnt <lnfnt@proton.me>

"""SQLite-кеш маршрутов (routing_cache.sqlite)."""
from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

# v0.4.5 (панель): кеш внутри пакета ломал read-only установки и параллельные запуски.
_USER_DIR = Path(os.environ.get("NEDVIGA_CACHE_DIR", str(Path.home() / ".local" / "share" / "nedviga")))
_USER_DIR.mkdir(parents=True, exist_ok=True)
_DEFAULT = _USER_DIR / "routing_cache.sqlite"
_lock = threading.Lock()

# S1-F4: TTL for cached routes (30 days). Older entries are treated as poisoned/expired.
ROUTE_CACHE_TTL_SECONDS = 30 * 24 * 3600


def _parse_created_at(value) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _valid_entry(meters, provider, created_at) -> bool:
    if isinstance(meters, bool) or not isinstance(meters, (int, float)):
        return False
    if not math.isfinite(meters):
        return False
    if meters < 0 or meters > 1_000_000_000:
        return False
    if not isinstance(provider, str) or not provider.strip():
        return False
    dt = _parse_created_at(created_at)
    if dt is None:
        return False
    age = (datetime.now(timezone.utc) - dt).total_seconds()
    if age < -300 or age > ROUTE_CACHE_TTL_SECONDS:
        return False
    return True


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    p = db_path or _DEFAULT
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS routes ("
        " key TEXT PRIMARY KEY,"
        " meters REAL NOT NULL,"
        " provider TEXT NOT NULL,"
        " created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    return conn


def cache_key(lat: float, lon: float, station: str, grid_m: float = 50.0) -> str:
    """Ключ = округлённые координаты (грид ~50м) + станция."""
    lat_r = round(lat / (grid_m / 111_000.0))
    lon_r = round(lon / (grid_m / 76_000.0))
    return f"{lat_r}:{lon_r}:{station.casefold()}"


def get(lat: float, lon: float, station: str, db_path: Path | None = None) -> float | None:
    k = cache_key(lat, lon, station)
    with _lock:
        conn = _connect(db_path)
        try:
            row = conn.execute(
                "SELECT meters, provider, created_at FROM routes WHERE key=?", (k,)
            ).fetchone()
            if row is None:
                return None
            meters, provider, created_at = row
            if not _valid_entry(meters, provider, created_at):
                # drop poisoned/expired entry so it can be recomputed
                conn.execute("DELETE FROM routes WHERE key=?", (k,))
                conn.commit()
                return None
            return meters
        finally:
            conn.close()


def put(lat: float, lon: float, station: str, meters: float,
        provider: str = "unknown", db_path: Path | None = None) -> None:
    if not _valid_entry(meters, provider, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")):
        raise ValueError("invalid route cache entry")
    k = cache_key(lat, lon, station)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with _lock:
        conn = _connect(db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO routes (key, meters, provider, created_at) VALUES (?, ?, ?, ?)",
                (k, meters, provider, now),
            )
            conn.commit()
        finally:
            conn.close()


def stats(db_path: Path | None = None) -> dict:
    conn = _connect(db_path)
    try:
        n = conn.execute("SELECT COUNT(*) FROM routes").fetchone()[0]
        return {"entries": n, "path": str(db_path or _DEFAULT)}
    finally:
        conn.close()
