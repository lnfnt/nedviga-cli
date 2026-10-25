"""Offline regression tests for get-card target normalization (v0.4.2).

Root cause: ids emitted by the tool in ``cian-<digits>`` form fell into the
URL branch and were treated as hostnames by netguard (EgressBlockedError).
All tests are deterministic and perform no network requests.
"""

from __future__ import annotations

import pytest

from nedviga.cian_live import _target_to_url

CANONICAL = "https://www.cian.ru/sale/flat/765432190/"


@pytest.mark.parametrize(
    "target",
    [
        "cian-765432190",
        "CIAN-765432190",
        "765432190",
    ],
)
def test_id_forms_normalize_to_canonical_url(target: str) -> None:
    assert _target_to_url(target) == CANONICAL


def test_full_url_passes_through() -> None:
    assert _target_to_url("https://www.cian.ru/sale/flat/765432190/") == CANONICAL


def test_schemeless_url_gets_https_prefix() -> None:
    assert _target_to_url("www.cian.ru/sale/flat/765432190/") == CANONICAL


def test_surrounding_whitespace_is_stripped() -> None:
    assert _target_to_url("  cian-765432190  ") == CANONICAL
