"""v0.4.7 (the task brief) F-11: Family Decision Card.

RED-тесты Фазы 1: модуль nedviga/family_card.py и команда `card`
пока не реализованы, поэтому этот файл должен падать целиком.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from nedviga.cli import main
from nedviga.family_card import (
    FamilyCard,
    build_family_card,
    render_html,
    render_telegram,
)
from nedviga.models import (
    Building,
    CianClaimedMetro,
    Geo,
    HonestWalkRoute,
    Image,
    ListingCard,
    Parameters,
    Pricing,
    Seller,
)

PHONE_BRACKETED = "+7 (999) 000-11-22"
PHONE_COMPACT = "+79161234567"
MASKED_MARKER = "+7 *** ***-**-**"

_RAW_PHONE_PATTERNS = (
    re.compile(r"\+?7[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}"),
    re.compile(r"(?<!\d)8[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}"),
    re.compile(r"(?<![\dA-Za-z])\d{3}[\s\-]\d{3}[\s\-]\d{2}[\s\-]\d{2}(?!\d)"),
)


def find_raw_phones(text: str) -> list[str]:
    hits: list[str] = []
    for pattern in _RAW_PHONE_PATTERNS:
        hits.extend(m.group(0) for m in pattern.finditer(text))
    return hits


def _make_card() -> ListingCard:
    photos = [Image(url=f"https://example.com/photo{i}.jpg", category="photo") for i in range(1, 6)]
    photos.append(Image(url="https://example.com/plan.jpg", category="plan"))
    return ListingCard(
        id="cian-900001",
        source="cian",
        url="https://www.cian.ru/sale/flat/900001/",
        title="2-к квартира, 54.2 м² — Сумской проезд, 12к1",
        pricing=Pricing(price_total_rub=14_800_000.0, price_per_m2_rub=273_000.0),
        parameters=Parameters(
            rooms=2,
            area_total_m2=54.2,
            area_living_m2=32.0,
            area_kitchen_m2=8.5,
            floor=6,
            floors_total=16,
            balcony="лоджия",
            bathroom="раздельный",
        ),
        building=Building(
            house_series="П-44",
            year_built=1988,
            building_type="панельный",
            floor_material="железобетон",
            has_garbage_chute=True,
            elevators_passenger=1,
            elevators_cargo=1,
            gas=False,
            renovation_program=True,
        ),
        geo=Geo(
            lat=55.6,
            lon=37.6,
            district="Чертаново",
            area_name="ЮАО",
            cian_claimed_metro=CianClaimedMetro(
                station="Чертановская", claimed_time_minutes=10, transport_type="walk"
            ),
            honest_walk_route=HonestWalkRoute(
                target_station="Чертановская",
                walk_distance_meters=980,
                walk_duration_minutes=12,
                routing_provider="graph_local",
                route_verified=True,
            ),
        ),
        seller=Seller(seller_type="owner", phones=[PHONE_BRACKETED, PHONE_COMPACT]),
        images=photos,
    )


@pytest.fixture
def card() -> ListingCard:
    return _make_card()


def test_build_family_card_basic(card):
    fc = build_family_card(card)
    assert isinstance(fc, FamilyCard)
    assert fc.price_total_rub == 14_800_000.0
    assert fc.price_per_m2_rub == 273_000.0
    assert len(fc.photos) == 6


def test_render_telegram_contains_house_and_walk(card):
    fc = build_family_card(card)
    text = render_telegram(fc)
    assert "Чертановская" in text
    assert "12" in text  # minutes walk
    assert "980" in text  # meters
    assert "П-44" in text
    assert "1988" in text
    assert "железобетон" in text.lower() or "ЖБ" in text
    # no transport-to-center block
    assert "до центра" not in text.lower()
    assert "на машине" not in text.lower()
    assert "на метро" not in text.lower() or "м." in text


def test_render_telegram_photo_count(card):
    fc = build_family_card(card)
    text = render_telegram(fc)
    assert "6" in text  # 6 photos
    assert "Фото" in text or "📸" in text


def test_render_html_contains_all_photos(card):
    fc = build_family_card(card)
    html = render_html(fc)
    for i in range(1, 6):
        assert f"photo{i}.jpg" in html
    assert "plan.jpg" in html


def test_render_html_no_raw_phones_default(card):
    fc = build_family_card(card)
    html = render_html(fc)
    assert find_raw_phones(html) == []
    assert MASKED_MARKER in html


def test_render_telegram_no_raw_phones_default(card):
    fc = build_family_card(card)
    text = render_telegram(fc)
    assert find_raw_phones(text) == []
    assert MASKED_MARKER in text


def test_house_block_detailed(card):
    fc = build_family_card(card)
    html = render_html(fc)
    for token in ("П-44", "1988", "железобетон", "мусоропровод"):
        assert token.lower() in html.lower() or token in html
    # elevators
    assert "лифт" in html.lower() or "лифта" in html.lower()


def test_no_utilities_in_output(card):
    fc = build_family_card(card)
    for out in (render_html(fc), render_telegram(fc)):
        low = out.lower()
        assert "жку" not in low
        assert "коммуналь" not in low
        assert "налог" not in low


def test_plus_minus_engine(card):
    fc = build_family_card(card)
    text = render_telegram(fc)
    # plus: kitchen >=7.5, not first floor, walk <15
    assert "Кухня" in text or "кухня" in text
    # minus: none critical maybe gas false -> no gas minus
    assert "Плюсы" in text or "✅" in text


def test_render_html_escapes(card):
    from nedviga.models import ListingCard

    c = _make_card()
    c.title = "<script>alert(1)</script>"
    fc = build_family_card(c)
    html = render_html(fc)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_cli_card_unknown_id_exit_3(tmp_path, capsys):
    p = tmp_path / "missing_id"
    # unknown id (not a file) -> exit 3
    code = main(["card", "no-such-id-12345", "--format", "telegram"])
    captured = capsys.readouterr()
    assert code == 3, captured.out


def test_cli_card_json_file_telegram(tmp_path, capsys):
    card = _make_card()
    inp = tmp_path / "card.json"
    inp.write_text(json.dumps(card.model_dump(mode="json", exclude_none=False), ensure_ascii=False), encoding="utf-8")
    outdir = tmp_path / "out"
    outdir.mkdir()
    code = main(["card", str(inp), "--format", "telegram", "--out", str(outdir)])
    captured = capsys.readouterr()
    assert code == 0, captured.out


def test_cli_card_html_all_photos(tmp_path, capsys):
    card = _make_card()
    inp = tmp_path / "card.json"
    inp.write_text(json.dumps(card.model_dump(mode="json", exclude_none=False), ensure_ascii=False), encoding="utf-8")
    outdir = tmp_path / "out"
    outdir.mkdir()
    code = main(["card", str(inp), "--format", "html", "--out", str(outdir)])
    captured = capsys.readouterr()
    assert code == 0, captured.out
    # find generated html
    htmls = list(outdir.glob("*.html"))
    assert htmls
    html = htmls[0].read_text(encoding="utf-8")
    assert find_raw_phones(html) == []
    for i in range(1, 6):
        assert f"photo{i}.jpg" in html


def test_cli_card_with_contacts_opens_phone(tmp_path, capsys):
    card = _make_card()
    inp = tmp_path / "card.json"
    inp.write_text(json.dumps(card.model_dump(mode="json", exclude_none=False), ensure_ascii=False), encoding="utf-8")
    outdir = tmp_path / "out"
    outdir.mkdir()
    code = main(["card", str(inp), "--format", "telegram", "--out", str(outdir), "--with-contacts", "--purpose", "test"])
    captured = capsys.readouterr()
    assert code == 0, captured.out
    # phone should appear in either stdout or file
    combined = captured.out
    for f in outdir.iterdir():
        combined += f.read_text(encoding="utf-8")
    assert PHONE_BRACKETED in combined or PHONE_COMPACT in combined


def test_get_card_default_masks_phone(capsys):
    # patch get_card to return card with phone
    from nedviga.cian_live import get_card as real_get_card

    card = _make_card()
    with patch("nedviga.cli.get_card", return_value=card):
        code = main(["get-card", "900001"])
    captured = capsys.readouterr()
    assert code == 0, captured.out
    assert find_raw_phones(captured.out) == []
    payload = json.loads(captured.out)
    assert payload["metadata"]["contacts_open"] is False


def test_profiles_env_error_not_crash(monkeypatch, tmp_path):
    # invalid file path should not crash load_profiles
    from nedviga import profiles

    monkeypatch.setenv("NEDVIGA_PROFILES_JSON", str(tmp_path / "nope.json"))
    # should not raise
    profiles.load_profiles()


# ---- контроль качества (доводка фазы 2) ----
def _card_control(**over):
    base = dict(id="cian-9001", source="cian", url="https://www.cian.ru/sale/flat/9001/",
                title="Контроль")
    from nedviga.models import ListingCard
    c = ListingCard.model_validate(base)
    from nedviga.models import Geo, Building
    c.geo = Geo(district="ЮАО", area_name="Царицыно",
                cian_claimed_metro={"station": "Кантемировская", "claimed_time_minutes": 20})
    c.building = Building(building_type="monolith")
    for k, v in over.items():
        setattr(c, k, v)
    return c


def test_control_claimed_metro_fallback():
    from nedviga.family_card import build_family_card, render_telegram
    tg = render_telegram(build_family_card(_card_control()))
    assert "Кантемировская" in tg and "графом не проверено" in tg
    assert "Индивидуальный проект" in tg  # серия: фолбэк по ТЗ
    assert "монолит" in tg


def test_control_no_transport_to_center():
    from nedviga.family_card import build_family_card, render_telegram, render_html
    fc = build_family_card(_card_control())
    blob = render_telegram(fc) + render_html(fc)
    assert "до центра" not in blob.lower()
    assert "ЮАО" in blob and "Царицыно" in blob
