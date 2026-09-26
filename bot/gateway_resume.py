"""Pure helpers for the user-account Gateway reconnect policy."""

from __future__ import annotations

EXPLICIT_CLOSE_CODES = frozenset({1000, 1001})
# Discord rejected the token outright (e.g. wrong token, password changed,
# account locked/flagged). Resuming with it can never succeed.
AUTH_FAILED_CLOSE_CODES = frozenset({4004})
INITIAL_BACKOFF = 1.0
MAX_BACKOFF = 30.0


def should_resume(
    invalid_resumable: bool | None,
    close_code: int | None,
    has_saved_session: bool,
) -> bool:
    """Decide whether a dropped Gateway connection may be resumed.

    An explicit non-resumable invalid session (op 9 with ``d: false``), a
    deliberate close (1000/1001), or an authentication failure (4004) must
    start a fresh session. Anything else may resume when a saved session
    exists.
    """
    if invalid_resumable is False:
        return False
    if close_code in EXPLICIT_CLOSE_CODES:
        return False
    if close_code in AUTH_FAILED_CLOSE_CODES:
        return False
    return bool(has_saved_session)


def next_backoff(current: float) -> float:
    """Grow the reconnect delay exponentially, capped at ``MAX_BACKOFF``."""
    return min(current * 2, MAX_BACKOFF)
