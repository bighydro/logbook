"""The Withings data export (the CSVs of *Download my data*) → health-sample/v1 (RFC 0014).

Not an adapter: `withings.run` reads an export through here when its path is the export's folder (or
one of its files), and the app's stores otherwise; both write `source` `withings`. The files read,
found by name, the columns by header (a column this reader does not need may be missing or renamed;
a file without one it needs is counted `skipped_unreadable_csv`, never a traceback):

    weight.csv            Date, Weight (kg), Fat mass (kg), Bone mass (kg), Muscle mass (kg),
                          Hydration (kg), Comments  — one standing per row; a line per quantity (rule 9):
                          `weight`, `fat_mass`, `bone_mass`, `muscle_mass`, `body_water`, and
                          `body_fat_pct` or `bmi` when the export carries them. A mass column in
                          pounds (`(lb)`) is converted to kg, the entered value under `extra.original`.
    bp.csv                Date, Heart Rate, Systolic, Diastolic, Comments — the cuff's pulse as a
                          `heart_rate` line (`raw_id` `heart_rate:bp:<at>`), the pressures beside it
                          under `extra.systolic_mmhg` and `extra.diastolic_mmhg`: blood pressure is no
                          type of the profile (rule 8), and `extra` is what else the source reports.
    sleep.csv             from, to, light (s), deep (s), rem (s), awake (s), Average heart rate, … — one
                          `in_bed` span per night (`sleep:night:<from>`), the night's totals the export
                          computed under `extra`; the stages come from the raw file, rule 4.
    raw_<device>_<measure>.csv   start, duration, value — `start` an ISO stamp with its offset, `duration`
                          and `value` JSON lists, one sample per pair, each starting where the one
                          before ended. `<device>` is `tracker` (a watch), `bed` (the sleep mat) …, and
                          it is the line's `device`. The measures: `steps` → `steps`, `distance` →
                          `distance` (m), `calories-earned` → `active_energy` (kcal), each summed into
                          quarter-hour UTC buckets per device (rule 2); `hr` → `heart_rate` bpm, one
                          reading per minute per device (rule 3); `sleep-state` → `sleep` spans, one
                          per run of equal states, 0 `awake`, 1 (light) `core`, 2 `deep`, 3 `rem`
                          (rule 4); any other measure (`elevation`) is counted `skipped_other_type` per row.
    activities.csv        from, to, Timezone, Type, Data — one `workout` span per row, `value` its
                          duration, the type under `extra.activity`, the steps, calories and distance
                          the `Data` JSON carries under `extra`, `tz` the row's zone.
    height.csv            counted `skipped_other_type` per row (no type of the profile).
    aggregates_*.csv      daily totals, derived: counted `skipped_daily_total` per row (rule 2).

Any other file of the export is not read. A naive clock (`weight.csv`, `bp.csv`: `2026-06-08
07:12:33`) is the account's local time, read in the record's zone; an ISO stamp with an offset is
taken as it says. `tz` is the record's zone (an offset names no zone), the activity's own when the
row has one. `raw_id` is `<type>:<at>` for a reading, `<type>:<device>:<at>` for a tracker's, `<type>:
<bucket start>:<device>` for a bucket, `sleep:night:<from>` for a night; a later export of the same
account gives the same keys, so re-adding appends nothing and a changed sample is a correction
(`health_export.corrected`). Pure: files opened read-only, each once; no network."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any

from . import health_export as hx

SOURCE = "withings"
KIND = "health"
SCHEMA = "health-sample/v1"

RAW_PREFIX = "raw_"
AGGREGATES_PREFIX = "aggregates_"
NAMED = {"weight.csv": "weight", "bp.csv": "bp", "sleep.csv": "sleep", "activities.csv": "activities"}
OTHER = {"height.csv"}
BUCKET = timedelta(minutes=15)
LB_TO_KG = 0.45359237
STATES = {0: "awake", 1: "core", 2: "deep", 3: "rem"}
MEASURES = {"steps": "steps", "distance": "distance", "calories-earned": "active_energy"}  # bucketed
UNITS = {
    "steps": "count",
    "distance": "m",
    "active_energy": "kcal",
    "heart_rate": "bpm",
    "sleep": "s",
    "workout": "s",
}
MASSES = {  # weight.csv header (without its unit) → type
    "weight": "weight",
    "fat mass": "fat_mass",
    "bone mass": "bone_mass",
    "muscle mass": "muscle_mass",
    "hydration": "body_water",
}
BODY_FAT_PCT = ("fat mass (%)", "fat ratio (%)", "body fat (%)")
BMI = ("bmi", "bmi (kg/m2)", "bmi (kg/m²)")
NIGHT_EXTRA = {  # sleep.csv header → extra key, kept when the row has it
    "light (s)": "light_s",
    "deep (s)": "deep_s",
    "rem (s)": "rem_s",
    "awake (s)": "awake_s",
    "average heart rate": "heart_rate_avg",
    "heart rate (min)": "heart_rate_min",
    "heart rate (max)": "heart_rate_max",
}
ACTIVITY_DATA = {"steps": "steps", "calories": "energy_kcal", "distance": "distance_m"}


def is_export(path: Path) -> bool:
    """The export's folder (any of its known files in it), or one of those files. Never raises."""
    path = Path(path)
    try:
        if path.is_dir():
            return any(_kind(p) is not None for p in path.iterdir() if p.is_file())
        return path.is_file() and _kind(path) is not None and hx.rows(path) is not None
    except OSError:
        return False


