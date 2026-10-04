"""Google Takeout Fit/ → health-sample/v1 (RFC 0014): the body's measurements as Google Fit kept them.

Takeout's `Fit/` folder holds three families, and this adapter reads all three, from the folder, from
one of its subfolders, or from a single file:

    All Data/<data source>.json       the raw streams: `{"Data Source": "<id>", "Data Points": [...]}`,
                                      one file per data source (`derived_com.google.step_count.delta_
                                      com.google.and.json`), each point with `dataTypeName`,
                                      `startTimeNanos`, `endTimeNanos`, `fitValue[0].value.{intVal,fpVal}`
                                      and `originDataSourceId`, the source that measured it
    All Sessions/<start>_<ACTIVITY>.json   the workouts: `fitnessActivity`, `startTime`, `endTime`,
                                      `duration`, `aggregate` (steps, distance, calories, heart points,
                                      move minutes), `application.packageName`
    Daily activity metrics/*.csv      `Daily activity metrics.csv`, one row per day (`Date`, `Step count`,
                                      `Distance (m)`, `Calories (kcal)`, `Heart Points`, `Move Minutes
                                      count`, average, max and min heart rate, …), and `<YYYY-MM-DD>.csv`,
                                      the same figures per quarter hour of that day (`Start time`, `End
                                      time`)

`Activities/` (one TCX per workout) is not read. The streams this version maps (`dataTypeName`):
`com.google.step_count.delta` → `steps`, `com.google.distance.delta` → `distance` (m), summed into
quarter-hour buckets aligned to the UTC hour, one bucket per device (rule 2), `raw_id` `<type>:<bucket
start>:<device>`; `com.google.heart_rate.bpm` → `heart_rate`, at its own resolution but at most one
reading per UTC minute per device, the rest counted (rule 3); `com.google.weight` → `weight` (kg) and
`com.google.body.fat.percentage` → `body_fat_pct`, one line per point; `com.google.sleep.segment` →
`sleep`, one span per segment with Fit's stage mapped to the profile's (1 awake, 2 asleep, 4 light →
`core`, 5 deep, 6 rem; 0 unspecified and 3 out of bed are counted, rule 4). An instant's `raw_id` is
`<type>:<start nanos>:<device>`. Any other stream (`com.google.calories.expended`, which counts the
basal rate in and so is neither `active_energy` nor `basal_energy`; `com.google.activity.segment`;
`com.google.active_minutes`; `com.google.heart_minutes`; height; speed) is counted, one per file, never
mapped to a near type (rule 8). When Google's own merged stream of a type is in the export
(`derived:…:merge_step_deltas`), the raw streams of that type are the same points before merging and
are counted (`skipped_covered_by_merge`), so a reading is written once; the merged points name the
device that measured each one.

A session is a `workout` span, `value` its duration in seconds (the file's `duration`, else the
span), `source_name` the app that recorded it, `raw_id` `workout:<id>` when the session has one, else
`workout:<start>:<activity>`; under `extra` the `activity` in the vocabulary `apple-health` uses
(`biking` → `cycling`, `strength_training` → `traditional_strength_training`, …; an activity with no
such name keeps Fit's own), Fit's `activity_type` as spelled, and the aggregates as `steps`,
`distance_m`, `energy_kcal`, `heart_points`, `move_minutes`; the session's `name` when the owner gave
it one. A session whose activity is `sleep` is the night in bed: a `sleep` span with stage `in_bed`,
`raw_id` `sleep:session:<start>`; the stages come from the stream (rule 4).

The daily CSVs are the fallback. A day's quarter-hour file is read as a stream would be: every
window's step count and distance go into the buckets, with no device (the file names none; `-` in the
`raw_id`). `Daily activity metrics.csv` is read last: for a day no stream and no window touched (per
type, in the record's zone), one `steps` and one `distance` line spanning that local day, `raw_id`
`<type>:day:<YYYY-MM-DD>`, `extra.period` `day`; the day's figures the profile has no type for
(`calories_kcal`, `heart_points`, `move_minutes`, `heart_rate_avg_bpm`, `heart_rate_max_bpm`,
`heart_rate_min_bpm`) ride under `extra` of the day's `steps` line (the `distance` line when there is
no step count). A day the streams cover is counted (`skipped_covered_by_stream`); a row with neither
steps nor distance too (`skipped_no_value`). The latitude, longitude, speed and weight columns are
never read: a day's bounding box is a location, and the daily weight is derived from the stream. The
columns are found by what their header says; a CSV without a date or start column, or without any of
the step, distance, Heart Points and Move Minutes columns, is counted (`skipped_unreadable_csv`).

Every line is tier 3 (SPEC §4; `logbook add --tier` overrides), `source` `google-takeout` (ADR 0008:
one archive, several witnesses), `kind` `health`. `device` is the manufacturer and model the point's
data source names (`Google Pixel 8`, `Fossil Gen 6`, `Withings Body+`), `source_name` the package of
the app that recorded it (`com.google.android.gms`, a third-party app); a device uid is never written.
`tz` is the record's zone (Fit keeps offsets, which name no zone). Timestamps are the export's,
nanoseconds since 1970 converted to UTC and never corrected (rule 7); a point without a start, or with
one at or before the epoch, is counted (`skipped_no_date`). A file is read in its own order, the
streams one point in memory at a time through `ijson`. Pure: nothing is written back, nothing fetched.

The same quarter hour counted by an Apple Watch through `apple-health` and by a phone through Fit is
two lines under two sources (rule 5): this adapter writes both and dedupes nothing across sources, and
a reader that wants one number takes, per bucket, the larger device (`logbook stats --health`).
"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from pathlib import Path
from typing import Any

from ...stream import ijson
from .. import health_export as hx
from . import SOURCE

NAME = "google-takeout-fit"
KIND = "health"
TIER = 3  # SPEC §4: health is tier 3; `logbook add --tier` overrides
SCHEMA = "health-sample/v1"
FOLDER = "Fit"
SUBFOLDERS = ("All Data", "All Sessions", "Daily activity metrics")

JSON_SUFFIX = ".json"
CSV_SUFFIX = ".csv"
SNIFF_BYTES = 4096
SNIFF_FILES = 64  # a folder is recognised by the first files in it, never by all of them
STREAM_MARKS = (b'"Data Points"', b'"dataTypeName"')
SESSION_MARKS = (b'"fitnessActivity"', b'"startTime"')
DATA_SOURCE = re.compile(rb'"Data Source"\s*:\s*"([^"]*)"')
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
BUCKET = timedelta(minutes=15)
NO_DEVICE = "-"  # the device slot of a raw_id when the source names none
MERGED = "merge"  # in the stream name of a data source Google merged from the raw ones
SLEEP_ACTIVITY = "sleep"
DAY = "day"

TYPES = {  # a point's dataTypeName → profile type
    "com.google.step_count.delta": "steps",
    "com.google.distance.delta": "distance",
    "com.google.heart_rate.bpm": "heart_rate",
    "com.google.weight": "weight",
    "com.google.body.fat.percentage": "body_fat_pct",
    "com.google.sleep.segment": "sleep",
}
UNITS = {  # profile type → unit (RFC 0014)
    "steps": "count",
    "distance": "m",
    "heart_rate": "bpm",
    "weight": "kg",
    "body_fat_pct": "%",
    "sleep": "s",
    "workout": "s",
}
BUCKETED = frozenset({"steps", "distance"})
CAPPED = frozenset({"heart_rate"})
STAGES = {1: "awake", 2: "asleep", 4: "core", 5: "deep", 6: "rem"}  # 0 unspecified, 3 out of bed: counted
AGGREGATES = {  # a session aggregate's metricName → the `extra` key, as apple-health spells them
    "com.google.step_count.delta": "steps",
    "com.google.distance.delta": "distance_m",
    "com.google.calories.expended": "energy_kcal",
    "com.google.heart_minutes": "heart_points",
    "com.google.active_minutes": "move_minutes",
}
ACTIVITIES = {  # Fit's activity names that apple-health spells otherwise; the rest keep Fit's own
    "biking": "cycling",
    "biking.hand": "hand_cycling",
    "circuit_training": "cross_training",
    "dancing": "dance",
    "football.american": "american_football",
    "football.australian": "australian_football",
    "football.soccer": "soccer",
    "ice_skating": "skating_sports",
    "interval_training": "hiit",
    "kayaking": "paddle_sports",
    "canoeing": "paddle_sports",
    "standup_paddleboarding": "paddle_sports",
    "rock_climbing": "climbing",
    "skating": "skating_sports",
    "skiing.cross_country": "cross_country_skiing",
    "skiing.downhill": "downhill_skiing",
    "strength_training": "traditional_strength_training",
    "treadmill": "running",
    "windsurfing": "water_sports",
    "kitesurfing": "water_sports",
}
# the daily CSV's columns, by the words in the header: (column key, the words it must hold)
METRICS = {"steps": ("step count",), "distance": ("distance",)}
FIGURES = {  # a day's figures the profile has no type for → the `extra` key on the day's steps line
    "calories_kcal": ("calories",),
    "heart_points": ("heart points",),
    "move_minutes": ("move minutes",),
    "heart_rate_avg_bpm": ("average heart rate",),
    "heart_rate_max_bpm": ("max heart rate",),
    "heart_rate_min_bpm": ("min heart rate",),
}
NEVER_READ = ("latitude", "longitude", "speed", "weight")
FIT_COLUMNS = ("step count", "distance", "heart points", "move minutes")  # one of them makes a CSV Fit's
DATE_COLUMN = "date"
START_COLUMN = "start time"


def sniff(path: Path) -> bool:
    """`Fit/` (a folder with one of its three subfolders), one of those subfolders, or one of their
    files: a stream, a session, or a daily CSV. Never raises."""
    path = Path(path)
    try:
        if path.is_dir():
            return _is_fit_folder(path)
        return _kind(path) is not None
    except OSError:
        return False


def _is_fit_folder(folder: Path) -> bool:
    if any((folder / sub).is_dir() for sub in SUBFOLDERS):
        return True
    return any(_kind(file) is not None for file in _files_in(folder)[:SNIFF_FILES])


def _files_in(folder: Path) -> list[Path]:
    """The JSON and CSV files directly in `folder`, by name; hidden files are not exports."""
    try:
        entries = sorted(folder.iterdir())
    except OSError:
        return []
    return [
        p
        for p in entries
        if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in (JSON_SUFFIX, CSV_SUFFIX)
    ]


def _kind(path: Path) -> str | None:
    """`stream`, `session`, `windows` (a day's quarter hours), `days` (one row per day), or None."""
    if not path.is_file():
        return None
    suffix = path.suffix.lower()
    if suffix == JSON_SUFFIX:
        try:
            with path.open("rb") as fh:
                head = fh.read(SNIFF_BYTES)
        except OSError:
            return None
        if all(mark in head for mark in SESSION_MARKS):
            return "session"
        return "stream" if any(mark in head for mark in STREAM_MARKS) else None
    if suffix != CSV_SUFFIX:
        return None
    header = _header(path)
    if header is None or not any(_column(header, words) for words in FIT_COLUMNS):
        return None
    if START_COLUMN in header:
        return "windows"
    return "days" if DATE_COLUMN in header else None


def _header(path: Path) -> list[str] | None:
    try:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            cells = next(csv.reader(fh), [])
    except (OSError, UnicodeDecodeError, csv.Error, StopIteration):
        return None
    return [cell.strip().lower() for cell in cells] or None


def _column(header: list[str], *words: str) -> str | None:
    """The first header cell holding every one of `words` and none of the columns never read."""
    for cell in header:
        if all(word in cell for word in words) and not any(never in cell for never in NEVER_READ):
            return cell
    return None


@dataclass
class _Bucket:
    """One open 15-minute bucket of one type from one device."""

    start: datetime
    total: float = 0.0
    samples: int = 0
    device: str | None = None
    source_name: str | None = None


@dataclass
class _State:
    counts: dict[str, int]
    since: str | None
    tier: int
    tz: str | None
    local: tzinfo
    buckets: dict[tuple[str, str], _Bucket] = field(default_factory=dict)
    last_reading: dict[tuple[str, str], datetime] = field(default_factory=dict)  # (type, device) → minute
    covered: set[tuple[str, str]] = field(default_factory=set)  # (type, local day) a bucket touched


@dataclass
class _Draft:
    """One mapped point, window or session before bucketing and capping."""

    type: str
    start: datetime
    end: datetime | None
    value: float
    raw_id: str
    device: str | None = None
    source_name: str | None = None
    stage: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Stream:
    path: Path
    source: str | None  # the file's `Data Source`, None when the head does not say
    type_name: str | None  # the data type that source names
    merged: bool


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    tier: int | None = None,
    timezone: str | None = None,
) -> Iterator[dict[str, Any]]:
    """One health-sample/v1 line per reading, stage, workout and night, one per quarter-hour bucket
    of steps and distance per device, and one per day of either for the days the streams do not
    cover: `path` is `Fit/`, one of its subfolders, or one file. The streams first, in file order,
    then the daily quarter-hour files, then the daily rows, then the sessions.

    `since` is RFC3339 UTC; lines with `at` before it are not yielded. `counts` tallies what was
    skipped (`skipped_no_date`, `skipped_no_value`, `skipped_bad_span`, `skipped_other_type`,
    `skipped_unknown_stage`, `skipped_over_cap`, `skipped_covered_by_merge`,
    `skipped_covered_by_stream`, `skipped_unreadable_json`, `skipped_unreadable_csv`,
    `skipped_bad_date`, `skipped_bad_start`, `skipped_no_start`). `tier` overrides the default 3;
    `timezone` is the record's zone, the lines' `tz` and the clock a day is read in."""
    path = Path(path)
    state = _State(counts if counts is not None else {}, since, tier or TIER, timezone, hx.zone(timezone))
    streams: list[_Stream] = []
    windows: list[Path] = []
    days: list[Path] = []
    sessions: list[Path] = []
    for file in _files(path):
        kind = _kind(file)
        if kind == "stream":
            streams.append(_stream(file))
        elif kind == "session":
            sessions.append(file)
        elif kind == "windows":
            windows.append(file)
        elif kind == "days":
            days.append(file)
        elif file.suffix.lower() == JSON_SUFFIX:
            _count(state, "skipped_unreadable_json")
        else:
            _count(state, "skipped_unreadable_csv")
    for stream in _without_raw_copies(streams, state):
        yield from _read_stream(stream, state)
    for file in windows:
        yield from _read_windows(file, state)
    for file in days:
        yield from _read_days(file, state)
    for file in sessions:
        yield from _read_session(file, state)


