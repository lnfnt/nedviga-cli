"""v0.5.10 (the task brief) developer tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from nedviga.cli import main


def test_developer_inn_exact(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    tok = tmp_path / "token.txt"
    tok.write_text("t")
    monkeypatch.setenv("NEDVIGA_MOS_TOKEN_FILE", str(tok))
    with patch("nedviga.developer._request") as m:
        m.return_value = {"value": [{"FullName": "ООО Тест", "INN": "1234567890"}]}
        code = main(["developer", "--inn", "1234567890"])
        out = capsys.readouterr().out
    assert code == 0
    assert "1234567890" in out


def test_developer_name_case_variants(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    tok = tmp_path / "token.txt"
    tok.write_text("t")
    monkeypatch.setenv("NEDVIGA_MOS_TOKEN_FILE", str(tok))
    with patch("nedviga.developer._request") as m:
        m.return_value = {"value": [{"FullName": "ООО Тест", "INN": "1234567890"}]}
        code = main(["developer", "--name", "тест"])
        out = capsys.readouterr().out
    # multiple requests for case variants
    assert m.call_count >= 2


def test_developer_from_file_inn_extraction(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    f = tmp_path / "card.json"
    f.write_text(json.dumps({"id": "cian-1", "source": "cian", "url": "u", "title": "flat",
                            "description_text": "ИНН 1234567890 застройщик: ООО Тест, телефон +7 (999) 000-11-22"}))
    code = main(["developer", "--from-file", str(f)])
    out = capsys.readouterr().out
    assert "1234567890" in out
    # 11-digit not extracted
    f2 = tmp_path / "card2.json"
    f2.write_text(json.dumps({"id": "cian-2", "source": "cian", "url": "u", "title": "flat",
                              "description_text": "ИНН 12345678901"}))
    code = main(["developer", "--from-file", str(f2)])
    out = capsys.readouterr().out
    assert "12345678901" not in out


def test_developer_litcheck_unavailable(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    tok = tmp_path / "token.txt"
    tok.write_text("t")
    monkeypatch.setenv("NEDVIGA_MOS_TOKEN_FILE", str(tok))
    monkeypatch.setenv("SUD_BIN", str(tmp_path / "nope"))
    with patch("nedviga.developer._request") as m:
        m.return_value = {"value": [{"FullName": "ООО Тест", "INN": "1234567890"}]}
        code = main(["developer", "--name", "тест", "--litcheck"])
        out = capsys.readouterr().out
    assert "unavailable" in out


def test_developer_cache_hit(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    tok = tmp_path / "token.txt"
    tok.write_text("t")
    monkeypatch.setenv("NEDVIGA_MOS_TOKEN_FILE", str(tok))
    with patch("nedviga.developer._request") as m:
        m.return_value = {"value": [{"FullName": "ООО Тест", "INN": "1234567890"}]}
        main(["developer", "--inn", "1234567890"])
        capsys.readouterr()
        main(["developer", "--inn", "1234567890"])
        out = capsys.readouterr().out
        # second should be cache hit: request called once
        assert m.call_count == 1


def test_control_real_row_shape_with_cells(tmp_path, monkeypatch):
    """v0.5.10 контроль: боевая форма apidata v1 rows = [{Number, Cells:{...}}];
    рендер обязан читать Cells, а не верхний уровень (живой баг: пустая строка)."""
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    from nedviga import developer as dv
    row = {"global_id": 1, "Number": 1, "Cells": {
        "INN": "770000111111", "ShortName": "ООО ТестДом", "FullName": "Полное ООО ТестДом",
        "LinkToProjectDeclaration": "https://example/decl", "PermitNum": "77-х-2024",
        "CooperationWithBanks": "Сбер"}}
    def fake(method, path, params=None):
        return [row]
    monkeypatch.setattr(dv, "_request", fake)
    r = dv.search_by_inn("770000111111")
    txt = dv.render_text(r)
    assert "ООО ТестДом" in txt and "770000111111" in txt
    assert "декларация:" in txt and "разрешение: 77-х-2024" in txt
