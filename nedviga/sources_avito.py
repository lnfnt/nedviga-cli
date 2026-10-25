"""v0.5.13 (the task brief) Avito browser adapter (offline-first)."""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# v0.5.13.1 (замечание realtor live): капча Авито формулируется по-разному —
# «Здравствуйте, робот» и «Доступ ограничен: проверка безопасности».
BLOCK_MARKERS = ("Здравствуйте, робот", "Доступ ограничен", "проверка безопасности",
                 "Are you a robot", "captcha")

RATE_LIMIT_SECONDS = 60.0
_last_goto: float = 0.0


def _norm_num(s: str) -> float:
    s = s.replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_livetext(text: str) -> list[dict]:
    cards = []
    for m in re.finditer(r"(\d)-к\.\s*квартира,\s*([\d,\.]+)\s*м²,\s*(\d+)/(\d+)\s*эт\.", text):
        rooms = int(m.group(1))
        area = _norm_num(m.group(2))
        floor = int(m.group(3))
        floors = int(m.group(4))
        prefix = text[:m.start()]
        price_matches = list(re.finditer(r"(\d[\d\s\u00a0]*)\s*₽", prefix))
        price = 0
        ppm2 = None
        # identify total price (not "за м²")
        total_pm = None
        for pm in reversed(price_matches):
            # v0.5.13 контроль: «за м²» ищем СРАЗУ после ₽, иначе следующая
            # строка-перм² съедала и total-цену (15 990 000 ₽\n\n382 536 ₽ за м²
            # — у обоих в 20-символьном хвосте было «за м²», price=0)
            seg_after = text[pm.end():pm.end()+12]
            if re.match(r"\s*за\s*м", seg_after):
                if ppm2 is None:
                    ppm2 = int(_norm_num(pm.group(1)))
                continue
            total_pm = pm
            break
        if total_pm is not None:
            price = int(_norm_num(total_pm.group(1)))
        # fallback ppm2 search
        if ppm2 is None:
            segment = text[total_pm.start() if total_pm else m.start():m.start()]
            ppm = re.search(r"(\d[\d\s\u00a0]*)\s*₽\s*за\s*м²", segment)
            if ppm:
                ppm2 = int(_norm_num(ppm.group(1)))
        rest = text[m.end():m.end() + 600]
        lines = [ln.strip() for ln in rest.splitlines() if ln.strip()]
        # контроль: продавец-строки не адрес
        _SELLER_MARKS = ("Надёжный партнёр", "Надёжный продавец", "Документы проверены")
        address = ""
        for ln in lines:
            if not any(s in ln for s in _SELLER_MARKS):
                address = ln
                break
        metro = ""
        for ln in lines:
            if "мин." in ln:
                metro = ln
                break
        seller_kind = "Надёжный партнёр" if "Надёжный партнёр" in rest else ""
        # v0.5.15 контроль: стабильный id. Позиционный 'avito-<индекс>' ломал
        # watch-идентичность при перестановке выдачи (digest врал new/removed).
        import hashlib as _hl
        lot = None
        ml = re.search(r"Номер лота[:\s]*([\w\-]+)", rest)
        if ml:
            lot = ml.group(1)
        cid = ("avito-" + lot) if lot else ("avito-" + _hl.sha1(
            f"{price}|{address}|{area}|{floor}".encode("utf-8")).hexdigest()[:10])
        card = {
            "id": cid,
            "source": "avito",
            "url": None,
            "title": f"{rooms}-к. квартира, {area} м²",
            "pricing": {"price_total_rub": price, "price_per_m2_rub": ppm2},
            "parameters": {"rooms": rooms, "area_total_m2": area, "floor": floor, "floors_total": floors},
            "building": {"address_raw": address},
            "geo": {"district": None},
            "seller": {"seller_type": seller_kind},
            "warnings": ["url_unavailable"],
        }
        cards.append(card)
    return cards


def _rate_limit_goto():
    global _last_goto
    now = time.time()
    wait = RATE_LIMIT_SECONDS - (now - _last_goto)
    if wait > 0:
        time.sleep(wait)
    _last_goto = time.time()


def browser_search(catalog_url: str, max_n: int = 20) -> list[dict]:
    proxy = os.environ.get("NEDVIGA_EGRESS_PROXY")
    if not proxy:
        raise RuntimeError("source_disabled")
    try:
        from camoufox.sync_api import Camoufox
    except Exception as exc:
        raise RuntimeError(f"source_disabled: {exc}")
    _rate_limit_goto()
    try:
        with Camoufox(headless=True, humanize=True, proxy={"server": proxy}) as browser:
            page = browser.new_page()
            page.goto(catalog_url, timeout=60000)
            page.wait_for_timeout(6000)
            _txt = (page.evaluate("document.body.innerText") or "")
            if any(m.lower() in _txt.lower() for m in BLOCK_MARKERS):
                raise RuntimeError("source_blocked")
            content = page.inner_text("body")
            if "Здравствуйте, робот" in content or "/captcha" in page.url:
                raise RuntimeError("source_blocked")
            cards = parse_livetext(content)
            return cards[:max_n]
    except RuntimeError:
        raise
    except Exception as exc:
        msg = str(exc).lower()
        if "captcha" in msg or "робот" in msg:
            raise RuntimeError("source_blocked")
        raise RuntimeError(f"source_error: {exc}")
