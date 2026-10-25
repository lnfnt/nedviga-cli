"""SQLite-кеш маршрутов (routing_cache.sqlite)."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path

# v0.4.5 (панель): кеш внутри пакета ломал read-only установки и параллельные запуски.
_USER_DIR = Path(os.environ.get("NEDVIGA_CACHE_DIR", str(Path.home() / ".local" / "share" / "nedviga")))
_USER_DIR.mkdir(parents=True, exist_ok=True)
_DEFAULT = _USER_DIR / "routing_cache.sqlite"
_lock = threading.Lock()


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
            row = conn.execute("SELECT meters FROM routes WHERE key=?", (k,)).fetchone()
            return row[0] if row else None
        finally:
            conn.close()


def put(lat: float, lon: float, station: str, meters: float,
        provider: str = "unknown", db_path: Path | None = None) -> None:
    k = cache_key(lat, lon, station)
    with _lock:
        conn = _connect(db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO routes (key, meters, provider) VALUES (?, ?, ?)",
                (k, meters, provider),
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
