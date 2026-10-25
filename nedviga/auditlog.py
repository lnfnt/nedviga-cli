"""v0.5.5 (the task brief) audit log."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from . import pipeline


def _state_dir() -> Path:
    return Path(os.environ.get("NEDVIGA_STATE_DIR", str(Path.home() / ".local" / "share" / "nedviga")))


def _log_path(ts=None) -> Path:
    ts = ts or datetime.now(timezone.utc)
    return _state_dir() / f"audit-{ts.strftime('%Y-%m')}.log.jsonl"


def log_action(role: str, command: str, card_id: Optional[str] = None, rc: int = 0,
               reason: Optional[str] = None, argv: Optional[list] = None,
               pii: bool = False, purpose: Optional[str] = None) -> None:
    # skeleton argv: remove values? store flags only roughly; store command + flags (no PII values)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "role": role,
        "command": command,
        "card_id": card_id,
        "rc": rc,
        "reason": reason,
        "pii": pii,
        "purpose": purpose,
        "argv_skeleton": [a for a in (argv or []) if a.startswith("-") or a in {"search","get-card","export","card","pipeline","watch","feedback","project","chain","checklist","purge","audit","pii-log"}],
    }
    p = _log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _all_log_files() -> list[Path]:
    base = _state_dir()
    return sorted(base.glob("audit-*.log.jsonl"))


def size_warn() -> bool:
    total = sum(p.stat().st_size for p in _all_log_files() if p.exists())
    return total > 50 * 1024 * 1024


def read_entries(days: int = 30, role: Optional[str] = None, card: Optional[str] = None,
                 pii_only: bool = False) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for p in _all_log_files():
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                e = json.loads(line)
                ts = datetime.fromisoformat(e["ts"].replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts < cutoff:
                    continue
                if role and e.get("role") != role:
                    continue
                if card and e.get("card_id") != card:
                    continue
                if pii_only and not e.get("pii"):
                    continue
                out.append(e)
        except Exception:
            continue
    return out
