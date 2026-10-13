"""The People page and one person's page — the People shelf of `logbook serve`.

**The People page** ranks the canonical people heard in a year (default the year of the record's
today, or its last year when the record ended before it), the people `people` reads over that
year: by days together that year, most first, then by the last real contact (later first), then by
name. Only canonical people: a person the record's resolution lines name, never the owner. What a
source saw and the record has not placed is an observed person (`people_review`), shown on the page
only in its review queue, never in the list.

**One person's page** reads the whole record (`people.read`) and composes, for the person:

- the **days together**, counted by year, each day with where and the lines that put them there
  (`people_drift.days_together`);
- the **last real contact** (`people_drift.real_contacts`: a day together, a meeting, an answered
  call, a message in a direct chat) and what it was, in the record's words: where the day was, the
  entry's title, the call's length, which chat; never a word of a message;
- the **promises** open both ways (`people_drift.promises_with`, the rule `people drift` counts by):
  what you owe them, what they owe you, each with the sentence and the line it was read in;
- the **anniversaries** in the coming `ANNIVERSARY_DAYS` days: a day together exactly 1, 2, 3, 5 or
  10 years before one of them (`people_drift.YEARS`, the Day's rule), and the birthday when a
  resolution line carries one;
- the **drift** status (`people_drift.verdict`, at the command's defaults) and why;
- the **places** you have been with them, by days there, each with its days and lines.

A reader: nothing here writes, and every number keeps the lines it rests on."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from ..core import day_start, people, reading
from ..core.chain import Line
from ..core.flights import Airports
from ..core.store import Logbook
from . import people_drift
from . import promises as promise_reader

ANNIVERSARY_DAYS = 30  # the anniversaries a person's page names: today and the 29 days after
YEAR_DIGITS = 4


# -- the list --------------------------------------------------------------------------------------------


def ranked(
    lb: Logbook,
    year: str | None = None,
    now: datetime | None = None,
    airports: Airports | None = None,
) -> dict[str, Any]:
    """The canonical people heard in `year`, most days together first (see the module); `ValueError`
    for a year that is not one. Writes nothing."""
    whole = reading.record_days(lb)
    if whole is None:
        return {"year": None, "years": [], "window": None, "people": []}
    today = today_of(lb, now)
    year = year or min(today, whole[1])[:YEAR_DIGITS]
    if not (len(year) == YEAR_DIGITS and year.isdigit()):
        raise ValueError(f"not a year (YYYY): {year!r}")
    years = [str(y) for y in range(int(whole[0][:4]), int(whole[1][:4]) + 1)]
    first, last = max(f"{year}-01-01", whole[0]), min(f"{year}-12-31", whole[1])
    if last < first:
        return {"year": year, "years": years, "window": None, "people": []}
    report = people.read(lb, first, last, airports)
    contacts = people_drift.real_contacts(lb, report)
    rows: list[dict[str, Any]] = [
        {
            "id": p.entity,
            "name": p.name,
            "days": len(p.days),
            "nights": p.nights,
            "last_real_contact": None if (c := contacts.get(p.entity)) is None else c.to_json(),
            "together": people_drift.days_together(p),
        }
        for p in report.people
    ]
    rows.sort(key=lambda r: (-r["days"], _desc(r["last_real_contact"]), r["name"].casefold()))
    return {"year": year, "years": years, "window": {"since": first, "until": last}, "people": rows}


def _desc(contact: Mapping[str, Any] | None) -> str:
    """A key that sorts later days first, no contact last."""
    if contact is None:
        return "~"
    return "".join(chr(ord("9") - ord(c) + ord("0")) if c.isdigit() else c for c in str(contact["day"]))


def today_of(lb: Logbook, now: datetime | None = None) -> str:
    """The record's today: the current date in its timezone, under its `day_start`."""
    return day_start.of(lb.meta).today(now or datetime.now(UTC)).isoformat()


# -- one person ------------------------------------------------------------------------------------------


