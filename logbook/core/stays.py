"""Stays and moves, derived from `location/v1` lines: the first reader of the record.

A stay is a span at one place; a stop is a short one with nothing attached; a move is what lies
between two of them. Everything here is a function of the lines it is given — the same lines give
the same segments — and nothing is ever appended to the record by it (ADR 0013: derived is
disposable). The thresholds live in `<root>/policy/stays.json`, written with defaults on the first
run and never rewritten; an optional `<root>/places.json` names places; `<root>/assets.json`
(ADR 0018) names the subjects whose tracks are derived beside the owner's.

The rules:

- Points of one subject are clustered in time order. A point joins the current cluster when it
  is within the place's radius (a named place) or the default radius of the cluster's first point
  (an anchor, not a running centroid, so a slow walk cannot drift a cluster along), however long
  after the cluster's last point it comes: the tracker sends no points while the owner is still,
  so a silence whose next point is back inside the radius is time spent at the place, never a
  gap row. A single point outside whose successor is back inside is GPS noise and is dropped. A
  cluster shorter than `stop_min_s` is travel, not a stop.
- A cluster lasts until the tracker's next point when that point comes after a silence of
  `merge_gap_s` or more and lies within a short walk of the cluster's last point — `walk_max_kmh`
  for `merge_gap_s`, 1.2 km by default, the hop a tracker reporting every `merge_gap_s` can miss:
  the silence is read as stillness, as the tracker's behaviour says, so the stay held until the
  tracker spoke again, even when that is the next morning and the first point is already on the
  way out. A next point farther than that is travel the tracker did not see (a flight with the
  phone off, a night train); that silence says nothing, and the cluster ends at its last point.
  With the tracker reporting as usual, a cluster ends at its last point and the move starts there.
- `merge_gap_s` governs an excursion: two consecutive clusters at the same place whose gap is
  under it (the owner steps out of the radius and is back, a burst of noise) are one stay; back
  after `merge_gap_s` or more is two stays with a move between. It is also the length of a gap
  that counts as a silence (above). A gap at the same place never splits a stay, whatever its
  length.
- A cluster is a stay when it lasts `stay_min_s` or longer, or when any evidence is attached to
  it: an event, transcript, note, call, message or photo whose instant falls inside it (a line with
  an `end` counts when its span overlaps). Evidence promotes; duration is the fallback. Otherwise
  it is a stop, kept and flagged. Evidence is the owner's, so only the owner's clusters are promoted.
- A move spans from the end of one cluster to the start of the next: its distance is measured along
  the points between them, its mode from the average speed (walk, car, train, flight), or flight
  when a gap starts and ends near airports (the flights table, RFC 0013), or, when the owner is
  aboard an asset, by the asset's kind (a yacht moves by boat, an aircraft by flight, a car by car).
- The owner is aboard an asset when the asset's own positions lie within the radius of the
  owner's points for `aboard_min_s` (20 minutes by default) or longer: during a stay, the asset's
  points in that span within the stay's radius, measured from the first such point to the last;
  during a move, at least half the owner's points within the radius of the asset's position at
  that instant — read between the asset's two fixes around it when they are no more than twice
  `aboard_window_s` apart (an AIS fix every ten minutes places a boat under way well enough), else
  the nearest fix within `aboard_window_s` — measured across the matched points. A run of
  consecutive segments matched to one asset is aboard it when the matched time adds up to the
  minimum; a boat that passes the quay once is not boarded. Aboard is the owner's relation to the
  asset (ADR 0018 rule 3); an asset's own segments never carry it.
- A stay aboard is a container (`fold`): the run of the owner's stays and moves aboard one asset is
  one stay `aboard <asset>`, from the first's start to the last's end, with the run inside it
  (`Segment.inside`) — a berth, a passage, an anchorage — so the asset's movement never fragments
  the owner's stay. Its centre is that of the inner stay the owner spent longest at. A run that is
  one move (a passage walked on and off) stays a move.
- The overnight stay of a day is the owner's stay with the longest overlap of the night window,
  22:00 to 08:00 next morning by default, a stay aboard counting whole; when no overlap reaches
  `stay_min_s`, the day is in transit. A night aboard names the asset and carries the asset's
  position: the inner stay that held the longest part of the night (`Night.inside`).
"""

from __future__ import annotations

import json
import math
from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from operator import attrgetter
from pathlib import Path, PurePosixPath
from typing import Any, NamedTuple
from zoneinfo import ZoneInfo

from . import assets as registry
from . import places as registry_of_places
from .chain import Line
from .flights import Airports, distance_km
from .places import Place
from .store import RETRACTION, retractions

