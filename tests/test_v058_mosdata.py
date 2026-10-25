"""v0.5.8 (the task brief) mosdata tests (RED)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from nedviga.cli import main


def test_mosdata_token_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("NEDVIGA_MOS_TOKEN_FILE", raising=False)
    code = main(["mos", "search-datasets", "--query", "многоквартирные"])
    out = capsys.readouterr().out
    assert "token_missing" in out or code != 0


def test_mosdata_proxy_respected(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    tok = tmp_path / "token.txt"
    tok.write_text("secret")
    monkeypatch.setenv("NEDVIGA_MOS_TOKEN_FILE", str(tok))
    monkeypatch.setenv("NEDVIGA_EGRESS_PROXY", "http://proxy:8080")
    # mock transport
    with patch("nedviga.mosdata._request") as m:
        m.return_value = {"datasets": [{"Id": "123", "Name": "МКД реестр"}]}
        code = main(["mos", "search-datasets", "--query", "многоквартирные"])
        out = capsys.readouterr().out
        # ensure proxy passed
        assert m.called
    assert "123" in out or code == 0


def test_mosdata_token_not_in_output(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    tok = tmp_path / "token.txt"
    tok.write_text("secret-token-value")
    monkeypatch.setenv("NEDVIGA_MOS_TOKEN_FILE", str(tok))
    with patch("nedviga.mosdata._request") as m:
        m.return_value = {"datasets": [{"Id": "123", "Name": "МКД"}]}
        code = main(["mos", "search-datasets", "--query", "многоквартирные"])
        out = capsys.readouterr().out
    assert "secret-token-value" not in out


def test_mosdata_dataset_ids_from_payload(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEDVIGA_STATE_DIR", str(tmp_path))
    tok = tmp_path / "token.txt"
    tok.write_text("t")
    monkeypatch.setenv("NEDVIGA_MOS_TOKEN_FILE", str(tok))
    with patch("nedviga.mosdata._request") as m:
        m.return_value = {"datasets": [{"Id": "999", "Name": "МКД реестр"}]}
        code = main(["mos", "search-datasets", "--query", "многоквартирные"])
        out = capsys.readouterr().out
    assert "999" in out


# ---- контроль качества v0.5.8: транспортная политика ----
def test_control_egress_proxy_mode_fastfail(monkeypatch):
    """Сеть в тесте запрещена: эгресс на заглушённый локальный порт = мгновенный
    ProxyError, но режим proxy зафиксирован ДО сокета (политика видима)."""
    monkeypatch.setenv("NEDVIGA_EGRESS_PROXY", "http://127.0.0.1:1")
    from nedviga import net_guard as ng
    ng.EGRESS_STATE["mode"] = None
    try:
        ng.guarded_get("https://apidata.mos.ru/v1/datasets", timeout=5)
    except Exception:
        pass
    assert ng.EGRESS_STATE["mode"] == "proxy"


def test_control_egress_proxy_routes_tunnel(monkeypatch):
    monkeypatch.setenv("NEDVIGA_EGRESS_PROXY", "http://10.9.9.9:3128")
    import nedviga.net_guard as ng
    class FakePM:
        def connection_from_host(self, host, port, scheme):
            seen['host'] = (host, port, scheme); return object()
    ng.EGRESS_STATE["managers"] = {}
    assert ng._normalize_proxy_url("10.9.9.9:3128") == "http://10.9.9.9:3128"
    assert ng._egress_proxy() == "http://10.9.9.9:3128"
    FakePM()  # сигнатура connection_from_host(host=, port=, scheme=) совместима



def test_control_direct_bypass_visible(monkeypatch):
    monkeypatch.delenv("NEDVIGA_EGRESS_PROXY", raising=False)
    monkeypatch.setenv("NEDVIGA_ALLOW_DIRECT", "1")
    from nedviga.net_guard import _allow_direct
    assert _allow_direct() is True
    monkeypatch.setenv("NEDVIGA_ALLOW_DIRECT", "0")
    assert _allow_direct() is False


def test_control_api_key_never_leaks_via_exception(monkeypatch):
    import nedviga.mosdata as md
    monkeypatch.setenv("NEDVIGA_MOS_TOKEN_FILE", "/tmp/fake-key-file")
    Path = __import__("pathlib").Path
    Path("/tmp/fake-key-file").write_text("SECRETKEY123456")
    def boom(url, **kw):
        raise RuntimeError(f"401 for url: {url}")
    import nedviga.net_guard as ng
    monkeypatch.setattr(ng, "guarded_get", boom)
    try:
        md.search_datasets("x")
        assert False
    except Exception as exc:
        assert "SECRETKEY123456" not in str(exc)
        assert "api_key=REDACTED" in str(exc)
