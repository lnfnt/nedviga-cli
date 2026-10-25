"""v0.5.13 F-15t: транспортная доступность — пешая до метро + ТЕКУЩИЕ пробки.

Честная рамка: прогноза «час-пик» нет — Яндекс отдаёт только
текущий балл, прогноз требует платного API-ключа. Балл замеряется ТОЛЬКО
через RU-egress браузерным каналом; без egress — честный unavailable
(не 0, не среднее, не выдумка).
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


def _egress() -> str | None:
    v = (os.environ.get("NEDVIGA_EGRESS_PROXY") or "").strip()
    return v or None


def _fetch_traffic() -> str:
    """Текущий балл пробок Москвы. Только RU-egress; без — RuntimeError.
    (тесты мокают эту функцию — сеть в тестах запрещена)"""
    proxy = _egress()
    if not proxy:
        raise RuntimeError("egress_required")
    from camoufox.sync_api import Camoufox
    with Camoufox(headless=True, humanize=True, geoip=False,
                  proxy={"server": proxy}) as browser:
        pg = browser.new_page()
        pg.goto("https://yandex.ru/maps/213/moscow/probki/",
                wait_until="domcontentloaded", timeout=45000)
        pg.wait_for_timeout(9000)
        return (pg.evaluate("document.body.innerText") or "")


def parse_balls(text: str) -> int | None:
    m = re.search(r"(\d+)\s*балл", text)
    return int(m.group(1)) if m else None


def _pairs_from_run(nums: list[int]) -> list[dict] | None:
    """Пары «балл@час» из ряда чисел; чередование сломалось -> None."""
    pairs: list[dict] = []
    for i in range(0, len(nums) - 1, 2):
        val, hour = nums[i], nums[i + 1]
        if not (0 <= val <= 10 and 0 <= hour <= 23):
            return None
        if pairs and hour <= pairs[-1]["hour"]:
            break  # прогноз остатка дня: часы идут по возрастанию
        pairs.append({"hour": hour, "balls": val})
    return pairs if len(pairs) >= 2 else None


def parse_forecast_hours(text: str) -> list[dict]:
    """v0.5.14 (the task brief §2): почасовой web-прогноз загруженности со
    страницы Яндекс Карт (innerText), НЕ платный API.

    Живая форма: «Дорожная ситуация сейчас Пробки N баллов» + пары
    «балл@час», идущие подряд: «6 18 5 19 4 20 2 21 1 22 1 23»
    (остаток дня; балл, затем час).

    Честная рамка: только целые баллы 0-10 и целые часы 0-23,
    часы строго по возрастанию, минимум 2 полные пары. Структура не
    распарсилась -> пустой список. Никогда не угадываем.
    """
    if not text:
        return []
    m = re.search(r"\b(\d{1,2})\s*балл", text)
    if not m:
        return []
    runs: list[list[int]] = []
    cur: list[int] = []
    for tok in re.split(r"[\s\u00a0]+", text[m.end():]):
        if re.fullmatch(r"\d{1,2}", tok):
            cur.append(int(tok))
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    for run in runs:
        if len(run) < 4:
            continue
        # смещение 1 — если первым в ряд попал мусор-число (напр. «41 км/ч»)
        for off in (0, 1):
            pairs = _pairs_from_run(run[off:])
            if pairs:
                return pairs
    return []


def walk_to_metro(lat: float, lon: float) -> dict:
    """Ближайшее метро по внутреннему графу (офлайн, пешая дистанция).
    Без графа — честная unavailable."""
    try:
        from .graph import load_graph, _haversine
        g = load_graph()
        node = g.nearest_node(lat, lon, max_m=4000.0)
        if node is None:
            return {"status": "no_metro_in_4km", "walk_minutes": None}
        nla, nlo = g.nodes[node]
        dist = _haversine(lat, lon, nla, nlo)
        minutes = round(dist / 80.0)  # 80 м/мин пешком
        return {"status": "ok", "metro_node": node,
                "distance_m": round(dist), "walk_minutes": minutes}
    except Exception as exc:
        return {"status": "graph_unavailable", "reason": type(exc).__name__,
                "walk_minutes": None}


def rush_report(card_data: dict) -> dict:
    geo = (card_data or {}).get("geo") or {}
    lat, lon = geo.get("lat"), geo.get("lon")
    out: dict = {"walk": None, "traffic": {}, "honest_note":
                 "загруженность текущего момента; прогноз час-пика недоступен без платного API-ключа"}
    if lat is not None and lon is not None:
        out["walk"] = walk_to_metro(lat, lon)
    else:
        out["walk"] = {"status": "no_coordinates", "walk_minutes": None}
    if _egress():
        try:
            text = _fetch_traffic()
            balls = parse_balls(text)
            out["traffic"] = {"score": balls,
                              "measured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            if balls is None:
                out["traffic"]["status"] = "unavailable"
            # v0.5.14: почасовой web-прогноз с той же страницы (офлайн-разбор,
            # без угадывания: пустой список, если структура не распарсилась)
            out["traffic"]["forecast_hours"] = parse_forecast_hours(text)
        except Exception:
            out["traffic"] = {"status": "unavailable", "score": None,
                              "forecast_hours": []}
    else:
        out["traffic"] = {"status": "unavailable (нет RU-egress: не замерено)",
                          "score": None, "forecast_hours": []}
    return out
