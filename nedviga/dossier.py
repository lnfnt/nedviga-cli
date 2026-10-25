"""v0.5.8 (the task brief) building dossier."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Optional

from .models import ListingCard


def db_path() -> Path:
    p = os.environ.get("NEDVIGA_MKD_DB")
    if p:
        return Path(p)
    base = Path(os.environ.get("NEDVIGA_STATE_DIR", str(Path.home() / ".local" / "share" / "nedviga")))
    base.mkdir(parents=True, exist_ok=True)
    return base / "mos_mkd.sqlite"


def _connect(db=None):
    p = db or db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS mkd (
        address TEXT, cadastral TEXT, year INTEGER, floors INTEGER,
        series TEXT, overlaps TEXT, elevators TEXT, garbage TEXT, capremont TEXT,
        raw TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS sync_state (
        id INTEGER PRIMARY KEY, cursor TEXT, dataset TEXT, last_sync TEXT)""")
    conn.commit()
    return conn


def _norm_addr(s: Optional[str]) -> str:
    if not s:
        return ""
    return " ".join(str(s).lower().split())


_MO_NOISE = ("российская", "федерация", "федерации", "город", "москва", "округ",
             "муниципальный", "муниципальная", "муниципальные", "внутригородская",
             "территория", "улица", "проспект", "переулок", "шоссе", "бульвар",
             "проезд", "тупик", "дом", "корпус", "строение", "владение")


def _addr_key(addr: str):
    """Ключ сопоставления: номер дома + корпус + слова-улица(район) из хвоста адреса.
    v0.5.10 контроль (live): реестр хранит полный канон "... МО Зюзино, Азовская улица,
    дом 4", карточка — короткий "Азовская, 4" — сравнение полных строк никогда не совпадало.
    Ключ требует ПОЛНОЕ совпадение номера дома; без номера — ключ None (никаких
    fuzzy-вердиктов)."""
    import re
    a = (addr or "").lower().strip()
    if not a:
        return None
    m = re.search(r"(?:дом|вл|владение)?\s*(\d{1,4})(?![\d])", a)
    if not m:
        return None
    num = m.group(1)
    km = re.search(r"корпус[.,\s]*(\d+)", a) or re.search(r"\d\s*к(\d+)", a)
    kor = km.group(1) if km else None
    words = {w for w in re.findall(r"[а-яё]{5,}", a) if w not in _MO_NOISE}
    return (num, kor, frozenset(words))


def _addr_score(qk, rk):
    if not qk or not rk:
        return 0.0
    qn, qkorr, qw = qk; rn, rkorr, rw = rk
    if qn != rn or not (qw & rw):
        return 0.0
    if qkorr and rkorr and qkorr != rkorr:
        return 0.0
    if (qkorr is None) != (rkorr is None):
        return 0.85  # корпус известен только с одной стороны — кандидат, не факт
    return 1.0


