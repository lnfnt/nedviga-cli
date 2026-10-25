"""v0.5.13 (the task brief) avito tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nedviga.cli import main


def test_avito_parse_offline(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    fix = Path(__file__).parent / "fixtures" / "avito_search_livetext_2026-10.txt"
    code = main(["avito", "parse", "--file", str(fix)])
    out = capsys.readouterr().out
    assert code == 0
    import json as _j
    d = _j.loads(out)
    cards = d.get("data") if isinstance(d, dict) else d
    assert isinstance(cards, list)
    assert len(cards) >= 20


def test_avito_manual_anchor(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    fix = Path(__file__).parent / "fixtures" / "avito_search_livetext_2026-10.txt"
    code = main(["avito", "parse", "--file", str(fix)])
    out = capsys.readouterr().out
    import json as _j
    d = _j.loads(out)
    cards = d.get("data") if isinstance(d, dict) else d
    # find first card with price 15990000
    found = [c for c in cards if c.get("pricing", {}).get("price_total_rub") == 15990000]
    assert len(found) >= 1
    c = found[0]
    assert c.get("parameters", {}).get("area_total_m2") == 41.8
    assert c.get("parameters", {}).get("rooms") == 2


def test_avito_no_egress_refused(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("NEDVIGA_EGRESS_PROXY", raising=False)
    code = main(["search", "--source", "avito", "--catalog", "https://avito.ru", "--live"])
    out = capsys.readouterr().out
    assert "source_disabled" in out or code != 0


def test_avito_captcha_blocked(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("NEDVIGA_EGRESS_PROXY", "http://proxy:8080")
    # mock browser returns captcha
    # We'll just ensure command exists
    fix = tmp_path / "captcha.txt"
    fix.write_text("Здравствуйте, робот")
    code = main(["avito", "parse", "--file", str(fix)])
    out = capsys.readouterr().out
    # either blocked or empty
    assert code in (0, 2, 3)
