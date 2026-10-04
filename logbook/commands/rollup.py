"""The record summed up: `rollup` and `ledger`."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from ..core import apps, drifting, flights, health, ledger, listen_rollup, reading, rollup, stays
from ..core.chain import Line
from ..core.export import parse_day
from ..core.store import Logbook
from .common import Subparsers, _airports

LEDGER = "ledger"  # `rollup ledger`: the command `ledger` until 0.6


def rollup_arguments(sub: Subparsers) -> None:
    """`logbook rollup`."""
    s = sub.add_parser(
        "rollup",
        help="the record per year: countries, flights, nights, places, people, listen, attention (hours by"
        " app and category), money; per month or week: health, attention; ledger: the transactions in"
        " context",
    )
    s.add_argument(
        "what",
        choices=(*rollup.KINDS, listen_rollup.KIND, LEDGER),
        help="what to sum up; ledger: the transactions at the stay, in the trip, per day; shares per person",
    )
    s.add_argument(
        "--month",
        metavar="YYYY-MM",
        help="ledger: one calendar month (default: every day with a transaction)",
    )
    s.add_argument(
        "--trip", metavar="ID", help="ledger: one trip's days, by the id `show trips --json` prints"
    )
    s.add_argument("--year", metavar="YYYY", help="one calendar year (default: the whole record)")
    s.add_argument("--since", metavar="YYYY-MM-DD", help="first day of a range")
    s.add_argument("--until", metavar="YYYY-MM-DD", help="last day of a range")
    s.add_argument(
        "--by",
        choices=rollup.PERIODS,
        help="health and attention: per calendar month (health's default) or per ISO week; attention is"
        " per year without it",
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
        "--drifting",
        action="store_true",
        help="people only: whose contact frequency fell most, the last --window days against the same"
        " number of days before them, with days since the last real contact, the channels that went"
        " quiet and the last shared place",
    )
    s.add_argument(
        "--window",
        type=int,
        metavar="DAYS",
        help=f"--drifting: the length of each window in days (default {drifting.DEFAULT_WINDOW}); the"
        " recent one ends on --until, else on the record's last day",
    )
    s.add_argument(
        "--min-contacts",
        type=int,
        metavar="N",
        help="--drifting: list only people with at least this many contacts in the earlier window"
        f" (default {drifting.DEFAULT_MIN_CONTACTS})",
    )
    s.add_argument(
        "--json", action="store_true", help="the rollup as one JSON object, every number with its line ids"
    )
    s.set_defaults(fn=cmd_rollup)


def cmd_rollup(a: argparse.Namespace) -> None:
    """`rollup countries|flights|nights|places|people|health|listen [--year YYYY | --since DAY
    --until DAY] [--by month|week] [--json]`: the record summed up per year from one reading of the window,
    clipped to the days the owner's track covers (the first to the last day with a location line;
    for flights, with any line), so a day outside them is nothing, not a night in transit; or, for
    health, per month or ISO week from the health lines of the window, clipped to the days they
    cover, with no reading of the track; or, for listen, per year with the months inside it from
    the listen lines of the window (`listen_rollup`), the same way; or, for `people --drifting
    [--until DAY] [--window N] [--min-contacts N]`, the people whose contact frequency fell most
    between the last N days and the N before them (`drifting`). Every number carries the ids of
    its lines under --json. Nothing is written. `rollup ledger` is `cmd_ledger`."""
    if a.what == LEDGER:
        cmd_ledger(a)
        return
    lb = Logbook.find()
    try:
        if a.by and a.what not in ("health", "attention"):
            raise ValueError("--by is for rollup health and rollup attention")
        if a.with_ and a.what != "places":
            raise ValueError("--with goes with `rollup places`: the place × person table")
        if a.drifting and a.what != "people":
            raise ValueError("--drifting goes with `rollup people`: whose contact frequency fell")
        if (a.window is not None or a.min_contacts is not None) and not a.drifting:
            raise ValueError("--window and --min-contacts go with --drifting")
        window = None if a.drifting else _rollup_days(lb, a)
        if a.drifting:
            data = _drifting(lb, a)
        elif window is None:
            data = listen_rollup.empty() if a.what == "listen" else rollup.empty(a.what, a.by)
        elif a.what == "health":
            tz = str(lb.meta["timezone"])
            data = rollup.health(_health_window(lb, *window), tz, *window, a.by or "month")
        elif a.what == "listen":
            data = listen_rollup.listen(_listen_window(lb, *window), str(lb.meta["timezone"]), *window)
        elif a.what == "attention":
            tz = str(lb.meta["timezone"])
            data = rollup.attention(
                _kind_window(lb, apps.KIND, *window), tz, *window, a.by, apps.read(lb.root)
            )
        else:
            read = reading.read(lb, window[0], window[1], _airports(a.airports))
            data = rollup.places(read, with_table=a.with_) if a.what == "places" else ROLLUPS[a.what](read)
    except (ValueError, stays.SettingsError) as e:
        print(f"rollup: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(data, indent=2))
        return
    text_rows = drifting.rows if a.drifting else listen_rollup.rows if a.what == "listen" else rollup.rows
    for text in text_rows(data):
        print(text)


def _drifting(lb: Logbook, a: argparse.Namespace) -> dict[str, Any]:
    """`rollup people --drifting`: the recent window is `--window` days (365) ending on `--until`,
    the record's last day with a line of any kind by default; the earlier window the same number of
    days before it. `--year` and `--since` do not apply: the window is a length, not a range."""
    if a.year or a.since:
        raise ValueError("--drifting takes --until and --window, not --year or --since")
    whole = reading.record_days(lb)
    if whole is None:
        return drifting.empty()
    until = parse_day(a.until).isoformat() if a.until else whole[1]
    return drifting.read(
        lb,
        until,
        drifting.DEFAULT_WINDOW if a.window is None else a.window,
        drifting.DEFAULT_MIN_CONTACTS if a.min_contacts is None else a.min_contacts,
        _airports(a.airports),
        record_first=whole[0],
    )


def _listen_window(lb: Logbook, first: str, last: str) -> list[Line]:
    """The listen lines whose local day is in `[first, last]`, through the index, with every
    retraction line."""
    with lb.index() as idx:
        return [*idx.by_kind(listen_rollup.KIND, first, last), *idx.retractions()]


def _health_window(lb: Logbook, first: str, last: str) -> list[Line]:
    """The health lines of `[first, last]` and of the day before (the night that ends on the first
    day starts then), through the index, with every retraction line."""
    before = (parse_day(first) - timedelta(days=1)).isoformat()
    with lb.index() as idx:
        return [*idx.by_kind(health.KIND, before, last), *idx.retractions()]


def _kind_window(lb: Logbook, kind: str, first: str, last: str) -> list[Line]:
    """The lines of one kind whose local day is in `[first, last]`, through the index, with every
    retraction line (a retraction applies wherever its line is)."""
    with lb.index() as idx:
        return [*idx.by_kind(kind, first, last), *idx.retractions()]


ROLLUPS: dict[str, Callable[[reading.Reading], dict[str, Any]]] = {
    "countries": rollup.countries,
    "flights": rollup.flights,
    "nights": rollup.nights,
    "places": rollup.places,
    "people": rollup.people,
    "money": ledger.rollup,
}


def _rollup_days(lb: Logbook, a: argparse.Namespace) -> tuple[str, str] | None:
    """The window of a rollup: `--year`, or `--since`/`--until`, each clipped to the record's
    first and last day; None for an empty record or a window the record has no day in."""
    if a.year and (a.since or a.until):
        raise ValueError("give --year, or --since and --until, not both")
    what = str(getattr(a, "what", None) or "")
    kinds = {
        "flights": None,
        "health": health.KIND,
        "listen": listen_rollup.KIND,
        "attention": apps.KIND,
        "money": ledger.KIND,
    }
    whole = reading.record_days(lb, kinds.get(what, "location"))
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


def cmd_ledger(a: argparse.Namespace) -> None:
    """`rollup ledger [--month YYYY-MM | --trip ID] [--json]` (`ledger` until 0.6): the transaction
    lines (tier 3) of the window
    in context — each at the stay the owner was in, in its trip, per day, a shared expense's shares
    per person — from one reading of the window through the index (`logbook.core.ledger`). The window
    is the days the record has a transaction on, one month of them, or one trip's days (its first
    day to the return day). Amounts in the line's currency, nothing converted; nothing is written."""
    lb = Logbook.find()
    try:
        if a.month and a.trip:
            raise ValueError("give --month, or --trip, not both")
        window = _ledger_days(lb, a.month, a.trip)
        if window is None:
            data = ledger.empty()
        else:
            read = reading.read(lb, window[0], window[1], _airports(a.airports))
            book = ledger.ledger(read)
            if a.trip and a.trip not in {t.id for t in book.trips}:
                raise ValueError(f"no trip {a.trip}: no run of nights away from home has that id")
            data = book.to_json()
    except (ValueError, stays.SettingsError) as e:
        print(f"ledger: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    for text in ledger.rows(data):
        print(text)


def _ledger_days(lb: Logbook, month: str | None, trip: str | None) -> tuple[str, str] | None:
    """The ledger's window: the days the record has a transaction on; `--month` clipped to them;
    `--trip` the trip's days, its first to the return day (`trip:<start>:<end>`). None when the
    record has no transaction in it."""
    whole = reading.record_days(lb, ledger.KIND)
    if trip:
        found = re.fullmatch(r"trip:(\d{4}-\d{2}-\d{2}):(\d{4}-\d{2}-\d{2})", trip)
        if not found:
            raise ValueError(
                f"not a trip id (trip:YYYY-MM-DD:YYYY-MM-DD, as `trips --json` prints it): {trip!r}"
            )
        start, end = parse_day(found.group(1)), parse_day(found.group(2))
        if end < start:
            raise ValueError(f"range runs backwards: {start} > {end}")
        return start.isoformat(), (end + timedelta(days=1)).isoformat()
    if whole is None:
        return None
    if month:
        if not re.fullmatch(r"\d{4}-\d{2}", month) or not 1 <= int(month[5:]) <= 12:
            raise ValueError(f"not a month (YYYY-MM): {month!r}")
        first_day = date.fromisoformat(f"{month}-01")
        last_day = (first_day.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        first, last = max(first_day.isoformat(), whole[0]), min(last_day.isoformat(), whole[1])
        return None if last < first else (first, last)
    return whole
