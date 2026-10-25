"""v0.5.3 (the task brief) relax tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from nedviga.cli import main


def test_relax_deep_equal(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))

    def fake_search(**kwargs):
        return []

    with patch("nedviga.cli.search", side_effect=fake_search):
        code1 = main(["search", "--source", "cian", "--suggest-relax"])
        out1 = capsys.readouterr().out
    with patch("nedviga.cli.search", side_effect=fake_search):
        code2 = main(["search", "--source", "cian"])
        out2 = capsys.readouterr().out
    # without hints field, outputs structurally same except hints
    import json as _j
    d1 = _j.loads(out1)
    d2 = _j.loads(out2)
    # hints stored in metadata, not data
    m1 = d1.get("metadata", {})
    m2 = d2.get("metadata", {})
    m1.pop("hints", None)
    m2.pop("hints", None)
    assert d1.get("data") == d2.get("data")
