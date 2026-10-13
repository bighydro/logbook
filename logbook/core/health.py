"""One row per day of the record's `health-sample/v1` lines (RFC 0014): sleep hours, steps,
resting heart rate, HRV — the readers `stats --health`, `rollup health` and the Day share.

`summary(lines, tz)` is a function of the lines it is given: every `health` line of the window,
the retraction lines beside them. Per local day (the record's zone): `sleep_h`, the asleep stages
(`asleep`, `core`, `deep`, `rem`; never `in_bed`, never `awake`) of the night that ends on that
day — per device the union of their spans, so a source that writes a night twice counts it once
(rule 4), and the longest device taken, never a sum across devices (rule 5) — in hours to one
decimal; `steps`, the sum over the day's quarter hours of the larger device's count (rule 5);
`resting_hr`, the mean of the day's resting readings, whole bpm; `hrv`, the mean of the day's
readings, whole ms. Units are as stored: a resting reading in `count/s` is multiplied by 60 to
read in bpm, one in `bpm` or `count/min` is taken as it is; an HRV reading in `s` is multiplied
by 1,000 to read in ms, one in `ms` is taken as it is. A line another health line
`supersedes` (a correction, `logbook repair health-units`) is out and the correction stands —
the latest one, when a line was corrected more than once; a retracted line is out. A field the
day has no line for is None. Under `lines` are the ids of the lines each number came from, and
under `by` the same ids per field.

`nights(lines, tz, start)` is the Day's night: per device, the asleep stages in time order, one night
while no gap between a stage and the next exceeds `NIGHT_GAP_S` (two hours); a night is on the local
day its last stage ends in, under `start` (a night across a 06:00 boundary is the day it ends on,
never split between two), and of the nights that end on a day the longest asleep is its night — the
longest device's, never a sum across devices (rule 5). `training(lines, tz, start)` is the day's
`workout` lines (on the local day of their start): the union of their spans, so a run the watch and a
phone app both recorded counts once. Nothing here opens a file."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .chain import Line
from .day_start import lenient, local_day
from .index import local_date
from .store import RETRACTION, retractions

KIND = "health"
ASLEEP = frozenset({"asleep", "core", "deep", "rem"})  # RFC 0014 rule 4: never in_bed, never awake
FIELDS = ("sleep_h", "steps", "resting_hr", "hrv")
NIGHT_GAP_S = 2 * 3600  # asleep stages of one device this close are one night; farther apart, two sleeps
WORKOUT = "workout"


def standing(lines: Iterable[Line]) -> list[Line]:
    """The health lines not retracted and not superseded by another health line, in chain order.
    Of several lines that supersede the same line, the latest stands and the earlier corrections
    are out with the line they corrected."""
    kept = sorted(lines, key=lambda line: int(line.get("seq", 0)))
    retracted = retractions(line for line in kept if line.get("kind") == RETRACTION)
    live = [line for line in kept if line.get("kind") == KIND and str(line.get("id")) not in retracted]
    latest: dict[str, str] = {}  # superseded id → the id of the last line that supersedes it
    for line in live:
        over = (line.get("payload") or {}).get("supersedes")
        if isinstance(over, str):
            latest[over] = str(line.get("id"))
    out = set(latest)
    for line in live:
        over = (line.get("payload") or {}).get("supersedes")
        if isinstance(over, str) and latest[over] != str(line.get("id")):
            out.add(str(line.get("id")))
    return [line for line in live if str(line.get("id")) not in out]


def bpm(value: float, unit: object) -> float:
    """A heart rate in bpm from the value as stored: count/s is multiplied by 60; bpm and
    count/min are what they say."""
    return value * 60 if unit == "count/s" else value


def ms(value: float, unit: object) -> float:
    """A heart-rate variability (SDNN) in ms from the value as stored: s is multiplied by 1,000;
    ms is what it says. RFC 0014: HRV is reported in ms, always."""
    return value * 1000 if unit == "s" else value


def summary(lines: Iterable[Line], tz: str, start: object = None) -> list[dict[str, Any]]:
    """The rows, oldest day first; see the module docstring. A line's day is its local day under
    `start`, the record's `day_start` (RFC 0036; None is midnight), checked by the reader that asks."""
    steps: dict[str, dict[str, tuple[float, str]]] = {}  # day → bucket `at` → (the larger count, its line)
    sleep: dict[str, dict[str, list[tuple[datetime, datetime, str]]]] = {}  # day → device → asleep spans
    resting: dict[str, list[tuple[float, str]]] = {}
    hrv: dict[str, list[tuple[float, str]]] = {}
    for line in standing(lines):
        payload = line.get("payload") or {}
        value = payload.get("value")
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        kind = payload.get("type")
        id_ = str(line.get("id", ""))
        try:
            if kind == "steps":
                day = local_date(str(line["at"]), tz, start)
                buckets = steps.setdefault(day, {})
                kept = buckets.get(str(line["at"]))
                if kept is None or float(value) > kept[0]:
                    buckets[str(line["at"])] = (float(value), id_)
            elif kind == "sleep" and payload.get("stage") in ASLEEP:
                day = local_date(str(line.get("end") or line["at"]), tz, start)
                device = str(payload.get("device") or "-")
                begun, ended = _sleep_span(line, float(value))
                sleep.setdefault(day, {}).setdefault(device, []).append((begun, ended, id_))
            elif kind == "resting_hr":
                reading = (bpm(float(value), payload.get("unit")), id_)
                resting.setdefault(local_date(str(line["at"]), tz, start), []).append(reading)
            elif kind == "hrv":
                reading = (ms(float(value), payload.get("unit")), id_)
                hrv.setdefault(local_date(str(line["at"]), tz, start), []).append(reading)
        except (KeyError, ValueError, TypeError):  # a stamp that does not parse is on no day
            continue
    rows: list[dict[str, Any]] = []
    for day in sorted(set(steps) | set(sleep) | set(resting) | set(hrv)):
        nights, readings, variability = sleep.get(day), resting.get(day), hrv.get(day)
        by: dict[str, list[str]] = {field: [] for field in FIELDS}
        sleep_h = None
        if nights:
            device, spans = max(nights.items(), key=lambda kv: _union_s([(a, b) for a, b, _ in kv[1]]))
            sleep_h = round(_union_s([(a, b) for a, b, _ in spans]) / 3600, 1)
            by["sleep_h"] = [id_ for _a, _b, id_ in spans if id_]
        if day in steps:
            by["steps"] = [id_ for _n, id_ in steps[day].values() if id_]
        if readings:
            by["resting_hr"] = [id_ for _v, id_ in readings if id_]
        if variability:
            by["hrv"] = [id_ for _v, id_ in variability if id_]
        rows.append(
            {
                "day": day,
                "sleep_h": sleep_h,
                "steps": round(sum(n for n, _ in steps[day].values())) if day in steps else None,
                "resting_hr": round(sum(v for v, _ in readings) / len(readings)) if readings else None,
                "hrv": round(sum(v for v, _ in variability) / len(variability)) if variability else None,
                "lines": [id_ for field in FIELDS for id_ in by[field]],
                "by": by,
            }
        )
    return rows


