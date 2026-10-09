"""The vault: `logbook export vault <folder> [--since DAY] [--until DAY] [--tier 1|1,2]`.

The record rendered as a folder of plain Markdown that an Obsidian or Logseq user opens as a vault:
one page per day (the Day of `logbook day`, with YAML front matter: the date, the country, the nights
either side, the places and the people), one page per named place (`places.json`) and per person the
record resolves, one per trip (`logbook trips`), one per year, and a root page, every page linked to
the others with wikilinks, `[[2026-06-13]]`, `[[Home]]`, `[[Kari Nordmann]]`, so the graph view shows
the record's shape: days hang off the places they were spent at and the people met, trips string their
days together, a year gathers all of it.

It is an export, and it is tier-gated exactly like a crossing (ADR 0016): a line is in the vault only
when its tier is in `--tier` (`1` by default, `1,2` when `policy/crossing.json` names `vault` with a
ceiling of 2, never 3), and a line that is not shows only as a count — `held back: 1 note` — so a
tier-1 vault has the shape of every day and no text of any note, message, transcript or mail. Whoever
a line confirms present is in the vault only when that line is; a companion a tier-2 note names is
not on the page until tier 2 crosses. Health and money never are. Every run appends one `crossing/v1`
line (RFC 0011) with the destination `vault`, the window, the counts and the digest of the folder as
written, so the record shows it left; nothing else is written to the record, and that one write goes
through `Logbook.append`.

Re-running rewrites only the files whose content changed: every page is a function of the record's
lines and settings alone — no head, no timestamp, no counter — so an unchanged day is an unchanged
file, and Obsidian's own index, its `.obsidian/` folder and the owner's own notes beside the pages are
never touched. Nothing is deleted. The window is read a calendar year at a time (`reading.read`, as
`logbook year` reads it, with the day before so the first day has its night before), so a long record
is a handful of readings and never one; a trip across New Year is two pages, as the Year shows it."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path, PurePosixPath
from typing import Any
from zoneinfo import ZoneInfo

from ..core import crossing, policy, reading, stays
from ..core import day as day_reader
from ..core import places as named_places
from ..core import trips as trip_reader
from ..core.chain import Line
from ..core.export import day_range, parse_day
from ..core.flights import Airports
from ..core.reading import Reading
from ..core.store import Logbook, uuid7

DESTINATION = policy.VAULT_DESTINATION
TIER_SETS = {"1": (1,), "1,2": (1, 2)}  # tier 3 never goes to a vault
DAYS, PLACES, PEOPLE, TRIPS, YEARS = "days", "places", "people", "trips", "years"
ROOT_PAGE = "Logbook"
PAGE_NOUNS = {  # a kind of page, singular and plural, for the console
    DAYS: ("day", "days"),
    PLACES: ("place", "places"),
    PEOPLE: ("person", "people"),
    TRIPS: ("trip", "trips"),
    YEARS: ("year", "years"),
}
UNNAMED = "unnamed"
UNSAFE = re.compile(r'[<>:"/\\|?*\[\]#^\x00-\x1f]+')  # a file name on every platform, and a wikilink's text
RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])$", re.IGNORECASE)  # Windows device names
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
EN_DASH = "\u2013"
ARROW = "\u2192"
DOT = " \u00b7 "
PLANE = "\u2708"
NAMED = ("events", "transcripts", "notes", "mail", "calls", "keepers")  # attachments the Day names
NOUN = {
    "events": "event",
    "transcripts": "transcript",
    "notes": "note",
    "mail": "mail thread",
    "calls": "call",
    "keepers": "keeper",
    "messages": "message",
    "photos": "photo",
}


class VaultError(ValueError):
    """A request the record or the policy refuses; the message says why and names the file."""


# -- the request --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Request:
    """One export, checked against the policy: the window of local days and the tiers asked for."""

    since: str  # local days, inclusive
    until: str
    tiers: tuple[int, ...]
    max_tier: int

    @property
    def days(self) -> list[str]:
        return day_range(self.since, self.until)


def parse_tiers(text: str) -> tuple[int, ...]:
    """`--tier 1` or `1,2`; `1,2,3` is refused, since tier 3 never goes to a vault."""
    key = ",".join(part.strip() for part in text.split(","))
    if key not in TIER_SETS:
        raise VaultError(f"--tier must be 1 or 1,2, not {text!r}; tier 3 never goes to a vault")
    return TIER_SETS[key]


def request(lb: Logbook, since: str | None, until: str | None, tiers: tuple[int, ...]) -> Request | None:
    """The window — `--since` and `--until` as local days, each defaulting to the days the owner's
    track covers (else the days with any line) — held against the policy: a tier above the ceiling
    for `vault` is refused naming the file. None when the record has no day at all."""
    whole = reading.record_days(lb, "location") or reading.record_days(lb)
    if whole is None:
        return None
    try:
        first = parse_day(since).isoformat() if since else whole[0]
        last = parse_day(until).isoformat() if until else whole[1]
    except ValueError as e:
        raise VaultError(str(e)) from e
    if last < first:
        raise VaultError(f"the window runs backwards: --since {first} --until {last}")
    try:
        max_tier = policy.vault_ceiling(lb.root)
    except policy.PolicyError as e:
        raise VaultError(str(e)) from e
    if max(tiers) > max_tier:
        raise VaultError(
            f"--tier {','.join(map(str, tiers))} is above the ceiling for {DESTINATION!r}: "
            f"{policy.policy_path(lb.root)} allows max_tier {max_tier}"
            f"{policy.expiry_note(lb.root, DESTINATION)}; "
            f'add {{"{DESTINATION}": {{"max_tier": {max(tiers)}}}}} to it if that is what you want'
        )
    return Request(first, last, tiers, max_tier)


# -- names: one namespace of page stems, safe as file names and inside a wikilink ----------------------------


def safe_stem(name: str) -> str:
    """A page's file stem: whitespace collapsed; every character a file system or a wikilink refuses
    (`<>:"/\\|?*[]#^` and controls) replaced by a dash; trailing dots and spaces dropped (Windows);
    `unnamed` for nothing; a Windows device name (`CON`, `COM1`) gets a dash."""
    text = UNSAFE.sub("-", " ".join(name.split())).strip(" .")
    if not text:
        return UNNAMED
    if RESERVED.match(text):
        text += "-"
    return text


class Names:
    """The stems claimed so far, one namespace for the whole vault, since Obsidian and Logseq resolve
    `[[Name]]` by the file's stem wherever it lies. Two names that differ only by case, or that fold
    to the same safe stem, are two pages: the second gets ` (2)`, the third ` (3)`. Claiming a name
    again gives the stem it got."""

    def __init__(self) -> None:
        self._stems: dict[str, str] = {}
        self._taken: set[str] = set()

    def claim(self, name: str) -> str:
        if name in self._stems:
            return self._stems[name]
        stem = safe_stem(name)
        candidate, n = stem, 1
        while candidate.casefold() in self._taken:
            n += 1
            candidate = f"{stem} ({n})"
        self._stems[name] = candidate
        self._taken.add(candidate.casefold())
        return candidate


def link(stem: str) -> str:
    return f"[[{stem}]]"


# -- the gate: a line is in the vault when its tier is -------------------------------------------------------


@dataclass(frozen=True)
class Gate:
    """Which lines of one reading cross: those whose tier is in the request's. A line the reading does
    not know is held back, never shown."""

    tiers: tuple[int, ...]
    tier_of: Mapping[str, int]

    def ok(self, line_id: object) -> bool:
        return self.tier_of.get(str(line_id)) in self.tiers

    def any(self, ids: Iterable[object]) -> bool:
        return any(self.ok(i) for i in ids)


# -- the pages, accumulated over the window ------------------------------------------------------------------


@dataclass
class Attachments:
    """One row's attachments after the gate: the named ones as text, the counts shown, the held."""

    named: list[str] = field(default_factory=list)
    shown: Counter[str] = field(default_factory=Counter)
    held: Counter[str] = field(default_factory=Counter)


