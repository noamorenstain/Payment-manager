"""Injectable clock. All "today" logic must go through a Clock so tests can freeze dates.

The real clock uses the Windows local date/time, as required by the specification.
"""

from __future__ import annotations

import datetime as dt


class Clock:
    def now(self) -> dt.datetime:
        return dt.datetime.now().replace(microsecond=0)

    def today(self) -> dt.date:
        return self.now().date()


class FrozenClock(Clock):
    """Test clock: fixed until explicitly moved."""

    def __init__(self, at: dt.datetime | dt.date):
        if isinstance(at, dt.date) and not isinstance(at, dt.datetime):
            at = dt.datetime.combine(at, dt.time(9, 0))
        self._now = at

    def now(self) -> dt.datetime:
        return self._now

    def set(self, at: dt.datetime | dt.date) -> None:
        if isinstance(at, dt.date) and not isinstance(at, dt.datetime):
            at = dt.datetime.combine(at, dt.time(9, 0))
        self._now = at

    def advance(self, **delta) -> None:
        self._now = self._now + dt.timedelta(**delta)
