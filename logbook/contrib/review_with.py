"""Who was there, read: the review-with queue of a stretch, and your people in a city (RFC 0043 §11,
*Who was there*, and §12, *On a journey day*), as readers and a command line, no page.

**The queue** (`read`): for a journey (`trip:<first>:<last>`, or a day of one), an ISO week
(`YYYY-Www`) or a stretch of local days (at most `who_was_there.MAX_DAYS`), every person the with
module (`logbook.core.present`) puts at one of the owner's stays of it, asked once for the whole
stretch rather than once a stay. The evidence is the with module's, each piece on the day it lies on:

- **faces** on photos, only from the owner's own camera (`who_was_there.own_camera`): a photo received
  in a chat, by AirDrop or through a shared album never proposes anyone;
- **calendar invitees**, the entries held at the stay: *invited to 'Lofoten crew'*;
- **the voices and participants of a recording**: *spoke in 2 calls*; of a meeting note-taker's
  transcript (Granola, Meet), whose attendees are kept as its participants: *in the meeting notes of
  'Boat plans'*.

A day the owner already answered is not asked again: a `with` note naming the person on that day (the
owner's word), or a note at the stay that says *with* them. A person the owner said `not-with` for a
day is not asked for it; a person who lives with the owner (`lives-with`) is not asked for a home
stay (`stays.is_home`), and away from home their faces propose as anyone's do. A name the record does
not place is not a row: it is counted, for `people review`.

Per person: the name, the evidence in words (*faces on 41 photos across 7 days · spoke in 2 calls ·
invited to 'Lofoten crew'*), the days the evidence lies on, and the lines. Ordered strongest first
(the most days, then the most evidence, then the name), at most `SHOWN`, the rest counted. No number
stands beside a name: the order is the only rank, and the counts are in the sentence of the evidence.

**The answers** (`answer`) are the acts of `who_was_there`: *whole stretch* (`--accept NAME`), one
`with` note per day of the stretch that has begun, at its longest stay; *some days* (`--accept NAME
--days D,D`); *not with me* (`--not NAME`), one `not-with` note for the stretch. Every name and day
is checked before the first line is written, under one hold of the writer lock.

**Your people in a city** (`people_in_city`): the people the record places in a city, by the owner's
`lives-in` note (the latest of each person). No contacts import keeps a city today (the iOS and
Google contacts and WhatsApp's keep names, numbers and addresses only), so a `lives-in` note is the
only source; and, for a journey, whether each was **seen** on it: confirmed by the with module at a
stay of it, or stated with the owner on one of its days. Names and *seen* / *not yet*, never a count
beside a name.

Cost: one reading of the stretch (`reading.read`, one sweep of its days through the index; a journey's
is the Trip's own, `trip_page.locate`), the with module once per stay, and one sweep of the owner's
manual notes for the relations (`who_was_there.relations`). Nothing is written by a reader, and
nothing is fetched."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..core import people, presence, present, reading, stays
from ..core.chain import Line
from ..core.export import parse_day
from ..core.flights import Airports
from ..core.reading import Reading
from ..core.store import Logbook
from . import trip_page, week_paper
from . import who_was_there as acts
from .who_was_there import CompanyError

SHOWN = 10  # the people a queue lists; the rest are counted
TITLES = 2  # the titles named in a sentence of evidence; the rest are counted
MEETING_PROVIDERS = frozenset({"granola", "meet"})  # a meeting note-taker's transcripts
EN_DASH = "\N{EN DASH}"
ANSWERS = "--accept NAME (every day of it) · --accept NAME --days D,D · --not NAME"


@dataclass(frozen=True)
class Stretch:
    """The days a queue asks about: from `first` to `last`, and what named them."""

    first: str
    last: str
    journey: str | None = None
    week: str | None = None

    @property
    def days(self) -> list[str]:
        return acts.days_of(self.first, self.last)

    def to_json(self) -> dict[str, Any]:
        return {
            "from": self.first,
            "to": self.last,
            "journey": self.journey,
            "week": self.week,
            "days": self.days,
        }

    def words(self) -> str:
        span = self.first if self.first == self.last else f"{self.first} {EN_DASH} {self.last}"
        named = f" (journey {self.journey})" if self.journey else f" (week {self.week})" if self.week else ""
        return f"{span}{named}"


@dataclass(frozen=True)
class Piece:
    """One piece of evidence: its kind (`PHOTO`, `CALL`, `MEETING`, `INVITE`), the day it lies on, and
    the title of the entry or the recording it came from."""

    kind: str
    day: str
    title: str


PHOTO, CALL, MEETING, INVITE = "photo", "call", "meeting", "invite"


@dataclass
class Ask:
    """One person of the queue: the evidence of the stretch, each piece by its line, in the order seen."""

    person: str
    name: str
    pieces: dict[str, Piece] = field(default_factory=dict)

    @property
    def days(self) -> set[str]:
        return {piece.day for piece in self.pieces.values()}

    def of(self, kind: str) -> list[Piece]:
        return [piece for piece in self.pieces.values() if piece.kind == kind]

    def strength(self) -> tuple[int, int, str]:
        return (-len(self.days), -len(self.pieces), self.name.casefold())

    def words(self) -> str:
        """The evidence in one sentence: *faces on 41 photos across 7 days · spoke in 2 calls ·
        invited to 'Lofoten crew'*."""
        parts = []
        photos, calls = self.of(PHOTO), self.of(CALL)
        if photos:
            n, d = len(photos), len({piece.day for piece in photos})
            where = "on one day" if d == 1 else f"across {d} days"
            parts.append(f"faces on {n} {'photo' if n == 1 else 'photos'} {where}")
        if calls:
            parts.append(f"spoke in {len(calls)} {'call' if len(calls) == 1 else 'calls'}")
        if meetings := self.of(MEETING):
            parts.append(f"in the meeting notes of {_titles(piece.title for piece in meetings)}")
        if invites := self.of(INVITE):
            parts.append(f"invited to {_titles(piece.title for piece in invites)}")
        return " · ".join(parts)

    def without(self, answered: set[str]) -> Ask:
        """The ask with the evidence of the days in `answered` left out."""
        kept = {line: piece for line, piece in self.pieces.items() if piece.day not in answered}
        return Ask(self.person, self.name, kept)

    def to_json(self) -> dict[str, Any]:
        return {
            "person": self.person,
            "name": self.name,
            "evidence": self.words(),
            "days": sorted(self.days),
            "lines": list(self.pieces),
        }


@dataclass(frozen=True)
class Queue:
    """A stretch's queue: the people shown, strongest first, how many more, how many not placed."""

    stretch: Stretch
    people: list[Ask]
    more: int
    unplaced: int

    def to_json(self) -> dict[str, Any]:
        return {
            "stretch": self.stretch.to_json(),
            "people": [ask.to_json() for ask in self.people],
            "more": self.more,
            "unplaced": self.unplaced,
        }


