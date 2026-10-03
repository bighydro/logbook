"""One day or a window of days read back: `show`, `day`, `digest`, `days` and `year`."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from .. import day as day_reader
from .. import days as days_reader
from .. import digest as digest_reader
from .. import flights, keepers, pages, reading, stays
from .. import year as year_reader
from ..export import parse_day
from ..resolve import Ref, labels
from ..store import RETRACTION, Logbook, retractions
from .common import Subparsers, _airports
from .rows import _day_rows


def show_arguments(sub: Subparsers) -> None:
    """`logbook show`."""
    s = sub.add_parser("show", help="one day (default today), or a page: person, asset or place")
    s.add_argument("day", nargs="?", help="YYYY-MM-DD, or person|asset|place")
    s.add_argument("name", nargs="?", help="with person|asset|place: the name, entity id or asset id")
    s.add_argument("--raw", action="store_true", help="print refs as the sources gave them, never a name")
    s.add_argument("--json", action="store_true", help="a page as one JSON object")
    s.set_defaults(fn=cmd_show)


def cmd_show(a: argparse.Namespace) -> None:
    """One local day (the owner's timezone), located through the index, read from the files,
    in time order (then chain order for the same instant). Senders, organizers and attendees
    are shown by the names the record's own resolution lines give them (RFC 0006), built once
    per call; `--raw` prints the refs as the sources gave them. Nothing is written."""
    lb = Logbook.find()
    if a.day in pages.PAGES:
        _show_page(lb, a)
        return
    if a.name is not None:
        print(f"show: {a.day!r} takes no name; a page is `show person|asset|place <name>`", file=sys.stderr)
        sys.exit(2)
    day = date.today().isoformat() if a.day in (None, "today") else a.day
    tz = ZoneInfo(lb.meta["timezone"])
    with lb.index() as idx:
        # A retraction is not an event of its own day; it shows as a marker where the line it hides was.
        rows = [line for line in idx.day(day) if line["kind"] != RETRACTION]
        retracted = retractions(idx.retractions())
        superseded = idx.superseded(flights.KIND)  # a flight another flight line replaced (RFC 0013 rule 4)
        names: dict[Ref, str] | None = None if a.raw else labels(lb, idx)
    if not rows:
        print(f"{day}: nothing logged")
        return
    rows.sort(key=lambda line: (line["at"], line["seq"]))
    print(day)
    hero = keepers.hero_row([*rows, *retracted.values()])  # RFC 0024 rule 4: the day's hero photos
    if hero:
        print(f"  {hero}")
    for text in _day_rows(rows, retracted, tz, names, superseded):
        print(text)
    note = lb.root / "notes" / day[:4] / f"{day}.md"
    if note.exists():
        print("  — note —\n" + "\n".join("  " + s for s in note.read_text(encoding="utf-8").splitlines()))


def day_arguments(sub: Subparsers) -> None:
    """`logbook day`."""
    s = sub.add_parser(
        "day", help="one day read back: nights, country, stays and moves with who and what, flights, health"
    )
    s.add_argument("day", nargs="?", metavar="YYYY-MM-DD", help="the local day (default today)")
    s.add_argument(
        "--airports",
        metavar="FILE",
        help=f"a CSV that adds to the airports table (else {flights.AIRPORTS_ENV})",
    )
    s.add_argument(
        "--json", action="store_true", help="the Day as one JSON object, every row with its line ids"
    )
    s.set_defaults(fn=cmd_day)


def cmd_day(a: argparse.Namespace) -> None:
    """`day [YYYY-MM-DD] [--json]`: the Day — the nights either side, the country, the timeline of
    stays, moves, stops and flights with what attached to each and who was there, the health
    line, the sources — read through the index from one reading of the day and the day before
    (`logbook.day`). Nothing is written, not even `policy/stays.json`."""
    lb = Logbook.find()
    day = date.today().isoformat() if a.day in (None, "today") else a.day
    try:
        data = day_reader.read(lb, day, _airports(a.airports))
    except (ValueError, stays.SettingsError) as e:
        print(f"day: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    for text in day_reader.rows(data):
        print(text)


def _today() -> str:
    """The local day, as one function so a test can pin it."""
    return date.today().isoformat()


def digest_arguments(sub: Subparsers) -> None:
    """`logbook digest`."""
    s = sub.add_parser(
        "digest",
        help="one day in 25 lines at most: where, with whom, what attached, flights, promises due, gaps,"
        " tomorrow, one question",
    )
    s.add_argument("day", nargs="?", metavar="YYYY-MM-DD", help="the local day (default today)")
    s.add_argument(
        "--airports",
        metavar="FILE",
        help=f"a CSV that adds to the airports table (else {flights.AIRPORTS_ENV})",
    )
    form = s.add_mutually_exclusive_group()
    form.add_argument("--json", action="store_true", help="the digest as one JSON object, with line ids")
    form.add_argument("--markdown", action="store_true", help="the same lines as Markdown")
    s.set_defaults(fn=cmd_digest)


def cmd_digest(a: argparse.Namespace) -> None:
    """`digest [YYYY-MM-DD] [--json | --markdown]`: the day in at most `digest.LIMIT` lines — its
    shape in three (where, with whom confirmed, what attached), the flights, the open promises due
    within the week, the usual sources with no line, tomorrow's timed calendar entries and one
    closing question the owner answers in a word (`logbook.digest`, composed from the readers).
    Nothing is written and nothing is sent: delivery is a later decision (ADR 0005)."""
    lb = Logbook.find()
    day = _today() if a.day in (None, "today") else a.day
    try:
        data = digest_reader.read(lb, day, _airports(a.airports))
    except (ValueError, stays.SettingsError) as e:
        print(f"digest: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    for text in digest_reader.markdown(data) if a.markdown else digest_reader.rows(data):
        print(text)


def days_arguments(sub: Subparsers) -> None:
    """`logbook days`."""
    s = sub.add_parser(
        "days", help="a window of days one line each: night, km moved, flights, stays, people, health, gaps"
    )
    s.add_argument("--from", dest="since", metavar="YYYY-MM-DD", help="the first day (default the record's)")
    s.add_argument("--to", dest="until", metavar="YYYY-MM-DD", help="the last day (default the record's)")
    s.add_argument(
        "--airports",
        metavar="FILE",
        help=f"a CSV that adds to the airports table (else {flights.AIRPORTS_ENV})",
    )
    s.add_argument("--json", action="store_true", help="one JSON object per line (JSON Lines)")
    s.set_defaults(fn=cmd_days)


def cmd_days(a: argparse.Namespace) -> None:
    """`days [--from DAY] [--to DAY] [--json]`: a window of the record one line per day — the
    night, the kilometres moved, the flights, the stays with what attached, the people confirmed,
    the health triple, and a gap marker for a usual source with no line that day — streamed from
    readings of the window in chunks through the index (`logbook.days`), never one per day. The
    window defaults to the days the owner's track covers. `--json` is one object per line. Nothing
    is written."""
    lb = Logbook.find()
    try:
        window = _days_window(lb, a.since, a.until)
        if window is None:
            if not a.json:
                print("no days: the record has no lines")
            return
        for r in days_reader.read(lb, window[0], window[1], _airports(a.airports)):
            print(json.dumps(r, ensure_ascii=False) if a.json else days_reader.row(r))
    except (ValueError, stays.SettingsError) as e:
        print(f"days: {e}", file=sys.stderr)
        sys.exit(2)


def year_arguments(sub: Subparsers) -> None:
    """`logbook year`."""
    s = sub.add_parser(
        "year",
        help="one year read back: countries, trips, flights, places, people, health, keepers, a day a month",
    )
    s.add_argument("year", metavar="YYYY", help="the calendar year")
    s.add_argument(
        "--html", metavar="PATH", help="write one self-contained page (inline CSS, no script) instead"
    )
    s.add_argument(
        "--airports",
        metavar="FILE",
        help=f"a CSV that adds to the airports table (else {flights.AIRPORTS_ENV})",
    )
    s.add_argument("--json", action="store_true", help="the Year as one JSON object, the picks' Days inside")
    s.set_defaults(fn=cmd_year)


def cmd_year(a: argparse.Namespace) -> None:
    """`year YYYY [--html PATH] [--json]`: the Year — days per country, nights, the trips, the
    flights, the places by nights, the people by days together, health and keepers by month, and
    twelve picks, one day a month, rendered with the day reader — composed from one reading of
    the year's days (`logbook.year`). `--html` writes one self-contained page. Nothing is written
    to the record."""
    lb = Logbook.find()
    try:
        data = year_reader.read(lb, a.year, _airports(a.airports))
    except (ValueError, stays.SettingsError) as e:
        print(f"year: {e}", file=sys.stderr)
        sys.exit(2)
    if a.html:
        out = Path(a.html)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(year_reader.html(data).encode("utf-8"))
        print(f"year {data['year']}: wrote {out}")
        return
    if a.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    for text in year_reader.rows(data):
        print(text)


def _days_window(lb: Logbook, since: str | None, until: str | None) -> tuple[str, str] | None:
    """`--from` and `--to`, each defaulting to the record's first or last day with a location line
    (else any line); None when a bound is missing and the record has no lines."""
    if since is not None and until is not None:
        return parse_day(since).isoformat(), parse_day(until).isoformat()
    whole = reading.record_days(lb, "location") or reading.record_days(lb)
    if whole is None:
        return None
    first = parse_day(since).isoformat() if since else whole[0]
    last = parse_day(until).isoformat() if until else whole[1]
    return first, last


def _show_page(lb: Logbook, a: argparse.Namespace) -> None:
    """`show person|asset|place <name> [--json]`: a page read from the whole record (the days the
    owner's track covers) through `pages`. Nothing is written."""
    if a.name is None:
        print(f"show {a.day}: say who or what, e.g. `logbook show {a.day} <name>`", file=sys.stderr)
        sys.exit(2)
    try:
        whole = reading.record_days(lb, "location") or reading.record_days(lb)
        if whole is None:
            raise pages.PageError("the record has no lines")
        read = reading.read(lb, whole[0], whole[1])
        page = {"person": pages.person, "asset": pages.asset, "place": pages.place}[a.day](read, a.name)
    except (pages.PageError, stays.SettingsError) as e:
        print(f"show {a.day}: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(page, indent=2, ensure_ascii=False))
        return
    for text in pages.rows(page):
        print(text)
