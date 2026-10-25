"""v0.5.14 F-15b: Domclid browser-адаптер. innerText-парсинг (Angular-рендер, карточных
атрибутов нет — решётка текста с пустыми строками; lesson avito v0.5.13: парсер по тексту).
Контакты не извлекаются никогда; «Показать телефон» — маркер отсечения поля.
url: ссылки /offer/ в DOM не появлялись — url=None честно, id = хеш карточки.
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from datetime import datetime, timezone

RATE_LIMIT_SECONDS = 60
_BLOCK_MARKERS = ("Доступ ограничен", "проверка безопасности", "Здравствуйте, робот",
                  "Are you a robot", "captcha")
_last_goto = [0.0]


def _rate_limit_goto() -> None:
    wait = RATE_LIMIT_SECONDS - (time.time() - _last_goto[0])
    if _last_goto[0] and wait > 0:
        time.sleep(wait)
    _last_goto[0] = time.time()


def _num(s: str) -> float | None:
    s = s.replace("\u00a0", "").replace(" ", "").replace(",", ".")
    m = re.match(r"^(\d+(?:\.\d+)?)(?:м²|этаж|эт)?", s)
    return float(m.group(1)) if m else None


def parse_domclick_text(text: str) -> list[dict]:
    """Карточка начинается с общей цены 'N ₽' отдельной строкой; дальше перм²/ипотека/
    статусы; параметры 'N-комн. квартира', площадь 'S м²', этаж 'F/E эт.', ЖК, адрес."""
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    cards = []
    for i, ln in enumerate(lines):
        m = re.fullmatch(r"(\d[\d\s\u00a0]{4,12})\s*₽", ln)
        if not m:
            continue
        # следующая содержательная строка — ₽/м² или сразу ипотека/параметры
        ppm2 = None
        j = i + 1
        if j < len(lines) and re.match(r"\d[\d\s\u00a0]*\s*₽/м²", lines[j]):
            ppm2 = _num(lines[j].split("₽")[0])
            j += 1
        # окна карточки: до следующей цены или <=18 строк
        window = lines[j:j + 18]
        rooms = area = floor = floors = None
        complex_name = address = None
        is_new = False
        for k, w in enumerate(window):
            mr = re.match(r"(\d+)-комн\.\s*(квартира|студия)", w)
            if mr and rooms is None:
                rooms = int(mr.group(1))
                if "студия" in mr.group(2):
                    rooms = 0
            ma = re.match(r"([\d.,]+)\s*м²$", w)
            if ma and area is None:
                area = _num(ma.group(1))
            mf = re.match(r"(\d+)/(\d+)\s*эт\.?", w)
            if mf and floor is None:
                floor, floors = int(mf.group(1)), int(mf.group(2))
            if w.startswith("ЖК") and complex_name is None:
                complex_name = w[:80]
            if w.startswith("Новостройка"):
                is_new = True
            if "Россия," in w and address is None:
                address = w[:120]
            # отсечение: следующая цена раньше параметров = стоп-окно прерываем позже
        if rooms is None or area is None:
            continue  # не карточка (мелкие цены/ипотека без структуры)
        price = _num(m.group(1))
        if not price or price < 1_000_000:
            continue
        cid = "dc-" + hashlib.sha1(f"{price}|{address}|{area}".encode()).hexdigest()[:10]
        cards.append({
            "id": cid, "source": "domclick", "url": None,
            "title": (complex_name or address or f"{rooms}-комн. {area} м²")[:100],
            "pricing": {"price_total_rub": int(price),
                        "price_per_m2_rub": int(ppm2) if ppm2 else None},
            "parameters": {"rooms": rooms, "area_total_m2": area,
                           "floor": floor, "floors_total": floors},
            "building": {"address_raw": address or "", "complex": complex_name,
                         "is_new_build": is_new},
            "status_flags": {"rosreestr_checked": any("Росреестр" in w for w in window[:10])},
        })
    # дедуп по id
    seen = set()
    out = []
    for c in cards:
        if c["id"] not in seen:
            seen.add(c["id"])
            out.append(c)
    return out


def browser_search_domclick(catalog_url: str, max_n: int = 20) -> list[dict]:
    proxy = (os.environ.get("NEDVIGA_EGRESS_PROXY") or "").strip()
    if not proxy:
        raise RuntimeError("source_disabled")
    try:
        from camoufox.sync_api import Camoufox
    except Exception as exc:
        raise RuntimeError(f"source_disabled: {exc}")
    _rate_limit_goto()
    with Camoufox(headless=True, humanize=True, geoip=True,
                  proxy={"server": proxy}) as browser:
        page = browser.new_page()
        page.goto(catalog_url, wait_until="domcontentloaded", timeout=50000)
        page.wait_for_timeout(8000)
        for _ in range(3):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(3000)
        txt = page.evaluate("document.body.innerText") or ""
    low = txt.lower()
    if any(m.lower() in low for m in _BLOCK_MARKERS):
        raise RuntimeError("source_blocked")
    cards = parse_domclick_text(txt)
    return cards[:max_n]
