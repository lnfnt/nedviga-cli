"""v0.5.5 (the task brief) purge."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from . import pipeline
from .auditlog import log_action


def _state_dir() -> Path:
    return Path(os.environ.get("NEDVIGA_STATE_DIR", str(Path.home() / ".local" / "share" / "nedviga")))


def purge_card(card_id: str, yes: bool = False, dry: bool = True) -> dict:
    # dry run: list tables and counts
    conn = pipeline._connect()
    tables = ["pipeline_items", "status_history", "watch_snapshots", "watch_history",
              "show_feedback", "deal_structures", "project_cards", "chain_links"]
    counts = {}
    for t in tables:
        try:
            if t == "project_cards":
                c = conn.execute(f"SELECT COUNT(*) FROM {t} WHERE card_id=?", (card_id,)).fetchone()[0]
            elif t in ("status_history", "watch_history"):
                c = conn.execute(f"SELECT COUNT(*) FROM {t} WHERE card_id=?", (card_id,)).fetchone()[0]
            elif t == "chain_links":
                c = conn.execute(f"SELECT COUNT(*) FROM {t} WHERE a=? OR b=?", (card_id, card_id)).fetchone()[0]
            else:
                c = conn.execute(f"SELECT COUNT(*) FROM {t} WHERE card_id=?", (card_id,)).fetchone()[0]
            counts[t] = c
        except Exception:
            counts[t] = 0
    conn.close()

    total = sum(counts.values())
    if dry or not yes:
        return {"dry": True, "card_id": card_id, "tables": counts, "total": total,
                "note": "files on disk not removed; manual decision required"}

    # execute
    conn = pipeline._connect()
    # ensure tables exist
    try:
        from .chains import _connect as _cc
        _cc().close()
    except Exception:
        pass
    try:
        from .feedback import _connect as _fc
        _fc().close()
    except Exception:
        pass
    for sql, params in [
        ("DELETE FROM pipeline_items WHERE card_id=?", (card_id,)),
        ("DELETE FROM status_history WHERE card_id=?", (card_id,)),
        ("DELETE FROM watch_snapshots WHERE card_id=?", (card_id,)),
        ("DELETE FROM watch_history WHERE card_id=?", (card_id,)),
        ("DELETE FROM show_feedback WHERE card_id=?", (card_id,)),
        ("DELETE FROM deal_structures WHERE card_id=?", (card_id,)),
        ("DELETE FROM chain_links WHERE a=? OR b=?", (card_id, card_id)),
        ("DELETE FROM project_cards WHERE card_id=?", (card_id,)),
    ]:
        try:
            conn.execute(sql, params)
        except Exception:
            pass
    try:
        from .textsearch import db_path as tdb
        import sqlite3
        tconn = sqlite3.connect(str(tdb()))
        try:
            tconn.execute("DELETE FROM documents WHERE card_id=?", (card_id,))
            tconn.execute("DELETE FROM docs_fts WHERE card_id=?", (card_id,))
            tconn.commit()
        except Exception:
            pass
        tconn.close()
    except Exception:
        pass
    try:
        conn.commit()
    except Exception:
        pass
    conn.close()

    # idempotency: if total was 0 -> not_found
    if total == 0:
        return {"ok": True, "card_id": card_id, "deleted": 0, "reason": "not_found",
                "tables": counts}
    # audit trail
    try:
        log_action(role=os.environ.get("NEDVIGA_ROLE", "agent"), command="purge",
                   card_id=card_id, rc=0, reason="purge_card",
                   argv=[], pii=False)
    except Exception:
        pass
    return {"ok": True, "card_id": card_id, "deleted": total, "tables": counts,
            "audit": "recorded"}


def purge_profile(name: str, yes: bool = False, dry: bool = True) -> dict:
    path = _state_dir() / "profile_overrides.json"
    if dry or not yes:
        return {"dry": True, "profile": name, "path": str(path)}
    # remove overrides file if exists
    if path.exists():
        path.unlink()
    try:
        log_action(role=os.environ.get("NEDVIGA_ROLE", "agent"), command="purge",
                   card_id=None, rc=0, reason="purge_profile", argv=[], pii=False)
    except Exception:
        pass
    return {"ok": True, "profile": name, "deleted": 1}
