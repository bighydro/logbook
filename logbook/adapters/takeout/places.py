"""`logbook places import-takeout`: Google Maps' saved and starred places → entries for `places.json`.

Not lines. A saved place is not an observation (nothing happened at an instant); it is a name for
coordinates, which is exactly what `<root>/places.json` holds for `derive stays`
(`{"Home": {"lat": 59.91, "lon": 10.75, "radius_m": 120}}`, `logbook.places`). This module
reads the two shapes Takeout writes and proposes entries; the command prints them, and writes
them only with `--write`, adding to the file and never changing an entry already there.

    Takeout/Maps (your places)/Saved Places.json   GeoJSON: one Feature per place, the point in
                                                   `geometry.coordinates` ([lon, lat]), the name
                                                   in `properties.Title`, the address and business
                                                   name under `properties.Location`, the day it was
                                                   saved in `properties.Published`
    Takeout/Saved/<list>.csv                       one list per file (`Favourites`, `Want to go`,
                                                   `Starred places`, the owner's own lists):
                                                   `Title,Note,URL,Comment`; coordinates only
                                                   when the url carries them (`/@lat,lon,` or
                                                   `/search/lat,lon`); a url that names a place
                                                   id instead has none, and such a place is
                                                   proposed but cannot be written

The entry: `{lat, lon, category, address?, note?}`, `category` the list's name (the file's stem).
`read_places` ignores keys it does not know, so the extra ones ride along. Pure: no network, so
a place without coordinates is reported, never geocoded.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from ...core.places import PLACES_FILE
from . import times

__all__ = ["PLACES_FILE", "Proposal", "Report", "merge", "read"]

GEOJSON_SUFFIX = ".json"
CSV_SUFFIX = ".csv"
CSV_HEADER = ("Title", "Note", "URL")
AT_COORDINATES = re.compile(r"/@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
SEARCH_COORDINATES = re.compile(r"/(?:search|place)/(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)")
QUERY_COORDINATES = re.compile(r"[?&]q=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
REVIEW_KEYS = ("five_star_rating_published", "Star Rating")  # a feature of `Reviews.json`: not a saved place


@dataclass(frozen=True)
class Proposal:
    name: str
    lat: float | None
    lon: float | None
    category: str
    address: str | None = None
    note: str | None = None
    saved_at: str | None = None  # the day it was saved (`Published`), when the export says

    def entry(self) -> dict[str, Any]:
        found: dict[str, Any] = {"lat": self.lat, "lon": self.lon, "category": self.category}
        if self.address:
            found["address"] = self.address
        if self.note:
            found["note"] = self.note
        return found


@dataclass
class Report:
    new: list[Proposal] = field(default_factory=list)
    existing: list[Proposal] = field(default_factory=list)
    without_coordinates: list[Proposal] = field(default_factory=list)
    written: bool = False


def read(path: Path) -> list[Proposal]:
    """Every place in `path`: a GeoJSON export, a saved-list CSV, or a folder — walked one level
    into the two Takeout folders too — in file order. A file that is neither is no places; a path
    that does not exist raises FileNotFoundError."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    if path.is_file():
        return _file(path)
    found: list[Proposal] = []
    for child in sorted(path.iterdir()):
        if child.is_file():
            found.extend(_file(child))
        elif child.is_dir() and not child.name.startswith("."):
            for f in sorted(child.iterdir()):
                if f.is_file():
                    found.extend(_file(f))
    return found


def _file(path: Path) -> list[Proposal]:
    suffix = path.suffix.lower()
    if suffix == GEOJSON_SUFFIX:
        return _geojson(path)
    if suffix == CSV_SUFFIX:
        return _saved_list(path)
    return []


def _geojson(path: Path) -> list[Proposal]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        return []
    found: list[Proposal] = []
    for feature in data.get("features") or []:
        if not isinstance(feature, dict):
            continue
        props = _object(feature.get("properties"))
        if any(key in props for key in REVIEW_KEYS):
            continue  # a review (`takeout.maps` reads those); the same file may hold both
        location = _object(props.get("Location"))
        name = (
            _clean(props.get("Title"))
            or _clean(location.get("Business Name"))
            or _clean(location.get("Address"))
        )
        if not name:
            continue
        lat, lon = _point(feature.get("geometry"))
        if lat is None:
            geo = _object(location.get("Geo Coordinates"))
            lat, lon = _coordinates(geo.get("Latitude"), geo.get("Longitude"))
        saved_at = _day(props.get("Published"))
        found.append(
            Proposal(name, lat, lon, path.stem, address=_clean(location.get("Address")), saved_at=saved_at)
        )
    return found


def _day(value: object) -> str | None:
    """The day of an RFC 3339 time the export spells, or None."""
    at, _ = times.parse(value)
    return at[:10] if at else None


def _object(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _point(geometry: object) -> tuple[float | None, float | None]:
    if not isinstance(geometry, dict) or geometry.get("type") != "Point":
        return None, None
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        return None, None
    return _coordinates(coordinates[1], coordinates[0])


def _coordinates(lat: object, lon: object) -> tuple[float | None, float | None]:
    """A usable pair, or (None, None): out of range, unparsable, or the (0, 0) a missing place
    gets."""
    try:
        la, lo = float(str(lat)), float(str(lon))
    except (TypeError, ValueError):
        return None, None
    if not (-90 <= la <= 90 and -180 <= lo <= 180) or (la == 0 and lo == 0):
        return None, None
    return la, lo


def _saved_list(path: Path) -> list[Proposal]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.reader(fh))
    except (OSError, UnicodeDecodeError, csv.Error):
        return []
    if not rows or tuple(cell.strip() for cell in rows[0][:3]) != CSV_HEADER:
        return []
    columns = {name.strip().lower(): i for i, name in enumerate(rows[0])}
    found: list[Proposal] = []
    for row in rows[1:]:
        name = _clean(row[columns["title"]]) if len(row) > columns["title"] else None
        if not name:
            continue
        url = unquote(row[columns["url"]]) if len(row) > columns["url"] else ""
        note = _clean(row[columns["note"]]) if len(row) > columns["note"] else None
        lat, lon = _url_coordinates(url)
        found.append(Proposal(name, lat, lon, path.stem, note=note))
    return found


def _url_coordinates(url: str) -> tuple[float | None, float | None]:
    for pattern in (AT_COORDINATES, SEARCH_COORDINATES, QUERY_COORDINATES):
        m = pattern.search(url)
        if m:
            return _coordinates(m.group(1), m.group(2))
    return None, None


def _clean(value: object) -> str | None:
    text = " ".join(str(value).split()) if value is not None else ""
    return text or None


def merge(root: Path, proposals: list[Proposal], write: bool) -> Report:
    """Sort the proposals against `<root>/places.json`: new names with coordinates, names already
    there (matched case-insensitively, never changed), and places without coordinates. With
    `write`, the new ones are added and the file written; every other key of the file is kept."""
    path = Path(root) / PLACES_FILE
    data: dict[str, Any] = {}
    if path.exists():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError(f"{path} must map a place name to {{lat, lon}}")
        data = loaded
    known = {name.casefold() for name in data}
    report = Report()
    for p in proposals:
        if p.lat is None or p.lon is None:
            report.without_coordinates.append(p)
        elif p.name.casefold() in known:
            report.existing.append(p)
        else:
            known.add(p.name.casefold())
            report.new.append(p)
    if write and report.new:
        for p in report.new:
            data[p.name] = p.entry()
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report.written = True
    return report
