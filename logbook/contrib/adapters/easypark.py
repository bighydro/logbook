"""EasyPark's recent parkings → journey/v1 (RFC 0020; `trip/v1` renamed by RFC 0031), mode `parking`.

The EasyPark app keeps no parking sessions on the phone; what it keeps, under its container's
`Documents/`, is `recentparkings_<user>.json`: the areas the owner parked in most recently, one
record each —

    id, signageAreaCode, areaNumber, operatorName, areaDescription, areaType (OnStreet, SurfaceLot),
    latitude, longitude (numbers, or numbers as strings), cluster,
    lastModified   seconds since 2001-01-01 UTC: when the area was last used

— and `findmycar-pin_<user>.json`, the pinned car position, which is not read. `logbook import-backup`
copies the recent-parkings file out (source `easypark`, a folder source whose glob is the file's
name) and runs this adapter on the folder; the input may also be the file itself.

Each record is one line (RFC 0020 rule 4): `at` the last-used time, `end` null, `extra.observed`
`last_used` so a reader knows the span is unknown rather than zero; `from` is the area — its
description as `name`, the signage code as `code`, the operator, the coordinates — and there is no
`to`. `raw_id` is `easypark:<area id>@<at>`, so the same file again appends nothing and the next use
of the same area is a new line. A record without a positive time is a placeholder and is counted
(`skipped_no_timestamp`); one whose coordinates do not parse or are off the globe is counted
(`skipped_bad_coordinates`); one with no coordinates at all is kept without them. Lines come out
oldest first. Tier 1 (the owner's own movement; no price is on the phone). Pure: one JSON file read
once, no network.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

NAME = "easypark"
KIND = "journey"  # RFC 0031: the written form of RFC 0020 since 2026-10-05; readers accept `trip` too
SCHEMA = "journey/v1"
TIER = 1
MODE = "parking"
FILES = "recentparkings_*.json"
APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=UTC)
REQUIRED = ("areaNumber", "lastModified")


def sniff(path: Path) -> bool:
    """A `recentparkings_*.json` holding a list of area records, or a folder with one. Never raises."""
    try:
        return any(_records(f) is not None for f in _files(Path(path)))
    except (OSError, ValueError):
        return False


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
) -> Iterator[dict[str, Any]]:
    """One journey/v1 draft per recently used area, oldest first. `since` is RFC3339 UTC; drafts whose
    `at` is before it are not yielded. `counts` tallies `skipped_no_timestamp` and
    `skipped_bad_coordinates`. `timezone` is the record's zone (the file names none)."""
    counts = counts if counts is not None else {}
    drafts: list[dict[str, Any]] = []
    for file in _files(Path(path)):
        records = _records(file)
        if records is None:
            continue
        for record in records:
            draft = _draft(record, counts, timezone)
            if draft is not None and not (since and draft["at"] < since):
                drafts.append(draft)
    drafts.sort(key=lambda d: (d["at"], d["payload"]["raw_id"]))
    yield from drafts


def _files(path: Path) -> list[Path]:
    if path.is_file():
        return [path] if fnmatch(path.name, FILES) else []
    if path.is_dir():
        return sorted(f for f in path.iterdir() if f.is_file() and fnmatch(f.name, FILES))
    return []


def _records(file: Path) -> list[dict[str, Any]] | None:
    """The file's area records, or None when it is not a recent-parkings file."""
    try:
        data = json.loads(file.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, list) or not data:
        return None
    records = [r for r in data if isinstance(r, dict)]
    if not records or not all(all(k in r for k in REQUIRED) for r in records):
        return None
    return records


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _draft(record: dict[str, Any], counts: dict[str, int], timezone: str | None) -> dict[str, Any] | None:
    seconds = record.get("lastModified")
    if isinstance(seconds, bool) or not isinstance(seconds, int | float) or seconds <= 0:
        _count(counts, "skipped_no_timestamp")
        return None
    at = (
        (APPLE_EPOCH + timedelta(seconds=float(seconds)))
        .replace(microsecond=0)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    try:
        coordinates = _coordinates(record)
    except ValueError:
        _count(counts, "skipped_bad_coordinates")
        return None
    from_: dict[str, Any] = {}
    for field, key in (
        ("name", "areaDescription"),
        ("code", "signageAreaCode"),
        ("operator", "operatorName"),
    ):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            from_[field] = value.strip()
    if coordinates is not None:
        from_["latitude"], from_["longitude"] = coordinates
    if not from_:
        from_["code"] = str(record.get("areaNumber"))
    extra: dict[str, Any] = {}
    if isinstance(record.get("areaType"), str) and record["areaType"]:
        extra["area_type"] = record["areaType"]
    extra["observed"] = "last_used"
    if isinstance(record.get("areaNumber"), int):
        extra["area_number"] = record["areaNumber"]
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": f"{NAME}:{record.get('id', record.get('areaNumber'))}@{at}",
        "mode": MODE,
        "provider": NAME,
        "from": from_,
        "extra": extra,
    }
    return {
        "at": at,
        "end": None,
        "tz": timezone,
        "source": NAME,
        "kind": KIND,
        "tier": TIER,
        "payload": payload,
    }


def _coordinates(record: dict[str, Any]) -> tuple[float, float] | None:
    """(latitude, longitude); None when the record has neither; ValueError when what it has is
    unusable (not numbers, off the globe, or the null island placeholder)."""
    raw = (record.get("latitude"), record.get("longitude"))
    if raw == (None, None):
        return None
    try:
        lat, lon = (float(str(v)) for v in raw)
    except ValueError as e:
        raise ValueError("coordinates are not numbers") from e
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        raise ValueError("coordinates are off the globe")
    return lat, lon
