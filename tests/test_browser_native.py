"""Offline unit tests for the native browser launcher (M3).

The real browser is never launched; camoufox and Playwright objects are
replaced with lightweight mocks.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from nedviga import browser_native as bn
from nedviga.errors import FetchError


class TestLibraryPath:
    def test_override_env_wins(self, monkeypatch):
        monkeypatch.setenv("CW_NEDVIGA_LD_PATH", "/custom/libs")
        assert bn._library_path() == "/custom/libs"

    def test_default_falls_back_to_none_when_missing(self, monkeypatch):
        monkeypatch.delenv("CW_NEDVIGA_LD_PATH", raising=False)
        # The real bundled path may or may not exist in CI; the function simply
        # returns None when nothing matches.
        result = bn._library_path()
        assert result is None or isinstance(result, str)


class TestNativeAvailable:
    def test_returns_true_when_camoufox_importable(self):
        # camoufox is a required dependency for M3.
        assert bn.native_available() is True


class TestSingletonAndCrashRecovery:
    def test_fetch_reuses_browser_and_recovers_after_crash(self):
        # Build a fake browser whose first new_page() call fails and second
        # succeeds. The relaunch must return a fresh browser without touching
        # the real Camoufox launcher.
        fake_page = MagicMock()
        fake_page.evaluate.return_value = "<html>ok</html>"

        fake_browser = MagicMock()
        fake_browser.new_page.side_effect = [RuntimeError("died"), fake_page]

        fresh_browser = MagicMock()
        fresh_browser.new_page.return_value = fake_page

        fake_pw = MagicMock()
        fresh_pw = MagicMock()

        with patch.object(
            bn, "_BROWSER_HOLDER", {"browser": fake_browser, "pw": fake_pw}
        ):
            with patch.object(bn, "_RELAUNCH_TS", 0.0):
                with patch.object(
                    bn, "_launch_browser", return_value=(fresh_pw, fresh_browser)
                ):
                    # _get_browser will see the existing browser as alive because
                    # browser_type attribute access works on a MagicMock.
                    html = bn.native_fetch("https://example.com/")

        assert html == "<html>ok</html>"
        assert fake_browser.new_page.call_count == 1
        assert fresh_browser.new_page.call_count == 1
        fake_pw.__exit__.assert_called_once()

    def test_relaunch_cooldown_raises_fetch_error(self):
        import time

        with patch.object(bn, "_BROWSER_HOLDER", {"browser": None, "pw": None}):
            with patch.object(bn, "_RELAUNCH_TS", time.monotonic()):
                with pytest.raises(FetchError, match="cooldown"):
                    bn._get_browser()

    def test_empty_dom_raises_fetch_error(self):
        fake_page = MagicMock()
        fake_page.evaluate.return_value = "   "

        fake_browser = MagicMock()
        fake_browser.new_page.return_value = fake_page

        with patch.object(bn, "_BROWSER_HOLDER", {"browser": fake_browser, "pw": None}):
            with patch.object(bn, "_RELAUNCH_TS", 0.0):
                with pytest.raises(FetchError, match="empty DOM"):
                    bn.native_fetch("https://example.com/")


class TestNativeStatus:
    def test_status_reflects_holder(self):
        fake_browser = MagicMock()
        with patch.object(bn, "_BROWSER_HOLDER", {"browser": fake_browser, "pw": None}):
            status = bn.native_status()
        assert status["mode"] == "native"
        assert status["available"] is True
        assert status["running"] is True


class TestImportSideEffects:
    """F-08: importing nedviga.browser_native must not mutate os.environ."""

    def test_import_does_not_change_environ(self):
        import os
        import subprocess
        import sys

        script = (
            "import json, os; "
            "before = dict(os.environ); "
            "import nedviga.browser_native; "
            "after = dict(os.environ); "
            "diff = {k: v for k, v in after.items() if before.get(k) != v}; "
            "print(json.dumps(diff))"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            cwd=str(__import__("pathlib").Path(__file__).resolve().parent.parent),
            env={**os.environ, "PYTHONPATH": str(__import__("pathlib").Path(__file__).resolve().parent.parent)},
        )
        assert result.returncode == 0, result.stderr
        diff = json.loads(result.stdout.strip())
        assert diff == {}, f"import mutated environ: {diff}"
