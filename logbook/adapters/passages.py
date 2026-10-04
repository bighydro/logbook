"""A ship's deck log, transcribed as CSV → declared sea legs of one registered asset.

`logbook add passages <log.csv> --asset <id> [--routes <dir>]`. The CSV has the columns

    dep_local, dep_place, arr_local, arr_place, tz, note, check

one row per leg: when and where the vessel left, when and where she arrived, the IANA zone the
clocks are in (empty: the record's zone), the keeper's remark, and a `check` value for a row the
transcriber doubts. Times are `YYYY-MM-DD HH:MM` (a `T` and seconds are fine; an offset is kept);
a bare date is a leg whose clocks were not noted. The arrival may be empty: the leg is still open.

Each row is one trip/v1 line (RFC 0020), mode `passage`, provider `deck-log`, `subject` the asset,
`evidence` `declared`, named `<dep_place> → <arr_place>`, `at` the departure and `end` the arrival
(null while open). The places are the log's own words under `from` and `to` (rule 2), with a
position when one can be found, in this order: an ECDIS route file in `--routes` (RTZ 1.0 XML, as
Maris MDS and other bridge systems export) whose name names both places — case, accents and
punctuation aside, by the words they share (`CANNES TO GENOA` is Cannes → Genoa Molo Vecchio, and
Genoa → Cannes with the waypoints reversed) — gives the first and last waypoint, the route as
`geometry` (a GeoJSON LineString) and its length as `distance_m`; else the record's `places.json`;
else a bundled gazetteer of Mediterranean, US East Coast and Bahamas ports and anchorages
(`logbook/tables/ports.csv`, real public coordinates, none invented); else the place keeps its name
and no position, and the run reports the name. For every positioned end with a time, the asset gets
a location/v1 line (RFC 0001, ADR 0018) — `subject` set, `provider` `manual`, `tracker` `deck-log`,
the accuracy that of the source (a waypoint, a named place's radius, a port's centre) — so the
readers that derive an asset's track (`assets status`, `derive stays`, `day`, `trips`) see the
declared movement like any other.

`raw_id` is `passages:<asset>:<dep_local>:<dep_place>`, so the same row again appends nothing and a
row typed twice with another arrival is the same leg (the correction is a new row with a later
departure, or a retraction). The position lines carry it with `:dep` and `:arr`. A row without a
departure time or place is a counted skip; a zone the database does not know is one too. Pure: the
CSV, the route files and the tables are read once, no network. Tier 1 (the vessel's own movement).
"""

from __future__ import annotations

import csv
import re
import unicodedata
from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime, time
from functools import cache
from itertools import pairwise
from pathlib import Path
from typing import Any, NamedTuple
from xml.etree import ElementTree
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..core.assets import Asset
from ..core.flights import distance_km
from ..core.places import Place

NAME = "passages"
KIND = "trip"
SCHEMA = "trip/v1"
LOCATION_SCHEMA = "location/v1"
TIER = 1
MODE = "passage"
PROVIDER = "deck-log"
COLUMNS = ("dep_local", "dep_place", "arr_local", "arr_place", "tz", "note", "check")
REQUIRED = ("dep_local", "dep_place")
PORTS = Path(__file__).resolve().parent.parent / "tables" / "ports.csv"
PORT_RADIUS_M = 1000.0  # a port's centre places a vessel this well
WAYPOINT_ACCURACY_M = 100.0  # a route's first or last waypoint
ARROW = "→"
# Words that name the kind of place, not the place: dropped before two names are compared, unless
# nothing else is left.
FILLER = frozenset(
    (
        "to",
        "from",
        "and",
        "the",
        "of",
        "via",
        "a",
        "al",
        "de",
        "di",
        "del",
        "della",
        "dei",
        "degli",
        "da",
        "la",
        "le",
        "les",
        "el",
        "los",
        "las",
        "il",
        "lo",
        "port",
        "porto",
        "puerto",
        "marina",
        "harbour",
        "harbor",
        "hafen",
        "bay",
        "baie",
        "cala",
        "isola",
        "isole",
        "ile",
        "iles",
        "island",
        "islands",
        "st",
        "saint",
        "sainte",
        "santa",
        "santo",
        "san",
        "sur",
        "mer",
        "sea",
        "anchorage",
        "anch",
        "molo",
        "quay",
        "quai",
        "dock",
        "pier",
        "berth",
        "mooring",
        "buoy",
    )
)
SEPARATOR = re.compile(r"\s*(?:\u2192|->|/|\s[-\u2013\u2014>]\s)\s*|\bto\b")
ROUTE_SUFFIXES = (".rtz",)


class Port(NamedTuple):
    name: str
    aliases: tuple[str, ...]
    lat: float
    lon: float
    country: str


