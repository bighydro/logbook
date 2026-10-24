"""The Journeys: the trips of the record read back one year at a time, and one journey whole — the
Journeys page of `logbook serve` — and the captain's name for one, `logbook add --trip ID "NAME"`.

A journey is a trip (ADR 0019): a run of nights away from home, derived from the record every time
and never written, its id `trip:<first day>:<last day>`. This reader grows the trips reader
(`trips.trips`), and changes nothing it says: per journey the **bounds** (the first and last day
away, the return day), the **nights away**, the **places** named, the **people** confirmed on it
who are canonical (a person the resolution lines name; the ones the with module saw that no line
names are counted, `unplaced`, and listed only in the People page's review queue), the **photos**
dated on its days (first day to return day, `photo/v1` lines standing), its **name** when the
captain gave it one, and the standing **draft** of it (RFC 0036, `unit` `journey`) when a model
wrote one. A journey's draft follows the `dream` entry of the crossing policy as a day's does
(`drafts.allowed`, `drafts.for_unit`): one above the entry's `max_tier` today is not shown, and when
the standing draft is one, a reader that holds the whole record carries the row that says so
(`draft_withheld`) and nothing of its text, while a gated reader hides it without a word. Every
number keeps the lines it rests on, so a page can say where it came from.

**The year.** A year's journeys are those whose first day is in it, most recent first, read from
one reading of the year and `MARGIN_DAYS` either side, so a journey that runs over New Year is read
whole and listed once, under the year it began; one that touches the reading's end is read again
the way the Trip reads it (`trip_page.locate`), so the id the list links is the id the journey's
page finds.

**One journey** is the Trip (`trip_page.compose`: the stays slept at, the legs, the days, the
flights, the people confirmed and proposed) with the name, the draft, the photos, the line ids each
stay and each day rests on, and the **promises made on it**: the proposals of `promises` whose
day is one of its days (first day to return day), open or done, in day order.

**The name** is a `note/v1` line (RFC 0010) in the captain's words, written through `notes.write`
with the label `name` and the journey's id under `extra.trip`, tier 2, source `manual`, dated
inside the journey: now, when today is one of its days, else the last minute of its last day away.
The standing name of a journey is its latest such note not retracted that names its id, else, when
a recompute has moved its bounds since it was named, the latest dated on one of its days. A reader
never parses a note's prose into a name: only the label and the id say it is one. A name is tier
2, so a reader through a gate without tier 2 (`reading.crossing`) shows none. `logbook add
--trip` and the Journeys page's form write it through `name`, the one path. Nothing else here
writes."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from ..core import day_start, drafts, notes, reading, trips
from ..core.chain import Line
from ..core.flights import Airports
from ..core.reading import Reading
from ..core.store import Logbook, retractions
from . import promises as promise_reader
from . import trip_page

SPILL_DAYS = 2  # a reading holds the night after its last day and the morning after that
MARGIN_DAYS = 31  # a year is read with a month either side: a journey over New Year is seen whole
PHOTO = "photo"
READ_KINDS: tuple[str, ...] | None = (
    *trips.READ_KINDS,
    PHOTO,
)  # a year's journeys' lines; the rest from the index
YEAR_DIGITS = 4


class JourneyError(ValueError):
    """A name the record refuses: no words, or no journey where it was asked for; nothing written."""


@dataclass(frozen=True)
class Name:
    """The captain's name for a journey: the words, the note line and when it was written."""

    text: str
    line: str
    at: str

    def to_json(self) -> dict[str, Any]:
        return {"text": self.text, "line": self.line, "at": self.at}


