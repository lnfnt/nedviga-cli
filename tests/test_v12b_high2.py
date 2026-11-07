# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 lnfnt <lnfnt@proton.me>

"""RED tests for v12b HIGH findings S2-F5, S2-F6."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from nedviga.export_html import _card_html
from nedviga.models import ListingCard
from nedviga.pii import PHONE_MASK


def test_s2f5_pipeline_note_phone_masked_in_db(tmp_path, monkeypatch):
    from nedviga import pipeline

    db = tmp_path / "pipeline.sqlite"
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    pipeline.set_status("cian-1", "candidate", note="call +7 (999) 000-11-22", db=db)

    conn = sqlite3.connect(str(db))
    try:
        item_notes = [r[0] for r in conn.execute("SELECT note FROM pipeline_items").fetchall()]
        hist_notes = [r[0] for r in conn.execute("SELECT note FROM status_history").fetchall()]
    finally:
        conn.close()

    for note in item_notes + hist_notes:
        assert "+7 (999) 000-11-22" not in (note or "")
        assert PHONE_MASK in (note or "")


def test_s2f5_pipeline_note_masked_on_transition(tmp_path, monkeypatch):
    from nedviga import pipeline

    db = tmp_path / "pipeline.sqlite"
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    pipeline.set_status("cian-1", "candidate", note="first +7 (999) 000-11-22", db=db)
    pipeline.set_status("cian-1", "shortlist", note="second +79161234567", db=db)

    conn = sqlite3.connect(str(db))
    try:
        hist_notes = [r[0] for r in conn.execute("SELECT note FROM status_history").fetchall()]
    finally:
        conn.close()

    for note in hist_notes:
        assert "+7 (999) 000-11-22" not in (note or "")
        assert "+79161234567" not in (note or "")
        assert PHONE_MASK in (note or "")


def test_s2f6_card_url_javascript_not_in_href():
    card = ListingCard(id="c", source="cian", url="javascript:alert(1)", title="t")
    html = _card_html(card, embed=False, idx=0)
    assert 'href="javascript:alert(1)"' not in html


def test_s2f6_card_url_data_text_html_not_in_href():
    card = ListingCard(id="c", source="cian", url="data:text/html,<script>alert(1)</script>", title="t")
    html = _card_html(card, embed=False, idx=0)
    assert 'href="data:text/html' not in html


def test_s2f6_card_url_https_passes_in_href():
    card = ListingCard(id="c", source="cian", url="https://example.com/flat/1", title="t")
    html = _card_html(card, embed=False, idx=0)
    assert 'href="https://example.com/flat/1"' in html


def test_s2f6_card_url_http_passes_in_href():
    card = ListingCard(id="c", source="cian", url="http://example.com/flat/2", title="t")
    html = _card_html(card, embed=False, idx=0)
    assert 'href="http://example.com/flat/2"' in html
