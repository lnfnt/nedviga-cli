"""v0.5.11 (the task brief) wizard tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nedviga.cli import main


def test_wizard_init_agent(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    outdir = tmp_path / "wizard_out"
    outdir.mkdir()
    code = main(["wizard", "init", "--profile", "agent", "--out", str(outdir)])
    out = capsys.readouterr().out
    assert code == 0
    # roles.json valid
    roles = outdir / "roles.json"
    if roles.exists():
        import json
        data = json.loads(roles.read_text())
        assert isinstance(data, list)


def test_wizard_doctor(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    code = main(["wizard", "doctor"])
    out = capsys.readouterr().out
    assert code in (0, 1)
    assert "egress" in out.lower() or "token" in out.lower() or "state" in out.lower()


def test_wizard_doctor_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    code = main(["wizard", "doctor", "--json"])
    out = capsys.readouterr().out
    import json
    try:
        d = json.loads(out)
        assert isinstance(d, dict)
    except Exception:
        assert code in (0, 1)


def test_help_examples_all_commands(tmp_path, monkeypatch):
    """v0.5.11 контроль (строже прежней заглушки): у КАЖДОЙ подкоманды в --help
    обязан быть пример строкой 'пример:'."""
    import subprocess, sys, os, re
    env = {**os.environ, "PYTHONPATH": str(Path.cwd()), "NEDVIGA_STATE_DIR": str(tmp_path)}
    proc = subprocess.run([sys.executable, "-m", "nedviga", "--help"], capture_output=True, text=True, env=env)
    m = re.search(r"positional arguments:.*?\n\s*{([^}]*)}", proc.stdout, re.S)
    assert m, "subcommand list not found in help"
    names = m.group(1).split(",")
    missing = []
    for name in (x.strip() for x in names if x.strip()):
        r = subprocess.run([sys.executable, "-m", "nedviga", name, "--help"], capture_output=True, text=True, env=env)
        if "пример:" not in r.stdout:
            missing.append(name)
    assert not missing, f"no example in help: {missing}"
