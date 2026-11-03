# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 lnfnt <lnfnt@proton.me>

"""Safe self-update for nedviga-cli (command ``update``).

Contract (TASK_UPDATER.md):
- ``check_update(source="pypi", target=None) -> dict``
- ``run_update(source="pypi", target=None, runner=None) -> dict``
- local state dir (~/.local/share/nedviga or NEDVIGA_STATE_DIR) is never touched;
  update reports ``data_safe`` / ``data_preserved``.
- fail-closed: raises :class:`UpdaterError` with ``UPDATE_FAILED: ...`` text.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

PACKAGE = "nedviga-cli"
PYPI_JSON_URL = "https://pypi.org/pypi/nedviga-cli/json"


class UpdaterError(RuntimeError):
    pass


ALLOWED_SOURCES = ("pypi", "git")


def _validate_source(source):
    if source not in ALLOWED_SOURCES:
        raise UpdaterError(
            f"UPDATE_FAILED: unsupported source '{source}' (use pypi|git)"
        )


def _validate_target(source, target):
    if source == "pypi":
        if target is not None and str(target).strip() not in ("", PACKAGE):
            raise UpdaterError("UPDATE_FAILED: arbitrary target rejected for pypi source")
        return
    # git source: allowlist -- only a bare package name, no paths/URLs/specs.
    if not target or not str(target).strip():
        raise UpdaterError("UPDATE_FAILED: --target required for --source git")
    t = str(target).strip()
    import re as _re
    if not _re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", t):
        raise UpdaterError("UPDATE_FAILED: arbitrary target rejected")


def _state_dir() -> Path:
    return Path(os.environ.get("NEDVIGA_STATE_DIR", str(Path.home() / ".local" / "share" / "nedviga")))


def _snapshot(state: Path) -> dict:
    """Mapping of state_dir files to (size, sha256) at this moment."""
    if not state.is_dir():
        return {}
    out = {}
    for p in state.iterdir():
        if p.is_file():
            data = p.read_bytes()
            out[p.name] = (len(data), hashlib.sha256(data).hexdigest())
    return out


def _version_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in str(version).split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit()) or "0"
        parts.append(int(digits))
    return tuple(parts)


def _git_local_version(root: Path) -> str:
    # offline: read __version__ from a local checkout tree
    for cand in (root, root / "nedviga", root / "src" / "nedviga"):
        init = cand / "__init__.py"
        if init.is_file():
            text = init.read_text(encoding="utf-8")
            match = re.search(r'__version__\s*=\s*["\']([^"\']+)', text)
            if match:
                return match.group(1)
    raise UpdaterError(
        "UPDATE_FAILED: no nedviga/__init__.py under git target; "
        "cannot determine version offline"
    )


def _pypi_latest(source: str = "pypi", target: str | None = None) -> str:
    if source == "git":
        if not target:
            raise UpdaterError("UPDATE_FAILED: --target required for --source git")
        path = Path(target)
        if path.exists():
            return _git_local_version(path)
        # remote git URL would need network; fail-closed instead of guessing
        raise UpdaterError(
            "UPDATE_FAILED: git URL check requires local checkout target "
            "(clone first and pass the path)"
        )
    with urllib.request.urlopen(PYPI_JSON_URL, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["info"]["version"]

def check_update(source: str = "pypi", target: str | None = None, _fetch=None) -> dict:
    from . import __version__ as current

    _validate_source(source)
    _validate_target(source, target)
    try:
        latest = (_fetch or _pypi_latest)(source, target)
    except UpdaterError:
        raise
    except Exception as exc:
        raise UpdaterError(f"UPDATE_FAILED: cannot determine latest version: {exc}") from exc

    state = _state_dir()
    return {
        "ok": True,
        "source": source,
        "target": target,
        "current_version": current,
        "latest_version": latest,
        "update_available": _version_tuple(latest) > _version_tuple(current),
        "state_dir": str(state),
        "state_files": len(_snapshot(state)),
        "data_safe": True,
    }


def _default_runner(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, (proc.stdout + "\n" + proc.stderr).strip()


def run_update(source: str = "pypi", target: str | None = None, runner=None) -> dict:
    from . import __version__ as current

    _validate_source(source)
    _validate_target(source, target)

    state = _state_dir()
    before = _snapshot(state)

    if source == "pypi":
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", PACKAGE]
    else:
        if not target:
            raise UpdaterError("UPDATE_FAILED: --target required for --source git")
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", str(target)]

    run = runner or _default_runner
    try:
        rc, output = run(cmd)
    except Exception as exc:
        raise UpdaterError(f"UPDATE_FAILED: pip runner error: {exc}") from exc

    after = _snapshot(state)
    preserved = before == after
    if rc != 0:
        raise UpdaterError(f"UPDATE_FAILED: pip exited {rc}: {output[-400:]}")

    return {
        "ok": True,
        "source": source,
        "target": target,
        "command": cmd,
        "from_version": current,
        "state_dir": str(state),
        "state_files": len(after),
        "data_safe": True,
        "data_preserved": preserved,
        "output": output,
    }
