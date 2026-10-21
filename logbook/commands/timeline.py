"""`logbook show timeline [--day D | --week W | --month M | --year Y | --life] [--json]`: the timeline the
Library's `/timeline` shows, as text or as one JSON object (`logbook.core.moments`, RFC 0043 §11-12).

A reader of `show`, as `show year` and `show trips` are: `show` lends it its `--year` and `--json` and
takes the other three zooms' options from here (`timeline_arguments`). Without a zoom, the day the owner
is in. The JSON is the object the page is drawn from, so the two never say different things. Nothing
is written and no connection is opened."""

from __future__ import annotations

import argparse
import json
import sys

WHAT = "timeline"


def timeline_arguments(s: argparse.ArgumentParser) -> None:
    """The timeline's zooms on `show`'s parser (its `--year` is shared with the year and trips)."""
    s.add_argument(
        "--day", dest="timeline_day", metavar="YYYY-MM-DD", help="timeline: one day (default: today)"
    )
    s.add_argument("--week", metavar="YYYY-Www", help="timeline: one ISO week, a line per day")
    s.add_argument("--month", metavar="YYYY-MM", help="timeline: one month, a calendar of its nights")
    s.add_argument(
        "--life", action="store_true", help="timeline: all years, per place and per vessel, names only"
    )


def cmd_timeline(a: argparse.Namespace) -> None:
    """`show timeline`: one zoom, read and printed; two zooms at once, or a key that is not one, exit 2
    and say so."""
    from ..contrib import gaps
    from ..core import day_start, moments, places, stays
    from ..core.store import Logbook

    asked = [
        (zoom, value)
        for zoom, value in (
            ("day", a.timeline_day),
            ("week", a.week),
            ("month", a.month),
            ("year", a.year),
        )
        if value
    ] + ([("life", None)] if a.life else [])
    if len(asked) > 1:
        print("show timeline: one zoom at a time: --day, --week, --month, --year or --life", file=sys.stderr)
        sys.exit(2)
    if a.name is not None:
        print("show timeline: takes no name; the zoom is an option, e.g. --week 2026-W24", file=sys.stderr)
        sys.exit(2)
    lb = Logbook.find()
    try:
        zoom, key = asked[0] if asked else ("day", day_start.of(lb.meta).today(gaps.now()).isoformat())
        data = moments.read(lb, zoom, key)
    except (ValueError, stays.SettingsError, places.PlaceError, day_start.DayStartError) as e:
        print(f"show timeline: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    for row in moments.rows(data):
        print(row)
