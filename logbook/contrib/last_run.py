"""The scheduled run's outcome (`logbook sync --scheduled`, docs/schedule.md): `state/last-run.json`,
bookkeeping beside the sync watermarks, never in the chain and never in a backup.

```json
{
  "at": "2026-10-08T17:00:12Z",
  "sources": {"immich": {"result": "ok", "lines": 12}, "gcal": {"result": "failed (status 1)", "lines": 0}},
  "doctor": {"pass": 12, "warn": 1, "fail": 0, "warned": ["sync:gcal"], "failed": []},
  "first_failing": "gcal  failed (status 1)",
  "clean": false,
  "week": [{"at": "2026-10-08T17:00:12Z", "clean": false, "lines": {"immich": 12}}],
  "weekly_sent": "2026-10-04"
}
```

`at` is when the run began, UTC. `sources` is one entry per live source `sync --all` listed, with
the lines it appended. `doctor` is the counts and the names of the checks that warned or failed,
and null while the run is still between the sync and the doctor (the file is written twice: once
after the sync, so `doctor` itself reads a run that is in progress as the last run, and once at the
end). `first_failing` is the first line that was wrong, as the run printed it: a source's summary
line, else the first doctor line that is not a pass; null when everything passed. `clean` is no
source failed and the doctor had nothing to warn about or fail. `week` is one short entry per run
of the last seven days, for the Sunday message; `weekly_sent` the local day the last weekly message
went out. `doctor` reads the file and warns when the last run is older than 26 hours or failed
(`last_run_check`); the notifier (`logbook.contrib.notify`) reads it to say what is wrong."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

LAST_RUN_FILE = PurePosixPath("state/last-run.json")  # record-relative
STALE_AFTER = timedelta(hours=26)  # twice a day is the schedule; a day and a little is a missed run
WEEK = timedelta(days=7)
WEEKLY_HOUR = 12  # the Sunday run at or after this local hour is the evening one, which sends the week
STAMP = "%Y-%m-%dT%H:%M:%SZ"


class LastRunError(ValueError):
    """`state/last-run.json` is not the documented shape; the message names the file."""


@dataclass(frozen=True)
class Source:
    name: str
    result: str  # `ok`, `failed (status N)`, `skipped (why)`, `not run`, `interrupted`
    lines: int

    @property
    def failed(self) -> bool:
        return self.result.startswith("failed")


@dataclass(frozen=True)
class Doctor:
    passed: int
    warned: tuple[str, ...]  # the names of the checks that warned, in print order
    failed: tuple[str, ...]

    @property
    def clean(self) -> bool:
        return not self.warned and not self.failed


@dataclass(frozen=True)
class Run:
    at: datetime  # UTC, aware
    sources: tuple[Source, ...]
    doctor: Doctor | None  # None while the run is between the sync and the doctor
    first_failing: str | None

    @property
    def failed_sources(self) -> list[str]:
        return [s.name for s in self.sources if s.failed]

    @property
    def failed(self) -> bool:
        """A source failed, or the doctor failed a check: what the exit status 1 says."""
        return bool(self.failed_sources) or (self.doctor is not None and bool(self.doctor.failed))

    @property
    def clean(self) -> bool:
        return not self.failed_sources and self.doctor is not None and self.doctor.clean

    @property
    def lines(self) -> dict[str, int]:
        """The lines appended per source, only the sources that appended one."""
        return {s.name: s.lines for s in self.sources if s.lines}


@dataclass(frozen=True)
class WeekEntry:
    at: datetime
    clean: bool
    lines: dict[str, int]


@dataclass(frozen=True)
class State:
    """The file as a whole: the last run, the week behind it, and when the week was last sent."""

    run: Run
    week: tuple[WeekEntry, ...]
    weekly_sent: date | None


def now() -> datetime:
    """UTC, aware. Tests replace it."""
    return datetime.now(UTC)


def path_of(root: Path) -> Path:
    return Path(root).joinpath(*LAST_RUN_FILE.parts)


def stamp(at: datetime) -> str:
    return at.astimezone(UTC).strftime(STAMP)


def parse_stamp(text: str) -> datetime:
    return datetime.strptime(text, STAMP).replace(tzinfo=UTC)


# -- reading and writing ---------------------------------------------------------------------------------


def read(root: Path) -> State | None:
    """The file as written, or None when no scheduled run has happened. A file that is not the shape
    raises LastRunError naming it; nothing is written."""
    path = path_of(root)
    if not path.exists():
        return None
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
        return _state(data)
    except ValueError as e:  # json.JSONDecodeError is one; so is a stamp that will not parse
        raise LastRunError(f"{path} is not the shape `logbook sync --scheduled` writes: {e}") from None
    except (TypeError, AttributeError, KeyError):
        raise LastRunError(f"{path} is not the shape `logbook sync --scheduled` writes") from None


def _state(data: dict[str, Any]) -> State:
    sources = tuple(
        Source(str(name), str(entry["result"]), int(entry["lines"]))
        for name, entry in data["sources"].items()
    )
    doctor = None
    if data.get("doctor") is not None:
        d = data["doctor"]
        doctor = Doctor(
            int(d["pass"]), tuple(str(n) for n in d["warned"]), tuple(str(n) for n in d["failed"])
        )
    first = data.get("first_failing")
    run = Run(parse_stamp(str(data["at"])), sources, doctor, str(first) if first is not None else None)
    week = tuple(
        WeekEntry(
            parse_stamp(str(e["at"])), bool(e["clean"]), {str(k): int(v) for k, v in dict(e["lines"]).items()}
        )
        for e in data.get("week", [])
    )
    sent = data.get("weekly_sent")
    return State(run, week, date.fromisoformat(str(sent)) if sent is not None else None)


def write(root: Path, state: State) -> Path:
    """The file, written whole, replaced in one step."""
    run = state.run
    doctor: dict[str, Any] | None = None
    if run.doctor is not None:
        doctor = {
            "pass": run.doctor.passed,
            "warn": len(run.doctor.warned),
            "fail": len(run.doctor.failed),
            "warned": list(run.doctor.warned),
            "failed": list(run.doctor.failed),
        }
    data = {
        "at": stamp(run.at),
        "sources": {s.name: {"result": s.result, "lines": s.lines} for s in run.sources},
        "doctor": doctor,
        "first_failing": run.first_failing,
        "clean": run.clean,
        "week": [{"at": stamp(e.at), "clean": e.clean, "lines": e.lines} for e in state.week],
        "weekly_sent": state.weekly_sent.isoformat() if state.weekly_sent is not None else None,
    }
    path = path_of(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def previous(root: Path) -> State | None:
    """What the last run left, for the run that replaces it; a file that is not the shape is
    bookkeeping and counts as none."""
    try:
        return read(root)
    except LastRunError:
        return None


# -- the week --------------------------------------------------------------------------------------------


def roll(week: Iterable[WeekEntry], run: Run) -> tuple[WeekEntry, ...]:
    """`week` with `run` added and every entry older than seven days before it dropped."""
    kept = [e for e in week if e.at > run.at - WEEK and e.at != run.at]
    kept.append(WeekEntry(run.at, run.clean, run.lines))
    return tuple(sorted(kept, key=lambda e: e.at))


def week_lines(week: Sequence[WeekEntry]) -> dict[str, int]:
    """The lines per source over the week, sources with none left out, most first."""
    totals: dict[str, int] = {}
    for entry in week:
        for name, n in entry.lines.items():
            totals[name] = totals.get(name, 0) + n
    return dict(sorted(totals.items(), key=lambda kv: (-kv[1], kv[0])))


def is_week_end(local: datetime) -> bool:
    """Sunday, at or after `WEEKLY_HOUR` local: the evening run that sends the week."""
    return local.weekday() == 6 and local.hour >= WEEKLY_HOUR


def is_first_sunday(local: datetime) -> bool:
    return local.weekday() == 6 and local.day <= 7


# -- text ------------------------------------------------------------------------------------------------


def age_text(delta: timedelta) -> str:
    """`12 min ago`, `2 h ago`, `3 days ago`."""
    seconds = max(0, round(delta.total_seconds()))
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 48 * 3600:
        return f"{seconds // 3600} h ago"
    return f"{seconds // 86400} days ago"


def sources_text(run: Run) -> str:
    """`alpha 2, beta 1 lines; gamma failed`: the counts, then the sources that failed."""
    counted = ", ".join(f"{name} {n:,}" for name, n in run.lines.items())
    parts = [f"{counted} lines" if counted else "no new lines"]
    if run.failed_sources:
        parts.append(f"{', '.join(run.failed_sources)} failed")
    return "; ".join(parts)


def doctor_text(doctor: Doctor | None) -> str:
    if doctor is None:
        return "doctor not yet run"
    return f"doctor {doctor.passed} pass, {len(doctor.warned)} warn, {len(doctor.failed)} fail"


__all__ = [
    "LAST_RUN_FILE",
    "STALE_AFTER",
    "Doctor",
    "LastRunError",
    "Run",
    "Source",
    "State",
    "WeekEntry",
    "age_text",
    "doctor_text",
    "is_first_sunday",
    "is_week_end",
    "now",
    "path_of",
    "previous",
    "read",
    "roll",
    "sources_text",
    "week_lines",
    "write",
]
