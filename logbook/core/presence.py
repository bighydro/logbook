"""With: who was there when the record could not see — `logbook with DAY NAME [NAME…] [--at HH:MM]`,
and the "with…" field of the Day page, which calls the same function.

The owner's word is the one source of company a calendar, a recording or a photo cannot supply: the
friend who came by, the brother on the boat. It is written as the profile `people` already reads
for "with" (SPEC §3.2.5 rule 3), one `note/v1` line per person through `notes.write`, the one note
path that names a day: the text `with <label>`, the person's canonical label as the resolution lines
give it, the label `with` among the note's labels so a reader can tell the owner's statement from a
note that happens to say "with", and the person's entity id under `extra.person`. Tier 2, as every
note is (RFC 0010), `source` `manual`. No new profile.

A name is the person `people NAME` would open (`people.find`): a label (case aside), a unique first or
last name, an entity id, or a ref the record resolves. A name the record does not place — nobody, or
several people, or the owner — refuses the whole statement with the people-review hint, and nothing
is written. Two names for one person are one line.

When: `--at HH:MM` is that clock on the day as the record defines it (its zone and `day_start`, RFC
0036: under `06:00`, `02:00` is the next calendar date), so the line sits in the stay the owner was
at and the Day lists the person there. Without it, now when the day is today, else noon: a statement
about the day with no hour is put where a day's company is usually kept, and the Day's `with` row
lists the person whichever stay it falls in. A day that has not begun, or a clock still to come, is
refused: with states who was there. A person already stated on the day (at that minute, with
`--at`) is not stated twice.

Everything is read and appended under one hold of the writer lock, the head read again before the
first append (`HeadMoved` and nothing written when it moved), as `day sign` does."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from . import day_start, notes, people
from .chain import Line
from .export import parse_day
from .store import HeadMoved, Logbook, retractions

LABEL = "with"  # the note's label: the owner's statement of company
SOURCE = "manual"  # the owner's word, from the command line or through the page
NOON = time(12, 0)
CLOCK = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
SKEW = timedelta(minutes=5)  # a clock this far ahead of this machine's is still now
REVIEW_HINT = (
    "`logbook people review` places the people the record has seen under the ones it names,"
    " and `logbook people merge` joins two names for one person"
)


class WithError(ValueError):
    """A statement the record refuses; the message says why and nothing is written."""


@dataclass(frozen=True)
class Stated:
    """One person stated present: the canonical person, the label, and the line, when written."""

    person: str
    name: str
    line: Line | None  # None: stated already on the day, nothing written

    def to_json(self) -> dict[str, Any]:
        return {
            "person": self.person,
            "name": self.name,
            "line": None if self.line is None else self.line["id"],
        }


def resolve(names: Iterable[str], report: people.Report) -> list[people.Person]:
    """The canonical person each name means, each once, in the order given. `WithError` naming the
    first name that is nobody, several people or the owner, with the people-review hint."""
    found: dict[str, people.Person] = {}
    for name in names:
        text = " ".join(name.split())
        if not text:
            continue
        try:
            person = people.find(text, report)
        except people.PersonError as e:
            reason = str(e)
            if "is the owner" in reason:
                reason = f"{text!r} is you; the owner is never their own company"
            raise WithError(f"{reason}; nothing was written. {REVIEW_HINT}.") from e
        found.setdefault(person.entity, person)
    if not found:
        raise WithError("name at least one person: `logbook with DAY NAME [NAME…]`")
    return list(found.values())


def moment(day: str, at: str | None, days: day_start.DayStart, now: datetime) -> str:
    """When the statement is put, in UTC: `at`, `HH:MM`, on `day` as `days` defines it; else now when
    `day` is today, else noon. `WithError` for a clock that is not one, a day that has not begun or a
    clock still to come."""
    d = parse_day(day)
    today = days.today(now)
    if d > today:
        raise WithError(f"{day} has not begun; with states who was there")
    if at is None:
        if d == today:
            return _stamp(now)
        clock = NOON
    else:
        match = CLOCK.match(at.strip())
        if match is None:
            raise WithError(f"--at {at.strip()!r} is not a clock; give HH:MM, e.g. 19:30")
        clock = time(int(match.group(1)), int(match.group(2)))
    local = _on_day(d, clock, days)
    if local > now + SKEW:
        raise WithError(f"--at {at} on {day} is still to come; with states who was there")
    return _stamp(local)


def _stamp(instant: datetime) -> str:
    """An aware datetime as a line's `at`: UTC, to the second, with the literal Z."""
    return instant.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _on_day(d: date, clock: time, days: day_start.DayStart) -> datetime:
    """`clock` on the day `d` as the record defines it: its date, or the next when the clock is
    before the record's `day_start`."""
    local = datetime.combine(d, clock, tzinfo=days.zone)
    if days.day(local) != d:
        local = datetime.combine(d + timedelta(days=1), clock, tzinfo=days.zone)
    return local


def stated(lines: Iterable[Line], retracted: Iterable[str] = ()) -> list[Line]:
    """The standing statements of company among `lines` (a day's): the `note/v1` lines labelled
    `with`, not retracted, in the day's order."""
    return notes.standing(lines, LABEL, frozenset(retracted))


def person_of(line: Line) -> str | None:
    """The canonical person a statement names (`extra.person`), else None."""
    extra = (line.get("payload") or {}).get("extra")
    found = extra.get("person") if isinstance(extra, dict) else None
    return found if isinstance(found, str) and found else None


def name_of(line: Line) -> str:
    """The person's label as the statement wrote it: the text after `with `."""
    text = str((line.get("payload") or {}).get("text") or "")
    return text.removeprefix(f"{LABEL} ").strip() or text


def text_of(label: str) -> str:
    """The statement's text: what SPEC §3.2.5 rule 3 reads as company."""
    return f"{LABEL} {label}"


def state(
    lb: Logbook, day: str, names: Sequence[str], at: str | None = None, now: datetime | None = None
) -> list[Stated]:
    """State the people `names` present on `day`: one `note/v1` line per canonical person, at
    `moment`, through `notes.write`, under the writer lock with the head read again before the first
    append. A person already stated on the day (at that moment, given `at`) is listed with no line.
    `WithError` for a name, a day or a clock the record refuses; nothing is written then."""
    day = parse_day(day).isoformat()
    clock = now if now is not None else datetime.now(UTC)
    with lb.writer():
        meta = lb.meta
        days = day_start.of(meta)
        stamp = moment(day, at, days, clock)
        report = people.directory(lb)
        persons = resolve(names, report)
        with lb.index() as idx:
            retracted = retractions(idx.retractions())
            earlier = stated(idx.day(day), retracted)
        already = {
            p
            for line in earlier
            if (p := person_of(line)) is not None and (at is None or line["at"] == stamp)
        }
        if lb.meta["head"] != meta["head"]:
            raise HeadMoved(
                f"the record's head moved from seq {meta['seq']} to seq {lb.meta['seq']} while {day} was"
                " read; nothing was written"
            )
        today = days.today(clock).isoformat()
        out = []
        for person in persons:
            if person.entity in already:
                out.append(Stated(person.entity, person.name, None))
                continue
            line = notes.write(
                lb,
                day,
                text_of(person.name),
                LABEL,
                SOURCE,
                at=stamp,
                today=today,
                extra={"person": person.entity},
            )
            out.append(Stated(person.entity, person.name, line))
    return out
