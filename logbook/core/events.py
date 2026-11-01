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
calendars), and `Folded.lines`, every line's id, the kept one's first. Nothing here reads a file.

`all_day` is the readers' own, after `fold`: an entry is all-day when any calendar of its set flags it
so (the kept line, a timed one, may come from a calendar that does not, as Notion's date-only pages and
a calendar's copy of another's birthday do), or when it runs from one midnight to a later one on the
record's clock; such a line is read with `all_day` set, so every reader says `all day` of it and none
`from 00:00 to 00:00+1` (the desk, after the tag). The line in the log is not touched.

`backfilled` is the Day's own, after `fold`: a Notion row seen live and then again by `sync notion
--relations-backfill` is one row. The backfill's `relations` line adds a row's relations to an edit
the record holds already, at that edit, so it is no happening of its own: it folds into the last
other line of its page among the day's lines, whose `Folded.lines` then name it, and whose sources
stay one. A page with no other line on the day keeps it as a row. `show` keeps both lines as rows
(SPEC §3.2.1: one calendar holding an entry twice is two), so `fold` does not do this."""

from __future__ import annotations

import unicodedata
from collections.abc import Container, Mapping, Sequence
from datetime import datetime, time, tzinfo
from typing import Any, NamedTuple

from .chain import Line
from .flights import Airlines, designator
from .stays import instant

SAME_START_S = 60  # two starts less than this apart are one start
IGNORED = frozenset({"schema", "raw_id", "modified_at", "extra", "title", "all_day", "calendar"})
BACKFILL = ("notion", "relations")  # the source and `extra.action` of `sync notion --relations-backfill`


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


def backfilled(
    lines: Sequence[Line], stands_for: Mapping[str, Folded], retracted: Container[str] = ()
) -> tuple[list[Line], dict[str, Folded]]:
    """`fold`'s result (one day's lines and what each kept line stands for) with every Notion
    `relations` line (`BACKFILL`) dropped into the last other line of its page among them: that
    line then stands for it too, its own lines first and the sources unchanged. A retracted line is
    never folded and folds nothing; a `relations` line whose page has no other line here stays."""
    live = [line for line in lines if _notion_page(line) is not None and str(line["id"]) not in retracted]
    last = {_notion_page(line): line for line in live if _action(line) != BACKFILL[1]}  # the page's last
    out = dict(stands_for)
    dropped: set[str] = set()
    for line in live:
        kept = last.get(_notion_page(line)) if _action(line) == BACKFILL[1] else None
        if kept is None:
            continue
        id_, into = str(line["id"]), str(kept["id"])
        mine = out.pop(id_, None)
        theirs = out.get(into) or Folded([str(kept.get("source"))], [into])
        also = mine.lines if mine is not None else [id_]
        sources = [*theirs.sources, *(s for s in (mine.sources if mine else []) if s not in theirs.sources)]
        out[into] = Folded(sources, [*theirs.lines, *also])
        dropped.add(id_)
    return [line for line in lines if str(line["id"]) not in dropped], out


def _notion_page(line: Line) -> str | None:
    """The Notion page id of an event line the Notion adapter wrote, else None."""
    if line.get("kind") != "event" or line.get("source") != BACKFILL[0]:
        return None
    page = _extra(line).get("page")
    id_ = page.get("id") if isinstance(page, dict) else None
    return str(id_) if id_ else None


def _action(line: Line) -> str | None:
    action = _extra(line).get("action")
    return str(action) if action is not None else None


def _extra(line: Line) -> dict[str, Any]:
    extra = _payload(line).get("extra")
    return extra if isinstance(extra, dict) else {}


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


def all_day(
    folded: Sequence[Line], stands_for: Mapping[str, Folded], lines: Sequence[Line], tz: tzinfo
) -> list[Line]:
    """`folded` with each calendar entry that is all-day read as one (`all_day` set in a copy of its
    payload): one a line of its set flags all-day, or one from a midnight to a later midnight in `tz`.
    `lines` are the lines `fold` was given; every other line is returned as it is."""
    flagged = {str(line["id"]) for line in lines if line.get("kind") == "event" and _all_day(line)}
    out: list[Line] = []
    for line in folded:
        if line.get("kind") == "event" and not _all_day(line):
            kept = stands_for.get(str(line["id"]))
            ids = set(kept.lines) if kept is not None else {str(line["id"])}
            if ids & flagged or whole_days(line, tz):
                line = {**line, "payload": {**_payload(line), "all_day": True}}
        out.append(line)
    return out


def whole_days(line: Line, tz: tzinfo) -> bool:
    """Whether `line` runs from a midnight to a later midnight on the clock of `tz`: a day or more, whole."""
    start, end = instant(line.get("at")), instant(line.get("end"))
    if start is None or end is None or end <= start:
        return False
    return all(t.astimezone(tz).time() == time.min for t in (start, end))


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