SETTINGS_FILE = PurePosixPath("policy/stays.json")  # record-relative
PLACES_FILE = registry_of_places.PLACES_FILE
EVIDENCE = ("event", "transcript", "note", "call", "message", "photo")
STAY, STOP, MOVE = "stay", "stop", "move"
MODES = ("walk", "car", "train", "boat", "flight")
KIND_MODE = {"yacht": "boat", "aircraft": "flight", "car": "car"}  # an asset's kind decides its mode


class SettingsError(ValueError):
    """The settings file, the places file or the asset registry is not what it should be."""


# -- settings ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Settings:
    stay_min_s: int = 1200  # a span this long is a stay by duration alone
    stop_min_s: int = 180  # a cluster shorter than this is travel, not a stop
    merge_gap_s: int = 600  # out of the radius and back within this: one stay; a gap this long is a silence
    radius_m: float = 150.0  # the radius of an unnamed place
    airport_km: float = 8.0  # a point this close to an airport is at it
    night: tuple[str, str] = ("22:00", "08:00")  # the window the overnight stay is chosen in
    walk_max_kmh: float = 7.0
    car_max_kmh: float = 130.0
    flight_min_kmh: float = 150.0
    aboard_window_s: int = 300  # how far from an asset fix, in time, its position is still trusted
    aboard_min_s: int = 1200  # the asset within the owner's radius this long, and the owner is aboard

    def to_json(self) -> dict[str, Any]:
        return {
            "stay_min_s": self.stay_min_s,
            "stop_min_s": self.stop_min_s,
            "merge_gap_s": self.merge_gap_s,
            "radius_m": _number(self.radius_m),
            "airport_km": _number(self.airport_km),
            "night": list(self.night),
            "modes": {
                "walk_max_kmh": _number(self.walk_max_kmh),
                "car_max_kmh": _number(self.car_max_kmh),
                "flight_min_kmh": _number(self.flight_min_kmh),
            },
            "aboard_window_s": self.aboard_window_s,
            "aboard_min_s": self.aboard_min_s,
        }

    @classmethod
    def from_json(cls, data: object, where: str) -> Settings:
        if not isinstance(data, dict):
            raise SettingsError(f"{where} must be a JSON object")
        modes = data.get("modes", {})
        if not isinstance(modes, dict):
            raise SettingsError(f"{where}: modes must be an object")
        night = data.get("night", list(cls.night))
        if not (isinstance(night, list) and len(night) == 2 and all(_clock_ok(t) for t in night)):
            raise SettingsError(f'{where}: night must be two clock times, like ["22:00", "08:00"]')
        try:
            return cls(
                stay_min_s=_seconds(data, "stay_min_s", cls.stay_min_s, where),
                stop_min_s=_seconds(data, "stop_min_s", cls.stop_min_s, where),
                merge_gap_s=_seconds(data, "merge_gap_s", cls.merge_gap_s, where),
                radius_m=_positive(data, "radius_m", cls.radius_m, where),
                airport_km=_positive(data, "airport_km", cls.airport_km, where),
                night=(str(night[0]), str(night[1])),
                walk_max_kmh=_positive(modes, "walk_max_kmh", cls.walk_max_kmh, where),
                car_max_kmh=_positive(modes, "car_max_kmh", cls.car_max_kmh, where),
                flight_min_kmh=_positive(modes, "flight_min_kmh", cls.flight_min_kmh, where),
                aboard_window_s=_seconds(data, "aboard_window_s", cls.aboard_window_s, where),
                aboard_min_s=_seconds(data, "aboard_min_s", cls.aboard_min_s, where),
            )
        except (TypeError, ValueError) as e:
            raise SettingsError(f"{where}: {e}") from e


def _number(value: float) -> float | int:
    return int(value) if float(value).is_integer() else value


def _clock_ok(text: object) -> bool:
    try:
        time.fromisoformat(str(text))
    except ValueError:
        return False
    return isinstance(text, str)


def _seconds(data: Mapping[str, Any], key: str, default: int, where: str) -> int:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise SettingsError(f"{where}: {key} must be a number of seconds, not {value!r}")
    return int(value)


def _positive(data: Mapping[str, Any], key: str, default: float, where: str) -> float:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise SettingsError(f"{where}: {key} must be a positive number, not {value!r}")
    return float(value)


def settings_path(root: Path) -> Path:
    return Path(root).joinpath(*SETTINGS_FILE.parts)


def write_default_settings(root: Path) -> Path:
    """Write the defaults where no settings file exists; never overwrite one. Returns the path."""
    path = settings_path(root)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(Settings().to_json(), indent=2) + "\n", encoding="utf-8")
    return path


def read_settings(root: Path) -> Settings:
    """The settings as written, or the defaults when the file does not exist yet."""
    path = settings_path(root)
    if not path.exists():
        return Settings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise SettingsError(f"{path} is not JSON: {e}") from e
    return Settings.from_json(data, str(path))


# -- places and assets -----------------------------------------------------------------------------------


