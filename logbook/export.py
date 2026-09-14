"""The day package: `logbook export --day` (ADR 0013 §4). A view of the log, never a replacement."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .chain import canonical_json
from .store import Logbook, now_utc

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


def day_entries(lb: Logbook, day: str) -> list[dict[str, Any]]:
    """One entry per line whose local date is `day`, in chain order."""
    tz = lb.meta["timezone"]
    return [
        {
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
        for line in lb.lines()
        if local_date(line["at"], tz) == day
    ]


def day_package(lb: Logbook, day: str, generated_at: str | None = None) -> dict[str, Any]:
    parse_day(day)
    meta = lb.meta
    return {
        "schema": SCHEMA,
        "date": day,
        "tz": meta["timezone"],
        "owner_id": meta["owner_id"],
        "generated_at": generated_at or now_utc(),
        "logbook_head": meta["head"],
        "entries": day_entries(lb, day),
        "derived": {},
        "attachments": [],
    }


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
