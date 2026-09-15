"""The day package: `logbook export --day` (ADR 0013 §4). A view of the log, never a replacement."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .chain import Line, canonical_json
from .store import Logbook, now_utc, retractions

SCHEMA = "day-package/v1"


def local_date(at: str, tz: str) -> str:
    """The calendar date of an RFC3339 UTC instant in the owner's timezone."""
    instant = datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone(UTC)
    return instant.astimezone(ZoneInfo(tz)).date().isoformat()


def parse_day(text: str) -> date:
    try:
        d = date.fromisoformat(text)
    except ValueError as e:
        raise ValueError(f"not a date (YYYY-MM-DD): {text!r}") from e
    if d.isoformat() != text:
        raise ValueError(f"not a date (YYYY-MM-DD): {text!r}")
    return d


def day_range(first: str, last: str) -> list[str]:
    a, b = parse_day(first), parse_day(last)
    if b < a:
        raise ValueError(f"range runs backwards: {first} > {last}")
    return [(a + timedelta(days=n)).isoformat() for n in range((b - a).days + 1)]


def entry(line: Line, retracted_by: Line | None = None) -> dict[str, Any]:
    """The day-package view of one line: identity and shape, never the payload. A retracted
    line stays (the record is complete) and carries the id of the retraction that hides it."""
    e = {
        "id": line["id"],
        "seq": line["seq"],
        "at": line["at"],
        "end": line.get("end"),
        "kind": line["kind"],
        "tier": line["tier"],
        "source": line["source"],
        "raw_id": (line.get("payload") or {}).get("raw_id"),
        "tags": [],
    }
    if retracted_by is not None:
        e["retracted_by"] = retracted_by["id"]
    return e


def entries_by_day(lb: Logbook, tz: str) -> dict[str, list[dict[str, Any]]]:
    """Every line as an entry, grouped by local date, each day in chain order. One pass over the
    log, streamed: entries are small, lines are not, and a year of days must not mean a year of
    re-reads."""
    lines: dict[str, list[Line]] = {}
    for line in lb.lines_unsorted():
        lines.setdefault(local_date(line["at"], tz), []).append(line)
    retracted = retractions(line for rows in lines.values() for line in rows)
    days: dict[str, list[dict[str, Any]]] = {}
    for day, rows in lines.items():
        rows.sort(key=lambda r: r["seq"])
        days[day] = [entry(line, retracted.get(line["id"])) for line in rows]
    return days


def day_entries(lb: Logbook, day: str) -> list[dict[str, Any]]:
    """One entry per line whose local date is `day`, in chain order."""
    return entries_by_day(lb, lb.meta["timezone"]).get(day, [])


def day_packages(lb: Logbook, days: list[str], generated_at: str | None = None) -> dict[str, dict[str, Any]]:
    """One package per requested day (empty days included), from a single read of the log.
    All packages carry the same `logbook_head`: they describe one state of the record."""
    for day in days:
        parse_day(day)
    meta = lb.meta
    generated_at = generated_at or now_utc()
    by_day = entries_by_day(lb, meta["timezone"])
    return {
        day: {
            "schema": SCHEMA,
            "date": day,
            "tz": meta["timezone"],
            "owner_id": meta["owner_id"],
            "generated_at": generated_at,
            "logbook_head": meta["head"],
            "entries": by_day.get(day, []),
            "derived": {},
            "attachments": [],
        }
        for day in days
    }


def day_package(lb: Logbook, day: str, generated_at: str | None = None) -> dict[str, Any]:
    return day_packages(lb, [day], generated_at)[day]


def write_package(package: dict[str, Any], out: Path) -> None:
    """Write `out/package.json` (canonical JSON). Re-running overwrites in place."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "package.json").write_text(canonical_json(package) + "\n", encoding="utf-8")


def write_day_package(lb: Logbook, day: str, out: Path, generated_at: str | None = None) -> int:
    """Build and write one day package; returns how many entries it holds."""
    package = day_package(lb, day, generated_at)
    write_package(package, out)
    return len(package["entries"])
