"""v0.4.6 (the task brief) F-03: клиентские профили поиска (--profile).

Инварианты:
- пресеты parents/lnfnt задают базовые значения фильтров;
- любой явно переданный CLI-аргумент переопределяет поле профиля;
- запуск БЕЗ --profile бьёт ровно то же, что и до v0.4.6 (backcompat);
- неизвестный профиль: envelope reason="unknown_profile" + список доступных,
  exit code 3, search не вызывается.
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import patch

from nedviga.cli import main
from nedviga.profiles import (
    BUILTIN_PROFILES,
    UnknownProfileError,
    available_profiles,
    get_profile,
)


def _run_search_cli(capsys, argv: list[str]) -> tuple[int, dict, dict]:
    """main(search) с заглушкой cian_live.search; возвращает (code, envelope, kwargs)."""
    seen: dict = {}

    def fake_search(**kwargs):
        seen.update(kwargs)
        return []

    with patch("nedviga.cli.search", side_effect=fake_search):
        code = main(["search", "--source", "cian", *argv])
    out = capsys.readouterr().out
    payload = json.loads(out) if out.strip() else {}
    return code, payload, seen


# ------------------------------------------------------------------ модуль


def test_builtin_profiles_shape_per_spec():
    assert set(BUILTIN_PROFILES) >= {"parents", "lnfnt"}
    parents = BUILTIN_PROFILES["parents"]
    assert parents["rooms"] == 2
    assert parents["floor_not_first"] is True
    assert parents["min_house_floors"] == 10
    assert parents["geo_districts"] == ["ЮАО", "ЮЗАО"]
    assert parents["kitchen_min"] == 7.5
    assert parents["price_max"] == 20_000_000
    assert parents["metro_walk_max"] == 20
    assert parents["strict_mkad"] is True
    assert parents["only_flat"] is True
    assert parents["no_shares"] is True
    assert parents["no_auction"] is True

    lnfnt = BUILTIN_PROFILES["lnfnt"]
    assert lnfnt["price_max"] == 16_000_000
    assert lnfnt["floor_not_first"] is True
    assert lnfnt["min_house_floors"] == 12
    assert lnfnt["geo_districts"] == ["ЗАО", "ЮАО", "ЮВАО"]
    assert lnfnt["kitchen_min"] == 8.0
    assert lnfnt["strict_mkad"] is True
    assert lnfnt["only_flat"] is True
    assert lnfnt["no_shares"] is True
    assert lnfnt["no_auction"] is True


def test_get_profile_unknown_raises():
    with pytest.raises(UnknownProfileError) as exc_info:
        get_profile("no-such-profile")
    assert "no-such-profile" in str(exc_info.value)
    assert "parents" in exc_info.value.known


# --------------------------------------------------------------------- CLI


def test_profile_parents_applies_defaults(capsys):
    code, payload, kwargs = _run_search_cli(capsys, ["--profile", "parents"])
    assert code == 0, payload
    assert kwargs["rooms"] == 2
    assert kwargs["floor_not_first"] is True
    assert kwargs["min_house_floors"] == 10
    assert kwargs["geo_districts"] == "ЮАО,ЮЗАО"
    assert kwargs["kitchen_min"] == 7.5
    assert kwargs["price_max"] == 20_000_000
    assert kwargs["metro_walk_max"] == 20
    assert kwargs["strict_mkad"] is True
    assert kwargs["only_flat"] is True
    assert kwargs["no_shares"] is True
    assert kwargs["no_auction"] is True
    # гео/строгий МКАД — forcing-фильтры: гидрация включается как обычно
    assert kwargs["hydrate"] is True
    assert payload["metadata"]["profile"] == "parents"


def test_profile_lnfnt_applies_defaults(capsys):
    code, payload, kwargs = _run_search_cli(capsys, ["--profile", "lnfnt"])
    assert code == 0, payload
    assert kwargs["price_max"] == 16_000_000
    assert kwargs["floor_not_first"] is True
    assert kwargs["min_house_floors"] == 12
    assert kwargs["geo_districts"] == "ЗАО,ЮАО,ЮВАО"
    assert kwargs["kitchen_min"] == 8.0
    assert kwargs["strict_mkad"] is True
    assert kwargs["only_flat"] is True
    assert kwargs["no_shares"] is True
    assert kwargs["no_auction"] is True
    assert kwargs["rooms"] is None  # lnfnt не задаёт комнаты
    assert payload["metadata"]["profile"] == "lnfnt"


def test_cli_arg_overrides_profile(capsys):
    code, _payload, kwargs = _run_search_cli(
        capsys, ["--profile", "parents", "--price-max", "18000000"]
    )
    assert code == 0
    assert kwargs["price_max"] == 18_000_000.0  # CLI победил профиль
    assert kwargs["rooms"] == 2  # остальное из профиля осталось


def test_cli_floor_flag_overrides_profile_bool(capsys):
    # store_true: явный флаг не может «выключить» профильный True,
    # но явное значение из CLI не должно терять профильные поля
    code, _payload, kwargs = _run_search_cli(
        capsys, ["--profile", "lnfnt", "--kitchen-min", "10"]
    )
    assert code == 0
    assert kwargs["kitchen_min"] == 10.0
    assert kwargs["price_max"] == 16_000_000


def test_unknown_profile_returns_error_exit_3(capsys):
    code, payload, kwargs = _run_search_cli(capsys, ["--profile", "chayka"])
    assert code == 3
    assert payload["status"] == "error"
    assert payload["reason"] == "unknown_profile"
    assert payload["data"]["requested_profile"] == "chayka"
    assert set(payload["data"]["available_profiles"]) >= {"parents", "lnfnt"}
    assert kwargs == {}  # search не вызывался


def test_no_profile_backcompat(capsys):
    """Без --profile kwargs равны до-v046 дефолтам argparse."""
    code, payload, kwargs = _run_search_cli(capsys, [])
    assert code == 0
    expected_defaults = {
        "deal_type": None,
        "rooms": None,
        "price_min": None,
        "price_max": None,
        "kitchen_min": None,
        "floor_not_first": False,
        "min_house_floors": None,
        "geo_districts": None,
        "limit": None,
        "page": 1,
        "pages": None,
        "metro_walk_max": None,
        "hydrate": False,
        "no_auction": False,
        "only_auction": False,
        "workers": 4,
        "strict_mkad": False,
        "only_flat": False,
        "no_shares": False,
        "exclude_legal_risks": False,
    }
    assert kwargs == expected_defaults
    assert "profile" not in payload["metadata"]
    assert payload["metadata"]["contacts_open"] is False


def test_custom_profile_from_env_file(capsys, tmp_path, monkeypatch):
    custom = tmp_path / "profiles.json"
    custom.write_text(
        json.dumps({"dacha": {"rooms": 4, "price_max": 5000000}}), encoding="utf-8"
    )
    monkeypatch.setenv("NEDVIGA_PROFILES_JSON", str(custom))
    assert set(available_profiles()) >= {"parents", "lnfnt", "dacha"}
    code, _payload, kwargs = _run_search_cli(capsys, ["--profile", "dacha"])
    assert code == 0
    assert kwargs["rooms"] == 4
    assert kwargs["price_max"] == 5_000_000
    # валидация поля: чужие ключи из файла не попадают в kwargs
    assert set(kwargs) <= {
        "deal_type", "rooms", "price_min", "price_max", "kitchen_min",
        "floor_not_first", "min_house_floors", "geo_districts", "limit",
        "page", "pages", "metro_walk_max", "hydrate", "no_auction",
        "only_auction", "workers", "strict_mkad", "only_flat", "no_shares",
        "exclude_legal_risks",
    }
