"""v0.5.8 (the task brief) mosdata client."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

import requests

BASE_URL = "https://apidata.mos.ru/v1"


def _token() -> Optional[str]:
    p = os.environ.get("NEDVIGA_MOS_TOKEN_FILE")
    if not p:
        return None
    try:
        return Path(p).read_text(encoding="utf-8").strip()
    except Exception:
        return None


def _proxy() -> Optional[str]:
    return os.environ.get("NEDVIGA_EGRESS_PROXY") or None




def _redact(s: str) -> str:
    import re
    return re.sub(r"api_key=[^&\s]+", "api_key=REDACTED", str(s))


class _SafeError(RuntimeError):
    def __str__(self):
        return _redact(super().__str__())

def _request(method: str, path: str, params=None, timeout=30.0) -> Any:
    from .net_guard import guarded_get
    url = BASE_URL.rstrip("/") + "/" + path.lstrip("/")
    headers = {}
    tok = _token()
    if tok is None:
        raise RuntimeError("token_missing")
    # v0.5.8 live: apidata v1 принимает ключ КАК QUERY-ПАРАМЕТР api_key (заголовок не канон).
    # Ключ в URL = риск утечки в exception/лог: все строки ошибок прогоняются через redact.
    params = dict(params or {})
    params["api_key"] = tok
    # v0.5.8 контроль качества: ЕДИНСТВЕННЫЙ транспорт — guarded_get (allowlist + RU-egress
    # внутри netguard по env NEDVIGA_EGRESS_PROXY). Прежний двойной путь (прямые requests
    # c прокси в обход пина) вырезан: он нарушал инвариант транспорта и молча глотал ошибки.
    import urllib.parse
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    try:
        resp = guarded_get(url, timeout=timeout, headers=headers)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        msg = _redact(str(exc))
        err = _SafeError(f"{type(exc).__name__}: {msg}")
        raise err from None


def search_datasets(query: str) -> dict:
    params = {"$filter": f"contains(Name,'{query}')"}
    return _request("GET", "datasets", params=params)


def dataset_versions(dataset_id: str) -> Any:
    return _request("GET", f"datasets/{dataset_id}/versions")


def rows(dataset_id: str, version: Optional[str] = None, top: int = 1000, skip: int = 0, filter_expr: Optional[str] = None) -> Any:
    path = f"datasets/{dataset_id}/rows"
    params = {"$top": top, "$skip": skip}
    if version:
        params["versionNumber"] = version
    if filter_expr:
        params["$filter"] = filter_expr
    return _request("GET", path, params=params)


def save_discovery(data: dict) -> None:
    base = Path(os.environ.get("NEDVIGA_STATE_DIR", str(Path.home() / ".local" / "share" / "nedviga")))
    base.mkdir(parents=True, exist_ok=True)
    p = base / "mos_datasets.json"
    # store only ids from live payload
    ids = []
    for d in (data.get("datasets") or data.get("value") or []):
        if isinstance(d, dict) and d.get("Id") is not None:
            ids.append(d["Id"])
    payload = {"datasets": data.get("datasets") or data.get("value") or [], "ids": ids}
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