def read_places(root: Path, default_radius_m: float) -> list[Place]:
    """`<root>/places.json` through `logbook.places` (`{"Home": {"lat": 59.91, "lon": 10.75,
    "radius_m": 120, "kind": "home"}}`, the radius and kind optional). An absent file is no places."""
    try:
        return registry_of_places.read(root, default_radius_m)
    except registry_of_places.PlaceError as e:
        raise SettingsError(str(e)) from e


def read_assets(root: Path) -> dict[str, registry.Asset]:
    """The asset registry (ADR 0018) by id, through `logbook.assets`; absent is no assets."""
    try:
        return {asset.id: asset for asset in registry.read(root)}
    except registry.AssetError as e:
        raise SettingsError(str(e)) from e


# -- airports ---------------------------------------------------------------------------------------------


def airport_near(airports: Airports, lat: float, lon: float, within_km: float) -> str | None:
    """The IATA code of the airport within `within_km` of a point, from the flights table."""
    airport = airports.nearest(lat, lon, within_km)
    return None if airport is None else airport.iata


# -- geometry ---------------------------------------------------------------------------------------------


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres (`flights.distance_km`, the one haversine in the package)."""
    return distance_km(lat1, lon1, lat2, lon2) * 1000


# -- points, evidence, segments -----------------------------------------------------------------------


class Point(NamedTuple):
    at: datetime
    lat: float
    lon: float
    subject: str | None
    seq: int
    id: str = ""


class Evidence(NamedTuple):
    at: datetime
    end: datetime | None
    kind: str


@dataclass(frozen=True)
class Segment:
    kind: str  # stay, stop or move
    subject: str | None
    start: datetime
    end: datetime
    points: int
    lat: float | None = None  # stays and stops: the centroid
    lon: float | None = None
    place: str | None = None
    attached: dict[str, int] = field(default_factory=dict)
    promoted: bool = False  # a stay by evidence, not by duration
    aboard: str | None = None
    distance_m: float | None = None  # moves
    mode: str | None = None
    airports: tuple[str, ...] = ()
    first_line: str | None = None  # the ids of the first and last location line of the segment
    last_line: str | None = None
    first_seq: int | None = None  # and their seqs, for a reader whose points carry no id (the index's)
    last_seq: int | None = None
    inside: tuple[Segment, ...] = ()  # a stay aboard an asset: the owner's run of segments aboard it

    @property
    def duration_s(self) -> int:
        return int((self.end - self.start).total_seconds())

    @property
    def id(self) -> str:
        """A derived id a recompute reproduces (ARCHITECTURE: derived is disposable, ids are
        stable): the kind, the subject, the start to the minute, and for a stay or stop its
        centre, `stay:owner:20260610T1000Z@59.9200,10.7400`. `places.parse_stay_id` reads it."""
        start = self.start.astimezone(UTC).strftime("%Y%m%dT%H%MZ")
        head = f"{self.kind}:{self.subject or 'owner'}:{start}"
        if self.kind == MOVE or self.lat is None or self.lon is None:
            return head
        return f"{head}@{self.lat:.4f},{self.lon:.4f}"

    def to_json(self, tz: ZoneInfo) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "subject": self.subject,
            "start": _stamp(self.start),
            "end": _stamp(self.end),
            "start_local": self.start.astimezone(tz).isoformat(timespec="seconds"),
            "end_local": self.end.astimezone(tz).isoformat(timespec="seconds"),
            "duration_s": self.duration_s,
            "points": self.points,
            "aboard": self.aboard,
            "lines": {"first": self.first_line, "last": self.last_line, "points": self.points},
        }
        if self.kind == MOVE:
            out["distance_m"] = None if self.distance_m is None else round(self.distance_m)
            out["mode"] = self.mode
            out["airports"] = list(self.airports)
        else:
            out["lat"] = None if self.lat is None else round(self.lat, 6)
            out["lon"] = None if self.lon is None else round(self.lon, 6)
            out["place"] = self.place
            out["attached"] = dict(self.attached)
            out["promoted"] = self.promoted
        if self.inside:
            out["inside"] = [s.to_json(tz) for s in self.inside]
        return out


@dataclass(frozen=True)
class Night:
    day: str
    stay: Segment | None
    home: bool = False  # the stay lies in a home region (places.json, kind `home`)
    inside: Segment | None = None  # a night aboard: the inner segment that held the longest part of it

    @property
    def in_transit(self) -> bool:
        return self.stay is None

    @property
    def aboard(self) -> str | None:
        return None if self.stay is None else self.stay.aboard

    @property
    def innermost(self) -> Segment | None:
        """The stay the night's place is read from: the inner stay of a night aboard (where the
        asset lay), else the stay itself. A night whose longest part was a passage falls back to
        the stay aboard, whose centre is the anchorage the owner spent longest at."""
        if self.inside is not None and self.inside.kind != MOVE:
            return self.inside
        return self.stay

    @property
    def position(self) -> tuple[float, float] | None:
        """The night's position: the asset's for a night aboard, else the stay's centre."""
        at = self.innermost
        if at is None or at.lat is None or at.lon is None:
            return None
        return at.lat, at.lon

    def to_json(self, tz: ZoneInfo) -> dict[str, Any]:
        position = self.position
        return {
            "day": self.day,
            "stay": None if self.stay is None else self.stay.to_json(tz),
            "in_transit": self.in_transit,
            "home": self.home,
            "aboard": self.aboard,
            "inside": None if self.inside is None else self.inside.to_json(tz),
            "position": None
            if position is None
            else {"lat": round(position[0], 6), "lon": round(position[1], 6)},
        }


