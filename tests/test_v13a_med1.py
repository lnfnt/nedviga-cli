# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 lnfnt <lnfnt@proton.me>

"""v13a PHASE T (RED): MEDIUM S1-F7..S1-F12 (адит unified-audit-2026-10-30).

Только тесты. RED = «ожидаемое поведение после фикса».
Изоляция: env через monkeypatch, файлы в tmp_path, сеть не трогаем (моки).
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

from nedviga.adaptive_selectors import extract_price_adaptive
from nedviga.cian_card import _normalize_number
from nedviga.cli import main
from nedviga import graph as graph_mod


# ---------------------------------------------------------------------------
# S1-F7 — adaptive-прайс: ипотека/история/склейка цифр не дают ложный прайс
# ---------------------------------------------------------------------------

class TestS1F7AdaptivePriceNoFalsePositives:
    def test_mortgage_line_is_not_price(self):
        html = (
            "<div data-name='MortgageBanner'>ипотека от 45 000 ₽</div>"
            "<div>8 600 000 ₽</div>"
        )
        assert extract_price_adaptive(html) == 8_600_000.0

    def test_price_history_beats_first_price(self):
        html = (
            "<div id='history'>Было: 12 900 000 ₽</div>"
            "<div itemprop='price' content='9800000'>9 800 000 ₽</div>"
        )
        assert extract_price_adaptive(html) == 9_800_000.0

    def test_glued_digits_are_not_price(self):
        # маркер price + текст без якоря валюты: раньше PRICE_CLEAN_RE
        # склеивал «64 м²: 8 700 000» в 648700000
        html = "<div data-name='Price'>64 м²: 8 700 000</div>"
        p = extract_price_adaptive(html)
        assert p != 648_700_000.0
        assert p is None or abs(p - 8_700_000.0) < 1.0


# ---------------------------------------------------------------------------
# S1-F8 — CIAN search: дрейф → exit 3/source_disabled, не пустой ok
# ---------------------------------------------------------------------------

class TestS1F8CianSearchDrift:
    def test_drift_page_raises_fetch_error(self, monkeypatch):
        """Где-то на площадке сменён поиск — страница без выдачи и без
        контейнера офферов не может быть «пустым ok»."""
        from nedviga.cian_live import search, FetchError

        drift = "<html><body><div class='layout'>Наш сайт обновляется</div></body></html>"
        with patch("nedviga.cian_live._requests_get_search", return_value=None), \
             patch("nedviga.cian_live._requests_get_card", return_value=None), \
             patch("nedviga.cian_live.native_fetch", return_value=drift):
            try:
                cards = search(rooms=2)
            except FetchError:
                return  # ok — дрейф подняли
            raise AssertionError(f"дрейф отдали как данные: {cards}")

    def test_drift_page_cli_exit_3_not_empty_ok(self, capsys):
        drift = "<html><body><div class='layout'>Наш сайт обновляется</div></body></html>"
        with patch("nedviga.cian_live._requests_get_search", return_value=None), \
             patch("nedviga.cian_live._requests_get_card", return_value=None), \
             patch("nedviga.cian_live.native_fetch", return_value=drift):
            code = main(["search", "--source", "cian", "--json"])
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert code == 3, captured.err
        assert payload["status"] != "ok"

    def test_genuine_empty_offerslist_still_allowed(self, capsys):
        """Контроль: настоящий пустой контейнер выдачи — легальный ok/[]"""
        html = "<html><body><div data-name='OffersList'></div></body></html>"
        with patch("nedviga.cian_live._requests_get_search", return_value=None), \
             patch("nedviga.cian_live._requests_get_card", return_value=None), \
             patch("nedviga.cian_live.native_fetch", return_value=html):
            code = main(["search", "--source", "cian", "--json"])
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert code == 0
        assert payload["status"] == "ok"
        assert payload["data"] == []


# ---------------------------------------------------------------------------
# S1-F9 — graph.route: хвост до цели, не до lon узла
# ---------------------------------------------------------------------------

class TestS1F9RouteTailToTarget:
    def test_tail_counts_to_target_point(self, monkeypatch):
        # s = узел 'a' (точка старта совпадает с узлом), t = узел 'b';
        # точка цели — 0.003° восточнее узла 'b' (~187 м), но в радиусе снапа.
        g = graph_mod._Graph(
            nodes={"a": (55.75, 37.60), "b": (55.751, 37.609)},
            edges={"a": [("b", 560.0)], "b": []},
            version=1,
            built_at="t",
        )
        monkeypatch.setattr(graph_mod, "load_graph", lambda explicit=None: g)
        meters, provider = graph_mod.route(55.75, 37.60, 55.751, 37.612)
        assert provider == "graph_local"
        # баг: хвост до цели считался до (mlat, lon узла) = 0 → всего 560 м
        assert 600 <= meters <= 900, meters


# ---------------------------------------------------------------------------
# S1-F10 — metro_directory: битый/подменённый JSON отбрасывается
# ---------------------------------------------------------------------------

def _reset_metro_dir(monkeypatch, content: str, tmp_path: Path) -> None:
    f = tmp_path / "metro_directory.json"
    f.write_text(content, encoding="utf-8")
    monkeypatch.setenv("NEDVIGA_METRO_DIR", str(f))
    monkeypatch.setattr("nedviga.metro_vestibules._GENERATED_CACHE", None)


class TestS1F10MetroDirectoryIntegrity:
    def test_broken_json_is_discarded(self, tmp_path, monkeypatch):
        _reset_metro_dir(monkeypatch, "{not json garbage", tmp_path)
        from nedviga.metro_vestibules import get_vestibules
        vests = get_vestibules("Медведково")
        assert vests, "битый JSON не должен гасить рабочий справочник"

    def test_env_poisoned_structure_is_discarded(self, tmp_path, monkeypatch):
        _reset_metro_dir(
            monkeypatch,
            json.dumps({
                "скрытыйпроход": {
                    "name": "Победа",
                    "vestibules": [{"name": "x", "lat": "не число", "lon": None}],
                }
            }),
            tmp_path,
        )
        from nedviga.metro_vestibules import get_vestibules
        assert get_vestibules("скрытыйпроход") is None

    def test_env_wrong_shape_does_not_crash_dict_contract(self, tmp_path, monkeypatch):
        _reset_metro_dir(monkeypatch, json.dumps(["not", "a", "dict"]), tmp_path)
        from nedviga.metro_vestibules import all_stations, get_vestibules
        assert isinstance(all_stations(), dict)
        assert get_vestibules("байтук") is None

    def test_env_entry_not_dict_does_not_crash(self, tmp_path, monkeypatch):
        _reset_metro_dir(
            monkeypatch,
            json.dumps({"байтук": "строка вместо станции"}),
            tmp_path,
        )
        from nedviga.metro_vestibules import get_vestibules
        assert get_vestibules("байтук") is None


# ---------------------------------------------------------------------------
# S1-F11 — avito live: ошибки браузера без proxy-creds в reason
# ---------------------------------------------------------------------------

class TestS1F11AvitoErrorReasonNoCreds:
    def test_browser_error_hides_proxy_credentials(self, monkeypatch, capsys):
        monkeypatch.setenv(
            "NEDVIGA_EGRESS_PROXY",
            "http://secretuser:secretpass@127.0.0.1:9377",
        )
        fake_sync = types.ModuleType("camoufox.sync_api")

        def _boom(*a, **kw):
            raise RuntimeError(
                "net::ERR_TUNNEL_CONNECTION_FAILED at proxy "
                "http://secretuser:secretpass@127.0.0.1:9377"
            )

        fake_sync.Camoufox = _boom
        fake_cam = types.ModuleType("camoufox")
        fake_cam.sync_api = fake_sync
        monkeypatch.setitem(sys.modules, "camoufox", fake_cam)
        monkeypatch.setitem(sys.modules, "camoufox.sync_api", fake_sync)

        code = main([
            "search", "--source", "avito", "--live",
            "--catalog", "https://www.avito.ru/moskva/kvartiry",
            "--json",
        ])
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert code == 3
        assert payload["status"] == "error"
        text = json.dumps(payload, ensure_ascii=False)
        assert "secretpass" not in text
        assert "secretuser" not in text


# ---------------------------------------------------------------------------
# S1-F12 — _normalize_number сохраняет минус
# ---------------------------------------------------------------------------

class TestS1F12NormalizeNumberMinus:
    def test_negative_integer(self):
        assert _normalize_number("-5") == -5.0

    def test_negative_with_grouping_and_comma(self):
        assert _normalize_number("-311 808,12") == -311808.12

    def test_negative_decimal(self):
        assert _normalize_number("-0.5") == -0.5

    def test_positive_unaffected(self):
        assert _normalize_number("5") == 5.0
