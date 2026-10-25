"""v0.5.7 (the task brief) MCP server."""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from typing import Any, Optional

import nedviga.cli as _cli


TOOLS = [    {"name": "getSourceCodeUrl", "description": "AGPL-3.0-only source information: license, repository URL, how to obtain sources", "inputSchema": {"type": "object"}},

    {"name": "card", "description": "Family card generation inputs"},
    {"name": "compare", "description": "Compare listings"},
    {"name": "pipeline_list", "description": "List pipeline"},
    {"name": "pipeline_set", "description": "Set pipeline status"},
    {"name": "watch_check", "description": "Watch check"},
    {"name": "digest", "description": "Digest"},
    {"name": "market", "description": "Market analytics"},
    {"name": "bargain", "description": "Bargain analysis"},
    {"name": "dedup", "description": "Dedup listings"},
    {"name": "risk", "description": "Risk scoring"},
    {"name": "triage", "description": "Legal triage"},
    {"name": "checklist", "description": "Checklist"},
    {"name": "scorefit", "description": "Score fit"},
    {"name": "tour", "description": "Tour routing"},
    {"name": "poi_offline", "description": "POI offline"},
    {"name": "litcheck", "description": "Litigation pre-check"},
    {"name": "ops", "description": "Ops panel"},
    {"name": "search_offline", "description": "Offline search corpus"},
    {"name": "auto", "description": "Auto selection"},
    {"name": "eco", "description": "Eco proxy"},
    {"name": "stale", "description": "Stale detection"},
]


def tool_list():
    return {"tools": [{"name": t["name"], "description": t["description"], "inputSchema": {"type": "object"}} for t in TOOLS]}


def _cmd_for(name: str):
    mapping = {
        "card": _cli._cmd_card,
        "compare": _cli._cmd_compare,
        "pipeline_list": _cli._cmd_pipeline,
        "pipeline_set": _cli._cmd_pipeline,
        "watch_check": _cli._cmd_watch,
        "digest": _cli._cmd_digest,
        "market": _cli._cmd_market,
        "bargain": _cli._cmd_bargain,
        "dedup": _cli._cmd_dedup,
        "risk": _cli._cmd_risk,
        "triage": _cli._cmd_triage,
        "checklist": _cli._cmd_checklist,
        "scorefit": _cli._cmd_scorefit,
        "tour": _cli._cmd_tour,
        "poi_offline": _cli._cmd_poi,
        "litcheck": _cli._cmd_litcheck,
        "ops": _cli._cmd_ops if hasattr(_cli, "_cmd_ops") else None,
        "auto": _cli._cmd_auto,
        "eco": _cli._cmd_eco,
        "stale": _cli._cmd_stale,
        "search_offline": _cli._cmd_search,
    }
    return mapping.get(name)


def _prepare_args(name: str, arguments: dict):
    ns = argparse.Namespace()
    ns.with_contacts = False
    ns._contacts_requested = False
    ns.role = "agent"
    ns.purpose = None
    # defaults for common
    for k, v in (arguments or {}).items():
        if k == "with_contacts":
            continue
        setattr(ns, k, v)
    # command-specific defaults
    if name == "pipeline_list":
        ns.pipeline_action = "list"
        ns.command = "pipeline"
    elif name == "pipeline_set":
        ns.pipeline_action = "set"
        ns.command = "pipeline"
    elif name == "watch_check":
        ns.watch_action = "check"
        ns.command = "watch"
    elif name == "checklist":
        # default new? leave action if provided
        if not hasattr(ns, "checklist_action"):
            ns.checklist_action = "new"
        ns.command = "checklist"
    elif name == "poi_offline":
        ns.command = "poi"
    else:
        ns.command = name.replace("_", "-")
    # ensure format defaults
    if not hasattr(ns, "format"):
        ns.format = "md" if name in {"compare", "tour"} else "telegram"
    if not hasattr(ns, "out"):
        ns.out = None
    if not hasattr(ns, "output"):
        ns.output = None
    return ns


def _invoke(name: str, arguments: dict) -> str:

    if name == "getSourceCodeUrl":
        import json as _j
        from ._wm import source_info
        try:
            from . import __version__ as _ver
        except Exception:
            _ver = "0"
        return _j.dumps(source_info(_ver), ensure_ascii=False, indent=1)
    func = _cmd_for(name)
    if func is None:
        raise ValueError(f"unknown tool: {name}")
    ns = _prepare_args(name, arguments)
    # map path->file for some tools
    if hasattr(ns, "path") and not hasattr(ns, "file"):
        pass
    # common: if arguments has path, set file too for tools expecting file
    if "path" in (arguments or {}) and not getattr(ns, "file", None):
        try:
            ns.file = arguments["path"]
        except Exception:
            pass
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        func(ns)
    except Exception as exc:
        sys.stdout = old
        return json.dumps({"error": str(exc)})
    finally:
        sys.stdout = old
    text = buf.getvalue().strip()
    # audit
    try:
        from .auditlog import log_action
        log_action(role="agent", command=f"mcp:{name}", card_id=getattr(ns, "card_id", None) or getattr(ns, "target", None),
                   rc=0, reason=None, argv=[], pii=False)
    except Exception:
        pass
    return text


def handle_request(request):
    method = request.get("method")
    rid = request.get("id")
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "nedviga-cli", "version": __import__("nedviga").__version__}}
    elif method == "notifications/initialized":
        return None
    elif method == "tools/list":
        result = tool_list()
    elif method == "tools/call":
        try:
            params = request.get("params", {}) or {}
            name = params["name"]
            args = params.get("arguments", {}) or {}
            text = _invoke(name, args)
            result = {"content": [{"type": "text", "text": text}], "isError": False}
        except (KeyError, TypeError, ValueError, OSError) as exc:
            result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
        except Exception as exc:
            result = {"content": [{"type": "text", "text": f"unexpected: {type(exc).__name__}: {exc}"}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "Method not found"}}
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def serve_stdio(input_stream=None, output_stream=None):
    input_stream = input_stream or sys.stdin
    output_stream = output_stream or sys.stdout
    for line in input_stream:
        if not line.strip():
            continue
        try:
            frame = json.loads(line)
        except json.JSONDecodeError as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {exc}"}}
        else:
            response = handle_request(frame)
        if response is not None:
            output_stream.write(json.dumps(response, ensure_ascii=False) + "\n")
            output_stream.flush()