@dataclass
class Night:
    text: str  # as the Day says it: a place, `aboard <asset>`, coordinates, `in transit`
    place: str | None  # the named place, when the night was at one (not aboard)
    home: bool
    aboard: str | None


@dataclass
class DayPage:
    day: str
    weekday: str
    country: str | None
    before: Night
    after: Night
    places: list[str] = field(default_factory=list)  # named places stayed at, in order of first stay
    people: list[tuple[str, str]] = field(
        default_factory=list
    )  # (key, name) confirmed by a line that crosses
    flights: list[str] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)  # the body below the header, rendered
    attached: int = 0  # attachments shown across the rows
    held: Counter[str] = field(default_factory=Counter)
    trip: str | None = None  # the trip page's stem, when the day is in one

    @property
    def year(self) -> str:
        return self.day[:4]


@dataclass
class PlaceDay:
    stays: int = 0
    seconds: int = 0
    night: bool = False


@dataclass
class PlacePage:
    place: named_places.Place
    days: dict[str, PlaceDay] = field(default_factory=dict)
    people: dict[str, set[str]] = field(default_factory=dict)  # person key -> days met there
    trips: list[str] = field(default_factory=list)

    @property
    def nights(self) -> int:
        return sum(1 for d in self.days.values() if d.night)


@dataclass
class PersonPage:
    key: str
    name: str
    entity: str | None
    days: dict[str, list[tuple[str | None, str, tuple[str, ...]]]] = field(default_factory=dict)
    trips: list[str] = field(default_factory=list)

    @property
    def places(self) -> list[tuple[str, int]]:
        """The named places shared, by days there, most first."""
        by_place: dict[str, set[str]] = {}
        for day, visits in self.days.items():
            for place, _where, _sources in visits:
                if place:
                    by_place.setdefault(place, set()).add(day)
        return sorted(((p, len(d)) for p, d in by_place.items()), key=lambda pd: (-pd[1], pd[0]))


@dataclass
class TripPage:
    trip: trip_reader.Trip
    stem: str
    people: list[tuple[str, str]]  # (key, name), gated
    asset_name: str | None


