"""v0.4.0 (ТЗ реалтора): tests for public SDK, realtor filters and field fixes."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import nedviga
from nedviga.cian_card import parse_card
from nedviga.cian_live import (
    _has_legal_risk,
    _is_apartment,
    _is_share,
    _is_strict_mkad,
    search,
)
from nedviga.cli import main
from nedviga.models import Building, Geo, ListingCard, Parameters, Pricing

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"


@pytest.fixture(autouse=True)
def _reset_native_http_status():
    """Prevent cross-test http_status leaks from test_live_native."""
    from nedviga.browser_native import _native_tls

    _native_tls.http_status = None


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _card(
    *,
    id: str = "cian-1",
    url: str = "https://www.cian.ru/sale/flat/1/",
    address: str | None = None,
    area_name: str | None = None,
    district: str | None = None,
    description: str | None = None,
    title: str | None = None,
    is_apartments: bool | None = None,
    category: str | None = None,
    share_amount: float | None = None,
    floors_total: int | None = None,
    floor: int | None = None,
    gas: bool | None = None,
) -> ListingCard:
    return ListingCard(
        id=id,
        source="cian",
        url=url,
        title=title,
        description_text=description,
        category=category,
        parameters=Parameters(
            floor=floor,
            floors_total=floors_total,
            share_amount=share_amount,
        ),
        building=Building(address_raw=address, gas=gas, is_apartments=is_apartments),
        geo=Geo(area_name=area_name, district=district),
    )


class TestPublicSdk:
    """Public API exported by nedviga package."""

    def test_top_level_functions_are_callable(self):
        assert callable(nedviga.search)
        assert callable(nedviga.get_card)
        assert callable(nedviga.export_html)
        assert callable(nedviga.walk_distance)

    def test_top_level_exceptions_exported(self):
        assert issubclass(nedviga.ChallengeError, Exception)
        assert issubclass(nedviga.FetchError, Exception)
        assert issubclass(nedviga.ParseError, Exception)

    def test_version_matches_pyproject(self):
        # version-agnostic инвариант: пакет и pyproject в одном шаге (вместо pinned 0.4.0)
        import re
        from pathlib import Path
        m = re.search(r'^version = "([^"]+)"',
                      Path(__file__).resolve().parents[1].joinpath("pyproject.toml").read_text(encoding="utf-8"),
                      re.M)
        assert m and nedviga.__version__ == m.group(1)

    def test_walk_distance_returns_typed_dict(self):
        with patch.object(nedviga, "walk_route") as mock_route:
            mock_route.return_value = {
                "target_station": "Чертановская",
                "target_vestibule": "Вестибюль 1",
                "walk_distance_meters": 1150,
                "walk_duration_minutes": 14,
                "routing_provider": "graph_local",
                "route_verified": True,
                "status": "ok",
                "reason": None,
            }
            result = nedviga.walk_distance(55.6385, 37.6025, "Чертановская")

        assert result["honest_walk_route"]["walk_distance_meters"] == 1150
        assert "honest_overclaim" not in result

    def test_walk_distance_with_claimed_time_includes_overclaim(self):
        with patch.object(nedviga, "walk_route") as mock_route:
            mock_route.return_value = {
                "target_station": "Чертановская",
                "target_vestibule": "Вестибюль 1",
                "walk_distance_meters": 1150,
                "walk_duration_minutes": 14,
                "routing_provider": "graph_local",
                "route_verified": True,
                "status": "ok",
                "reason": None,
            }
            result = nedviga.walk_distance(
                55.6385, 37.6025, "Чертановская", claimed_time=10
            )

        assert result["honest_overclaim"]["overclaim_minutes"] == 4
        assert result["honest_overclaim"]["flag"] is True

    def test_export_html_returns_path(self, tmp_path: Path):
        card = _card(title="Test", floor=5, floors_total=12)
        out = nedviga.export_html([card], tmp_path / "catalog.html")
        assert out.exists()
        assert "Test" in out.read_text(encoding="utf-8")


class TestRealtorFilters:
    """v0.4.0 combat filters."""

    def test_strict_mkad_detects_communaraka_in_address(self):
        card = _card(address="Москва, посёлок Коммунарка, ул. Липовый Парк")
        assert _is_strict_mkad(card) is True

    def test_strict_mkad_detects_zelenograd_in_area(self):
        card = _card(area_name="Зеленоград")
        assert _is_strict_mkad(card) is True

    def test_strict_mkad_detects_nao_district(self):
        card = _card(district="НАО")
        assert _is_strict_mkad(card) is True

    def test_strict_mkad_allows_moscow_inside_mkad(self):
        card = _card(address="Москва, ЮАО, р-н Чертаново")
        assert _is_strict_mkad(card) is False

    @pytest.mark.parametrize(
        "text",
        [
            "Продаются апартаменты, 61 м²",
            "Светлая квартира. Апартаменты в собственности.",
        ],
    )
    def test_is_apartment_detects_apartments(self, text):
        card = _card(title=text, description=text, is_apartments=False)
        assert _is_apartment(card) is True

    def test_is_apartment_by_flag(self):
        card = _card(is_apartments=True)
        assert _is_apartment(card) is True

    def test_is_apartment_allows_regular_flat(self):
        card = _card(title="2-комн. квартира", is_apartments=False)
        assert _is_apartment(card) is False

    def test_is_share_by_category(self):
        card = _card(category="flatShare")
        assert _is_share(card) is True

    def test_is_share_by_amount(self):
        card = _card(share_amount=0.25)
        assert _is_share(card) is True

    def test_is_share_by_description(self):
        card = _card(description="Продаётся доля в квартире 1/3")
        assert _is_share(card) is True

    def test_is_share_allows_regular_flat(self):
        card = _card(category="flatSale", description="Продаётся квартира")
        assert _is_share(card) is False

    @pytest.mark.parametrize(
        "phrase",
        [
            "отказник от приватизации",
            "пожизненное проживание",
            "бессрочное пользование",
            "без просмотра",
            "третье лицо с правом",
        ],
    )
    def test_has_legal_risk_detects_stop_phrases(self, phrase):
        card = _card(description=f"Уютная квартира. {phrase}.")
        assert _has_legal_risk(card) is True

    def test_has_legal_risk_allows_clean_description(self):
        card = _card(description="Светлая квартира после евроремонта")
        assert _has_legal_risk(card) is False


class TestSearchFilterIntegration:
    """search() applies filters on hydrated cards."""

    def _hydrated_search(self, cards: list[ListingCard], **kwargs):
        search_html = _fixture("cian_search_results.html")
        with patch("nedviga.cian_live._requests_get_search", return_value=None), \
             patch("nedviga.cian_live._requests_get_card", return_value=None), \
             patch("nedviga.cian_live.native_fetch", return_value=search_html), \
             patch("nedviga.cian_live.get_card", side_effect=lambda url, **kw: next(
                 c for c in cards if c.url == url
             )):
            return search(hydrate=True, **kwargs)

    def test_search_strict_mkad_filters_out_mkad_cards(self):
        inside = _card(
            id="cian-in",
            url="https://www.cian.ru/sale/flat/1/",
            address="Москва, ЮАО",
        )
        outside = _card(
            id="cian-out",
            url="https://www.cian.ru/sale/flat/2/",
            address="Коммунарка",
        )
        with patch("nedviga.cian_live._parse_search_result_links", return_value=[inside, outside]):
            result = self._hydrated_search([inside, outside], strict_mkad=True)
        assert len(result) == 1
        assert result[0].id == "cian-in"

    def test_search_only_flat_excludes_apartments(self):
        flat = _card(
            id="cian-flat",
            url="https://www.cian.ru/sale/flat/1/",
            title="2-комн. квартира",
        )
        apt = _card(
            id="cian-apt",
            url="https://www.cian.ru/sale/flat/2/",
            title="Апартаменты",
        )
        with patch("nedviga.cian_live._parse_search_result_links", return_value=[flat, apt]):
            result = self._hydrated_search([flat, apt], only_flat=True)
        assert len(result) == 1
        assert result[0].id == "cian-flat"

    def test_search_no_shares_excludes_shares(self):
        whole = _card(
            id="cian-whole",
            url="https://www.cian.ru/sale/flat/1/",
            category="flatSale",
        )
        share = _card(
            id="cian-share",
            url="https://www.cian.ru/sale/flat/2/",
            category="flatShare",
        )
        with patch("nedviga.cian_live._parse_search_result_links", return_value=[whole, share]):
            result = self._hydrated_search([whole, share], no_shares=True)
        assert len(result) == 1
        assert result[0].id == "cian-whole"

    def test_search_exclude_legal_risks_excludes_risky(self):
        clean = _card(
            id="cian-clean",
            url="https://www.cian.ru/sale/flat/1/",
            description="Хорошая квартира",
        )
        risky = _card(
            id="cian-risky",
            url="https://www.cian.ru/sale/flat/2/",
            description="Продаётся с пожизненное проживание",
        )
        with patch("nedviga.cian_live._parse_search_result_links", return_value=[clean, risky]):
            result = self._hydrated_search([clean, risky], exclude_legal_risks=True)
        assert len(result) == 1
        assert result[0].id == "cian-clean"


class TestParserFieldFixes:
    """v0.4.0 field-level parser fixes."""

    def test_year_built_from_house_year_built(self):
        html = """<!DOCTYPE html><html><head>
        <link rel="canonical" href="https://www.cian.ru/sale/flat/700/">
        </head><body><script>
        window._cianConfig = {"frontend-offer-card": [{"key":"defaultState","value":{
        "offerData": {"offer": {"house": {"yearBuilt": 1999}, "totalArea": 50,
        "floorNumber": 3, "building": {"floorsCount": 9},
        "bargainTerms": {"price": 10000000}}}
        }}]}
        </script></body></html>"""
        card = parse_card(html)
        assert card.building.year_built == 1999

    def test_year_built_from_building_build_year_still_works(self):
        html = """<!DOCTYPE html><html><head>
        <link rel="canonical" href="https://www.cian.ru/sale/flat/701/">
        </head><body><script>
        window._cianConfig = {"frontend-offer-card": [{"key":"defaultState","value":{
        "offerData": {"offer": {"building": {"buildYear": 2005, "floorsCount": 9},
        "totalArea": 50, "floorNumber": 3, "bargainTerms": {"price": 10000000}}}
        }}]}
        </script></body></html>"""
        card = parse_card(html)
        assert card.building.year_built == 2005

    def test_gas_false_when_floors_total_14_or_more(self):
        html = """<!DOCTYPE html><html><head>
        <link rel="canonical" href="https://www.cian.ru/sale/flat/702/">
        </head><body>
        <div data-name="HouseInfo">
          <div data-name="HouseInfoItem">
            <div data-name="HouseInfoItemTitle">Газоснабжение</div>
            <div data-name="HouseInfoItemValue">Есть</div>
          </div>
        </div>
        <script>
        window._cianConfig = {"frontend-offer-card": [{"key":"defaultState","value":{
        "offerData": {"offer": {"building": {"floorsCount": 16},
        "totalArea": 50, "floorNumber": 5, "bargainTerms": {"price": 10000000}}}
        }}]}
        </script></body></html>"""
        card = parse_card(html)
        assert card.parameters.floors_total == 16
        assert card.building.gas is False

    def test_gas_kept_when_low_rise(self):
        html = """<!DOCTYPE html><html><head>
        <link rel="canonical" href="https://www.cian.ru/sale/flat/703/">
        </head><body>
        <div data-name="HouseInfo">
          <div data-name="HouseInfoItem">
            <div data-name="HouseInfoItemTitle">Газоснабжение</div>
            <div data-name="HouseInfoItemValue">Есть</div>
          </div>
        </div>
        <script>
        window._cianConfig = {"frontend-offer-card": [{"key":"defaultState","value":{
        "offerData": {"offer": {"building": {"floorsCount": 9},
        "totalArea": 50, "floorNumber": 3, "bargainTerms": {"price": 10000000}}}
        }}]}
        </script></body></html>"""
        card = parse_card(html)
        assert card.building.gas is True

    def test_category_extracted_from_default_state(self):
        html = """<!DOCTYPE html><html><head>
        <link rel="canonical" href="https://www.cian.ru/sale/flat/704/">
        </head><body><script>
        window._cianConfig = {"frontend-offer-card": [{"key":"defaultState","value":{
        "offerData": {"offer": {"category": "flatShare", "totalArea": 50,
        "floorNumber": 3, "building": {"floorsCount": 9},
        "bargainTerms": {"price": 10000000}}}
        }}]}
        </script></body></html>"""
        card = parse_card(html)
        assert card.category == "flatShare"


class TestCliRealtorFlags:
    """CLI parses and passes new realtor flags."""

    def test_cli_search_strict_mkad_auto_hydrates(self, capsys):
        flat = _card(
            id="cian-flat",
            url="https://www.cian.ru/sale/flat/310123456/",
            address="Москва, ЮАО",
        )
        search_html = _fixture("cian_search_results.html")
        with patch("nedviga.cian_live._requests_get_search", return_value=None), \
             patch("nedviga.cian_live._requests_get_card", return_value=None), \
             patch("nedviga.cian_live.native_fetch", return_value=search_html), \
             patch("nedviga.cian_live.get_card", return_value=flat):
            code = main(
                [
                    "search",
                    "--source",
                    "cian",
                    "--strict-mkad",
                    "--limit",
                    "2",
                    "--json",
                ]
            )
        captured = capsys.readouterr()
        assert code == 0, captured.err
        payload = json.loads(captured.out)
        assert payload["status"] == "ok"

    def test_cli_search_no_gas_sets_min_house_floors_14_in_url(self, capsys):
        with patch("nedviga.cian_live._requests_get_search") as mock_req, \
             patch("nedviga.cian_live.native_fetch", return_value="<html></html>"):
            mock_req.return_value = None
            code = main(
                [
                    "search",
                    "--source",
                    "cian",
                    "--no-gas",
                    "--json",
                ]
            )
        captured = capsys.readouterr()
        assert code == 0, captured.err
        # The URL built by search must contain minhousefloors=14
        url = mock_req.call_args[0][0]
        assert "minhousefloors=14" in url
