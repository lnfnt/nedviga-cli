"""Offline regression tests for the Cian card parser (M1 import mode).

All tests are deterministic and do not perform network requests.
Fixtures under ``fixtures/`` are synthetic and marked as such.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from nedviga.cian_card import (
    ParseError,
    _extract_district,
    _normalize_area,
    _normalize_number,
    _normalize_price,
    _parse_bathroom,
    _parse_building_type,
    _parse_elevators,
    _parse_floor,
    _parse_renovation,
    _parse_rooms,
    _parse_year,
    parse_card,
)

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run the CLI in a subprocess with PYTHONPATH set to the project root."""
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    return subprocess.run(
        [sys.executable, "-m", "nedviga", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
    )


def parse_stdout_json(proc: subprocess.CompletedProcess[str]) -> dict:
    """Assert that stdout is exactly one JSON object and parse it."""
    assert proc.returncode is not None
    assert proc.stdout.strip(), "stdout is empty"
    first_brace = proc.stdout.index("{")
    last_brace = proc.stdout.rindex("}")
    import json

    return json.loads(proc.stdout[first_brace : last_brace + 1])


# ---------------------------------------------------------------------------
# Fixture-level parsing tests
# ---------------------------------------------------------------------------


class TestParseFullPanelFixture:
    """Fixture 1: 2-комнатная панелька с полной инфой."""

    @pytest.fixture
    def card(self):
        return parse_card(_fixture("cian_card_full_panel.html"))

    def test_identity(self, card):
        assert card.id == "cian-310123456"
        assert card.source == "cian"
        assert card.url == "https://www.cian.ru/sale/flat/310123456/"
        assert card.status == "active"
        assert "2-комн." in card.title

    def test_pricing(self, card):
        assert card.pricing.price_total_rub == 16_900_000
        assert card.pricing.price_per_m2_rub == 311_808.12

    def test_parameters_all_fields(self, card):
        assert card.parameters.rooms == 2
        assert card.parameters.rooms_type == "isolated"
        assert card.parameters.area_total_m2 == 54.2
        assert card.parameters.area_living_m2 == 32.0
        assert card.parameters.area_kitchen_m2 == 8.5
        assert card.parameters.floor == 6
        assert card.parameters.floors_total == 12
        assert card.parameters.ceiling_height_m == 2.64
        assert card.parameters.balcony == "1 лоджия"
        assert card.parameters.bathroom == "раздельный"
        assert card.parameters.renovation == "cosmetic"
        assert card.parameters.window_view == "yard"

    def test_building(self, card):
        assert card.building.building_type == "panel"
        assert card.building.year_built == 1971
        assert card.building.house_series == "II-49"
        assert card.building.floor_material == "reinforced_concrete"
        assert card.building.renovation_program is False
        assert card.building.elevators_passenger == 1
        assert card.building.elevators_cargo is None
        assert card.building.gas is True

    def test_geo(self, card):
        assert card.geo.lat == 55.638512
        assert card.geo.lon == 37.602534
        assert card.geo.district == "ЮАО"
        assert card.geo.area_name == "Чертаново Северное"
        assert card.geo.cian_claimed_metro.station == "Чертановская"
        assert card.geo.cian_claimed_metro.claimed_time_minutes == 10
        assert card.geo.cian_claimed_metro.transport_type == "walk"

    def test_description_and_seller(self, card):
        assert "Светлая уютная квартира" in card.description_text
        assert card.seller.seller_type == "realtor"
        assert card.seller.name == "Инком-Недвижимость"
        assert card.seller.agent_phone_masked == "+7 999 ***-**-**"

    def test_images(self, card):
        assert len(card.images) == 2
        assert card.images[0].category == "plan"
        assert card.images[1].category == "interior"


class TestParseStudioMinimalFixture:
    """Fixture 2: студия с минимальным набором — многие поля null."""

    @pytest.fixture
    def card(self):
        return parse_card(_fixture("cian_card_studio_minimal.html"))

    def test_identity(self, card):
        assert card.id == "cian-310123457"
        assert "Студия" in card.title

    def test_studio_rooms_zero(self, card):
        assert card.parameters.rooms == 0

    def test_minimal_fields_are_null(self, card):
        assert card.pricing.price_per_m2_rub is None
        assert card.parameters.area_living_m2 is None
        assert card.parameters.area_kitchen_m2 is None
        assert card.parameters.ceiling_height_m is None
        assert card.parameters.balcony is None
        assert card.parameters.bathroom is None
        assert card.parameters.renovation is None
        assert card.parameters.window_view is None
        assert card.building.building_type is None
        assert card.building.year_built is None
        assert card.geo.cian_claimed_metro is None
        assert card.images == []

    def test_present_fields(self, card):
        assert card.pricing.price_total_rub == 7_200_000
        assert card.parameters.area_total_m2 == 22.0
        assert card.parameters.floor == 3
        assert card.parameters.floors_total == 5
        assert card.seller.seller_type == "owner"


class TestParseBusinessMonolithFixture:
    """Fixture 3: монолит бизнес-класса с этажностью и лифтами."""

    @pytest.fixture
    def card(self):
        return parse_card(_fixture("cian_card_business_monolith.html"))

    def test_identity(self, card):
        assert card.id == "cian-310123458"
        assert card.parameters.rooms == 3
        assert card.parameters.floor == 15
        assert card.parameters.floors_total == 25

    def test_building(self, card):
        assert card.building.building_type == "monolith"
        assert card.building.year_built == 2022
        assert card.building.floor_material == "reinforced_concrete"
        assert card.building.elevators_passenger == 2
        assert card.building.elevators_cargo == 1

    def test_parameters(self, card):
        assert card.parameters.area_total_m2 == 98.0
        assert card.parameters.ceiling_height_m == 3.2
        assert card.parameters.bathroom == "2 санузла"
        assert card.parameters.renovation == "design"
        assert card.parameters.rooms_type == "euro"

    def test_seller(self, card):
        assert card.seller.seller_type == "developer"
        assert card.seller.name == "Level Group"


class TestParsePriceDropsFixture:
    """Fixture 4: карточка со снижением цены — price_history из 3 точек."""

    @pytest.fixture
    def card(self):
        return parse_card(_fixture("cian_card_price_drops.html"))

    def test_price_history(self, card):
        history = card.pricing.price_history
        assert len(history) == 3
        assert history[0].date == "2026-06-10"
        assert history[0].price == 13_200_000
        assert history[1].date == "2026-07-22"
        assert history[1].price == 12_600_000
        assert history[2].date == "2026-09-05"
        assert history[2].price == 11_900_000

    def test_pricing(self, card):
        assert card.pricing.price_total_rub == 11_900_000
        assert card.pricing.price_per_m2_rub == 313_157.89

    def test_district_parsed_correctly(self, card):
        assert card.geo.district == "ЮЗАО"


class TestParseMetroClaimFixture:
    """Fixture 5: карточка с claim на метро 10 мин пешком."""

    @pytest.fixture
    def card(self):
        return parse_card(_fixture("cian_card_metro_claim.html"))

    def test_metro_claim(self, card):
        assert card.geo.cian_claimed_metro.station == "Чертановская"
        assert card.geo.cian_claimed_metro.claimed_time_minutes == 10
        assert card.geo.cian_claimed_metro.transport_type == "walk"

    def test_honest_walk_route_is_not_computed(self, card):
        assert card.geo.honest_walk_route is None


# ---------------------------------------------------------------------------
# Normalisation unit tests
# ---------------------------------------------------------------------------


class TestNormalizers:
    def test_normalize_price_with_spaces(self):
        assert _normalize_price("16 900 000 ₽") == 16_900_000

    def test_normalize_price_with_nbsp(self):
        assert _normalize_price("16\u00a0900\u00a0000 ₽") == 16_900_000

    def test_normalize_area_with_comma(self):
        assert _normalize_area("54,2 м²") == 54.2

    def test_normalize_area_with_dot(self):
        assert _normalize_area("54.2 м²") == 54.2

    def test_normalize_area_whole_number(self):
        assert _normalize_area("38 м²") == 38.0

    def test_normalize_number_decimal_comma(self):
        assert _normalize_number("311 808,12") == 311_808.12

    def test_parse_floor_slash(self):
        assert _parse_floor("6/12 этаж") == (6, 12)

    def test_parse_floor_iz(self):
        assert _parse_floor("6 из 12") == (6, 12)

    def test_parse_floor_single(self):
        assert _parse_floor("3 этаж") == (3, None)

    def test_parse_year(self):
        assert _parse_year("1971") == 1971
        assert _parse_year("Построен в 2022 году") == 2022

    def test_parse_rooms(self):
        assert _parse_rooms("2-комн. квартира", {}) == 2
        assert _parse_rooms("Студия, 22 м²", {}) == 0
        assert _parse_rooms(None, {"комнаты": "3-комнатная"}) == 3

    def test_parse_renovation(self):
        assert _parse_renovation("Косметический") == "cosmetic"
        assert _parse_renovation("Евроремонт") == "euro"
        assert _parse_renovation("Дизайнерский") == "design"

    def test_parse_renovation_unknown_returns_none(self):
        assert _parse_renovation("unknown") is None

    def test_parse_renovation_empty_returns_none(self):
        assert _parse_renovation("") is None
        assert _parse_renovation(None) is None

    def test_parse_building_type(self):
        assert _parse_building_type("Панельный") == "panel"
        assert _parse_building_type("Кирпичный") == "brick"
        assert _parse_building_type("Монолитный") == "monolith"

    def test_parse_elevators(self):
        assert _parse_elevators("1 пассажирский") == (1, None)
        assert _parse_elevators("2 пассажирских и 1 грузовой") == (2, 1)

    def test_parse_bathroom(self):
        assert _parse_bathroom("раздельный") == "раздельный"
        assert _parse_bathroom("совмещенный") == "совмещенный"

    def test_extract_district(self):
        assert _extract_district("Москва, ЮАО, р-н Чертаново") == "ЮАО"
        assert _extract_district("Москва, ЮЗАО, Ленинский проспект") == "ЮЗАО"
        assert _extract_district("Москва, СЗАО") == "СЗАО"


# ---------------------------------------------------------------------------
# Fail-closed behaviour
# ---------------------------------------------------------------------------


class TestFailClosed:
    def test_empty_html_raises_parse_error(self):
        with pytest.raises(ParseError):
            parse_card("")

    def test_whitespace_html_raises_parse_error(self):
        with pytest.raises(ParseError):
            parse_card("   \n   ")

    def test_garbage_html_raises_parse_error(self):
        with pytest.raises(ParseError):
            parse_card("<html><body>hello world</body></html>")

    def test_missing_field_becomes_none(self):
        html = _fixture("cian_card_studio_minimal.html")
        card = parse_card(html)
        assert card.parameters.ceiling_height_m is None
        assert card.building.house_series is None


# ---------------------------------------------------------------------------
# CLI import command integration
# ---------------------------------------------------------------------------


class TestImportCli:
    def test_import_fixture_one_exit_zero(self):
        proc = run_cli(["import", str(FIXTURES / "cian_card_full_panel.html"), "--json"])
        payload = parse_stdout_json(proc)
        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        assert payload["status"] == "ok"
        assert payload["data"]["id"] == "cian-310123456"

    def test_import_missing_file_exit_three(self):
        proc = run_cli(["import", "fixtures/does_not_exist.html", "--json"])
        payload = parse_stdout_json(proc)
        assert proc.returncode == 3
        assert payload["status"] == "error"
        assert payload["reason"] == "file_not_found"

    def test_import_garbage_html_exit_three(self):
        proc = run_cli(["import", str(FIXTURES / "cian_card_garbage.html"), "--json"])
        payload = parse_stdout_json(proc)
        assert proc.returncode == 3
        assert payload["status"] == "error"
        assert "parse_error" in payload["reason"]


# ---------------------------------------------------------------------------
# SPEC 4.2 coverage assertion
# ---------------------------------------------------------------------------


class TestSpecCoverage:
    """Ensure every field declared in SPEC 4.2 appears in at least one fixture."""

    @pytest.fixture
    def all_cards(self):
        names = [
            "cian_card_full_panel.html",
            "cian_card_studio_minimal.html",
            "cian_card_business_monolith.html",
            "cian_card_price_drops.html",
            "cian_card_metro_claim.html",
            "cian_card_secondary_defaultstate.html",
            "cian_card_multi_metro.html",
            "cian_card_geo_null.html",
        ]
        return [parse_card(_fixture(n)) for n in names]

    def _has(self, cards, predicate):
        return any(predicate(c) for c in cards)

    def test_pricing_fields_covered(self, all_cards):
        assert self._has(all_cards, lambda c: c.pricing.price_total_rub is not None)
        assert self._has(all_cards, lambda c: c.pricing.price_per_m2_rub is not None)
        assert self._has(all_cards, lambda c: len(c.pricing.price_history) >= 3)

    def test_parameter_fields_covered(self, all_cards):
        assert self._has(all_cards, lambda c: c.parameters.rooms is not None)
        assert self._has(all_cards, lambda c: c.parameters.rooms_type is not None)
        assert self._has(all_cards, lambda c: c.parameters.area_total_m2 is not None)
        assert self._has(all_cards, lambda c: c.parameters.area_living_m2 is not None)
        assert self._has(all_cards, lambda c: c.parameters.area_kitchen_m2 is not None)
        assert self._has(all_cards, lambda c: c.parameters.floor is not None)
        assert self._has(all_cards, lambda c: c.parameters.floors_total is not None)
        assert self._has(all_cards, lambda c: c.parameters.ceiling_height_m is not None)
        assert self._has(all_cards, lambda c: c.parameters.balcony is not None)
        assert self._has(all_cards, lambda c: c.parameters.bathroom is not None)
        assert self._has(all_cards, lambda c: c.parameters.renovation is not None)
        assert self._has(all_cards, lambda c: c.parameters.window_view is not None)

    def test_building_fields_covered(self, all_cards):
        assert self._has(all_cards, lambda c: c.building.address_raw is not None)
        assert self._has(all_cards, lambda c: c.building.house_series is not None)
        assert self._has(all_cards, lambda c: c.building.year_built is not None)
        assert self._has(all_cards, lambda c: c.building.building_type is not None)
        assert self._has(all_cards, lambda c: c.building.floor_material is not None)
        assert self._has(all_cards, lambda c: c.building.elevators_passenger is not None)
        assert self._has(all_cards, lambda c: c.building.elevators_cargo is not None)
        assert self._has(all_cards, lambda c: c.building.gas is not None)

    def test_geo_fields_covered(self, all_cards):
        assert self._has(all_cards, lambda c: c.geo.lat is not None)
        assert self._has(all_cards, lambda c: c.geo.lon is not None)
        assert self._has(all_cards, lambda c: c.geo.district is not None)
        assert self._has(all_cards, lambda c: c.geo.area_name is not None)
        assert self._has(all_cards, lambda c: c.geo.cian_claimed_metro is not None)

    def test_description_seller_images_covered(self, all_cards):
        assert self._has(all_cards, lambda c: c.description_text is not None)
        assert self._has(all_cards, lambda c: c.seller.seller_type is not None)
        assert self._has(all_cards, lambda c: c.seller.name is not None)
        assert self._has(all_cards, lambda c: len(c.images) > 0)


class TestGeoNullRegression:
    """F-06: offer.geo=null must not crash the parser."""

    _HTML = """<!DOCTYPE html><html><head>
<link rel="canonical" href="https://www.cian.ru/sale/flat/999/">
</head><body>
<script>
window._cianConfig = {"frontend-offer-card": {"data": [{"key":"defaultState","value":{
"offerData": {"offer": {"geo": null, "title": "Test"}}
}}]}};
</script>
</body></html>"""

    def test_parse_card_with_geo_null_does_not_crash(self):
        card = parse_card(self._HTML)
        assert card.id == "cian-999"
        assert card.geo.lat is None
        assert card.geo.lon is None


# ---------------------------------------------------------------------------
# F-02: _normalize_number multi-dot
# ---------------------------------------------------------------------------


class TestNormalizeNumberMultiDot:
    def test_multi_dot_all_three_digit_groups_treated_as_thousands(self):
        assert _normalize_number("1.234.567") == 1_234_567

    def test_multi_dot_non_three_digit_groups_returns_none(self):
        assert _normalize_number("1.23.456") is None

    def test_multi_dot_with_trailing_short_group_returns_none(self):
        assert _normalize_number("1.234.56") is None

    def test_single_dot_still_works(self):
        assert _normalize_number("54.2") == 54.2

    def test_single_dot_integer(self):
        assert _normalize_number("100.0") == 100.0


# ---------------------------------------------------------------------------
# F-04: window_view JSON path normalizes through _parse_window_view
# ---------------------------------------------------------------------------


class TestWindowViewNormalization:
    def test_json_path_yard(self):
        html = """<!DOCTYPE html><html><head>
        <link rel="canonical" href="https://www.cian.ru/sale/flat/400/">
        </head><body><script>
        window._cianConfig = {"frontend-offer-card": [{"key":"defaultState","value":{
        "offerData": {"offer": {"windowsViewType": "yard", "totalArea": 50, "floorNumber": 3,
        "building": {"floorsCount": 9}, "bargainTerms": {"price": 10000000}}}
        }}]}
        </script></body></html>"""
        card = parse_card(html)
        assert card.parameters.window_view == "yard"

    def test_json_path_russian_yard(self):
        html = """<!DOCTYPE html><html><head>
        <link rel="canonical" href="https://www.cian.ru/sale/flat/401/">
        </head><body><script>
        window._cianConfig = {"frontend-offer-card": [{"key":"defaultState","value":{
        "offerData": {"offer": {"windowsViewType": "Во двор", "totalArea": 50, "floorNumber": 3,
        "building": {"floorsCount": 9}, "bargainTerms": {"price": 10000000}}}
        }}]}
        </script></body></html>"""
        card = parse_card(html)
        assert card.parameters.window_view == "yard"

    def test_json_path_forest(self):
        html = """<!DOCTYPE html><html><head>
        <link rel="canonical" href="https://www.cian.ru/sale/flat/402/">
        </head><body><script>
        window._cianConfig = {"frontend-offer-card": [{"key":"defaultState","value":{
        "offerData": {"offer": {"windowsViewType": "forest", "totalArea": 50, "floorNumber": 3,
        "building": {"floorsCount": 9}, "bargainTerms": {"price": 10000000}}}
        }}]}
        </script></body></html>"""
        card = parse_card(html)
        assert card.parameters.window_view == "forest"

    def test_json_and_dom_produce_same_output(self):
        html_dom = """<!DOCTYPE html><html><head>
        <link rel="canonical" href="https://www.cian.ru/sale/flat/403/">
        </head><body>
        <div data-name="OfferCardPageInfo">
        <div data-name="OfferFactoidsItem">
        <span data-name="OfferFactoidsItemTitle">Вид из окон</span>
        <span data-name="OfferFactoidsItemValue">На улицу</span>
        </div></div>
        </body></html>"""
        html_json = """<!DOCTYPE html><html><head>
        <link rel="canonical" href="https://www.cian.ru/sale/flat/404/">
        </head><body><script>
        window._cianConfig = {"frontend-offer-card": [{"key":"defaultState","value":{
        "offerData": {"offer": {"windowsViewType": "street", "totalArea": 50, "floorNumber": 3,
        "building": {"floorsCount": 9}, "bargainTerms": {"price": 10000000}}}
        }}]}
        </script></body></html>"""
        card_dom = parse_card(html_dom)
        card_json = parse_card(html_json)
        assert card_dom.parameters.window_view == card_json.parameters.window_view == "street"


# ---------------------------------------------------------------------------
# F-10: status detection
# ---------------------------------------------------------------------------


class TestStatusDetection:
    def test_status_active_when_published(self):
        html = """<!DOCTYPE html><html><head>
        <link rel="canonical" href="https://www.cian.ru/sale/flat/500/">
        </head><body><script>
        window._cianConfig = {"frontend-offer-card": [{"key":"defaultState","value":{
        "offerData": {"offer": {"status": "published", "totalArea": 50, "floorNumber": 3,
        "building": {"floorsCount": 9}, "bargainTerms": {"price": 10000000}}}
        }}]}
        </script></body></html>"""
        card = parse_card(html)
        assert card.status == "active"

    def test_status_removed_when_offer_removed(self):
        html = """<!DOCTYPE html><html><head>
        <link rel="canonical" href="https://www.cian.ru/sale/flat/501/">
        </head><body><script>
        window._cianConfig = {"frontend-offer-card": [{"key":"defaultState","value":{
        "offerData": {"offer": {"status": "removed", "totalArea": 50, "floorNumber": 3,
        "building": {"floorsCount": 9}, "bargainTerms": {"price": 10000000}}}
        }}]}
        </script></body></html>"""
        card = parse_card(html)
        assert card.status == "removed"

    def test_status_sold_when_offer_sold(self):
        html = """<!DOCTYPE html><html><head>
        <link rel="canonical" href="https://www.cian.ru/sale/flat/502/">
        </head><body><script>
        window._cianConfig = {"frontend-offer-card": [{"key":"defaultState","value":{
        "offerData": {"offer": {"status": "sold", "totalArea": 50, "floorNumber": 3,
        "building": {"floorsCount": 9}, "bargainTerms": {"price": 10000000}}}
        }}]}
        </script></body></html>"""
        card = parse_card(html)
        assert card.status == "sold"

    def test_status_detected_from_page_text_removed(self):
        html = """<!DOCTYPE html><html><head>
        <link rel="canonical" href="https://www.cian.ru/sale/flat/503/">
        </head><body>
        <p>Объявление удалено</p>
        </body></html>"""
        card = parse_card(html)
        assert card.status == "removed"

    def test_status_default_active_when_no_indicators(self):
        html = _fixture("cian_card_full_panel.html")
        card = parse_card(html)
        assert card.status == "active"


# ---------------------------------------------------------------------------
# F-11: new synthetic fixtures
# ---------------------------------------------------------------------------


class TestSecondaryDefaultStateFixture:
    @pytest.fixture
    def card(self):
        return parse_card(_fixture("cian_card_secondary_defaultstate.html"))

    def test_identity(self, card):
        assert card.id == "cian-310123500"

    def test_has_house_series_no_deadline(self, card):
        assert card.building.house_series == "II-57"
        assert card.building.year_built == 1985

    def test_parameters(self, card):
        assert card.parameters.rooms == 3
        assert card.parameters.area_total_m2 == 72.0
        assert card.parameters.floor == 4
        assert card.parameters.floors_total == 9
        assert card.parameters.window_view == "yard"
        assert card.parameters.renovation == "euro"

    def test_pricing(self, card):
        assert card.pricing.price_total_rub == 19_500_000

    def test_geo(self, card):
        assert card.geo.lat is not None
        assert card.geo.lon is not None
        assert card.geo.district == "ЗАО"

    def test_renovation_program_none(self, card):
        assert card.building.renovation_program is None

    def test_status_active(self, card):
        assert card.status == "active"


class TestMultiMetroFixture:
    @pytest.fixture
    def card(self):
        return parse_card(_fixture("cian_card_multi_metro.html"))

    def test_identity(self, card):
        assert card.id == "cian-310123501"

    def test_metro_claim_uses_first_station(self, card):
        assert card.geo.cian_claimed_metro is not None
        assert card.geo.cian_claimed_metro.station == "Водный стадион"
        assert card.geo.cian_claimed_metro.claimed_time_minutes == 8
        assert card.geo.cian_claimed_metro.transport_type == "walk"

    def test_pricing(self, card):
        assert card.pricing.price_total_rub == 12_000_000


class TestGeoNullFixture:
    @pytest.fixture
    def card(self):
        return parse_card(_fixture("cian_card_geo_null.html"))

    def test_identity(self, card):
        assert card.id == "cian-310123502"

    def test_geo_is_none(self, card):
        assert card.geo.lat is None
        assert card.geo.lon is None

    def test_parameters_present(self, card):
        assert card.parameters.area_total_m2 == 50.0
        assert card.parameters.floor == 3

    def test_pricing(self, card):
        assert card.pricing.price_total_rub == 8_500_000


# ---------------------------------------------------------------------------
# F-13: renovation_program None when no data
# ---------------------------------------------------------------------------


class TestRenovationProgramNone:
    def test_renovation_program_none_when_no_renovation_key(self):
        card = parse_card(_fixture("cian_card_studio_minimal.html"))
        assert card.building.renovation_program is None

    def test_renovation_program_false_when_explicitly_no(self):
        card = parse_card(_fixture("cian_card_full_panel.html"))
        assert card.building.renovation_program is False


# ---------------------------------------------------------------------------
# F-14: negative-path tests
# ---------------------------------------------------------------------------


class TestNegativePaths:
    def test_default_state_with_empty_offer_data(self):
        html = """<!DOCTYPE html><html><head>
        <link rel="canonical" href="https://www.cian.ru/sale/flat/600/">
        </head><body><script>
        window._cianConfig = {"frontend-offer-card": [{"key":"defaultState","value":{
        "offerData": {}
        }}]}
        </script></body></html>"""
        card = parse_card(html)
        assert card.id == "cian-600"
        assert card.parameters.area_total_m2 is None
        assert card.geo.lat is None

    def test_default_state_missing_entirely_dom_only(self):
        html = """<!DOCTYPE html><html><head>
        <link rel="canonical" href="https://www.cian.ru/sale/flat/601/">
        </head><body>
        <h1 data-name="OfferTitle">1-комн. квартира</h1>
        <div data-name="OfferPrice">5 000 000 ₽</div>
        </body></html>"""
        card = parse_card(html)
        assert card.id == "cian-601"
        assert card.pricing.price_total_rub == 5_000_000
        assert card.parameters.area_total_m2 is None

    def test_normalize_number_multi_dot_ambiguous(self):
        assert _normalize_number("1.234.567") == 1_234_567
        assert _normalize_number("1.23.456") is None
        assert _normalize_number("1.2.3") is None
