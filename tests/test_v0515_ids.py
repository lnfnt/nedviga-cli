"""v0.5.15: стабильные id карточек — watch не врёт при перестановке выдачи."""
from __future__ import annotations

import json
import random
from pathlib import Path

from nedviga.cli import main
from nedviga.sources_avito import parse_livetext
from nedviga.sources_domclick import parse_domclick_text

AV = Path(__file__).parent / "fixtures" / "avito_search_livetext_2026-10.txt"
DC = Path(__file__).parent / "fixtures" / "domclick_search_livetext_2026-10.txt"


def test_avito_ids_deterministic():
    a = {c["id"] for c in parse_livetext(AV.read_text())}
    b = {c["id"] for c in parse_livetext(AV.read_text())}
    assert a == b and len(a) >= 20


def test_avito_lot_preferred():
    cards = parse_livetext(AV.read_text())
    lots = [c for c in cards if "вт-" in c["id"]]
    assert lots, "lot-id card expected (Номер лота в выдаче)"
    assert lots[0]["id"].startswith("avito-вт-")


def test_domclick_ids_stable():
    a = {c["id"] for c in parse_domclick_text(DC.read_text())}
    b = {c["id"] for c in parse_domclick_text(DC.read_text())}
    assert a == b and len(a) >= 10


def test_watch_no_false_diff_on_shuffle(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    cards = parse_livetext(AV.read_text())[:12]
    f1 = tmp_path / "a.json"
    f1.write_text(json.dumps(cards, ensure_ascii=False))
    main(["watch", "add", "--file", str(f1)])
    add_out = json.loads(capsys.readouterr().out)
    assert len(add_out["data"]["added"]) == 12  # регистрация реальна — тест не вакуумный
    shuffled = cards[:]
    random.Random(42).shuffle(shuffled)
    f2 = tmp_path / "b.json"
    f2.write_text(json.dumps(shuffled, ensure_ascii=False))
    main(["watch", "check", "--offline", str(f2)])
    chk = json.loads(capsys.readouterr().out)
    assert isinstance(chk["data"], list) and chk["data"] == [], str(chk["data"])[:300]


def test_watch_detects_real_removal(tmp_path, monkeypatch, capsys):
    """Контроль отрицания: удаление карточки из выдачи ОБЯЗАНО детектиться."""
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    cards = parse_livetext(AV.read_text())[:12]
    f1 = tmp_path / "a.json"
    f1.write_text(json.dumps(cards, ensure_ascii=False))
    main(["watch", "add", "--file", str(f1)])
    capsys.readouterr()
    f2 = tmp_path / "b.json"
    f2.write_text(json.dumps(cards[1:], ensure_ascii=False))
    main(["watch", "check", "--offline", str(f2)])
    chk = json.loads(capsys.readouterr().out)
    changes = json.dumps(chk["data"], ensure_ascii=False)
    assert cards[0]["id"] in changes, "removed card must surface"