def _titles(found: Iterable[str]) -> str:
    titles = list(dict.fromkeys(found))
    quoted = [f"'{t}'" for t in titles[:TITLES]]
    rest = len(titles) - TITLES
    if rest > 0:
        return f"{', '.join(quoted)} and {rest} more"
    return " and ".join(quoted)


# -- the stretch -------------------------------------------------------------------------------------------


def stretch_of(
    lb: Logbook,
    journey: str | None = None,
    week: str | None = None,
    first: str | None = None,
    last: str | None = None,
    airports: Airports | None = None,
    read_it: bool = True,
) -> tuple[Stretch, Reading | None]:
    """The stretch one of `journey`, `week` or `first`/`last` names, and its reading (a journey's is
    the one it was found in; with `read_it` False, a week's or a stretch's is not read, None).
    `CompanyError` when none or more than one is given, or the stretch is longer than `MAX_DAYS`;
    `ValueError` as the journey's reader raises it."""
    given = [
        x for x in (journey, week, first if first is not None or last is not None else None) if x is not None
    ]
    if len(given) != 1:
        raise CompanyError("say one of --journey ID, --week YYYY-Www or --from D1 --to D2")
    airports = airports or Airports.load()
    if journey is not None:
        rd, trip = trip_page.locate(lb, trip_page.parse_ref(journey), airports)
        stretch = Stretch(trip.start, trip.until, journey=trip.id)
        acts.days_of(stretch.first, stretch.last)
        return stretch, rd
    if week is not None:
        _text, monday, sunday = week_paper.parse_week(week)
        stretch = Stretch(monday, sunday, week=week)
    else:
        if first is None or last is None:
            raise CompanyError("--from and --to go together")
        stretch = Stretch(parse_day(first).isoformat(), parse_day(last).isoformat())
    acts.days_of(stretch.first, stretch.last)
    return stretch, reading.read(lb, stretch.first, stretch.last, airports) if read_it else None


# -- the queue ---------------------------------------------------------------------------------------------


