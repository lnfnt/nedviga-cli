"""v0.5.5 (the task brief) roles tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nedviga.cli import main


def _setup_roles(tmp_path, monkeypatch):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    roles = tmp_path / "roles.json"
    roles.write_text(json.dumps([{"name": "alice", "role": "agent", "since": "2026-01-01"},
                                {"name": "fam", "role": "family", "since": "2026-01-01"}]))
    monkeypatch.setenv("NEDVIGA_ROLE", "family")
    # tell system where roles manifest is via env?
    monkeypatch.setenv("NEDVIGA_ROLES_FILE", str(roles))


def test_unknown_role_rejected(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("NEDVIGA_ROLE", "ghost")
    code = main(["pipeline", "list"])
    out = capsys.readouterr().out
    assert "unknown_role" in out or code != 0


def test_family_with_contacts_masked(tmp_path, monkeypatch, capsys):
    _setup_roles(tmp_path, monkeypatch)
    # get-card with --with-contacts should still mask
    from unittest.mock import patch
    card = {"id": "cian-1", "source": "cian", "url": "u", "title": "flat", "seller": {"phones": ["+7 (999) 000-11-22"]}}
    with patch("nedviga.cli.get_card", return_value=__import__("nedviga.models", fromlist=["ListingCard"]).ListingCard(**card)):
        code = main(["get-card", "cian-1", "--with-contacts", "--purpose", "test"])
    out = capsys.readouterr().out
    assert "+7 ***" in out or "+7 *** ***-**-**" in out


def test_family_write_forbidden(tmp_path, monkeypatch, capsys):
    _setup_roles(tmp_path, monkeypatch)
    code = main(["watch", "add", "cian-1"])
    out = capsys.readouterr().out
    assert "role_forbidden" in out or code != 0


def test_envelope_has_role(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("NEDVIGA_ROLE", "agent")
    code = main(["pipeline", "list"])
    out = capsys.readouterr().out
    import json
    d = json.loads(out)
    assert "role" in (d.get("metadata") or {}) or "role" in d
