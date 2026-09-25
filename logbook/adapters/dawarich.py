"""Dawarich → location/v1 (RFC 0001).

Reads Dawarich's GeoJSON export: a FeatureCollection of Point features whose properties carry the
tracker's fields (timestamp in unix seconds, accuracy, altitude/velocity/course as strings, a
`tracker_id` UUID, optional device fields) and, when Dawarich has reverse-geocoded the point, a
nested Photon Feature under `geodata`. Pure: reads one file, makes no network calls.

The export can be gigabytes (millions of points), so the file is streamed with ijson: `sniff`
reads up to the end of the first feature and `run` holds one feature at a time.

`draft(props, lat, lon)` is the one mapping from a Dawarich point to a location/v1 line draft. The
live adapter (`dawarich_live`) calls it too, with a row of `GET /api/v1/points`, which carries the
same point attributes as an export feature's properties: a point imported from an export and the
same point pulled live are the same line with the same `raw_id`, so it is deduped, not duplicated.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import ijson

NAME = "dawarich"
KIND = "location"
TIER = 1
SCHEMA = "location/v1"

# the compact subset of a Photon reverse-geocode result worth keeping on every point
PLACE_FIELDS = (
    "name",
    "type",
    "street",
    "housenumber",
    "district",
    "city",
    "postcode",
    "country",
    "countrycode",
    "osm_type",
    "osm_id",
)
DEVICE_FIELDS = ("battery", "ssid", "bssid", "motion_data")


def sniff(path: Path) -> bool:
    """A FeatureCollection whose first feature has properties.tracker_id and properties.timestamp."""
    path = Path(path)
    if not path.is_file():
        return False
    try:
        doc_type, first = _head(path)
    except (OSError, ValueError, ijson.JSONError):
        return False
    if doc_type != "FeatureCollection" or not isinstance(first, dict):
        return False
    props = first.get("properties")
    return isinstance(props, dict) and "tracker_id" in props and "timestamp" in props


def _head(path: Path) -> tuple[object, object]:
    """The document's `type` and its first feature, reading no further than the first feature.

    Dawarich writes `type` before `features`; a `type` that comes after is not seen."""
    doc_type: object = None
    builder: ijson.ObjectBuilder | None = None
    with path.open("rb") as fh:
        for prefix, event, value in ijson.parse(fh, use_float=True):
            if prefix == "type" and event == "string":
                doc_type = value
            elif prefix == "features" and event == "end_array":
                break
            elif prefix == "features.item" and event == "start_map":
                builder = ijson.ObjectBuilder()
            if builder is not None:
                builder.event(event, value)
                if prefix == "features.item" and event == "end_map":
                    return doc_type, builder.value
    return doc_type, None


def run(path: Path, since: str | None = None) -> Iterator[dict[str, Any]]:
    """Yield one location/v1 line draft per point, in export order. `since` is RFC3339 UTC."""
    with Path(path).open("rb") as fh:
        for feature in ijson.items(fh, "features.item", use_float=True):
            line = _draft_of(feature)
            if since and line["at"] < since:
                continue
            yield line


def _draft_of(feature: dict[str, Any]) -> dict[str, Any]:
    lon, lat = feature["geometry"]["coordinates"][:2]  # GeoJSON: longitude first
    return draft(feature["properties"], lat, lon)


def draft(props: Mapping[str, Any], lat: float, lon: float) -> dict[str, Any]:
    """One Dawarich point → one location/v1 line draft. `props` are the point's attributes (an
    export feature's properties, or a row of the points API); they must carry `timestamp` (unix
    seconds) and `tracker_id`. Fields not named here are ignored."""
    return {
        "at": _rfc3339(props["timestamp"]),
        "end": None,
        "tz": None,  # the logbook's own
        "source": NAME,
        "kind": KIND,
        "tier": TIER,
        "payload": payload(props, lat, lon),
    }


def _rfc3339(unix_seconds: int | float) -> str:
    return datetime.fromtimestamp(int(unix_seconds), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _number(value: object) -> float | None:
    """Dawarich exports altitude/velocity/course as strings; None when absent, unparsable or not finite."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _payload(feature: dict[str, Any]) -> dict[str, Any]:
    lon, lat = feature["geometry"]["coordinates"][:2]
    return payload(feature["properties"], lat, lon)


def payload(props: Mapping[str, Any], lat: float, lon: float) -> dict[str, Any]:
    anomaly = props.get("anomaly")
    payload: dict[str, Any] = {"schema": SCHEMA, "lat": lat, "lon": lon}
    accuracy = _number(props.get("accuracy"))
    if accuracy is not None:
        payload["accuracy_m"] = accuracy
    alt = _number(props.get("altitude"))
    if alt is not None and not (alt == 0.0 and anomaly):
        payload["alt_m"] = alt
    speed = _number(props.get("velocity"))
    if speed is not None and speed >= 0:
        payload["speed_mps"] = speed
    heading = _number(props.get("course"))
    if heading is not None and 0 <= heading <= 360:
        payload["heading_deg"] = heading
    payload["tracker"] = props["tracker_id"]
    payload["raw_id"] = f"{props['tracker_id']}:{props['timestamp']}"
    payload["extra"] = _extra(props, anomaly)
    return payload


def _extra(props: Mapping[str, Any], anomaly: object) -> dict[str, Any]:
    extra: dict[str, Any] = {
        "track_id": props.get("track_id"),
        "anomaly": anomaly,
        "vertical_accuracy": props.get("vertical_accuracy"),
    }
    for key in DEVICE_FIELDS:
        if props.get(key) is not None:
            extra[key] = props[key]
    geodata = props.get("geodata")
    if isinstance(geodata, dict):
        place_props = geodata.get("properties")
        if isinstance(place_props, dict):
            place = {k: place_props[k] for k in PLACE_FIELDS if place_props.get(k) is not None}
            if place:
                extra["place"] = place
    return extra
