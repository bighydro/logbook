"""The trips: `trips` and `trip`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ..contrib import print_page, trip_page
from ..core import drafts, reading, stays, trips
from ..core.export import day_range
from ..core.store import Logbook, retractions
from .common import _airports, _print_target
from .rollup import _rollup_days


def cmd_trip(a: argparse.Namespace) -> None:
    """`trip <id-or-date> [--html PATH] [--json]`: one trip read back — the route as the stays
    slept at with their nights and the legs between them, the days from the leaving day to the
    return day one line each, the flights in and out, the people confirmed and proposed, the
    nights aboard, the keepers per day, the health of the span and the spend — from one reading
    of the days around it (`logbook.contrib.trip_page`). The trip is named by the id `trips` prints or by
    any day inside it. `--html` writes one self-contained page with an inline SVG map of the
    route. Nothing is written to the record."""
    lb = Logbook.find()
    try:
        if a.print:  # the paper edition (`logbook.contrib.print_page`), written where --html says
            out = _print_target(a, "trip")
            data = print_page.read_trip(lb, a.ref, _airports(a.airports))
            out.write_bytes(print_page.html(data).encode("utf-8"))
            print(f"trip {data['id']}: wrote {out}")
            return
        airports = _airports(a.airports)
        rd, trip = trip_page.locate(lb, trip_page.parse_ref(a.ref), airports)
        data = trip_page.compose(lb, rd, trip)
    except (ValueError, stays.SettingsError) as e:
        print(f"trip: {e}", file=sys.stderr)
        sys.exit(2)
    if a.html:
        out = Path(a.html)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(trip_page.html(data).encode("utf-8"))
        print(f"trip {data['id']}: wrote {out}")
        return
    drafted = journey_drafts(lb, [trip])[trip.id]
    if a.json:
        data.update(draft_keys(*drafted))
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    for text in trip_page.rows(data):
        print(text)
    for text in drafts.unit_rows(trip.id, *drafted):
        print(text)


def draft_keys(draft: dict[str, Any] | None, withheld: dict[str, Any] | None) -> dict[str, Any]:
    """A journey's `draft` and its `draft_withheld` row, each key there only when it has one (RFC 0036,
    as the Day carries its own), so a trip nobody dreamed is the object it always was."""
    out: dict[str, Any] = {}
    if draft is not None:
        out["draft"] = draft
    if withheld is not None:
        out["draft_withheld"] = withheld
    return out


def journey_drafts(
    lb: Logbook, found: list[trips.Trip]
) -> dict[str, tuple[dict[str, Any] | None, dict[str, Any] | None]]:
    """Each trip's standing draft (`dream journey`) and its withheld row, by the Journeys reader's
    rule (`drafts.for_unit`: the `dream` entry today), the evidence checked against the lines of its
    days, first day to return day, as the index holds them: a trip at the edge of the window read is
    checked against its whole days, never only the part of them the window holds."""
    out: dict[str, tuple[dict[str, Any] | None, dict[str, Any] | None]] = {}
    allowed = drafts.allowed(lb.root)
    with lb.index() as idx:
        retracted = frozenset(retractions(idx.retractions()))
        drafted = drafts.by_unit(idx.by_kind(drafts.KIND), retracted, drafts.UNIT_JOURNEY)
        for t in found:
            if t.id not in drafted:
                out[t.id] = (None, None)
                continue
            on = {
                str(line["id"])
                for day in day_range(t.start, t.until)
                for line in idx.day(day)
                if str(line["id"]) not in retracted
            }
            out[t.id] = drafts.for_unit(drafted[t.id], on, None, allowed, drafts.NOT_ON_JOURNEY)
    return out


def cmd_trips(a: argparse.Namespace) -> None:
    """`trips [--year YYYY | --since DAY --until DAY] [--json]`: runs of consecutive days whose
    overnight stay is outside every home region, derived from one reading of the window and
    never written (ADR 0019); each with its standing draft (`dream journey`) after the rows, `draft`
    or `draft_withheld` under `--json` when it has one."""
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
    drafted = journey_drafts(lb, found)
    if a.json:
        listed = [{**t.to_json(), **draft_keys(*drafted[t.id])} for t in found]
        out: dict[str, Any] = {"window": reading.window_json(read), "trips": listed}
        if warning:
            out["warning"] = warning
        print(json.dumps(out, indent=2))
        return
    for text in trips.rows(read, found, warning):
        print(text)
    for t in found:
        for text in drafts.unit_rows(t.id, *drafted[t.id]):
            print(text)
