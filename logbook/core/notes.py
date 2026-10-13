"""A note on a day: one `note/v1` line (RFC 0010) in the owner's words, put on a given local day, its
kind in the profile's `labels`. The one note path for a write that names a day: the MCP tool
`note_day` (ADR 0022), `logbook day reflect` and a journey's name (`logbook.contrib.journeys.name`)
append through `write`, and nowhere else.

The line is what RFC 0010 says a note is: kind `note`, tier 2 whoever writes it, the text as given
and never filtered, the kind as the one label (`note`, `proposal` or `reflection` through the door;
`reflection` and `delegation` from `day reflect`, `name` from `add --trip` and the Journeys page), and
`extra` when the writer has something to add. `source` is the writer's: `mcp` through the door,
`reflect` from the command, `manual` for a journey's name. `at` is checked by the
rules of `day sign --at` (`signing.moment`: an RFC 3339 moment with an offset or Z, not ahead of this
clock, not before the day) and must fall on the day as the record defines it, its zone and its
`day_start` (RFC 0036), since a note on a day is written during it; without it the note is now when
the day is today, else at the day's last minute: 23:59, or 05:59 the next morning when the day
begins at 06:00.

The readers ask `standing` for the notes of a day with a label, retracted ones left out, in the
day's order; the Day shows the latest reflection apart from the timeline (`logbook.core.day`)."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from . import day_start, signing
from .chain import Line
from .export import parse_day
from .store import Logbook, now_utc, utc

KIND = "note"
SCHEMA = "note/v1"
TIER = 2  # RFC 0010: a note/v1 line is tier 2, whoever writes it
NOTE, PROPOSAL, REFLECTION, DELEGATION = "note", "proposal", "reflection", "delegation"
NAME = "name"  # the captain names a journey (ADR 0019): `add --trip`, the Journeys page


class NoteError(ValueError):
    """A note the record refuses; the message says why and nothing is written."""


def moment(day: str, tz: str, at: str | None, today: str, days: day_start.DayStart | None = None) -> str:
    """When a note on `day` is written, in UTC: `at` checked by `signing.moment` and on the day as
    `days` defines it (the record's `day_start`; None is midnight in `tz`); without it, now when `day`
    is `today`, else the day's last minute: 23:59, or 05:59 the next morning when the day begins at
    06:00."""
    if days is None:
        days = day_start.DayStart(ZoneInfo(tz))
    if at is not None:
        stamp = signing.moment(at, day, tz)
        if days.day_of(stamp) != day:
            raise NoteError(f"at {at.strip()} is not on {day} in {tz}; a note on a day is written during it")
        return stamp
    if day == today:
        return now_utc()
    return utc((days.span(day)[1] - timedelta(minutes=1)).isoformat())


def today_in(days: day_start.DayStart) -> str:
    """The day the owner is in now under `days`, the record's zone and `day_start`, `YYYY-MM-DD`."""
    return days.today(datetime.now(UTC)).isoformat()


def write(
    lb: Logbook,
    day: str,
    text: str,
    label: str,
    source: str,
    at: str | None = None,
    today: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> Line:
    """One note/v1 line on `day` through `Logbook.append`: `text` as given, `label` its one label,
    `extra` when given, tier 2, at `moment(day, tz, at, today)`; `today` is the record's today unless
    the caller knows better."""
    day = parse_day(day).isoformat()
    tz = str(lb.meta["timezone"])
    days = day_start.of(lb.meta)
    stamp = moment(day, tz, at, today if today is not None else today_in(days), days)
    payload: dict[str, Any] = {"schema": SCHEMA, "text": text, "labels": [label]}
    if extra:
        payload["extra"] = dict(extra)
    return lb.append(at=stamp, source=source, kind=KIND, tier=TIER, payload=payload)


def labelled(line: Line, label: str) -> bool:
    """Whether `line` is a note/v1 line carrying `label` among its labels."""
    payload = line.get("payload") or {}
    labels = payload.get("labels")
    return (
        line.get("kind") == KIND
        and payload.get("schema") == SCHEMA
        and isinstance(labels, list)
        and label in labels
    )


def standing(lines: Iterable[Line], label: str, retracted: Collection[str] = ()) -> list[Line]:
    """The notes among `lines` that carry `label` and are not retracted, in the day's order: by the
    instant of `at`, then `seq`."""
    found = [line for line in lines if labelled(line, label) and str(line["id"]) not in retracted]
    found.sort(key=lambda line: (_instant(str(line["at"])), int(line["seq"])))
    return found


def _instant(stamp: str) -> datetime:
    parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
