# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 lnfnt <lnfnt@proton.me>

"""RED tests for Phase 1 CRITICAL findings (S2-F2, S2-F3, S1-F2).

All DB/file paths are isolated via NEDVIGA_STATE_DIR + tmp_path.
These tests are expected to FAIL against the current (unfixed) code.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nedviga import browser_native as bn
from nedviga import pipeline
from nedviga.cli import main
from nedviga.errors import FetchError
from nedviga.roles import check_permission


def _state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))


# ---------------------------------------------------------------------------
# S2-F2: purge
# ---------------------------------------------------------------------------


def test_purge_active_object_not_deleted(tmp_path, monkeypatch, capsys):
    _state(tmp_path, monkeypatch)
    monkeypatch.setenv("NEDVIGA_ROLE", "agent")
    pipeline.set_status("cian-1", "shortlist", title="flat", price=1_000_000)

    main(["purge", "card", "cian-1", "--yes"])
    capsys.readouterr()

    items = pipeline.list_items()
    assert any(i["card_id"] == "cian-1" for i in items)


def test_purge_db_failure_rolls_back(tmp_path, monkeypatch, capsys):
    _state(tmp_path, monkeypatch)
    monkeypatch.setenv("NEDVIGA_ROLE", "agent")
    pipeline.set_status("cian-1", "rejected", title="flat", price=1_000_000)

    original = pipeline._connect

    class _Wrapped:
        def __init__(self, conn):
            self._conn = conn

        def execute(self, sql, *a, **k):
            if sql.strip().upper().startswith("DELETE") and "STATUS_HISTORY" in sql.upper():
                raise sqlite3.OperationalError("boom")
            return self._conn.execute(sql, *a, **k)

        def __getattr__(self, name):
            return getattr(self._conn, name)

    def patched(db=None):
        return _Wrapped(original(db))

    monkeypatch.setattr("nedviga.pipeline._connect", patched)

    out = ""
    try:
        main(["purge", "card", "cian-1", "--yes"])
        out = capsys.readouterr().out
    except Exception:
        out = capsys.readouterr().out

    items = pipeline.list_items()
    assert any(i["card_id"] == "cian-1" for i in items)

    try:
        data = json.loads(out)
        assert not (data.get("ok") is True and (data.get("deleted") or 0) > 0)
    except (json.JSONDecodeError, AttributeError):
        pass


# ---------------------------------------------------------------------------
# S2-F3: roles
# ---------------------------------------------------------------------------


def _setup_role(tmp_path: Path, monkeypatch, role: str) -> None:
    _state(tmp_path, monkeypatch)
    roles = tmp_path / "roles.json"
    roles.write_text(json.dumps([{"name": "u", "role": role, "since": "2026-01-01"}]))
    monkeypatch.setenv("NEDVIGA_ROLES_FILE", str(roles))
    monkeypatch.setenv("NEDVIGA_ROLE", role)


@pytest.mark.parametrize(
    "argv",
    [
        ["deck"],
        ["auto", "run"],
        ["dossier", "sync", "--dataset", "nope"],
        ["noise", "sync"],
        ["text", "index", "--file", "nope.json"],
        ["project", "new", "p"],
    ],
)
def test_roles_auditor_denies_write_commands(tmp_path, monkeypatch, capsys, argv):
    _setup_role(tmp_path, monkeypatch, "auditor")
    main(list(argv))
    out = capsys.readouterr().out
    assert "role_forbidden" in out


@pytest.mark.parametrize(
    "argv",
    [
        ["deck"],
        ["auto", "run"],
        ["dossier", "sync", "--dataset", "nope"],
        ["noise", "sync"],
    ],
)
def test_roles_family_denies_write_commands(tmp_path, monkeypatch, capsys, argv):
    _setup_role(tmp_path, monkeypatch, "family")
    main(list(argv))
    out = capsys.readouterr().out
    assert "role_forbidden" in out


def test_roles_is_write_covers_new_commands():
    import argparse
    from nedviga.roles import is_write

    for cmd in ("deck", "auto", "dossier", "noise", "text", "update"):
        ns = argparse.Namespace(command=cmd)
        for attr in ("pipeline_action", "watch_action", "feedback_action",
                     "project_action", "chain_action", "checklist_action",
                     "text_action", "sources_action", "auto_action",
                     "dossier_action", "noise_action"):
            setattr(ns, attr, None)
        if cmd == "auto":
            ns.auto_action = "run"
        if cmd == "dossier":
            ns.dossier_action = "sync"
        if cmd == "noise":
            ns.noise_action = "sync"
        if cmd == "text":
            ns.text_action = "index"
        assert is_write(ns) is True, cmd


# ---------------------------------------------------------------------------
# S1-F2: browser_native egress
# ---------------------------------------------------------------------------


def test_browser_native_no_egress_raises(monkeypatch):
    monkeypatch.delenv("NEDVIGA_EGRESS_PROXY", raising=False)
    fake = MagicMock()
    fake.return_value.__enter__.return_value = MagicMock()
    with patch("camoufox.sync_api.Camoufox", fake):
        with pytest.raises((FetchError, RuntimeError, ValueError)):
            bn._launch_browser()


def test_browser_native_passes_proxy(monkeypatch):
    monkeypatch.setenv("NEDVIGA_EGRESS_PROXY", "http://proxy:8080")
    fake = MagicMock()
    fake.return_value.__enter__.return_value = MagicMock()
    with patch("camoufox.sync_api.Camoufox", fake):
        try:
            bn._launch_browser()
        except Exception:
            pass
    assert fake.called
    _, kwargs = fake.call_args
    assert kwargs.get("proxy") == {"server": "http://proxy:8080"}
