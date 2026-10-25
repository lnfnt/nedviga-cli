"""v0.5.11 (the task brief) wizard."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from .roles import load_roles


def init(profile: str = "agent", out: Optional[str] = None) -> dict:
    base = Path(out) if out else Path.cwd() / "wizard_out"
    base.mkdir(parents=True, exist_ok=True)
    # roles.json
    roles = [{"name": "agent", "role": "agent", "since": "2026-01-01"}]
    if profile == "family":
        roles.append({"name": "family", "role": "family", "since": "2026-01-01"})
    (base / "roles.json").write_text(json.dumps(roles, ensure_ascii=False, indent=2), encoding="utf-8")
    # env template
    (base / "env.sh").write_text(
        'export NEDVIGA_EGRESS_PROXY="http://host:port"\n'
        'export NEDVIGA_MOS_TOKEN_FILE="/path/token.txt"\n'
        'export NEDVIGA_STATE_DIR="$HOME/.local/share/nedviga"\n',
        encoding="utf-8",
    )
    # profile template
    (base / "profile.json").write_text(json.dumps({"rooms": 2, "price_max": 20000000}, ensure_ascii=False, indent=2), encoding="utf-8")
    # cron example
    (base / "cron.txt").write_text(
        "0 */6 * * * nedviga-cli watch check --offline /path/fresh.json\n"
        "0 8 * * * nedviga-cli digest --days 1 --format telegram\n",
        encoding="utf-8",
    )
    # templates dir
    tdir = base / "profiles" / "templates"
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "metro_secondary.json").write_text(json.dumps({"rooms": 2, "metro_walk_max": 15}, ensure_ascii=False), encoding="utf-8")
    (tdir / "novostroyka.json").write_text(json.dumps({"rooms": 2, "price_max": 15000000}, ensure_ascii=False), encoding="utf-8")
    (tdir / "investment.json").write_text(json.dumps({"price_max": 12000000}, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "out": str(base)}


def doctor(json_out: bool = False) -> dict:
    import sys
    state_dir = Path(os.environ.get("NEDVIGA_STATE_DIR", str(Path.home() / ".local" / "share" / "nedviga")))
    checks = []
    checks.append({"name": "python", "ok": sys.version_info >= (3, 11), "detail": sys.version.split()[0]})
    checks.append({"name": "state_dir_writable", "ok": _writable(state_dir), "detail": str(state_dir)})
    egress = os.environ.get("NEDVIGA_EGRESS_PROXY")
    checks.append({"name": "egress_mode", "ok": bool(egress), "detail": egress or "not set (direct mode)"})
    tok_file = os.environ.get("NEDVIGA_MOS_TOKEN_FILE")
    tok_ok = False
    if tok_file:
        try:
            tok_ok = Path(tok_file).is_file() and Path(tok_file).stat().st_size > 0
        except Exception:
            tok_ok = False
    checks.append({"name": "token_file", "ok": tok_ok, "detail": tok_file or "not set"})
    # netguard import
    try:
        import nedviga.net_guard
        netguard_ok = True
    except Exception:
        netguard_ok = False
    checks.append({"name": "netguard", "ok": netguard_ok, "detail": "importable" if netguard_ok else "fail"})
    # registry counts
    try:
        import sqlite3
        db = state_dir / "mos_mkd.sqlite"
        if db.exists():
            conn = sqlite3.connect(str(db))
            c1 = conn.execute("SELECT COUNT(*) FROM mkd").fetchone()[0]
            c2 = 0
            try:
                c2 = conn.execute("SELECT COUNT(*) FROM mkd520").fetchone()[0]
            except Exception:
                c2 = 0
            conn.close()
            checks.append({"name": "registry", "ok": True, "detail": f"mkd={c1}, mkd520={c2}"})
        else:
            checks.append({"name": "registry", "ok": True, "detail": "no db yet"})
    except Exception as exc:
        checks.append({"name": "registry", "ok": False, "detail": str(exc)})
    ok = all(c["ok"] for c in checks if c["name"] in {"python", "state_dir_writable", "netguard"})
    return {"ok": ok, "checks": checks}


def _writable(p: Path) -> bool:
    try:
        p.mkdir(parents=True, exist_ok=True)
        test = p / ".wizard_write_test"
        test.write_text("x")
        test.unlink()
        return True
    except Exception:
        return False


def render_text(res: dict) -> str:
    lines = []
    for c in res["checks"]:
        mark = "OK" if c["ok"] else "FAIL"
        lines.append(f"[{mark}] {c['name']}: {c['detail']}")
    lines.append("overall: " + ("OK" if res["ok"] else "FAIL"))
    return "\n".join(lines)