@dataclass(frozen=True)
class Derived:
    segments: list[Segment]  # every subject's, the owner's first, each in time order
    subjects: list[str | None]  # None is the owner; then asset ids, sorted
    noise_points: int
    folded: list[Segment] = field(default_factory=list)  # the owner's, a run aboard one stay (`fold`)


def _stamp(instant: datetime) -> str:
    return instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def instant(text: object) -> datetime | None:
    """An RFC3339 stamp as an aware datetime; None when it is not one (a reader skips it, SPEC §3.2)."""
    if not isinstance(text, str):
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def _split(lines: Iterable[Line]) -> tuple[dict[str | None, list[Point]], list[Evidence]]:
    """Location lines by subject (each track sorted by instant then seq) and the owner's evidence,
    retracted lines and retraction lines left out (RFC 0003)."""
    kept = list(lines)
    retracted = retractions(kept)
    tracks: dict[str | None, list[Point]] = {}
    evidence: list[Evidence] = []
    for line in kept:
        if line.get("kind") == RETRACTION or line.get("id") in retracted:
            continue
        at = instant(line.get("at"))
        if at is None:
            continue
        payload = line.get("payload") or {}
        if line.get("kind") == "location":
            lat, lon = payload.get("lat"), payload.get("lon")
            if not isinstance(lat, int | float) or not isinstance(lon, int | float):
                continue
            if (
                isinstance(lat, bool)
                or isinstance(lon, bool)
                or not (math.isfinite(lat) and math.isfinite(lon))
            ):
                continue
            subject = payload.get("subject")
            subject = subject if isinstance(subject, str) and subject else None
            tracks.setdefault(subject, []).append(
                Point(at, float(lat), float(lon), subject, int(line.get("seq", 0)), str(line.get("id", "")))
            )
        elif line.get("kind") in EVIDENCE:
            evidence.append(Evidence(at, instant(line.get("end")), str(line["kind"])))
    return tracks, evidence


# -- clustering --------------------------------------------------------------------------------------------


@dataclass
class _Cluster:
    members: list[int]  # indices into the track
    place: Place | None
    anchor_lat: float
    anchor_lon: float


def _place_of(lat: float, lon: float, places: Sequence[Place]) -> Place | None:
    best, best_m = None, math.inf
    for place in places:
        m = distance_m(lat, lon, place.lat, place.lon)
        if m <= place.radius_m and m < best_m:
            best, best_m = place, m
    return best


def _joins(cluster: _Cluster, p: Point, settings: Settings) -> bool:
    """Inside the cluster's radius, whatever the gap since its last point: a tracker that is silent
    while the owner is still has been silent at this place. Called once per point of a track of
    millions, so the distance is taken in kilometres here and not through `distance_m`."""
    if cluster.place is not None:
        return (
            distance_km(p.lat, p.lon, cluster.place.lat, cluster.place.lon) * 1000 <= cluster.place.radius_m
        )
    return distance_km(p.lat, p.lon, cluster.anchor_lat, cluster.anchor_lon) * 1000 <= settings.radius_m


def _start(i: int, p: Point, places: Sequence[Place]) -> _Cluster:
    return _Cluster([i], _place_of(p.lat, p.lon, places), p.lat, p.lon)


def _cluster(
    track: Sequence[Point], settings: Settings, places: Sequence[Place]
) -> tuple[list[_Cluster], set[int]]:
    """Greedy clusters over the track, and the indices dropped as GPS noise."""
    clusters: list[_Cluster] = []
    noise: set[int] = set()
    current: _Cluster | None = None
    for i, p in enumerate(track):
        if current is None:
            current = _start(i, p, places)
            continue
        if _joins(current, p, settings):
            current.members.append(i)
            continue
        if i + 1 < len(track) and _joins(current, track[i + 1], settings):
            noise.add(i)  # one fix away and straight back: noise
            continue
        clusters.append(current)
        current = _start(i, p, places)
    if current is not None:
        clusters.append(current)
    return clusters, noise


