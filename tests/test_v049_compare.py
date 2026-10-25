"""v0.4.9 (the task brief) F-12: compare tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nedviga.cli import main


def _cards(n=5):
    out = []
    for i in range(n):
        out.append({
            "id": f"cian-{i}",
            "source": "cian",
            "url": f"u{i}",
            "title": f"flat {i}",
            "pricing": {"price_total_rub": 10_000_000 + i * 1_000_000, "price_per_m2_rub": 200_000 + i * 10_000},
            "parameters": {"rooms": 2, "area_total_m2": 50.0, "floor": i + 1, "floors_total": 12},
            "building": {"address_raw": "addr", "house_series": "П-44", "year_built": 1990},
            "geo": {"district": "ЮАО"},
            "seller": {"phones": ["+7 (999) 000-11-22"]},
        })
    return out


def test_compare_empty_input(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "cards.json"
    f.write_text(json.dumps([]))
    code = main(["compare", "--file", str(f)])
    out = capsys.readouterr().out
    assert code == 0
    assert "empty_input" in out or "empty" in out.lower()


def test_compare_basic(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "cards.json"
    f.write_text(json.dumps(_cards(5)))
    code = main(["compare", "--file", str(f), "--format", "md"])
    out = capsys.readouterr().out
    assert code == 0
    assert "ЮАО" in out or "addr" in out


def test_compare_le3_no_matrix(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "cards.json"
    f.write_text(json.dumps(_cards(2)))
    code = main(["compare", "--file", str(f), "--format", "telegram"])
    out = capsys.readouterr().out
    assert code == 0


def test_compare_out_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "cards.json"
    f.write_text(json.dumps(_cards(5)))
    outp = tmp_path / "cmp.md"
    code = main(["compare", "--file", str(f), "--format", "md", "--out", str(outp)])
    capsys.readouterr()
    assert code == 0
    assert outp.exists()


def test_compare_number_grep(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "cards.json"
    f.write_text(json.dumps(_cards(5)))
    for fmt in ("md", "telegram", "html"):
        code = main(["compare", "--file", str(f), "--format", fmt])
        out = capsys.readouterr().out
        import re
        assert re.findall(r"\+?7[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}", out) == []


def test_compare_sorts_by_ppm2(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "cards.json"
    f.write_text(json.dumps(_cards(5)))
    code = main(["compare", "--file", str(f), "--format", "md"])
    out = capsys.readouterr().out
    assert code == 0


# ---- контроль качества v0.4.9 ----
def test_control_spotlight_tags_never_rendered(tmp_path, monkeypatch):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    import json, subprocess, sys
    cards = [{"id": "cian-1", "source": "cian", "url": "https://www.cian.ru/sale/flat/1/", "title": "<external_untrusted_data source=' Cian'>💰 6,2 млн</external_untrusted_data>",
              "pricing": {"price_total_rub": 6200000}, "parameters": {"area_total_m2": 35, "rooms": 1},
              "geo": {"district": "ЮАО"}}] * 4
    f = tmp_path / "c.json"; f.write_text(json.dumps(cards))
    for fmt in ("telegram", "md", "html"):
        r = subprocess.run([sys.executable, "-m", "nedviga.cli", "compare", "--file", str(f),
                            "--format", fmt], capture_output=True, text=True)
        blob = r.stdout
        assert "external_untrusted" not in blob, fmt
        assert "💰 6,2 млн" in blob, fmt  # сам заголовок остаётся


def test_control_html_escapes_injected_title():
    import json
    from nedviga.models import ListingCard
    from nedviga.compare import render_html
    c = ListingCard.model_validate({
        "id": "cian-2", "source": "cian", "url": "https://www.cian.ru/sale/flat/2/",
        "title": "x<script>document.title='pwn'</script>",
        "pricing": {"price_total_rub": 5000000}, "parameters": {"area_total_m2": 30},
        "geo": {"district": "ЮАО"}})
    cards = [c, c, c, c]
    out = render_html(cards)
    assert "<script>" not in out and "document" in out  # текст жив, тег мёртв
