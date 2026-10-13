"""Google Takeout Location History → location/v1 (RFC 0001).

Four export shapes, all read with ijson so a multi-gigabyte file is never held in memory:

- `Records.json`, the archive Takeout writes: `{"locations": [{latitudeE7, longitudeE7, timestamp,
  accuracy, altitude?, velocity?, heading?, source?, deviceTag?, ...}]}`. Older archives carry
  `timestampMs` (a string of unix milliseconds) instead of `timestamp`.
- `Semantic Location History/<year>/<year>_<MONTH>.json`, the archive's monthly visits:
  `{"timelineObjects": [{"placeVisit": ...} | {"activitySegment": ...}]}`. A `placeVisit` holds
  `location` (`latitudeE7`, `longitudeE7`, `placeId`, and the `name` and `address` Google Maps knew
  the place by, `semanticType`), `duration` (`startTimestamp` / `endTimestamp`, or the older
  `startTimestampMs` / `endTimestampMs`) and the candidates; an `activitySegment` its
  `startLocation`, `endLocation` and `duration`.
- `Timeline.json`, the export an Android phone writes on its own: `{"semanticSegments": [...]}`
  where a segment holds a `timelinePath` (raw points as `"geo:lat,lng"` plus `time`), a `visit`
  (one place: `topCandidate` with `placeId`, `semanticType`, `placeLocation.latLng`) or an
  `activity` (a move with `start` and `end`).
- `location-history.json`, the export an iPhone writes on its own: the same segments as a top-level
  array, with `placeID`, coordinates as `"geo:lat,lng"` strings, numbers as strings, and a path
  point's time as `durationMinutesOffsetFromStartTime` from the segment's `startTime`.

Neither phone export names a place: a visit carries Google's place id and a semantic type
(`HOME`, `Work`), never a name or an address. Only the archive's `placeVisit` does.

Every raw point becomes one line. A visit or an activity becomes exactly two lines, its start and
its end coordinate (a `placeVisit` at its `location`, else at its centre); the span itself is not a
location line (RFC 0001) and what it means is engine work (ADR 0011). The visit's own object is
kept whole under `extra.<key>` (`visit`, `placeVisit`, ...), its span under `extra.segment_start`
and `segment_end`: what `places review` reads a place's name from. Nothing the source says is
dropped: what has no RFC field is kept under `payload.extra`. An item with no usable timestamp or
with a missing, non-numeric, non-finite or out-of-range coordinate is skipped and tallied in
`counts`. Pure: one file, no network.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ... import stream
from ...stream import ijson
from . import SOURCE

NAME = "google-takeout-location"
KIND = "location"
TIER = 1
SCHEMA = "location/v1"

RECORDS = "locations"
TIMELINE = "semanticSegments"
SEMANTIC = "timelineObjects"
ON_DEVICE = ""  # the iPhone's export: the segments as a top-level array, whose prefix is the root's
ITEMS = {  # ijson's prefix of an item → the shape it is an item of
    f"{RECORDS}.item": RECORDS,
    f"{TIMELINE}.item": TIMELINE,
    f"{SEMANTIC}.item": SEMANTIC,
    "item": ON_DEVICE,
}
SEGMENT_KEYS = ("timelinePath", "visit", "activity", "startTime")
DEVICE_KEYS = ("timelinePath", "visit", "activity", "timelineMemory")
SEMANTIC_KEYS = ("placeVisit", "activitySegment")
SNIFF_EVENT_BUDGET = 20_000  # parse events sniff reads before deciding the file is not ours

PROVIDERS = {"GPS": "gps", "WIFI": "wifi", "CELL": "cell"}
RECORD_FIELDS = ("latitudeE7", "longitudeE7", "timestamp", "timestampMs")
RECORD_NUMBERS = {
    "accuracy": "accuracy_m",
    "altitude": "alt_m",
    "velocity": "speed_mps",
    "heading": "heading_deg",
}
NO_TIMESTAMP = "skipped_no_timestamp"
BAD_COORDINATES = "skipped_bad_coordinates"


def sniff(path: Path) -> bool:
    """A JSON object whose `locations`, `timelineObjects` or `semanticSegments` array starts with an
    item of the right shape, or a top-level array whose first item is a segment with a `startTime`."""
    path = Path(path)
    if not path.is_file():
        return False
    try:
        shape, first = _head(path)
    except stream.MissingExtra:  # no ijson: the first bytes decide, and `add` then names the extra
        return _looks_like_location_history(path)
    except stream.json_errors():
        return False
    if not isinstance(first, dict):
        return False
    if shape == RECORDS:
        return "latitudeE7" in first and "longitudeE7" in first
    if shape == TIMELINE:
        return any(k in first for k in SEGMENT_KEYS)
    if shape == SEMANTIC:
        return any(k in first for k in SEMANTIC_KEYS)
    if shape == ON_DEVICE:
        return "startTime" in first and any(k in first for k in DEVICE_KEYS)
    return False


def _looks_like_location_history(path: Path) -> bool:
    """Without `ijson`: `locations` with `latitudeE7`, `timelineObjects` with a visit or an activity,
    `semanticSegments` with a segment's key, or a top-level array of segments, in the first bytes."""
    head = stream.head(path)
    if f'"{RECORDS}"' in head:
        return '"latitudeE7"' in head and '"longitudeE7"' in head
    if f'"{SEMANTIC}"' in head:
        return any(f'"{k}"' in head for k in SEMANTIC_KEYS)
    if f'"{TIMELINE}"' in head:
        return any(f'"{k}"' in head for k in SEGMENT_KEYS)
    if head.lstrip().startswith("["):
        return '"startTime"' in head and any(f'"{k}"' in head for k in DEVICE_KEYS)
    return False


