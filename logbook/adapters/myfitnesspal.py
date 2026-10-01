"""MyFitnessPal's maindb.sqlite → health-sample/v1 (RFC 0014).

Reads the store the app keeps at `Documents/maindb.sqlite` (`AppDomain-com.myfitnesspal.mfp`; `logbook
import-backup` copies it out as `myfitnesspal/`). The app syncs most of its history to its servers and
keeps little on the phone, so a backup holds the recent entries. The tables that matter:

    food_entries        (uid, entry_date `YYYY-MM-DD`, entry_time `HH:MM:SS` or NULL, meal_id, food_id,
                         quantity, weight_index)
    foods               (id, description, brand)
    food_portions       (food_id, weight_index, amount, description, nutritional_multiplier)
    nutritional_values  (food_id, nutrient_id — 0 is energy in kcal —, value: per the base portion)
    measurements        (uid, measurement_type_id → measurement_types.description, value, entry_date)
    exercise_entries    (uid, entry_date, exercise_id → exercises.description, calories, duration_in_seconds)
    steps_entries       (daily totals)
    user_properties     (property_name, property_value: `meal_names`, `timezone_identifier`,
                         `body_weight_unit_preference`)

A logged food is an `energy_intake` line: `value` = the food's energy per base portion x the chosen
portion's multiplier x the quantity, in kcal, rounded to a tenth; the meal's name (from `meal_names`),
the food's description and brand, the quantity and the portion go under `extra` (rule 10). A
`Weight` measurement is a `weight` line, converted to kg when the owner's unit preference is pounds
(the entered value kept under `extra.original`); the other body measurements (neck, waist, hips) are
not in the profile and are counted. An exercise entry is a `workout` whose `value` is its duration,
with the exercise's name and the calories under `extra`; one without a duration is counted
(`skipped_bad_span`). A daily step total is derived data, not a sample (rule 2), and is counted
(`skipped_daily_total`).

Clocks: `entry_date` plus `entry_time` are local in the store's `timezone_identifier` (else the
record's zone, else UTC) and are converted to UTC. A food entry without a clock, a weight and an
exercise entry (the app keeps their day only) are spans over that local day — `at` midnight, `end` the
next — with `extra.all_day` true; nothing is invented about the hour. `raw_id` is `<type>:<uid>`;
`source_name` is `MyFitnessPal`. Every line is tier 3 (SPEC §4; `logbook add --tier` overrides). Pure:
opened `mode=ro`, `immutable=1`; no network.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

NAME = "myfitnesspal"
KIND = "health"
TIER = 3
SCHEMA = "health-sample/v1"
SOURCE_NAME = "MyFitnessPal"

SQLITE_HEADER = b"SQLite format 3\x00"
REQUIRED_TABLES = ("food_entries", "foods", "food_portions", "nutritional_values")
ENERGY = 0  # nutrient_id of energy, kcal
WEIGHT_TYPE = "weight"  # measurement_types.description, compared lower-case
LB_TO_KG = 0.45359237
POUNDS = ("lb", "lbs", "pound", "pounds")


def sniff(path: Path) -> bool:
    """A SQLite file with the food diary tables. Never raises."""
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


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
    tier: int | None = None,
) -> Iterator[dict[str, Any]]:
    """One health-sample/v1 line per food entry with energy, weight and exercise entry, in `at` order.

    `since` is RFC3339 UTC; lines with `at` before it are not yielded. `counts` tallies
    `skipped_no_value`, `skipped_other_type`, `skipped_bad_span`, `skipped_daily_total` and
    `skipped_no_date`. `timezone` is the record's zone, the clock's zone when the store names none;
    `tier` overrides 3."""
    path = Path(path)
    counts = counts if counts is not None else {}
    con = _open(path)
    try:
        tables = _tables(con)
        properties = _properties(con, tables)
        zone_name = _zone_name(properties.get("timezone_identifier")) or timezone
        zone = _zone(zone_name)
        meals = _meal_names(properties.get("meal_names"))
        weight_unit = (properties.get("body_weight_unit_preference") or "").strip().lower()
        lines: list[dict[str, Any]] = []
        lines.extend(_foods(con, tables, meals, zone, zone_name, counts, tier or TIER))
        lines.extend(_weights(con, tables, weight_unit, zone, zone_name, counts, tier or TIER))
        lines.extend(_workouts(con, tables, zone, zone_name, counts, tier or TIER))
        if "steps_entries" in tables:
            (daily,) = con.execute("SELECT count(*) FROM steps_entries").fetchone()
            if daily:
                counts["skipped_daily_total"] = counts.get("skipped_daily_total", 0) + int(daily)
    finally:
        con.close()
    lines.sort(key=lambda line: (line["at"], line["payload"]["raw_id"]))
    for line in lines:
        if since and line["at"] < since:
            continue
        yield line


def _properties(con: sqlite3.Connection, tables: set[str]) -> dict[str, str]:
    if "user_properties" not in tables or not {"property_name", "property_value"} <= _columns(
        con, "user_properties"
    ):
        return {}
    found: dict[str, str] = {}
    for name, value in con.execute("SELECT property_name, property_value FROM user_properties"):
        if isinstance(name, str) and isinstance(value, str) and name not in found:
            found[name] = value
    return found


def _zone_name(value: object) -> str | None:
    name = _text(value)
    if not name or " " in name:
        return None
    return name if "/" in name or name in ("UTC", "Etc/UTC") else None


def _zone(name: str | None) -> ZoneInfo:
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return ZoneInfo("UTC")


def _meal_names(value: object) -> list[str]:
    """The owner's meal names, kept by the app as a comma-separated list of JSON strings."""
    text = _text(value)
    if not text:
        return []
    try:
        parsed = json.loads(f"[{text}]")
    except ValueError:
        return [part.strip().strip('"') for part in text.split(",") if part.strip()]
    return [str(item) for item in parsed if isinstance(item, str)]