def _files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    subfolders = [path / sub for sub in SUBFOLDERS if (path / sub).is_dir()]
    return [file for folder in (subfolders or [path]) for file in _files_in(folder)]


def _count(state: _State, key: str) -> None:
    state.counts[key] = state.counts.get(key, 0) + 1


# -- the streams -------------------------------------------------------------------------------------


def _stream(path: Path) -> _Stream:
    source: str | None = None
    try:
        with path.open("rb") as fh:
            head = fh.read(SNIFF_BYTES)
    except OSError:
        head = b""
    match = DATA_SOURCE.search(head)
    if match:
        source = match.group(1).decode("utf-8", "replace")
    parts = source.split(":") if source else []
    type_name = parts[1] if len(parts) > 1 and parts[1] else None
    return _Stream(path, source, type_name, bool(parts) and MERGED in parts[-1])


def _without_raw_copies(streams: list[_Stream], state: _State) -> list[_Stream]:
    """The streams to read: when a type has a merged stream, its raw streams are counted and left."""
    merged = {s.type_name for s in streams if s.merged and s.type_name}
    kept: list[_Stream] = []
    for stream in streams:
        if stream.type_name in merged and not stream.merged:
            _count(state, "skipped_covered_by_merge")
            continue
        kept.append(stream)
    return kept