@dataclass(frozen=True)
class Journey:
    """One journey of the list: the trip as `trips` derives it, and what this reader adds."""

    trip: trips.Trip
    name: Name | None
    photos: list[str]  # the photo lines dated on its days, in chain order
    draft: dict[str, Any] | None  # `drafts.day_json` of the standing journey draft the policy allows
    draft_withheld: dict[str, Any] | None  # `drafts.withheld_json` when the policy withholds it
    people: list[dict[str, Any]]  # the canonical people confirmed on it: id, name, lines
    unplaced: int  # the people the with module saw on it that no resolution line names
    nights_of: list[dict[str, Any]] = field(default_factory=list)  # each night away: day, where, lines

    @property
    def id(self) -> str:
        return self.trip.id

    def to_json(self) -> dict[str, Any]:
        t = self.trip
        return {
            "id": t.id,
            "start": t.start,
            "end": t.end,
            "until": t.until,
            "nights": t.nights,
            "in_transit": t.in_transit,
            "route": list(t.route),
            "places": list(t.places),
            "people": self.people,
            "unplaced": self.unplaced,
            "photos": {"count": len(self.photos), "lines": list(self.photos)},
            "name": None if self.name is None else self.name.to_json(),
            "draft": self.draft,
            "draft_withheld": self.draft_withheld,
            "nights_of": self.nights_of,
            "lines": list(t.lines),
        }


@dataclass(frozen=True)
class Shelf:
    """The journeys of one year, most recent first; `years` the calendar years the record covers."""

    year: str | None
    years: list[str]
    journeys: list[Journey]
    warning: str | None = None
    reads: tuple[str, str] | None = None  # the local days read: the year, the margin, its journeys whole

    def to_json(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "years": self.years,
            "warning": self.warning,
            "journeys": [j.to_json() for j in self.journeys],
        }


# -- the year --------------------------------------------------------------------------------------------


def shelf(
    lb: Logbook,
    year: str | None = None,
    airports: Airports | None = None,
    tiers: Sequence[int] | None = None,
) -> Shelf:
    """The journeys that begin in `year` (default the record's last), most recent first; through
    the gate `tiers` when given. `ValueError` for a year that is not one; `stays.SettingsError` as
    the readers raise it. Nothing is written."""
    whole = reading.record_days(lb, "location")
    if whole is None:
        return Shelf(None, [], [], "the record has no days: no location line places the owner anywhere")
    year = year or whole[1][:YEAR_DIGITS]
    if not (len(year) == YEAR_DIGITS and year.isdigit()):
        raise ValueError(f"not a year (YYYY): {year!r}")
    years = [str(y) for y in range(int(whole[0][:4]), int(whole[1][:4]) + 1)]
    since = max(whole[0], (date(int(year), 1, 1) - timedelta(days=MARGIN_DAYS)).isoformat())
    until = min(whole[1], (date(int(year), 12, 31) + timedelta(days=MARGIN_DAYS)).isoformat())
    if until < f"{year}-01-01" or since > f"{year}-12-31":
        runs = f"{whole[0]} {trips.EN_DASH} {whole[1]}"
        return Shelf(year, years, [], f"no days in {year}: the record runs {runs}")
    airports = airports or Airports.load()
    rd = reading.read(lb, since, until, airports, tiers, READ_KINDS)
    found, warning = trips.trips(rd)
    if warning:
        return Shelf(year, years, [], warning)
    begun = [t for t in found if t.start[:YEAR_DIGITS] == year]
    pairs: list[tuple[trips.Trip, Reading]] = []
    for t in begun:
        if t.end >= until and until < whole[1]:  # it may run on past the reading: read it as the Trip does
            located, whole_trip = trip_page.locate(lb, trip_page.Ref(t.start, None), airports, tiers)
            pairs.append((whole_trip, located))
        else:
            pairs.append((t, rd))
    last = max((t.until for t, _rd in pairs), default=until)
    with lb.index() as idx:
        retracted = frozenset(retractions(idx.retractions()))
        named = names_in(reading.crossing(idx.by_kind(notes.KIND, since, max(until, last)), tiers), retracted)
        drafted = drafts.by_unit(idx.by_kind(drafts.KIND), retracted, drafts.UNIT_JOURNEY)
    allowed = drafts.allowed(lb.root)
    out = [_journey(t, r, named, drafted, allowed, tiers) for t, r in pairs]
    out.sort(key=lambda j: j.trip.start, reverse=True)
    through = (date.fromisoformat(max(until, last)) + timedelta(days=SPILL_DAYS)).isoformat()
    return Shelf(year, years, out, reads=(since, through))