def nights(lines: Iterable[Line], tz: str, start: object = None) -> dict[str, dict[str, Any]]:
    """By local day, the night that ends on it (the module docstring): `start` and `end` (RFC3339 UTC,
    the first asleep stage's start and the last one's end), `asleep_s` (the union of its asleep stages,
    whole seconds), `device` (None when the lines name none) and `lines` (the stages, in time order). A
    day no night ends on has no entry."""
    zone, clock = ZoneInfo(tz), lenient(start)
    by_device: dict[str, list[tuple[datetime, datetime, str]]] = {}
    for line in standing(lines):
        payload = line.get("payload") or {}
        value = payload.get("value")
        if payload.get("type") != "sleep" or payload.get("stage") not in ASLEEP:
            continue
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        try:
            begun, ended = _sleep_span(line, float(value))
        except (KeyError, ValueError, TypeError):  # a stamp that does not parse is on no night
            continue
        device = str(payload.get("device") or "-")
        by_device.setdefault(device, []).append((begun, ended, str(line.get("id", ""))))
    out: dict[str, dict[str, Any]] = {}
    for device in sorted(by_device):
        for spans in _runs(sorted(by_device[device])):
            begun, ended = spans[0][0], max(b for _a, b, _id in spans)
            night = {
                "start": _stamp(begun),
                "end": _stamp(ended),
                "asleep_s": round(_union_s([(a, b) for a, b, _id in spans])),
                "device": None if device == "-" else device,
                "lines": [id_ for _a, _b, id_ in spans if id_],
            }
            day = local_day(ended, zone, clock).isoformat()
            kept = out.get(day)
            if kept is None or night["asleep_s"] > kept["asleep_s"]:
                out[day] = night
    return out


