# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 lnfnt <lnfnt@proton.me>

"""v13b PHASE T (RED): MEDIUM S2-F10..S2-F13, S3-F4, S3-F5 (аудит unified-audit-2026-10-30).

Только тесты. RED = «ожидаемое поведение после фикса».
Изоляция: env через monkeypatch, файлы в tmp_path, сеть не трогаем (моки/подпроцесс без сети).
"""
from __future__ import annotations

import json
import os
import stat
import sys
import subprocess
from pathlib import Path

import pytest

from nedviga import pipeline
from nedviga.cli import main


def _card(cid, addr="addr", area=50.0, rooms=2, floor=5, floors=10,
          photo="p.jpg", lat=55.6, lon=37.6, price=10_000_000.0):
    return {
        "id": cid, "source": "cian", "url": f"u{cid}", "title": f"flat {cid}",
        "pricing": {"price_total_rub": price, "price_per_m2_rub": price / area},
        "parameters": {"rooms": rooms, "area_total_m2": area, "floor": floor, "floors_total": floors},
        "building": {"address_raw": addr},
        "geo": {"lat": lat, "lon": lon, "district": "d"},
        "images": [{"url": f"https://cdn/{photo}"}],
    }


def _no_group_other(path: Path) -> bool:
    mode = stat.S_IMODE(path.stat().st_mode)
    return (mode & 0o077) == 0


# ---------------------------------------------------------------------------
# S2-F10 — молчаливый fallback raw[0]: чужие title/price в pipeline,
# чужой чек-лист. Неопределённость честная: нет карты в файле — нет снапшота.
# ---------------------------------------------------------------------------