def _foods(
    con: sqlite3.Connection,
    tables: set[str],
    meals: list[str],
    zone: ZoneInfo,
    zone_name: str | None,
    counts: dict[str, int],
    tier: int,
) -> Iterator[dict[str, Any]]:
    entries = _columns(con, "food_entries")
    select = ["e.id", "e.uid", "e.entry_date", "e.entry_time", "e.meal_id", "e.quantity", "e.weight_index"]
    select += ["f.description", "f.brand", "p.amount", "p.description", "p.nutritional_multiplier", "n.value"]
    select = [c if c.split(".")[1] in entries or not c.startswith("e.") else "NULL" for c in select]
    sql = (
        f"SELECT {', '.join(select)} FROM food_entries e"
        " LEFT JOIN foods f ON f.id = e.food_id"
        " LEFT JOIN food_portions p ON p.food_id = e.food_id AND p.weight_index = e.weight_index"
        " LEFT JOIN nutritional_values n ON n.food_id = e.food_id AND n.nutrient_id = ?"
        " ORDER BY e.entry_date, e.entry_time, e.id"
    )
    for row in con.execute(sql, (ENERGY,)):
        pk, uid, day, clock, meal_id, quantity, _index, food, brand, amount, portion, multiplier, energy = row
        per_portion, factor, count = _number(energy), _number(multiplier), _number(quantity)
        if per_portion is None or factor is None or count is None:
            _count(counts, "skipped_no_value")
            continue
        start, end, all_day = _when(day, clock, zone)
        if start is None:
            _count(counts, "skipped_no_date")
            continue
        extra: dict[str, Any] = {}
        if isinstance(meal_id, int) and 1 <= meal_id <= len(meals):
            extra["meal"] = meals[meal_id - 1]
        if _text(food):
            extra["food"] = _text(food)
        if _text(brand):
            extra["brand"] = _text(brand)
        extra["quantity"] = _round(count)
        size = _number(amount)
        if size is not None and _text(portion):
            extra["portion"] = f"{_round(size)} {_text(portion)}"
        if all_day:
            extra["all_day"] = True
        yield _line(
            "energy_intake", "kcal", _round_tenth(per_portion * factor * count),
            start, end, f"energy_intake:{_text(uid) or pk}", zone_name, extra, tier,
        )  # fmt: skip


