"""The named places of the record: `<root>/places.json`, read by the readers and edited by
`logbook places`. A setting of the record, not part of the chain (as `assets.json`, ADR 0018): a
place is never a line, and renaming one changes no line. What is in the chain is the naming
itself: `logbook places name` and `logbook places propose --write` append one `note/v1` line per
naming, "named <lat>,<lon> as <name>", so the record says when the captain gave a place its name.

    {"Home": {"lat": 59.9139, "lon": 10.7522, "radius_m": 120, "kind": "home", "tags": ["family"]}}

`kind` is `home`, `asset-berth` or `other` (absent is `other`); home regions are the places of kind
`home`, and a night is at home when its stay lies in one. `tags` is free text. Keys of an entry
this module does not know are kept when the file is rewritten (SPEC §1 for `logbook.json`).

`propose` is a reader (ADR 0013): the owner's unnamed stays of a window, grouped by place and ranked
by hours, each with the nearest known place, the Google Timeline visits that overlap it when the
record holds Takeout timeline lines, and a suggested name. The stays come from the index alone
(`reading.owner_track`): the owner's points, the evidence and the retractions are columns of it, so
a window of years over a record of millions of lines is read in seconds and no month file is opened;
only the Timeline visit lines are read whole, found through the index by their `raw_id`. It appends
nothing; `--write` appends the namings the captain accepts, through `Logbook.append`."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple

from .chain import Line
from .flights import distance_km

PLACES_FILE = "places.json"
KINDS = ("home", "asset-berth", "other")
HOME, BERTH, OTHER = KINDS
DEFAULT_RADIUS_M = 150.0
GROUP_M = 300.0  # unnamed stays this close are one proposal
STAY_ID = re.compile(r"^(?:stay|stop):[^@]+@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)$")
COORDINATES = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
COUNTRY = re.compile(r"^[A-Z]{2}$")
TIMELINE_SOURCE = "google-takeout"
TIMELINE_VISIT_RAW_ID = "visit:"  # the takeout adapter's raw_id of a visit edge: `visit:<time>:start|end`


class PlaceError(ValueError):
    """The places file is not what it should be, or an entry is not a place."""


class Place(NamedTuple):
    name: str
    lat: float
    lon: float
    radius_m: float
    kind: str = OTHER
    tags: tuple[str, ...] = ()
    country: str | None = None  # ISO 3166-1 alpha-2, the captain's word for `rollup countries`

    def to_json(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "lat": self.lat,
            "lon": self.lon,
            "radius_m": _number(self.radius_m),
            "kind": self.kind,
        }
        if self.tags:
            entry["tags"] = list(self.tags)
        if self.country:
            entry["country"] = self.country
        return entry

    @classmethod
    def from_json(cls, name: str, entry: object, default_radius_m: float, where: str) -> Place:
        if not isinstance(entry, dict):
            raise PlaceError(f"{where}: {name!r} must be an object with lat and lon")
        try:
            lat, lon = float(entry["lat"]), float(entry["lon"])
            radius = float(entry.get("radius_m", default_radius_m))
        except (KeyError, TypeError, ValueError) as e:
            raise PlaceError(f"{where}: {name!r} needs numeric lat and lon (and radius_m)") from e
        kind = entry.get("kind", OTHER)
        tags = entry.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise PlaceError(f"{where}: {name!r}: tags must be a list of strings")
        country = entry.get("country")
        return cls(str(name), lat, lon, radius, str(kind), tuple(tags), country).check(where)

    def check(self, where: str = PLACES_FILE) -> Place:
        if not self.name.strip():
            raise PlaceError(f"{where}: a place needs a name")
        if not (-90 <= self.lat <= 90 and -180 <= self.lon <= 180):
            raise PlaceError(f"{where}: {self.name!r} has coordinates off the earth")
        if not self.radius_m > 0:
            raise PlaceError(f"{where}: {self.name!r} needs a positive radius")
        if self.kind not in KINDS:
            raise PlaceError(
                f"{where}: {self.name!r}: kind must be one of {', '.join(KINDS)}, not {self.kind!r}"
            )
        return self


def _number(value: float) -> float | int:
    return int(value) if float(value).is_integer() else value


# -- the file ---------------------------------------------------------------------------------------------


def path_of(root: Path) -> Path:
    return Path(root) / PLACES_FILE


def _document(root: Path) -> dict[str, Any]:
    path = path_of(root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise PlaceError(f"{path} is not JSON: {e}") from e
    if not isinstance(data, dict):
        raise PlaceError(f"{path} must map a place name to {{lat, lon, radius_m, kind, tags}}")
    return data


def read(root: Path, default_radius_m: float = DEFAULT_RADIUS_M) -> list[Place]:
    """Every place in file order; none when there is no file. PlaceError, naming the file, when
    it is not a places file."""
    path = path_of(root)
    return [
        Place.from_json(name, entry, default_radius_m, str(path)) for name, entry in _document(root).items()
    ]


def add(root: Path, place: Place) -> Path:
    """Add one place to the file, keeping every other entry as written; refuses a name already
    taken (case-insensitively, so `home` and `Home` are one place). Returns the path."""
    place = place.check()
    document = _document(root)
    for name in document:
        if name.casefold() == place.name.casefold():
            raise PlaceError(f"{name!r} is already a place; pick another name or edit {path_of(root)}")
    document[place.name] = place.to_json()
    path = path_of(root)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


# -- geometry ---------------------------------------------------------------------------------------------


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return distance_km(lat1, lon1, lat2, lon2) * 1000


def home_places(places: Iterable[Place]) -> list[Place]:
    return [p for p in places if p.kind == HOME]


def at_home(lat: float, lon: float, places: Iterable[Place]) -> Place | None:
    """The home place whose radius holds the point, else None."""
    for place in home_places(places):
        if distance_m(lat, lon, place.lat, place.lon) <= place.radius_m:
            return place
    return None


def nearest(lat: float, lon: float, places: Iterable[Place]) -> tuple[Place, float] | None:
    """The closest known place and the distance to it in metres; None when there are no places."""
    best: tuple[Place, float] | None = None
    for place in places:
        m = distance_m(lat, lon, place.lat, place.lon)
        if best is None or m < best[1]:
            best = (place, m)
    return best


def parse_stay_id(text: str) -> tuple[float, float]:
    """`lat,lon`, or a stay id as `propose` prints it (`stay:owner:20260610T1000Z@59.9200,10.7400`),
    as coordinates. ValueError for anything else, or coordinates off the earth."""
    match = STAY_ID.match(text.strip()) or COORDINATES.match(text)
    if match is None:
        raise ValueError(
            f"{text!r} is neither lat,lon nor a stay id like stay:owner:20260610T1000Z@59.92,10.74"
        )
    lat, lon = float(match.group(1)), float(match.group(2))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError(f"{text!r}: coordinates off the earth")
    return lat, lon


def naming_text(lat: float, lon: float, name: str) -> str:
    """The text of the note/v1 line a naming appends: `named <lat>,<lon> as <name>`."""
    return f"named {_coordinate(lat)},{_coordinate(lon)} as {name}"


def _coordinate(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-") else "0"


# -- proposals --------------------------------------------------------------------------------------------


class TimelineVisit(NamedTuple):
    start: datetime
    end: datetime
    lat: float
    lon: float
    place_id: str | None
    semantic_type: str | None
    probability: float | None
    line: str

    def to_json(self) -> dict[str, Any]:
        return {
            "start": _stamp(self.start),
            "end": _stamp(self.end),
            "lat": self.lat,
            "lon": self.lon,
            "place_id": self.place_id,
            "semantic_type": self.semantic_type,
            "probability": self.probability,
            "line": self.line,
        }


def timeline_visits(lines: Iterable[Line]) -> list[TimelineVisit]:
    """The Google Timeline visits the takeout adapter wrote as location lines (`extra.segment`
    `visit`, the `start` edge, the span under `extra.segment_start` / `segment_end`)."""
    visits: list[TimelineVisit] = []
    for line in lines:
        if line.get("kind") != "location" or line.get("source") != TIMELINE_SOURCE:
            continue
        payload = line.get("payload") or {}
        extra = payload.get("extra") or {}
        if not isinstance(extra, dict) or extra.get("segment") != "visit" or extra.get("edge") != "start":
            continue
        start, end = _instant(extra.get("segment_start")), _instant(extra.get("segment_end"))
        lat, lon = payload.get("lat"), payload.get("lon")
        if (
            start is None
            or end is None
            or not isinstance(lat, int | float)
            or not isinstance(lon, int | float)
        ):
            continue
        candidate = (
            (extra.get("visit") or {}).get("topCandidate") if isinstance(extra.get("visit"), dict) else None
        )
        candidate = candidate if isinstance(candidate, dict) else {}
        probability = candidate.get("probability")
        visits.append(
            TimelineVisit(
                start,
                end,
                float(lat),
                float(lon),
                _text(candidate.get("placeId")),
                _text(candidate.get("semanticType")),
                float(probability) if isinstance(probability, int | float) else None,
                str(line.get("id")),
            )
        )
    return visits


@dataclass(frozen=True)
class Stay:
    """What `propose` needs of a stay: the reader passes `stays.Segment`s through `stay_of`."""

    id: str
    start: datetime
    end: datetime
    lat: float
    lon: float
    aboard: str | None
    first_line: str | None
    last_line: str | None
    points: int

    @property
    def hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600


@dataclass(frozen=True)
class Proposal:
    lat: float
    lon: float
    hours: float
    stays: list[Stay]
    nearest: tuple[Place, float] | None
    timeline: list[TimelineVisit]
    suggested: str
    aboard: str | None

    @property
    def id(self) -> str:
        return self.stays[0].id

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "lat": round(self.lat, 6),
            "lon": round(self.lon, 6),
            "hours": round(self.hours, 2),
            "stays": [s.id for s in self.stays],
            "first": _stamp(min(s.start for s in self.stays)),
            "last": _stamp(max(s.end for s in self.stays)),
            "aboard": self.aboard,
            "nearest": None
            if self.nearest is None
            else {
                "name": self.nearest[0].name,
                "kind": self.nearest[0].kind,
                "metres": round(self.nearest[1]),
            },
            "timeline": [v.to_json() for v in self.timeline],
            "suggested": self.suggested,
            "lines": {
                "first": self.stays[0].first_line,
                "last": self.stays[-1].last_line,
                "points": sum(s.points for s in self.stays),
                "timeline": [v.line for v in self.timeline],
            },
        }


def propose(
    stays: Sequence[Stay], places: Sequence[Place], visits: Sequence[TimelineVisit], group_m: float = GROUP_M
) -> list[Proposal]:
    """Unnamed stays grouped by place (within `group_m` of the group's first stay) and ranked by
    total hours; each with the nearest known place, the timeline visits overlapping any of its
    stays, and a suggested name. `stays` are the owner's unnamed stays, in time order."""
    groups: list[list[Stay]] = []
    for stay in stays:
        for group in groups:
            if distance_m(stay.lat, stay.lon, group[0].lat, group[0].lon) <= group_m:
                group.append(stay)
                break
        else:
            groups.append([stay])
    proposals = []
    for group in groups:
        hours = sum(s.hours for s in group)
        weight = hours or len(group)
        lat = sum(s.lat * (s.hours or 1) for s in group) / weight
        lon = sum(s.lon * (s.hours or 1) for s in group) / weight
        near = nearest(lat, lon, places)
        overlapping = [
            v
            for v in visits
            if any(v.start < s.end and v.end > s.start for s in group)
            and distance_m(v.lat, v.lon, lat, lon) <= group_m
        ]
        aboard = _aboard(group)
        proposals.append(
            Proposal(lat, lon, hours, group, near, overlapping, _suggest(near, overlapping, aboard), aboard)
        )
    proposals.sort(key=lambda p: (-p.hours, p.stays[0].start))
    return proposals


def _aboard(group: Sequence[Stay]) -> str | None:
    """The asset the group's stays were aboard, when most of its hours were aboard one."""
    hours: dict[str, float] = {}
    for s in group:
        if s.aboard:
            hours[s.aboard] = hours.get(s.aboard, 0) + s.hours
    if not hours:
        return None
    asset, aboard_hours = max(hours.items(), key=lambda kv: kv[1])
    return asset if aboard_hours * 2 >= sum(s.hours for s in group) else None


def _suggest(near: tuple[Place, float] | None, visits: Sequence[TimelineVisit], aboard: str | None) -> str:
    """A timeline visit's semantic type, title-cased (`Restaurant`); else `aboard <asset>`; else
    `near <place>` for a known place within two kilometres; else nothing."""
    for visit in visits:
        if visit.semantic_type:
            return visit.semantic_type.replace("_", " ").title()
    if aboard:
        return f"aboard {aboard}"
    if near is not None and near[1] <= 2000:
        return f"near {near[0].name}"
    return ""


def _instant(text: object) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def _stamp(instant: datetime) -> str:
    from datetime import UTC

    return instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def by_name(places: Iterable[Place]) -> Mapping[str, Place]:
    return {p.name: p for p in places}
