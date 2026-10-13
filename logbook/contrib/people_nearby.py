"""`logbook people nearby`: who is where the owner is about to go. A reader (ADR 0013): derived
from the record at its head, by rules alone, never written; it names canonical people only (the
people the record's resolution lines name), never an observed one.

A person is **seen at** a place on a day together (the with module's confirmed set, as `people`
counts it) at one of the owner's stays whose centre lies within the radius of the place (`--radius`,
default 50 km). Per place they are ranked by the days together there, then the days together
anywhere, then the latest real contact (`people_drift`'s definition), then the name; each with the
last day there.

The place is one of three things:

- `PLACE`: `lat,lon`; else a place of `places.json`, by name, case aside; else a city of the
  airports table (`logbook/tables/airports.csv`, the record's own gazetteer), by the city a row's
  municipality names, case and accents aside, at that airport's reference point; else an IATA or
  ICAO code of it. A name none of them knows is refused.
- `--journey ID`: the line with that id, a `journey/v1` (or `trip/v1`) line — its `to`, else its
  `from`, by coordinates when it has them, else by name as above — or a `flight/v1` line, its
  destination airport.
- `--days FROM TO`: the places the owner has planned in those days: every standing calendar entry
  with a location (its coordinates, else its location text, whole or any comma-separated part of
  it, as a `PLACE`), every standing flight dated in them (its destination, a cancelled one left
  out), every standing journey line in them (as `--journey`). A planned place within the radius of
  a home place of `places.json` is home, not a trip, and is left out; two that share a name, or lie
  within 5 km, are one, the first planned first. A location no rule places is listed as unplaced."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..core import day_start, flights, people, places, reading, stays, trips
from ..core.flights import Airport, Airports
from ..core.index import local_date
from ..core.store import Logbook, retractions
from . import people_drift

DEFAULT_RADIUS_KM = 50.0
SAME_KM = 5.0  # two planned places this close are one
JOURNEY_KINDS = ("journey", "trip")  # RFC 0031: readers accept both spellings
EN_DASH = "\u2013"


class NearbyError(ValueError):
    """A place, a journey or a span the reader cannot use."""


@dataclass
class Target:
    """A place to ask about: its label, centre, what named it (`coordinates`, `places`,
    `airports`), and for a planned place the lines that planned it."""

    label: str
    lat: float
    lon: float
    by: str
    planned: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {"label": self.label, "lat": round(self.lat, 4), "lon": round(self.lon, 4), "by": self.by}


# -- the place -----------------------------------------------------------------------------------------------


def place(text: str, known: Sequence[places.Place], airports: Airports) -> Target:
    """`text` as a place: `lat,lon`, a name of `places.json`, a city of the airports table, or an
    airport code. `NearbyError` when it is none of them."""
    found = _place(text, known, airports)
    if found is None:
        raise NearbyError(
            f"{text!r} is no place the record knows: give lat,lon, a name of places.json, a city of the"
            " airports table or an airport code"
        )
    return found


def _place(text: str, known: Sequence[places.Place], airports: Airports) -> Target | None:
    words = " ".join(text.split())
    if not words:
        return None
    match = places.COORDINATES.match(words)
    if match is not None:
        lat, lon = float(match.group(1)), float(match.group(2))
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return Target(f"{lat:.4f},{lon:.4f}", lat, lon, "coordinates")
        return None
    for p in known:
        if p.name.casefold() == words.casefold():
            return Target(p.name, p.lat, p.lon, "places")
    wanted = _fold(words)
    city = [a for a in airports if a.city and _fold(a.city) == wanted]
    if city:
        best = min(city, key=lambda a: (not a.scheduled, a.iata))
        return Target(best.city, best.lat, best.lon, "airports")
    if words.isalpha() and len(words) in (3, 4):
        airport = airports.get(words)
        if airport is not None:
            return Target(airport.city or airport.iata, airport.lat, airport.lon, "airports")
    return None


def _fold(text: str) -> str:
    """Case and accents aside: `Zürich` is `zurich`; a letter of its own (`ø`) stays itself."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c)).strip()


def _location(text: str, known: Sequence[places.Place], airports: Airports) -> Target | None:
    """A calendar entry's location text as a place: whole, else any comma-separated part of it,
    the last first (`Solsiden, Trondheim` is Trondheim)."""
    found = _place(text, known, airports)
    if found is not None:
        return found
    parts = text.split(",")
    for part in reversed(parts) if len(parts) > 1 else ():
        found = _place(part, known, airports)
        if found is not None:
            return found
    return None


def _airport_target(airport: Airport) -> Target:
    return Target(airport.city or airport.iata, airport.lat, airport.lon, "airports")


def _coordinates_target(lat: float, lon: float, known: Sequence[places.Place], airports: Airports) -> Target:
    """A point as a place: the named place it lies in or within 5 km of, else the city of the
    nearest large airport within 30 km (the rollups' label), else its coordinates."""
    near = places.nearest(lat, lon, known)
    if near is not None and near[1] <= trips.NEAR_KM * 1000:
        return Target(near[0].name, lat, lon, "places")
    city = trips.city_near(lat, lon, airports)
    return Target(city or f"{lat:.4f},{lon:.4f}", lat, lon, "coordinates")


