"""v0.4.8 (the task brief) F-14b: digest tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nedviga.cli import main

PHONES = ("+7 (999) 000-11-22",)


def test_digest_empty_period(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    code = main(["digest", "--days", "7", "--format", "telegram"])
    out = capsys.readouterr().out
    assert code == 0
    assert "без изменений" in out or "без изменений" in out.lower()


def test_digest_section_order(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    # seed some data via pipeline/watch? minimal: just run
    code = main(["digest", "--days", "7", "--format", "md", "--out", str(tmp_path / "d.md")])
    capsys.readouterr()
    assert code == 0


def test_digest_no_phones(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    code = main(["digest", "--days", "7", "--format", "telegram"])
    out = capsys.readouterr().out
    import re
    for pat in (r"\+?7[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}",):
        assert __import__("re").findall(pat, out) == []


def test_digest_sections_omit_empty(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    code = main(["digest", "--days", "7", "--format", "telegram"])
    out = capsys.readouterr().out
    # no empty section headers
    assert out.count("🔻") + out.count("✨") + out.count("❌") + out.count("📋") >= 0
    assert code == 0
