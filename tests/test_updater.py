# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 lnfnt <lnfnt@proton.me>

"""Offline tests for nedviga-cli update (TASK_UPDATER.md)."""

from __future__ import annotations

import json
import sys

import pytest

from nedviga import __version__, updater
from nedviga.cli import main
from nedviga.updater import UpdaterError


@pytest.fixture()
def state(tmp_path, monkeypatch):
    """Isolated state dir with a local file that MUST survive an update."""
    sdir = tmp_path / "state"
    sdir.mkdir()
    (sdir / "pipeline.sqlite").write_text("local-data", encoding="utf-8")
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(sdir))
    return sdir


def test_check_update_pypi_mocked():
    res = updater.check_update("pypi", _fetch=lambda s, t: "9.9.9")
    assert res["ok"] is True
    assert res["current_version"] == __version__
    assert res["latest_version"] == "9.9.9"
    assert res["update_available"] is True
    assert res["data_safe"] is True


def test_check_update_git_target_rejected_if_not_package_name(tmp_path):
    with pytest.raises(UpdaterError):
        updater.check_update("git", target=str(tmp_path))


def test_run_update_success_mock_runner(state):
    calls = []

    def runner(cmd):
        calls.append(cmd)
        return 0, "Successfully installed nedviga-cli-9.9.9"

    res = updater.run_update("pypi", runner=runner)
    assert calls == [[sys.executable, "-m", "pip", "install", "--upgrade", "nedviga-cli"]]
    assert res["ok"] is True
    assert res["data_safe"] is True
    assert res["data_preserved"] is True
    assert res["state_dir"] == str(state)
    assert res["from_version"] == __version__


def test_run_update_git_target_in_command(state):
    seen = {}

    def runner(cmd):
        seen["cmd"] = cmd
        return 0, "ok"

    updater.run_update("git", target="nedviga-cli", runner=runner)
    assert seen["cmd"][-2:] == ["--upgrade", "nedviga-cli"]


def test_run_update_failure_fail_closed(state):
    def runner(cmd):
        return 1, "ERROR: pip failed"

    with pytest.raises(UpdaterError, match="UPDATE_FAILED"):
        updater.run_update("pypi", runner=runner)


def test_state_files_survive_update(state):
    def runner(cmd):
        return 0, "ok"

    updater.run_update("pypi", runner=runner)
    assert (state / "pipeline.sqlite").read_text(encoding="utf-8") == "local-data"


def test_cli_update_check(state, monkeypatch, capsys):
    monkeypatch.setattr(updater, "_pypi_latest", lambda s, t: "9.9.9")
    rc = main(["update", "--check"])
    envelope = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert envelope["status"] == "ok"
    assert envelope["data"]["update_available"] is True
    assert envelope["data"]["data_safe"] is True


def test_cli_update_run_mock(state, monkeypatch, capsys):
    monkeypatch.setattr(updater, "_default_runner", lambda cmd: (0, "ok"))
    rc = main(["update"])
    envelope = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert envelope["status"] == "ok"
    assert envelope["data"]["command"] == [
        sys.executable, "-m", "pip", "install", "--upgrade", "nedviga-cli"
    ]
    assert envelope["data"]["data_preserved"] is True


def test_cli_update_failure(state, monkeypatch, capsys):
    monkeypatch.setattr(updater, "_default_runner", lambda cmd: (1, "boom"))
    rc = main(["update"])
    envelope = json.loads(capsys.readouterr().out)
    assert rc == 3
    assert envelope["status"] == "error"
    assert envelope["reason"].startswith("UPDATE_FAILED")
    # данные не пострадали
    assert (state / "pipeline.sqlite").exists()


def test_check_update_network_failure_fail_closed(state):
    def broken_fetch(source, target):
        raise OSError("network down")

    with pytest.raises(UpdaterError, match="UPDATE_FAILED"):
        updater.check_update("pypi", _fetch=broken_fetch)