@dataclass(frozen=True)
class Build:
    """What one export renders, before anything is written: the files by record-relative posix path."""

    files: dict[str, bytes]
    pages: dict[str, int]  # per kind of page
    days: int  # day pages
    logged: int
    crossed: int
    by_tier: dict[str, int]
    by_kind: dict[str, int]
    held_by_kind: dict[str, int]

    @property
    def held_back(self) -> int:
        return self.logged - self.crossed

    def counts(self) -> dict[str, Any]:
        """RFC 0011's `counts`, in the crossing's shape: a vault carries no resolution overlay and
        copies no attachment, so those are zero."""
        return {
            "logged": self.logged,
            "crossed": self.crossed,
            "held_back": self.held_back,
            "by_tier": dict(self.by_tier),
            "by_kind": dict(self.by_kind),
            "resolutions": 0,
            "resolutions_held_back": 0,
            "attachments": {"included": 0, "bytes": 0, "missing": 0},
        }


class _Builder:
    """Reads the window a calendar year at a time and accumulates the pages; `files()` renders them."""

    def __init__(self, lb: Logbook, req: Request, airports: Airports | None) -> None:
        self.lb = lb
        self.req = req
        self.airports = airports or Airports.load()
        self.tz = ZoneInfo(str(lb.meta["timezone"]))
        self.names = Names()
        self.names.claim(ROOT_PAGE)
        for year in sorted({d[:4] for d in req.days}):
            self.names.claim(year)
        for day in req.days:
            self.names.claim(day)
        self.days: dict[str, DayPage] = {}
        self.places: dict[str, PlacePage] = {}
        self.people: dict[str, PersonPage] = {}
        self.trips: list[TripPage] = []
        self.logged = 0
        self.crossed = 0
        self.by_tier: Counter[int] = Counter()
        self.by_kind: Counter[str] = Counter()
        self.held_by_kind: Counter[str] = Counter()

    # -- reading --

    def read(self) -> None:
        for first, last in _chunks(self.req.since, self.req.until):
            before = (date.fromisoformat(first) - timedelta(days=1)).isoformat()
            rd = reading.read(self.lb, before, last, self.airports)
            for place in rd.places:
                if place.name not in self.places:
                    self.names.claim(place.name)
                    self.places[place.name] = PlacePage(place)
            gate = Gate(self.req.tiers, {str(line["id"]): int(line["tier"]) for line in rd.lines})
            by_day = _by_day(rd)
            pages: list[DayPage] = []
            for day in day_range(first, last):
                lines = by_day.get(day, [])
                if not lines:
                    continue
                self._count(lines)
                data = day_reader.of_reading(rd, day, None, lines)
                page = self._day(data, lines, rd, gate)
                self.days[day] = page
                pages.append(page)
            found, _warning = trip_reader.trips(rd)
            for trip in found:
                if trip.start >= first:  # a trip that began before the chunk belongs to the chunk before
                    self._trip(trip, rd, gate)

    def _count(self, lines: Sequence[Line]) -> None:
        for line in lines:
            tier, kind = int(line["tier"]), str(line["kind"])
            self.logged += 1
            if tier in self.req.tiers:
                self.crossed += 1
                self.by_tier[tier] += 1
                self.by_kind[kind] += 1
            else:
                self.held_by_kind[kind] += 1

    # -- a day --

    def _day(self, data: Mapping[str, Any], lines: Sequence[Line], rd: Reading, gate: Gate) -> DayPage:
        day = str(data["day"])
        place_names = {p.name for p in rd.places}
        page = DayPage(
            day,
            str(data["weekday"]),
            data["country"]["code"],
            _night(data["nights"]["before"], place_names),
            _night(data["nights"]["after"], place_names),
        )
        day_start = datetime.combine(date.fromisoformat(day), time.min, tzinfo=self.tz)
        day_end = day_start + timedelta(days=1)
        rows: list[str] = []
        for entry in data["timeline"]:
            rows.extend(self._row(entry, page, day, day_end, rd, gate, depth=0))
        page.sections.append("## Timeline\n\n" + ("\n".join(rows) if rows else "- no track") + "\n")
        all_day = [str(e["title"]) for e in data["all_day"] if gate.any(e.get("lines") or [e["line"]])]
        if all_day:
            page.sections.append("## All day\n\n" + "\n".join(f"- {t}" for t in all_day) + "\n")
        unplaced = []
        for item in data["unplaced"]:
            if gate.any(item.get("lines") or [item["line"]]):
                unplaced.append(f"- {_clock(item['at'], self.tz, day_end)} {item['kind']}: {item['title']}")
            else:
                page.held[NOUN.get(item["kind"] + "s", item["kind"])] += 1
        if unplaced:
            page.sections.append("## Unplaced\n\n" + "\n".join(unplaced) + "\n")
        notes = [
            str((line.get("payload") or {}).get("text") or "").strip()
            for line in lines
            if line.get("kind") == "note" and gate.ok(line["id"])
        ]
        notes = [n for n in notes if n]
        if notes:
            page.sections.append("## Notes\n\n" + "\n\n".join(_quote(n) for n in notes) + "\n")
        sources = [f"{s['source']} {s['lines']}" for s in data["sources"]]
        page.sections.append("## Sources\n\n" + ", ".join(sources) + "\n")
        for place in page.places:
            self.places[place].days.setdefault(day, PlaceDay())
        if page.after.place and page.after.place in self.places:
            self.places[page.after.place].days.setdefault(day, PlaceDay()).night = True
        return page

    def _row(
        self,
        e: Mapping[str, Any],
        page: DayPage,
        day: str,
        day_end: datetime,
        rd: Reading,
        gate: Gate,
        depth: int,
    ) -> Iterator[str]:
        indent = "    " * depth
        if e["kind"] == day_reader.FLIGHT:
            text = _flight_text(e)
            page.flights.append(text)
            span = f"{_clock(e['start'], self.tz, day_end)} {EN_DASH} {_clock(e['end'], self.tz, day_end)}"
            yield f"{indent}- {span} {text}"
            return
        within = e["within_day"]
        span = (
            f"{_clock(within['start'], self.tz, day_end)} {EN_DASH} {_clock(within['end'], self.tz, day_end)}"
        )
        parts = [self._where(e, rd)]
        attached = self._attached(e.get("attached"), gate)
        if attached.shown:
            parts.append(", ".join(_plural(n, NOUN[k]) for k, n in attached.shown.items()))
        people = self._people(e.get("with"), gate)
        if people:
            parts.append("with " + ", ".join(link(self.names.claim(name)) for _key, name in people))
        if attached.held:
            parts.append("held back: " + ", ".join(_plural(n, NOUN[k]) for k, n in attached.held.items()))
        yield f"{indent}- {span} {DOT.join(parts)}"
        for text in attached.named:
            yield f"{indent}    - {text}"
        page.attached += sum(attached.shown.values())
        page.held.update(attached.held)
        place = e.get("place")
        if place and place in self.places:
            if place not in page.places:
                page.places.append(place)
            at_place = self.places[place].days.setdefault(day, PlaceDay())
            at_place.stays += 1
            at_place.seconds += int(within["duration_s"])
        for key, name in people:
            if (key, name) not in page.people:
                page.people.append((key, name))
            person = self._person(key, name)
            person.days.setdefault(day, []).append((place, str(e.get("where") or ""), ()))
            if place and place in self.places:
                self.places[place].people.setdefault(key, set()).add(day)
        for inner in e.get("inside") or []:
            yield from self._row(inner, page, day, day_end, rd, gate, depth + 1)

    def _where(self, e: Mapping[str, Any], rd: Reading) -> str:
        kind = e["kind"]
        if kind == stays.MOVE:
            if e.get("gap"):
                return f"gap in the track, {_duration(int(e['duration_s']))}"
            mode = str(e.get("mode") or "moved")
            text = mode if e.get("distance_m") is None else f"{mode} {_km(float(e['distance_m']))}"
            if e.get("airports"):
                text += f" {e['airports'][0]} {ARROW} {e['airports'][1]}"
            return text
        place = e.get("place")
        if place and place in self.places:
            text = link(self.names.claim(place))
        else:
            text = str(e.get("where") or "somewhere")
        if kind == stays.STOP:
            text = f"stop at {text}"
        return text

    def _attached(self, attached: Mapping[str, Any] | None, gate: Gate) -> Attachments:
        out = Attachments()
        if not attached:
            return out
        for key in NAMED:
            for item in attached[key]:
                ids = item.get("lines") or [item["line"]]
                if gate.any(ids):
                    out.shown[key] += 1
                    out.named.append(_named_text(key, item))
                else:
                    out.held[key] += 1
        for key in ("messages", "photos"):
            for line_id in attached[key]["lines"]:
                (out.shown if gate.ok(line_id) else out.held)[key] += 1
        return out

    def _people(self, company: Mapping[str, Any] | None, gate: Gate) -> list[tuple[str, str]]:
        """The confirmed companions whose evidence crosses, each once."""
        found: list[tuple[str, str]] = []
        for c in (company or {}).get("confirmed", []):
            if not gate.any(c.get("lines") or []):
                continue
            key = str(c.get("person") or f"name:{c['name']}")
            if (key, str(c["name"])) not in found:
                found.append((key, str(c["name"])))
        return found

    def _person(self, key: str, name: str) -> PersonPage:
        page = self.people.get(key)
        if page is None:
            self.names.claim(name)
            page = self.people[key] = PersonPage(key, name, None if key.startswith("name:") else key)
        return page

    # -- a trip --

    def _trip(self, trip: trip_reader.Trip, rd: Reading, gate: Gate) -> None:
        stem = self.names.claim(f"Trip {trip.start} to {trip.end}")
        people = []
        for c in trip.people:
            if gate.any(c.lines):
                key = str(c.person or f"name:{c.name}")
                people.append((key, c.name))
                self._person(key, c.name).trips.append(stem)
        asset = trip_reader.asset_name(trip.asset, rd.assets) if trip.asset else None
        self.trips.append(TripPage(trip, stem, people, asset))
        for place in trip.places:
            if place in self.places:
                self.places[place].trips.append(stem)
        for day in day_range(trip.start, trip.end):
            page = self.days.get(day)
            if page is not None:
                page.trip = stem

    # -- rendering --

    def files(self) -> dict[str, bytes]:
        out: dict[str, str] = {}
        for page in self.days.values():
            out[f"{DAYS}/{page.year}/{self.names.claim(page.day)}.md"] = self._day_text(page)
        for place in self.places.values():
            out[f"{PLACES}/{self.names.claim(place.place.name)}.md"] = self._place_text(place)
        for person in self.people.values():
            out[f"{PEOPLE}/{self.names.claim(person.name)}.md"] = self._person_text(person)
        for trip in self.trips:
            out[f"{TRIPS}/{trip.stem}.md"] = self._trip_text(trip)
        years = sorted({page.year for page in self.days.values()})
        for year in years:
            out[f"{YEARS}/{self.names.claim(year)}.md"] = self._year_text(year)
        out[f"{ROOT_PAGE}.md"] = self._root_text(years)
        return {path: text.encode("utf-8") for path, text in out.items()}

    def _day_text(self, page: DayPage) -> str:
        front = [
            f"date: {page.day}",
            f"weekday: {page.weekday}",
            f"country: {_yaml(page.country)}",
            "nights:",
            f"  before: {_yaml(page.before.text)}",
            f"  after: {_yaml(page.after.text)}",
            *_yaml_list("places", page.places),
            *_yaml_list("people", [name for _key, name in page.people]),
        ]
        if page.trip:
            front.append(f"trip: {_yaml(page.trip)}")
        head = [
            page.weekday,
            f"night before {self._night_link(page.before)}",
            f"night after {self._night_link(page.after)}",
        ]
        if page.country:
            head.append(page.country)
        head.append(link(self.names.claim(page.year)))
        if page.trip:
            head.append(link(page.trip))
        body = [f"# {page.day}", "", DOT.join(head), ""]
        for section in page.sections:
            body.append(section)
        return _front_matter(front) + "\n".join(body)

    def _night_link(self, night: Night) -> str:
        if night.place and night.place in self.places:
            return link(self.names.claim(night.place))
        return night.text

    def _place_text(self, page: PlacePage) -> str:
        p = page.place
        front = [
            f"name: {_yaml(p.name)}",
            f"kind: {_yaml(p.kind)}",
            f"lat: {p.lat}",
            f"lon: {p.lon}",
            f"radius_m: {_number(p.radius_m)}",
        ]
        if p.country:
            front.append(f"country: {_yaml(p.country)}")
        if p.tags:
            front.extend(_yaml_list("tags", list(p.tags)))
        front += [f"days: {len(page.days)}", f"nights: {page.nights}"]
        head = [p.kind, f"{p.lat}, {p.lon}", f"{_number(p.radius_m)} m"]
        if p.country:
            head.append(p.country)
        body = [f"# {self.names.claim(p.name)}", "", DOT.join(head), ""]
        days = []
        for day in sorted(page.days):
            at = page.days[day]
            parts = [self.days[day].weekday]
            if at.stays:
                parts.append(_plural(at.stays, "stay"))
                parts.append(_duration(at.seconds))
            if at.night:
                parts.append("night")
            days.append(f"- {link(self.names.claim(day))} {DOT.join(parts)}")
        body.append("## Days\n\n" + ("\n".join(days) if days else "- none in the window") + "\n")
        people = sorted(page.people.items(), key=lambda kv: (-len(kv[1]), self.people[kv[0]].name))
        if people:
            rows = [
                f"- {link(self.names.claim(self.people[key].name))}{DOT}{_plural(len(days_met), 'day')}"
                for key, days_met in people
            ]
            body.append("## People\n\n" + "\n".join(rows) + "\n")
        if page.trips:
            body.append("## Trips\n\n" + "\n".join(f"- {link(t)}" for t in dict.fromkeys(page.trips)) + "\n")
        return _front_matter(front) + "\n".join(body)

    def _person_text(self, page: PersonPage) -> str:
        days = sorted(page.days)
        front = [f"name: {_yaml(page.name)}"]
        if page.entity:
            front.append(f"id: {_yaml(page.entity)}")
        front += [
            f"days: {len(days)}",
            f"first: {days[0] if days else 'null'}",
            f"last: {days[-1] if days else 'null'}",
            *_yaml_list("places", [p for p, _n in page.places]),
        ]
        body = [f"# {self.names.claim(page.name)}", "", f"{_plural(len(days), 'day')} together", ""]
        rows = []
        for day in days:
            where = []
            for place, text, _sources in page.days[day]:
                label = link(self.names.claim(place)) if place and place in self.places else text
                if label and label not in where:
                    where.append(label)
            parts = [self.days[day].weekday] + [_at(w) for w in where]
            rows.append(f"- {link(self.names.claim(day))} {DOT.join(parts)}")
        body.append("## Days together\n\n" + ("\n".join(rows) if rows else "- none in the window") + "\n")
        if page.places:
            rows = [
                f"- {link(self.names.claim(place))}{DOT}{_plural(n, 'day')}"
                for place, n in page.places
                if place in self.places
            ]
            if rows:
                body.append("## Places\n\n" + "\n".join(rows) + "\n")
        if page.trips:
            body.append("## Trips\n\n" + "\n".join(f"- {link(t)}" for t in dict.fromkeys(page.trips)) + "\n")
        return _front_matter(front) + "\n".join(body)

    def _trip_text(self, page: TripPage) -> str:
        t = page.trip
        front = [
            f"id: {_yaml(t.id)}",
            f"start: {t.start}",
            f"end: {t.end}",
            f"until: {t.until}",
            f"nights: {t.nights}",
            f"in_transit: {t.in_transit}",
        ]
        if page.asset_name:
            front.append(f"asset: {_yaml(page.asset_name)}")
        front += [
            *_yaml_list("route", t.route),
            *_yaml_list("places", t.places),
            *_yaml_list("people", [name for _key, name in page.people]),
        ]
        nights = _plural(t.nights, "night")
        if page.asset_name:
            nights += f" aboard {page.asset_name}"
        head = [nights]
        if t.route:
            head.append("route " + f" {ARROW} ".join(self._route_label(label) for label in t.route))
        for label, flights in (("in", t.flights_in), ("out", t.flights_out)):
            for f in flights:
                head.append(f"{label} {_flight_line(f)}")
        head.append(link(self.names.claim(t.start[:4])))
        body = [f"# {page.stem}", "", DOT.join(head), ""]
        rows = []
        for day in day_range(t.start, t.end):
            page_of_day = self.days.get(day)
            if page_of_day is None:
                rows.append(f"- {day}{DOT}no lines")
                continue
            parts = [page_of_day.weekday, f"night {self._night_link(page_of_day.after)}"]
            if page_of_day.people:
                parts.append("with " + ", ".join(link(self.names.claim(n)) for _k, n in page_of_day.people))
            rows.append(f"- {link(self.names.claim(day))} {DOT.join(parts)}")
        body.append("## Days\n\n" + "\n".join(rows) + "\n")
        if t.places:
            rows = [f"- {self._route_label(p)}" for p in t.places]
            body.append("## Places\n\n" + "\n".join(rows) + "\n")
        if page.people:
            rows = [f"- {link(self.names.claim(name))}" for _key, name in page.people]
            body.append("## People\n\n" + "\n".join(rows) + "\n")
        if t.flights:
            rows = [f"- {f['date']} {_flight_line(f)}" for f in t.flights]
            body.append("## Flights\n\n" + "\n".join(rows) + "\n")
        return _front_matter(front) + "\n".join(body)

    def _route_label(self, label: str) -> str:
        return link(self.names.claim(label)) if label in self.places else label

    def _year_text(self, year: str) -> str:
        pages = [p for p in self.days.values() if p.year == year]
        pages.sort(key=lambda p: p.day)
        front = [f"year: {year}", f"days: {len(pages)}", f"first: {pages[0].day}", f"last: {pages[-1].day}"]
        head = [_plural(len(pages), "day"), f"{pages[0].day} {EN_DASH} {pages[-1].day}", link(ROOT_PAGE)]
        body = [f"# {year}", "", DOT.join(head), ""]
        countries: Counter[str] = Counter(p.country or "unknown" for p in pages)
        rows = [f"- {code}{DOT}{_plural(n, 'day')}" for code, n in countries.most_common()]
        body.append("## Countries\n\n" + "\n".join(rows) + "\n")
        trips = [t for t in self.trips if t.trip.start[:4] == year]
        if trips:
            rows = []
            for t in trips:
                parts = [_plural(t.trip.nights, "night")]
                if t.asset_name:
                    parts[-1] += f" aboard {t.asset_name}"
                if t.people:
                    parts.append("with " + ", ".join(link(self.names.claim(n)) for _k, n in t.people))
                rows.append(f"- {link(t.stem)} {DOT.join(parts)}")
            body.append("## Trips\n\n" + "\n".join(rows) + "\n")
        places = []
        for place in self.places.values():
            days_here = [d for d in place.days if d[:4] == year]
            if days_here:
                nights = sum(1 for d in days_here if place.days[d].night)
                places.append((place.place.name, nights, len(days_here)))
        places.sort(key=lambda p: (-p[1], -p[2], p[0]))
        if places:
            rows = [
                f"- {link(self.names.claim(name))}{DOT}{_nights_days(nights, days)}"
                for name, nights, days in places
            ]
            body.append("## Places\n\n" + "\n".join(rows) + "\n")
        people = []
        for person in self.people.values():
            days_with = [d for d in person.days if d[:4] == year]
            if days_with:
                people.append((person.name, len(days_with)))
        people.sort(key=lambda p: (-p[1], p[0]))
        if people:
            rows = [f"- {link(self.names.claim(name))}{DOT}{_plural(n, 'day')}" for name, n in people]
            body.append("## People\n\n" + "\n".join(rows) + "\n")
        for month in range(1, 13):
            key = f"{year}-{month:02d}"
            of_month = [p for p in pages if p.day.startswith(key)]
            if not of_month:
                continue
            rows = [self._year_row(p) for p in of_month]
            body.append(f"## {MONTHS[month - 1]}\n\n" + "\n".join(rows) + "\n")
        return _front_matter(front) + "\n".join(body)

    def _year_row(self, p: DayPage) -> str:
        parts = [p.weekday[:3], f"night {self._night_link(p.after)}"]
        if p.places:
            parts.append(", ".join(link(self.names.claim(place)) for place in p.places))
        if p.people:
            parts.append("with " + ", ".join(link(self.names.claim(n)) for _k, n in p.people))
        parts.extend(p.flights)
        if p.attached:
            parts.append(_plural(p.attached, "attachment"))
        if p.trip:
            parts.append(link(p.trip))
        return f"- {link(self.names.claim(p.day))} {DOT.join(parts)}"

    def _days_in(self, year: str) -> int:
        return sum(1 for p in self.days.values() if p.year == year)

    def _root_text(self, years: Sequence[str]) -> str:
        front = [f"days: {len(self.days)}", *_yaml_list("years", list(years))]
        body = [
            f"# {ROOT_PAGE}",
            "",
            f"{_plural(len(self.days), 'day')}{DOT}tier {','.join(map(str, self.req.tiers))}",
            "",
        ]
        rows = [f"- {link(self.names.claim(y))}{DOT}{_plural(self._days_in(y), 'day')}" for y in years]
        body.append("## Years\n\n" + "\n".join(rows) + "\n")
        if self.places:
            rows = [
                f"- {link(self.names.claim(p.place.name))}{DOT}{_nights_days(p.nights, len(p.days))}"
                for p in sorted(self.places.values(), key=lambda p: (-p.nights, -len(p.days), p.place.name))
            ]
            body.append("## Places\n\n" + "\n".join(rows) + "\n")
        if self.people:
            rows = [
                f"- {link(self.names.claim(p.name))}{DOT}{_plural(len(p.days), 'day')}"
                for p in sorted(self.people.values(), key=lambda p: (-len(p.days), p.name))
            ]
            body.append("## People\n\n" + "\n".join(rows) + "\n")
        if self.trips:
            rows = [f"- {link(t.stem)}{DOT}{_plural(t.trip.nights, 'night')}" for t in self.trips]
            body.append("## Trips\n\n" + "\n".join(rows) + "\n")
        return _front_matter(front) + "\n".join(body)


