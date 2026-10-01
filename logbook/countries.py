"""The country a point is in, coarsely, for `logbook rollup countries`.

The record has no country polygons and asks no server (CLAUDE.md: no network in a reader). The
country of a point is decided, in this order:

1. **The captain's word.** A place in `places.json` whose radius holds the point and that carries
   a `country` (ISO 3166-1 alpha-2) decides. This is the override for everything below.
2. **The nearest major airport's zone.** The airports table (RFC 0013, OurAirports' large
   airports) gives the nearest airport within `WITHIN_KM`; its IANA zone is looked up in
   `logbook/tables/zones.csv`, the zone database's own `zone.tab` (public domain), which files
   every zone under one country. `Europe/Oslo` is Norway, `Europe/Zurich` is Switzerland.
3. **Unknown** otherwise: further than `WITHIN_KM` from any large airport (mid-ocean, the far
   north), or an airport whose zone the table does not list.

The limits, so that nobody mistakes this for geography: a point near a border takes the country
of the nearest *large* airport, not the border's side (Basel's airport is in France; a stay in
Basel reads as `FR` unless a place says `CH`); a country with no large airport in the table
(Liechtenstein, Monaco, San Marino) reads as its neighbour; islands and territories read as the
country their zone is filed under (Svalbard is `SJ` only through a place). Whenever that matters,
name the place and give it a `country`; the place wins, and the method is reported beside every
count."""

from __future__ import annotations

import csv
from collections.abc import Iterable, Sequence
from importlib import resources
from typing import NamedTuple

from .flights import Airports, distance_km
from .places import Place

WITHIN_KM = 300.0
METHODS = ("place", "airport", "unknown")
METHOD_TEXT = (
    "country of the overnight stay: a place with a country in places.json when the stay lies in it,"
    f" else the nearest large airport within {int(WITHIN_KM)} km (airports table) and its zone's country"
    " (zone.tab); coarse near borders and far from airports"
)


class Country(NamedTuple):
    code: str | None  # ISO 3166-1 alpha-2, None when unknown
    method: str  # place, airport or unknown
    by: str | None  # the place's name or the airport's IATA code


class Countries:
    """zone → country, from the bundled table."""

    def __init__(self, rows: Iterable[tuple[str, str]]):
        self._by_zone = {zone: country for zone, country in rows}

    @classmethod
    def load(cls) -> Countries:
        text = (resources.files("logbook") / "tables" / "zones.csv").read_text(encoding="utf-8")
        rows = csv.DictReader(line for line in text.splitlines() if line and not line.startswith("#"))
        return cls((str(row["zone"]), str(row["country"])) for row in rows)

    def of_zone(self, zone: str) -> str | None:
        return self._by_zone.get(zone)

    def __len__(self) -> int:
        return len(self._by_zone)


def country_of(
    lat: float,
    lon: float,
    places: Sequence[Place],
    airports: Airports,
    table: Countries,
    within_km: float = WITHIN_KM,
) -> Country:
    """The country of a point by the rules in the module docstring."""
    for place in places:
        if place.country and distance_km(lat, lon, place.lat, place.lon) * 1000 <= place.radius_m:
            return Country(place.country, "place", place.name)
    airport = airports.nearest(lat, lon, within_km)
    if airport is not None:
        code = table.of_zone(airport.tz)
        if code is not None:
            return Country(code, "airport", airport.iata)
    return Country(None, "unknown", None)
