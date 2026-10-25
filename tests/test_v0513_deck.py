"""v0.5.13 (the task brief §5.5) deck-тесты — Round-trip и честные числа."""
from __future__ import annotations

import json
from pathlib import Path

from nedviga.deck import deck_from_cards, DISCLAIMER

CARDS = [
    {"id": "cian-1", "source": "cian", "url": "u1", "title": "2-к",
     "pricing": {"price_total_rub": 15990000, "price_per_m2_rub": 382536},
     "parameters": {"rooms": 2, "area_total_m2": 41.8, "floor": 3, "floors_total": 5},
     "building": {"address_raw": "Петровско-Разумовский пр., 18А"}},
    {"id": "avito-0", "source": "avito", "url": None, "title": "1-к",
     "pricing": {"price_total_rub": 9800000, "price_per_m2_rub": 301000},
     "parameters": {"rooms": 1, "area_total_m2": 32.5, "floor": 2, "floors_total": 9},
     "building": {"address_raw": "ул. Кантемировская, 20к1"}},
]


def test_deck_roundtrip(tmp_path):
    out = tmp_path / "d.pptx"
    r = deck_from_cards(CARDS, str(out), title="Тест")
    assert r["status"] == "ok" and out.exists()
    from pptx import Presentation
    prs = Presentation(str(out))
    texts = [" ".join(sh.text_frame.text for sh in sl.shapes if sh.has_text_frame)
             + " ".join(c.text for g in (sl.shapes) if getattr(g, "has_table", False)
                        for g2 in [g] if g2.has_table for row in g2.table.rows for c in row.cells)
             for sl in prs.slides]
    blob = " ".join(texts)
    assert r["slides"] >= 4
    # числа карточек присутствуют на слайдах точно
    assert "15 990 000" in blob and "41.8" in blob
    assert "Петровско-Разумовский" in blob


def test_deck_disclaimer_last(tmp_path):
    from pptx import Presentation
    out = tmp_path / "d.pptx"
    deck_from_cards(CARDS, str(out))
    prs = Presentation(str(out))
    last = prs.slides[-1]
    blob = " ".join(sh.text_frame.text for sh in last.shapes if sh.has_text_frame)
    assert "внешних источников" in blob or "Проверяйте" in blob


def test_deck_cap15(tmp_path):
    many = [dict(CARDS[0], id=f"c-{i}") for i in range(40)]
    out = tmp_path / "big.pptx"
    r = deck_from_cards(many, str(out))
    assert r["cards"] <= 15


def test_deck_family_slide(tmp_path):
    fam = dict(CARDS[0], family_card={"verdict": "Нравится район"})
    out = tmp_path / "f.pptx"
    r = deck_from_cards([fam, CARDS[1]], str(out))
    assert r["slides"] >= 5  # титул/таблица/family/сводка/дисклеймер