class Position(NamedTuple):
    lat: float
    lon: float
    accuracy_m: float
    origin: str  # route, places or gazetteer


class Waypoint(NamedTuple):
    lat: float
    lon: float
    name: str | None


class Route(NamedTuple):
    name: str
    file: str
    waypoints: tuple[Waypoint, ...]
    length_m: float


# -- names ---------------------------------------------------------------------------------------------------


def tokens(text: str) -> tuple[str, ...]:
    """Every word of a name, lower-case ASCII: accents and punctuation gone."""
    plain = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in plain if not unicodedata.combining(c)).casefold()
    return tuple(re.sub(r"[^a-z0-9]+", " ", plain).split())


def normalise(text: str) -> tuple[str, ...]:
    """The words of a name that tell it apart: `tokens` minus FILLER, or all of them when nothing
    else is left (`La Marina`)."""
    words = tokens(text)
    kept = tuple(w for w in words if w not in FILLER)
    return kept or words


def _parts(route_name: str) -> list[tuple[str, ...]]:
    """A route name split at its `to`, dash, slash or arrow into normalised ends; one part when it
    has no such separator."""
    plain = " ".join(tokens(route_name)) if not SEPARATOR.search(route_name.casefold()) else route_name
    pieces = [normalise(p) for p in SEPARATOR.split(unicodedata.normalize("NFKD", plain).casefold())]
    pieces = [p for p in pieces if p]
    return pieces if len(pieces) == 2 else [normalise(route_name)]


def match_route(dep_place: str, arr_place: str, routes: Sequence[Route]) -> tuple[Route, bool] | None:
    """The route whose name names both places, and whether it runs the other way (its waypoints are
    then read last to first). A name with two ends (`CANNES TO GENOA`, `LA SPEZIA - BONIFACIO`)
    must name the departure in one and the arrival in the other; a name without a separator must
    name both somewhere, and the one named first is the departure. The most words shared wins;
    between equals a name with two ends, then the first file."""
    dep, arr = set(normalise(dep_place)), set(normalise(arr_place))
    if not dep or not arr:
        return None
    best: tuple[tuple[int, int], Route, bool] | None = None
    for route in routes:
        parts = _parts(route.name)
        found: tuple[tuple[int, int], bool] | None = None
        if len(parts) == 2:
            first, second = set(parts[0]), set(parts[1])
            if dep & first and arr & second:
                found = ((len(dep & first) + len(arr & second), 1), False)
            elif dep & second and arr & first:
                found = ((len(dep & second) + len(arr & first), 1), True)
        else:
            words = parts[0]
            shared_dep, shared_arr = dep & set(words), arr & set(words)
            if shared_dep and shared_arr:
                first_dep = min(words.index(w) for w in shared_dep)
                first_arr = min(words.index(w) for w in shared_arr)
                found = ((len(shared_dep) + len(shared_arr), 0), first_arr < first_dep)
        if found is not None and (best is None or found[0] > best[0]):
            best = (found[0], route, found[1])
    return None if best is None else (best[1], best[2])


# -- positions -----------------------------------------------------------------------------------------------


@cache
def gazetteer() -> tuple[Port, ...]:
    """The bundled ports table: name, aliases, position, country (ISO 3166-1 alpha-2)."""
    with PORTS.open(encoding="utf-8", newline="") as f:
        return tuple(
            Port(
                row["name"],
                tuple(a for a in row["aliases"].split("|") if a),
                float(row["lat"]),
                float(row["lon"]),
                row["country"],
            )
            for row in csv.DictReader(f)
        )


def gazetteer_places() -> list[Place]:
    """The gazetteer as named places (radius PORT_RADIUS_M), for a reader that labels a position."""
    return [Place(p.name, p.lat, p.lon, PORT_RADIUS_M, country=p.country) for p in gazetteer()]


def _covers(candidate: str, words: set[str]) -> int:
    """How many distinguishing words of `candidate` the name has — all of them, or 0."""
    own = set(normalise(candidate))
    return len(own) if own and own <= words else 0


def resolve(name: str, named: Sequence[Place], ports: Sequence[Port]) -> Position | None:
    """Where a place the log names is: the record's own place whose name the log's name contains
    (`Genoa Molo Vecchio` contains `Genoa`; the most specific match wins), else the port or alias of
    the gazetteer it contains, else nothing."""
    words = set(normalise(name))
    if not words:
        return None
    best: tuple[int, Position] | None = None
    for place in named:
        n = _covers(place.name, words)
        if n and (best is None or n > best[0]):
            best = (n, Position(place.lat, place.lon, place.radius_m, "places"))
    if best is not None:
        return best[1]
    for port in ports:
        for label in (port.name, *port.aliases):
            n = _covers(label, words)
            if n and (best is None or n > best[0]):
                best = (n, Position(port.lat, port.lon, PORT_RADIUS_M, "gazetteer"))
    return None if best is None else best[1]


