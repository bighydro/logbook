"""Google Takeout Maps (your places)/ → the reviews as highlight/v1 (RFC 0022); the saved places as
candidates for `places propose --takeout`, never as lines.

Takeout writes two GeoJSON files under `Takeout/Maps (your places)/`, one Feature per place with
the point in `geometry.coordinates` ([lon, lat]):

    Saved Places.json   the starred and saved places: `properties.Title`, `Published` (when it was
                        saved), the business name and address under `properties.Location`
    Reviews.json        the owner's reviews, in one of two spellings Google has used: the newer
                        `{date, five_star_rating_published, review_text_published, location:
                        {name, address, country_code}, google_maps_url}` and the older `{Published,
                        Star Rating, Review Comment, Location: {Business Name, Address, Country Code,
                        Geo Coordinates}, Google Maps URL}`; the reader looks for both

A saved place is not an observation (nothing happened at an instant): it is a name for coordinates,
which is what `places.json` holds. So `run` writes no line for one; it counts them
(`saved_places_left_to_places_propose`) and `candidates` hands them — name, coordinates, the list
they are in (the file's stem; the `Saved/<list>.csv` lists too through `takeout.places`) and the
day they were saved — to `logbook places propose --takeout`, where the owner adopts one as the name
of a stay, or to `places add` by hand.

A review is the owner's own words on a place at a date, so it is one `highlight/v1` line, tier 2:
`at` the review's date, `title` the place's name (else its address), `quote` the review's text with
`type` `highlight`, or `type` `bookmark` when the owner gave stars and no words; `location` the
address; `extra` carries the `rating`, the Maps `url`, the point as `lat`/`lon` and the `country`.
`raw_id` is `maps-review:<date as spelled>:<sha256(url, else the name)[:16]>`. A review with no date
or no name is skipped and counted. Pure: no network, never writes the source.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from logbook.flights import distance_km

from . import SOURCE, times
from . import places as saved_places

NAME = "google-takeout-maps"
KIND = "highlight"
TIER = 2
SCHEMA = "highlight/v1"
FOLDER = "Maps (your places)"

SAVED_FILE = "Saved Places.json"
REVIEWS_FILE = "Reviews.json"
SUFFIX = ".json"
SNIFF_BYTES = 4096
COLLECTION = "FeatureCollection"
RATING_KEYS = ("five_star_rating_published", "Star Rating", "five_star_rating", "rating")
TEXT_KEYS = ("review_text_published", "Review Comment", "review_text", "comment")
DATE_KEYS = ("date", "Published", "published", "Updated")
URL_KEYS = ("google_maps_url", "Google Maps URL")
LOCATION_KEYS = ("location", "Location")
NAME_KEYS = ("name", "Business Name", "Title", "title")
ADDRESS_KEYS = ("address", "Address")
COUNTRY_KEYS = ("country_code", "Country Code")
SAVED_COUNT = "saved_places_left_to_places_propose"


@dataclass(frozen=True)
class Candidate:
    """A saved place as `places propose --takeout` shows it: a name for coordinates, the list it was
    saved to and the day it was saved (None for a `Saved/` CSV list, which keeps no date)."""

    name: str
    lat: float
    lon: float
    list: str
    saved_at: str | None = None
    address: str | None = None
    metres: float | None = None  # set by `near`: whole metres from the stay asked about

    def to_json(self) -> dict[str, Any]:
        found: dict[str, Any] = {"name": self.name, "lat": self.lat, "lon": self.lon, "list": self.list}
        found["saved_at"] = self.saved_at
        if self.address:
            found["address"] = self.address
        if self.metres is not None:
            found["metres"] = round(self.metres)
        return found


# -- the files -----------------------------------------------------------------------------------------


def sniff(path: Path) -> bool:
    """`Saved Places.json` or `Reviews.json` with at least one place, or a folder holding either.
    Never raises."""
    path = Path(path)
    try:
        if path.is_dir():
            return any(_which(f) is not None for f in sorted(path.iterdir()))
        return _which(path) is not None
    except OSError:
        return False


def _which(path: Path) -> str | None:
    """`SAVED_FILE`, `REVIEWS_FILE`, or None when the file is neither."""
    if not path.is_file() or path.suffix.lower() != SUFFIX:
        return None
    with path.open("rb") as fh:
        head = fh.read(SNIFF_BYTES)
    if COLLECTION.encode() not in head:
        return None
    features = _features(path)
    if not features:
        return None
    if any(_rating(_properties(f)) is not None for f in features):
        return REVIEWS_FILE
    if any(_clean(_properties(f).get("Title")) for f in features):
        return SAVED_FILE
    return None


def _features(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict) or data.get("type") != COLLECTION:
        return []
    return [f for f in data.get("features") or [] if isinstance(f, dict)]


def _properties(feature: dict[str, Any]) -> dict[str, Any]:
    return _object(feature.get("properties"))


def _object(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first(mapping: dict[str, Any], keys: Sequence[str]) -> object:
    for key in keys:
        if mapping.get(key) is not None:
            return mapping[key]
    return None


def _rating(props: dict[str, Any]) -> int | None:
    value = _first(props, RATING_KEYS)
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        rating = int(float(value))
    except ValueError:
        return None
    return rating if 0 <= rating <= 5 else None


def _clean(value: object) -> str | None:
    text = " ".join(str(value).split()) if isinstance(value, str | int | float) else ""
    return text or None


# -- the reviews ---------------------------------------------------------------------------------------


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
) -> Iterator[dict[str, Any]]:
    """One highlight/v1 line draft per review in `path` (`Reviews.json`, or the folder), oldest
    first; the saved places in it counted and never lines. `since` is RFC3339 UTC; `timezone` is
    the record's zone."""
    counts = counts if counts is not None else {}
    path = Path(path)
    files = [path] if path.is_file() else sorted(f for f in path.iterdir() if _which(f) is not None)
    tz = timezone or "UTC"
    drafts: list[dict[str, Any]] = []
    for file in files:
        which = _which(file)
        if which == SAVED_FILE:
            for feature in _features(file):
                if _clean(_properties(feature).get("Title")):
                    _count(counts, SAVED_COUNT)
            continue
        if which != REVIEWS_FILE:
            continue
        for feature in _features(file):
            draft = _draft(feature, tz, counts)
            if draft is not None and (since is None or draft["at"] >= since):
                drafts.append(draft)
    yield from sorted(drafts, key=lambda d: (d["at"], d["payload"]["raw_id"]))


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _draft(feature: dict[str, Any], tz: str, counts: dict[str, int]) -> dict[str, Any] | None:
    props = _properties(feature)
    location = _object(_first(props, LOCATION_KEYS))
    name = _clean(_first(location, NAME_KEYS)) or _clean(_first(props, ("Title", "title")))
    address = _clean(_first(location, ADDRESS_KEYS))
    title = name or address
    if not title:
        _count(counts, "skipped_no_title")
        return None
    at, spelled = times.parse(_first(props, DATE_KEYS))
    if at is None:
        _count(counts, "skipped_no_date")
        return None
    url = _clean(_first(props, URL_KEYS))
    text = _first(props, TEXT_KEYS)
    quote = str(text).replace("\r\n", "\n").strip() if isinstance(text, str) else ""
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": f"maps-review:{spelled}:{hashlib.sha256((url or title).encode('utf-8')).hexdigest()[:16]}",
        "type": "highlight" if quote else "bookmark",
        "title": title,
    }
    if quote:
        payload["quote"] = quote
    if address and address != title:
        payload["location"] = address
    extra: dict[str, Any] = {}
    rating = _rating(props)
    if rating is not None:
        extra["rating"] = rating
    if url:
        extra["url"] = url
    lat, lon = _point(feature, location)
    if lat is not None and lon is not None:
        extra["lat"], extra["lon"] = lat, lon
    country = _clean(_first(location, COUNTRY_KEYS))
    if country:
        extra["country"] = country
    if extra:
        payload["extra"] = extra
    return {"at": at, "end": None, "tz": tz, "source": SOURCE, "kind": KIND, "tier": TIER, "payload": payload}


