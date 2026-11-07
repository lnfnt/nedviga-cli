# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 lnfnt <lnfnt@proton.me>

"""RED tests for v12c HIGH findings S2-F7, S2-F8, S2-F9."""
from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nedviga.cli import main


def _card(cid="cian-1", title="flat", status="active", sale_status=None,
          address="SECRET ADDRESS 123", price=100.0):
    c = {
        "id": cid,
        "source": "cian",
        "url": "https://example.com/x",
        "title": title,
        "status": status,
        "pricing": {"price_total_rub": price},
        "building": {"address_raw": address},
    }
    if sale_status is not None:
        c["sale_status"] = sale_status
    return c


# ---------- S2-F7 watch ----------

def test_s2f7_title_snyat_without_sold_status_not_sold(tmp_path, monkeypatch):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    from nedviga import watch

    db = tmp_path / "w.db"
    watch.add("cian-1", price=100.0, db=db)
    fresh = [_card(title="Снять с продажи квартира", status="active")]
    f = tmp_path / "fresh.json"
    f.write_text(json.dumps(fresh), encoding="utf-8")
    ev = watch.check(offline=str(f), db=db)
    assert not any(e.get("type") == "sold" for e in ev), ev


def test_s2f7_sale_status_sold_triggers_sold(tmp_path, monkeypatch):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    from nedviga import watch

    db = tmp_path / "w.db"
    watch.add("cian-1", price=100.0, db=db)
    fresh = [_card(status="active", sale_status="sold")]
    f = tmp_path / "fresh.json"
    f.write_text(json.dumps(fresh), encoding="utf-8")
    ev = watch.check(offline=str(f), db=db)
    assert any(e.get("type") == "sold" for e in ev), ev


def test_s2f7_broken_timestamp_not_fresh_digest(tmp_path, monkeypatch):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    from nedviga import pipeline, watch, digest

    db = tmp_path / "w.db"
    watch.add("cian-1", price=100.0, db=db)
    conn = pipeline._connect(db)
    try:
        conn.execute(
            "INSERT INTO watch_history (card_id, price, status, at) VALUES (?,?,?,?)",
            ("cian-1", 90.0, "active", "not-a-timestamp"),
        )
        conn.commit()
    finally:
        conn.close()

    d = digest.build_digest(days=7, db=db)
    assert d["reductions"] == [], d["reductions"]


def test_s2f7_broken_timestamp_status_history_not_fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    from nedviga import pipeline, digest

    db = tmp_path / "p.db"
    conn = pipeline._connect(db)
    try:
        conn.execute(
            "INSERT INTO status_history (card_id, from_status, to_status, at, note) "
            "VALUES (?,?,?,?,?)",
            ("cian-1", None, "shortlist", "broken-ts", None),
        )
        conn.commit()
    finally:
        conn.close()

    d = digest.build_digest(days=7, db=db)
    assert d["new_shortlist"] == [], d["new_shortlist"]


# ---------- S2-F8 auditlog ----------

def test_s2f8_read_skips_bad_line_and_returns_rest(tmp_path, monkeypatch):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    from nedviga import auditlog

    now = datetime.now(timezone.utc).isoformat()
    valid1 = {"ts": now, "role": "agent", "command": "a", "card_id": None,
              "rc": 0, "reason": None, "pii": False, "purpose": None,
              "argv_skeleton": []}
    valid2 = {"ts": now, "role": "agent", "command": "b", "card_id": None,
              "rc": 0, "reason": None, "pii": False, "purpose": None,
              "argv_skeleton": []}
    p = tmp_path / "audit-2026-11.log.jsonl"
    p.write_text(
        json.dumps(valid1) + "\n" + "NOT VALID JSON {{{\n" + json.dumps(valid2) + "\n",
        encoding="utf-8",
    )
    entries = auditlog.read_entries(days=30)
    assert len(entries) == 2, entries
    commands = {e.get("command") for e in entries}
    assert commands == {"a", "b"}


def test_s2f8_read_returns_valid_after_bad_in_middle(tmp_path, monkeypatch):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    from nedviga import auditlog

    now = datetime.now(timezone.utc).isoformat()
    items = []
    for cmd in ("first", "second", "third"):
        items.append({"ts": now, "role": "agent", "command": cmd, "card_id": None,
                      "rc": 0, "reason": None, "pii": False, "purpose": None,
                      "argv_skeleton": []})
    lines = [json.dumps(items[0]), "{bad", json.dumps(items[1]), "", json.dumps(items[2])]
    p = tmp_path / "audit-2026-11.log.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    entries = auditlog.read_entries(days=30)
    assert [e["command"] for e in entries] == ["first", "second", "third"]


# ---------- S2-F9 checklist ----------

def test_s2f9_traversal_card_id_no_write_outside_drafts(tmp_path, monkeypatch):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    from nedviga import checklist

    cards = [_card(cid="../escape", address="addr")]
    f = tmp_path / "cards.json"
    f.write_text(json.dumps(cards), encoding="utf-8")
    outside = tmp_path / "escape.md"
    if outside.exists():
        outside.unlink()

    try:
        res = checklist.handoff("../escape", "colleague", file=str(f))
    except Exception:
        res = {"ok": False}
    assert not outside.exists(), "draft written outside drafts dir"
    assert not (res or {}).get("ok"), res


def test_s2f9_handoff_does_not_send_full_address_to_binary(tmp_path, monkeypatch):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    from nedviga import checklist

    secret = "SECRET ADDRESS 123"
    cards = [_card(cid="cian-1", address=secret)]
    f = tmp_path / "cards.json"
    f.write_text(json.dumps(cards), encoding="utf-8")

    bin_path = tmp_path / "a2a"
    capture = tmp_path / "argv.txt"
    bin_path.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$@\" > " + str(capture) + "\n"
        "exit 0\n",
        encoding="utf-8",
    )
    bin_path.chmod(bin_path.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("A2A_BIN", str(bin_path))

    res = checklist.handoff("cian-1", "colleague", file=str(f))
    assert (res or {}).get("ok") is True, res
    captured = capture.read_text(encoding="utf-8") if capture.exists() else ""
    assert secret not in captured, "full address leaked to external binary"


def test_s2f9_traversal_via_cli_no_escape(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    cards = [_card(cid="../escape", address="addr")]
    f = tmp_path / "cards.json"
    f.write_text(json.dumps(cards), encoding="utf-8")
    outside = tmp_path / "escape.md"
    if outside.exists():
        outside.unlink()
    code = main(["checklist", "handoff", "../escape", "--to", "colleague", "--file", str(f)])
    capsys.readouterr()
    assert not outside.exists()
    assert code != 0