def _head(path: Path) -> tuple[str | None, object]:
    """Which array the file has (a top-level key's, or the root itself: `ON_DEVICE`) and its first
    item, reading no further than that item.

    Gives up after SNIFF_EVENT_BUDGET events so an unrelated multi-gigabyte document is not streamed
    to its end just to say no."""
    builder: ijson.ObjectBuilder | None = None
    shape: str | None = None
    item = ""
    root_is_array = False
    with path.open("rb") as fh:
        for n, (prefix, event, value) in enumerate(ijson.parse(fh, use_float=True)):
            if builder is None:
                if n >= SNIFF_EVENT_BUDGET:
                    return None, None
                if n == 0:
                    root_is_array = event == "start_array"
                    if root_is_array:
                        continue
                known = prefix in ITEMS and (prefix != "item" or root_is_array)
                container = prefix in ITEMS.values() and (prefix != ON_DEVICE or root_is_array)
                if event == "start_map" and known:
                    shape, item = ITEMS[prefix], prefix
                    builder = ijson.ObjectBuilder()
                elif event == "end_array" and container:
                    return prefix, None  # empty: nothing to import, so not ours
                elif event == "start_array" and container:
                    continue
                elif known:
                    return ITEMS[prefix], value  # a scalar item: not ours
                else:
                    continue
            builder.event(event, value)
            if event == "end_map" and prefix == item:
                return shape, builder.value
    return shape, None


def run(
    path: Path, since: str | None = None, counts: dict[str, int] | None = None
) -> Iterator[dict[str, Any]]:
    """Yield one location/v1 line draft per raw point and per visit/activity edge, in export order.

    `since` is RFC3339 UTC. `counts`, when given, receives how many items were skipped and why."""
    if counts is None:
        counts = {}
    counts.setdefault(NO_TIMESTAMP, 0)
    counts.setdefault(BAD_COORDINATES, 0)
    path = Path(path)
    shape, _first = _head(path)
    with path.open("rb") as fh:
        if shape == RECORDS:
            items = (_from_record(r, counts) for r in ijson.items(fh, f"{RECORDS}.item", use_float=True))
        elif shape in (TIMELINE, ON_DEVICE):
            prefix = f"{TIMELINE}.item" if shape == TIMELINE else "item"
            items = (
                line for s in ijson.items(fh, prefix, use_float=True) for line in _from_segment(s, counts)
            )
        elif shape == SEMANTIC:
            items = (
                line
                for o in ijson.items(fh, f"{SEMANTIC}.item", use_float=True)
                for line in _from_timeline_object(o, counts)
            )
        else:
            raise ValueError(f"{path}: not a Google Takeout location export")
        for line in items:
            if line is not None and not (since and line["at"] < since):
                yield line


# -- Records.json --------------------------------------------------------------------