def _point(feature: dict[str, Any], location: dict[str, Any]) -> tuple[float | None, float | None]:
    """The feature's point, else the coordinates under its location; (None, None) for the (0, 0)
    a place Google could not place gets."""
    lat, lon = saved_places._point(feature.get("geometry"))
    if lat is None:
        geo = _object(location.get("Geo Coordinates"))
        lat, lon = saved_places._coordinates(geo.get("Latitude"), geo.get("Longitude"))
    return lat, lon


# -- the saved places ----------------------------------------------------------------------------------


def candidates(path: Path) -> list[Candidate]:
    """Every saved place with coordinates in `path` — `Saved Places.json`, the `Maps (your places)/`
    folder, a `Saved/<list>.csv` or the Takeout root holding both folders — in file order. A path
    that does not exist raises FileNotFoundError."""
    found: list[Candidate] = []
    for p in saved_places.read(Path(path)):
        if p.lat is None or p.lon is None:
            continue
        found.append(Candidate(p.name, p.lat, p.lon, p.category, p.saved_at, p.address))
    return found


def near(found: Sequence[Candidate], lat: float, lon: float, within_m: float) -> list[Candidate]:
    """The candidates within `within_m` of the point, nearest first, each carrying its distance."""
    close = []
    for c in found:
        metres = distance_km(lat, lon, c.lat, c.lon) * 1000
        if metres <= within_m:
            close.append(Candidate(c.name, c.lat, c.lon, c.list, c.saved_at, c.address, float(round(metres))))
    return sorted(close, key=lambda c: (c.metres or 0, c.name))