def _read_stream(stream: _Stream, state: _State) -> Iterator[dict[str, Any]]:
    kind = TYPES.get(stream.type_name or "")
    if stream.type_name is not None and kind is None:
        _count(state, "skipped_other_type")
        return
    try:
        with stream.path.open("rb") as fh:
            for point in ijson.items(fh, "Data Points.item", use_float=True):
                if not isinstance(point, dict):
                    continue
                draft = _point(point, stream, state)
                if draft is not None:
                    yield from _emit(draft, state)
                yield from _flush(state, _datetime(_nanos(point.get("startTimeNanos"))))
    except (OSError, ijson.JSONError, ValueError):
        _count(state, "skipped_unreadable_json")
    yield from _flush(state, None)


def _point(point: dict[str, Any], stream: _Stream, state: _State) -> _Draft | None:
    type_name = point.get("dataTypeName") if isinstance(point.get("dataTypeName"), str) else stream.type_name
    kind = TYPES.get(type_name or "")
    if kind is None:
        _count(state, "skipped_other_type")
        return None
    nanos = _nanos(point.get("startTimeNanos"))
    start = _datetime(nanos)
    if start is None or nanos is None:
        _count(state, "skipped_no_date")
        return None
    end = _datetime(_nanos(point.get("endTimeNanos")))
    origin = point.get("originDataSourceId")
    device, source_name = _provenance(origin if isinstance(origin, str) and origin else stream.source)
    value = _value(point)
    raw_id = f"{kind}:{nanos}:{device or NO_DEVICE}"
    if kind == "sleep":
        stage = STAGES.get(int(value)) if value is not None and value == int(value) else None
        if stage is None:
            _count(state, "skipped_unknown_stage")
            return None
        if end is None or end < start:
            _count(state, "skipped_bad_span")
            return None
        seconds = max(0, round((end - start).total_seconds()))
        return _Draft(kind, start, end, seconds, raw_id, device, source_name, stage)
    if value is None:
        _count(state, "skipped_no_value")
        return None
    return _Draft(kind, start, None, hx.rounded(value), raw_id, device, source_name)