def build(lb: Logbook, req: Request, airports: Airports | None = None) -> Build:
    """Read the window and render every page; nothing is written. `stays.SettingsError` when the
    record's settings, places or assets file is not what it should be."""
    builder = _Builder(lb, req, airports)
    builder.read()
    files = builder.files()
    pages = {
        DAYS: len(builder.days),
        PLACES: len(builder.places),
        PEOPLE: len(builder.people),
        TRIPS: len(builder.trips),
        YEARS: len({p.year for p in builder.days.values()}),
    }
    return Build(
        files,
        pages,
        len(builder.days),
        builder.logged,
        builder.crossed,
        {str(t): builder.by_tier.get(t, 0) for t in policy.TIERS},
        dict(sorted(builder.by_kind.items())),
        dict(sorted(builder.held_by_kind.items())),
    )


# -- writing, and the line that says it left -----------------------------------------------------------------


@dataclass(frozen=True)
class Result:
    folder: Path
    written: int
    unchanged: int
    sha256: str  # of the folder as written: every file's digest and path, in path order
    line: Line  # the crossing/v1 line appended


def write(folder: Path, files: Mapping[str, bytes]) -> tuple[int, int]:
    """Write every file whose bytes differ from what is on disk, create the folders on the way,
    leave the rest alone, delete nothing. Returns (written, unchanged). Bytes, never text: a page
    is the same file on Windows and the digest names what is on disk."""
    folder = Path(folder)
    written = unchanged = 0
    for rel in sorted(files):
        path = folder.joinpath(*PurePosixPath(rel).parts)
        raw = files[rel]
        if path.is_file() and path.read_bytes() == raw:
            unchanged += 1
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        written += 1
    return written, unchanged


