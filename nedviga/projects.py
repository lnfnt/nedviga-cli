"""v0.5.0 (the task brief) projects."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_STATE = lambda: Path(os.environ.get("NEDVIGA_STATE_DIR", str(Path.home() / ".local" / "share" / "nedviga")))


def db_path() -> Path:
    p = _STATE() / "projects.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _connect(db=None):
    p = db or db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, query_json TEXT, created TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS project_cards (
        project_id TEXT NOT NULL, card_id TEXT NOT NULL, added_at TEXT NOT NULL,
        UNIQUE(project_id, card_id))""")
    conn.commit()
    return conn


def project_new(name: str, query: Optional[str] = None, db=None) -> dict:
    pid = name
    conn = _connect(db)
    try:
        conn.execute("INSERT OR REPLACE INTO projects (id,name,query_json,created) VALUES (?,?,?,?)",
                     (pid, name, query, datetime.now(timezone.utc).isoformat()))
        conn.commit()
        return {"ok": True, "id": pid, "name": name}
    finally:
        conn.close()


def project_list(db=None) -> list[dict]:
    conn = _connect(db)
    try:
        rows = conn.execute("SELECT * FROM projects ORDER BY name").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def project_add(project: str, card_id: str, db=None) -> dict:
    conn = _connect(db)
    try:
        # idempotent
        exists = conn.execute("SELECT 1 FROM project_cards WHERE project_id=? AND card_id=?",
                              (project, card_id)).fetchone()
        if exists:
            return {"ok": True, "project": project, "card_id": card_id, "idempotent": True}
        conn.execute("INSERT INTO project_cards (project_id, card_id, added_at) VALUES (?,?,?)",
                     (project, card_id, datetime.now(timezone.utc).isoformat()))
        conn.commit()
        return {"ok": True, "project": project, "card_id": card_id, "added": True}
    finally:
        conn.close()


def project_cards(project: str, db=None) -> list[str]:
    conn = _connect(db)
    try:
        rows = conn.execute("SELECT card_id FROM project_cards WHERE project_id=? ORDER BY added_at",
                            (project,)).fetchall()
        return [r["card_id"] for r in rows]
    finally:
        conn.close()


def project_open(project: str, db=None) -> dict:
    cards = project_cards(project, db=db)
    # skeletons
    return {"project": project, "cards": [{"id": c} for c in cards]}


def project_refresh(project: str, file: str, db=None) -> dict:
    # new search export
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
    new_ids = {str(x.get("id")) for x in raw if isinstance(x, dict) and x.get("id")}
    old_ids = set(project_cards(project, db=db))
    added = sorted(new_ids - old_ids)
    removed = sorted(old_ids - new_ids)
    # cheaper: compare price if card present in both? Need old snapshot not stored; skip
    cheaper = []
    # add new ids to project (idempotent)
    for cid in added:
        project_add(project, cid, db=db)
    return {"project": project, "new": added, "removed": removed, "cheaper": cheaper,
            "delta": {"added": len(added), "removed": len(removed)}}