def _provenance(source: str | None) -> tuple[str | None, str | None]:
    """(device, source_name) from a data source id, `raw:<type>:<package>:<manufacturer>:<model>:
    <uid>:<stream>`: the manufacturer and model as the device, the package as the source's name; a
    derived or merged source (`derived:<type>:<package>:<stream>`) names no device."""
    if not source:
        return None, None
    parts = source.split(":")
    source_name = parts[2].strip() if len(parts) > 2 and parts[2].strip() else None
    device = None
    if len(parts) >= 6:
        device = " ".join(part.strip() for part in parts[3:5] if part.strip()) or None
    return device, source_name


def _value(point: dict[str, Any]) -> int | float | None:
    """The point's first value: `fitValue[0].value.{intVal,fpVal}` (Takeout), or `value[0]` (the
    API's shape); None when there is none."""
    values = point.get("fitValue")
    if not isinstance(values, list):
        values = point.get("value")
    if not isinstance(values, list) or not values or not isinstance(values[0], dict):
        return None
    first = values[0]
    inner = first.get("value")
    holder: dict[str, Any] = inner if isinstance(inner, dict) else first
    for key in ("intVal", "fpVal"):
        number = _number(holder.get(key))
        if number is not None:
            return number
    return None


# -- buckets, the cap and the line ----------------------------------------------------------------