def _journey(
    trip: trips.Trip,
    rd: Reading,
    named: Sequence[Line],
    drafted: Mapping[str, Sequence[Line]],
    allowed: drafts.Allowed,
    tiers: Sequence[int] | None,
) -> Journey:
    canonical = [c for c in trip.people if c.person is not None]
    draft, withheld = draft_of(trip, rd, drafted, allowed, tiers)
    return Journey(
        trip,
        name_of(trip, named, rd.day_start),
        photos(rd, trip),
        draft,
        withheld,
        [{"id": c.person, "name": c.name, "lines": list(c.lines)} for c in canonical],
        len(trip.people) - len(canonical),
        nights_of(trip, rd),
    )


def photos(rd: Reading, trip: trips.Trip) -> list[str]:
    """The ids of the photo lines standing whose local day is one of the journey's, first day to
    return day, in chain order."""
    return [str(line["id"]) for line in rd.of_kind(PHOTO) if trip.start <= rd.day_of(line) <= trip.until]


def nights_of(trip: trips.Trip, rd: Reading) -> list[dict[str, Any]]:
    """Each night away: the day, where it was spent as the route labels it, the stay's id and the
    lines it rests on (the first and last point of the stay); a night in transit has none."""
    out: list[dict[str, Any]] = []
    for night in rd.nights:
        if not trip.start <= night.day <= trip.end:
            continue
        stay = night.stay
        if stay is None:
            out.append({"day": night.day, "where": "in transit", "stay": None, "lines": []})
            continue
        where = trips.route_of([stay], rd.places, rd.airports, rd.assets)[0]
        lines = [id_ for id_ in (stay.first_line, stay.last_line) if id_]
        out.append({"day": night.day, "where": where, "stay": stay.id, "lines": list(dict.fromkeys(lines))})
    return out


# -- the name --------------------------------------------------------------------------------------------


def names_in(lines: Iterable[Line], retracted: frozenset[str]) -> list[Line]:
    """The name notes among `lines`, not retracted, in the day's order: `note/v1` with the label
    `name` and a journey's id under `extra.trip`."""
    return [
        line
        for line in notes.standing(lines, notes.NAME, retracted)
        if _named_id(line) is not None and _words(line)
    ]


def name_of(trip: trips.Trip, named: Sequence[Line], days: day_start.DayStart) -> Name | None:
    """The standing name of `trip`: the latest note that names its id, else the latest dated on
    one of its days (its bounds moved since it was named); None when it has none."""
    by_id = [line for line in named if _named_id(line) == trip.id]
    by_day = [line for line in named if trip.start <= days.day_of(str(line["at"])) <= trip.until]
    found = by_id or by_day
    if not found:
        return None
    line = found[-1]
    return Name(_words(line), str(line["id"]), str(line["at"]))


def name(
    lb: Logbook,
    ref: str,
    text: str,
    airports: Airports | None = None,
    today: str | None = None,
) -> Line:
    """Name the journey `ref` (its id, or any day of it): one `note/v1` line, the words as given
    (whitespace folded), the label `name`, the id under `extra.trip`, through `notes.write`, dated
    now when `today` (the record's today unless given) is one of its days, else at the last minute
    of its last day away. `JourneyError` for no words, `ValueError` as `trip_page.locate` raises it
    when there is no journey there."""
    words = " ".join(text.split())
    if not words:
        raise JourneyError("a journey's name is words; nothing was written")
    trip_ref = trip_page.parse_ref(ref)
    _rd, trip = trip_page.locate(lb, trip_ref, airports or Airports.load())
    days = day_start.of(lb.meta)
    today = today or notes.today_in(days)
    if today < trip.start:
        raise JourneyError(f"{trip.id} begins after today, {today}; a journey is named once it has begun")
    day = today if today <= trip.until else trip.end
    return notes.write(lb, day, words, notes.NAME, "manual", today=today, extra={"trip": trip.id})


def _named_id(line: Line) -> str | None:
    extra = (line.get("payload") or {}).get("extra")
    found = extra.get("trip") if isinstance(extra, dict) else None
    return found if isinstance(found, str) and found.startswith("trip:") else None