# -- routes --------------------------------------------------------------------------------------------------


def _local_name(tag: object) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _route(file: Path) -> Route | None:
    """One RTZ file as a Route: its `routeInfo/@routeName` (else the file's stem) and the positions
    of its waypoints in document order; None when the file is not a route with two waypoints."""
    try:
        root = ElementTree.parse(file).getroot()
    except (OSError, ElementTree.ParseError):
        return None
    if _local_name(root.tag) != "route":
        return None
    name = file.stem
    for element in root.iter():
        if _local_name(element.tag) == "routeInfo" and (element.get("routeName") or "").strip():
            name = str(element.get("routeName")).strip()
            break
    waypoints: list[Waypoint] = []
    for element in root.iter():
        if _local_name(element.tag) != "waypoint":
            continue
        position = next((c for c in element if _local_name(c.tag) == "position"), None)
        if position is None:
            continue
        try:
            lat, lon = float(str(position.get("lat"))), float(str(position.get("lon")))
        except ValueError:
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        waypoints.append(Waypoint(lat, lon, (element.get("name") or "").strip() or None))
    if len(waypoints) < 2:
        return None
    length = sum(distance_km(a.lat, a.lon, b.lat, b.lon) * 1000 for a, b in pairwise(waypoints))
    return Route(name, file.name, tuple(waypoints), length)


def read_routes(path: Path) -> list[Route]:
    """Every readable RTZ route under `path` (a folder, or one file), by file name."""
    path = Path(path)
    files = [path] if path.is_file() else sorted(path.iterdir()) if path.is_dir() else []
    routes = [_route(f) for f in files if f.is_file() and f.suffix.lower() in ROUTE_SUFFIXES]
    return [r for r in routes if r is not None]


# -- the mapping ---------------------------------------------------------------------------------------------


