"""Apple Health's healthdb_secure.sqlite → health-sample/v1 (RFC 0014).

Reads the store an iPhone keeps under Health/ — only an encrypted backup carries it
(`logbook import-backup` copies it out as `health/healthdb_secure.sqlite`, with `healthdb.sqlite`
beside it, and runs this adapter on the copy). The tables that matter:

    samples            (data_id, start_date, end_date — seconds since 2001-01-01 UTC — data_type)
    quantity_samples   (data_id, quantity, original_quantity, original_unit)
    category_samples   (data_id, value)
    workouts           (data_id, activity_type, duration, total_energy_burned, total_distance, …)
    objects            (data_id, provenance)              → data_provenances (ROWID, origin_product_type,
                                                            tz_name, source_id)
    unit_strings       (ROWID, unit_string)               the unit `original_unit` names

`sources` (ROWID, name) lives in `healthdb.sqlite` beside the store on a phone; when that file is
there it names each sample's source (`Apple Watch`, a third-party app), else there is no name.
Every table but `samples` and `quantity_samples` is optional: PRAGMA says what the store has, and a
store without one yields lines without what it would have given.

Data types this version maps (`data_type`): 3 body mass → `weight` (kg); 5 heart rate → `heart_rate`
(bpm); 7 step count → `steps`; 8 walking+running distance → `distance` (m); 9 basal energy →
`basal_energy` (kcal); 10 active energy → `active_energy` (kcal); 12 flights climbed →
`flights_climbed`; 63 sleep analysis → `sleep` with `stage` (0 in_bed, 1 asleep, 2 awake, 3 core,
4 deep, 5 rem); 118 resting heart rate → `resting_hr` (bpm); 183 heart-rate variability SDNN → `hrv`
(ms). A row in `workouts` is a `workout` whatever its data_type. Any other type is skipped and counted
(RFC 0014 rule 8), never mapped to a near type.

The store keeps a quantity in one unit per data type, checked against a real store (RFC 0014
rule 6, the RFC's "Units as the store keeps them"): a count as a count, a length in metres, an
energy in kilocalories, a mass in kilograms, a time in seconds; a heart rate (type 5) in count per
second, but a resting heart rate (type 118) in count per minute and HRV SDNN (type 183) in
milliseconds already. The profile's units are those, with one conversion: a heart rate is
multiplied by 60 (count/s → bpm). Nothing else is rescaled; a factor of 60 on resting heart rate once made a
resting rate of 62 read as 3,720. When the row keeps the quantity as it was entered
(`original_quantity`, `original_unit`) that goes under `extra.original` so the conversion can be
checked against a real store.

Steps, distance, energy and flights are summed into 15-minute buckets aligned to the UTC hour, one
bucket per device (rule 2): `at` the bucket's start, `end` its end, `extra.samples` the count,
`raw_id` `<type>:<bucket start>:<device>`. Heart rate keeps its native resolution but at most one
reading per UTC minute per device: the first is the line, the rest are skipped and counted (rule 3).
A sleep stage is one line per segment, `value` its length in seconds (rule 4). A workout is a span
with its duration as `value` and its activity, energy and distance under `extra`. Every line is tier 3
(SPEC §4); `logbook add --tier` overrides.

`device` is the provenance's `origin_product_type` (`Watch7,1`, `iPhone14,2`); `tz` the provenance's
`tz_name` when it looks like a zone name, else None so the record's applies. `raw_id` is
`<type>:<data_id>` for every line that is one row. Rows dated before 1900 are placeholders and are
skipped and counted, as are rows without a date, without a value, and spans that end before they
start. Pure: opened `mode=ro`, `immutable=1`, one SELECT streamed through the cursor in start order,
no network.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

NAME = "apple-health"
KIND = "health"
TIER = 3  # SPEC §4: health is tier 3; `logbook add --tier` overrides
SCHEMA = "health-sample/v1"

SQLITE_HEADER = b"SQLite format 3\x00"
COMPANION = "healthdb.sqlite"  # beside the store on the phone; names the sources
APPLE_EPOCH_UTC = datetime(2001, 1, 1, tzinfo=UTC)
PLACEHOLDER_BEFORE_YEAR = 1900
BUCKET = timedelta(minutes=15)
CAP = timedelta(minutes=1)  # heart rate: one reading per device per minute
NO_DEVICE = "-"  # the device slot of a bucket's raw_id when the store names none

TYPES = {  # samples.data_type → profile type
    3: "weight",
    5: "heart_rate",
    7: "steps",
    8: "distance",
    9: "basal_energy",
    10: "active_energy",
    12: "flights_climbed",
    63: "sleep",
    118: "resting_hr",
    183: "hrv",
}
UNITS = {  # profile type → unit (RFC 0014)
    "steps": "count",
    "distance": "m",
    "active_energy": "kcal",
    "basal_energy": "kcal",
    "flights_climbed": "count",
    "heart_rate": "bpm",
    "resting_hr": "bpm",
    "hrv": "ms",
    "weight": "kg",
    "sleep": "s",
    "workout": "s",
}
SCALE = {"heart_rate": 60}  # the store's unit → the profile's; every other type is kept as stored
BUCKETED = frozenset({"steps", "distance", "active_energy", "basal_energy", "flights_climbed"})
CAPPED = frozenset({"heart_rate"})
STAGES = {0: "in_bed", 1: "asleep", 2: "awake", 3: "core", 4: "deep", 5: "rem"}
ACTIVITIES = {  # HKWorkoutActivityType, the common ones; an unnamed code keeps only `activity_type`
    1: "american_football", 2: "archery", 3: "australian_football", 4: "badminton", 5: "baseball",
    6: "basketball", 7: "bowling", 8: "boxing", 9: "climbing", 10: "cricket", 11: "cross_training",
    12: "curling", 13: "cycling", 14: "dance", 16: "elliptical", 17: "equestrian", 18: "fencing",
    19: "fishing", 20: "functional_strength_training", 21: "golf", 22: "gymnastics", 23: "handball",
    24: "hiking", 25: "hockey", 26: "hunting", 27: "lacrosse", 28: "martial_arts", 29: "mind_and_body",
    31: "paddle_sports", 32: "play", 33: "preparation_and_recovery", 34: "racquetball", 35: "rowing",
    36: "rugby", 37: "running", 38: "sailing", 39: "skating_sports", 40: "snow_sports", 41: "soccer",
    42: "softball", 43: "squash", 44: "stair_climbing", 45: "surfing", 46: "swimming", 47: "table_tennis",
    48: "tennis", 49: "track_and_field", 50: "traditional_strength_training", 51: "volleyball",
    52: "walking", 53: "water_fitness", 54: "water_polo", 55: "water_sports", 56: "wrestling", 57: "yoga",
    58: "barre", 59: "core_training", 60: "cross_country_skiing", 61: "downhill_skiing", 62: "flexibility",
    63: "hiit", 64: "jump_rope", 65: "kickboxing", 66: "pilates", 67: "snowboarding", 68: "stairs",
    69: "step_training", 70: "wheelchair_walk_pace", 71: "wheelchair_run_pace", 72: "tai_chi",
    73: "mixed_cardio", 74: "hand_cycling", 75: "disc_sports", 76: "fitness_gaming", 77: "cardio_dance",
    78: "social_dance", 79: "pickleball", 80: "cooldown", 82: "swim_bike_run", 83: "transition",
    84: "underwater_diving", 3000: "other",
}  # fmt: skip

REQUIRED_TABLES = ("samples", "quantity_samples")
WORKOUT_COLUMNS = ("activity_type", "duration", "total_energy_burned", "total_distance")


def sniff(path: Path) -> bool:
    """A SQLite file with `samples` and `quantity_samples` tables. Never raises."""
    path = Path(path)
    try:
        if not path.is_file():
            return False
        with path.open("rb") as fh:
            if fh.read(len(SQLITE_HEADER)) != SQLITE_HEADER:
                return False
        con = _open(path)
    except (OSError, ValueError, sqlite3.Error):
        return False
    try:
        return all(t in _tables(con) for t in REQUIRED_TABLES)
    except sqlite3.Error:
        return False
    finally:
        con.close()


def _open(path: Path) -> sqlite3.Connection:
    """Read-only and immutable: SQLite neither locks the file nor writes a journal beside it."""
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)


def _tables(con: sqlite3.Connection) -> set[str]:
    rows = con.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(name) for (name,) in rows}


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}


@dataclass
class _Bucket:
    """One open 15-minute bucket of one type from one device."""

    start: datetime
    total: float = 0.0
    samples: int = 0
    device: str | None = None
    source_name: str | None = None
    tz: str | None = None


@dataclass
class _State:
    counts: dict[str, int]
    since: str | None
    tier: int
    buckets: dict[tuple[str, str], _Bucket] = field(default_factory=dict)
    last_reading: dict[tuple[str, str], datetime] = field(default_factory=dict)  # (type, device) → minute


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    tier: int | None = None,
) -> Iterator[dict[str, Any]]:
    """One health-sample/v1 line per reading, stage or workout, and one per 15-minute bucket of the
    counted types, streamed in start order.

    `since` is RFC3339 UTC; lines with `at` before it are not yielded. `counts` tallies
    `skipped_no_date`, `skipped_placeholder_date`, `skipped_no_value`, `skipped_bad_span`,
    `skipped_other_type`, `skipped_unknown_stage` and `skipped_over_cap` (RFC 0014 rules 3, 7, 8).
    `tier` overrides the default 3 (`logbook add --tier`)."""
    path = Path(path)
    state = _State(counts if counts is not None else {}, since, tier or TIER)
    con = _open(path)
    try:
        query, names = _query(con)
        source_names = _source_names(con, path)
        for row in con.execute(query):
            values = dict(zip(names, row, strict=True))
            draft = _draft(values, source_names, state)
            if draft is not None:
                yield from _emit(draft, state)
            yield from _flush(state, values.get("start_date"))
        yield from _flush(state, None)
    finally:
        con.close()


def _query(con: sqlite3.Connection) -> tuple[str, list[str]]:
    """One SELECT over `samples` and whatever optional tables the store has, in start order."""
    tables = _tables(con)
    select = ["s.data_id", "s.start_date", "s.end_date", "s.data_type"]
    names = ["data_id", "start_date", "end_date", "data_type"]
    joins: list[str] = []
    quantity = _columns(con, "quantity_samples")
    select.append("q.quantity")
    names.append("quantity")
    for column in ("original_quantity", "original_unit"):
        if column in quantity:
            select.append(f"q.{column}")
            names.append(column)
    joins.append("LEFT JOIN quantity_samples q ON q.data_id = s.data_id")
    if "category_samples" in tables:
        select.append("c.value")
        names.append("value")
        joins.append("LEFT JOIN category_samples c ON c.data_id = s.data_id")
    if "workouts" in tables:
        workout = _columns(con, "workouts")
        select.append("w.data_id")
        names.append("workout_id")
        for column in WORKOUT_COLUMNS:
            if column in workout:
                select.append(f"w.{column}")
                names.append(column)
        joins.append("LEFT JOIN workouts w ON w.data_id = s.data_id")
    if "objects" in tables and "data_provenances" in tables:
        provenance = _columns(con, "data_provenances")
        for column in ("origin_product_type", "tz_name", "source_id"):
            if column in provenance:
                select.append(f"p.{column}")
                names.append(column)
        joins.append("LEFT JOIN objects o ON o.data_id = s.data_id")
        joins.append("LEFT JOIN data_provenances p ON p.ROWID = o.provenance")
    if "unit_strings" in tables and "original_unit" in names:
        select.append("u.unit_string")
        names.append("unit_string")
        joins.append("LEFT JOIN unit_strings u ON u.ROWID = q.original_unit")
    sql = f"SELECT {', '.join(select)} FROM samples s {' '.join(joins)} ORDER BY s.start_date, s.data_id"
    return sql, names


def _source_names(con: sqlite3.Connection, path: Path) -> dict[int, str]:
    """`sources.ROWID → name` from the store itself when it has the table, else from the
    healthdb.sqlite beside it, else nothing."""
    if "sources" in _tables(con):
        return _read_sources(con)
    companion = path.parent / COMPANION
    if not companion.is_file():
        return {}
    try:
        other = _open(companion)
    except (OSError, ValueError, sqlite3.Error):
        return {}
    try:
        return _read_sources(other) if "sources" in _tables(other) else {}
    except sqlite3.Error:
        return {}
    finally:
        other.close()


def _read_sources(con: sqlite3.Connection) -> dict[int, str]:
    if "name" not in _columns(con, "sources"):
        return {}
    found: dict[int, str] = {}
    for rowid, name in con.execute("SELECT ROWID, name FROM sources"):
        if isinstance(rowid, int) and isinstance(name, str) and name.strip():
            found[rowid] = name.strip()
    return found


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


@dataclass
class _Draft:
    """One mapped row before bucketing and capping."""

    type: str
    start: datetime
    end: datetime | None
    value: float
    data_id: int
    device: str | None
    source_name: str | None
    tz: str | None
    stage: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _draft(values: dict[str, Any], source_names: dict[int, str], state: _State) -> _Draft | None:
    counts = state.counts
    start = _datetime(values.get("start_date"))
    if start is None:
        _count(
            counts,
            "skipped_placeholder_date"
            if _number(values.get("start_date")) is not None
            else "skipped_no_date",
        )
        return None
    if start.year < PLACEHOLDER_BEFORE_YEAR:
        _count(counts, "skipped_placeholder_date")
        return None
    end = _datetime(values.get("end_date"))
    device = _text(values.get("origin_product_type")) or None
    tz = _zone(values.get("tz_name"))
    source_id = values.get("source_id")
    source_name = source_names.get(source_id) if isinstance(source_id, int) else None
    data_id = int(values["data_id"])

    def made(kind: str, end: datetime | None, value: float, stage: str | None = None) -> _Draft:
        return _Draft(kind, start, end, value, data_id, device, source_name, tz, stage=stage)

    if values.get("workout_id") is not None:
        return _workout(values, start, end, made, counts)
    kind = TYPES.get(values.get("data_type"))  # type: ignore[arg-type]
    if kind is None:
        _count(counts, "skipped_other_type")
        return None
    if kind == "sleep":
        stage = STAGES.get(values.get("value"))  # type: ignore[arg-type]
        if stage is None:
            _count(counts, "skipped_unknown_stage")
            return None
        if end is None or end < start:
            _count(counts, "skipped_bad_span")
            return None
        return made(kind, end, _seconds(end - start), stage=stage)
    quantity = _number(values.get("quantity"))
    if quantity is None:
        _count(counts, "skipped_no_value")
        return None
    draft = made(kind, None, _round(quantity * SCALE.get(kind, 1)))
    original = _number(values.get("original_quantity"))
    unit = _text(values.get("unit_string"))
    if original is not None and unit:
        draft.extra["original"] = {"quantity": _round(original), "unit": unit}
    return draft


def _workout(
    values: dict[str, Any],
    start: datetime,
    end: datetime | None,
    made: Callable[..., _Draft],
    counts: dict[str, int],
) -> _Draft | None:
    if end is None or end < start:
        _count(counts, "skipped_bad_span")
        return None
    duration = _number(values.get("duration"))
    value = _round(duration) if duration is not None and duration >= 0 else _seconds(end - start)
    draft = made("workout", end, value)
    extra = draft.extra
    code = _number(values.get("activity_type"))
    if code is not None:
        extra["activity_type"] = int(code)
        if int(code) in ACTIVITIES:
            extra["activity"] = ACTIVITIES[int(code)]
    energy = _number(values.get("total_energy_burned"))
    if energy is not None:
        extra["energy_kcal"] = _round(energy)
    distance = _number(values.get("total_distance"))
    if distance is not None:
        extra["distance_m"] = _round(distance)
    return draft


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
            bucket = state.buckets[key] = _Bucket(
                start, device=draft.device, source_name=draft.source_name, tz=draft.tz
            )
        bucket.total += draft.value
        bucket.samples += 1
        return
    if draft.type in CAPPED:
        key = (draft.type, draft.device or NO_DEVICE)
        minute = draft.start.replace(second=0, microsecond=0)
        if state.last_reading.get(key) == minute:
            _count(state.counts, "skipped_over_cap")
            return
        state.last_reading[key] = minute
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": f"{draft.type}:{draft.data_id}",
        "type": draft.type,
        "value": draft.value,
        "unit": UNITS[draft.type],
    }
    if draft.stage is not None:
        payload["stage"] = draft.stage
    yield from _line(
        payload, draft.start, draft.end, draft.device, draft.source_name, draft.tz, draft.extra, state
    )


def _flush(state: _State, current_start: object) -> Iterator[dict[str, Any]]:
    """Close every bucket that the row now being read (at `current_start`) can no longer fall in, so
    lines come out in start order; at the end (`None`), every bucket."""
    now = _datetime(current_start)
    for key in list(state.buckets):
        bucket = state.buckets[key]
        if now is None or now >= bucket.start + BUCKET:
            yield from _close(key, state)


def _close(key: tuple[str, str], state: _State) -> Iterator[dict[str, Any]]:
    bucket = state.buckets.pop(key)
    kind, device_key = key
    at = bucket.start
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": f"{kind}:{_stamp(at)}:{device_key}",
        "type": kind,
        "value": _round(bucket.total),
        "unit": UNITS[kind],
    }
    extra = {"samples": bucket.samples}
    yield from _line(payload, at, at + BUCKET, bucket.device, bucket.source_name, bucket.tz, extra, state)


def _line(
    payload: dict[str, Any],
    start: datetime,
    end: datetime | None,
    device: str | None,
    source_name: str | None,
    tz: str | None,
    extra: dict[str, Any],
    state: _State,
) -> Iterator[dict[str, Any]]:
    if device:
        payload["device"] = device
    if source_name:
        payload["source_name"] = source_name
    if extra:
        payload["extra"] = extra
    at = _stamp(start)
    if state.since and at < state.since:
        return
    yield {
        "at": at,
        "end": _stamp(end) if end is not None else None,
        "tz": tz,
        "source": NAME,
        "kind": KIND,
        "tier": state.tier,
        "payload": payload,
    }


def _bucket_start(when: datetime) -> datetime:
    minute = when.minute - when.minute % 15
    return when.replace(minute=minute, second=0, microsecond=0)


def _zone(value: object) -> str | None:
    """A provenance `tz_name` that looks like an IANA name (`Europe/Oslo`, `UTC`), else None."""
    name = _text(value)
    if not name or " " in name:
        return None
    return name if "/" in name or name in ("UTC", "Etc/UTC") else None


def _text(value: object) -> str:
    if isinstance(value, bytes | bytearray | memoryview):
        try:
            return bytes(value).decode("utf-8").strip()
        except UnicodeDecodeError:
            return ""
    return value.strip() if isinstance(value, str) else ""


def _number(value: object) -> int | float | None:
    """The value when it is a finite number (a bool is not one), else None."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def _round(value: int | float) -> int | float:
    """Whole numbers as ints (`250`, not `250.0`; canonical JSON prints them the same, readers do
    not), else rounded to three decimals: the store's own precision is no better."""
    rounded = round(float(value), 3)
    return int(rounded) if rounded == int(rounded) else rounded


def _seconds(span: timedelta) -> int:
    return max(0, round(span.total_seconds()))


def _datetime(seconds_since_2001: object) -> datetime | None:
    """Arithmetic from the epoch, not `fromtimestamp`: Windows refuses instants before 1970."""
    number = _number(seconds_since_2001)
    if number is None:
        return None
    try:
        return APPLE_EPOCH_UTC + timedelta(seconds=int(number))
    except (OverflowError, ValueError):
        return None


def _stamp(when: datetime) -> str:
    return when.astimezone(UTC).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"