def _from_record(record: object, counts: dict[str, int]) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        counts[BAD_COORDINATES] += 1
        return None
    raw_time = record.get("timestamp")
    at = _rfc3339(raw_time) if raw_time is not None else _from_millis(record.get("timestampMs"))
    if at is None:
        counts[NO_TIMESTAMP] += 1
        return None
    lat = _e7(record.get("latitudeE7"), 90)
    lon = _e7(record.get("longitudeE7"), 180)
    if lat is None or lon is None:
        counts[BAD_COORDINATES] += 1
        return None
    payload: dict[str, Any] = {"schema": SCHEMA, "lat": lat, "lon": lon}
    mapped = set(RECORD_FIELDS)
    for key, field in RECORD_NUMBERS.items():
        number = _finite(record.get(key))
        if number is not None and not (field == "heading_deg" and not 0 <= number <= 360):
            payload[field] = number
            mapped.add(key)
    provider = PROVIDERS.get(record.get("source"))  # type: ignore[arg-type]
    if provider is not None:
        payload["provider"] = provider
        mapped.add("source")
    device = record.get("deviceTag")
    if device is not None:
        payload["tracker"] = str(device)
        mapped.add("deviceTag")
    time_id = raw_time if raw_time is not None else record.get("timestampMs")
    payload["raw_id"] = f"records:{device if device is not None else ''}:{time_id}"
    payload["extra"] = {k: v for k, v in record.items() if k not in mapped}
    return _line(at, payload)


def _e7(value: object, limit: float) -> float | None:
    """Degrees from an E7 integer; None unless it is a finite number within ±limit degrees."""
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    degrees = value / 1e7
    return degrees if -limit <= degrees <= limit else None


