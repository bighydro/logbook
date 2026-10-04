"""The trips: `trips` and `trip`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ..contrib import print_page, trip_page
from ..core import flights, reading, stays, trips
from ..core.store import Logbook
from .common import Subparsers, _airports, _print_target
from .rollup import _rollup_days


def trip_arguments(sub: Subparsers) -> None:
    """`logbook trip`."""
    s = sub.add_parser(
        "trip", help="one trip read back: the route with a map, days, flights, people, keepers, health, spend"
    )
    s.add_argument(
        "ref",
        metavar="ID-OR-DAY",
        help="a trip id as `trips` prints it (trip:YYYY-MM-DD:YYYY-MM-DD), or any day inside the trip",
    )
    s.add_argument(
        "--html",
        metavar="PATH",
        help="write one self-contained page (inline CSS and SVG map, no script) instead",
    )
    s.add_argument(
        "--print",
        action="store_true",
        help="with --html: the paper edition — a cover, contents, one spread per day, for A4 and US Letter",
    )
    s.add_argument(
        "--airports",
        metavar="FILE",
        help=f"a CSV that adds to the airports table (else {flights.AIRPORTS_ENV})",
    )
    s.add_argument("--json", action="store_true", help="the Trip as one JSON object, the days' rows inside")
    s.set_defaults(fn=cmd_trip)


def cmd_trip(a: argparse.Namespace) -> None:
    """`trip <id-or-date> [--html PATH] [--json]`: one trip read back — the route as the stays
    slept at with their nights and the legs between them, the days from the leaving day to the
    return day one line each, the flights in and out, the people confirmed and proposed, the
    nights aboard, the keepers per day, the health of the span and the spend — from one reading
    of the days around it (`logbook.trip_page`). The trip is named by the id `trips` prints or by
    any day inside it. `--html` writes one self-contained page with an inline SVG map of the
    route. Nothing is written to the record."""
    lb = Logbook.find()
    try:
        if a.print:  # the paper edition (`logbook.print_page`), written where --html says
            out = _print_target(a, "trip")
            data = print_page.read_trip(lb, a.ref, _airports(a.airports))
            out.write_bytes(print_page.html(data).encode("utf-8"))
            print(f"trip {data['id']}: wrote {out}")
            return
        data = trip_page.read(lb, a.ref, _airports(a.airports))
    except (ValueError, stays.SettingsError) as e:
        print(f"trip: {e}", file=sys.stderr)
        sys.exit(2)
    if a.html:
        out = Path(a.html)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(trip_page.html(data).encode("utf-8"))
        print(f"trip {data['id']}: wrote {out}")
        return
    if a.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    for text in trip_page.rows(data):
        print(text)


def trips_arguments(sub: Subparsers) -> None:
    """`logbook trips`."""
    s = sub.add_parser(
        "trips", help="runs of nights away from home: route, places, people, flights in and out"
    )
    s.add_argument("--year", metavar="YYYY", help="one calendar year (default: the whole record)")
    s.add_argument("--since", metavar="YYYY-MM-DD", help="first day of a range")
    s.add_argument("--until", metavar="YYYY-MM-DD", help="last day of a range")
    s.add_argument(
        "--airports",
        metavar="FILE",
        help=f"a CSV that adds to the airports table (else {flights.AIRPORTS_ENV})",
    )
    s.add_argument("--json", action="store_true", help="the trips as one JSON object, with line ids")
    s.set_defaults(fn=cmd_trips)


def cmd_trips(a: argparse.Namespace) -> None:
    """`trips [--year YYYY | --since DAY --until DAY] [--json]`: runs of consecutive days whose
    overnight stay is outside every home region, derived from one reading of the window and
    never written (ADR 0019)."""
    lb = Logbook.find()
    try:
        window = _rollup_days(lb, a)
        if window is None:
            print(
                json.dumps({"window": None, "trips": []}, indent=2)
                if a.json
                else "no trips: the record has no days"
            )
            return
        read = reading.read(lb, window[0], window[1], _airports(a.airports))
    except (ValueError, stays.SettingsError) as e:
        print(f"trips: {e}", file=sys.stderr)
        sys.exit(2)
    found, warning = trips.trips(read)
    if a.json:
        out: dict[str, Any] = {"window": reading.window_json(read), "trips": [t.to_json() for t in found]}
        if warning:
            out["warning"] = warning
        print(json.dumps(out, indent=2))
        return
    for text in trips.rows(read, found, warning):
        print(text)
