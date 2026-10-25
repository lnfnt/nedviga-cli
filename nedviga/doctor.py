"""System diagnostics command for nedviga-cli."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from .browser_native import native_available, native_status
from .models import ApiOutcomeEnvelope
from .outcomes import make_envelope


CACHE_DIR = Path.home() / ".cache" / "nedviga-cli"
REQUIRED_DEPS = ("pydantic", "yaml", "camoufox")


def _check_python() -> tuple[bool, str]:
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    return sys.version_info >= (3, 11), version


def _check_dependencies() -> tuple[bool, list[str]]:
    missing = [dep for dep in REQUIRED_DEPS if importlib.util.find_spec(dep) is None]
    return not missing, missing


def _check_cache() -> tuple[bool, str]:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        probe = CACHE_DIR / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True, str(CACHE_DIR)
    except Exception as exc:  # pragma: no cover - hard to trigger in tests
        return False, str(exc)


def verify_signature(file_path: str, pubkey_path: str | None = None) -> dict:
    """ gpg-подпись релизного артефакта против бандл-публичного ключа.
    Честные статусы: ok / fail / unsigned / gpg_unavailable. Молчание запрещено."""
    import subprocess, tempfile, os
    from pathlib import Path as _P
    f = _P(file_path)
    asc = f.with_name(f.name + ".asc")
    if not f.exists():
        return {"status": "fail", "reason": "file_missing"}
    if not asc.exists():
        return {"status": "unsigned", "reason": "no .asc next to file"}
    keyfile = _P(pubkey_path) if pubkey_path else _P(__file__).parent / "data" / "release_pubkey.asc"
    if not keyfile.exists():
        return {"status": "fail", "reason": "bundled pubkey missing"}
    with tempfile.TemporaryDirectory() as td_:
        env = {**os.environ, "GNUPGHOME": td_}
        try:
            subprocess.run(["gpg", "--batch", "--quiet", "--import", str(keyfile)], env=env,
                           capture_output=True, timeout=30)
            r = subprocess.run(["gpg", "--batch", "--quiet", "--status-fd", "1",
                                "--verify", str(asc), str(f)], env=env,
                               capture_output=True, text=True, timeout=60)
        except FileNotFoundError:
            return {"status": "gpg_unavailable", "reason": "gpg binary not found"}
        except Exception as exc:
            return {"status": "fail", "reason": f"verify_error: {type(exc).__name__}"}
    out = r.stdout or ""
    if r.returncode == 0 and ("VALIDSIG" in out or "GOODSIG" in out):
        fpr = [x.split("\t")[-1] for x in out.splitlines() if "VALIDSIG" in x]
        return {"status": "ok", "signer_fpr": (fpr or [""])[0][-16:]}
    if "BADSIG" in out or "ERRSIG" in out:
        return {"status": "fail", "reason": "bad_signature (key/file mismatch)"}
    return {"status": "fail", "reason": "unparsable gpg output"}


def run_doctor() -> tuple[ApiOutcomeEnvelope, int]:
    """Run diagnostics and return (envelope, exit_code)."""
    python_ok, python_version = _check_python()
    deps_ok, missing_deps = _check_dependencies()
    cache_ok, cache_detail = _check_cache()
    browser_available = native_available()
    browser_status = native_status()

    critical = not python_ok or not deps_ok or not cache_ok or not browser_available

    data = {
        "python_ok": python_ok,
        "python_version": python_version,
        "dependencies_ok": deps_ok,
        "missing_dependencies": missing_deps,
        "cache_ok": cache_ok,
        "cache_dir": cache_detail,
        "browser": {
            "status": "available" if browser_available else "missing",
            "available": browser_available,
            "running": browser_status["running"],
            "mode": browser_status["mode"],
            "note": (
                "Camoufox stealth browser is required for live search/get-card. "
                "Install with: pip install 'camoufox[geoip]' && python3 -m camoufox fetch"
            ),
        },
    }

    if critical:
        reason_parts = []
        if not python_ok:
            reason_parts.append("python_version_too_old")
        if not deps_ok:
            reason_parts.append("missing_dependencies")
        if not cache_ok:
            reason_parts.append("cache_not_writable")
        if not browser_available:
            reason_parts.append("browser_not_available")
        envelope = make_envelope(
            status="error",
            reason=",".join(reason_parts),
            source="doctor",
            data=data,
            metadata={"engine": "native", "cached": False, "elapsed_seconds": 0.0},
        )
        return envelope, 1

    envelope = make_envelope(
        status="ok",
        source="doctor",
        data=data,
        metadata={"engine": "native", "cached": False, "elapsed_seconds": 0.0},
    )
    return envelope, 0
