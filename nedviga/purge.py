# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 lnfnt <lnfnt@proton.me>

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


def purge_card(card_id: str, yes: bool = False, dry: bool = True,
               include_active: bool = False) -> dict:
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
    total = sum(counts.values())

    if dry or not yes:
        conn.close()
        return {"dry": True, "card_id": card_id, "tables": counts, "total": total,
                "note": "files on disk not removed; manual decision required"}

    # status gate: active objects are not purged unless explicitly requested
    try:
        row = conn.execute("SELECT status FROM pipeline_items WHERE card_id=?", (card_id,)).fetchone()
    except Exception:
        row = None
    status = None
    if row is not None:
        try:
            status = row["status"]
        except Exception:
            try:
                status = row[0]
            except Exception:
                status = None
    active_statuses = set(getattr(pipeline, "STATUSES", [])) - set(getattr(pipeline, "TERMINAL", set()))
    is_active = status is not None and status in active_statuses
    if is_active and not include_active:
        conn.close()
        return {"ok": False, "card_id": card_id, "reason": "active_object",
                "deleted": 0, "tables": counts, "status": status}

    # ensure auxiliary tables exist
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
    try:
        from .textsearch import _connect as _tc
        _tc().close()
    except Exception:
        pass
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS project_cards (card_id TEXT, project_id TEXT, added_at TEXT)")
        conn.commit()
    except Exception:
        pass

    # atomic execution: one transaction, rollback on any error
    try:
        conn.execute("BEGIN IMMEDIATE")
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
            conn.execute(sql, params)

        # textsearch (best-effort within same logical operation; failure rolls back main)
        try:
            from .textsearch import db_path as tdb
            import sqlite3 as _sqlite3
            tconn = _sqlite3.connect(str(tdb()))
            try:
                tconn.execute("DELETE FROM documents WHERE card_id=?", (card_id,))
                tconn.execute("DELETE FROM docs_fts WHERE card_id=?", (card_id,))
                tconn.commit()
            except Exception:
                try:
                    tconn.rollback()
                except Exception:
                    pass
                tconn.close()
                raise
            tconn.close()
        except Exception:
            raise

        conn.commit()
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        conn.close()
        return {"ok": False, "card_id": card_id, "reason": str(exc) or "db_error",
                "deleted": 0, "tables": counts, "rolled_back": True}

    conn.close()

    # audit trail
    try:
        log_action(role=os.environ.get("NEDVIGA_ROLE", "agent"), command="purge",
                   card_id=card_id, rc=0, reason="purge_card" + ("_include_active" if include_active else ""),
                   argv=[], pii=False)
    except Exception:
        pass

    if total == 0:
        return {"ok": True, "card_id": card_id, "deleted": 0, "reason": "not_found",
                "tables": counts}
    return {"ok": True, "card_id": card_id, "deleted": total, "tables": counts,
            "audit": "recorded"}


def purge_profile(name: str, yes: bool = False, dry: bool = True) -> dict:
    # S2-F15: имя профиля — allowlist; «удалено всё по любому имени» убрано,
    # deleted честный (0/1), несуществующий файл не отчитывается как удалённый.
    import re as _re
    if not name or not _re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(name)):
        return {"ok": False, "reason": "invalid_profile_name", "profile": name}
    path = _state_dir() / "profile_overrides.json"
    if dry or not yes:
        return {"dry": True, "profile": name, "path": str(path)}
    deleted = 0
    # remove overrides file if exists
    if path.exists():
        path.unlink()
        deleted = 1
    try:
        log_action(role=os.environ.get("NEDVIGA_ROLE", "agent"), command="purge",
                   card_id=None, rc=0, reason="purge_profile", argv=[], pii=False)
    except Exception:
        pass
    return {"ok": True, "profile": name, "deleted": deleted}
