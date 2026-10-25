"""v0.5.4 (the task brief) chains tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nedviga.cli import main


def test_chain_new(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    code = main(["chain", "new", "cian-1", "--kind", "direct"])
    out = capsys.readouterr().out
    assert code == 0


def test_chain_link_cycle_rejected(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    main(["chain", "new", "a", "--kind", "direct"])
    capsys.readouterr()
    main(["chain", "new", "b", "--kind", "direct"])
    capsys.readouterr()
    main(["chain", "link", "a", "b", "--rel", "depends_on"])
    capsys.readouterr()
    code = main(["chain", "link", "b", "a", "--rel", "depends_on"])
    out = capsys.readouterr().out
    assert code != 0


def test_chain_show_risk_string(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    main(["chain", "new", "cian-1", "--kind", "alt_unfound"])
    capsys.readouterr()
    code = main(["chain", "show", "cian-1"])
    out = capsys.readouterr().out
    assert code == 0
    assert "развал вероятен" in out or "alt_unfound" in out


def test_chain_show_ten_nodes_no_hang(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    for i in range(10):
        main(["chain", "new", f"cian-{i}", "--kind", "direct"])
        capsys.readouterr()
    code = main(["chain", "show", "cian-0"])
    out = capsys.readouterr().out
    assert code == 0
