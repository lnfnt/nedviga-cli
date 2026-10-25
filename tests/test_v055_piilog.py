"""v0.5.5 (the task brief) pii-log tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from nedviga.cli import main
from nedviga.models import ListingCard


def test_pii_purpose_required(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("NEDVIGA_ROLE", "agent")
    card = ListingCard(id="cian-1", source="cian", url="u", seller=ListingCard.__fields__["seller"].default_factory() if False else None) if False else None
    # simpler: patch get_card
    from nedviga.models import Seller
    c = ListingCard(id="cian-1", source="cian", url="u", seller=Seller(phones=["+7 (999) 000-11-22"]))
    with patch("nedviga.cli.get_card", return_value=c):
        code = main(["get-card", "cian-1", "--with-contacts"])
    out = capsys.readouterr().out
    assert "pii_purpose_required" in out or code != 0


def test_pii_log_command(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("NEDVIGA_ROLE", "agent")
    code = main(["pii-log", "--days", "1"])
    out = capsys.readouterr().out
    assert code == 0