def _end(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for key in ("to", "from"):
        value = payload.get(key)
        if isinstance(value, dict) and value:
            return value
    return None


def _of_line(line: Mapping[str, Any], known: Sequence[places.Place], airports: Airports) -> Target | None:
    """Where a journey or a flight line goes: a journey's `to`, else its `from`, by coordinates,
    else by name; a flight's destination airport. None when nothing places it."""
    payload = line.get("payload") or {}
    if line.get("kind") == flights.KIND:
        to = payload.get("to")
        code = (to.get("iata") or to.get("icao")) if isinstance(to, dict) else None
        airport = airports.get(str(code)) if isinstance(code, str) and code else None
        return None if airport is None else _airport_target(airport)
    end = _end(payload)
    if end is None:
        return None
    lat, lon = end.get("latitude"), end.get("longitude")
    if isinstance(lat, int | float) and isinstance(lon, int | float):
        return _coordinates_target(float(lat), float(lon), known, airports)
    name = end.get("name")
    return _location(name, known, airports) if isinstance(name, str) else None


def journey(lb: Logbook, line_id: str, known: Sequence[places.Place], airports: Airports) -> Target:
    """The place a journey or flight line goes to. `NearbyError` for an id the record has not, a
    line of another kind, or one nothing places."""
    with lb.index() as idx:
        line = idx.by_id(line_id.strip())
    if line is None:
        raise NearbyError(f"no line has the id {line_id!r}")
    if line.get("kind") not in (*JOURNEY_KINDS, flights.KIND):
        raise NearbyError(f"{line_id} is a {line.get('kind')} line, not a journey or a flight")
    found = _of_line(line, known, airports)
    if found is None:
        raise NearbyError(f"the {line.get('kind')} line {line_id} names no place the record knows")
    found.planned.append(_planned(line, str(lb.meta["timezone"]), found.label, lb.meta.get(day_start.KEY)))
    return found


def _planned(line: Mapping[str, Any], tz: str, what: str, start: object = None) -> dict[str, Any]:
    return {
        "kind": str(line.get("kind")),
        "day": local_date(str(line["at"]), tz, start),
        "line": str(line["id"]),
        "what": what,
    }


def planned(
    lb: Logbook,
    first: str,
    last: str,
    known: Sequence[places.Place],
    airports: Airports,
    radius_km: float = DEFAULT_RADIUS_KM,
) -> tuple[list[Target], list[dict[str, Any]]]:
    """The places planned in `[first, last]` (local days), away from home, first planned first;
    and the planned lines no rule places, as `unplaced`. Writes nothing."""
    if last < first:
        raise NearbyError(f"--days runs backwards: {first} is after {last}")
    tz, start = str(lb.meta["timezone"]), day_start.of(lb.meta).text  # a line's day: RFC 0036
    candidates: list[tuple[Mapping[str, Any], Target | None, str]] = []
    with lb.index() as idx:
        marks = idx.retractions()
        retracted = frozenset(retractions(marks))
        superseded = idx.superseded("event")
        for line in idx.of_kind("event", first, last):
            id_ = str(line["id"])
            payload = line.get("payload") or {}
            if id_ in retracted or id_ in superseded or payload.get("status") == "cancelled":
                continue
            text = payload.get("location")
            extra = payload.get("extra")
            detail = extra.get("location") if isinstance(extra, dict) else None
            lat = detail.get("latitude") if isinstance(detail, dict) else None
            lon = detail.get("longitude") if isinstance(detail, dict) else None
            if isinstance(lat, int | float) and isinstance(lon, int | float):
                candidates.append(
                    (line, _coordinates_target(float(lat), float(lon), known, airports), "event")
                )
            elif isinstance(text, str) and text.strip():
                candidates.append((line, _location(text, known, airports), text.strip()))
        standing = flights.standing([*idx.by_kind(flights.KIND, first, last), *marks])
        for line in standing.values():
            payload = line.get("payload") or {}
            day = str(payload.get("date") or local_date(str(line["at"]), tz, start))
            if payload.get("cancelled") is True or not first <= day <= last:
                continue
            candidates.append((line, _of_line(line, known, airports), flights.designator_text(payload)))
        for kind in JOURNEY_KINDS:
            gone = idx.superseded(kind)
            for line in idx.of_kind(kind, first, last):
                id_ = str(line["id"])
                if (
                    id_ in retracted
                    or id_ in gone
                    or (line.get("payload") or {}).get("status") == "cancelled"
                ):
                    continue
                candidates.append((line, _of_line(line, known, airports), kind))
    candidates.sort(key=lambda c: (str(c[0]["at"]), int(c[0]["seq"])))
    homes = places.home_places(known)
    found: list[Target] = []
    unplaced: list[dict[str, Any]] = []
    for planned_line, target, what in candidates:
        if target is None:
            unplaced.append(_planned(planned_line, tz, what, start))
            continue
        if any(places.distance_m(target.lat, target.lon, h.lat, h.lon) <= radius_km * 1000 for h in homes):
            continue
        same = next(
            (
                t
                for t in found
                if t.label.casefold() == target.label.casefold()
                or places.distance_m(t.lat, t.lon, target.lat, target.lon) <= SAME_KM * 1000
            ),
            None,
        )
        if same is None:
            same = target
            found.append(target)
        if what in JOURNEY_KINDS:
            what = f"{what} to {target.label}"
        same.planned.append(_planned(planned_line, tz, what, start))
    return found, unplaced


# -- who is there -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Seen:
    person: people.Person
    there: list[str]  # the days together at the place, oldest first
    contact: people_drift.Contact | None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.person.entity,
            "name": self.person.name,
            "days_there": len(self.there),
            "last_there": self.there[-1],
            "days": len(self.person.days),
            "last_real_contact": None if self.contact is None else self.contact.to_json(),
        }