def _kind(path: Path) -> str | None:
    """What a file of the export holds, by its name; None for one this reader does not know."""
    name = path.name.lower()
    if name in NAMED:
        return NAMED[name]
    if name in OTHER:
        return "other"
    if name.startswith(AGGREGATES_PREFIX) and name.endswith(".csv"):
        return "aggregate"
    if name.startswith(RAW_PREFIX) and name.endswith(".csv") and name.count("_") >= 2:
        return "raw"
    return None


def files(path: Path) -> list[Path]:
    """The files one call reads, in name order."""
    path = Path(path)
    if path.is_dir():
        return sorted(p for p in path.iterdir() if p.is_file() and _kind(p) is not None)
    return [path] if _kind(path) is not None else []


def lines(path: Path, counts: dict[str, int], timezone: str | None, tier: int) -> list[dict[str, Any]]:
    """Every line of the export at `path`, sorted by `at` then `raw_id`."""
    local = hx.zone(timezone)
    out: list[dict[str, Any]] = []
    for file in files(path):
        kind = _kind(file)
        read = hx.rows(file)
        if read is None:
            hx.count(counts, "skipped_unreadable_csv")
            continue
        header, rows = read
        if kind == "weight":
            out.extend(_weights(header, rows, local, timezone, tier, counts))
        elif kind == "bp":
            out.extend(_pulses(header, rows, local, timezone, tier, counts))
        elif kind == "sleep":
            out.extend(_nights(header, rows, local, timezone, tier, counts))
        elif kind == "activities":
            out.extend(_workouts(header, rows, local, timezone, tier, counts))
        elif kind == "raw":
            out.extend(_raw(file, header, rows, local, timezone, tier, counts))
        elif kind == "aggregate":
            hx.count(counts, "skipped_daily_total", len(rows))
        else:
            hx.count(counts, "skipped_other_type", len(rows))
    out.sort(key=lambda line: (line["at"], line["payload"]["raw_id"]))
    return out


# -- weight.csv ------------------------------------------------------------------------------------


def _weights(
    header: list[str],
    rows: list[dict[str, str]],
    local: tzinfo,
    tz: str | None,
    tier: int,
    counts: dict[str, int],
) -> Iterator[dict[str, Any]]:
    date = hx.column(header, "date")
    if date is None:
        hx.count(counts, "skipped_unreadable_csv")
        return
    quantities: list[tuple[str, str, str, str]] = []  # column, type, unit written, unit in the header
    for cell in header:
        name, unit = _split_unit(cell)
        if cell in BODY_FAT_PCT:
            quantities.append((cell, "body_fat_pct", "%", "%"))
        elif cell in BMI:
            quantities.append((cell, "bmi", "kg/m2", "kg/m2"))
        elif name in MASSES and unit in ("kg", "lb", "lbs"):
            quantities.append((cell, MASSES[name], "kg", unit))
    comment = hx.column(header, "comments", "comment")
    for row in rows:
        at = hx.when(row[date], local)
        if at is None:
            hx.count(counts, "skipped_bad_date")
            continue
        found = 0
        for cell, type_name, unit, source_unit in quantities:
            value = hx.number(row[cell])
            if value is None:
                continue
            found += 1
            extra: dict[str, Any] = {}
            if source_unit in ("lb", "lbs"):
                extra["original"] = {"value": value, "unit": "lb"}
                value = hx.rounded(value * LB_TO_KG)
            if comment and row[comment]:
                extra["comment"] = row[comment]
            yield _line(
                type_name, value, unit, at, None, f"{type_name}:{hx.stamp(at)}", None, tz, tier, extra
            )
        if not found:
            hx.count(counts, "skipped_no_value")


def _split_unit(cell: str) -> tuple[str, str]:
    """`fat mass (kg)` → (`fat mass`, `kg`); a header without a unit → (`cell`, ``)."""
    name, sep, rest = cell.partition("(")
    return (name.strip(), rest.rstrip(")").strip()) if sep else (cell.strip(), "")


# -- bp.csv ----------------------------------------------------------------------------------------


