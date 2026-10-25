"""v0.4.3 (ТЗ the task brief, скоуп согласован с agent-profile 21.10):
базовые поля из сниппета выдачи Циана одним прогоном, без hydrate-запросов.
TDD: этот файл written ДО реализации — первые прогоны обязаны были быть RED."""
from pathlib import Path

from nedviga.cian_live import _parse_search_result_links
from nedviga.models import ListingCard

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "cian_search_results_scrubbed.html"


def _cards():
    return _parse_search_result_links(FIX.read_text(encoding="utf-8"))


def test_cards_parsed():
    cards = _cards()
    assert len(cards) >= 5


def test_snippet_price_area_rooms():
    aura = next(c for c in _cards() if (c.building.complex or "") == "АУРА")
    assert aura.parameters.rooms == 1
    assert aura.parameters.area_total_m2 == 38.0
    assert aura.pricing.price_total_rub == 26754660


def test_snippet_floor_floors_total():
    aura = next(c for c in _cards() if (c.building.complex or "") == "АУРА")
    assert aura.parameters.floor == 7
    assert aura.parameters.floors_total == 42


def test_snippet_address_and_complex():
    aura = next(c for c in _cards() if (c.building.complex or "") == "АУРА")
    assert "Малая Тульская" in (aura.building.address_raw or "")
    assert "ЮАО" in (aura.building.address_raw or "")


def test_snippet_metro_besteffort():
    aura = next(c for c in _cards() if (c.building.complex or "") == "АУРА")
    m = aura.geo.cian_claimed_metro
    assert m is not None and m.station == "Тульская"
    assert m.claimed_time_minutes == 7


def test_no_silent_guesses_on_old_synthetic_fixture():
    old = Path(__file__).resolve().parent.parent / "fixtures" / "cian_search_results.html"
    cards = _parse_search_result_links(old.read_text(encoding="utf-8"))
    for c in cards:  # не пасть, всё None там, где не прочитано
        assert c.parameters.floor is None or isinstance(c.parameters.floor, int)


def test_hydrate_not_forced_by_floor_only_filters():
    import nedviga.cli as cli
    src = Path(cli.__file__).read_text(encoding="utf-8")
    seg = src.split("detail_filters = (")[1].split(")")[0]
    assert "floor_not_first" not in seg and "min_house_floors" not in seg and "no_gas" not in seg


def test_merge_snippet_fills_only_empty():
    from nedviga.cian_live import _merge_snippet_into_hydrated
    skel = _cards()[0]
    hy = ListingCard(id=skel.id, source="cian", url=skel.url, status="active")
    _merge_snippet_into_hydrated(skel, hy)
    assert hy.parameters.floor == skel.parameters.floor  # пустое заполнено из сниппета
    hy2 = ListingCard(id="x", source="cian", url="u")
    hy2.parameters.floor = 9
    hy2.parameters.floors_total = 17
    _merge_snippet_into_hydrated(skel, hy2)
    assert hy2.parameters.floor == 9  #hydrated-истина не перезаписывается