class TestS2F10NoSilentRaw0:
    def _file_two_cards(self, tmp_path: Path) -> Path:
        f = tmp_path / "cards.json"
        f.write_text(json.dumps({
            "cards": [
                _card("owned", price=111.0, addr="улица Идейная 1"),
                _card("other", price=999.0, addr="другая площадь 2"),
            ]
        }), encoding="utf-8")
        return f

    def test_pipeline_no_foreign_snapshot(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
        f = self._file_two_cards(tmp_path)
        res = pipeline.set_status("absent", "new", from_file=str(f))
        assert res["ok"] is True
        assert res.get("warning"), "честная неопределённость: снапшота нет — должно быть помечено"
        item = pipeline.list_items()[0]
        assert item["title"] is None, "чужой title из raw[0] попал в pipeline"
        assert item["price_snapshot"] is None, "чужая цена из raw[0] попала в pipeline"

    def test_pipeline_real_match_still_snapshots(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
        f = self._file_two_cards(tmp_path)
        res = pipeline.set_status("owned", "new", from_file=str(f))
        assert res["ok"] is True
        item = pipeline.list_items()[0]
        assert item["title"] == "flat owned"
        assert item["price_snapshot"] == 111.0

    def test_checklist_wrong_card_raises_not_foreign_triage(self, tmp_path):
        from nedviga.checklist import new_checklist
        f = self._file_two_cards(tmp_path)
        with pytest.raises(ValueError):
            new_checklist("wrong", str(f))

    def test_handoff_unknown_card_fails_without_external_call(self, tmp_path, monkeypatch):
        from nedviga.checklist import handoff

        f = self._file_two_cards(tmp_path)
        monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
        monkeypatch.setenv("A2A_BIN", "definitely-not-a-real-binary")
        res = handoff("wrong", "the owner", file=str(f))
        assert res["ok"] is False
        assert "card" in res.get("reason", ""), res
        assert not (tmp_path / "drafts" / "wrong.md").exists(), \
            "рукописный чек-лист по несуществующей карте + внешняя отправка"


# ---------------------------------------------------------------------------
# S2-F11 — dedup: соседние этажи не склеиваются; strict не no-op;
# projects.refresh реально удаляет устаревшее.
# ---------------------------------------------------------------------------

class TestS2F11DedupFloorsStrict:
    def test_adjacent_floors_not_grouped(self):
        from nedviga.dedup import dedup_cards
        cards = [_card("a", floor=5), _card("b", floor=6)]
        grp = dedup_cards(cards)
        ids = [set(g["cards"]) for g in grp]
        assert not any({"a", "b"} <= s for s in ids), \
            "этаж 5 и 6 одного дома склеены как дубль"

    def test_strict_demotes_weak_pairs(self):
        from nedviga.dedup import dedup_cards
        # geo/адрес + планировка совпали, фото разное — слабая пара:
        # в норм-режиме показываем кандидата, strict её демо-няет
        weak = [_card("a", floor=5, photo="p1.jpg"),
                _card("b", floor=5, photo="p2.jpg")]
        normal = [set(g["cards"]) for g in dedup_cards(weak)]
        strict = [set(g["cards"]) for g in dedup_cards(weak, strict=True)]
        assert strict == [] or not any({"a", "b"} <= s for s in strict), \
            "strict=True — no-op: слабая пара переживает strict"
        assert any({"a", "b"} <= s for s in normal), "норм-режим обязан показывать слабую пару"

    def test_strict_keeps_strong_pairs(self):
        from nedviga.dedup import dedup_cards
        strong = [_card("a", floor=5, photo="same.jpg"),
                  _card("b", floor=5, photo="same.jpg")]
        strict = [set(g["cards"]) for g in dedup_cards(strong, strict=True)]
        assert any({"a", "b"} <= s for s in strict), "обязательный дубль потерян в strict"


class TestS2F11ProjectsRefreshRemoves:
    def test_refresh_deletes_stale_ids(self, tmp_path, monkeypatch):
        from nedviga import projects
        monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
        projects.project_add("p1", "a")
        projects.project_add("p1", "b")
        f = tmp_path / "search.json"
        f.write_text(json.dumps({"cards": [{"id": "a"}, {"id": "c"}]}), encoding="utf-8")
        res = projects.project_refresh("p1", str(f))
        assert sorted(res["removed"]) == ["b"]
        assert sorted(projects.project_cards("p1")) == ["a", "c"], \
            "отчёт removed врёт: 'b' остался в project_cards"


# ---------------------------------------------------------------------------
# S2-F12 — файлы с ПДн 0600; doctor проверяет права.
# ---------------------------------------------------------------------------

class TestS2F12PIIMode0600:
    def test_pipeline_db_mode(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
        pipeline.set_status("c1", "new", note="звоните +7 916 123-45-67")
        assert _no_group_other(tmp_path / "pipeline.sqlite")

    def test_audit_log_mode(self, tmp_path, monkeypatch):
        from nedviga import auditlog
        monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
        auditlog.log_action(role="agent", command="get-card", card_id="c1")
        logs = list(tmp_path.glob("audit-*.log.jsonl"))
        assert logs and all(_no_group_other(p) for p in logs)

    def test_draft_with_address_mode(self, tmp_path, monkeypatch):
        from nedviga.checklist import handoff
        monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
        monkeypatch.setenv("A2A_BIN", "definitely-not-a-real-binary")
        f = tmp_path / "cards.json"
        f.write_text(json.dumps({"cards": [_card("c1", addr="улица Идейная 1")]}),
                     encoding="utf-8")
        handoff("c1", "the owner", file=str(f))
        draft = tmp_path / "drafts" / "c1.md"
        assert draft.exists()
        assert _no_group_other(draft)


class TestS2F12DoctorChecksPermissions:
    def _doctor_data(self, tmp_path, monkeypatch):
        from nedviga import doctor as doctor_mod
        monkeypatch.setattr(doctor_mod, "CACHE_DIR", tmp_path / "cache")
        monkeypatch.setattr(doctor_mod, "_check_cache", lambda: (True, str(tmp_path / "cache")))
        envelope, code = doctor_mod.run_doctor()
        return envelope.data, code

    def _perm_block(self, data: dict):
        for k in data:
            if "permission" in k:
                return data[k]
        return None

    def test_doctor_reports_wide_permissions(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
        f = tmp_path / "pipeline.sqlite"
        f.write_bytes(b"x")
        f.chmod(0o644)
        data, code = self._doctor_data(tmp_path, monkeypatch)
        perm = self._perm_block(data)
        assert perm is not None, "doctor не проверяет права на state-файлы"
        assert "pipeline.sqlite" in json.dumps(perm, ensure_ascii=False), \
            "0644-файл с ПДн не помечен doctor'ом"

    def test_doctor_no_false_positive_on_0600(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
        f = tmp_path / "pipeline.sqlite"
        f.write_bytes(b"x")
        f.chmod(0o600)
        data, code = self._doctor_data(tmp_path, monkeypatch)
        perm = self._perm_block(data)
        if perm is None:
            pytest.fail("doctor не проверяет права на state-файлы")
        assert "pipeline.sqlite" not in json.dumps(perm, ensure_ascii=False)


# ---------------------------------------------------------------------------
# S2-F13 — бизнес-логика: digest inactive≠sold; market days не мёртв;
# ops precheck честный (non-live не заявляет ok).
# ---------------------------------------------------------------------------

class TestS2F13DigestInactiveNotSold:
    def test_inactive_not_in_removed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
        conn = pipeline._connect()
        for cid, st in (("w1", "inactive"), ("w2", "sold")):
            conn.execute("INSERT INTO watch_history (card_id, price, status, at) VALUES (?,?,?,?)",
                         (cid, 100.0, st, "2026-10-30T00:00:00+00:00"))
        conn.commit()
        conn.close()
        from nedviga.digest import build_digest
        d = build_digest(days=7)
        removed = {e["card_id"] for e in d["removed"]}
        assert "w1" not in removed, "inactive показан как «снято/продано»"
        assert "w2" in removed, "sold потерялось"


class TestS2F13MarketDaysHonest:
    def _corpus(self, n=25):
        return [_card(f"m{i}", price=10_000_000 + i * 100_000, area=50.0 + i,
                      rooms=2 if i % 2 == 0 else 3) for i in range(n)]

    def test_market_reports_days(self, tmp_path):
        from nedviga.market import analyze
        f = tmp_path / "corpus.json"
        f.write_text(json.dumps(self._corpus()), encoding="utf-8")
        res = analyze([str(f)], days=3)
        assert res.get("days") == 3, "days в ответе отсутствует — параметр мёртв"

    def test_market_days_disclosed_when_not_applied(self, tmp_path):
        from nedviga.market import analyze
        f = tmp_path / "corpus.json"
        f.write_text(json.dumps(self._corpus()), encoding="utf-8")
        res = analyze([str(f)], days=3)
        applied = res.get("days_applied", True) is True and "фильтр" in json.dumps(res)
        disclosed = res.get("days_applied") is False
        assert applied or disclosed, \
            f"days=3 проглочен молча: {json.dumps(res, ensure_ascii=False)[:200]}"


class TestS2F13OpsPrecheckHonest:
    def test_non_live_precheck_not_ok(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
        from nedviga.ops import collect
        res = collect(days=1, precheck=True, live=False)
        assert res["precheck"], "precheck пуст"
        bad = [p for p in res["precheck"] if p["status"] == "ok"]
        assert not bad, f"non-live precheck без пинга заявляет ok: {bad}"


# ---------------------------------------------------------------------------
# S3-F4 — check_update/run_update валидируют source (bogus → UpdaterError).
# ---------------------------------------------------------------------------

class TestS3F4CheckUpdateValidatesSource:
    def test_bogus_source_raises(self):
        from nedviga.updater import check_update, UpdaterError
        with pytest.raises(UpdaterError):
            check_update(source="not-a-source")

    def test_run_update_bogus_source_raises(self):
        from nedviga.updater import run_update, UpdaterError
        with pytest.raises(UpdaterError):
            run_update(source="not-a-source")


# ---------------------------------------------------------------------------
# S3-F5 — MCP читает NEDVIGA_ROLE, аудит под реальной ролью,
# client-подмена role в аргументах не проходит и не замывает аудит.
# ---------------------------------------------------------------------------

def _mcp(requests, tmp_path, extra_env=None):
    env = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).parent.parent),
        "NEDVIGA_STATE_DIR": str(tmp_path),
        "NEDVIGA_WRITE_OK": "1",
    }
    env.pop("NEDVIGA_ROLE", None)
    env.update(extra_env or {})
    proc = subprocess.run(
        [sys.executable, "-m", "nedviga", "mcp", "serve"],
        input="".join(json.dumps(r) + "\n" for r in requests),
        capture_output=True, text=True, env=env,
        cwd=str(Path(__file__).parent.parent),
    )
    outs = [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]
    return proc, outs


def _write_roles(tmp_path: Path) -> Path:
    roles = tmp_path / "roles.json"
    roles.write_text(json.dumps([{"role": "family", "name": "Family"}]), encoding="utf-8")
    return roles


class TestS3F5McpRoleFromEnv:
    def test_write_denied_for_family_env(self, tmp_path):
        roles = _write_roles(tmp_path)
        proc, outs = _mcp(
            [{"jsonrpc": "2.0", "id": 2, "method": "tools/call",
              "params": {"name": "pipeline_set", "arguments": {"card_id": "x", "status": "new",
                                                               "note": "n"}}}],
            tmp_path,
            extra_env={"NEDVIGA_ROLE": "family", "NEDVIGA_ROLES_FILE": str(roles)},
        )
        call = [o for o in outs if o.get("id") == 2][0]
        assert call["result"]["isError"] is True, call
        text = json.dumps(call["result"], ensure_ascii=False)
        assert "forbidden" in text or "denied" in text or "not allowed" in text, call

    def test_bogus_env_role_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
        monkeypatch.setenv("NEDVIGA_ROLE", "ghost-role")
        monkeypatch.delenv("NEDVIGA_ROLES_FILE", raising=False)
        from nedviga.mcp_server import handle_request
        resp = handle_request({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "digest", "arguments": {}},
        })
        assert resp["result"]["isError"] is True, resp

    def _audit_entries(self, tmp_path: Path) -> list[dict]:
        out = []
        for p in sorted(tmp_path.glob("audit-*.log.jsonl")):
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    out.append(json.loads(line))
        return out

    def test_audit_recorded_under_real_env_role(self, tmp_path):
        roles = _write_roles(tmp_path)
        proc, outs = _mcp(
            [{"jsonrpc": "2.0", "id": 2, "method": "tools/call",
              "params": {"name": "digest", "arguments": {}}}],
            tmp_path,
            extra_env={"NEDVIGA_ROLE": "family", "NEDVIGA_ROLES_FILE": str(roles)},
        )
        call = [o for o in outs if o.get("id") == 2][0]
        assert call["result"]["isError"] is False, call
        entries = self._audit_entries(tmp_path)
        assert any(e.get("command") == "mcp:digest" and e.get("role") == "family"
                   for e in entries), entries

    def test_client_role_argument_cannot_wash_audit(self, tmp_path):
        tool_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": "digest",
                               "arguments": {"role": "stealing-role"}}}
        proc, outs = _mcp([tool_req], tmp_path, extra_env={})
        call = [o for o in outs if o.get("id") == 2][0]
        assert call["result"]["isError"] is False, call
        entries = self._audit_entries(tmp_path)
        mcp_entries = [e for e in entries if e.get("command") == "mcp:digest"]
        assert mcp_entries, entries
        assert all(e.get("role") != "stealing-role" for e in mcp_entries), entries
        assert any(e.get("role") == "agent" for e in mcp_entries), entries

    def test_prepare_args_role_not_overridable(self, monkeypatch):
        from nedviga.mcp_server import _prepare_args
        monkeypatch.setenv("NEDVIGA_ROLE", "family")
        ns = _prepare_args("digest", {"role": "auditor"})
        assert ns.role == "family", "client-args перебивают env-роль"
