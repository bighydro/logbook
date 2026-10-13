"""`day_start` (RFC 0036): where the owner's day begins, and the one rule every reader that puts a
line on a day applies.

`logbook.json` MAY carry `"day_start": "HH:MM"`, a clock in the 24-hour form; absent, it is
`"00:00"`, the calendar day. The **local day** of an instant is its calendar date in the record's
zone (SPEC §3.2), except that an instant whose local wall clock is before `day_start` belongs to
the date before: with `"06:00"`, a line at 01:30 on the 13th is on the 12th, a line at 06:00 or
07:00 on the 13th is on the 13th. The comparison is on the wall clock after localising, so a change
of offset in the night moves no line: the day is what the owner's clock said. A day's span is from
`day_start` on its date to `day_start` on the next.

The setting is a reader's. No line, hash or month file changes with it (SPEC §1: a line's month is
the month of its `at` in UTC). `verify` never reads it and `add` never groups by day.

A reader that groups by day takes `of(meta)` once, before it reads anything: it refuses a value it
cannot parse (not `HH:MM`, or outside 00:00 to 23:59) with `DayStartError`, naming the key and the
value, as SPEC §2 refuses a zone it does not know, and never groups as if the key were absent. The
index (`index.local_date`) derives `day_local` with `lenient` and never refuses, since it is
extended inside `add`; under a value no reader accepts it reads midnight, and no reader reads it.

The night window of `policy/stays.json` (22:00 to 08:00 by default) is unchanged and independent:
it finds a night's stay (`stays.night`), and a night keeps the date its window starts on.
`day_start` says which night is a day's: the night after a day is the one whose window holds the
day's end (the stay at 06:00 next morning, under `"06:00"`), the night before it the one that holds
the day's start, and when the boundary falls between two windows (a day that begins at noon) the
last night begun before it. Under any boundary before the night's start, which midnight is, the
night after a day is the night of that date, as it always was."""

from __future__ import annotations

import functools
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

KEY = "day_start"  # the key of logbook.json
MIDNIGHT = "00:00"  # absent, this: the calendar day
_CLOCK = re.compile(r"([01]\d|2[0-3]):([0-5]\d)\Z")


class DayStartError(ValueError):
    """A `day_start` this reader cannot parse: the command that groups by day refuses, naming it."""


def clock(value: object) -> time:
    """`value` as the clock it names; None (the key absent) is midnight. `DayStartError` naming the
    key and the value for anything that is not `HH:MM` from 00:00 to 23:59."""
    if value is None:
        return time(0)
    found = _clock(value) if isinstance(value, str) else None
    if found is None:
        raise DayStartError(
            f"logbook.json has {KEY} {value!r}, which is not a clock from 00:00 to 23:59 written HH:MM;"
            " a reader that groups lines by day refuses rather than guess (RFC 0036): write it as"
            f' "06:00", or remove the key for midnight'
        )
    return found


def lenient(value: object) -> time:
    """The index's reading of `value`: its clock, or midnight for a value no reader accepts."""
    found = _clock(value) if isinstance(value, str) else None
    return time(0) if found is None else found


@functools.lru_cache(maxsize=64)
def _clock(text: str) -> time | None:
    m = _CLOCK.match(text)
    return None if m is None else time(int(m[1]), int(m[2]))


def text_of(value: object) -> str:
    """What the setting says, as `doctor` and the index's meta name it: `"00:00"` when absent."""
    return MIDNIGHT if value is None else str(value)


def local_day(instant: datetime, zone: ZoneInfo, start: time) -> date:
    """The rule (RFC 0036): the calendar date of `instant` on the wall clock of `zone`, the date
    before when that clock reads earlier than `start`."""
    local = instant.astimezone(zone)
    if start != time(0) and local.time() < start:
        return local.date() - timedelta(days=1)
    return local.date()


@dataclass(frozen=True)
class DayStart:
    """The record's zone and where its day begins: what a reader asks which day an instant is on,
    where a day starts and ends, and which nights frame it."""

    zone: ZoneInfo
    start: time = time(0)

    @property
    def text(self) -> str:
        return f"{self.start.hour:02d}:{self.start.minute:02d}"

    @property
    def midnight(self) -> bool:
        return self.start == time(0)

    def day(self, instant: datetime) -> date:
        """The local day `instant` is on."""
        return local_day(instant, self.zone, self.start)

    def day_of(self, stamp: str) -> str:
        """The local day of an RFC 3339 stamp (a line's `at`), `YYYY-MM-DD`."""
        return self.day(datetime.fromisoformat(stamp.replace("Z", "+00:00"))).isoformat()

    def today(self, now: datetime) -> date:
        """The day the owner is in at `now`: at 05:59 under `"06:00"`, still yesterday."""
        return self.day(now)

    def span(self, day: str | date) -> tuple[datetime, datetime]:
        """Where `day` starts and where it ends on the record's clock: `day_start` on its date to
        `day_start` on the next (local midnight to midnight under the default)."""
        d = date.fromisoformat(day) if isinstance(day, str) else day
        return (
            datetime.combine(d, self.start, tzinfo=self.zone),
            datetime.combine(d + timedelta(days=1), self.start, tzinfo=self.zone),
        )

    def night_after(self, day: str, night_start: str) -> str:
        """The date of the night that follows `day` (its window starts at `night_start`, the
        settings' `night[0]`): the night whose window holds the day's end."""
        return (date.fromisoformat(day) + timedelta(days=self._shift(night_start))).isoformat()

    def night_before(self, day: str, night_start: str) -> str:
        """The date of the night that precedes `day`: the one whose window holds the day's start."""
        return (date.fromisoformat(day) - timedelta(days=1 - self._shift(night_start))).isoformat()

    def day_before_night(self, night: str, night_start: str) -> str:
        """The day the night of date `night` follows: `night_after`'s inverse."""
        return (date.fromisoformat(night) - timedelta(days=self._shift(night_start))).isoformat()

    def _shift(self, night_start: str) -> int:
        """1 when the boundary is at or after the night's start (a day that begins at 23:00 ends
        inside the window of the next date's night), else 0."""
        return 1 if self.start >= time.fromisoformat(night_start) else 0

    def describe(self) -> str:
        """`06:00 to 06:00 the next day`: the day's span in words, as the Day's header says it."""
        return span_words(self.text)


def span_words(clock: str) -> str:
    """`06:00 to 06:00 the next day`: where a day begins and ends, said where it is not midnight."""
    return f"{clock} to {clock} the next day"


def of(meta: Mapping[str, Any]) -> DayStart:
    """The record's day as `logbook.json` (`meta`) sets it: its zone and its `day_start`.
    `DayStartError` for a value this reader cannot parse; the zone's own error for a zone this
    machine does not know."""
    return DayStart(ZoneInfo(str(meta["timezone"])), clock(meta.get(KEY)))
