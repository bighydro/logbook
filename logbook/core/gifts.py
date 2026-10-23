"""Gifts: what the owner gave and was given — `logbook add gift DAY NAME WHAT [--received]`, read back
by `logbook people gifts [NAME]` (RFC 0043 §11, §12: "the gift act, a note labelled `gift`, given or
received").

A gift is one `note/v1` line through `notes.write`, the one note path that names a day, as the
statement of company is (`presence`): the thing in the owner's words as the text, given and never
filtered; the label `gift`; the person under `extra.recipient` when the owner gave it and under
`extra.giver` when the owner received it, the canonical entity id as the record's resolution lines
give it. Tier 2, as every note is (RFC 0010); `source` `manual`. No new profile.

A name is the person `people NAME` would open (`people.find`): a label (case aside), a unique first or
last name, an entity id, or a ref the record resolves, its whitespace normalised (runs collapsed, ends
stripped: `normal`). A name that is nobody, several people or the owner is refused in one sentence,
and nothing is written. The note is put on the day as every note on a past day is (`notes.moment`:
its last minute; now when the day is today); a day that has not begun is refused. The same gift said
twice on one day, the same person, the same way and the same words (their whitespace normalised), is
one line; the text written is the words as given. The day is read and the line appended under one
hold of the writer lock, the head read again before the append (`HeadMoved` and nothing written when
it moved).

`gifts` lists them both ways, retracted ones left out, in the day's order: every gift, or one
person's (`person`, a name as above), in a window of local days when given. `counts` is the one line
a person page will print under the person's name, never beside it (`3 given, 1 received`), and `said`
a gift as the commands say it."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from . import day_start, notes, people
from .chain import Line
from .export import parse_day
from .store import HeadMoved, Logbook, retractions

LABEL = "gift"  # the note's label
SOURCE = "manual"  # the owner's word
GIVEN, RECEIVED = "given", "received"
RECIPIENT, GIVER = "recipient", "giver"  # the `extra` key that names the person, by direction
KEYS = {GIVEN: RECIPIENT, RECEIVED: GIVER}


class GiftError(ValueError):
    """A gift the record refuses, or a name it cannot place; the message says why in one sentence."""


@dataclass(frozen=True)
class Gift:
    """One gift as the record holds it: the day, which way, the person and their label, the words."""

    day: str
    direction: str  # GIVEN or RECEIVED
    person: str
    name: str
    what: str
    line: Line
    written: bool = True  # False: said on the day already, nothing written

    def to_json(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "direction": self.direction,
            "person": self.person,
            "name": self.name,
            "what": self.what,
            "line": self.line["id"],
        }


def find(name: str, report: people.Report, writing: bool = False) -> people.Person:
    """The canonical person `name` means, its whitespace normalised; `GiftError` in one sentence when
    it is nobody, several people or the owner (ending `nothing was written` when `writing`)."""
    text = normal(name)
    try:
        return people.find(text, report)
    except people.PersonError as e:
        reason = str(e)
        if "is the owner" in reason:
            reason = f"{text!r} is you, and a gift is given to someone or received from them"
        raise GiftError(f"{reason}; nothing was written" if writing else reason) from e


def whose(lb: Logbook, name: str) -> people.Person:
    """The person `name` means in this record, as `gifts` reads them; `GiftError` as `find`."""
    return find(name, people.directory(lb))


def give(
    lb: Logbook, day: str, name: str, what: str, received: bool = False, now: datetime | None = None
) -> Gift:
    """Write one gift on `day`: `what` given to the person `name` names, or received from them. A
    gift said on the day already is returned with `written` False. `GiftError` for a name, a day or
    words the record refuses; nothing is written then."""
    day = parse_day(day).isoformat()
    if not what.strip():
        raise GiftError("say what the gift was, in your words; nothing was written")
    direction = RECEIVED if received else GIVEN
    clock = now if now is not None else datetime.now(UTC)
    with lb.writer():
        meta = lb.meta
        days = day_start.of(meta)
        today = days.today(clock).isoformat()
        if day > today:
            raise GiftError(f"{day} has not begun, and a gift is written on the day it changed hands")
        report = people.directory(lb)
        person = find(name, report, writing=True)
        with lb.index() as idx:
            retracted = retractions(idx.retractions())
            earlier = notes.standing(idx.day(day), LABEL, retracted)
        for line in earlier:
            if _who(line) == (direction, person.entity) and normal(_text(line)) == normal(what):
                return Gift(day, direction, person.entity, person.name, what, line, written=False)
        if lb.meta["head"] != meta["head"]:
            raise HeadMoved(
                f"the record's head moved from seq {meta['seq']} to seq {lb.meta['seq']} while {day} was"
                " read; nothing was written"
            )
        line = notes.write(lb, day, what, LABEL, SOURCE, today=today, extra={KEYS[direction]: person.entity})
    return Gift(day, direction, person.entity, person.name, what, line)


def gifts(
    lb: Logbook,
    person: str | people.Person | None = None,
    window: tuple[str, str] | None = None,
    tiers: Sequence[int] | None = None,
) -> list[Gift]:
    """Every standing gift, given and received, in the day's order: one person's when `person` (a
    name, `GiftError` when the record cannot place it, or the person `whose` found), the local days
    [first, last] of `window` when given. Through a gate (`tiers`) without tier 2, none: every note
    is tier 2. The notes are streamed from the index, a thousand at a time, and only the gifts kept."""
    first, last = (
        (parse_day(window[0]).isoformat(), parse_day(window[1]).isoformat()) if window else (None, None)
    )
    report = people.directory(lb)
    if isinstance(person, str):
        person = find(person, report)
    wanted = person.entity if person is not None else None
    if tiers is not None and notes.TIER not in tiers:
        return []
    days = day_start.of(lb.meta)
    with lb.index() as idx:
        retracted = retractions(idx.retractions())
        found = notes.standing(idx.stream(notes.KIND, first, last), LABEL, retracted)
    out: list[Gift] = []
    for line in found:
        who = _who(line)
        if who is None or (wanted is not None and who[1] != wanted):
            continue
        direction, entity = who
        known = report.known.get(entity)
        day = days.day_of(str(line["at"]))
        out.append(Gift(day, direction, entity, known.name if known else entity, _text(line), line))
    out.sort(key=lambda g: g.day)  # stable: the day's order within a day
    return out


def normal(text: str) -> str:
    """`text` with its whitespace normalised: every run of it one space, none at either end."""
    return " ".join(text.split())


def said(g: Gift) -> str:
    """`given to Per Hansen: a book on knots`, `received from Ola Nordmann: cloudberry jam`."""
    way = f"given to {g.name}" if g.direction == GIVEN else f"received from {g.name}"
    return f"{way}: {g.what}"


def counts(found: Iterable[Gift]) -> str:
    """`3 given, 1 received`: the line a person page prints under the person's name, with
    `logbook people gifts NAME`."""
    found = list(found)
    given = sum(1 for g in found if g.direction == GIVEN)
    return f"{given} given, {len(found) - given} received"


def _who(line: Line) -> tuple[str, str] | None:
    """(direction, person) a gift note names: `extra.recipient` given, `extra.giver` received; None
    when it names neither, or both."""
    extra = (line.get("payload") or {}).get("extra")
    if not isinstance(extra, dict):
        return None
    found = [
        (direction, value)
        for direction, key in KEYS.items()
        if isinstance(value := extra.get(key), str) and value
    ]
    return found[0] if len(found) == 1 else None


def _text(line: Line) -> str:
    text = (line.get("payload") or {}).get("text")
    return text if isinstance(text, str) else ""
