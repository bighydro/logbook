"""`logbook lab introductions`: for every person, the first day the record confirms them present at a
stay with the owner, and who else was confirmed present that day — the likely introducer — with the
lines that say so.

One reading of the window (`reading.read`). The people are the confirmed company of the owner's
stays by the with module (SPEC §3.2.5): a timed calendar entry's attendee held at the stay, a
transcript's participant the record resolves, a note's `with <Name>`; never the owner, and never a
proposal (a tagged face, an all-day entry's attendee). Each piece of evidence is dated by its own
line's local day, as `rollup people` dates it. A person's **first day** is the earliest such day in
the window; everyone else confirmed on that day is listed with them: those known from an earlier
day under `introducers`, those also first seen that day under `met_together`, each marked
`same_stay` when the evidence puts them at the same stay as the newcomer.

What this cannot see, stated plainly in `BLIND_SPOTS` and printed with the rows: the record's
first weeks (a person present when the record began was not met then), the people who leave no
confirming line, and the fact that co-presence is a guess at an introduction, not the thing itself.
Nothing is written; no connection is opened."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from .. import present, rollup, stays
from ..reading import Reading, window_json

NEAR_START_DAYS = 30  # a first day this close to the record's first tracked day is the record's beginning
EN_DASH = "\u2013"
MIDDLE_DOT = "\u00b7"

BLIND_SPOTS = (
    "The first day is the first confirming line, not the meeting: anyone present when the record"
    " began, or known for years before it, is first seen on an ordinary day and marked"
    " near_record_start when that day falls in the record's first 30 days.",
    "Only confirmed company counts: a timed calendar entry held at the stay, a transcript participant"
    " the record resolves, a note saying `with <Name>`. A tagged face is proposed, not confirmed; an"
    " all-day entry places nobody; a person met with no such line is invisible until one exists.",
    "A person is seen only at the owner's stays: a day the tracker did not see, or an entry the"
    " record cannot place, confirms nobody there.",
    "The introducer is a guess from co-presence: everyone confirmed that day is listed, the same"
    " stay first; a large meeting lists everyone in it, and nobody is ever named as the cause.",
    "A person under two refs before `people merge` is two people with two first days; a name no"
    " resolution line knows is listed by its spelling, with no person id.",
)


@dataclass
class _Seen:
    """One person's evidence on one local day."""

    person: str | None
    name: str
    stays: dict[str, stays.Segment] = field(default_factory=dict)  # stay id → the stay, first-start first
    sources: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)


Key = tuple[str | None, str]  # (entity id, "") or (None, the name casefolded)


def first_seen(reading: Reading, record_start: str | None = None) -> dict[str, Any]:
    """The JSON-ready report: `window`, `people` (one entry per person, by first day then name) and
    `blind_spots`. `record_start` is the first day the owner's track covers, for the
    `near_record_start` mark; the window's first day when not given."""
    seen = _appearances(reading)
    first_day: dict[Key, str] = {}
    for (key, day), _entry in seen.items():
        first_day[key] = min(first_day.get(key, day), day)
    by_day: dict[str, list[Key]] = {}
    for key, day in first_day.items():
        by_day.setdefault(day, []).append(key)
    start = date.fromisoformat(record_start or reading.first)
    people: list[dict[str, Any]] = []
    for key, day in sorted(first_day.items(), key=lambda kv: (kv[1], seen[(kv[0], kv[1])].name)):
        me = seen[(key, day)]
        stay = next(iter(me.stays.values()))
        others = [(other, seen[(other, day)]) for other in _keys_on(seen, day) if other != key]
        introducers = [
            _companion(entry, first_day[other], me) for other, entry in others if first_day[other] < day
        ]
        met = [_companion(entry, None, me) for other, entry in others if first_day[other] == day]
        introducers.sort(key=lambda c: (not c["same_stay"], c["known_since"] or "", c["name"]))
        met.sort(key=lambda c: (not c["same_stay"], c["name"]))
        people.append(
            {
                "person": me.person,
                "name": me.name,
                "first_day": day,
                "stay": stay.id,
                "where": _where(stay, reading),
                "sources": list(dict.fromkeys(me.sources)),
                "lines": list(dict.fromkeys(me.lines)),
                "near_record_start": date.fromisoformat(day) < start + timedelta(days=NEAR_START_DAYS),
                "introducers": introducers,
                "met_together": met,
            }
        )
    return {"window": window_json(reading), "people": people, "blind_spots": list(BLIND_SPOTS)}