def digest(files: Mapping[str, bytes]) -> str:
    """The folder's digest: one line per file, `<sha256 of its bytes>  <path>`, in path order, hashed.
    What a crossing's `package_sha256` is for a bundle with a manifest, this is for a folder without."""
    whole = hashlib.sha256()
    for rel in sorted(files):
        whole.update(f"{hashlib.sha256(files[rel]).hexdigest()}  {rel}\n".encode())
    return whole.hexdigest()


def export(lb: Logbook, req: Request, built: Build, folder: Path, generated_at: str) -> Result:
    """Write the folder, then append the crossing line: in that order, so a crash leaves at worst a
    folder no line names, and the next run writes the same files again and does name it."""
    policy.write_default(lb.root)  # the first export writes the default; an existing file is kept
    head = str(lb.meta["head"])
    written, unchanged = write(folder, built.files)
    sha256 = digest(built.files)
    tz = ZoneInfo(str(lb.meta["timezone"]))
    line = lb.append(
        at=generated_at,
        source=crossing.SOURCE,
        kind=crossing.KIND,
        tier=1,
        payload={
            "schema": crossing.LINE_SCHEMA,
            "destination": DESTINATION,
            "bundle_id": uuid7(),
            "window": {"from": _midnight(req.since, tz), "to": _midnight(_day_after(req.until), tz)},
            "tiers": list(req.tiers),
            "counts": built.counts(),
            "policy": {"file": policy.POLICY_FILE.as_posix(), "max_tier": req.max_tier},
            "logbook_head": head,
            "package_sha256": sha256,
            "extra": {
                "vault": {
                    "days": built.days,
                    "pages": dict(built.pages),
                    "files": {"written": written, "unchanged": unchanged, "total": len(built.files)},
                }
            },
        },
        recorded_at=generated_at,
    )
    return Result(Path(folder), written, unchanged, sha256, line)


