"""P3-3 (2026-10-20): fail-closed для карточек без цены.

Живой дефект (ТЗ realtor): карточка без цены молча уезжала с price_total_rub=None.
Схема (status enum) контракта не меняет — карантин выражается отдельным
jsonl-журналом price_drift: «цена пропала» = событие, а не отсутствие поля.

Порядок для цены:
  1) structured fields / itemprop (cian_card),
  2) adaptive selectors (adaptive_selectors.extract_price_adaptive),
  3) title-fallback (этот модуль: «12 500 000 ₽»/«12500000 руб.» из заголовка),
  4) ничего не найдено -> None + запись в drift-журнал (карантин для приёмки).
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_TITLE_PRICE_RE = re.compile(
    r"(?<![\d.])(\d{1,3}(?:[ \u00a0]\d{3})+|\d{6,12})[ \u00a0]*(?:₽|руб)",
    re.IGNORECASE,
)


def price_from_title(title: Optional[str]) -> Optional[float]:
    """Вытащить цену из заголовка, только если рядом стоит ₽/руб.

    Голые числа (комнаты, этажи, «1 из 12») не считаются ценой — ложные
    срабатывания дороже молчаливого None (тогда уж drift-событие)."""
    if not title:
        return None
    m = _TITLE_PRICE_RE.search(title)
    if not m:
        return None
    digits = m.group(1).replace(" ", "").replace("\u00a0", "")
    try:
        value = float(digits)
    except ValueError:
        return None
    if value < 100_000:  # квартир-ценников ниже нет; отсекает мусор вроде «1250 ₽/м2»
        return None
    return value


def drift_file() -> Path:
    return Path(os.environ.get(
        "NEDVIGA_DRIFT_FILE",
        str(Path.home() / ".cache" / "nedviga-cli" / "price_drift.jsonl"),
    ))


def record_price_drift(card_id: str, url: Optional[str],
                       title: Optional[str]) -> Path:
    """Карантин-событие: цена пропала после всех фолбэков. Возвращает путь к журналу."""
    path = drift_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    # v0.4.5 (review R15): drift-журнал в ~/.cache не должен нести заголовок и
    # полный url (в title бывают ПДн) — только id и host источника.
    from urllib.parse import urlsplit
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "card_id": card_id,
        "url_host": urlsplit(url).netloc if url else None,
        "event": "price_missing_quarantined",
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return path
