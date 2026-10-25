"""v0.5.14 (the task brief §1) domclick-адаптер — офлайн по боевой обезличенной фикстуре."""
from __future__ import annotations

import json
from pathlib import Path

from nedviga.cli import main
from nedviga.sources_domclick import parse_domclick_text, browser_search_domclick

FIX = Path(__file__).parent / "fixtures" / "domclick_search_livetext_2026-10.txt"


def test_cards_extracted():
    cards = parse_domclick_text(FIX.read_text())
    assert len(cards) >= 10


def test_manual_anchor_20700000():
    cards = parse_domclick_text(FIX.read_text())
    c = [x for x in cards if x["pricing"]["price_total_rub"] == 20700000]
    assert c, "anchor card missing"
    assert c[0]["parameters"]["area_total_m2"] == 38.42
    assert c[0]["parameters"]["rooms"] == 1
    assert c[0]["building"]["complex"] and "Дубровка" in c[0]["building"]["complex"]


def test_anchor_21493640_floor():
    cards = parse_domclick_text(FIX.read_text())
    c = [x for x in cards if x["pricing"]["price_total_rub"] == 21493640][0]
    assert c["parameters"]["floor"] == 12 and c["parameters"]["floors_total"] == 14


def test_no_url_fabrication():
    cards = parse_domclick_text(FIX.read_text())
    assert all(c["url"] is None for c in cards)


def test_no_contacts():
    blob = FIX.read_text()
    cards = parse_domclick_text(blob)
    s = json.dumps(cards, ensure_ascii=False)
    assert "Показать телефон" not in s and "Написать" not in s
    import re
    assert not re.search(r"7\s?9\d{9}", s)


def test_rubbish_empty():
    assert parse_domclick_text("Привет\nмир\n500 ₽") == []


def test_browser_disabled_without_egress(monkeypatch):
    monkeypatch.delenv("NEDVIGA_EGRESS_PROXY", raising=False)
    try:
        browser_search_domclick("https://domclick.ru/search")
        assert False, "must raise"
    except RuntimeError as e:
        assert "source_disabled" in str(e)


def test_cli_parse(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    code = main(["domclick", "parse", "--file", str(FIX)])
    assert code == 0
    d = json.loads(capsys.readouterr().out)
    assert d["status"] == "ok" and len(d["data"]) >= 10


def test_cli_search_offline_refused(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("NEDVIGA_EGRESS_PROXY", raising=False)
    code = main(["search", "--source", "domclick", "--catalog", "https://x"])
    assert code != 0
    d = json.loads(capsys.readouterr().out)
    assert d["reason"] in ("source_disabled",)


def test_cli_search_replay_input(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    code = main(["search", "--source", "domclick", "--input", str(FIX)])
    assert code == 0
    d = json.loads(capsys.readouterr().out)
    assert d["status"] == "ok" and len(d["data"]) >= 10