# -- helpers -----------------------------------------------------------------------------------------------


def _chunks(first: str, last: str) -> Iterator[tuple[str, str]]:
    """The window cut at calendar years: `(first, last)` per year it touches."""
    a, b = date.fromisoformat(first), date.fromisoformat(last)
    for year in range(a.year, b.year + 1):
        start = max(a, date(year, 1, 1))
        end = min(b, date(year, 12, 31))
        yield start.isoformat(), end.isoformat()


def _by_day(rd: Reading) -> dict[str, list[Line]]:
    """The reading's lines by local day, in chain order."""
    out: dict[str, list[Line]] = {}
    for line in rd.lines:
        at = stays.instant(line.get("at"))
        if at is not None:
            out.setdefault(at.astimezone(rd.tz).date().isoformat(), []).append(line)
    return out


def _night(n: Mapping[str, Any], place_names: Iterable[str]) -> Night:
    if n["in_transit"]:
        return Night("in transit", None, False, None)
    where = str(n["where"] or "somewhere")
    place = where if n["aboard"] is None and where in set(place_names) else None
    return Night(where, place, bool(n["home"]), n["aboard"])


def _day_after(day: str) -> str:
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


def _midnight(day: str, tz: ZoneInfo) -> str:
    local = datetime.combine(date.fromisoformat(day), time.min, tzinfo=tz)
    return local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clock(stamp: str, tz: ZoneInfo, day_end: datetime) -> str:
    """`HH:MM` local; `24:00` for the end of the day, so a stay that runs on reads to midnight."""
    instant = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(tz)
    if instant == day_end:
        return "24:00"
    return instant.strftime("%H:%M")


