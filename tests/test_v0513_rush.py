"""v0.5.13 (the task brief) rush tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nedviga.cli import main


def test_rush_unavailable_without_egress(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("NEDVIGA_EGRESS_PROXY", raising=False)
    f = tmp_path / "card.json"
    f.write_text(json.dumps({"id": "cian-1", "source": "cian", "url": "u", "title": "flat", "geo": {"lat": 55.6, "lon": 37.6}}))
    code = main(["rush", "--file", str(f)])
    out = capsys.readouterr().out
    assert "unavailable" in out


def test_rush_parses_balls(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("NEDVIGA_EGRESS_PROXY", "http://proxy:8080")
    # mock browser traffic
    from unittest.mock import patch
    with patch("nedviga.rush._fetch_traffic", return_value="7 баллов"):
        f = tmp_path / "card.json"
        f.write_text(json.dumps({"id": "cian-1", "source": "cian", "url": "u", "title": "flat", "geo": {"lat": 55.6, "lon": 37.6}}))
        code = main(["rush", "--file", str(f)])
        out = capsys.readouterr().out
    assert "7 баллов" in out or "7" in out
    assert "прогноз недоступен" in out or "прогноз" in out.lower()


def test_rush_walk_present(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("NEDVIGA_EGRESS_PROXY", raising=False)
    f = tmp_path / "card.json"
    f.write_text(json.dumps({"id": "cian-1", "source": "cian", "url": "u", "title": "flat", "geo": {"lat": 55.6, "lon": 37.6}}))
    code = main(["rush", "--file", str(f)])
    out = capsys.readouterr().out
    assert "пешком" in out or "walk" in out.lower() or "metro" in out.lower()
