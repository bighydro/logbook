"""`rollup countries|flights|nights|places|people|health`: the record summed up over a window."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from .. import flights, health, reading, rollup, stays
from ..chain import Line
from ..export import parse_day
from ..store import Logbook
from .common import Subparsers, _airports


def rollup_arguments(sub: Subparsers) -> None:
    """`logbook rollup`."""
    s = sub.add_parser(
        "rollup",
        help="the record per year: countries, flights, nights, places, people; per month or week: health",
    )
    s.add_argument("what", choices=rollup.KINDS, help="what to sum up")
    s.add_argument("--year", metavar="YYYY", help="one calendar year (default: the whole record)")
    s.add_argument("--since", metavar="YYYY-MM-DD", help="first day of a range")
    s.add_argument("--until", metavar="YYYY-MM-DD", help="last day of a range")
    s.add_argument(
        "--by", choices=rollup.PERIODS, help="health only: per calendar month (default) or per ISO week"
    )
    s.add_argument(
        "--airports",
        metavar="FILE",
        help=f"a CSV that adds to the airports table (else {flights.AIRPORTS_ENV})",
    )
    s.add_argument(
        "--with",
        dest="with_",
        action="store_true",
        help="places only: the place × person table — stays, days and nights at each place per person",
    )
    s.add_argument(
        "--json", action="store_true", help="the rollup as one JSON object, every number with its line ids"
    )
    s.set_defaults(fn=cmd_rollup)


def cmd_rollup(a: argparse.Namespace) -> None:
    """`rollup countries|flights|nights|places|people|health [--year YYYY | --since DAY --until DAY]
    [--by month|week] [--json]`: the record summed up per year from one reading of the window,
    clipped to the days the owner's track covers (the first to the last day with a location line;
    for flights, with any line), so a day outside them is nothing, not a night in transit; or, for
    health, per month or ISO week from the health lines of the window, clipped to the days they
    cover, with no reading of the track. Every number carries the ids of its lines under --json.
    Nothing is written."""
    lb = Logbook.find()
    try:
        if a.by and a.what != "health":
            raise ValueError("--by is for rollup health")
        if a.with_ and a.what != "places":
            raise ValueError("--with goes with `rollup places`: the place × person table")
        window = _rollup_days(lb, a)
        if window is None:
            data = rollup.empty(a.what, a.by or "month")
        elif a.what == "health":
            tz = str(lb.meta["timezone"])
            data = rollup.health(_health_window(lb, *window), tz, *window, a.by or "month")
        else:
            read = reading.read(lb, window[0], window[1], _airports(a.airports))
            data = rollup.places(read, with_table=a.with_) if a.what == "places" else ROLLUPS[a.what](read)
    except (ValueError, stays.SettingsError) as e:
        print(f"rollup: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(data, indent=2))
        return
    for text in rollup.rows(data):
        print(text)


def _health_window(lb: Logbook, first: str, last: str) -> list[Line]:
    """The health lines of `[first, last]` and of the day before (the night that ends on the first
    day starts then), through the index, with every retraction line."""
    before = (parse_day(first) - timedelta(days=1)).isoformat()
    with lb.index() as idx:
        return [*idx.by_kind(health.KIND, before, last), *idx.retractions()]


ROLLUPS: dict[str, Callable[[reading.Reading], dict[str, Any]]] = {
    "countries": rollup.countries,
    "flights": rollup.flights,
    "nights": rollup.nights,
    "places": rollup.places,
    "people": rollup.people,
}


def _rollup_days(lb: Logbook, a: argparse.Namespace) -> tuple[str, str] | None:
    """The window of a rollup: `--year`, or `--since`/`--until`, each clipped to the record's
    first and last day; None for an empty record or a window the record has no day in."""
    if a.year and (a.since or a.until):
        raise ValueError("give --year, or --since and --until, not both")
    what = str(getattr(a, "what", None) or "")
    whole = reading.record_days(lb, {"flights": None, "health": health.KIND}.get(what, "location"))
    if whole is None:
        return None
    if a.year:
        if not re.fullmatch(r"\d{4}", a.year):
            raise ValueError(f"not a year (YYYY): {a.year!r}")
        since, until = f"{a.year}-01-01", f"{a.year}-12-31"
    else:
        since = parse_day(a.since).isoformat() if a.since else whole[0]
        until = parse_day(a.until).isoformat() if a.until else whole[1]
    first, last = max(since, whole[0]), min(until, whole[1])
    if last < first:
        return None if a.year or since > whole[1] or until < whole[0] else _raise_backwards(since, until)
    return first, last


def _raise_backwards(since: str, until: str) -> tuple[str, str]:
    raise ValueError(f"range runs backwards: {since} > {until}")
