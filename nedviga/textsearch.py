"""v0.5.4 (the task brief) local full-text search (FTS5)."""
from __future__ import annotations

import hashlib
import html as _html
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Optional

from .models import ListingCard


class TextSearchError(Exception):
    pass


def db_path() -> Path:
    base = Path(os.environ.get("NEDVIGA_STATE_DIR", str(Path.home() / ".local" / "share" / "nedviga")))
    base.mkdir(parents=True, exist_ok=True)
    return base / "text_index.sqlite"


def _sha_file(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _connect(db=None):
    p = db or db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=30.0)
    conn.row_factory = sqlite3.Row
    # check FTS5
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_check USING fts5(x)")
        conn.execute("DROP TABLE IF EXISTS _fts5_check")
    except sqlite3.OperationalError as exc:
        conn.close()
        raise TextSearchError("fts5_unavailable: " + str(exc))
    conn.execute("""CREATE TABLE IF NOT EXISTS indexed_files (
        sha TEXT PRIMARY KEY, path TEXT, indexed_at TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS documents (
        card_id TEXT PRIMARY KEY, title TEXT, description TEXT, note TEXT, sha TEXT)""")
    conn.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(card_id, title, description, note)""")
    conn.commit()
    return conn


def _load_cards(path: str):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
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
    out = []
    for x in raw:
        if isinstance(x, dict):
            try:
                out.append(ListingCard(**x))
            except Exception:
                # minimal
                out.append(x)
        elif isinstance(x, ListingCard):
            out.append(x)
    return out


def index_file(path: str, db=None) -> dict:
    sha = _sha_file(path)
    conn = _connect(db)
    try:
        row = conn.execute("SELECT 1 FROM indexed_files WHERE sha=?", (sha,)).fetchone()
        if row:
            return {"ok": True, "idempotent": True, "sha": sha}
        cards = _load_cards(path)
        for c in cards:
            if isinstance(c, ListingCard):
                card_id = c.id
                title = c.title or ""
                desc = c.description_text or ""
                note = ""
            else:
                card_id = c.get("id", "")
                title = c.get("title", "") or ""
                desc = c.get("description_text", "") or ""
                note = c.get("note", "") or ""
            conn.execute("INSERT OR REPLACE INTO documents (card_id,title,description,note,sha) VALUES (?,?,?,?,?)",
                         (card_id, title, desc, note, sha))
            conn.execute("INSERT INTO docs_fts (card_id,title,description,note) VALUES (?,?,?,?)",
                         (card_id, title, desc, note))
        conn.execute("INSERT INTO indexed_files (sha,path,indexed_at) VALUES (?,?,?)",
                     (sha, path, __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()))
        conn.commit()
        return {"ok": True, "idempotent": False, "sha": sha, "indexed": len(cards)}
    except TextSearchError:
        raise
    except Exception as exc:
        raise TextSearchError(str(exc))
    finally:
        conn.close()


def query(q: str, project: Optional[str] = None, db=None) -> list[dict]:
    conn = _connect(db)
    try:
        # v0.5.4 контроль качества: FTS5 unicode61 не понимает русскую морфологию
        # («доверенности» != «доверенность», узакон* не ловит «узаконим»).
        # LIKE по подстроке = предсказуемое поведение для локального корпуса;
        # хвостовая * трактуется как префикс-поиск.
        term = q.strip().rstrip("*").strip()
        if len(term) < 2:
            raise TextSearchError("query_too_short")
        like = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = conn.execute(
            "SELECT card_id, title, description, note FROM documents"
            " WHERE title LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\' OR note LIKE ? ESCAPE '\\'"
            " ORDER BY card_id", (like, like, like)).fetchall()
    except sqlite3.OperationalError as exc:
        conn.close()
        raise TextSearchError("fts5_unavailable: " + str(exc))
    results = []
    for r in rows:
        # context fragment from description
        hay = (r["description"] or "") or (r["title"] or "") or (r["note"] or "")
        pos = hay.lower().find(term.lower())
        start = max(0, pos - 40) if pos >= 0 else 0
        frag = ("…" if start else "") + hay[start:start + 120]
        results.append({
            "card_id": r["card_id"],
            "title": _html.escape(r["title"] or ""),
            "fragment": _html.escape(frag),
        })
    conn.close()
    return results
