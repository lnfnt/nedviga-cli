# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 lnfnt <lnfnt@proton.me>

"""Shared test fixtures."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """Create an isolated home directory."""
    return tmp_path / "shared_workspace"


@pytest.fixture
def profile() -> str:
    return "tester"


@pytest.fixture
def other() -> str:
    return "other"


@pytest.fixture(autouse=True)
def _isolated_routing_cache(tmp_path, monkeypatch):
    """Все тесты работают с изолированным кешем маршрутов (tmp), не с живым."""
    monkeypatch.setattr(
        "nedviga.routing_cache._DEFAULT", tmp_path / "routing_cache.sqlite"
    )


@pytest.fixture(autouse=True)
def _nedviga_write_ok(monkeypatch):
    monkeypatch.setenv("NEDVIGA_WRITE_OK", "1")
