"""`trips`: runs of consecutive nights away, derived from one reading of the window."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .. import flights, reading, stays, trips
from ..store import Logbook
from .common import Subparsers, _airports
from .rollup import _rollup_days


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
