"""v0.5.5 (the task brief) purge tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nedviga.cli import main


def test_purge_dry_default(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("NEDVIGA_ROLE", "agent")
    code = main(["purge", "card", "cian-1"])
    out = capsys.readouterr().out
    assert code == 0
    assert "dry" in out.lower() or "would" in out.lower() or "preview" in out.lower()


def test_purge_yes_idempotent(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("NEDVIGA_ROLE", "agent")
    main(["purge", "card", "cian-1", "--yes"])
    capsys.readouterr()
    code = main(["purge", "card", "cian-1", "--yes"])
    out = capsys.readouterr().out
    assert code == 0
    assert "not_found" in out or "0" in out


def test_purge_audit_survives(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("NEDVIGA_ROLE", "agent")
    main(["purge", "card", "cian-1", "--yes"])
    capsys.readouterr()
    code = main(["audit", "--days", "1"])
    out = capsys.readouterr().out
    assert code == 0
    assert "purge" in out
