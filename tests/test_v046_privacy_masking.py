"""v0.4.6 (the task brief) F-13: fail-closed privacy masking телефонов.

Инвариант: по умолчанию НИ в одном формате вывода (search stdout JSON,
файл --json, HTML-экспорт) не встречается сырой телефон; при --with-contacts
сырые номера возвращаются и в envelope/metadata присутствует явный маркер
contacts_open: true/false.

Номер-грейп тест (№2.2 ТЗ) — find_raw_phones() по всему выводу.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import patch

from nedviga.cli import main
from nedviga.export_html import export_html
from nedviga.models import ListingCard, Parameters, Pricing, Seller
from nedviga.pii import (
    PHONE_MASK,
    mask_phone_number,
    mask_phones,
    mask_phones_in_obj,
    sanitize_contacts,
)

# Синтетические номера (ТЗ §2.2): мобильный в скобках, городская с 8,
# компактный мобильный, «голый» группированный номер без кода страны.
PHONE_BRACKETED = "+7 (999) 000-11-22"
PHONE_LANDLINE = "8-495-777-77-77"
PHONE_COMPACT = "+79161234567"
PHONE_BARE_GROUPED = "495 123-45-67"

_RAW_PHONE_PATTERNS = (
    re.compile(r"\+?7[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}"),
    re.compile(r"(?<!\d)8[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}"),
    re.compile(r"(?<![\dA-Za-z])\d{3}[\s\-]\d{3}[\s\-]\d{2}[\s\-]\d{2}(?!\d)"),
)

MASKED_MARKER = "+7 *** ***-**-**"


def find_raw_phones(text: str) -> list[str]:
    """Номер-грейп: все сырые телефонные паттерны в тексте вывода."""
    hits: list[str] = []
    for pattern in _RAW_PHONE_PATTERNS:
        hits.extend(m.group(0) for m in pattern.finditer(text))
    return hits


def _make_card(
    *,
    cid: str = "cian-900001",
    num: str = "900001",
    phones: tuple[str, ...] = (PHONE_BRACKETED, PHONE_COMPACT),
    description: str | None = None,
) -> ListingCard:
    card = ListingCard(
        id=cid,
        source="cian",
        url=f"https://www.cian.ru/sale/flat/{num}/",
        title=f"2-комн. квартира, 54,3 м² (тест {cid})",
        pricing=Pricing(price_total_rub=16_000_000.0, price_per_m2_rub=294_659.0),
        parameters=Parameters(rooms=2, floor=5, floors_total=17, area_total_m2=54.3),
        seller=Seller(seller_type="owner", phones=list(phones)),
        description_text=description,
    )
    return card


def _fixture_cards() -> list[ListingCard]:
    return [
        _make_card(),
        _make_card(
            cid="cian-900002",
            num="900002",
            phones=(PHONE_LANDLINE,),
            description=(
                f"Звонить {PHONE_BRACKETED} или {PHONE_LANDLINE}, "
                f"альтернатива {PHONE_BARE_GROUPED}. Цена 16 000 000 ₽."
            ),
        ),
    ]


def _run_search_cli(capsys, argv: list[str]) -> tuple[int, str]:
    with patch("nedviga.cli.search", return_value=_fixture_cards()):
        code = main(["search", "--source", "cian", *argv])
    captured = capsys.readouterr()
    return code, captured.out


# ---------------------------------------------------------------- unit: pii


def test_mask_phones_variants_in_free_text():
    for raw in (PHONE_BRACKETED, PHONE_LANDLINE, PHONE_COMPACT, PHONE_BARE_GROUPED):
        masked = mask_phones(f"номер {raw} звоните")
        assert find_raw_phones(masked) == [], f"телефон не замаскирован: {raw!r}"
        assert MASKED_MARKER in masked
    # цены не повреждаются (регресс v0.4.3 sanity)
    assert mask_phones("16 000 000 ₽") == "16 000 000 ₽"


def test_mask_phone_number_fail_closed_on_unrecognized_slot():
    assert mask_phone_number(PHONE_COMPACT) == MASKED_MARKER
    assert mask_phone_number(MASKED_MARKER) == MASKED_MARKER  # идемпотентно
    # непонятная строка в слоте телефона -> полный маски (fail-closed)
    assert mask_phone_number("позвоните по viber") == MASKED_MARKER


def test_sanitize_contacts_masks_phone_slots_and_text():
    obj = {
        "seller": {"phones": [PHONE_BRACKETED, "some-unknown-digits"], "name": "Иван"},
        "description_text": f"тел {PHONE_LANDLINE}",
        "price_total_rub": 16_000_000.0,
    }
    out = sanitize_contacts(obj)
    assert find_raw_phones(json.dumps(out, ensure_ascii=False)) == []
    assert out["seller"]["name"] == "Иван"
    assert out["price_total_rub"] == 16_000_000.0
    # рекурсивная базовая функция не сломана
    assert isinstance(mask_phones_in_obj(["тут 8-495-777-77-77"]), list)


# ------------------------------------------------- acceptance: search (F-13)


def test_search_default_output_has_no_raw_phones(capsys):
    """Номер-грейп ТЗ §2.2: дефолтный JSON stdout строго маскирован."""
    code, out = _run_search_cli(capsys, [])
    assert code == 0, out
    assert find_raw_phones(out) == []
    assert MASKED_MARKER in out
    payload = json.loads(out)
    assert payload["metadata"]["contacts_open"] is False


def test_search_json_file_is_masked(capsys, tmp_path: Path):
    """cards.json (--json FILE) тоже строго маскирован и помечен."""
    target = tmp_path / "cards.json"
    code, _out = _run_search_cli(capsys, ["--json", str(target)])
    assert code == 0
    dumped = target.read_text(encoding="utf-8")
    assert find_raw_phones(dumped) == []
    payload = json.loads(dumped)
    assert payload["metadata"]["contacts_open"] is False
    assert MASKED_MARKER in dumped


def test_search_with_contacts_returns_raw_and_marker(capsys):
    """--with-contacts: сырые номера возвращены, contacts_open: true."""
    code, out = _run_search_cli(capsys, ["--with-contacts", "--purpose", "test"])
    assert code == 0, out
    payload = json.loads(out)
    assert payload["metadata"]["contacts_open"] is True
    flat = json.dumps(payload["data"], ensure_ascii=False)
    assert PHONE_BRACKETED in flat
    assert PHONE_LANDLINE in flat
    assert PHONE_COMPACT in flat


# --------------------------------------------------- acceptance: export (F-13)


def _write_cards_json(path: Path) -> None:
    raw = [c.model_dump(mode="json", exclude_none=False) for c in _fixture_cards()]
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")


def test_export_html_default_has_no_raw_phones(capsys, tmp_path: Path):
    """Номер-грейп ТЗ §2.2: HTML-экспорт по умолчанию без сырых телефонов."""
    cards_json = tmp_path / "cards.json"
    _write_cards_json(cards_json)
    catalog = tmp_path / "catalog.html"
    code = main(
        ["export", "--input", str(cards_json), "--output", str(catalog), "--format", "html"]
    )
    captured = capsys.readouterr()
    assert code == 0, captured.out
    html = catalog.read_text(encoding="utf-8")
    assert find_raw_phones(html) == []
    assert MASKED_MARKER in html
    payload = json.loads(captured.out)
    assert payload["metadata"]["contacts_open"] is False


def test_export_html_with_contacts_shows_raw_and_marker(capsys, tmp_path: Path):
    cards_json = tmp_path / "cards.json"
    _write_cards_json(cards_json)
    catalog = tmp_path / "catalog.html"
    code = main(
        [
            "export",
            "--input",
            str(cards_json),
            "--output",
            str(catalog),
            "--with-contacts", "--purpose", "test",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0, captured.out
    html = catalog.read_text(encoding="utf-8")
    assert PHONE_BRACKETED in html
    assert PHONE_LANDLINE in html
    payload = json.loads(captured.out)
    assert payload["metadata"]["contacts_open"] is True


def test_export_html_library_default_fail_closed(tmp_path: Path):
    """export_html() как библиотека: маскирование по умолчанию даже без CLI."""
    out = export_html(_fixture_cards(), tmp_path / "catalog.html")
    html = out.read_text(encoding="utf-8")
    assert find_raw_phones(html) == []
    assert MASKED_MARKER in html
    # а с with_contacts=True — открываются
    out2 = export_html(
        _fixture_cards(), tmp_path / "catalog2.html", with_contacts=True
    )
    assert PHONE_BRACKETED in out2.read_text(encoding="utf-8")
