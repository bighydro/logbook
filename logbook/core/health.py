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
under `by` the same ids per field. Nothing here opens a file."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from .chain import Line
from .index import local_date
from .store import RETRACTION, retractions

KIND = "health"
ASLEEP = frozenset({"asleep", "core", "deep", "rem"})  # RFC 0014 rule 4: never in_bed, never awake
FIELDS = ("sleep_h", "steps", "resting_hr", "hrv")


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


def summary(lines: Iterable[Line], tz: str) -> list[dict[str, Any]]:
    """The rows, oldest day first; see the module docstring."""
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
                day = local_date(str(line["at"]), tz)
                buckets = steps.setdefault(day, {})
                kept = buckets.get(str(line["at"]))
                if kept is None or float(value) > kept[0]:
                    buckets[str(line["at"])] = (float(value), id_)
            elif kind == "sleep" and payload.get("stage") in ASLEEP:
                day = local_date(str(line.get("end") or line["at"]), tz)
                device = str(payload.get("device") or "-")
                start, end = _sleep_span(line, float(value))
                sleep.setdefault(day, {}).setdefault(device, []).append((start, end, id_))
            elif kind == "resting_hr":
                reading = (bpm(float(value), payload.get("unit")), id_)
                resting.setdefault(local_date(str(line["at"]), tz), []).append(reading)
            elif kind == "hrv":
                reading = (ms(float(value), payload.get("unit")), id_)
                hrv.setdefault(local_date(str(line["at"]), tz), []).append(reading)
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
