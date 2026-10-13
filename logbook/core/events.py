"""Calendar entries several sources carry: `fold`.

Two calendars that hold the same entry — a flight in the phone's calendar and in a subscribed
.ics, in two languages — are N `event/v1` lines for one event. `fold` keeps one line of each
such set and names the sources it stands for, so `logbook show` and `logbook day` print one
row, `×N sources`, instead of N. It folds at read time only: every line stays in the log as it
was written. Two lines are one event when they come from different calendars, start less than a
minute apart, last as long as each other or one of them is all-day, and either name the same
flight (`flights.designator` on the title: `Flight to Zürich (XY 561)`, `Flug XY561 nach Zürich`)
or carry the same title, case, accents and whitespace aside (`Standup` and `standup`, `Zürich` and
`Zurich`). A calendar is the line's source and its `calendar` id: `gcal` writes its lines as
`ics`, the file adapter's, so a Google calendar and a subscribed .ics are told apart by the
calendar they name. The fold happens only across calendars: one calendar holding an entry twice
is two entries, though a repeat from one calendar folds into a set another calendar already makes.

The line kept is the richest of the set: a timed entry before an all-day one, then the one whose
payload fills the most fields (location, attendees, notes, organizer, status), then the earliest
in the order given. The others are named in its evidence: `Folded.sources`, its own source first,
then the others in evidence order (`ics (Work)` when one source brings the entry from two of its
calendars), and `Folded.lines`, every line's id, the kept one's first. Nothing here reads a file."""

from __future__ import annotations

import unicodedata
from collections.abc import Container, Sequence
from datetime import datetime
from typing import Any, NamedTuple

from .chain import Line
from .flights import Airlines, designator
from .stays import instant

SAME_START_S = 60  # two starts less than this apart are one start
IGNORED = frozenset({"schema", "raw_id", "modified_at", "extra", "title", "all_day", "calendar"})


class Folded(NamedTuple):
    """What one kept event line stands for: the sources, the ids of every line, its own first."""

    sources: list[str]
    lines: list[str]


def fold(
    lines: Sequence[Line], airlines: Airlines, retracted: Container[str] = ()
) -> tuple[list[Line], dict[str, Folded]]:
    """The lines in their order with every event line that repeats another from another calendar
    dropped (every other kind kept in place), and, for each event kept in the place of two or more
    calendars' lines, keyed by its id, the sources it stands for and the ids of every line it
    stands for, its own first. A retracted line (`retracted`, ids) is never folded and
    folds nothing."""
    by_minute: dict[int | None, list[list[Line]]] = {}
    clusters: list[list[Line]] = []
    for line in lines:
        if line.get("kind") != "event" or str(line["id"]) in retracted:
            continue
        at = instant(line.get("at"))
        minute = None if at is None else int(at.timestamp()) // SAME_START_S
        near = [None] if minute is None else [minute - 1, minute, minute + 1]
        found = next(
            (
                cluster
                for key in near
                for cluster in by_minute.get(key, [])
                if _same_event(cluster[0], line, airlines)
            ),
            None,
        )
        if found is not None:
            found.append(line)
            continue
        cluster = [line]
        clusters.append(cluster)
        by_minute.setdefault(minute, []).append(cluster)
    dropped: set[str] = set()
    folded: dict[str, Folded] = {}
    for cluster in clusters:
        if len({_calendar(line) for line in cluster}) < 2:
            continue
        _, _, kept = max((_richness(line), -n, line) for n, line in enumerate(cluster))
        ordered = [kept, *(line for line in cluster if line is not kept)]
        folded[str(kept["id"])] = Folded(_sources(ordered), [str(line["id"]) for line in ordered])
        dropped.update(str(line["id"]) for line in cluster if line is not kept)
    return [line for line in lines if str(line["id"]) not in dropped], folded


def _same_event(a: Line, b: Line, airlines: Airlines) -> bool:
    start_a, start_b = instant(a.get("at")), instant(b.get("at"))
    if (start_a is None) != (start_b is None):
        return False
    if start_a is not None and start_b is not None:
        if abs((start_a - start_b).total_seconds()) >= SAME_START_S:
            return False
        if not (_all_day(a) or _all_day(b)) and _duration(a, start_a) != _duration(b, start_b):
            return False
    title_a, title_b = (str(_payload(line).get("title") or "") for line in (a, b))
    if _normal(title_a) == _normal(title_b):
        return True
    flight = designator(title_a, airlines)
    return flight is not None and flight == designator(title_b, airlines)


def _payload(line: Line) -> dict[str, Any]:
    payload = line.get("payload")
    return payload if isinstance(payload, dict) else {}


def _all_day(line: Line) -> bool:
    return _payload(line).get("all_day") is True


def _duration(line: Line, start: datetime) -> float | None:
    end = instant(line.get("end"))
    return None if end is None else (end - start).total_seconds()


def _calendar(line: Line) -> tuple[str, str | None]:
    """The calendar a line came from: its source and the calendar id the payload names."""
    calendar = _payload(line).get("calendar")
    named = calendar.get("id") if isinstance(calendar, dict) else None
    return str(line.get("source")), None if named is None else str(named)


def _sources(cluster: Sequence[Line]) -> list[str]:
    """The sources a set stands for, the kept line's first, then in evidence order; a source that
    brings the entry from two of its calendars is named once per calendar, `ics (Work)`."""
    calendars: dict[str, set[str | None]] = {}
    for line in cluster:
        source, named = _calendar(line)
        calendars.setdefault(source, set()).add(named)
    out: list[str] = []
    for line in cluster:
        source, named = _calendar(line)
        if len(calendars[source]) < 2:
            label = source
        else:
            calendar = _payload(line).get("calendar")
            name = calendar.get("name") if isinstance(calendar, dict) else None
            label = f"{source} ({name or named or 'no calendar'})"
        if label not in out:
            out.append(label)
    return out


def _richness(line: Line) -> tuple[int, int, int]:
    """A timed entry before an all-day one, then the payload fields it fills, then its attendees."""
    payload = _payload(line)
    filled = sum(
        1 for key, value in payload.items() if key not in IGNORED and value not in (None, "", [], {})
    )
    attendees = payload.get("attendees")
    return (0 if _all_day(line) else 1, filled, len(attendees) if isinstance(attendees, list) else 0)


def _normal(title: str) -> str:
    """The title with accents stripped (NFKD, the combining marks dropped), case folded and
    whitespace collapsed, so `Zürich` and `Zurich`, `Café  Olsen` and `cafe olsen` compare equal."""
    bare = "".join(c for c in unicodedata.normalize("NFKD", title) if not unicodedata.combining(c))
    return " ".join(bare.split()).casefold()