@dataclass(frozen=True)
class Nearby:
    radius_km: float
    places: list[tuple[Target, list[Seen]]]
    span: tuple[str, str] | None = None  # `--days`
    unplaced: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "radius_km": _number(self.radius_km),
            "days": None if self.span is None else {"since": self.span[0], "until": self.span[1]},
            "places": [
                {
                    **target.to_json(),
                    "radius_km": _number(self.radius_km),
                    "from": list(target.planned),
                    "people": [s.to_json() for s in seen],
                }
                for target, seen in self.places
            ],
            "unplaced": list(self.unplaced),
        }


def nearby(
    lb: Logbook,
    targets: Sequence[Target],
    radius_km: float = DEFAULT_RADIUS_KM,
    airports: Airports | None = None,
    span: tuple[str, str] | None = None,
    unplaced: Sequence[dict[str, Any]] = (),
) -> Nearby:
    """Who was seen at each target: the canonical people with a day together at one of the
    owner's stays within `radius_km` of it, ranked. Writes nothing."""
    if not radius_km > 0:
        raise NearbyError("--radius is a distance in km, more than 0")
    whole = reading.record_days(lb)
    if whole is None or not targets:
        return Nearby(radius_km, [(t, []) for t in targets], span, list(unplaced))
    report = people.read(lb, *whole, airports)
    contacts = people_drift.real_contacts(lb, report)
    centres: dict[str, tuple[float, float] | None] = {}
    out = []
    for target in targets:
        seen = []
        for person in report.people:
            there = sorted(
                {s.day for s in person.shared.values() if _within(s.stay, target, radius_km, centres)}
            )
            if there:
                seen.append(Seen(person, there, contacts.get(person.entity)))
        seen.sort(
            key=lambda s: (
                -len(s.there),
                -len(s.person.days),
                _desc(s.contact.day if s.contact else None),
                s.person.name.casefold(),
            )
        )
        out.append((target, seen))
    return Nearby(radius_km, out, span, list(unplaced))


def _within(
    stay_id: str, target: Target, radius_km: float, centres: dict[str, tuple[float, float] | None]
) -> bool:
    if stay_id not in centres:
        try:
            centres[stay_id] = places.parse_stay_id(stay_id)
        except ValueError:
            centres[stay_id] = None
    centre = centres[stay_id]
    return (
        centre is not None
        and stays.distance_m(centre[0], centre[1], target.lat, target.lon) <= radius_km * 1000
    )


# -- text ----------------------------------------------------------------------------------------------------


def rows(found: Nearby) -> Iterator[str]:
    if found.span is not None:
        count = _plural(len(found.places), "place")
        yield f"planned · {found.span[0]} {EN_DASH} {found.span[1]} · {count} away from home"
        if not found.places:
            yield "  nothing planned away from home with a place the record knows"
    for target, seen in found.places:
        head = f"{target.label} · {target.lat:.4f},{target.lon:.4f} · within {_number(found.radius_km)} km"
        head += f" · {_plural(len(seen), 'person', 'people')}"
        if target.planned:
            head += " · " + ", ".join(f"{p['day']} {p['what']}" for p in target.planned)
        yield head
        if not seen:
            yield "  nobody seen there"
        width = max((len(s.person.name) for s in seen), default=0)
        for s in seen:
            parts = [
                f"{_plural(len(s.there), 'day')} there, last seen {s.there[-1]}",
                f"{_plural(len(s.person.days), 'day')} in all",
            ]
            if s.contact is not None:
                parts.append(f"last real contact {s.contact.day} ({s.contact.via})")
            yield f"  {s.person.name:<{width}}  {' · '.join(parts)}"
    for p in found.unplaced:
        yield f"  unplaced  {p['day']} {p['kind']} {p['what']}"


def _desc(day: str | None) -> str:
    """A key that sorts later days first (`people`'s): each digit flipped; no day last."""
    return "".join(chr(ord("9") - ord(c) + ord("0")) if c.isdigit() else c for c in (day or "")) or "~"


def _number(value: float) -> float | int:
    return int(value) if float(value).is_integer() else value


def _plural(n: int, noun: str, plural: str | None = None) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {plural or noun + 's'}"
