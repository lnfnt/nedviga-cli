"""v0.5.4 (the task brief) textsearch tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nedviga.cli import main


def test_text_index_and_query(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "cards.json"
    f.write_text(json.dumps([{"id": "cian-1", "source": "cian", "url": "u", "title": "flat", "description_text": "узакон перепланировка"}]))
    code = main(["text", "index", "--file", str(f)])
    capsys.readouterr()
    assert code == 0
    code = main(["text", "query", "узакон*"])
    out = capsys.readouterr().out
    assert code == 0
    assert "cian-1" in out


def test_text_idempotent(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "cards.json"
    f.write_text(json.dumps([{"id": "cian-1", "source": "cian", "url": "u", "title": "flat", "description_text": "hello"}]))
    main(["text", "index", "--file", str(f)])
    capsys.readouterr()
    main(["text", "index", "--file", str(f)])
    capsys.readouterr()
    code = main(["text", "query", "hello"])
    out = capsys.readouterr().out
    assert code == 0


def test_text_fts5_absent_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    # mock sqlite3.connect to raise OperationalError on FTS5
    import sqlite3
    orig = sqlite3.connect
    def fake_connect(*a, **k):
        conn = orig(*a, **k)
        orig_exec = conn.execute
        def patched(sql, *args, **kwargs):
            if "fts5" in str(sql).lower():
                raise sqlite3.OperationalError("no such module: fts5")
            return orig_exec(sql, *args, **kwargs)
        conn.execute = patched
        return conn
    monkeypatch.setattr("sqlite3.connect", fake_connect)
    f = tmp_path / "cards.json"
    f.write_text(json.dumps([{"id": "cian-1", "source": "cian", "url": "u", "title": "flat", "description_text": "hello"}]))
    code = main(["text", "index", "--file", str(f)])
    out = capsys.readouterr().out
    assert code != 0 or "error" in out.lower() or "fts" in out.lower()


def test_control_russian_morphology_substring():
    """v0.5.4 контроль качества: морфология. «узакон*» обязан ловить «узаконим»,
    «доверенност» — обе падежные формы. FTS5-unicode61 этого не делал."""
    import json, pathlib
    from nedviga.models import ListingCard
    from nedviga import textsearch
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        db = pathlib.Path(td) / "t.db"
        cards = [ListingCard.model_validate({
            "id": "cian-5", "source": "cian", "url": "https://cian.ru/5",
            "title": "продажа по доверенности", "pricing": {"price_total_rub": 6000000},
            "description_text": "узаконим перепланировку"})]
        f = pathlib.Path(td) / "c.json"
        f.write_text(json.dumps([c.model_dump(mode="json") for c in cards]))
        textsearch.index_file(str(f), db=db)
        assert [r["card_id"] for r in textsearch.query("узакон*", db=db)] == ["cian-5"]
        assert [r["card_id"] for r in textsearch.query("доверенност", db=db)] == ["cian-5"]
        assert textsearch.query("абрака*", db=db) == []