def _flight_text(e: Mapping[str, Any]) -> str:
    route = f"{e.get('from') or '?'} {ARROW} {e.get('to') or '?'}"
    name = f"{e['carrier']} {e['number']} " if e.get("carrier") and e.get("number") else ""
    return f"{PLANE} {name}{route} ({e['evidence']})" if e.get("evidence") else f"{PLANE} {name}{route}"


def _flight_line(f: Mapping[str, Any]) -> str:
    name = f"{f['carrier']} {f['number']} " if f.get("number") else ""
    return f"{name}{f['from']} {ARROW} {f['to']}"


def _named_text(key: str, item: Mapping[str, Any]) -> str:
    if key == "events":
        return f"event: {item['title']}"
    if key == "transcripts":
        return f"transcript: {item['title']}"
    if key == "notes":
        return f"note: {item['text']}"
    if key == "mail":
        return f"mail: {item['subject']} ({_plural(int(item['messages']), 'message')})"
    if key == "calls":
        return f"call: {day_reader.call_text(dict(item))}"
    return f"keeper: {item.get('name')}"


def _at(where: str) -> str:
    """`at [[Home]]`, `at 59.8500,10.6000`; `aboard Solvind` as it stands."""
    return where if where.startswith("aboard ") else f"at {where}"


def _quote(text: str) -> str:
    return "\n".join(f"> {line}".rstrip() for line in text.splitlines())


def _front_matter(fields: Sequence[str]) -> str:
    return "---\n" + "\n".join(fields) + "\n---\n"


def _yaml(value: object) -> str:
    """A YAML scalar: null, a number, or a double-quoted string with `\\` and `"` escaped."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _yaml_list(key: str, values: Sequence[str]) -> list[str]:
    if not values:
        return [f"{key}: []"]
    return [f"{key}:", *(f"  - {_yaml(v)}" for v in values)]


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def _km(metres: float) -> str:
    km = metres / 1000
    return f"{km:.1f} km" if km < 100 else f"{km:,.0f} km"


def _duration(seconds: int) -> str:
    hours, minutes = divmod(max(seconds, 0) // 60, 60)
    if not hours:
        return f"{minutes} min"
    return f"{hours} h {minutes:02d} min" if minutes else f"{hours} h"


def _nights_days(nights: int, days: int) -> str:
    return f"{_plural(nights, 'night')}, {_plural(days, 'day')}"


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"