def _emit(draft: _Draft, state: _State) -> Iterator[dict[str, Any]]:
    """Bucket, cap, or pass the draft through as one line."""
    if draft.type in BUCKETED:
        key = (draft.type, draft.device or NO_DEVICE)
        start = _bucket_start(draft.start)
        bucket = state.buckets.get(key)
        if bucket is not None and bucket.start != start:
            yield from _close(key, state)
            bucket = None
        if bucket is None:
            bucket = state.buckets[key] = _Bucket(start, device=draft.device, source_name=draft.source_name)
        bucket.total += draft.value
        bucket.samples += 1
        return
    if draft.type in CAPPED:
        key = (draft.type, draft.device or NO_DEVICE)
        minute = draft.start.replace(second=0, microsecond=0)
        if state.last_reading.get(key) == minute:
            _count(state, "skipped_over_cap")
            return
        state.last_reading[key] = minute
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": draft.raw_id,
        "type": draft.type,
        "value": draft.value,
        "unit": UNITS[draft.type],
    }
    if draft.stage is not None:
        payload["stage"] = draft.stage
    yield from _line(payload, draft.start, draft.end, draft.device, draft.source_name, draft.extra, state)


def _flush(state: _State, current: datetime | None) -> Iterator[dict[str, Any]]:
    """Close every bucket the point now being read (at `current`) can no longer fall in, so lines
    come out in start order; at the end of a file (`None`), every bucket."""
    for key in list(state.buckets):
        bucket = state.buckets[key]
        if current is None or current >= bucket.start + BUCKET:
            yield from _close(key, state)


def _close(key: tuple[str, str], state: _State) -> Iterator[dict[str, Any]]:
    bucket = state.buckets.pop(key)
    kind, device_key = key
    at = bucket.start
    state.covered.add((kind, _local_day(at, state)))
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": f"{kind}:{hx.stamp(at)}:{device_key}",
        "type": kind,
        "value": hx.rounded(bucket.total),
        "unit": UNITS[kind],
    }
    extra = {"samples": bucket.samples}
    yield from _line(payload, at, at + BUCKET, bucket.device, bucket.source_name, extra, state)


