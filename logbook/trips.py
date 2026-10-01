"""Trips, derived from the nights: `logbook trips`.

A trip is a run of consecutive days whose overnight stay is outside every home region (places.json,
kind `home`, or within 400 m of one) or in transit. It has a route (the night places in order: the
named place, else a large airport's name when the stay is within 2 km of it, else the coordinates
with `near <place>, x km` for the nearest named place within 5 km, else the coordinates with the
city of the nearest large airport within 30 km in parentheses, `53.5998,10.0130 (Hamburg)` — the
city only, never the airport's name, so a reader sees where a hotel is; consecutive points within
200 m of each other collapse into the first), its nights, the named places visited and the people
confirmed present (the with module: never the owner, at most `WITH_MAX` names, most evidence
first) between the first day's midnight and the end of the return day, and the flights in (dated
the first day) and out (dated the return day, the day after the last night). An asset trip is one
whose every night was aboard one asset.

A trip is never a line: it is a reader's output, recomputed from the record every time, until the
captain names it, and then the name is a note (ADR 0019). It is not RFC 0020's `trip/v1`, which
is one bought ride, ticket or parking session as the service recorded it: raw evidence, like a
flight line, that a derived trip may one day list beside its flights. Without a place of kind `home` nothing
can be outside home, so there are no trips and the reader says so."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from . import flights as flight_lines
from . import places as named_places
from . import present, stays
from .flights import Airports
from .reading import Reading, window_json

AIRPORT_KM = 2.0  # an unnamed night this close to a large airport is named after it
NEAR_KM = 5.0  # else its coordinates, with `near <place>, x km` for a named place this close
CITY_KM = 30.0  # else its coordinates, with the city of the nearest large airport this close
MERGE_M = 200.0  # consecutive route points this close are one
WITH_MAX = 12  # names listed under "with", most evidence first
EN_DASH = "\u2013"
ARROW = "\u2192"


@dataclass(frozen=True)
class Trip:
    start: str  # the first day whose night is away
    end: str  # the last such day
    until: str  # the return day: the day after the last night
    nights: int
    in_transit: int  # nights with no stay
    route: list[str]
    places: list[str]
    people: list[present.Companion]
    flights: list[dict[str, Any]]  # every flight dated inside the trip, in date order
    asset: str | None
    lines: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"trip:{self.start}:{self.end}"

    @property
    def flights_in(self) -> list[dict[str, Any]]:
        return [f for f in self.flights if f["date"] == self.start]

    @property
    def flights_out(self) -> list[dict[str, Any]]:
        return [f for f in self.flights if f["date"] == self.until]

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "start": self.start,
            "end": self.end,
            "until": self.until,
            "nights": self.nights,
            "in_transit": self.in_transit,
            "asset": self.asset,
            "route": list(self.route),
            "places": list(self.places),
            "people": [
                {"id": c.person, "name": c.name, "confidence": c.confidence, "lines": list(c.lines)}
                for c in self.people
            ],
            "flights_in": self.flights_in,
            "flights_out": self.flights_out,
            "flights": self.flights,
            "lines": list(self.lines),
        }


def trips(reading: Reading) -> tuple[list[Trip], str | None]:
    """The trips of the window, and a warning when none can be derived."""
    if not named_places.home_places(reading.places):
        return [], "no place of kind home in places.json: nothing is away from home, so there are no trips"
    found: list[Trip] = []
    run: list[stays.Night] = []
    for night in reading.nights:
        if night.home:
            found.extend(_trips_of(run, reading))
            run = []
        else:
            run.append(night)
    found.extend(_trips_of(run, reading))
    return found, None


def _trips_of(run: Sequence[stays.Night], reading: Reading) -> list[Trip]:
    """The trip a run of nights away makes: none when every night of it is in transit (a record
    whose last day ends before the night, a gap in the track), since nothing places the owner
    anywhere."""
    if not run or all(n.stay is None for n in run):
        return []
    return [_trip(run, reading)]


def _trip(nights: Sequence[stays.Night], reading: Reading) -> Trip:
    start, end = nights[0].day, nights[-1].day
    until = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
    first = datetime.combine(date.fromisoformat(start), datetime.min.time(), tzinfo=reading.tz)
    last = datetime.combine(date.fromisoformat(until), datetime.max.time(), tzinfo=reading.tz)
    visited = [s for s in reading.owner_stays if s.start < last and s.end > first]
    route = route_of([n.stay for n in nights if n.stay is not None], reading.places, reading.airports)
    places = list(dict.fromkeys(s.place for s in visited if s.place and not stays.is_home(s, reading.places)))
    people = _people(visited, reading)
    flights = [f for f in _flights(reading) if start <= f["date"] <= until]
    aboard = {n.stay.aboard for n in nights if n.stay is not None}
    asset = next(iter(aboard)) if len(aboard) == 1 and None not in aboard else None
    lines = [id_ for n in nights for id_ in _stay_lines(n.stay)]
    lines += [id_ for f in flights for id_ in f["lines"]]
    lines += [id_ for c in people for id_ in c.lines]
    return Trip(
        start,
        end,
        until,
        len(nights),
        sum(1 for n in nights if n.stay is None),
        route,
        places,
        people,
        flights,
        asset,
        list(dict.fromkeys(lines)),
    )


def _stay_lines(stay: stays.Segment | None) -> list[str]:
    if stay is None:
        return []
    return [id_ for id_ in (stay.first_line, stay.last_line) if id_]


def route_of(
    night_stays: Sequence[stays.Segment], places: Sequence[named_places.Place], airports: Airports
) -> list[str]:
    """The route a trip's night stays make: one label per stay (`_label`), consecutive stays within
    `MERGE_M` of each other (or of the same name) folded into the first."""
    route: list[str] = []
    last: stays.Segment | None = None
    for stay in night_stays:
        if last is not None and _same_point(last, stay):
            continue
        label = _label(stay, places, airports)
        if not route or route[-1] != label:
            route.append(label)
        last = stay
    return route


def _same_point(a: stays.Segment, b: stays.Segment) -> bool:
    if a.place is not None or b.place is not None:
        return a.place == b.place
    if a.lat is None or a.lon is None or b.lat is None or b.lon is None:
        return False
    return named_places.distance_m(a.lat, a.lon, b.lat, b.lon) <= MERGE_M


def _label(stay: stays.Segment, places: Sequence[named_places.Place], airports: Airports) -> str:
    if stay.place:
        return stay.place
    assert stay.lat is not None and stay.lon is not None
    airport = airports.nearest(stay.lat, stay.lon, AIRPORT_KM)
    if airport is not None:
        return airport.name
    label = f"{stay.lat:.4f},{stay.lon:.4f}"
    near = named_places.nearest(stay.lat, stay.lon, places)
    if near is not None and near[1] <= NEAR_KM * 1000:
        return f"{label} near {near[0].name}, {near[1] / 1000:.1f} km"
    city = city_near(stay.lat, stay.lon, airports)
    return f"{label} ({city})" if city else label


def city_near(lat: float, lon: float, airports: Airports) -> str | None:
    """The city of the nearest large airport within `CITY_KM` (`Airport.city`: Hamburg for a
    point in Hamburg), for a point that is at no airport and near no named place; None when no
    airport is that close or its row names no municipality. The Day labels an unnamed stay with
    it too."""
    airport = airports.nearest(lat, lon, CITY_KM)
    return airport.city or None if airport is not None else None


def _people(visited: Sequence[stays.Segment], reading: Reading) -> list[present.Companion]:
    merged: dict[tuple[str | None, str], present.Companion] = {}
    for stay in visited:
        for c in present.company(stay, reading.lines, reading.identities, reading.places, reading.owner):
            if c.status != present.CONFIRMED:
                continue
            key = (c.person, "" if c.person else c.name.casefold())
            seen = merged.get(key)
            if seen is None:
                merged[key] = c
            else:
                merged[key] = present.Companion(
                    seen.person,
                    seen.name,
                    seen.status,
                    max(seen.confidence, c.confidence),
                    tuple(dict.fromkeys([*seen.sources, *c.sources])),
                    (*seen.reasons, *c.reasons),
                    tuple(dict.fromkeys([*seen.lines, *c.lines])),
                )
    return sorted(merged.values(), key=lambda c: (-len(c.lines), c.name))[:WITH_MAX]


def _flights(reading: Reading) -> list[dict[str, Any]]:
    standing = flight_lines.standing(reading.of_kind(flight_lines.KIND))
    out = []
    for line in sorted(
        standing.values(), key=lambda line: (str(line["payload"].get("date")), int(line["seq"]))
    ):
        payload = line["payload"]
        out.append(
            {
                "date": str(payload.get("date") or line["at"][:10]),
                "carrier": payload.get("carrier"),
                "number": payload.get("number"),
                "from": _code(payload.get("from")),
                "to": _code(payload.get("to")),
                "evidence": payload.get("evidence"),
                "lines": [str(line["id"])],
            }
        )
    return out


def _code(ref: object) -> str | None:
    if not isinstance(ref, dict):
        return None
    code = ref.get("iata") or ref.get("icao")
    return str(code) if code else None


# -- text ----------------------------------------------------------------------------------------------------


def rows(reading: Reading, found: Sequence[Trip], warning: str | None) -> Iterator[str]:
    window = window_json(reading)
    head = f"trips {window['since']} {EN_DASH} {window['until']}"
    if warning:
        yield f"{head}: {warning}"
        return
    if not found:
        yield f"{head}: no trips"
        return
    yield f"{head}: {_plural(len(found), 'trip')}"
    for trip in found:
        yield from trip_rows(trip)


def trip_rows(trip: Trip) -> Iterator[str]:
    nights = _plural(trip.nights, "night")
    if trip.asset:
        nights += f" aboard {trip.asset}"
    if trip.in_transit:
        nights += f" ({trip.in_transit} in transit)"
    parts = [nights, f"route {f' {ARROW} '.join(trip.route)}" if trip.route else "route unknown"]
    for label, flights in (("in", trip.flights_in), ("out", trip.flights_out)):
        for f in flights:
            name = f"{f['carrier']} {f['number']} " if f["number"] else ""
            parts.append(f"{label} {name}{f['from']} {ARROW} {f['to']}")
    if trip.places:
        parts.append("places " + ", ".join(trip.places))
    if trip.people:
        parts.append("with " + ", ".join(c.name for c in trip.people))
    yield f"  {trip.start} {EN_DASH} {trip.end}  {' · '.join(parts)}"


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"
