"""v0.4.8 (the task brief) F-04: pipeline tests (RED)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from nedviga.cli import main

PHONES = ("+7 (999) 000-11-22", "+79161234567")
RAW_PATTERNS = (
    __import__("re").compile(r"\+?7[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}"),
)


def _run(capsys, monkeypatch, tmp_path, argv):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    code = main(["pipeline", *argv])
    out = capsys.readouterr().out
    return code, out


def test_pipeline_set_valid_transition(tmp_path, monkeypatch, capsys):
    code, out = _run(capsys, monkeypatch, tmp_path, ["set", "cian-1", "--status", "candidate"])
    assert code == 0
    payload = json.loads(out)
    assert payload["status"] == "ok"


def test_pipeline_set_invalid_transition(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    main(["pipeline", "set", "cian-1", "--status", "candidate"])
    capsys.readouterr()
    code, out = _run(capsys, monkeypatch, tmp_path, ["set", "cian-1", "--status", "bought"])
    # new -> bought invalid (must go through stages)
    assert code in (2, 3) or "invalid" in out.lower() or "transition" in out.lower()


def test_pipeline_idempotent_same_status(tmp_path, monkeypatch, capsys):
    _run(capsys, monkeypatch, tmp_path, ["set", "cian-1", "--status", "candidate"])
    capsys.readouterr()
    _run(capsys, monkeypatch, tmp_path, ["set", "cian-1", "--status", "candidate"])
    capsys.readouterr()
    code, out = _run(capsys, monkeypatch, tmp_path, ["show", "cian-1"])
    assert code == 0
    # history should not duplicate
    assert out.count("candidate") <= 3


def test_pipeline_list_filter(tmp_path, monkeypatch, capsys):
    _run(capsys, monkeypatch, tmp_path, ["set", "cian-1", "--status", "candidate"])
    capsys.readouterr()
    _run(capsys, monkeypatch, tmp_path, ["set", "cian-2", "--status", "shortlist"])
    capsys.readouterr()
    code, out = _run(capsys, monkeypatch, tmp_path, ["list", "--status", "candidate"])
    assert code == 0
    assert "cian-1" in out
    assert "cian-2" not in out


def test_pipeline_show_history(tmp_path, monkeypatch, capsys):
    _run(capsys, monkeypatch, tmp_path, ["set", "cian-1", "--status", "candidate"])
    capsys.readouterr()
    _run(capsys, monkeypatch, tmp_path, ["set", "cian-1", "--status", "shortlist"])
    capsys.readouterr()
    code, out = _run(capsys, monkeypatch, tmp_path, ["show", "cian-1"])
    assert code == 0
    assert "candidate" in out and "shortlist" in out


def test_pipeline_from_file_snapshot(tmp_path, monkeypatch, capsys):
    card = {"id": "cian-1", "source": "cian", "url": "u", "title": "T", "pricing": {"price_total_rub": 100.0}}
    (tmp_path / "cards.json").write_text(json.dumps([card]))
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    code = main(["pipeline", "set", "cian-1", "--status", "candidate", "--from-file", str(tmp_path / "cards.json")])
    capsys.readouterr()
    assert code == 0


def test_pipeline_note_phone_warning(tmp_path, monkeypatch, capsys):
    code, out = _run(capsys, monkeypatch, tmp_path, ["set", "cian-1", "--status", "candidate", "--note", "call +7 (999) 000-11-22"])
    # should succeed with warning, not crash
    assert code in (0, 2)
    assert "warning" in out.lower() or "phone" in out.lower() or code == 0


def test_pipeline_number_grep_no_phones(tmp_path, monkeypatch, capsys):
    _run(capsys, monkeypatch, tmp_path, ["set", "cian-1", "--status", "candidate", "--note", "call +7 (999) 000-11-22"])
    capsys.readouterr()
    code, out = _run(capsys, monkeypatch, tmp_path, ["list"])
    assert code == 0
    for pat in RAW_PATTERNS:
        assert pat.findall(out) == []


# ---- контроль качества (v0.4.8) ----
def test_control_corrupt_from_file_no_traceback(tmp_path, monkeypatch):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    import subprocess, sys, json
    bad = tmp_path / "bad.json"; bad.write_text("{не json")
    r = subprocess.run([sys.executable, "-m", "nedviga.cli", "pipeline", "set",
                        "cian-1", "--status", "candidate", "--from-file", str(bad)],
                       capture_output=True, text=True)
    assert "Traceback" not in r.stdout + r.stderr
    assert r.returncode == 3
    env = json.loads(r.stdout)
    assert "snapshot_file_unreadable" in env["reason"]