def _words(line: Line) -> str:
    text = (line.get("payload") or {}).get("text")
    return " ".join(text.split()) if isinstance(text, str) else ""


# -- the draft -------------------------------------------------------------------------------------------


def draft_of(
    trip: trips.Trip,
    rd: Reading,
    drafted: Mapping[str, Sequence[Line]],
    allowed: drafts.Allowed | None = None,
    tiers: Sequence[int] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """The standing draft of the journey and its withheld row, by the Day's rule
    (`drafts.for_unit`): of its drafts (`drafted`, `drafts.by_unit` of unit `journey`, by the
    subject that names its id), those the gate `tiers` and the `dream` entry today (`allowed`) let
    through, the evidence checked against the lines of the journey's days, first day to return day;
    None for either when there is none."""
    found = drafted.get(trip.id, [])
    if not found:
        return None, None
    on_journey = {str(line["id"]) for line in rd.lines_of(trip.start, trip.until)}
    return drafts.for_unit(found, on_journey, tiers, allowed, not_on=drafts.NOT_ON_JOURNEY)


# -- one journey ------------------------------------------------------------------------------------------


def read(
    lb: Logbook,
    ref: str,
    airports: Airports | None = None,
    tiers: Sequence[int] | None = None,
) -> dict[str, Any]:
    """One journey as one JSON-ready object: the Trip (`trip_page.compose`) with `journey` (the
    list's row: name, draft, photos, people, the nights' lines) and `promises` (the proposals made
    on its days), and for each route stay and each day the lines it rests on. `ValueError` as
    `trip_page.locate` raises it. Nothing is written."""
    airports = airports or Airports.load()
    rd, trip = trip_page.locate(lb, trip_page.parse_ref(ref), airports, tiers)
    data = trip_page.compose(lb, rd, trip, tiers)
    with lb.index() as idx:
        retracted = frozenset(retractions(idx.retractions()))
        named = names_in(reading.crossing(idx.by_kind(notes.KIND, trip.start, trip.until), tiers), retracted)
        drafted = drafts.by_unit(idx.by_kind(drafts.KIND), retracted, drafts.UNIT_JOURNEY)
    row = _journey(trip, rd, named, drafted, drafts.allowed(lb.root), tiers)
    data["journey"] = row.to_json()
    by_stay: dict[str, list[str]] = {}
    for night in rd.nights:
        stay = night.innermost
        if stay is not None and trip.start <= night.day <= trip.end:
            kept = by_stay.setdefault(stay.id, [])
            kept += [i for i in (stay.first_line, stay.last_line) if i and i not in kept]
    for entry in data["route"]:
        entry["lines"] = by_stay.get(str(entry["stay"]), []) if entry["stay"] else []
    night_lines = {n["day"]: n["lines"] for n in row.nights_of}
    for day in data["days"]:
        day["night_lines"] = night_lines.get(str(day["day"]), [])
    data["promises"] = promises_on(lb, trip)
    return data


def promises_on(lb: Logbook, trip: trips.Trip) -> list[dict[str, Any]]:
    """The promises made on the journey: every proposal of `promises` the sections show whose day
    is one of its days, first day to return day, open or done, in day order."""
    report = promise_reader.extract(lb, since=trip.start, until=trip.until)
    return [_promise(p) for p in report.proposals if p.shows]


def _promise(p: promise_reader.Proposal) -> dict[str, Any]:
    return {
        "id": p.id,
        "day": p.day,
        "status": p.status,
        "role": p.role,
        "speaker": None if p.speaker is None else p.speaker.display(),
        "counterpart": p.counterpart,
        "quote": p.match.quote,
        "due": p.due,
        "kind": p.kind,
        "source": p.source,
        "line": p.line,
    }


def nights_text(j: Mapping[str, Any]) -> str:
    """`6 nights away`, `(1 in transit)` when one was."""
    n = int(j["nights"])
    text = f"{n:,} night{'s' if n != 1 else ''} away"
    return f"{text} ({j['in_transit']} in transit)" if j["in_transit"] else text
