"""v0.5.14 (the task brief §2) rush почасовой web-прогноз — офлайн-тесты.

Сеть запрещена: _fetch_traffic мокается фикстурами innerText страницы
Яндекс Карт (формы из живого наблюдения 23.10).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from nedviga.cli import main
from nedviga.rush import parse_forecast_hours

# Живая форма (the task brief §2): «Пробки N баллов» + пары балл@час остатка дня
LIVE_TEXT = ("Дорожная ситуация сейчас\nПробки 6 баллов\n"
             "Средняя скорость 41 км/ч\n"
             "6 18 5 19 4 20 2 21 1 22 1 23")

FIX = Path(__file__).parent / "fixtures" / "rush_probki_forecast_2026-10.txt"


def _card(tmp_path):
    f = tmp_path / "card.json"
    f.write_text(json.dumps({"id": "cian-1", "source": "cian", "url": "u",
                             "title": "flat", "geo": {"lat": 55.6, "lon": 37.6}}),
                 encoding="utf-8")
    return f


# --- парсер ---

def test_forecast_parses_live_shape():
    got = parse_forecast_hours(LIVE_TEXT)
    assert got == [{"hour": 18, "balls": 6}, {"hour": 19, "balls": 5},
                   {"hour": 20, "balls": 4}, {"hour": 21, "balls": 2},
                   {"hour": 22, "balls": 1}, {"hour": 23, "balls": 1}]


def test_forecast_offline_fixture_file():
    got = parse_forecast_hours(FIX.read_text(encoding="utf-8"))
    assert [p["hour"] for p in got] == [18, 19, 20, 21, 22, 23]
    assert all(0 <= p["balls"] <= 10 for p in got)


def test_forecast_marker_only_returns_empty():
    assert parse_forecast_hours("Пробки 7 баллов") == []


def test_forecast_garbage_returns_empty():
    assert parse_forecast_hours("") == []
    assert parse_forecast_hours("никаких пробок тут нет") == []
    # балл@час с невалидным часом (25/99) -> не угадываем
    assert parse_forecast_hours("Пробки 4 балла\n9 25 3 99") == []
    # одна пара (>=2 чисел, но <2 пар) -> пусто
    assert parse_forecast_hours("Пробки 5 баллов\n3 19") == []


def test_forecast_hours_must_ascend():
    # убывающие часы = не прогноз остатка дня -> пусто
    assert parse_forecast_hours("Пробки 5 баллов\n9 19 8 17 7 16") == []


def test_forecast_skips_stray_number_run():
    # мусорный ряд «41 км/ч» короче 4 чисел — пропущен, прогноз найден дальше
    text = "Пробки 3 балла\n41 км/ч\n5 14 4 15 3 16"
    assert parse_forecast_hours(text) == [{"hour": 14, "balls": 5},
                                          {"hour": 15, "balls": 4},
                                          {"hour": 16, "balls": 3}]


# --- CLI ---

def test_rush_hour_hits_forecast(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("NEDVIGA_EGRESS_PROXY", "http://proxy:8080")
    with patch("nedviga.rush._fetch_traffic", return_value=LIVE_TEXT):
        code = main(["rush", "--file", str(_card(tmp_path)), "--hour", "19"])
    out = capsys.readouterr().out
    assert code == 0
    assert "прогноз на 19: 5 баллов" in out
    # обязательный дисклеймер всякий раз, когда прогноз показан
    assert "web-прогноз Яндекса, не гарантируется" in out


def test_rush_hour_absent_is_honest(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("NEDVIGA_EGRESS_PROXY", "http://proxy:8080")
    with patch("nedviga.rush._fetch_traffic", return_value=LIVE_TEXT):
        code = main(["rush", "--file", str(_card(tmp_path)), "--hour", "7"])
    out = capsys.readouterr().out
    assert code == 0
    assert "недоступен" in out
    assert "web-прогноз" in out
    assert "прогноз на 7:" not in out  # вымысла нет (строка «на 7: N баллов»)


def test_rush_without_hour_shows_forecast_table(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("NEDVIGA_EGRESS_PROXY", "http://proxy:8080")
    with patch("nedviga.rush._fetch_traffic", return_value=LIVE_TEXT):
        code = main(["rush", "--file", str(_card(tmp_path))])
    out = capsys.readouterr().out
    assert code == 0
    assert "Пробки сейчас: 6 баллов" in out
    assert "18:00" in out and "web-прогноз Яндекса, не гарантируется" in out


def test_rush_no_regression_bare_balls(tmp_path, monkeypatch, capsys):
    """Текст без прогноза -> вывод ровно как в 0.5.13.1 (никаких таблиц)."""
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("NEDVIGA_EGRESS_PROXY", "http://proxy:8080")
    with patch("nedviga.rush._fetch_traffic", return_value="7 баллов"):
        code = main(["rush", "--file", str(_card(tmp_path))])
    out = capsys.readouterr().out
    assert code == 0
    assert "Пробки сейчас: 7 баллов" in out
    assert "почасовой" not in out


def test_rush_hour_without_egress_honest(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("NEDVIGA_EGRESS_PROXY", raising=False)
    code = main(["rush", "--file", str(_card(tmp_path)), "--hour", "18"])
    out = capsys.readouterr().out
    assert code == 0
    assert "unavailable" in out
    assert "недоступен" in out and "web-прогноз" in out
