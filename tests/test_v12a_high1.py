# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 lnfnt <lnfnt@proton.me>

"""RED tests for v12a HIGH findings S1-F3, S1-F4, S1-F6."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nedviga.cli import main


def test_s1f3_avito_price_zero_is_degraded_not_ok(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("NEDVIGA_DRIFT_FILE", str(tmp_path / "drift.jsonl"))
    fix = tmp_path / "zero.txt"
    fix.write_text("1-к. квартира, 40 м², 1/10 эт.\nАдрес\n", encoding="utf-8")
    code = main(["avito", "parse", "--file", str(fix)])
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "degraded", out.get("status")


def test_s1f4_routing_cache_poisoned_entry_not_verified(tmp_path, monkeypatch):
    import nedviga.routing_cache as rc
    from nedviga.geo_routing import walk_route

    lat, lon, station = 55.8200, 37.6410, "ВДНХ"
    db = rc._DEFAULT
    conn = rc._connect(db)
    try:
        key = rc.cache_key(lat, lon, station)
        # poisoned: invalid meters + bogus provider + expired timestamp
        conn.execute(
            "INSERT OR REPLACE INTO routes (key, meters, provider, created_at) "
            "VALUES (?, ?, ?, ?)",
            (key, -999.0, "evil", "2000-01-01 00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    with patch("nedviga.graph.load_graph", side_effect=Exception("no graph")), \
         patch("nedviga.net_guard.guarded_get", side_effect=Exception("no net")):
        result = walk_route(lat, lon, station)

    assert result.get("route_verified") is not True


def test_s1f4_routing_cache_expired_ttl_not_verified(tmp_path, monkeypatch):
    import nedviga.routing_cache as rc
    from nedviga.geo_routing import walk_route

    lat, lon, station = 55.8200, 37.6410, "ВДНХ"
    db = rc._DEFAULT
    conn = rc._connect(db)
    try:
        key = rc.cache_key(lat, lon, station)
        conn.execute(
            "INSERT OR REPLACE INTO routes (key, meters, provider, created_at) "
            "VALUES (?, ?, ?, ?)",
            (key, 1000.0, "cache", "2000-01-01 00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    with patch("nedviga.graph.load_graph", side_effect=Exception("no graph")), \
         patch("nedviga.net_guard.guarded_get", side_effect=Exception("no net")):
        result = walk_route(lat, lon, station)

    assert result.get("route_verified") is not True


def test_s1f6_mosdata_token_not_in_url(tmp_path, monkeypatch):
    import nedviga.net_guard as ng
    import nedviga.mosdata as md
    from unittest.mock import MagicMock

    tok = tmp_path / "token.txt"
    tok.write_text("SECRET-TOKEN-VALUE")
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("NEDVIGA_MOS_TOKEN_FILE", str(tok))

    captured = {}

    def fake_guarded_get(url, timeout=30.0, headers=None):
        captured["url"] = url
        captured["headers"] = headers or {}
        r = MagicMock()
        r.json.return_value = {"datasets": []}
        r.raise_for_status.return_value = None
        return r

    monkeypatch.setattr(ng, "guarded_get", fake_guarded_get)

    md.search_datasets("query")

    assert "SECRET-TOKEN-VALUE" not in captured.get("url", "")


def test_s1f6_mosdata_odata_filter_escaped(tmp_path, monkeypatch):
    import urllib.parse
    import nedviga.net_guard as ng
    import nedviga.mosdata as md
    from unittest.mock import MagicMock

    tok = tmp_path / "token.txt"
    tok.write_text("t")
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("NEDVIGA_MOS_TOKEN_FILE", str(tok))

    captured = {}

    def fake_guarded_get(url, timeout=30.0, headers=None):
        captured["url"] = url
        r = MagicMock()
        r.json.return_value = {"datasets": []}
        r.raise_for_status.return_value = None
        return r

    monkeypatch.setattr(ng, "guarded_get", fake_guarded_get)

    md.search_datasets("x' or 1=1")

    url = captured.get("url", "")
    decoded = urllib.parse.unquote_plus(url)
    # single quote must be escaped (doubled) to neutralize injection
    assert "x''" in decoded