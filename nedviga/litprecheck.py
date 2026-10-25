"""v0.5.6 (the task brief) litigation pre-check via sud-cli."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from . import pipeline


def _sud_bin() -> str:
    return os.environ.get("SUD_BIN", "sud-cli")


def _cache_dir() -> Path:
    base = Path(os.environ.get("NEDVIGA_STATE_DIR", str(Path.home() / ".local" / "share" / "nedviga")))
    d = base / "litcheck_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_key(query: str) -> str:
    return hashlib.sha256(query.encode()).hexdigest()


def _cache_get(key: str) -> Optional[dict]:
    p = _cache_dir() / f"{key}.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    ts = data.get("_ts")
    if ts:
        dt = datetime.fromisoformat(ts)
        if datetime.now(timezone.utc) - dt > timedelta(hours=24):
            return None
    return data.get("payload")


def _cache_set(key: str, payload: dict) -> None:
    p = _cache_dir() / f"{key}.json"
    p.write_text(json.dumps({"_ts": datetime.now(timezone.utc).isoformat(), "payload": payload},
                            ensure_ascii=False), encoding="utf-8")


def litcheck(card_id: Optional[str] = None, address: Optional[str] = None,
             developer: Optional[str] = None, since: int = 2020, file: Optional[str] = None,
             db=None) -> dict:
    # build query from card if file provided
    query = address or developer or ""
    if file and not query:
        try:
            import json as _j
            raw = _j.loads(Path(file).read_text(encoding="utf-8"))
            if isinstance(raw, list):
                raw = raw[0]
            if isinstance(raw, dict) and "cards" in raw:
                raw = raw["cards"][0]
            addr = (raw.get("building", {}) or {}).get("address_raw")
            if addr:
                query = addr
        except Exception:
            pass
    if not query:
        query = card_id or ""

    key = _cache_key(query)
    cached = _cache_get(key)
    if cached is not None:
        cached["cache_hit"] = True
        return cached

    bin_path = _sud_bin()
    # try subprocess
    try:
        proc = subprocess.run(
            [bin_path, "--json", "kad", "--name", query],
            capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        result = {"status": "unavailable", "reason": "sud_bin_not_found", "count": None, "links": []}
        _cache_set(key, result)
        return result
    except Exception as exc:
        result = {"status": "error", "reason": str(exc), "count": None, "links": []}
        _cache_set(key, result)
        return result

    if proc.returncode != 0:
        result = {"status": "unavailable", "reason": proc.stderr.strip() or "sud_error", "count": None, "links": []}
        _cache_set(key, result)
        return result
    # parse
    try:
        data = json.loads(proc.stdout)
    except Exception:
        result = {"status": "error", "reason": "invalid_json", "count": None, "links": []}
        _cache_set(key, result)
        return result
    count = data.get("count")
    links = data.get("links", [])
    result = {"status": "ok", "count": count, "links": links, "query": query, "cache_hit": False}
    _cache_set(key, result)
    return result


def render_text(result: dict) -> str:
    if result.get("status") != "ok":
        return f"litcheck: {result.get('status')} — {result.get('reason')}"
    return f"выявлены записи {result.get('count')} по запросу {result.get('query')}, проверь детали; " + ", ".join(result.get("links", []))