def sync(dataset: str = "confirmed", limit: int = 20000, db=None, rows_func=None) -> dict:
    """Заполняет реестр живыми датасетами data.mos.ru: 3293 (спецсчета КР) и 520
    (паспорта новостроек гор.стройки). v0.5.10 контроль: прежний sync молчал на
    dataset='auto' (HTTP 400 → вставлено 0, статус ok) — теперь id валидируются,
    ошибки не глотаются, форма поля читается из Cells (боевой ответ apidata v1)."""
    import json
    ids = {"3293": "spec", "520": "mkd520"}
    if dataset not in ids:
        return {"ok": False, "reason": f"unknown_dataset:{dataset} (разрешено: {', '.join(ids)})"}
    conn = _connect(db)
    if ids[dataset] == "mkd520":
        conn.execute("CREATE TABLE IF NOT EXISTS mkd520 (address TEXT PRIMARY KEY, flats INTEGER, raw TEXT)")
    elif not any(r["name"] == "mkd" for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")):
        conn.execute("CREATE TABLE mkd (address TEXT, cadastral TEXT, year INTEGER, floors INTEGER,"
                     " series TEXT, overlaps TEXT, elevators TEXT, garbage TEXT, capremont TEXT, raw TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS sync_state (id INTEGER PRIMARY KEY AUTOINCREMENT, cursor TEXT, dataset TEXT, last_sync TEXT)")
    if rows_func is None:
        from .mosdata import rows as rows_func_
        def rows_func_(dsid, version=None, top=1000, skip=0, flt=None):
            from .mosdata import rows as R
            return R(dsid, filter_expr=flt, top=top, skip=skip)
        rows_func = rows_func_
    skip = 0; inserted = 0; errors = []
    while inserted < limit:
        top = min(1000, limit - inserted)
        try:
            data = rows_func(dataset, None, top, skip)
        except Exception as exc:
            errors.append(str(exc)[:160]); break
        items = data if isinstance(data, list) else (data.get("value") or data.get("Items") or [])
        if not items:
            break
        for item in items:
            cells = item.get("Cells") if isinstance(item, dict) and isinstance(item.get("Cells"), dict) else item
            if dataset == "520":
                addr = cells.get("Address")
                if addr:
                    conn.execute("INSERT OR REPLACE INTO mkd520 (address,flats,raw) VALUES (?,?,?)",
                                 (str(addr), cells.get("FlatsAmount"), json.dumps(item, ensure_ascii=False)))
                    inserted += 1
            else:  # 3293
                c_addr = cells.get("AddressMKD")
                if c_addr:
                    cap = json.dumps({"spec_account": {"owner": cells.get("SpecAccountOwnerName"),
                                                        "bank": cells.get("CreditOrganization"),
                                                        "monthly": cells.get("MonthlyContribution"),
                                                        "opened": cells.get("OpenDate"), "dataset": 3293}},
                                     ensure_ascii=False)
                    conn.execute("INSERT INTO mkd (address,cadastral,year,floors,series,overlaps,elevators,garbage,capremont,raw)"
                                 " VALUES (?,?,?,?,?,?,?,?,?,?)",
                                 (str(c_addr), None, None, None, None, None, None, None, cap, json.dumps(item, ensure_ascii=False)))
                    inserted += 1
            if inserted >= limit:
                break
        skip += len(items)
        conn.execute("INSERT INTO sync_state (cursor,dataset,last_sync) VALUES (?,?,?)",
                     (str(skip), dataset, __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()))
        conn.commit()
        if len(items) < top:
            break
    conn.commit(); conn.close()
    if inserted == 0 and not errors:
        return {"ok": False, "reason": "empty_source", "dataset": dataset}
    out = {"ok": not errors, "inserted": inserted, "cursor": str(skip), "dataset": dataset}
    if errors:
        out["error"] = errors[0]
    return out


def match(card_or_address, db=None) -> dict:
    conn = _connect(db)
    # determine address
    if isinstance(card_or_address, str):
        addr = card_or_address
        cadastral = None
    else:
        c = card_or_address
        if isinstance(c, dict):
            addr = (c.get("building") or {}).get("address_raw")
            cadastral = None
        else:
            addr = getattr(c.building, "address_raw", None) if getattr(c, "building", None) else None
            cadastral = None
    norm = _norm_addr(addr)
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    rows = conn.execute("SELECT * FROM mkd").fetchall() if "mkd" in tables else []
    candidates = []
    qkey = _addr_key(addr)
    for r in rows:
        rd = dict(r)
        score = _addr_score(qkey, _addr_key(rd.get("address")))
        if cadastral and rd.get("cadastral") == cadastral:
            score = max(score, 0.9)
        if score > 0:
            cand = {"address": rd.get("address"), "cadastral": rd.get("cadastral"),
                    "year": rd.get("year"), "floors": rd.get("floors"), "match_score": score}
            if rd.get("capremont"):
                cand["capremont"] = __import__("json").loads(rd["capremont"])
            candidates.append(cand)
    # 520 novostroyka block with house-gate
    # v0.5.10 контроль: conn.close() до этого блока закрывал курсор → mkd520
    # не читался и match вечно возвращал no_match. Закрытие — строго в конце.
    novostroyka = None
    if "mkd520" in tables:
        rows520 = conn.execute("SELECT * FROM mkd520").fetchall()
        for r in rows520:
            rd = dict(r)
            # house gate: номер+корпус+улица (key), 0.85 допустим только односторонний корпус
            sc = _addr_score(qkey, _addr_key(rd.get("address")))
            if sc >= 0.85:
                novostroyka = {"address": rd.get("address"), "flats": rd.get("flats"),
                               "match_score": sc,
                               "source": "data.mos.ru 520 (паспорта новостроек гор.стройки)"}
                if sc < 1.0:
                    novostroyka["note"] = "корпус известен только с одной стороны — сверьте перед выводом клиенту"
                break
    conn.close()
    if not candidates and novostroyka is None:
        return {"status": "no_match"}
    result = {"status": "ok", "candidates": candidates}
    if novostroyka is not None:
        result["novostroyka"] = novostroyka
    return result


def _addr_tokens(address: str) -> list[str]:
    """Корневые токены улицы/ЖК из адреса: длинные кириллические слова, степпинг суффиксов."""
    import re
    words = re.findall(r"[а-яёА-ЯЁ]{6,}", address or "")
    # v0.5.9 контроль:Generic-токены (город/федерация/округ...) матчат случайные дома —
    # это ложные dossier-факты,Stop-words обязательны.
    stop = {"российская", "федерация", "город", "москва", "улица", "дом", "корпус",
            "муниципальный", "муниципальная", "муниципальные", "округ", "внутригородская",
            "территория", "проспект", "переулок", "шоссе", "бульвар", "проезд", " тупик"}
    toks = set()
    for w in words:
        wl = w.lower()
        if wl in stop or any(s0 in wl for s0 in ("российск", "федераци", "муницип", "внутригород")):
            continue
        toks.add(wl)
        for suf in ("ская","ская","ского","ской","ые","ие","ый","ая","ов","ев","ск","ин"):
            if wl.endswith(suf) and len(wl) - len(suf) >= 5:
                toks.add(wl[: -len(suf)]); break
    return sorted(toks, key=len, reverse=True)[:4]


def mos_sources(card_address: str, db=None) -> dict:
    """Dossier live-sources через RU-egress: 3293 спецсчета капремонта (data.mos.ru).
    Только подтверждённые факты канала; absent честный. Series/год/перекрытия —
    легального источника нет (re-scope 23.10). 62963 отложен: адрес вложен,
    серверный фильтр невозможен, полный дамп запрещён."""
    from . import mosdata
    import json, hashlib, time, os, re as _re2

    cache_dir = os.path.join(os.environ.get("NEDVIGA_STATE_DIR",
                            os.path.expanduser("~/.local/share/nedviga")), "mos_cache")
    os.makedirs(cache_dir, exist_ok=True)
    key = hashlib.sha256(card_address.encode()).hexdigest()[:24]
    cf = os.path.join(cache_dir, key + ".json")
    if os.path.exists(cf) and time.time() - os.path.getmtime(cf) < 30 * 86400:
        return json.load(open(cf))

    out = {"spec_account": None, "spec_account_absent": False, "source": "data.mos.ru"}
    tokens = _addr_tokens(card_address)[:3]

    def _num_gate(hits):
        mnum = _re2.search(r"(?:дом|владение|д\.?)\s*(\d+)", card_address or "", _re2.I)
        if not mnum:
            return hits, None
        n = mnum.group(1)
        def _ok(addr):
            a = str(addr)
            return bool(_re2.search(rf"(?:дом|вл|владение)\s*{n}(?:\b|\s|,|$)", a, _re2.I)) or \
                   bool(_re2.search(rf",\s*{n}\s*(?:к\d|,|$)", a, _re2.I))
        exact = [r for r in hits if _ok(r["Cells"]["AddressMKD"])]
        return exact, (None if exact else f"дом {n}: спецсчета по улице найдены, номер не сопоставлен — проверьте вручную")

    tried = 0
    matched = False
    for base_tok in tokens:
        variants = []
        for v in (base_tok.capitalize(), base_tok.title(), base_tok):
            if v not in variants:
                variants.append(v)
        for tok in variants:
            if tried >= 8:
                break
            tried += 1
            esc = tok.replace("'", "''")
            try:
                raw = mosdata.rows(3293, filter_expr=f"substringof('{esc}',AddressMKD)", top=20)
                rows = raw if isinstance(raw, list) else (raw.get("Items") or raw.get("value") or [])
            except Exception as exc:
                out["error_3293"] = str(exc)[:120]
                continue
            hits = [r for r in rows if isinstance(r, dict) and r.get("Cells", {}).get("AddressMKD")]
            if not hits:
                continue
            exact, unmatched = _num_gate(hits)
            if unmatched:
                out["candidates"] = [r["Cells"]["AddressMKD"] for r in hits][:5]
                out["number_unmatched"] = unmatched
                matched = True  # нашли улицу — absent больше не ложный
                break
            c = exact[0]["Cells"]
            out["spec_account"] = {"address": c.get("AddressMKD"), "owner": c.get("SpecAccountOwnerName"),
                                   "bank": c.get("CreditOrganization"), "monthly": c.get("MonthlyContribution"),
                                   "opened": c.get("OpenDate"), "dataset": 3293,
                                   "source": "data.mos.ru, датасет 3293 (спецсчета КР), apidata v1, через RU-egress"}
            matched = True
            break
        if matched:
            break

    if not matched and "number_unmatched" not in out:
        out["spec_account_absent"] = True
        out["absent_note"] = ("в реестре спецсчетов капремонта (3293) не найдено; "
                              "форма накопления не подтверждена этим датасетом")
    out["_query_tokens"] = tokens
    out["_attempts"] = tried
    json.dump(out, open(cf, "w"), ensure_ascii=False)
    return out
