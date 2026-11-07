# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 lnfnt <lnfnt@proton.me>

"""RED tests for v12e HIGH findings S3-F1, S3-F2, S3-F3."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from nedviga import updater
from nedviga.updater import UpdaterError
from nedviga import mcp_server


@pytest.fixture()
def state(tmp_path, monkeypatch):
    sdir = tmp_path / "state"
    sdir.mkdir()
    (sdir / "pipeline.sqlite").write_text("local-data", encoding="utf-8")
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(sdir))
    return sdir


# ---------- S3-F1 updater git target ----------

def test_s3f1_run_update_git_traversal_target_not_invoked(state, tmp_path, monkeypatch):
    base = tmp_path / "work"
    base.mkdir()
    (tmp_path / "evil").mkdir()
    monkeypatch.chdir(base)
    calls = []

    def runner(cmd):
        calls.append(list(cmd))
        return 0, "ok"

    with pytest.raises(UpdaterError):
        updater.run_update("git", target="../evil", runner=runner)

    assert calls == [], "pip must not run for traversal target"


def test_s3f1_run_update_git_target_without_checkout_rejected(state, tmp_path):
    checkout = tmp_path / "not-a-checkout"
    checkout.mkdir()
    calls = []

    def runner(cmd):
        calls.append(list(cmd))
        return 0, "ok"

    with pytest.raises(UpdaterError):
        updater.run_update("git", target=str(checkout), runner=runner)

    assert calls == []


# ---------- S3-F2 data_preserved content snapshot ----------

def test_s3f2_data_preserved_false_when_state_content_changed(state):
    def runner(cmd):
        (state / "pipeline.sqlite").write_text("tampered", encoding="utf-8")
        return 0, "ok"

    res = updater.run_update("pypi", runner=runner)
    assert res["data_preserved"] is False


def test_s3f2_data_preserved_false_when_state_file_replaced(state):
    def runner(cmd):
        p = state / "pipeline.sqlite"
        p.unlink()
        p.write_text("different", encoding="utf-8")
        return 0, "ok"

    res = updater.run_update("pypi", runner=runner)
    assert res["data_preserved"] is False


# ---------- S3-F3 MCP isError ----------

def test_s3f3_mcp_cli_command_failure_is_error(tmp_path, monkeypatch):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(mcp_server._cli, "_cmd_stale", lambda ns: 3)

    resp = mcp_server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "stale", "arguments": {}}}
    )
    assert resp["result"]["isError"] is True


def test_s3f3_mcp_exception_is_error(tmp_path, monkeypatch):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))

    def boom(ns):
        raise RuntimeError("boom")

    monkeypatch.setattr(mcp_server._cli, "_cmd_stale", boom)

    resp = mcp_server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "stale", "arguments": {}}}
    )
    assert resp["result"]["isError"] is True
