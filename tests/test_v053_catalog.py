"""v0.5.3 (the task brief) catalog-pdf tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from nedviga.cli import main


def _cards(n=5):
    return [{"id": f"c{i}", "source": "cian", "url": f"u{i}", "title": f"flat {i}",
             "pricing": {"price_total_rub": 100.0, "price_per_m2_rub": 10.0},
             "parameters": {"rooms": 1, "area_total_m2": 30.0},
             "building": {"address_raw": "addr"}, "geo": {"district": "d"}} for i in range(n)]


def test_catalog_pdf_too_many(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "cards.json"
    f.write_text(json.dumps(_cards(31)))
    code = main(["catalog-pdf", "--file", str(f), "--out", str(tmp_path / "k.pdf")])
    out = capsys.readouterr().out
    assert "too_many" in out


def test_catalog_pdf_fail_closed_no_weasyprint(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "cards.json"
    f.write_text(json.dumps(_cards(3)))
    with patch.dict("sys.modules", {"weasyprint": None}):
        code = main(["catalog-pdf", "--file", str(f), "--out", str(tmp_path / "k.pdf")])
    out = capsys.readouterr().out
    assert "pdf-format-unavailable" in out or code != 0


def test_catalog_pdf_basic(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "cards.json"
    f.write_text(json.dumps(_cards(3)))
    # weasyprint absent in env -> fail-closed; just run
    code = main(["catalog-pdf", "--file", str(f), "--out", str(tmp_path / "k.pdf")])
    out = capsys.readouterr().out
    assert code in (0, 3)


# ---- контроль качества v0.5.3 ----
def test_control_catalog_caps_six_photos_and_shows_meta(tmp_path, monkeypatch):
    """капер ≤6 фото/карточку живёт именно в каталоге (одиночная family-card
    по контракту v0.4.7 рендерит ВСЕ), плюс титульная страница с n объектов."""
    from nedviga.models import ListingCard
    import nedviga.export_pdf as ep
    import sys, types
    c = ListingCard.model_validate({
        "id": "cian-1", "source": "cian", "url": "https://cian.ru/1", "title": "тест",
        "pricing": {"price_total_rub": 9000000},
        "parameters": {"area_total_m2": 40, "rooms": 2},
        "geo": {"district": "ЮАО"},
        "images": [{"url": f"data:image/png;base64,iVB{i}AAAA=", "alt": "p"} for i in range(8)]})
    captured = {}
    class FakeHTML:
        def __init__(self, string): captured['html'] = string
        def write_pdf(self, path): open(path, 'wb').write(b'%PDF-1.4 fake')
    fake = types.ModuleType('weasyprint'); fake.HTML = FakeHTML
    monkeypatch.setitem(sys.modules, 'weasyprint', fake)
    out = ep.catalog_pdf([c], tmp_path / 'k.pdf', title='Каталог', profile='agent-profile')
    h = captured['html']
    assert h.count('<img') <= 6
    assert 'Объектов: 1' in h and 'agent-profile' in h and 'Каталог' in h
    assert out.exists()