def training(lines: Iterable[Line], tz: str, start: object = None) -> dict[str, dict[str, Any]]:
    """By local day of their start, the day's workouts: `minutes`, the union of their spans in whole
    minutes, and `lines`, their ids in time order. A day with no workout has no entry."""
    found: dict[str, list[tuple[datetime, datetime, str]]] = {}
    for line in standing(lines):
        payload = line.get("payload") or {}
        value = payload.get("value")
        if payload.get("type") != WORKOUT or isinstance(value, bool) or not isinstance(value, int | float):
            continue
        try:
            begun, ended = _sleep_span(line, float(value))
            day = local_date(str(line["at"]), tz, start)
        except (KeyError, ValueError, TypeError):
            continue
        found.setdefault(day, []).append((begun, ended, str(line.get("id", ""))))
    return {
        day: {
            "minutes": round(_union_s([(a, b) for a, b, _id in spans]) / 60),
            "lines": [id_ for _a, _b, id_ in sorted(spans) if id_],
        }
        for day, spans in sorted(found.items())
    }


def _runs(spans: list[tuple[datetime, datetime, str]]) -> list[list[tuple[datetime, datetime, str]]]:
    """Spans in time order split where the next starts more than `NIGHT_GAP_S` after every earlier one
    has ended: each run one sleep."""
    runs: list[list[tuple[datetime, datetime, str]]] = []
    reach: datetime | None = None
    for span in spans:
        if reach is None or (span[0] - reach).total_seconds() > NIGHT_GAP_S:
            runs.append([])
            reach = span[1]
        runs[-1].append(span)
        reach = max(reach, span[1])
    return runs


def _stamp(instant: datetime) -> str:
    return instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sleep_span(line: Line, seconds: float) -> tuple[datetime, datetime]:
    """A sleep stage's span: `at` to `end`, or `at` plus its `value` when `end` is missing."""
    start = datetime.fromisoformat(str(line["at"]).replace("Z", "+00:00"))
    end = line.get("end")
    if isinstance(end, str):
        return start, datetime.fromisoformat(end.replace("Z", "+00:00"))
    return start, start + timedelta(seconds=seconds)


def _union_s(spans: list[tuple[datetime, datetime]]) -> float:
    """The seconds covered by the spans, an instant under two of them counted once."""
    total = 0.0
    run_start: datetime | None = None
    run_end: datetime | None = None
    for start, end in sorted(spans):
        if run_start is None or run_end is None or start > run_end:
            if run_start is not None and run_end is not None:
                total += (run_end - run_start).total_seconds()
            run_start, run_end = start, end
        elif end > run_end:
            run_end = end
    if run_start is not None and run_end is not None:
        total += (run_end - run_start).total_seconds()
    return total
