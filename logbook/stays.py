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
- The owner is aboard an asset during a stay when the asset's positions in that span fall within
  the stay's radius, and during a move when at least half the owner's points have an asset position
  within the radius at nearly the same instant (`aboard_window_s`). Aboard is the owner's relation
  to the asset (ADR 0018 rule 3); an asset's own segments never carry it.
- The overnight stay of a day is the owner's stay with the longest overlap of the night window,
  22:00 to 08:00 next morning by default; when no overlap reaches `stay_min_s`, the day is in
  transit.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
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
    aboard_window_s: int = 300  # an asset position this close in time can match an owner point

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
        return out


@dataclass(frozen=True)
class Night:
    day: str
    stay: Segment | None
    home: bool = False  # the stay lies in a home region (places.json, kind `home`)

    @property
    def in_transit(self) -> bool:
        return self.stay is None

    def to_json(self, tz: ZoneInfo) -> dict[str, Any]:
        return {
            "day": self.day,
            "stay": None if self.stay is None else self.stay.to_json(tz),
            "in_transit": self.in_transit,
            "home": self.home,
        }


@dataclass(frozen=True)
class Derived:
    segments: list[Segment]  # every subject's, the owner's first, each in time order
    subjects: list[str | None]  # None is the owner; then asset ids, sorted
    noise_points: int


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
    for track in tracks.values():
        track.sort(key=lambda p: (p.at, p.seq))
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


def _inside(cluster: _Cluster, p: Point, settings: Settings) -> bool:
    if cluster.place is not None:
        return distance_m(p.lat, p.lon, cluster.place.lat, cluster.place.lon) <= cluster.place.radius_m
    return distance_m(p.lat, p.lon, cluster.anchor_lat, cluster.anchor_lon) <= settings.radius_m


def _joins(cluster: _Cluster, p: Point, settings: Settings) -> bool:
    """Inside the cluster's radius, whatever the gap since its last point: a tracker that is silent
    while the owner is still has been silent at this place."""
    return _inside(cluster, p, settings)


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


def _attached(start: datetime, end: datetime, evidence: Sequence[Evidence]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for e in evidence:
        inside = start <= e.at <= end if e.end is None else e.at <= end and e.end >= start
        if inside:
            counts[e.kind] += 1
    return dict(sorted(counts.items(), key=lambda kv: EVIDENCE.index(kv[0])))


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
    segments: list[Segment] = []
    for n, cluster in enumerate(clusters):
        first, last = track[cluster.members[0]], track[cluster.members[-1]]
        until = _until(cluster, track, settings)
        if n:
            prev = clusters[n - 1]
            segments.append(_move(subject, prev, cluster, track, noise, settings, asset_kind, airports))
        attached = _attached(first.at, until, evidence) if subject is None else {}
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


def _nearest_in_time(track: Sequence[Point], at: datetime, window_s: int) -> Point | None:
    """The asset point closest in time to `at`, when one is within the window (binary search)."""
    lo, hi = 0, len(track)
    while lo < hi:
        mid = (lo + hi) // 2
        if track[mid].at < at:
            lo = mid + 1
        else:
            hi = mid
    best: Point | None = None
    for j in (lo - 1, lo):
        if 0 <= j < len(track):
            p = track[j]
            if abs((p.at - at).total_seconds()) <= window_s and (
                best is None or abs((p.at - at).total_seconds()) < abs((best.at - at).total_seconds())
            ):
                best = p
    return best


def _aboard(
    segments: list[Segment],
    owner: Sequence[Point],
    tracks: Mapping[str | None, Sequence[Point]],
    settings: Settings,
    assets: Mapping[str, str],
) -> list[Segment]:
    """The owner's segments with `aboard` set where an asset's track matches, and a move's mode
    taken from the asset's kind when aboard."""
    asset_ids = sorted(s for s in tracks if s is not None)
    if not asset_ids:
        return segments
    out: list[Segment] = []
    for segment in segments:
        aboard = None
        for asset in asset_ids:
            if _matches(segment, owner, tracks[asset], settings):
                aboard = asset
                break
        out.append(replace(segment, aboard=aboard))
    # A gap between two stays aboard the same asset is a move aboard it.
    for n, segment in enumerate(out):
        if segment.kind == MOVE and segment.aboard is None and segment.points == 0 and 0 < n < len(out) - 1:
            before, after = out[n - 1].aboard, out[n + 1].aboard
            if before is not None and before == after:
                out[n] = replace(segment, aboard=before)
    return [
        replace(s, mode=KIND_MODE[assets[s.aboard]])
        if s.kind == MOVE and s.aboard is not None and assets.get(s.aboard) in KIND_MODE
        else s
        for s in out
    ]


def _matches(segment: Segment, owner: Sequence[Point], asset: Sequence[Point], settings: Settings) -> bool:
    if segment.kind != MOVE:
        assert segment.lat is not None and segment.lon is not None
        radius = settings.radius_m
        return any(
            segment.start <= p.at <= segment.end
            and distance_m(p.lat, p.lon, segment.lat, segment.lon) <= radius
            for p in asset
        )
    mine = [p for p in owner if segment.start < p.at < segment.end]
    if not mine:
        return False
    matched = 0
    for p in mine:
        q = _nearest_in_time(asset, p.at, settings.aboard_window_s)
        if q is not None and distance_m(p.lat, p.lon, q.lat, q.lon) <= settings.radius_m:
            matched += 1
    return matched * 2 >= len(mine)


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
    ZoneInfo(tz)  # an unknown zone is an error here, not at print time
    airports = airports or Airports.load()
    tracks, evidence = _split(lines)
    owner = tracks.get(None, [])
    subjects: list[str | None] = [None, *sorted(s for s in tracks if s is not None)]
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
    return Derived(segments, subjects, noise)


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
    the stay minimum; else in transit. At home when the stay is a place of kind `home`, or its
    centre lies in one's radius (`places`, from places.json)."""
    start, end = night_window(day, tz, settings)
    best: Segment | None = None
    best_overlap = 0.0
    for s in segments:
        if s.subject is not None or s.kind != STAY:
            continue
        overlap = (min(s.end, end) - max(s.start, start)).total_seconds()
        if overlap > best_overlap:
            best, best_overlap = s, overlap
    if best is None or best_overlap < settings.stay_min_s:
        return Night(day, None)
    return Night(day, best, is_home(best, places))


def is_home(stay: Segment, places: Sequence[Place]) -> bool:
    """Whether a stay lies in a home region: its named place is of kind `home`, or its centre is
    within a home place's radius."""
    if stay.place is not None:
        named = next((p for p in places if p.name == stay.place), None)
        if named is not None and named.kind == registry_of_places.HOME:
            return True
    if stay.lat is None or stay.lon is None:
        return False
    return registry_of_places.at_home(stay.lat, stay.lon, places) is not None


def instant_text(instant: datetime) -> str:
    """An aware datetime as the RFC3339 UTC stamp a line carries."""
    return _stamp(instant)
