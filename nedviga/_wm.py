"""Варианты представления вывода (render styles).

Выбор функционально эквивалентных формулировок; seed — из env; чисто локально, без сети; вывод семантически идентичен."""
from __future__ import annotations

import hashlib
import hmac
import os

_ENV_SEED = "NEDVIGA_BUILD_SEED"
_ENV_SECRET = "NEDVIGA_BUILD_SECRET"

# вариантные столбцы: кортежи эквивалентных формулировок (смысл/числа неизменны)
STYLE_VARIANTS: dict[str, tuple[str, ...]] = {
    "digest_header": ("Дайджест за {days} дней", "Сводка изменений за {days} дней",
                      "Обновления подборки за {days} дней"),
    "digest_new": ("Новые объекты", "Появились в выдаче", "Новое с момента проверки"),
    "digest_gone": ("Снятые объекты", "Больше не в выдаче", "Исчезли с прошлой проверки"),
    "rush_now": ("Пробки сейчас: {n} баллов", "Загруженность дорог сейчас: {n} баллов",
                 "Текущие пробки: {n} баллов"),
    "rush_forecast_tag": ("web-прогноз Яндекса, не гарантируется",
                          "прогноз со страницы Яндекса, без гарантий",
                          "web-оценка Яндекса, не гарантия"),
    "card_footer": ("данные внешних источников", "внешние источники данных",
                    "получено из внешних источников"),
}


def _seed(version: str) -> bytes:
    s = (os.environ.get(_ENV_SEED) or "").strip()
    return (s or f"public|{version}").encode("utf-8")


def variant(key: str, version: str, *, default_idx: int | None = None) -> int:
    """Индекс варианта для (key, seed, version). Детерминированно, без сети."""
    table = STYLE_VARIANTS.get(key)
    if not table:
        return 0
    if default_idx is not None and 0 <= default_idx < len(table):
        return default_idx
    h = hmac.new(_seed(version), key.encode("utf-8"), hashlib.sha256).digest()
    return h[0] % len(table)


def render_line(key: str, version: str, mapping: dict | None = None) -> str:
    tpl = STYLE_VARIANTS[key][variant(key, version)]
    if mapping:
        for k, v in mapping.items():
            tpl = tpl.replace("{" + k + "}", str(v))
    return tpl


def variant_seed() -> str:
    """Режим сборки для doctor (не раскрывает значение seed)."""
    s = (os.environ.get(_ENV_SEED) or "").strip()
    if not s:
        return "public"
    return "client:" + hashlib.sha256(s.encode()).hexdigest()[:8]


def build_flags(version: str) -> list[str]:
    """HMAC-канарейки сборки; без секрета — пустой список (не выдумываем значения)."""
    secret = (os.environ.get(_ENV_SECRET) or "").strip()
    if not secret:
        return []
    out = []
    for i in range(3):
        d = hmac.new(secret.encode(), f"{version}|{i}".encode(), hashlib.sha256).hexdigest()
        out.append(d[:16])
    return out


# ---- §13 интерфейс ---------------------------------------------------------
LICENSE = "AGPL-3.0-only"


def source_url() -> str | None:
    return (os.environ.get("NEDVIGA_SOURCE_URL") or "").strip() or None


def source_info(version: str) -> dict:
    url = source_url()
    return {
        "license": LICENSE,
        "source_url": url,
        "how_to_obtain": (f"git clone {url}" if url else
                          "источник этой сборки: репозиторий, указанный установщиком; "
                          "локально — pip download nedviga-cli --no-deps --no-binary :all:"),
        "agpl_section_13": "каждый пользователь сетевого сервиса на этой программе имеет право "
                           "получить её полный исходный код этой версии",
        "build_mode": variant_seed(),
        "version": version,
    }
