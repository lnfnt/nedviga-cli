"""v0.5.7 (the task brief) ops panel."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from .sources import list_sources
from . import pipeline
from .auditlog import read_entries


def _state_dir() -> Path:
    return Path(os.environ.get("NEDVIGA_STATE_DIR", str(Path.home() / ".local" / "share" / "nedviga")))


def collect(days: int = 1, precheck: bool = False, live: bool = False) -> dict[str, Any]:
    # sources
    sources = []
    for s in list_sources():
        sources.append({"id": s["id"], "status": s["status"], "site_patterns": s["site_patterns"]})
    # breaker state: try net_guard
    breaker = {}
    try:
        from .net_guard import _DEFAULT_DB
        breaker = {"db": str(_DEFAULT_DB)}
    except Exception:
        breaker = {}
    # cache stats
    poi_cache = _state_dir() / "poi_cache"
    poi_count = len(list(poi_cache.glob("*.json"))) if poi_cache.exists() else 0
    watch_count = 0
    try:
        conn = pipeline._connect()
        watch_count = conn.execute("SELECT COUNT(*) FROM watch_snapshots").fetchone()[0]
        conn.close()
    except Exception:
        pass
    # errors top-n
    entries = read_entries(days=days)
    errors = [e for e in entries if e.get("rc", 0) != 0]
    # aggregate by command
    agg: dict[str, int] = {}
    for e in errors:
        c = e.get("command", "unknown")
        agg[c] = agg.get(c, 0) + 1
    top_errors = sorted(agg.items(), key=lambda x: x[1], reverse=True)[:10]

    precheck_results = None
    if precheck:
        precheck_results = []
        for s in sources:
            if live:
                # one ping via netguard
                status = "ok"
                try:
                    from .net_guard import guarded_get
                    # minimal HEAD not available; attempt GET root
                    resp = guarded_get(f"https://{s['site_patterns'][0]}", timeout=5.0)
                    if resp.status_code >= 400:
                        status = "error"
                except Exception as exc:
                    msg = str(exc).lower()
                    if "challenge" in msg or "403" in msg:
                        status = "challenge"
                    elif "blocked" in msg:
                        status = "blocked"
                    else:
                        status = "error"
                precheck_results.append({"source": s["id"], "status": status})
            else:
                precheck_results.append({"source": s["id"], "status": "ok"})

    return {
        "sources": sources,
        "breaker": breaker,
        "cache": {"poi_cache_entries": poi_count, "watch_entries": watch_count},
        "errors_top": top_errors,
        "precheck": precheck_results,
    }


def render_text(data: dict) -> str:
    lines = ["OPS"]
    lines.append("sources: " + ", ".join(f"{s['id']}={s['status']}" for s in data["sources"]))
    lines.append(f"poi_cache: {data['cache']['poi_cache_entries']}")
    lines.append(f"watch: {data['cache']['watch_entries']}")
    if data["errors_top"]:
        lines.append("errors: " + ", ".join(f"{k}:{v}" for k, v in data["errors_top"]))
    if data.get("precheck"):
        lines.append("precheck: " + ", ".join(f"{p['source']}={p['status']}" for p in data["precheck"]))
    return "\n".join(lines)