def _until(cluster: _Cluster, track: Sequence[Point], settings: Settings) -> datetime:
    """When the cluster ends: at its last point, or at the track's next point when that comes after a
    silence of `merge_gap_s` or more and lies within a walk of `merge_gap_s` (the hop the tracker can
    miss) — a silent tracker is a still owner, unless the next point is too far for that."""
    last = track[cluster.members[-1]]
    following = cluster.members[-1] + 1
    if following >= len(track):
        return last.at
    nxt = track[following]
    if (nxt.at - last.at).total_seconds() < settings.merge_gap_s:
        return last.at
    hop_m = settings.walk_max_kmh * 1000 * settings.merge_gap_s / 3600
    return nxt.at if distance_m(last.lat, last.lon, nxt.lat, nxt.lon) <= hop_m else last.at


def _span_s(cluster: _Cluster, track: Sequence[Point]) -> float:
    return (track[cluster.members[-1]].at - track[cluster.members[0]].at).total_seconds()


def _centroid(cluster: _Cluster, track: Sequence[Point]) -> tuple[float, float]:
    lat = sum(track[i].lat for i in cluster.members) / len(cluster.members)
    lon = sum(track[i].lon for i in cluster.members) / len(cluster.members)
    return lat, lon


def _same_place(a: _Cluster, b: _Cluster, track: Sequence[Point], settings: Settings) -> bool:
    if a.place is not None or b.place is not None:
        return a.place == b.place
    (alat, alon), (blat, blon) = _centroid(a, track), _centroid(b, track)
    return distance_m(alat, alon, blat, blon) <= settings.radius_m


def _merge(clusters: list[_Cluster], track: Sequence[Point], settings: Settings) -> list[_Cluster]:
    """Drop clusters too short to be a stop, then join consecutive clusters at the same place
    whose gap is under the merge gap."""
    kept = [c for c in clusters if _span_s(c, track) >= settings.stop_min_s]
    merged: list[_Cluster] = []
    for cluster in kept:
        if merged:
            last = merged[-1]
            gap = (track[cluster.members[0]].at - track[last.members[-1]].at).total_seconds()
            if gap < settings.merge_gap_s and _same_place(last, cluster, track, settings):
                last.members.extend(cluster.members)
                continue
        merged.append(cluster)
    return merged


# -- classification, moves, aboard ---------------------------------------------------------------------


class _EvidenceLookup:
    """The evidence sorted by instant, so what is attached to a span is found by binary search and
    not by a pass over every line of the window for every cluster. A line with an `end` can start
    before the span and still overlap it, by at most the longest span any evidence line has, so
    the search starts that far before the cluster's start; the test on each candidate is exact."""

    def __init__(self, evidence: Sequence[Evidence]):
        self.items = sorted(evidence, key=lambda e: e.at)
        self.instants = [e.at for e in self.items]
        self.reach = timedelta(
            seconds=max(((e.end - e.at).total_seconds() for e in self.items if e.end is not None), default=0)
        )

    def attached(self, start: datetime, end: datetime) -> dict[str, int]:
        counts: Counter[str] = Counter()
        lo, hi = bisect_left(self.instants, start - self.reach), bisect_right(self.instants, end)
        for e in self.items[lo:hi]:
            inside = start <= e.at <= end if e.end is None else e.at <= end and e.end >= start
            if inside:
                counts[e.kind] += 1
        return dict(sorted(counts.items(), key=lambda kv: EVIDENCE.index(kv[0])))


def _attached(start: datetime, end: datetime, evidence: Sequence[Evidence]) -> dict[str, int]:
    return _EvidenceLookup(evidence).attached(start, end)


def _segments_of(
    subject: str | None,
    track: Sequence[Point],
    settings: Settings,
    places: Sequence[Place],
    evidence: Sequence[Evidence],
    asset_kind: str | None,
    airports: Airports,
) -> tuple[list[Segment], int]:
    clusters, noise = _cluster(track, settings, places)
    clusters = _merge(clusters, track, settings)
    lookup = _EvidenceLookup(evidence if subject is None else ())
    segments: list[Segment] = []
    for n, cluster in enumerate(clusters):
        first, last = track[cluster.members[0]], track[cluster.members[-1]]
        until = _until(cluster, track, settings)
        if n:
            prev = clusters[n - 1]
            segments.append(_move(subject, prev, cluster, track, noise, settings, asset_kind, airports))
        attached = lookup.attached(first.at, until) if subject is None else {}
        by_duration = (until - first.at).total_seconds() >= settings.stay_min_s
        lat, lon = _centroid(cluster, track)
        segments.append(
            Segment(
                kind=STAY if by_duration or attached else STOP,
                subject=subject,
                start=first.at,
                end=until,
                points=len(cluster.members),
                lat=lat,
                lon=lon,
                place=None if cluster.place is None else cluster.place.name,
                attached=attached,
                promoted=bool(attached) and not by_duration,
                first_line=first.id or None,
                last_line=last.id or None,
                first_seq=first.seq,
                last_seq=last.seq,
            )
        )
    return segments, len(noise)