def _pulses(
    header: list[str],
    rows: list[dict[str, str]],
    local: tzinfo,
    tz: str | None,
    tier: int,
    counts: dict[str, int],
) -> Iterator[dict[str, Any]]:
    date, pulse = hx.column(header, "date"), hx.column(header, "heart rate", "heart rate (bpm)")
    if date is None or pulse is None:
        hx.count(counts, "skipped_unreadable_csv")
        return
    systolic, diastolic = hx.column(header, "systolic"), hx.column(header, "diastolic")
    comment = hx.column(header, "comments", "comment")
    for row in rows:
        at = hx.when(row[date], local)
        if at is None:
            hx.count(counts, "skipped_bad_date")
            continue
        value = hx.number(row[pulse])
        if value is None:
            hx.count(counts, "skipped_no_value")
            continue
        extra: dict[str, Any] = {}
        for cell, key in ((systolic, "systolic_mmhg"), (diastolic, "diastolic_mmhg")):
            pressure = hx.number(row[cell]) if cell else None
            if pressure is not None:
                extra[key] = pressure
        if comment and row[comment]:
            extra["comment"] = row[comment]
        yield _line(
            "heart_rate", value, "bpm", at, None, f"heart_rate:bp:{hx.stamp(at)}", None, tz, tier, extra
        )


# -- sleep.csv -------------------------------------------------------------------------------------


def _nights(
    header: list[str],
    rows: list[dict[str, str]],
    local: tzinfo,
    tz: str | None,
    tier: int,
    counts: dict[str, int],
) -> Iterator[dict[str, Any]]:
    start, end = hx.column(header, "from", "start"), hx.column(header, "to", "end")
    if start is None or end is None:
        hx.count(counts, "skipped_unreadable_csv")
        return
    for row in rows:
        began, ended = hx.when(row[start], local), hx.when(row[end], local)
        if began is None or ended is None:
            hx.count(counts, "skipped_bad_date")
            continue
        if ended <= began:
            hx.count(counts, "skipped_bad_span")
            continue
        extra: dict[str, Any] = {}
        for cell, key in NIGHT_EXTRA.items():
            value = hx.number(row.get(cell))
            if value is not None:
                extra[key] = value
        seconds = int((ended - began).total_seconds())
        yield _line(
            "sleep",
            seconds,
            "s",
            began,
            ended,
            f"sleep:night:{hx.stamp(began)}",
            None,
            tz,
            tier,
            extra,
            "in_bed",
        )


# -- activities.csv --------------------------------------------------------------------------------


def _workouts(
    header: list[str],
    rows: list[dict[str, str]],
    local: tzinfo,
    tz: str | None,
    tier: int,
    counts: dict[str, int],
) -> Iterator[dict[str, Any]]:
    start, end = hx.column(header, "from", "start"), hx.column(header, "to", "end")
    if start is None or end is None:
        hx.count(counts, "skipped_unreadable_csv")
        return
    kind, zone, data = hx.column(header, "type"), hx.column(header, "timezone"), hx.column(header, "data")
    for row in rows:
        began, ended = hx.when(row[start], local), hx.when(row[end], local)
        if began is None or ended is None:
            hx.count(counts, "skipped_bad_date")
            continue
        if ended <= began:
            hx.count(counts, "skipped_bad_span")
            continue
        extra: dict[str, Any] = {}
        if kind and row[kind]:
            extra["activity"] = row[kind]
        for key, out in ACTIVITY_DATA.items():
            value = _data(row[data] if data else "").get(key)
            if isinstance(value, int | float) and not isinstance(value, bool):
                extra[out] = hx.rounded(value)
        row_tz = row[zone] if zone and row[zone] and "/" in row[zone] else tz
        seconds = int((ended - began).total_seconds())
        yield _line(
            "workout", seconds, "s", began, ended, f"workout:{hx.stamp(began)}", None, row_tz, tier, extra
        )


def _data(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text) if text else {}
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


# -- raw_<device>_<measure>.csv ---------------------------------------------------------------------


def _raw(
    file: Path,
    header: list[str],
    rows: list[dict[str, str]],
    local: tzinfo,
    tz: str | None,
    tier: int,
    counts: dict[str, int],
) -> Iterator[dict[str, Any]]:
    _raw, device, measure = file.name.lower().removesuffix(".csv").split("_", 2)
    start, duration, value = (
        hx.column(header, "start"),
        hx.column(header, "duration"),
        hx.column(header, "value"),
    )
    if start is None or duration is None or value is None:
        hx.count(counts, "skipped_unreadable_csv")
        return
    if measure not in MEASURES and measure not in ("hr", "sleep-state"):
        hx.count(counts, "skipped_other_type", len(rows))
        return
    samples: list[tuple[datetime, int, float]] = []  # start, seconds, value
    for row in rows:
        began = hx.when(row[start], local)
        durations, values = _list(row[duration]), _list(row[value])
        if began is None or durations is None or values is None or len(durations) != len(values):
            hx.count(counts, "skipped_unreadable_row")
            continue
        at = began
        for seconds, number in zip(durations, values, strict=True):
            samples.append((at, int(seconds), number))
            at += timedelta(seconds=int(seconds))
    samples.sort(key=lambda sample: sample[0])
    if measure == "hr":
        yield from _readings(samples, device, tz, tier, counts)
    elif measure == "sleep-state":
        yield from _stages(samples, device, tz, tier, counts)
    else:
        yield from _buckets(samples, MEASURES[measure], device, tz, tier)