def sniff(path: Path) -> bool:
    """A CSV whose header has `dep_local` and `dep_place`. Never raises."""
    try:
        path = Path(path)
        if not path.is_file() or path.suffix.lower() != ".csv":
            return False
        with path.open(encoding="utf-8-sig", newline="") as f:
            header = next(csv.reader(f), [])
    except (OSError, ValueError, StopIteration):
        return False
    columns = {c.strip().casefold() for c in header}
    return all(c in columns for c in REQUIRED)


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
    assets: Sequence[Asset] | None = None,
    asset: str | None = None,
    routes: Path | None = None,
    report: list[str] | None = None,
    places: Sequence[Place] | None = None,
) -> Iterator[dict[str, Any]]:
    """One trip/v1 draft per row and a location/v1 draft per positioned end with a time, oldest
    first. `asset` is the registered asset the log belongs to (required; ValueError names the
    flag, or the asset when `assets` does not list it). `routes` is a folder of RTZ files, `places`
    the record's named places. `since` is RFC3339 UTC: legs that left before it are not yielded.
    `counts` tallies the skips; `report` receives the summary and the names left unpositioned."""
    counts = counts if counts is not None else {}
    report = report if report is not None else []
    if not asset:
        raise ValueError(
            f"{NAME} needs --asset ASSET-ID, the registered asset the log belongs to (logbook assets list)"
        )
    if asset not in {a.id for a in assets or ()}:
        raise ValueError(f"asset {asset!r} is not registered in assets.json (logbook assets add {asset} ...)")
    known_routes = read_routes(Path(routes)) if routes is not None else []
    ports = gazetteer()
    named = list(places or ())
    drafts: list[dict[str, Any]] = []
    legs = matched = open_legs = 0
    unresolved: dict[str, None] = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f):
            row = {(k or "").strip().casefold(): (v or "").strip() for k, v in raw.items() if k is not None}
            zone = _zone(row.get("tz", ""), timezone)
            if zone is None:
                _count(counts, "skipped_unknown_timezone")
                continue
            dep = _local(row.get("dep_local", ""), zone)
            if dep is None:
                _count(counts, "skipped_no_timestamp")
                continue
            dep_place = row.get("dep_place", "")
            if not dep_place:
                _count(counts, "skipped_no_place")
                continue
            at = _stamp(dep[0])
            if since and at < since:
                continue
            arr_place = row.get("arr_place", "")
            arr = _local(row.get("arr_local", ""), zone, arrival=True)
            legs += 1
            route = match_route(dep_place, arr_place, known_routes) if arr_place else None
            origins: dict[str, str | None] = {}
            if route is not None:
                matched += 1
                found, reversed_ = route
                points = found.waypoints[::-1] if reversed_ else found.waypoints
                from_pos: Position | None = Position(
                    points[0].lat, points[0].lon, WAYPOINT_ACCURACY_M, "route"
                )
                to_pos: Position | None = Position(
                    points[-1].lat, points[-1].lon, WAYPOINT_ACCURACY_M, "route"
                )
            else:
                points = ()
                from_pos = resolve(dep_place, named, ports)
                to_pos = resolve(arr_place, named, ports) if arr_place else None
            origins["from"] = from_pos.origin if from_pos else None
            if from_pos is None:
                unresolved.setdefault(dep_place)
            if arr_place:
                origins["to"] = to_pos.origin if to_pos else None
                if to_pos is None:
                    unresolved.setdefault(arr_place)
            else:
                open_legs += 1
            raw_id = f"{NAME}:{asset}:{dep[2]}:{'-'.join(tokens(dep_place))}"
            end = _stamp(arr[0]) if arr is not None else None
            extra: dict[str, Any] = {"positions": origins}
            if route is not None:
                extra["route"] = {"name": route[0].name, "file": route[0].file}
            approximate = [label for label, parsed in (("dep", dep), ("arr", arr)) if parsed and parsed[1]]
            if approximate:
                extra["approximate"] = approximate
            if not arr_place:
                extra["open"] = True
            if row.get("note"):
                extra["note"] = row["note"]
            if row.get("check"):
                extra["check"] = row["check"]
            payload: dict[str, Any] = {
                "schema": SCHEMA,
                "raw_id": raw_id,
                "mode": MODE,
                "provider": PROVIDER,
                "subject": asset,
                "evidence": "declared",
                "name": f"{dep_place} {ARROW} {arr_place or '?'}",
                "from": _end(dep_place, from_pos),
            }
            if arr_place:
                payload["to"] = _end(arr_place, to_pos)
            if route is not None:
                payload["geometry"] = {"type": "LineString", "coordinates": [[w.lon, w.lat] for w in points]}
                payload["distance_m"] = round(route[0].length_m)
            payload["extra"] = extra
            drafts.append(_draft(at, end, str(zone), KIND, payload))
            if from_pos is not None:
                drafts.append(_position(at, str(zone), asset, raw_id, "dep", dep_place, from_pos))
            if to_pos is not None and end is not None:
                drafts.append(_position(end, str(zone), asset, raw_id, "arr", arr_place, to_pos))
    if legs:
        summary = f"{legs} {'leg' if legs == 1 else 'legs'}"
        details = []
        if known_routes or matched:
            details.append(f"{matched} matched to a route")
        if open_legs:
            details.append(f"{open_legs} open (no arrival yet)")
        report.append(summary + (": " + ", ".join(details) if details else ""))
    if unresolved:
        report.append("places unresolved: " + ", ".join(unresolved))
    drafts.sort(key=lambda d: d["at"])  # a stable sort: a leg stays ahead of its own departure line
    yield from drafts


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _zone(name: str, default: str | None) -> ZoneInfo | None:
    try:
        return ZoneInfo(name or default or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _local(text: str, zone: ZoneInfo, arrival: bool = False) -> tuple[datetime, bool, str] | None:
    """A cell as (the instant, whether only the day was given, the key for `raw_id`): a bare date
    is the start of that local day — its end for an arrival — and said so; an offset in the text
    is kept; empty or unreadable is None."""
    if not text:
        return None
    if len(text) == 10:
        try:
            day = date.fromisoformat(text)
        except ValueError:
            return None
        clock = time(23, 59, 59) if arrival else time.min
        return datetime.combine(day, clock, tzinfo=zone), True, day.isoformat()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed, False, parsed.strftime("%Y-%m-%dT%H:%M")


def _stamp(instant: datetime) -> str:
    return instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _end(name: str, position: Position | None) -> dict[str, Any]:
    if position is None:
        return {"name": name}
    return {"name": name, "latitude": position.lat, "longitude": position.lon}


def _draft(at: str, end: str | None, tz: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"at": at, "end": end, "tz": tz, "source": NAME, "kind": kind, "tier": TIER, "payload": payload}


def _position(
    at: str, tz: str, asset: str, leg: str, which: str, place: str, pos: Position
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": LOCATION_SCHEMA,
        "lat": pos.lat,
        "lon": pos.lon,
        "accuracy_m": pos.accuracy_m,
        "provider": "manual",
        "tracker": PROVIDER,
        "raw_id": f"{leg}:{which}",
        "subject": asset,
        "extra": {"evidence": "declared", "place": place, "leg": leg, "position": pos.origin},
    }
    return _draft(at, None, tz, "location", payload)