def _move(
    subject: str | None,
    prev: _Cluster,
    nxt: _Cluster,
    track: Sequence[Point],
    noise: set[int],
    settings: Settings,
    asset_kind: str | None,
    airports: Airports,
) -> Segment:
    start, end = track[prev.members[-1]], track[nxt.members[0]]
    leaves = _until(prev, track, settings)  # the stay may hold through a silence; the move starts after
    between = [track[i] for i in range(prev.members[-1] + 1, nxt.members[0]) if i not in noise]
    path = [start, *between, end]
    distance = sum(distance_m(a.lat, a.lon, b.lat, b.lon) for a, b in pairwise(path))
    codes = tuple(
        code
        for code in (
            airport_near(airports, start.lat, start.lon, settings.airport_km),
            airport_near(airports, end.lat, end.lon, settings.airport_km),
        )
        if code
    )
    mode = _mode(
        distance,
        (end.at - leaves).total_seconds(),
        len(codes) == 2 and not between,
        settings,
        asset_kind,
    )
    return Segment(
        kind=MOVE,
        subject=subject,
        start=leaves,
        end=end.at,
        points=len(between),
        distance_m=distance,
        mode=mode,
        airports=codes if len(codes) == 2 else (),
        first_line=start.id or None,
        last_line=end.id or None,
        first_seq=start.seq,
        last_seq=end.seq,
    )


def _mode(
    distance: float, duration_s: float, airport_gap: bool, settings: Settings, asset_kind: str | None
) -> str | None:
    if asset_kind in KIND_MODE:
        return KIND_MODE[asset_kind]
    if distance < settings.radius_m or duration_s <= 0:
        return None  # a gap in the track at one place; nothing moved
    kmh = distance / duration_s * 3.6
    if kmh > settings.flight_min_kmh or airport_gap:
        return "flight"
    if kmh <= settings.walk_max_kmh:
        return "walk"
    if kmh <= settings.car_max_kmh:
        return "car"
    return "train"


def _position_at(
    track: Sequence[Point], instants: Sequence[datetime], at: datetime, window_s: int
) -> tuple[float, float] | None:
    """Where the asset was at `at`: on the line between its last fix at or before `at` and its first
    fix after, when those are no more than `2 * window_s` apart (so the instant is within the window
    of at least one of them); else at the nearer of the two when that is within the window; else
    unknown. Binary search on `instants`, the track's instants in order."""
    i = bisect_right(instants, at)
    before = track[i - 1] if i > 0 else None
    after = track[i] if i < len(track) else None
    if before is not None and after is not None:
        gap = (after.at - before.at).total_seconds()
        if gap <= 2 * window_s:
            f = (at - before.at).total_seconds() / gap if gap > 0 else 0.0
            return before.lat + (after.lat - before.lat) * f, before.lon + (after.lon - before.lon) * f
    nearest = min(
        (p for p in (before, after) if p is not None),
        key=lambda p: abs((p.at - at).total_seconds()),
        default=None,
    )
    if nearest is None or abs((nearest.at - at).total_seconds()) > window_s:
        return None
    return nearest.lat, nearest.lon


def _aboard(
    segments: list[Segment],
    owner: Sequence[Point],
    tracks: Mapping[str | None, Sequence[Point]],
    settings: Settings,
    assets: Mapping[str, str],
) -> list[Segment]:
    """The owner's segments with `aboard` set where an asset's track matches for `aboard_min_s`
    or longer, and a move's mode taken from the asset's kind when aboard. Each segment is matched
    to the asset it shares the most time with (`_matched_s`); a move with no points between two
    segments matched to one asset is matched to it too (the tracker slept through the passage);
    then a run of consecutive segments matched to one asset is aboard it when the matched time
    adds up to the minimum, and not at all when it does not."""
    asset_ids = sorted(a for a in tracks if a is not None)
    if not asset_ids:
        return segments
    owner_instants = [p.at for p in owner]
    instants = {asset: [p.at for p in tracks[asset]] for asset in asset_ids}
    matched: list[tuple[str, float] | None] = []
    for segment in segments:
        best: tuple[str, float] | None = None
        for asset in asset_ids:
            seconds = _matched_s(segment, owner, owner_instants, tracks[asset], instants[asset], settings)
            if seconds is not None and (best is None or seconds > best[1]):
                best = (asset, seconds)
        matched.append(best)
    for n in range(1, len(segments) - 1):
        s = segments[n]
        if s.kind == MOVE and s.points == 0 and matched[n] is None:
            before, after = matched[n - 1], matched[n + 1]
            if before is not None and after is not None and before[0] == after[0]:
                matched[n] = (before[0], 0.0)
    out = list(segments)
    n = 0
    while n < len(segments):
        found = matched[n]
        if found is None:
            n += 1
            continue
        asset = found[0]
        m = n
        while m < len(segments) and (hit := matched[m]) is not None and hit[0] == asset:
            m += 1
        if sum(hit[1] for hit in matched[n:m] if hit is not None) >= settings.aboard_min_s:
            mode = KIND_MODE.get(assets.get(asset, ""))
            for k in range(n, m):
                s = segments[k]
                out[k] = replace(s, aboard=asset, mode=mode if s.kind == MOVE and mode else s.mode)
        n = m
    return out


