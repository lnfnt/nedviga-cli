"""Offline tests for the live native browser integration (M3).

All browser fetches are mocked; no real network traffic is performed.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from nedviga.cli import main
from nedviga.cian_card import parse_card
from nedviga.cian_live import (
    ChallengeError,
    FetchError,
    _build_search_url,
    _post_filter_cards,
    detect_challenge,
    get_card,
    search,
)
from nedviga.export_html import export_html
from nedviga.models import Geo, ListingCard, Parameters, Pricing

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestChallengeDetection:
    def test_empty_html_is_not_challenge(self):
        assert detect_challenge("") == (False, None)

    def test_smartcaptcha_detected(self):
        html = "<html><body>SmartCaptcha challenge</body></html>"
        is_challenge, reason = detect_challenge(html)
        assert is_challenge is True
        assert "smartcaptcha" in reason

    def test_cloudflare_detected(self):
        html = "<html><div class='cf-turnstile'>checking</div></html>"
        is_challenge, reason = detect_challenge(html)
        assert is_challenge is True
        assert "cf-turnstile" in reason

    def test_access_denied_detected(self):
        html = "<html><body>Доступ временно ограничен</body></html>"
        is_challenge, reason = detect_challenge(html)
        assert is_challenge is True
        assert "доступ" in reason

    def test_http_403_hint(self):
        assert detect_challenge("<html></html>", http_hint="403") == (True, "http_403")

    def test_http_429_hint(self):
        assert detect_challenge("<html></html>", http_hint="429") == (True, "http_429")

    def test_normal_page_with_waf_verdict_js_is_not_challenge(self):
        # Regression (2026-09-21 retest v3): Cian's legitimate inline JS contains
        # const e="waf-verdict" — a bare "waf" marker flagged every normal page
        # (348k listings) as a challenge. The string "waf-verdict" must NOT be a
        # marker, and a page containing it alongside real offer data stays OK.
        html = '<html><script>const e="waf-verdict";</script><body>offers here</body></html>'
        assert detect_challenge(html) == (False, None)


class TestDefaultStateParsing:
    """Regression (2026-09-21): live cards carry the offer payload inside
    window._cianConfig['frontend-offer-card'] defaultState.offerData — the old
    window._offersData island is gone. Fixture is captured from a live card."""

    def _card(self):
        html = _fixture("cian_card_newbuilding_defaultstate.html")
        return parse_card(html)

    def test_pricing_from_default_state(self):
        card = self._card()
        assert card.pricing.price_total_rub == 15_256_100.0
        assert card.pricing.price_per_m2_rub == 250_100.0
        assert len(card.pricing.price_history) >= 3
        # chronological order
        dates = [p.date for p in card.pricing.price_history]
        assert dates == sorted(dates)

    def test_parameters_from_default_state(self):
        p = self._card().parameters
        assert p.rooms == 2
        assert p.area_total_m2 == 61.0
        assert p.area_living_m2 == 32.8
        assert p.area_kitchen_m2 == 22.1
        assert p.floor == 5
        assert p.floors_total == 20
        assert p.ceiling_height_m == 3.05
        assert p.window_view == "yard"

    def test_building_and_geo_from_default_state(self):
        card = self._card()
        assert card.building.building_type == "monolith"
        assert card.building.year_built == 2024
        assert card.building.elevators_passenger == 7
        assert card.geo.lat is not None
        assert card.geo.lon is not None
        assert card.geo.district == "СВАО"
        assert card.geo.area_name == "Северный"

    def test_metro_time_extracted_from_station_text(self):
        # live newbuilding cards render 'Станция 5 мин.' as a single string
        metro = self._card().geo.cian_claimed_metro
        assert metro is not None
        assert "5 мин" not in (metro.station or "")
        assert metro.claimed_time_minutes == 5


class TestGetCard:
    def test_get_card_parses_fixture(self):
        html = _fixture("cian_card_full_panel.html")
        with patch("nedviga.cian_live._requests_get_search", return_value=None), \
             patch("nedviga.cian_live._requests_get_card", return_value=None), \
             patch("nedviga.cian_live.native_fetch", return_value=html):
            card = get_card("https://www.cian.ru/sale/flat/310123456/")
        assert card.id == "cian-310123456"
        assert card.source == "cian"
        assert card.pricing.price_total_rub == 16_900_000

    def test_get_card_by_numeric_id(self):
        html = _fixture("cian_card_studio_minimal.html")
        with patch("nedviga.cian_live._requests_get_search", return_value=None), \
             patch("nedviga.cian_live._requests_get_card", return_value=None), \
             patch("nedviga.cian_live.native_fetch", return_value=html):
            card = get_card("310123457")
        assert card.id == "cian-310123457"

    def test_get_card_raises_challenge_error(self):
        html = "<html><body>SmartCaptcha</body></html>"
        with patch("nedviga.cian_live._requests_get_search", return_value=None), \
             patch("nedviga.cian_live._requests_get_card", return_value=None), \
             patch("nedviga.cian_live.native_fetch", return_value=html):
            with pytest.raises(ChallengeError):
                get_card("https://www.cian.ru/sale/flat/1/")

    def test_get_card_raises_fetch_error_on_parse_failure(self):
        html = "<html><body>nothing useful</body></html>"
        with patch("nedviga.cian_live._requests_get_search", return_value=None), \
             patch("nedviga.cian_live._requests_get_card", return_value=None), \
             patch("nedviga.cian_live.native_fetch", return_value=html):
            with pytest.raises(FetchError):
                get_card("https://www.cian.ru/sale/flat/1/")


class TestSearch:
    def test_search_extracts_links(self):
        html = _fixture("cian_search_results.html")
        with patch("nedviga.cian_live._requests_get_search", return_value=None), \
             patch("nedviga.cian_live._requests_get_card", return_value=None), \
             patch("nedviga.cian_live.native_fetch", return_value=html):
            cards = search(rooms=2)
        assert len(cards) == 3
        assert cards[0].id == "cian-310123456"
        assert cards[1].id == "cian-310123457"
        assert cards[2].id == "cian-310123458"

    def test_search_respects_limit(self):
        html = _fixture("cian_search_results.html")
        with patch("nedviga.cian_live._requests_get_search", return_value=None), \
             patch("nedviga.cian_live._requests_get_card", return_value=None), \
             patch("nedviga.cian_live.native_fetch", return_value=html):
            cards = search(rooms=2, limit=2)
        assert len(cards) == 2

    def test_search_empty_result_is_allowed(self):
        html = "<html><body><div data-name='OffersList'></div></body></html>"
        with patch("nedviga.cian_live._requests_get_search", return_value=None), \
             patch("nedviga.cian_live._requests_get_card", return_value=None), \
             patch("nedviga.cian_live.native_fetch", return_value=html):
            cards = search(rooms=2)
        assert cards == []

    def test_search_raises_challenge_error(self):
        html = "<html><body>Доступ ограничен</body></html>"
        with patch("nedviga.cian_live._requests_get_search", return_value=None), \
             patch("nedviga.cian_live._requests_get_card", return_value=None), \
             patch("nedviga.cian_live.native_fetch", return_value=html):
            with pytest.raises(ChallengeError):
                search(rooms=2)


class TestCliLiveNative:
    """In-process CLI tests with mocked native browser (no real network)."""

    def test_cli_get_card_ok(self, capsys):
        html = _fixture("cian_card_full_panel.html")
        with patch("nedviga.cian_live._requests_get_search", return_value=None), \
             patch("nedviga.cian_live._requests_get_card", return_value=None), \
             patch("nedviga.cian_live.native_fetch", return_value=html):
            code = main(
                ["get-card", "https://www.cian.ru/sale/flat/310123456/", "--json"]
            )
        captured = capsys.readouterr()
        assert code == 0, captured.err
        payload = json.loads(captured.out)
        assert payload["status"] == "ok"
        assert payload["data"]["id"] == "cian-310123456"
        assert payload["metadata"]["engine"] == "native"

    def test_cli_get_card_challenge_returns_degraded(self, capsys):
        html = "<html><body>SmartCaptcha</body></html>"
        with patch("nedviga.cian_live._requests_get_search", return_value=None), \
             patch("nedviga.cian_live._requests_get_card", return_value=None), \
             patch("nedviga.cian_live.native_fetch", return_value=html):
            code = main(["get-card", "https://www.cian.ru/sale/flat/1/", "--json"])
        captured = capsys.readouterr()
        assert code == 2, captured.err
        payload = json.loads(captured.out)
        assert payload["status"] == "degraded"
        assert "challenge" in payload["reason"]

    def test_cli_search_ok(self, capsys):
        html = _fixture("cian_search_results.html")
        with patch("nedviga.cian_live._requests_get_search", return_value=None), \
             patch("nedviga.cian_live._requests_get_card", return_value=None), \
             patch("nedviga.cian_live.native_fetch", return_value=html):
            code = main(["search", "--source", "cian", "--limit", "2", "--json"])
        captured = capsys.readouterr()
        assert code == 0, captured.err
        payload = json.loads(captured.out)
        assert payload["status"] == "ok"
        assert len(payload["data"]) == 2

    def test_cli_search_challenge_returns_degraded(self, capsys):
        html = "<html><body>cloudflare challenge</body></html>"
        with patch("nedviga.cian_live._requests_get_search", return_value=None), \
             patch("nedviga.cian_live._requests_get_card", return_value=None), \
             patch("nedviga.cian_live.native_fetch", return_value=html):
            code = main(["search", "--source", "cian", "--json"])
        captured = capsys.readouterr()
        assert code == 2, captured.err
        payload = json.loads(captured.out)
        assert payload["status"] == "degraded"

    def test_cli_search_unsupported_source_returns_error(self, capsys):
        # v0.5.13: avito ТЕПЕРЬ поддерживаемый источник (the task brief) — контракт
        # «unsupported» проверяем на реально несуществующем source.
        code = main(["search", "--source", "sbornet", "--json"])
        captured = capsys.readouterr()
        assert code == 3, captured.err
        payload = json.loads(captured.out)
        assert payload["status"] == "error"
        assert payload["reason"] == "unsupported_source"


class TestBuildSearchUrl:
    """F-01: _build_search_url must encode all CLI filters."""

    def test_kitchen_min_in_url(self):
        url = _build_search_url(kitchen_min=7.5)
        assert "kitchen%5B0%5D=7.5" in url

    def test_kitchen_min_integer(self):
        url = _build_search_url(kitchen_min=10)
        assert "kitchen%5B0%5D=10" in url

    def test_rooms_still_encoded(self):
        url = _build_search_url(rooms=2)
        assert "room2=1" in url

    def test_no_kitchen_min_omits_param(self):
        url = _build_search_url()
        assert "kitchen" not in url


class TestPostFilterCards:
    """F-01: client-side post-filtering must work on hydrated cards."""

    def _card(self, *, floor=None, floors_total=None, district=None):
        return ListingCard(
            id="cian-1",
            source="cian",
            url="https://cian.ru/1/",
            parameters=Parameters(floor=floor, floors_total=floors_total),
            geo=Geo(district=district),
        )

    def test_floor_not_first_excludes_first_floor(self):
        cards = [self._card(floor=1), self._card(floor=5)]
        result = _post_filter_cards(cards, floor_not_first=True)
        assert len(result) == 1
        assert result[0].parameters.floor == 5

    def test_floor_not_first_keeps_unknown(self):
        cards = [self._card()]
        result = _post_filter_cards(cards, floor_not_first=True)
        assert len(result) == 1

    def test_min_house_floors_excludes_small_buildings(self):
        cards = [self._card(floors_total=3), self._card(floors_total=12)]
        result = _post_filter_cards(cards, min_house_floors=5)
        assert len(result) == 1
        assert result[0].parameters.floors_total == 12

    def test_geo_districts_filter(self):
        cards = [self._card(district="ЦАО"), self._card(district="САО")]
        result = _post_filter_cards(cards, geo_districts="ЦАО")
        assert len(result) == 1
        assert result[0].geo.district == "ЦАО"

    def test_limit_slices_results(self):
        cards = [self._card() for _ in range(5)]
        for i, c in enumerate(cards):
            c.id = f"cian-{i}"
        result = _post_filter_cards(cards, limit=2)
        assert len(result) == 2


class TestHttpHintPlumbing:
    """F-05: get_card/search must pass http_hint from fetch to detect_challenge."""

    def test_get_card_passes_http_hint_403_raises_challenge(self):
        def mock_fetch(url, **kwargs):
            from nedviga import browser_native as bn
            bn._native_tls.http_status = 403
            return "<html><body>normal page</body></html>"

        with patch("nedviga.cian_live._requests_get_search", return_value=None), \
             patch("nedviga.cian_live.native_fetch", side_effect=mock_fetch):
            with pytest.raises(ChallengeError):
                get_card("https://www.cian.ru/sale/flat/1/")

    def test_get_card_passes_http_hint_200_ok(self):
        html = _fixture("cian_card_full_panel.html")

        def mock_fetch(url, **kwargs):
            from nedviga import browser_native as bn
            bn._native_tls.http_status = 200
            return html

        with patch("nedviga.cian_live._requests_get_search", return_value=None), \
             patch("nedviga.cian_live.native_fetch", side_effect=mock_fetch):
            card = get_card("https://www.cian.ru/sale/flat/310123456/")
        assert card.id == "cian-310123456"

    def test_search_passes_http_hint_429_raises_challenge(self):
        def mock_fetch(url, **kwargs):
            from nedviga import browser_native as bn
            bn._native_tls.http_status = 429
            return "<html><body>normal search results</body></html>"

        # v0.3.3: search использует requests-first; мокаем и его
        # (requests возвращает короткое тело -> сразу fallback на native_fetch,
        #  где 429 -> ChallengeError)
        with patch("nedviga.cian_live.native_fetch", side_effect=mock_fetch), \
             patch("nedviga.cian_live._requests_get_search", return_value=None):
            with pytest.raises(ChallengeError):
                search(rooms=2)


class TestExportHtmlXss:
    """F-03: HTML catalog must escape card fields that reach the DOM."""

    def test_title_script_tag_is_escaped(self, tmp_path: Path):
        card = ListingCard(
            id="cian-xss-1",
            source="cian",
            url="https://www.cian.ru/sale/flat/1/",
            title='<script>alert("owned")</script>',
            pricing=Pricing(price_total_rub=10_000_000),
            parameters=Parameters(area_total_m2=50.0, rooms=2, floor=5, floors_total=12),
        )
        out = export_html([card], tmp_path / "catalog.html")
        html = out.read_text(encoding="utf-8")

        assert '<script>alert' not in html
        assert "&lt;script" in html
        assert '&quot;owned&quot;' in html
