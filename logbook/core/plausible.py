"""Plausible dates: which lines carry a timestamp far outside what their source could have meant.

A calendar entry dated 1948 or a mail dated 2612 is a parser's misreading or a sender's broken
clock, not a day of the owner's life. Such a line stays in the log as written (it is never
deleted, hidden or rewritten); `logbook doctor` counts them per source with the earliest and the
latest and warns, and `logbook doctor --implausible` lists their ids.

The range a line's `at` must fall in, from the first instant of `earliest` (UTC) up to now plus
`ahead`:

- a calendar entry (kind `event`): 1970-01-01 to now plus 5 years, so next year's holidays are fine;
- a mail (kind `mail`): 1990-01-01 to now plus 1 day;
- every other line: 1970-01-01 to now plus 1 day.

A record overrides it per source in `policy/plausible.json`, either field optional, the other kept:

    {"sources": {"ios-calendar": {"earliest": "1960-01-01", "ahead": "10y"},
                 "mail": {"ahead": "2d"}}}

`earliest` is a day, `YYYY-MM-DD`; `ahead` is a count of years or days, `5y`, `1d`. A source the
file does not name keeps the defaults; no file is the defaults. A file that is not this shape is a
`PlausibleError` naming it. Nothing here writes."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

PLAUSIBLE_FILE = PurePosixPath("policy/plausible.json")  # record-relative
AHEAD = re.compile(r"(\d+)([yd])")


class PlausibleError(ValueError):
    """`policy/plausible.json` is not the documented shape."""


@dataclass(frozen=True)
class Window:
    """From the first instant of `earliest` to now plus `years` and `days`."""

    earliest: date
    years: int = 0
    days: int = 0

    def latest(self, now: datetime) -> datetime:
        return _plus_years(now, self.years) + timedelta(days=self.days)

    def holds(self, at: datetime, now: datetime) -> bool:
        return datetime.combine(self.earliest, datetime.min.time(), tzinfo=UTC) <= at <= self.latest(now)

    def text(self, now: datetime) -> str:
        return f"{self.earliest.isoformat()} to {self.latest(now):%Y-%m-%d}"


CALENDAR = Window(date(1970, 1, 1), years=5)
MAIL = Window(date(1990, 1, 1), days=1)
OTHER = Window(date(1970, 1, 1), days=1)
BY_KIND: Mapping[str, Window] = {"event": CALENDAR, "mail": MAIL}


@dataclass(frozen=True)
class Found:
    """One line outside its window."""

    id: str
    source: str
    kind: str
    at: str


@dataclass(frozen=True)
class Count:
    """A source's lines outside their window: how many, the earliest and latest `at`."""

    source: str
    lines: int
    earliest: str
    latest: str


def path_of(root: Path) -> Path:
    return root.joinpath(*PLAUSIBLE_FILE.parts)


def overrides(root: Path) -> dict[str, dict[str, Any]]:
    """source → `{"earliest": date?, "ahead": (years, days)?}` from `policy/plausible.json`; empty
    when there is no file. Never writes it."""
    path = path_of(root)
    name = PLAUSIBLE_FILE.as_posix()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise PlausibleError(f"{name}: not readable JSON ({e})") from e
    sources = data.get("sources", {}) if isinstance(data, dict) else None
    if not isinstance(sources, dict):
        raise PlausibleError(f'{name}: expected {{"sources": {{"<source>": {{"earliest", "ahead"}}}}}}')
    out: dict[str, dict[str, Any]] = {}
    for source, entry in sources.items():
        if not isinstance(entry, dict) or set(entry) - {"earliest", "ahead"}:
            raise PlausibleError(f"{name}: {source}: expected earliest and/or ahead")
        parsed: dict[str, Any] = {}
        if "earliest" in entry:
            try:
                parsed["earliest"] = date.fromisoformat(str(entry["earliest"]))
            except ValueError as e:
                raise PlausibleError(f"{name}: {source}: earliest is not a YYYY-MM-DD day") from e
        if "ahead" in entry:
            match = AHEAD.fullmatch(str(entry["ahead"]))
            if match is None:
                raise PlausibleError(f"{name}: {source}: ahead is not a count of years or days, `5y`, `1d`")
            n = int(match.group(1))
            parsed["ahead"] = (n, 0) if match.group(2) == "y" else (0, n)
        out[str(source)] = parsed
    return out


def window(kind: str, source: str, given: Mapping[str, Mapping[str, Any]]) -> Window:
    """The window a line of `kind` from `source` must fall in: the default for its kind, with the
    record's override for its source on top."""
    base = BY_KIND.get(kind, OTHER)
    override = given.get(source)
    if not override:
        return base
    years, days = override.get("ahead", (base.years, base.days))
    return Window(override.get("earliest", base.earliest), years, days)


def find(
    rows: Iterable[tuple[str, str, str, str]], now: datetime, given: Mapping[str, Mapping[str, Any]]
) -> Iterator[Found]:
    """The lines, as (id, at, kind, source), whose `at` falls outside their window, in the order given."""
    for id_, at, kind, source in rows:
        when = _instant(at)
        if when is not None and not window(kind, source, given).holds(when, now):
            yield Found(id_, source, kind, at)


def counts(found: Iterable[Found]) -> list[Count]:
    """Per source, by name: how many, the earliest and the latest `at`."""
    by: dict[str, list[datetime]] = {}
    stamps: dict[tuple[str, datetime], str] = {}
    for f in found:
        when = _instant(f.at)
        if when is None:
            continue
        by.setdefault(f.source, []).append(when)
        stamps[(f.source, when)] = f.at
    return [
        Count(source, len(ats), stamps[(source, min(ats))], stamps[(source, max(ats))])
        for source, ats in sorted(by.items())
    ]


def rows_from_index(path: Path) -> list[tuple[str, str, str, str]]:
    """(id, at, kind, source) of every line, from an index opened read-only; closed before return."""
    db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        found = db.execute("SELECT id, at, kind, source FROM lines ORDER BY seq").fetchall()
        return [(str(id_), str(at), str(kind), str(source)) for id_, at, kind, source in found]
    finally:
        db.close()


def rows_from_lines(lines: Iterable[Mapping[str, Any]]) -> Iterator[tuple[str, str, str, str]]:
    for line in lines:
        yield str(line["id"]), str(line.get("at")), str(line.get("kind")), str(line.get("source"))


def _instant(at: str) -> datetime | None:
    try:
        when = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo is not None else when.replace(tzinfo=UTC)


def _plus_years(when: datetime, years: int) -> datetime:
    try:
        return when.replace(year=when.year + years)
    except ValueError:  # 29 February into a year without one
        return when.replace(year=when.year + years, day=28)