def _weights(
    con: sqlite3.Connection,
    tables: set[str],
    unit_preference: str,
    zone: ZoneInfo,
    zone_name: str | None,
    counts: dict[str, int],
    tier: int,
) -> Iterator[dict[str, Any]]:
    if "measurements" not in tables or "measurement_types" not in tables:
        return
    sql = (
        "SELECT m.id, m.uid, m.value, m.entry_date, t.description FROM measurements m"
        " LEFT JOIN measurement_types t ON t.id = m.measurement_type_id ORDER BY m.entry_date, m.id"
    )
    for pk, uid, value, day, description in con.execute(sql):
        if _text(description).lower() != WEIGHT_TYPE:
            _count(counts, "skipped_other_type")
            continue
        number = _number(value)
        if number is None or number <= 0:
            _count(counts, "skipped_no_value")
            continue
        start, end, _all_day = _when(day, None, zone)
        if start is None:
            _count(counts, "skipped_no_date")
            continue
        extra: dict[str, Any] = {"all_day": True}
        kilograms = number
        if unit_preference in POUNDS:
            kilograms = number * LB_TO_KG
            extra["original"] = {"quantity": _round(number), "unit": "lbs"}
        yield _line(
            "weight",
            "kg",
            _round(kilograms),
            start,
            end,
            f"weight:{_text(uid) or pk}",
            zone_name,
            extra,
            tier,
        )


def _workouts(
    con: sqlite3.Connection,
    tables: set[str],
    zone: ZoneInfo,
    zone_name: str | None,
    counts: dict[str, int],
    tier: int,
) -> Iterator[dict[str, Any]]:
    if "exercise_entries" not in tables:
        return
    columns = _columns(con, "exercise_entries")
    if "duration_in_seconds" not in columns:
        return
    activity = "x.description" if "exercises" in tables else "NULL"
    join = "LEFT JOIN exercises x ON x.id = e.exercise_id" if "exercises" in tables else ""
    calories = "e.calories" if "calories" in columns else "NULL"
    sql = (
        f"SELECT e.id, e.uid, e.entry_date, e.duration_in_seconds, {calories}, {activity}"
        f" FROM exercise_entries e {join} ORDER BY e.entry_date, e.id"
    )
    for pk, uid, day, duration, energy, name in con.execute(sql):
        seconds = _number(duration)
        if seconds is None or seconds <= 0:
            _count(counts, "skipped_bad_span")
            continue
        start, end, _all_day = _when(day, None, zone)
        if start is None:
            _count(counts, "skipped_no_date")
            continue
        extra: dict[str, Any] = {}
        if _text(name):
            extra["activity"] = _text(name)
        kcal = _number(energy)
        if kcal is not None:
            extra["energy_kcal"] = _round(kcal)
        extra["all_day"] = True
        yield _line(
            "workout", "s", _round(seconds), start, end, f"workout:{_text(uid) or pk}", zone_name, extra, tier
        )


def _when(day: object, clock: object, zone: ZoneInfo) -> tuple[datetime | None, datetime | None, bool]:
    """(`at`, `end`, all day) from the store's local date and optional clock: an instant when the
    clock is there, else the span of that local day."""
    try:
        local_day = date.fromisoformat(_text(day))
    except ValueError:
        return None, None, False
    clock_text = _text(clock)
    if clock_text:
        try:
            local_time = time.fromisoformat(clock_text)
        except ValueError:
            local_time = None
        if local_time is not None:
            return datetime.combine(local_day, local_time, tzinfo=zone), None, False
    start = datetime.combine(local_day, time(0, 0), tzinfo=zone)
    end = datetime.combine(local_day + timedelta(days=1), time(0, 0), tzinfo=zone)
    return start, end, True


def _line(
    type_name: str,
    unit: str,
    value: int | float,
    start: datetime,
    end: datetime | None,
    raw_id: str,
    tz: str | None,
    extra: dict[str, Any],
    tier: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": raw_id,
        "type": type_name,
        "value": value,
        "unit": unit,
        "source_name": SOURCE_NAME,
    }
    if extra:
        payload["extra"] = extra
    return {
        "at": _stamp(start),
        "end": _stamp(end) if end is not None else None,
        "tz": tz,
        "source": NAME,
        "kind": KIND,
        "tier": tier,
        "payload": payload,
    }


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _text(value: object) -> str:
    if isinstance(value, bytes | bytearray | memoryview):
        try:
            return bytes(value).decode("utf-8").strip()
        except UnicodeDecodeError:
            return ""
    return value.strip() if isinstance(value, str) else ""


def _number(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def _round(value: int | float) -> int | float:
    rounded = round(float(value), 3)
    return int(rounded) if rounded == int(rounded) else rounded


def _round_tenth(value: int | float) -> int | float:
    rounded = round(float(value), 1)
    return int(rounded) if rounded == int(rounded) else rounded


def _stamp(when: datetime) -> str:
    return when.astimezone(UTC).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"
