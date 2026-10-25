"""v0.4.6 (the task brief F-03): именованные профили поиска (client search profiles).

CLI: ``nedviga-cli search --profile parents [аргументы…]``

Семантика:
- профиль задаёт базовые значения фильтров (defaults);
- любой явно переданный CLI-аргумент переопределяет поле профиля;
- без ``--profile`` поведение не меняется (инвариант обратной совместимости);
- неизвестный профиль -> :class:`UnknownProfileError` (CLI: envelope
  ``reason="unknown_profile"``, exit code 3).

Пресеты встроены в модуль; дополнительные/переопределённые профили могут
приходить из JSON-файла, путь которого задан переменной окружения
``NEDVIGA_PROFILES_JSON`` (структура: ``{"<name>": {"<field>": value}}``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# Булевы флаги search: CLI-значение True трактуется как «задано явно».
BOOL_FIELDS = {"floor_not_first", "strict_mkad", "only_flat", "no_shares", "no_auction", "no_gas"}
# Значимые поля: CLI-значение «не None» трактуется как «задано явно».
VALUE_FIELDS = {
    "rooms",
    "price_min",
    "price_max",
    "kitchen_min",
    "min_house_floors",
    "geo_districts",
    "metro_walk_max",
}
_ALLOWED_FIELDS = BOOL_FIELDS | VALUE_FIELDS

# Встроенные пресеты (ТЗ the task brief §3.1, автор agent-profile).
BUILTIN_PROFILES: dict[str, dict[str, Any]] = {
    "parents": {
        "rooms": 2,
        "floor_not_first": True,
        "min_house_floors": 10,
        "geo_districts": ["ЮАО", "ЮЗАО"],
        "kitchen_min": 7.5,
        "price_max": 20_000_000,
        "metro_walk_max": 20,
        "strict_mkad": True,
        "only_flat": True,
        "no_shares": True,
        "no_auction": True,
    },
    "lnfnt": {
        "price_max": 16_000_000,
        "floor_not_first": True,
        "min_house_floors": 12,
        "geo_districts": ["ЗАО", "ЮАО", "ЮВАО"],
        "kitchen_min": 8.0,
        "strict_mkad": True,
        "only_flat": True,
        "no_shares": True,
        "no_auction": True,
    },
}

_ENV_VAR = "NEDVIGA_PROFILES_JSON"


class UnknownProfileError(ValueError):
    """Профиль с таким именем не найден (ни во встроенных, ни в файле)."""

    def __init__(self, requested: str, known: list[str]) -> None:
        super().__init__(f"unknown search profile '{requested}'")
        self.requested = requested
        self.known = list(known)


def load_profiles() -> dict[str, dict[str, Any]]:
    """Встроенные профили + опциональный override-файл из NEDVIGA_PROFILES_JSON.

    Некорректный/нечитаемый файл не роняет CLI: fallback на встроенные.
    Поля, не входящие в известные фильтры search, из файла отбрасываются.
    """
    profiles: dict[str, dict[str, Any]] = {
        name: dict(values) for name, values in BUILTIN_PROFILES.items()
    }
    path = os.environ.get(_ENV_VAR, "").strip()
    if path:
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = None
        if isinstance(raw, dict):
            for name, values in raw.items():
                if isinstance(name, str) and isinstance(values, dict):
                    merged = dict(profiles.get(name, {}))
                    merged.update(
                        {k: v for k, v in values.items() if k in _ALLOWED_FIELDS}
                    )
                    profiles[name] = merged
    return profiles


def available_profiles() -> list[str]:
    return sorted(load_profiles())


def get_profile(name: str) -> dict[str, Any]:
    profiles = load_profiles()
    if name not in profiles:
        raise UnknownProfileError(name, available_profiles())
    return profiles[name]


def apply_profile(args: Any, name: str) -> list[str]:
    """Применить профиль к argparse-namespace; явные CLI-аргументы сильнее.

    Возвращает список применённых полей (для metadata).
    """
    applied: list[str] = []
    for field, value in get_profile(name).items():
        if isinstance(value, list):
            value = ",".join(str(item) for item in value)
        current = getattr(args, field, None)
        if field in BOOL_FIELDS and bool(current):
            continue  # флаг задан в CLI
        if field in VALUE_FIELDS and current is not None:
            continue  # значение задано в CLI
        setattr(args, field, value)
        applied.append(field)
    return applied