def _list(text: str) -> list[float] | None:
    try:
        parsed = json.loads(text)
    except ValueError:
        return None
    if not isinstance(parsed, list) or not all(
        isinstance(x, int | float) and not isinstance(x, bool) for x in parsed
    ):
        return None
    return [float(x) for x in parsed]


def _readings(
    samples: list[tuple[datetime, int, float]], device: str, tz: str | None, tier: int, counts: dict[str, int]
) -> Iterator[dict[str, Any]]:
    """Heart rate: the first reading of each UTC minute (rule 3)."""
    last: datetime | None = None
    for at, _seconds, value in samples:
        minute = at.replace(second=0, microsecond=0)
        if last == minute:
            hx.count(counts, "skipped_over_cap")
            continue
        last = minute
        raw_id = f"heart_rate:{device}:{hx.stamp(at)}"
        yield _line("heart_rate", hx.rounded(value), "bpm", at, None, raw_id, device, tz, tier, {})


def _stages(
    samples: list[tuple[datetime, int, float]], device: str, tz: str | None, tier: int, counts: dict[str, int]
) -> Iterator[dict[str, Any]]:
    """Sleep: one span per run of equal states (rule 4)."""
    run_start: datetime | None = None
    run_end: datetime | None = None
    run_stage: str | None = None
    for at, seconds, value in samples:
        stage = STATES.get(int(value)) if value == int(value) else None
        if stage is None:
            hx.count(counts, "skipped_unknown_stage")
            continue
        if run_start is not None and run_end is not None and stage == run_stage and at == run_end:
            run_end = at + timedelta(seconds=seconds)
            continue
        if run_start is not None and run_end is not None and run_stage is not None:
            yield _stage(run_start, run_end, run_stage, device, tz, tier)
        run_start, run_end, run_stage = at, at + timedelta(seconds=seconds), stage
    if run_start is not None and run_end is not None and run_stage is not None:
        yield _stage(run_start, run_end, run_stage, device, tz, tier)


def _stage(
    start: datetime, end: datetime, stage: str, device: str, tz: str | None, tier: int
) -> dict[str, Any]:
    seconds = int((end - start).total_seconds())
    raw_id = f"sleep:{device}:{hx.stamp(start)}"
    return _line("sleep", seconds, "s", start, end, raw_id, device, tz, tier, {}, stage)


def _buckets(
    samples: list[tuple[datetime, int, float]], type_name: str, device: str, tz: str | None, tier: int
) -> Iterator[dict[str, Any]]:
    """Counts summed into quarter hours aligned to the UTC hour, per device (rule 2)."""
    totals: dict[datetime, list[float]] = {}  # bucket start → [sum, samples]
    for at, _seconds, value in samples:
        start = at.replace(minute=at.minute - at.minute % 15, second=0, microsecond=0)
        bucket = totals.setdefault(start, [0.0, 0])
        bucket[0] += value
        bucket[1] += 1
    for start in sorted(totals):
        total, n = totals[start]
        raw_id = f"{type_name}:{hx.stamp(start)}:{device}"
        extra = {"samples": int(n)}
        yield _line(
            type_name,
            hx.rounded(total),
            UNITS[type_name],
            start,
            start + BUCKET,
            raw_id,
            device,
            tz,
            tier,
            extra,
        )


# -- the line --------------------------------------------------------------------------------------


def _line(
    type_name: str,
    value: int | float,
    unit: str,
    start: datetime,
    end: datetime | None,
    raw_id: str,
    device: str | None,
    tz: str | None,
    tier: int,
    extra: dict[str, Any],
    stage: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": raw_id,
        "type": type_name,
        "value": value,
        "unit": unit,
    }
    if stage is not None:
        payload["stage"] = stage
    if device:
        payload["device"] = device
    if extra:
        payload["extra"] = extra
    return {
        "at": hx.stamp(start),
        "end": hx.stamp(end) if end is not None else None,
        "tz": tz,
        "source": SOURCE,
        "kind": KIND,
        "tier": tier,
        "payload": payload,
    }


__all__ = ["UTC", "files", "is_export", "lines"]