def empty() -> dict[str, Any]:
    return {"window": None, "people": [], "blind_spots": list(BLIND_SPOTS)}


def _appearances(reading: Reading) -> dict[tuple[Key, str], _Seen]:
    """Every confirmed piece of evidence, merged per person and local day."""
    evidence = present.Evidence(reading.lines, reading.tz)
    days_of = {str(line["id"]): reading.day_of(line) for line in reading.lines}
    seen: dict[tuple[Key, str], _Seen] = {}
    for stay in sorted(reading.owner_stays, key=lambda s: s.start):
        stay_day = stay.start.astimezone(reading.tz).date().isoformat()
        found = present.present(stay, evidence.near(stay), reading.identities, reading.places, reading.owner)
        for p in found:
            if p.status != present.CONFIRMED:
                continue
            key: Key = (p.person, "" if p.person else p.name.casefold())
            entry = seen.setdefault((key, days_of.get(p.line, stay_day)), _Seen(p.person, p.name))
            entry.stays.setdefault(stay.id, stay)
            entry.sources.append(p.source)
            entry.lines.append(p.line)
    for entry in seen.values():  # evidence order, as the with module gives it: calendar, transcript, note
        order = {source: i for i, source in enumerate(present.SOURCES)}
        entry.sources.sort(key=lambda s: order.get(s, len(order)))
    return seen


def _keys_on(seen: Mapping[tuple[Key, str], _Seen], day: str) -> list[Key]:
    return [key for (key, d) in seen if d == day]


def _companion(entry: _Seen, known_since: str | None, newcomer: _Seen) -> dict[str, Any]:
    return {
        "person": entry.person,
        "name": entry.name,
        "known_since": known_since,
        "same_stay": not newcomer.stays.keys().isdisjoint(entry.stays.keys()),
        "lines": list(dict.fromkeys(entry.lines)),
    }


def _where(stay: stays.Segment, reading: Reading) -> str:
    if stay.place:
        return stay.place
    if stay.aboard:
        return f"aboard {stay.aboard}"
    if stay.lat is None or stay.lon is None:
        return "somewhere"
    return rollup.unnamed_label(stay.lat, stay.lon, None, reading)


# -- the text -----------------------------------------------------------------------------------------------


def rows(data: dict[str, Any]) -> Iterator[str]:
    """One row per person, first day first; then the blind spots."""
    window = data["window"]
    if window is None:
        yield "introductions: no days"
        return
    people = data["people"]
    head = f"introductions {window['since']} {EN_DASH} {window['until']}"
    yield f"{head}: {_plural(len(people), 'person', 'people')} first seen"
    width = max((len(p["name"]) for p in people), default=0)
    for p in people:
        parts = [f"at {p['where']}", ", ".join(p["sources"])]
        if p["introducers"]:
            parts.append("with " + ", ".join(_introducer_text(c) for c in p["introducers"]))
        if p["met_together"]:
            parts.append("met together: " + ", ".join(_met_text(c) for c in p["met_together"]))
        if not p["introducers"] and not p["met_together"]:
            parts.append("nobody else that day")
        if p["near_record_start"]:
            parts.append("the record had just begun")
        name = p["name"] if p["person"] else f"{p['name']} (unresolved)"
        yield f"  {p['first_day']}  {name:<{width}}  {f' {MIDDLE_DOT} '.join(parts)}"
    yield "blind spots:"
    for sentence in data["blind_spots"]:
        yield f"  - {sentence}"


def _introducer_text(c: dict[str, Any]) -> str:
    where = "" if c["same_stay"] else ", elsewhere that day"
    return f"{c['name']} (known since {c['known_since']}{where})"


def _met_text(c: dict[str, Any]) -> str:
    return c["name"] if c["same_stay"] else f"{c['name']} (elsewhere that day)"


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one}" if n == 1 else f"{n} {many}"
