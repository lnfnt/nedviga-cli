"""v0.5.11 (the task brief) noise monitoring."""
from __future__ import annotations

import json
import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .models import ListingCard


def db_path() -> Path:
    base = Path(os.environ.get("NEDVIGA_STATE_DIR", str(Path.home() / ".local" / "share" / "nedviga")))
    base.mkdir(parents=True, exist_ok=True)
    return base / "noise.sqlite"


def _connect(db=None):
    p = db or db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS noise_measurements (
        id INTEGER PRIMARY KEY, date TEXT, adm_area TEXT, district TEXT, lat REAL, lon REAL,
        location TEXT, territory TEXT, category TEXT, results TEXT, raw TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS sync_state (cursor TEXT, last_sync TEXT)""")
    conn.commit()
    return conn


def _haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0
    phi1 = math.radians(lat1); phi2 = math.radians(lat2)
    dphi = math.radians(lat2-lat1); dl = math.radians(lon2-lon1)
    x = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dl/2)**2
    return 2*R*math.asin(math.sqrt(x))


def _scalar(v):
    """sqlite-безопасное значение: списки/структуры — в JSON-строку (v0.5.11 контроль:
    live/mock Results бывают list — bind падал ProgrammingError)."""
    if v is None or isinstance(v, (str, int, float, bytes)):
        return v
    import json as _j
    try:
        return _j.dumps(v, ensure_ascii=False)
    except Exception:
        return str(v)


def sync(limit=1000, db=None, rows_func=None) -> dict:
    conn = _connect(db)
    row = conn.execute("SELECT cursor FROM sync_state ORDER BY rowid DESC LIMIT 1").fetchone()
    skip = int(row["cursor"]) if row and row["cursor"] else 0
    if rows_func is None:
        from .mosdata import rows as rows_func
    total = 0
    while total < limit:
        top = min(1000, limit - total)
        try:
            data = rows_func("2449", None, top, skip)
        except Exception:
            break
        items = data if isinstance(data, list) else (data.get("value") or data.get("rows") or [])
        if not items:
            break
        for it in items:
            # map fields
            # v0.5.11 замечание realtor (верное): apidata v1 кладёт поля в Cells —
            # без unwrap половина замеров теряла координаты. Cells в приоритете,
            # верхний уровень — фолбэк (формат моков/экспортов).
            c = it.get("Cells") if isinstance(it.get("Cells"), dict) else it
            lat = c.get("Latitude_WGS84") or it.get("Latitude_WGS84") or c.get("lat")
            lon = c.get("Longitude_WGS84") or it.get("Longitude_WGS84") or c.get("lon")
            row_id = c.get("Id") or it.get("Id") or it.get("id")
            if row_id is None:
                continue
            conn.execute("INSERT OR REPLACE INTO noise_measurements (id,date,adm_area,district,lat,lon,location,territory,category,results,raw) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (row_id, _scalar(c.get("Date") or it.get("Date") or it.get("date")),
                          _scalar(c.get("AdmArea") or it.get("AdmArea")), _scalar(c.get("District") or it.get("District")),
                          _scalar(lat), _scalar(lon),
                          _scalar(c.get("Location") or it.get("Location")),
                          _scalar(c.get("TerritoryType") or it.get("TerritoryType")),
                          _scalar(c.get("NoiseCategory") or it.get("NoiseCategory")),
                          _scalar(c.get("Results") or it.get("Results")), json.dumps(it, ensure_ascii=False)))
            total += 1
            if total >= limit:
                break
        skip += len(items)
        conn.execute("INSERT INTO sync_state (cursor,last_sync) VALUES (?,?)",
                     (str(skip), datetime.now(timezone.utc).isoformat()))
        conn.commit()
        if len(items) < top:
            break
    conn.close()
    return {"ok": True, "inserted": total, "cursor": str(skip)}


def nearest(lat, lon, limit=5) -> list[dict]:
    conn = _connect()
    rows = conn.execute("SELECT * FROM noise_measurements WHERE lat IS NOT NULL AND lon IS NOT NULL").fetchall()
    conn.close()
    items = []
    for r in rows:
        d = _haversine(lat, lon, r["lat"], r["lon"])
        items.append({"distance_m": int(round(d)), "date": r["date"], "results": r["results"],
                      "territory": r["territory"], "source": "data.mos.ru 2449", "location": r["location"]})
    items.sort(key=lambda x: x["distance_m"])
    return items[:limit]


def noise_for_card(card, radius_m: int = 1500) -> dict:
    """v0.5.11 контроль качества: принимает карточку ListingCard/dict-карточку ИЛИ
    чистые координаты {"geo": {"lat":..,"lon":..}} (CLI --lat/--lon).
    Прежняя версия падала ValidationError на чистых координатах."""
    from .models import ListingCard
    lat = lon = None
    c = None
    if isinstance(card, str):
        try:
            import json, pathlib
            raw = json.loads(pathlib.Path(card).read_text(encoding="utf-8"))
            if isinstance(raw, list):
                raw = raw[0] if raw else {}
            card = raw
        except Exception:
            return {"status": "no_coordinates", "measurements": []}
    if isinstance(card, dict) and "geo" in card and "id" not in card:
        g = card.get("geo") or {}
        lat, lon = g.get("lat"), g.get("lon")
    else:
        c = card if isinstance(card, ListingCard) else (ListingCard(**card) if isinstance(card, dict) else None)
        if c is not None:
            g = c.geo
            lat = g.lat if g else None
            lon = g.lon if g else None
    if lat is None or lon is None:
        return {"status": "no_coordinates", "measurements": []}
    items = [x for x in nearest(lat, lon, limit=5) if x["distance_m"] <= radius_m]
    return {"status": "ok", "measurements": items}


DISCLAIMER = "точечные измерения подвижной лабораторией, покрытие фрагментарное; отсутствие записи ≠ низкий шум"


def render_text(result: dict) -> str:
    if result.get("status") == "no_coordinates":
        return "no_coordinates"
    lines = []
    for m in result.get("measurements", []):
        lines.append(f"{m['distance_m']} м — {m['date']}: {m['results']} ({m['territory']}) [{m['source']}]")
    lines.append(DISCLAIMER)
    return "\n".join(lines)