def _line(
    payload: dict[str, Any],
    start: datetime,
    end: datetime | None,
    device: str | None,
    source_name: str | None,
    extra: dict[str, Any],
    state: _State,
) -> Iterator[dict[str, Any]]:
    if device:
        payload["device"] = device
    if source_name:
        payload["source_name"] = source_name
    if extra:
        payload["extra"] = extra
    at = hx.stamp(start)
    if state.since and at < state.since:
        return
    yield {
        "at": at,
        "end": hx.stamp(end) if end is not None else None,
        "tz": state.tz,
        "source": SOURCE,
        "kind": KIND,
        "tier": state.tier,
        "payload": payload,
    }


def _bucket_start(when: datetime) -> datetime:
    return when.replace(minute=when.minute - when.minute % 15, second=0, microsecond=0)


def _local_day(when: datetime, state: _State) -> str:
    return when.astimezone(state.local).date().isoformat()


# -- the daily CSVs ----------------------------------------------------------------------------------


def _read_windows(path: Path, state: _State) -> Iterator[dict[str, Any]]:
    """A day's quarter-hour file: each window's step count and distance into the buckets."""
    read = hx.rows(path)
    if read is None:
        _count(state, "skipped_unreadable_csv")
        return
    header, rows = read
    columns = {kind: _column(header, *words) for kind, words in METRICS.items()}
    start_column = _column(header, START_COLUMN)
    date_column = _column(header, DATE_COLUMN)
    file_day = _day(path.stem)
    for row in rows:
        day = _day(row.get(date_column, "")) if date_column else file_day
        start = _window_start(row.get(start_column, "") if start_column else "", day, state.local)
        if start is None:
            _count(state, "skipped_bad_start")
            continue
        found = False
        for kind, column in columns.items():
            value = hx.number(row.get(column, "")) if column else None
            if value is None:
                continue
            found = True
            yield from _emit(_Draft(kind, start, None, value, ""), state)
        if not found:
            _count(state, "skipped_no_value")
        yield from _flush(state, start)
    yield from _flush(state, None)


def _window_start(text: str, day: date | None, local: tzinfo) -> datetime | None:
    """A window's start: a full stamp as it says, or a clock (`06:15:00.000+02:00`) on `day`."""
    text = text.strip()
    if not text:
        return None
    when = hx.when(text, local)
    if when is not None:
        return when
    if day is None:
        return None
    return hx.when(f"{day.isoformat()}T{text}", local)


def _read_days(path: Path, state: _State) -> Iterator[dict[str, Any]]:
    """One row per day: a `steps` and a `distance` span over the local day for the days no bucket
    touched, the day's other figures under `extra` of the steps line."""
    read = hx.rows(path)
    if read is None:
        _count(state, "skipped_unreadable_csv")
        return
    header, rows = read
    date_column = _column(header, DATE_COLUMN)
    if date_column is None:
        _count(state, "skipped_unreadable_csv")
        return
    columns = {kind: _column(header, *words) for kind, words in METRICS.items()}
    figures = {key: _column(header, *words) for key, words in FIGURES.items()}
    for row in rows:
        day = _day(row.get(date_column, ""))
        if day is None:
            _count(state, "skipped_bad_date")
            continue
        values = {
            kind: value
            for kind, column in columns.items()
            if column and (value := hx.number(row.get(column, ""))) is not None
        }
        if not values:
            _count(state, "skipped_no_value")
            continue
        wanted = {k: v for k, v in values.items() if (k, day.isoformat()) not in state.covered}
        if not wanted:
            _count(state, "skipped_covered_by_stream")
            continue
        start = datetime.combine(day, time(), tzinfo=state.local).astimezone(UTC)
        end = datetime.combine(day + timedelta(days=1), time(), tzinfo=state.local).astimezone(UTC)
        carrier = "steps" if "steps" in wanted else next(iter(wanted))
        for kind, value in wanted.items():
            extra: dict[str, Any] = {"period": DAY, "day": day.isoformat()}
            if kind == carrier:
                for key, column in figures.items():
                    figure = hx.number(row.get(column, "")) if column else None
                    if figure is not None:
                        extra[key] = figure
            payload: dict[str, Any] = {
                "schema": SCHEMA,
                "raw_id": f"{kind}:{DAY}:{day.isoformat()}",
                "type": kind,
                "value": hx.rounded(value),
                "unit": UNITS[kind],
            }
            yield from _line(payload, start, end, None, None, extra, state)


