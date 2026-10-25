"""v0.5.7 (the task brief) MCP tests (RED)."""
from __future__ import annotations

import json
import subprocess
import sys
import os
from pathlib import Path

import pytest


def _run_mcp(requests, tmp_path):
    env = {**os.environ, "PYTHONPATH": str(Path.cwd()), "NEDVIGA_STATE_DIR": str(tmp_path)}
    proc = subprocess.run(
        [sys.executable, "-m", "nedviga", "mcp", "serve"],
        input="".join(json.dumps(r) + "\n" for r in requests),
        capture_output=True, text=True, env=env, cwd=str(Path.cwd()),
    )
    outs = [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]
    return proc, outs


def test_mcp_initialize_tools_list(tmp_path):
    reqs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    proc, outs = _run_mcp(reqs, tmp_path)
    assert any(o.get("id") == 1 for o in outs)
    tools = [o for o in outs if o.get("id") == 2][0]["result"]["tools"]
    assert len(tools) >= 20


def test_mcp_unknown_method(tmp_path):
    reqs = [{"jsonrpc": "2.0", "id": 1, "method": "foo/bar", "params": {}}]
    proc, outs = _run_mcp(reqs, tmp_path)
    assert outs[0]["error"]["code"] == -32601


def test_mcp_card_envelope(tmp_path):
    card = {"id": "cian-1", "source": "cian", "url": "u", "title": "flat"}
    f = tmp_path / "card.json"
    f.write_text(json.dumps(card))
    reqs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "card", "arguments": {"path": str(f)}}},
    ]
    proc, outs = _run_mcp(reqs, tmp_path)
    call = [o for o in outs if o.get("id") == 2][0]
    assert "result" in call


def test_mcp_contacts_ignored(tmp_path):
    card = {"id": "cian-1", "source": "cian", "url": "u", "title": "flat", "seller": {"phones": ["+7 (999) 000-11-22"]}}
    f = tmp_path / "card.json"
    f.write_text(json.dumps(card))
    reqs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "card", "arguments": {"path": str(f), "with_contacts": True}}},
    ]
    proc, outs = _run_mcp(reqs, tmp_path)
    text = json.dumps(outs)
    import re
    assert re.findall(r"\+?7[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}", text) == []
