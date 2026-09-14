"""Dawarich → location/v1 (RFC 0001).

Reads Dawarich's GeoJSON export: a FeatureCollection of Point features whose properties carry the
tracker's fields (timestamp in unix seconds, accuracy, altitude/velocity/course as strings, a
`tracker_id` UUID, optional device fields) and, when Dawarich has reverse-geocoded the point, a
nested Photon Feature under `geodata`. Pure: reads one file, makes no network calls.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(doc, dict) or doc.get("type") != "FeatureCollection":
        return False
    features = doc.get("features")
    if not isinstance(features, list) or not features:
        return False
    props = features[0].get("properties") if isinstance(features[0], dict) else None
    return isinstance(props, dict) and "tracker_id" in props and "timestamp" in props


def run(path: Path, since: str | None = None) -> Iterator[dict[str, Any]]:
    """Yield one location/v1 line draft per point, in export order. `since` is RFC3339 UTC."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    for feature in doc["features"]:
        at = _rfc3339(feature["properties"]["timestamp"])
        if since and at < since:
            continue
        yield {
            "at": at,
            "end": None,
            "tz": None,  # the logbook's own
            "source": NAME,
            "kind": KIND,
            "tier": TIER,
            "payload": _payload(feature),
        }


def _rfc3339(unix_seconds: int | float) -> str:
    return datetime.fromtimestamp(int(unix_seconds), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _number(value: object) -> float | None:
    """Dawarich exports altitude/velocity/course as strings; None when absent or unparsable."""
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _payload(feature: dict[str, Any]) -> dict[str, Any]:
    props: dict[str, Any] = feature["properties"]
    lon, lat = feature["geometry"]["coordinates"][:2]  # GeoJSON: longitude first
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
    if heading is not None and heading >= 0:
        payload["heading_deg"] = heading
    payload["tracker"] = props["tracker_id"]
    payload["raw_id"] = f"{props['tracker_id']}:{props['timestamp']}"
    payload["extra"] = _extra(props, anomaly)
    return payload


def _extra(props: dict[str, Any], anomaly: object) -> dict[str, Any]:
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