def read(
    lb: Logbook,
    name: str,
    now: datetime | None = None,
    airports: Airports | None = None,
) -> dict[str, Any]:
    """One person's page as one JSON-ready object (see the module). `people.PersonError` when the
    name is nobody's, several people's or the owner's; `ValueError` for a record with no days.
    Writes nothing."""
    whole = reading.record_days(lb)
    if whole is None:
        raise ValueError("the record has no days")
    report = people.read(lb, *whole, airports)
    person = people.find(name, report)
    contacts = people_drift.real_contacts(lb, report)
    contact = contacts.get(person.entity)
    verdict = people_drift.verdict(person, contact, people_drift.until_of(report, whole[1]))
    together = people_drift.days_together(person)
    by_year = Counter(d["day"][:YEAR_DIGITS] for d in together)
    owed = people_drift.promises_with(lb, [person]).get(person.entity, [])
    today = today_of(lb, now)
    return {
        "page": "person",
        "id": person.entity,
        "name": person.name,
        "refs": [{"kind": k, "value": v} for k, v in person.refs],
        "birthday": person.birthday,
        "today": today,
        "window": {"since": whole[0], "until": whole[1]},
        "days": len(together),
        "nights": person.nights,
        "years": [
            {"year": y, "days": by_year[y], "together": [d for d in together if d["day"][:4] == y]}
            for y in sorted(by_year, reverse=True)
        ],
        "last_real_contact": None
        if contact is None
        else {**contact.to_json(), "what": _what(lb, contact, together)},
        "promises": {
            "you_owe": [_promise(p) for p, mine in owed if mine],
            "they_owe": [_promise(p) for p, mine in owed if not mine],
        },
        "anniversaries": anniversaries(together, today),
        "drift": {**verdict.to_json(), "text": verdict.text()},
        "places": places(person),
    }


def anniversaries(
    together: Sequence[Mapping[str, Any]], today: str, within: int = ANNIVERSARY_DAYS
) -> list[dict[str, Any]]:
    """The days together exactly `people_drift.YEARS` before one of the `within` days from `today`:
    `on` (the day it falls on), `years`, the `day` together, where, its lines; soonest first, then
    the nearest years."""
    by_day = {str(d["day"]): d for d in together}
    found = []
    start = date.fromisoformat(today)
    for offset in range(within):
        on = (start + timedelta(days=offset)).isoformat()
        for years in people_drift.YEARS:
            then = _years_before(on, years)
            if then is not None and then in by_day:
                day = by_day[then]
                found.append(
                    {
                        "on": on,
                        "years": years,
                        "day": then,
                        "where": day["where"],
                        "lines": list(day["lines"]),
                    }
                )
    return found


def places(person: people.Person) -> list[dict[str, Any]]:
    """The places shared, by days there, most first (`Person.places`), each with its days and the
    lines of them."""
    out = []
    for where, n in person.places:
        days = sorted({s.day for s in person.shared.values() if s.where == where}, reverse=True)
        lines = list(dict.fromkeys(i for s in person.shared.values() if s.where == where for i in s.lines))
        out.append({"where": where, "days": n, "on": days, "lines": lines})
    return out


def _promise(p: promise_reader.Proposal) -> dict[str, Any]:
    return {
        "id": p.id,
        "day": p.day,
        "role": p.role,
        "quote": p.match.quote,
        "due": p.due,
        "kind": p.kind,
        "source": p.source,
        "line": p.line,
    }


def _what(lb: Logbook, contact: people_drift.Contact, together: Sequence[Mapping[str, Any]]) -> str:
    """What the last real contact was, in the record's words and never a message's: the place of a
    day together, a meeting's title (and where it was held), a call's direction and length, the
    chat a message was in and who wrote it."""
    if contact.via == people_drift.TOGETHER:
        where = next((d["where"] for d in together if d["day"] == contact.day), None)
        return f"a day together at {where}" if where else "a day together"
    with lb.index() as idx:
        line = idx.by_id(contact.line)
    if line is None:
        return contact.via
    return describe(line)


def describe(line: Line) -> str:
    """One line of a real contact as the page names it, no word of a message: `Catch-up (Video
    call)`, `spoke in Planning`, `a call, incoming, answered, 10 min`, `a message from them in a
    direct chat (whatsapp)`."""
    payload = line.get("payload") or {}
    kind = line.get("kind")
    if kind == "event":
        title = str(payload.get("title") or "a meeting")
        held = payload.get("location")
        return f"{title} ({held})" if isinstance(held, str) and held else title
    if kind == "transcript":
        return f"spoke in {payload.get('title') or 'a recording'}"
    if kind == "call":
        seconds = payload.get("duration_s")
        length = f", {round(seconds / 60):,} min" if isinstance(seconds, int | float) and seconds else ""
        direction = payload.get("direction")
        return f"a call{f', {direction}' if isinstance(direction, str) else ''}, answered{length}"
    if kind == "message":
        who = "from you" if payload.get("from_me") is True else "from them"
        return f"a message {who} in a direct chat ({line.get('source')})"
    return str(kind)


def _years_before(day: str, years: int) -> str | None:
    d = date.fromisoformat(day)
    try:
        return d.replace(year=d.year - years).isoformat()
    except ValueError:  # 29 February, in a year without one
        return None
