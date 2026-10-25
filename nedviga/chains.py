"""v0.5.4 (the task brief) deal chains."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from . import pipeline


def _connect(db=None):
    conn = pipeline._connect(db)
    conn.execute("""CREATE TABLE IF NOT EXISTS deal_structures (
        card_id TEXT PRIMARY KEY, kind TEXT NOT NULL, created TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS chain_links (
        a TEXT NOT NULL, b TEXT NOT NULL, rel TEXT NOT NULL,
        UNIQUE(a,b,rel))""")
    conn.commit()
    return conn


def chain_new(card_id: str, kind: str, db=None) -> dict:
    conn = _connect(db)
    try:
        conn.execute("INSERT OR REPLACE INTO deal_structures (card_id, kind, created) VALUES (?,?,?)",
                     (card_id, kind, pipeline._now()))
        conn.commit()
        return {"ok": True, "card_id": card_id, "kind": kind}
    finally:
        conn.close()


def _has_path(start: str, target: str, db=None) -> bool:
    conn = _connect(db)
    try:
        # BFS over links a->b
        seen = set()
        stack = [start]
        while stack:
            cur = stack.pop()
            if cur == target:
                return True
            if cur in seen:
                continue
            seen.add(cur)
            rows = conn.execute("SELECT b FROM chain_links WHERE a=?", (cur,)).fetchall()
            for r in rows:
                if r["b"] not in seen:
                    stack.append(r["b"])
        return False
    finally:
        conn.close()


def chain_link(a: str, b: str, rel: str, db=None) -> dict:
    if _has_path(b, a, db=db):
        return {"ok": False, "reason": "cycle_detected"}
    conn = _connect(db)
    try:
        conn.execute("INSERT OR REPLACE INTO chain_links (a,b,rel) VALUES (?,?,?)", (a, b, rel))
        conn.commit()
        return {"ok": True, "a": a, "b": b, "rel": rel}
    finally:
        conn.close()


def chain_show(card_id: str, db=None) -> dict:
    conn = _connect(db)
    try:
        row = conn.execute("SELECT * FROM deal_structures WHERE card_id=?", (card_id,)).fetchone()
        links = conn.execute("SELECT * FROM chain_links WHERE a=? OR b=?", (card_id, card_id)).fetchall()
        # gather up to 10 nodes
        nodes = {card_id}
        for r in links:
            nodes.add(r["a"]); nodes.add(r["b"])
        nodes = list(nodes)[:10]
        risk = None
        if row and row["kind"] == "alt_unfound":
            risk = "risk: развал вероятен — альтернатива не подобрана"
        return {"card_id": card_id, "kind": row["kind"] if row else None,
                "nodes": nodes, "links": [dict(r) for r in links], "risk": risk}
    finally:
        conn.close()
