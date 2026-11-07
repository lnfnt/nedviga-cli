# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 lnfnt <lnfnt@proton.me>
"""Compat-shim: netguard re-export + nedviga-cli egress policy.

Canonical implementation ships with this tree at ``nedviga/_secure/netguard.py``
(vendored copy of the project's shared network guard). This shim layers the
product egress policy on top of the canonical fail-closed core:

  1. live network access is a standard feature of the search tool; an explicit
     egress proxy is a user option, not a prerequisite. Direct egress is
     allowed by default (the canonical default-deny gate is lifted here).
  2. an explicit ``NEDVIGA_EGRESS_PROXY`` (alias ``SUD_EGRESS_PROXY``,
     compatibility) switches back to the tunneled mode: all traffic via a
     CONNECT tunnel.
  3. standard ``HTTPS_PROXY``/``HTTP_PROXY`` (and lowercase variants) are used
     as egress when no explicit variable is set.
  4. ``NEDVIGA_ALLOW_DIRECT`` is the killswitch: "0/false/no/off" forbids
     direct egress (fail-closed), unset/"1" allows it.
"""
from __future__ import annotations

import os as _os

from nedviga._secure.netguard import *  # noqa: F401,F403
from nedviga._secure.netguard import (  # noqa: F401
    NETGUARD_VERSION, EGRESS_STATE, EgressBlockedError, BreakerOpenError,
    _DEFAULT_DB, _normalize_proxy_url, _applies_to, _breaker_db,
    _breaker_suffixes, guard_url, guarded_get,
    check_before_fetch, breaker_remaining, breaker_trip,
    breaker_soft_fail, breaker_success, spotlight, is_spotlighted, strip_spotlight,
)

_STD_PROXY_VARS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")
_DENY = {"0", "false", "no", "off"}


def _egress_proxy() -> str:
    """Egress proxy of nedviga-cli: explicit NEDVIGA/SUD proxy wins; standard
    HTTPS_PROXY/HTTP_PROXY are the fallback user option."""
    explicit = (
        _os.environ.get("NEDVIGA_EGRESS_PROXY")
        or _os.environ.get("SUD_EGRESS_PROXY")
        or ""
    ).strip()
    if explicit:
        return explicit
    for var in _STD_PROXY_VARS:
        v = (_os.environ.get(var) or "").strip()
        if v:
            return v
    return ""


def _allow_direct() -> bool:
    """Direct egress is enabled by default; an explicit "0/false/no/off" in
    NEDVIGA_ALLOW_DIRECT restores the canonical fail-closed behavior."""
    return (_os.environ.get("NEDVIGA_ALLOW_DIRECT") or "").strip().lower() not in _DENY