def _day(text: str) -> date | None:
    try:
        return date.fromisoformat(text.strip()[:10]) if text.strip() else None
    except ValueError:
        return None


# -- the sessions ------------------------------------------------------------------------------------


def _read_session(path: Path, state: _State) -> Iterator[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _count(state, "skipped_unreadable_json")
        return
    if not isinstance(data, dict):
        _count(state, "skipped_unreadable_json")
        return
    start = hx.when(_text(data.get("startTime")), state.local)
    if start is None:
        _count(state, "skipped_no_start")
        return
    end = hx.when(_text(data.get("endTime")), state.local)
    if end is None or end < start:
        _count(state, "skipped_bad_span")
        return
    activity = _text(data.get("fitnessActivity")) or _text(data.get("activity")) or "unknown"
    span = max(0, round((end - start).total_seconds()))
    application = data.get("application")
    source_name = _text(application.get("packageName")) if isinstance(application, dict) else ""
    if activity.lower() == SLEEP_ACTIVITY:
        payload: dict[str, Any] = {
            "schema": SCHEMA,
            "raw_id": f"sleep:session:{hx.stamp(start)}",
            "type": "sleep",
            "value": span,
            "unit": UNITS["sleep"],
            "stage": "in_bed",
        }
        yield from _line(payload, start, end, None, source_name or None, {}, state)
        return
    duration = _duration(data.get("duration"))
    session_id = _text(data.get("id"))
    extra: dict[str, Any] = {"activity": _activity(activity), "activity_type": activity}
    for item in data.get("aggregate") or []:
        if not isinstance(item, dict):
            continue
        key = AGGREGATES.get(_text(item.get("metricName")))
        number = _number(item.get("intValue"))
        if number is None:
            number = _number(item.get("floatValue"))
        if key and number is not None:
            extra[key] = hx.rounded(number)
    name = _text(data.get("name"))
    if name:
        extra["name"] = name
    payload = {
        "schema": SCHEMA,
        "raw_id": f"workout:{session_id}" if session_id else f"workout:{hx.stamp(start)}:{activity}",
        "type": "workout",
        "value": hx.rounded(duration) if duration is not None and duration >= 0 else span,
        "unit": UNITS["workout"],
    }
    yield from _line(payload, start, end, None, source_name or None, extra, state)


def _activity(name: str) -> str:
    """Fit's activity in the vocabulary apple-health uses, by the full name, then its first part
    (`running.treadmill` → `running`), else Fit's own with its dots as underscores."""
    lowered = name.strip().lower()
    if lowered in ACTIVITIES:
        return ACTIVITIES[lowered]
    head = lowered.split(".")[0]
    return ACTIVITIES.get(head, head if head and head != lowered else lowered.replace(".", "_"))


def _duration(value: object) -> float | None:
    """A session's duration in seconds: a number, or the export's `1953.0s`."""
    number = _number(value)
    if number is not None:
        return float(number)
    text = _text(value).lower().removesuffix("s").strip()
    try:
        return float(text) if text else None
    except ValueError:
        return None


# -- values ----------------------------------------------------------------------------------------


def _text(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _number(value: object) -> int | float | None:
    """The value when it is a finite number (a bool is not one), else None."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def _nanos(value: object) -> int | None:
    """Nanoseconds since 1970 as the export spells them: a number, or digits in a string."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if _number(value) is not None else None
    if isinstance(value, str):
        text = value.strip()
        if text.lstrip("-").isdigit():
            return int(text)
    return None


def _datetime(nanos: int | None) -> datetime | None:
    """The instant, UTC; None for no nanos or an instant at or before the epoch (a placeholder).
    Arithmetic from the epoch, not `fromtimestamp`: Windows refuses instants before 1970."""
    if nanos is None or nanos <= 0:
        return None
    try:
        return EPOCH + timedelta(seconds=nanos // 10**9, microseconds=(nanos % 10**9) // 1000)
    except OverflowError:
        return None
