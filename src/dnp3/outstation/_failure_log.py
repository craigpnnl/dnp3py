"""Per-key flood control for application-code failure logging (#46).

A handler that keeps failing the same way on every request could otherwise
fill the log at whatever rate the peer sends requests. ``FailureLogLimiter``
allows at most one ERROR record per key per window, so the rate is bounded by
code regardless of what a master sends.
"""

import time
from dataclasses import dataclass

from dnp3.core.enums import FunctionCode

WINDOW_SECONDS = 60.0

# (function, handler method name, exception type). The handler method and
# exception type are supplied by the caller, not derived from wire data, so
# the set of keys a run can ever produce is bounded by the code that calls
# FailureLogLimiter.record, never by anything a peer sends.
FailureKey = tuple[FunctionCode, str, type[BaseException]]


@dataclass
class _Window:
    started: float
    suppressed: int = 0


class FailureLogLimiter:
    """Tracks one flood-control window per failure key."""

    def __init__(self) -> None:
        self._windows: dict[FailureKey, _Window] = {}

    def record(self, key: FailureKey) -> int | None:
        """Register one failure of ``key`` and say whether to log it now.

        Returns the number suppressed since ``key``'s last logged record
        (0 when there is nothing to report) when this failure should be
        logged. Returns None when it falls inside an already-open window
        and should only be counted.
        """
        now = time.monotonic()
        window = self._windows.get(key)
        if window is None or now - window.started >= WINDOW_SECONDS:
            suppressed = window.suppressed if window is not None else 0
            self._windows[key] = _Window(started=now)
            return suppressed
        window.suppressed += 1
        return None