def _matched_s(
    segment: Segment,
    owner: Sequence[Point],
    owner_instants: Sequence[datetime],
    asset: Sequence[Point],
    asset_instants: Sequence[datetime],
    settings: Settings,
) -> float | None:
    """How long the asset was within the radius of the owner during the segment, in seconds; None
    when it was not there at all. For a stay or stop: the asset's points in the span within the
    radius of the stay's centre, from the first such point to the last (one point is 0 s: a boat
    passing the quay). For a move: when at least half the owner's points lie within the radius of
    the asset's position at their instant (`_position_at`), the span of the matched points; else
    None. Both tracks are in time order and `*_instants` are their instants, so the
    points of a span are found by binary search (two years of a track is a million points; a span
    is minutes)."""
    if segment.kind != MOVE:
        assert segment.lat is not None and segment.lon is not None
        radius = settings.radius_m
        lo, hi = bisect_left(asset_instants, segment.start), bisect_right(asset_instants, segment.end)
        inside = [p.at for p in asset[lo:hi] if distance_m(p.lat, p.lon, segment.lat, segment.lon) <= radius]
        if not inside:
            return None
        return (inside[-1] - inside[0]).total_seconds()
    lo, hi = bisect_right(owner_instants, segment.start), bisect_left(owner_instants, segment.end)
    mine = owner[lo:hi]
    if not mine:
        return None
    hits: list[datetime] = []
    for p in mine:
        q = _position_at(asset, asset_instants, p.at, settings.aboard_window_s)
        if q is not None and distance_m(p.lat, p.lon, q[0], q[1]) <= settings.radius_m:
            hits.append(p.at)
    if len(hits) * 2 < len(mine):
        return None
    return (hits[-1] - hits[0]).total_seconds()


# -- the container -------------------------------------------------------------------------------------


def fold(segments: Iterable[Segment]) -> list[Segment]:
    """The owner's segments with every run of consecutive segments aboard one asset folded into one
    stay aboard it, the run inside (`Segment.inside`): a container the asset's movement never
    fragments. A run that is one move (a passage walked on and off) stays a move. A segment that
    is a container already passes through, so folding twice is folding once; so does a segment
    not aboard, and an asset's own segments, which never carry `aboard`."""
    out: list[Segment] = []
    run: list[Segment] = []

    def flush() -> None:
        if all(s.kind == MOVE for s in run):
            out.extend(run)  # a passage walked on and off; segments alternate, so at most one
        else:
            out.append(_container(run))
        run.clear()

    for s in segments:
        if s.aboard is None or s.inside:
            flush()
            out.append(s)
            continue
        if run and run[-1].aboard != s.aboard:
            flush()
        run.append(s)
    flush()
    return out


def _container(run: Sequence[Segment]) -> Segment:
    """One stay aboard from a run of segments aboard one asset: its centre is that of the inner
    stay the owner spent longest at (the anchorage of the night, not the berth of the morning),
    its attachments the run's added up, its lines the first's first and the last's last."""
    held = [s for s in run if s.kind != MOVE]
    anchor = max(held, key=lambda s: s.duration_s)
    attached: Counter[str] = Counter()
    for s in run:
        attached.update(s.attached)
    return Segment(
        kind=STAY if any(s.kind == STAY for s in held) else STOP,
        subject=run[0].subject,
        start=run[0].start,
        end=run[-1].end,
        points=sum(s.points for s in run),
        lat=anchor.lat,
        lon=anchor.lon,
        place=None,
        attached=dict(sorted(attached.items(), key=lambda kv: EVIDENCE.index(kv[0]))),
        promoted=any(s.promoted for s in run),
        aboard=run[0].aboard,
        first_line=run[0].first_line,
        last_line=run[-1].last_line,
        first_seq=run[0].first_seq,
        last_seq=run[-1].last_seq,
        inside=tuple(run),
    )


# -- the pass ---------------------------------------------------------------------------------------------


