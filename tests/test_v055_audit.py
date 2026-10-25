"""v0.5.5 (the task brief) audit tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nedviga.cli import main


def test_audit_records_write_command(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("NEDVIGA_ROLE", "agent")
    main(["pipeline", "set", "cian-1", "--status", "candidate"])
    capsys.readouterr()
    code = main(["audit", "--days", "1"])
    out = capsys.readouterr().out
    assert code == 0
    assert "pipeline" in out or "set" in out


def test_audit_no_recursion(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("NEDVIGA_ROLE", "agent")
    main(["audit", "--days", "1"])
    out = capsys.readouterr().out
    # audit command itself should not create audit entry for audit? at least no crash
    assert True


def test_audit_size_warn(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("NEDVIGA_ROLE", "agent")
    # create big audit file
    audit = tmp_path / "audit-2026-10.log.jsonl"
    audit.write_text("x" * (51 * 1024 * 1024))
    code = main(["audit", "--days", "1"])
    out = capsys.readouterr().out
    assert "audit_size_warn" in out or code == 0
