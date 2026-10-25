"""Runtime exceptions used by the live fetch pipeline.

These are intentionally separate from :class:`ParseError` so that the CLI can
distinguish fetch-time problems (WAF, crash, missing runtime) from offline
parser failures.
"""

from __future__ import annotations


class FetchError(RuntimeError):
    """Raised when a live network fetch fails for any reason.

    The message is actionable and never fabricates data.
    """


class ChallengeError(FetchError):
    """Raised when the target site returns a WAF/captcha/rate-limit page.

    Consumers should treat this as ``DEGRADED`` (exit code 2).
    """