def read(
    lb: Logbook,
    journey: str | None = None,
    week: str | None = None,
    first: str | None = None,
    last: str | None = None,
    airports: Airports | None = None,
    limit: int = SHOWN,
) -> Queue:
    """The review-with queue of the stretch (the module's docstring). Nothing is written."""
    stretch, rd = stretch_of(lb, journey, week, first, last, airports)
    assert rd is not None
    return queue_of(rd, stretch, acts.relations(lb), limit)


def queue_of(rd: Reading, stretch: Stretch, relations: acts.Relations, limit: int = SHOWN) -> Queue:
    """The queue of `stretch` from its reading `rd` and the record's relation notes."""
    wanted = set(stretch.days)
    start, end = rd.day_start.span(stretch.first)[0], rd.day_start.span(stretch.last)[1]
    near = present.Evidence(rd.lines, rd.tz)
    again = [
        line
        for line in rd.lines
        if line.get("kind") == "transcript" and isinstance((line.get("payload") or {}).get("supersedes"), str)
    ]
    answered = {
        (person, day)
        for line in presence.stated(rd.lines)
        if (person := presence.person_of(line)) is not None and (day := rd.day_of(line)) in wanted
    }
    asks: dict[str, Ask] = {}
    unplaced: set[str] = set()
    for stay in rd.owner_stays:
        if not (stay.start < end and stay.end > start):
            continue
        found = {str(line.get("id")): line for line in [*near.near(stay), *again]}
        lines = sorted(found.values(), key=lambda line: int(line.get("seq", 0)))
        home = stays.is_home(stay, rd.places)
        for p in present.present(stay, lines, rd.identities, rd.places, rd.owner):
            line = found.get(p.line)
            if line is None:
                continue
            day = _day_at(rd, line, stay)
            if day not in wanted:
                continue
            if p.source == "photo" and not acts.own_camera(line):
                continue  # a photo the owner's camera did not take proposes nobody
            if p.person is None:
                unplaced.add(p.name.casefold())
                continue
            if p.source == "note":
                answered.add((p.person, day))  # the owner's own words at the stay
                continue
            if relations.not_with_on(p.person, day):
                continue
            if home and relations.lives_with_on(p.person, day):
                continue  # with the owner at home without asking
            ask = asks.setdefault(p.person, Ask(p.person, p.name))
            _add(ask, p, line, day)
    shown = []
    for ask in asks.values():
        left = ask.without({day for person, day in answered if person == ask.person})
        if left.pieces:
            shown.append(left)
    shown.sort(key=Ask.strength)
    return Queue(stretch, shown[:limit], max(0, len(shown) - limit), len(unplaced))


def _day_at(rd: Reading, line: Line, stay: stays.Segment) -> str:
    """The day a piece of evidence lies on: where its line begins, or where the stay does when the line
    began before it (an entry that runs over midnight)."""
    at = stays.instant(line.get("at"))
    moment = stay.start if at is None else max(at, stay.start)
    return rd.day_start.day(moment).isoformat()


def _add(ask: Ask, p: present.Presence, line: Line, day: str) -> None:
    payload = line.get("payload") or {}
    title = str(payload.get("title") or "an entry")
    if p.source == "photo":
        kind = PHOTO
    elif p.source == "calendar":
        kind = INVITE
    elif p.source == "transcript":
        provider = str(payload.get("provider") or line.get("source") or "")
        kind = MEETING if provider in MEETING_PROVIDERS else CALL
    else:
        return
    ask.pieces.setdefault(p.line, Piece(kind, day, title))


def rows(queue: Queue) -> Iterator[str]:
    """The queue as `review with` prints it: the stretch, then each person on a line of their own, the
    evidence and the days under the name."""
    yield f"who was there, {queue.stretch.words()}"
    if not queue.people:
        yield "  nobody to ask: no proposal on these days that you have not answered"
    for ask in queue.people:
        yield f"  {ask.name}"
        yield f"      {ask.words()}"
        yield f"      on {', '.join(_short(day) for day in sorted(ask.days))}"
    if queue.more:
        yield f"  and {queue.more} more, on less evidence"
    if queue.unplaced:
        yield f"  {queue.unplaced} not placed yet (faces or names): `logbook people review`"
    if queue.people:
        yield f"  answer: {ANSWERS}"


def _short(day: str) -> str:
    d = parse_day(day)
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b')}"


# -- the answers -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Answered:
    """What the answers wrote: the days stated per person, and the not-with notes."""

    stated: list[tuple[str, list[acts.DayStated]]]
    not_with: list[Line]

    def to_json(self) -> dict[str, Any]:
        return {
            "with": [{"name": name, "days": [d.to_json() for d in found]} for name, found in self.stated],
            "not_with": [line["id"] for line in self.not_with],
        }


