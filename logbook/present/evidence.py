"""The evidence of a window by day (`Evidence`), and whether a line's span overlaps a stay or
falls inside it."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from ..chain import Line
from ..stays import Segment, instant
from .model import EVIDENCE_KINDS


class Evidence:
    """The evidence lines of a window (`EVIDENCE_KINDS`) bucketed by every local day their span
    touches, so the company of a stay is read from the lines of the stay's days — one lookup per
    stay — and never by a pass over the whole window per stay or per place. The sources above still
    apply their exact rules to what `near` returns; a line on the stay's day that does not overlap
    it places nobody, as before."""

    def __init__(self, lines: Iterable[Line], tz: ZoneInfo):
        self.tz = tz
        self._by_day: dict[date, list[Line]] = {}
        for line in lines:
            if line.get("kind") not in EVIDENCE_KINDS:
                continue
            at = instant(line.get("at"))
            if at is None:
                continue
            end = instant(line.get("end")) or at
            first, last = at.astimezone(tz).date(), max(at, end).astimezone(tz).date()
            day = first
            while day <= last:
                self._by_day.setdefault(day, []).append(line)
                day += timedelta(days=1)

    def near(self, stay: Segment) -> list[Line]:
        """The evidence lines of the days the stay touches, in chain order, each once."""
        found: dict[str, Line] = {}
        day, last = stay.start.astimezone(self.tz).date(), stay.end.astimezone(self.tz).date()
        while day <= last:
            for line in self._by_day.get(day, ()):
                found.setdefault(str(line.get("id")), line)
            day += timedelta(days=1)
        return sorted(found.values(), key=lambda line: int(line.get("seq", 0)))


def _overlaps(stay: Segment, line: Line) -> bool:
    return _overlap_s(stay, line) > 0 or _inside(stay, line)


def _overlap_s(stay: Segment, line: Line) -> float:
    """The seconds the line's span shares with the stay; zero for an instant or no overlap."""
    at = instant(line.get("at"))
    if at is None:
        return 0.0
    end = instant(line.get("end")) or at
    return max(0.0, (min(end, stay.end) - max(at, stay.start)).total_seconds())


def _inside(stay: Segment, line: Line) -> bool:
    at = instant(line.get("at"))
    return at is not None and stay.start <= at <= stay.end