def derive(
    lines: Iterable[Line],
    settings: Settings,
    places: Sequence[Place],
    assets: Mapping[str, str],
    tz: str,
    airports: Airports | None = None,
) -> Derived:
    """Stays, stops and moves for every subject in `lines`. `assets` maps an asset id to its kind
    (from `assets.json`); an id the registry does not name is derived like any other subject, with
    its mode from speed. `airports` is the flights table (RFC 0013), the built-in one when not
    given. `tz` is the owner's zone; it is not used to derive (instants are compared as instants)
    but is kept on the result's contract for readers that print."""
    tracks, evidence = _split(lines)
    return derive_tracks(tracks, evidence, settings, places, assets, tz, airports)


def derive_tracks(
    tracks: Mapping[str | None, list[Point]],
    evidence: Sequence[Evidence],
    settings: Settings,
    places: Sequence[Place],
    assets: Mapping[str, str],
    tz: str,
    airports: Airports | None = None,
    subjects: Sequence[str | None] | None = None,
) -> Derived:
    """`derive` from points already split by subject (None is the owner) and the owner's evidence:
    what `places propose` calls with the points the index serves. Each track is put in time order
    here. `subjects` names whose segments to derive — the owner only, `[None]`, for a reader of the
    owner's stays — default every subject with a track; every track still says what the owner was
    aboard."""
    ZoneInfo(tz)  # an unknown zone is an error here, not at print time
    airports = airports or Airports.load()
    for track in tracks.values():
        track.sort(key=attrgetter("at", "seq"))
    owner = tracks.get(None, [])
    present: list[str | None] = [None, *sorted(s for s in tracks if s is not None)]
    subjects = present if subjects is None else [s for s in present if s in subjects]
    segments: list[Segment] = []
    noise = 0
    for subject in subjects:
        track = tracks.get(subject, [])
        found, dropped = _segments_of(
            subject,
            track,
            settings,
            places,
            evidence,
            None if subject is None else assets.get(subject),
            airports,
        )
        noise += dropped
        if subject is None:
            found = _aboard(found, owner, tracks, settings, assets)
        segments.extend(found)
    return Derived(segments, subjects, noise, fold(s for s in segments if s.subject is None))


def night_window(day: str, tz: ZoneInfo, settings: Settings) -> tuple[datetime, datetime]:
    """The night of `day`: from the night's start on that day to its end the next morning, local."""
    start_clock, end_clock = (time.fromisoformat(t) for t in settings.night)
    d = date.fromisoformat(day)
    start = datetime.combine(d, start_clock, tzinfo=tz)
    end_day = d + timedelta(days=1) if end_clock <= start_clock else d
    return start, datetime.combine(end_day, end_clock, tzinfo=tz)


def night(
    segments: Iterable[Segment], day: str, tz: ZoneInfo, settings: Settings, places: Sequence[Place] = ()
) -> Night:
    """The owner's stay with the longest overlap of the night window, when that overlap reaches
    the stay minimum; else in transit. A stay aboard an asset counts whole (`fold`): a passage
    through the night is a night aboard, not a night in transit, and the night carries the inner
    segment that held the longest part of it, so the asset's position that night is known. At
    home when the stay is a place of kind `home`, or its centre lies in one's radius (`places`,
    from places.json)."""
    start, end = night_window(day, tz, settings)

    def overlap_s(s: Segment) -> float:
        return (min(s.end, end) - max(s.start, start)).total_seconds()

    best: Segment | None = None
    best_overlap = 0.0
    for s in fold(s for s in segments if s.subject is None):
        if s.kind != STAY:
            continue
        overlap = overlap_s(s)
        if overlap > best_overlap:
            best, best_overlap = s, overlap
    if best is None or best_overlap < settings.stay_min_s:
        return Night(day, None)
    inside = max(best.inside, key=overlap_s) if best.inside else None
    return Night(day, best, is_home(best, places), inside)


HOME_NEAR_M = 400.0  # a night whose stay centre is this close to a home place is a night at home


def is_home(stay: Segment, places: Sequence[Place]) -> bool:
    """Whether a stay lies in a home region: its named place is of kind `home`, or its centre is
    within a home place's radius, or within `HOME_NEAR_M` of a home place whatever its radius (the
    night rule: a guest room across the street is not a trip, and a trip never starts or ends with
    such a night)."""
    if stay.place is not None:
        named = next((p for p in places if p.name == stay.place), None)
        if named is not None and named.kind == registry_of_places.HOME:
            return True
    if stay.lat is None or stay.lon is None:
        return False
    if registry_of_places.at_home(stay.lat, stay.lon, places) is not None:
        return True
    return any(
        registry_of_places.distance_m(stay.lat, stay.lon, home.lat, home.lon) <= HOME_NEAR_M
        for home in registry_of_places.home_places(places)
    )


def instant_text(instant: datetime) -> str:
    """An aware datetime as the RFC3339 UTC stamp a line carries."""
    return _stamp(instant)