def _from_millis(value: object) -> str | None:
    try:
        millis = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError, OverflowError):
        return None
    try:
        return datetime.fromtimestamp(millis / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return None


# -- Timeline.json --------------------------------------------------------------------


def _from_segment(segment: object, counts: dict[str, int]) -> Iterator[dict[str, Any]]:
    if not isinstance(segment, dict):
        return
    start, end = segment.get("startTime"), segment.get("endTime")
    span = {"segment_start": start, "segment_end": end}
    path = segment.get("timelinePath")
    if isinstance(path, list):
        for point in path:
            line = _from_path_point(point, counts, start)
            if line is not None:
                yield line
    for key in ("visit", "activity"):
        item = segment.get(key)
        if not isinstance(item, dict):
            continue
        for edge, raw_time in (("start", start), ("end", end)):
            coords = _visit_coordinates(item) if key == "visit" else _location(item.get(edge))
            at = _rfc3339(raw_time)
            if at is None:
                counts[NO_TIMESTAMP] += 1
                continue
            if coords is None:
                counts[BAD_COORDINATES] += 1
                continue
            lat, lon = coords
            extra: dict[str, Any] = {"segment": key, "edge": edge, **span, key: item}
            payload = {
                "schema": SCHEMA,
                "lat": lat,
                "lon": lon,
                "raw_id": f"{key}:{raw_time}:{edge}",
                "extra": extra,
            }
            yield _line(at, payload)


def _from_path_point(
    point: object, counts: dict[str, int], segment_start: object = None
) -> dict[str, Any] | None:
    """One raw point: its own `time` (Android), else the segment's start plus its
    `durationMinutesOffsetFromStartTime` (iPhone), whose `raw_id` is then that instant."""
    if not isinstance(point, dict):
        counts[BAD_COORDINATES] += 1
        return None
    raw_time = point.get("time")
    at = _rfc3339(raw_time)
    if raw_time is None:
        at = _offset(segment_start, point.get("durationMinutesOffsetFromStartTime"))
        raw_time = at
    if at is None:
        counts[NO_TIMESTAMP] += 1
        return None
    coords = _geo(point.get("point"))
    if coords is None:
        counts[BAD_COORDINATES] += 1
        return None
    lat, lon = coords
    extra = {"segment": "timelinePath", **{k: v for k, v in point.items() if k not in ("point", "time")}}
    return _line(at, {"schema": SCHEMA, "lat": lat, "lon": lon, "raw_id": f"path:{raw_time}", "extra": extra})


def _offset(start: object, minutes: object) -> str | None:
    """`start` plus `minutes` (a number, or a string of one) as RFC3339 UTC; None when either is not."""
    begun = _instant(start)
    try:
        offset = float(minutes)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if begun is None or not math.isfinite(offset) or isinstance(minutes, bool):
        return None
    try:
        return (begun + timedelta(minutes=offset)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, ValueError):
        return None


def _visit_coordinates(visit: dict[str, Any]) -> tuple[float, float] | None:
    return _location(_nested(visit, "topCandidate", "placeLocation"))


def _location(value: object) -> tuple[float, float] | None:
    """`{"latLng": "59.911°, 10.75°"}` (Android) or `"geo:59.911,10.75"` (iPhone) → (lat, lon)."""
    return _latlng(value.get("latLng") if isinstance(value, dict) else value)


# -- Semantic Location History ----------------------------------------------------------


def _from_timeline_object(obj: object, counts: dict[str, int]) -> Iterator[dict[str, Any]]:
    """A `placeVisit` or an `activitySegment` → its two edges, the object whole under `extra`."""
    if not isinstance(obj, dict):
        return
    for key in SEMANTIC_KEYS:
        item = obj.get(key)
        if not isinstance(item, dict):
            continue
        duration = item.get("duration")
        duration = duration if isinstance(duration, dict) else {}
        edges = {edge: _duration_edge(duration, edge) for edge in ("start", "end")}
        span = {"segment_start": edges["start"][1], "segment_end": edges["end"][1]}
        for edge, (raw_time, _text, at) in edges.items():
            if at is None:
                counts[NO_TIMESTAMP] += 1
                continue
            coords = _place_visit_coordinates(item) if key == "placeVisit" else _e7_location(item, edge)
            if coords is None:
                counts[BAD_COORDINATES] += 1
                continue
            lat, lon = coords
            extra: dict[str, Any] = {"segment": key, "edge": edge, **span, key: item}
            payload = {
                "schema": SCHEMA,
                "lat": lat,
                "lon": lon,
                "raw_id": f"{key}:{raw_time}:{edge}",
                "extra": extra,
            }
            yield _line(at, payload)


def _duration_edge(duration: dict[str, Any], edge: str) -> tuple[object, object, str | None]:
    """(the raw value, the span's text, the line's `at`) of one edge of a `duration`: the ISO
    `<edge>Timestamp` kept as written, or the older `<edge>TimestampMs` as RFC3339 UTC."""
    raw = duration.get(f"{edge}Timestamp")
    if raw is not None:
        return raw, raw, _rfc3339(raw)
    raw = duration.get(f"{edge}TimestampMs")
    at = _from_millis(raw) if raw is not None else None
    return raw, at, at


def _place_visit_coordinates(visit: dict[str, Any]) -> tuple[float, float] | None:
    """The place's own coordinates (`location.latitudeE7`), else the visit's centre."""
    found = _e7_pair(_nested(visit, "location", "latitudeE7"), _nested(visit, "location", "longitudeE7"))
    return found or _e7_pair(visit.get("centerLatE7"), visit.get("centerLngE7"))


def _e7_location(activity: dict[str, Any], edge: str) -> tuple[float, float] | None:
    where = activity.get(f"{edge}Location")
    if not isinstance(where, dict):
        return None
    return _e7_pair(where.get("latitudeE7"), where.get("longitudeE7"))


def _e7_pair(lat: object, lon: object) -> tuple[float, float] | None:
    found = _e7(lat, 90), _e7(lon, 180)
    return None if found[0] is None or found[1] is None else (found[0], found[1])


def _nested(obj: object, *keys: str) -> object:
    for key in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _geo(value: object) -> tuple[float, float] | None:
    """`"geo:59.911,10.75"` → (lat, lon)."""
    if not isinstance(value, str) or not value.startswith("geo:"):
        return None
    return _pair(value.removeprefix("geo:"))


def _latlng(value: object) -> tuple[float, float] | None:
    """`"59.911°, 10.75°"`, or `"geo:59.911,10.75"`, → (lat, lon)."""
    if not isinstance(value, str):
        return None
    if value.startswith("geo:"):
        return _geo(value)
    return _pair(value.replace("°", ""))


def _pair(text: str) -> tuple[float, float] | None:
    parts = text.split(",")
    if len(parts) != 2:
        return None
    try:
        lat, lon = (float(p.strip()) for p in parts)
    except ValueError:
        return None
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


# -- shared ---------------------------------------------------------------------------


def _line(at: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "at": at,
        "end": None,
        "tz": None,
        "source": SOURCE,
        "kind": KIND,
        "tier": TIER,
        "payload": payload,
    }


def _rfc3339(value: object) -> str | None:
    """An ISO 8601 time with any offset (or none, taken as UTC) → RFC3339 UTC to the second."""
    parsed = _instant(value)
    if parsed is None:
        return None
    try:
        return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, ValueError):
        return None


def _instant(value: object) -> datetime | None:
    """An ISO 8601 time with any offset (or none, taken as UTC) as an aware datetime."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _finite(value: object) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return value
