"""v0.5.10 (the task brief) developer dossier."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from .mosdata import _request


class _SafeError(Exception):
    pass


def _cache_dir() -> Path:
    base = Path(os.environ.get("NEDVIGA_STATE_DIR", str(Path.home() / ".local" / "share" / "nedviga")))
    d = base / "developer_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_key(q: str) -> str:
    return hashlib.sha256(q.encode()).hexdigest()


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
        if datetime.now(timezone.utc) - dt > timedelta(days=30):
            return None
    return data.get("payload")


def _cache_set(key: str, payload: dict) -> None:
    p = _cache_dir() / f"{key}.json"
    p.write_text(json.dumps({"_ts": datetime.now(timezone.utc).isoformat(), "payload": payload},
                            ensure_ascii=False), encoding="utf-8")


def _variants(name: str) -> list[str]:
    return list(dict.fromkeys([name, name.capitalize(), name.title(), name.lower()]))


def _extract_inns(text: str) -> list[tuple[str, str]]:
    # returns list of (inn, context)
    res = []
    for m in re.finditer(r"(?<!\d)(\d{10}|\d{12})(?!\d)", text):
        inn = m.group(1)
        start = max(0, m.start() - 40)
        end = min(len(text), m.end() + 40)
        ctx = text[start:end].strip()
        res.append((inn, ctx))
    return res


def _from_file(path: str) -> dict:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, list):
        raw = raw[0]
    if isinstance(raw, dict) and "cards" in raw and isinstance(raw["cards"], list):
        raw = raw["cards"][0]
    text = (raw.get("description_text") or "") + " " + (raw.get("title") or "")
    # also "застройщик: ..." extraction
    cands = []
    for inn, ctx in _extract_inns(text):
        cands.append({"inn": inn, "context": ctx})
    # застройщик name
    m = re.search(r"застройщик[:\s]+([^\n,]+)", text, re.IGNORECASE)
    if m:
        cands.append({"name_candidate": m.group(1).strip(), "context": m.group(0)})
    return {"candidates": cands}


def search_by_inn(inn: str) -> dict:
    key = "inn:" + inn
    cached = _cache_get(key)
    if cached is not None:
        cached["cache_hit"] = True
        return cached
    try:
        # exact INN search via filter
        data = _request("GET", "datasets/2114/rows", params={"$filter": f"INN eq '{inn}'", "$top": 10})
    except Exception as exc:
        raise _SafeError(str(exc))
    result = {"status": "ok", "inn": inn, "items": data.get("value", []) if isinstance(data, dict) else data, "cache_hit": False}
    _cache_set(key, result)
    return result


def search_by_name(name: str) -> dict:
    key = "name:" + name
    cached = _cache_get(key)
    if cached is not None:
        cached["cache_hit"] = True
        return cached
    all_items = []
    for v in _variants(name):
        try:
            data = _request("GET", "datasets/2114/rows", params={"$filter": f"substringof('{v}', FullName)", "$top": 10})
        except Exception as exc:
            raise _SafeError(str(exc))
        items = data.get("value", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        all_items.extend(items)
    # dedupe by INN
    seen = set()
    uniq = []
    for it in all_items:
        inn = _cells(it).get("INN")
        if inn in seen:
            continue
        if inn:
            seen.add(inn)
        uniq.append(it)
    result = {"status": "ok", "name": name, "items": uniq, "cache_hit": False}
    _cache_set(key, result)
    return result


def litcheck_developer(name_or_inn: str) -> dict:
    from .litprecheck import litcheck
    # query by name/inn
    res = litcheck(address=None, developer=name_or_inn)
    return res


def _cells(item) -> dict:
    """Строка 2114 приходит как {global_id, Number, Cells:{...}} — поля внутри Cells.
    Живой контроль v0.5.10 поймал рендер/дедуп, читавшие верхний уровень (пустой вывод)."""
    if not isinstance(item, dict):
        return {}
    return item.get("Cells") or item


def render_text(result: dict, lit: Optional[dict] = None) -> str:
    lines = []
    items = result.get("items", [])
    if not items:
        lines.append("реестр: совпадений нет")
    for it in items:
        if not isinstance(it, dict):
            continue
        c = _cells(it)
        name = c.get("ShortName") or c.get("FullName") or ""
        inn = c.get("INN") or ""
        lines.append(f"🏗 Застройщик: {name} (ИНН {inn}) (реестр 2114)")
        if c.get("LinkToProjectDeclaration"):
            lines.append(f"декларация: {c.get('LinkToProjectDeclaration')}")
        if c.get("CooperationWithBanks"):
            lines.append(f"банки: {c.get('CooperationWithBanks')}")
        if c.get("PermitNum"):
            lines.append(f"разрешение: {c.get('PermitNum')}")
    if lit is not None:
        if lit.get("status") != "ok":
            lines.append(f"суды: unavailable — {lit.get('reason')}")
        else:
            lines.append(f"суды: {lit.get('count')} записей")
    return "\n".join(lines)
