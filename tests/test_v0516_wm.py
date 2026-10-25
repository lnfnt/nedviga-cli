"""v0.1.0: флаги представления выходной поверхности + build_flag + §13."""
from __future__ import annotations

import json
from pathlib import Path

from nedviga.cli import main
from nedviga import _wm


def test_variant_deterministic_same_seed(tmp_path, monkeypatch):
    monkeypatch.setenv("NEDVIGA_BUILD_SEED", "client-X")
    v1 = [_wm.variant(k, "0.1.0") for k in _wm.STYLE_VARIANTS]
    v2 = [_wm.variant(k, "0.1.0") for k in _wm.STYLE_VARIANTS]
    assert v1 == v2


def test_variant_differs_across_seeds(monkeypatch):
    monkeypatch.setenv("NEDVIGA_BUILD_SEED", "client-X")
    a = [_wm.variant(k, "0.1.0") for k in _wm.STYLE_VARIANTS]
    monkeypatch.setenv("NEDVIGA_BUILD_SEED", "client-Z")
    b = [_wm.variant(k, "0.1.0") for k in _wm.STYLE_VARIANTS]
    assert a != b, "different seeds must select different vectors"


def test_semantic_invariants_rush_line(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("NEDVIGA_BUILD_SEED", "client-Y")
    monkeypatch.setenv("NEDVIGA_EGRESS_PROXY", "http://mock:1")  # путь трафика активен, fetch замокан
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"id": "x", "source": "cian", "url": "u", "title": "t",
                             "geo": {"lat": 55.7, "lon": 37.6}}))
    # с моком трафика — чтобы все варианты содержали «баллов» и число
    from unittest.mock import patch
    for seed in ("client-Y", "client-W", "public"):
        monkeypatch.setenv("NEDVIGA_BUILD_SEED", seed)
        with patch("nedviga.rush._fetch_traffic", return_value="Пробки 7 баллов"):
            main(["rush", "--file", str(f)])
        d = json.loads(capsys.readouterr().out)
        txt = d["data"]["text"]
        assert "7" in txt and "баллов" in txt.lower(), (seed, txt[:200])


def test_build_flags_require_secret(monkeypatch):
    monkeypatch.delenv("NEDVIGA_BUILD_SECRET", raising=False)
    assert _wm.build_flags("0.1.0") == []
    monkeypatch.setenv("NEDVIGA_BUILD_SECRET", "test-secret")
    c1 = _wm.build_flags("0.1.0")
    c2 = _wm.build_flags("0.1.0")
    assert len(c1) == 3 and c1 == c2 and all(len(x) == 16 for x in c1)
    assert c1 != _wm.build_flags("0.1.1")


def test_source_command_and_banner(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    code = main(["source"])
    d = json.loads(capsys.readouterr().out)
    assert code == 0 and d["data"]["license"] == "AGPL-3.0-only"
    assert "agpl_section_13" in d["data"]
    # banner в метаданных ЛЮБОЙ команды (пассивный §13):
    main(["compare", "--file", str(tmp_path / "none.json")])
    capsys.readouterr()
    f = tmp_path / "c.json"
    f.write_text(json.dumps([{"id": "x", "source": "cian", "url": "u", "title": "t"}]))
    main(["compare", "--file", str(f)])
    env = json.loads(capsys.readouterr().out)
    assert env["metadata"].get("license") == "AGPL-3.0-only"


def test_source_url_env(monkeypatch):
    monkeypatch.setenv("NEDVIGA_SOURCE_URL", "https://example.test/nedviga")
    info = _wm.source_info("0.1.0")
    assert info["source_url"].startswith("https://") and "git clone" in info["how_to_obtain"]


def test_digest_variant_renders(tmp_path, monkeypatch):
    monkeypatch.setenv("NEDVIGA_BUILD_SEED", "client-D")
    from nedviga.digest import render
    d = {"days": 7, "moves": [], "new_shortlist": [], "reductions": [], "removed": []}
    txt = render(d, "md")
    assert "7" in txt  # дни обязательны во всех вариантах заголовка
