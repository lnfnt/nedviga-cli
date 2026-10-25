"""Directory of Moscow metro vestibules with real WGS-84 coordinates.

The coordinates are taken from public cartographic sources
(OpenStreetMap / Wikipedia) and represent the actual street-level exits.
"""

from __future__ import annotations

import json
from pathlib import Path


def _normalize(name: str) -> str:
    """Normalize a station name for directory lookup."""
    return name.strip().casefold().replace("ё", "е")


#: Mapping station name -> list of (vestibule_name, lat, lon).
VESTIBULES: dict[str, list[tuple[str, float, float]]] = {
    # 1. Комсомольская (Sokolnicheskaya + Koltsevaya lines, Komsomolskaya square)
    _normalize("Комсомольская"): [
        ("Вестибюль на Комсомольской площади (Сокольническая линия)", 55.7753, 37.6555),
        ("Вестибюль у Ленинградского вокзала (Кольцевая линия)", 55.7747, 37.6548),
    ],
    # 2. Чертановская
    _normalize("Чертановская"): [
        ("Вестибюль 1 (южный)", 55.6405, 37.6067),
        ("Вестибюль 2 (северный)", 55.6412, 37.6073),
    ],
    # 3. Тверская
    _normalize("Тверская"): [
        ("Вестибюль на Пушкинской площади", 55.7648, 37.6042),
    ],
    # 4. Арбатская (Arbatsko-Pokrovskaya + Filyovskaya)
    _normalize("Арбатская"): [
        ("Вестибюль на улице Воздвиженка (Арбатско-Покровская линия)", 55.7523, 37.6039),
        ("Вестибюль у Старого Арбата (Филёвская линия)", 55.7521, 37.6019),
    ],
    # 5. Курская (Arbatsko-Pokrovskaya + Koltsevaya)
    _normalize("Курская"): [
        ("Вестибюль у Курского вокзала (Арбатско-Покровская линия)", 55.7572, 37.6591),
        ("Вестибюль на Земляном валу (Кольцевая линия)", 55.7566, 37.6597),
    ],
    # 6. Киевская (Filyovskaya + Arbatsko-Pokrovskaya + Koltsevaya)
    _normalize("Киевская"): [
        ("Вестибюль у Киевского вокзала (Филёвская линия)", 55.7440, 37.5666),
        ("Вестибюль на площади Киевского вокзала (Арбатско-Покровская линия)", 55.7437, 37.5645),
        ("Вестибюль на Киевской площади (Кольцевая линия)", 55.7436, 37.5663),
    ],
    # 7. Таганская (Tagansko-Krasnopresnenskaya + Koltsevaya)
    _normalize("Таганская"): [
        ("Вестибюль на Таганской площади (Таганско-Краснопресненская линия)", 55.7393, 37.6538),
        ("Вестибюль у Таганской радиальной (Кольцевая линия)", 55.7390, 37.6534),
    ],
    # 8. Баррикадная
    _normalize("Баррикадная"): [
        ("Вестибюль на Баррикадной улице", 55.7612, 37.5812),
    ],
    # 9. ВДНХ
    _normalize("ВДНХ"): [
        ("Вестибюль у главного входа ВДНХ", 55.8203, 37.6411),
    ],
    # 10. Сокольники
    _normalize("Сокольники"): [
        ("Вестибюль у Сокольнического круга", 55.7891, 37.6803),
    ],
    # 11. Автозаводская
    _normalize("Автозаводская"): [
        ("Вестибюль на Автозаводской улице", 55.7066, 37.6571),
    ],
    # 12. Пролетарская
    _normalize("Пролетарская"): [
        ("Вестибюль на Крутицком валу", 55.7319, 37.6658),
    ],
    # 13. Тульская
    _normalize("Тульская"): [
        ("Вестибюль на Большой Тульской улице", 55.7095, 37.6229),
    ],
    # 14. Нагатинская
    _normalize("Нагатинская"): [
        ("Вестибюль на Варшавском шоссе", 55.6830, 37.6224),
    ],
    # 15. Павелецкая (Zamoskvoretskaya + Koltsevaya)
    _normalize("Павелецкая"): [
        ("Вестибюль у Павелецкого вокзала (Замоскворецкая линия)", 55.7304, 37.6364),
        ("Вестибюль на Павелецкой площади (Кольцевая линия)", 55.7317, 37.6386),
    ],
}


def get_vestibules(station: str) -> list[tuple[str, float, float]] | None:
    """Return vestibule list for a station, or ``None`` if unknown.

    v0.2.0: сначала сгенерированный справочник из OSM
    (metro_directory.json, 237 станций метро + МЦД), затем ручной хардкод MVP.
    """
    k = _normalize(station)
    generated = _load_generated()
    if generated is not None and k in generated:
        entry = generated[k]
        return [(v["name"], v["lat"], v["lon"]) for v in entry["vestibules"]]
    return VESTIBULES.get(k)


_GENERATED_CACHE = None


def _load_generated() -> dict | None:
    """Load the generated OSM directory (metro_directory.json), cached."""
    global _GENERATED_CACHE
    if _GENERATED_CACHE is not None:
        return _GENERATED_CACHE
    candidates = [
        Path(__file__).parent / "metro_directory.json",
        Path(__file__).parent.parent / "metro_directory.json",
    ]
    import os
    env = os.environ.get("NEDVIGA_METRO_DIR")
    if env:
        candidates.insert(0, Path(env))
    for c in candidates:
        try:
            if c.exists():
                _GENERATED_CACHE = json.loads(c.read_text(encoding="utf-8"))
                return _GENERATED_CACHE
        except Exception:
            continue
    return None


# Директория станций из сгенерированного справочника (для CLI "list-stations" и тестов)
def all_stations() -> dict[str, dict]:
    """Return {norm_key: {name, transit_type, vestibules}} из сгенерированного справочника."""
    return _load_generated() or {}
