"""v0.5.5 (the task brief) roles."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

WRITE_COMMANDS = {
    "pipeline": {"set"},
    "watch": {"add", "rm"},
    "feedback": {"add", "apply"},
    "project": {"new", "add", "refresh"},
    "chain": {"new", "link"},
    "checklist": {"handoff"},
    "purge": {"card", "profile"},
}

READ_COMMANDS = {
    "search", "get-card", "export", "import", "walk-distance", "doctor",
    "pipeline", "watch", "digest", "compare", "bargain", "risk", "triage",
    "checklist", "callsheet", "project", "poi", "tour", "market", "stale",
    "catalog-pdf", "sources", "dedup", "scorefit", "chain", "text", "audit",
    "pii-log", "feedback",
}


def roles_file() -> Path:
    p = os.environ.get("NEDVIGA_ROLES_FILE")
    if p:
        return Path(p)
    base = Path(os.environ.get("NEDVIGA_STATE_DIR", str(Path.home() / ".local" / "share" / "nedviga")))
    return base / "roles.json"


def load_roles() -> list[dict]:
    p = roles_file()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, list):
        return data
    return []


def current_role() -> str:
    return os.environ.get("NEDVIGA_ROLE", "agent")


def validate_role() -> tuple[bool, Optional[str]]:
    role = current_role()
    roles = load_roles()
    # default agent allowed even without manifest? Task: family/auditor must be declared explicitly.
    if role == "agent":
        return True, None
    for r in roles:
        if r.get("name") == role or r.get("role") == role:
            # manifest contains role
            if r.get("role") == role:
                return True, None
    # also allow if manifest lists role as a role value
    for r in roles:
        if r.get("role") == role:
            return True, None
    return False, "unknown_role"


def _subcommand(args) -> Optional[str]:
    # determine subcommand for grouped commands
    for attr in ("pipeline_action", "watch_action", "feedback_action", "project_action",
                 "chain_action", "checklist_action", "text_action", "sources_action"):
        v = getattr(args, attr, None)
        if v:
            return v
    return None


def is_write(args) -> bool:
    cmd = getattr(args, "command", None)
    sub = _subcommand(args)
    if cmd in ("purge",):
        return True
    if cmd in WRITE_COMMANDS:
        if sub is None:
            return True
        return sub in WRITE_COMMANDS[cmd]
    return False


def check_permission(args) -> tuple[bool, Optional[str]]:
    role = current_role()
    ok, reason = validate_role()
    if not ok:
        return False, reason
    cmd = getattr(args, "command", None)
    sub = _subcommand(args)
    if role == "agent":
        return True, None
    if role == "auditor":
        # read-only: no writes, no contacts
        if is_write(args):
            return False, "role_forbidden"
        return True, None
    if role == "family":
        if is_write(args):
            # allow feedback add
            if cmd == "feedback" and sub == "add":
                return True, None
            # pipeline set only show->feedback: allow if status == feedback
            if cmd == "pipeline" and sub == "set":
                if getattr(args, "status", None) == "feedback":
                    return True, None
                return False, "role_forbidden"
            return False, "role_forbidden"
        return True, None
    return False, "unknown_role"


def role_allows_contacts(role: Optional[str] = None) -> bool:
    r = role or current_role()
    return r == "agent"