def answer(
    lb: Logbook,
    stretch: Stretch,
    accept: Sequence[str] = (),
    days: Sequence[str] | None = None,
    nots: Sequence[str] = (),
    now: datetime | None = None,
) -> Answered:
    """Write the answers to a stretch's queue through the acts: `accept` the people with the owner on
    every day of the stretch that has begun, or on `days` only (one person then); `nots` a `not-with`
    note each for the stretch. Every name and day is checked first, under one hold of the writer lock;
    `CompanyError` and nothing written otherwise."""
    clock = now if now is not None else datetime.now(UTC)
    if not accept and not nots:
        raise CompanyError("nothing to write: say --accept NAME or --not NAME")
    if days is not None and len(accept) != 1:
        raise CompanyError("--days goes with one --accept NAME")
    with lb.writer():
        report = people.directory(lb)
        accepted = [acts.resolve([name], report)[0] for name in accept]
        refused = [acts.resolve([name], report)[0] for name in nots]
        both = {p.entity for p in accepted} & {p.entity for p in refused}
        if both:
            named = sorted(p.name for p in accepted if p.entity in both)
            raise CompanyError(f"{', '.join(named)}: --accept and --not at once; nothing was written")
        today = acts.today_of(lb, clock)
        whole = stretch.days
        if days is None:
            chosen = [d for d in whole if d <= today]
        else:
            chosen = []
            for text in days:
                try:
                    d = parse_day(text).isoformat()
                except ValueError as e:
                    raise CompanyError(f"--days {text!r}: {e}; nothing was written") from e
                if d not in whole:
                    raise CompanyError(f"{d} is not a day of {stretch.words()}; nothing was written")
                if d > today:
                    raise CompanyError(f"{d} has not begun; nothing was written")
                chosen.append(d)
        if accepted and not chosen:
            raise CompanyError(f"no day of {stretch.words()} has begun; nothing was written")
        stated = [(p.name, acts.with_days(lb, chosen, [p.entity], clock, report)) for p in accepted]
        written = [acts.not_with(lb, p.entity, stretch.first, stretch.last, clock) for p in refused]
    return Answered(stated, written)


# -- your people in a city ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Placed:
    """A person the record places in a city, and, for a journey, whether they were seen on it."""

    person: str
    name: str
    city: str
    line: str
    seen: bool | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"person": self.person, "name": self.name, "city": self.city, "line": self.line}
        if self.seen is not None:
            out["seen"] = self.seen
        return out


def people_in_city(
    lb: Logbook, city: str, journey: str | None = None, airports: Airports | None = None
) -> dict[str, Any]:
    """The people the record places in `city` (case and accents aside), by name, and with `journey`
    whether each was seen on it: confirmed at one of its stays, or stated with the owner on one of
    its days. `ValueError` as the journey's reader raises it. Nothing is written."""
    wanted = fold(city)
    if not wanted:
        raise CompanyError("name the city")
    found = acts.relations(lb)
    report = people.directory(lb)
    placed = [
        (person, report.known[person].name, home)
        for person, home in found.lives_in.items()
        if fold(home.city) == wanted and person in report.known
    ]
    seen: set[str] | None = None
    trip_id = None
    if journey is not None:
        rd, trip = trip_page.locate(lb, trip_page.parse_ref(journey), airports or Airports.load())
        trip_id = trip.id
        seen = {c.person for c in trip.people if c.person}
        seen |= {
            person
            for line in presence.stated(rd.lines)
            if (person := presence.person_of(line)) is not None
            and trip.start <= rd.day_of(line) <= trip.until
        }
    out = [
        Placed(person, name, home.city, home.line, None if seen is None else person in seen)
        for person, name, home in sorted(placed, key=lambda p: p[1].casefold())
    ]
    return {"city": " ".join(city.split()), "journey": trip_id, "people": [p.to_json() for p in out]}


def city_rows(data: dict[str, Any]) -> Iterator[str]:
    """`people city` as it prints: the city, then a name a line, *seen* or *not yet* beside it on a
    journey."""
    head = f"your people in {data['city']}"
    yield head + (f", on journey {data['journey']}" if data["journey"] else "")
    if not data["people"]:
        yield "  nobody the record places there: `logbook people lives-in NAME CITY` says where someone lives"
    for p in data["people"]:
        mark = "" if "seen" not in p else ("  seen" if p["seen"] else "  not yet")
        yield f"  {p['name']}{mark}"


def fold(text: str) -> str:
    """A city's name for matching: its words, case and accents aside."""
    decomposed = unicodedata.normalize("NFKD", " ".join(str(text).split()))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()
