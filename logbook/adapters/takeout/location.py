"""Google Takeout Location History → location/v1 (RFC 0001).

Two export shapes, both read with ijson so a multi-gigabyte file is never held in memory:

- `Records.json`, the archive Takeout writes: `{"locations": [{latitudeE7, longitudeE7, timestamp,
  accuracy, altitude?, velocity?, heading?, source?, deviceTag?, ...}]}`. Older archives carry
  `timestampMs` (a string of unix milliseconds) instead of `timestamp`.
- `Timeline.json`, the newer export a phone writes on its own: `{"semanticSegments": [...]}` where
  a segment holds a `timelinePath` (raw points as `"geo:lat,lng"` plus `time`), a `visit` (one
  place) or an `activity` (a move with `start` and `end`).

Every raw point becomes one line. A visit or an activity becomes exactly two lines, its start and
its end coordinate; the span itself is not a location line (RFC 0001) and what it means is engine
work (ADR 0011). Nothing the source says is dropped: what has no RFC field is kept under
`payload.extra`. An item with no usable timestamp or with a missing, non-numeric, non-finite or
out-of-range coordinate is skipped and tallied in `counts`. Pure: one file, no network.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import ijson

from logbook.adapters.takeout import SOURCE

NAME = "google-takeout-location"
KIND = "location"
TIER = 1
SCHEMA = "location/v1"

RECORDS = "locations"
TIMELINE = "semanticSegments"
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
    """A JSON object whose `locations` or `semanticSegments` array starts with an item of the right shape."""
    path = Path(path)
    if not path.is_file():
        return False
    try:
        shape, first = _head(path)
    except (OSError, ValueError, ijson.JSONError):
        return False
    if not isinstance(first, dict):
        return False
    if shape == RECORDS:
        return "latitudeE7" in first and "longitudeE7" in first
    if shape == TIMELINE:
        return any(k in first for k in ("timelinePath", "visit", "activity", "startTime"))
    return False


def _head(path: Path) -> tuple[str | None, object]:
    """Which top-level array the file has and its first item, reading no further than that item.

    Gives up after SNIFF_EVENT_BUDGET events so an unrelated multi-gigabyte document is not streamed
    to its end just to say no."""
    builder: ijson.ObjectBuilder | None = None
    shape: str | None = None
    with path.open("rb") as fh:
        for n, (prefix, event, value) in enumerate(ijson.parse(fh, use_float=True)):
            if builder is None:
                if n >= SNIFF_EVENT_BUDGET:
                    return None, None
                if event == "start_map" and prefix in (f"{RECORDS}.item", f"{TIMELINE}.item"):
                    shape = prefix.removesuffix(".item")
                    builder = ijson.ObjectBuilder()
                elif event == "end_array" and prefix in (RECORDS, TIMELINE):
                    return prefix, None  # empty: nothing to import, so not ours
                elif event == "start_array" and prefix in (RECORDS, TIMELINE):
                    continue
                elif prefix in (f"{RECORDS}.item", f"{TIMELINE}.item"):
                    return prefix.removesuffix(".item"), value  # a scalar item: not ours
                else:
                    continue
            builder.event(event, value)
            if event == "end_map" and prefix == f"{shape}.item":
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
        elif shape == TIMELINE:
            items = (
                line
                for s in ijson.items(fh, f"{TIMELINE}.item", use_float=True)
                for line in _from_segment(s, counts)
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
            line = _from_path_point(point, counts)
            if line is not None:
                yield line
    for key in ("visit", "activity"):
        item = segment.get(key)
        if not isinstance(item, dict):
            continue
        for edge, raw_time in (("start", start), ("end", end)):
            coords = _visit_coordinates(item) if key == "visit" else _latlng(_nested(item, edge, "latLng"))
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


def _from_path_point(point: object, counts: dict[str, int]) -> dict[str, Any] | None:
    if not isinstance(point, dict):
        counts[BAD_COORDINATES] += 1
        return None
    raw_time = point.get("time")
    at = _rfc3339(raw_time)
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


def _visit_coordinates(visit: dict[str, Any]) -> tuple[float, float] | None:
    return _latlng(_nested(visit, "topCandidate", "placeLocation", "latLng"))


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
    """`"59.911°, 10.75°"` → (lat, lon)."""
    if not isinstance(value, str):
        return None
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
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    try:
        return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, ValueError):
        return None


def _finite(value: object) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return value
