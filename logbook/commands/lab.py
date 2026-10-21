"""`logbook lab <reader>`: the readers still finding their shape (docs/labs.md), read-only."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..core import flights, reading, stays
from ..core.search import MAX_TIER
from ..core.store import Logbook
from .common import Subparsers, _airports
from .maps import lab_map_arguments
from .rollup import _rollup_days

# The defaults `lab chapters --help` names. `logbook.labs.chapters` owns them and is imported only when
# the command runs (the labs tier); a test holds these copies to it.
MIN_TRIP_NIGHTS = 21
MIN_GAP_DAYS = 7
MIN_HOME_NIGHTS = 14


def lab_arguments(sub: Subparsers) -> None:
    """`logbook lab introductions|chapters`."""
    s = sub.add_parser(
        "lab",
        help="readers still finding their shape (docs/labs.md); read-only",
        description="readers still finding their shape (docs/labs.md): introductions, chapters; read-only",
    )
    verbs = s.add_subparsers(dest="verb", required=True)
    for name, text in (
        (
            "introductions",
            "per person, the first day confirmed present with the owner and who else was there",
        ),
        ("chapters", "the record cut into chapters by home changes, gaps in the track and long trips"),
    ):
        v = verbs.add_parser(name, help=text)
        v.add_argument("--year", metavar="YYYY", help="one calendar year (default: the whole record)")
        v.add_argument("--since", metavar="YYYY-MM-DD", help="first day of a range")
        v.add_argument("--until", metavar="YYYY-MM-DD", help="last day of a range")
        v.add_argument(
            "--airports",
            metavar="FILE",
            help=f"a CSV that adds to the airports table (else {flights.AIRPORTS_ENV})",
        )
        v.add_argument("--json", action="store_true", help="one JSON object, with line ids")
        if name == "chapters":
            v.add_argument(
                "--min-trip-nights",
                type=int,
                default=MIN_TRIP_NIGHTS,
                metavar="N",
                help=f"a trip this long is a chapter of its own (default {MIN_TRIP_NIGHTS})",
            )
            v.add_argument(
                "--min-gap-days",
                type=int,
                default=MIN_GAP_DAYS,
                metavar="N",
                help=f"days without a location line that make a gap (default {MIN_GAP_DAYS})",
            )
            v.add_argument(
                "--min-home-nights",
                type=int,
                default=MIN_HOME_NIGHTS,
                metavar="N",
                help="without dates in places.json, a home place holding this many nights is the home of the"
                f" time (default {MIN_HOME_NIGHTS})",
            )
        v.set_defaults(fn=cmd_lab)
    hold_arguments(verbs)
    lab_map_arguments(verbs)


def hold_arguments(verbs: Subparsers) -> None:
    """`logbook lab hold census files|senders|drive` (docs/hold.md, RFC 0042)."""
    hold = verbs.add_parser(
        "hold",
        help="Hold v0: censuses of your files, mail senders and Drive, as a report (docs/hold.md)",
        description="Hold v0 (docs/hold.md, RFC 0042 draft): censuses written as a report under"
        " state/hold/ in the record folder; nothing is moved, renamed, deleted or appended",
    )
    census = hold.add_subparsers(dest="hold_verb", required=True).add_parser(
        "census", help="count what you hold: files, senders or drive"
    )
    kinds = census.add_subparsers(dest="census", required=True)
    for name, text in (
        (
            "files",
            "walk the folders read-only (never a link, never a system or Claude folder): types, years,"
            " duplicates by SHA-256, the 50 largest, folders untouched for two years",
        ),
        (
            "senders",
            "from the record's own mail lines: senders by count and last seen, never answered, newsletters",
        ),
        (
            "drive",
            "from the record's own Drive lines: files by type, folder and last activity, shared, trashed",
        ),
    ):
        v = kinds.add_parser(name, help=text, description=text)
        if name == "files":
            v.add_argument("paths", nargs="+", metavar="PATH", help="a folder to count; several may be given")
        else:
            v.add_argument(
                "--tier",
                type=int,
                choices=(1, 2, 3),
                default=MAX_TIER,
                help=f"read lines up to this tier (default {MAX_TIER}); the report takes the highest"
                " tier it read",
            )
        v.add_argument(
            "--json",
            action="store_true",
            help="the summary as one JSON object: counts and the report's path, no name",
        )
        v.set_defaults(fn=cmd_hold)


def cmd_lab(a: argparse.Namespace) -> None:
    """`lab introductions|chapters [--year YYYY | --since DAY --until DAY] [--json]`: the lab's readers
    (docs/labs.md), derived from one reading of the window, clipped to the days the owner's track
    covers, and never written. `introductions`: for every person, the first day the record confirms
    them present at a stay with the owner and who else was confirmed present that day. `chapters
    [--min-trip-nights N] [--min-gap-days N] [--min-home-nights N]`: the record cut into chapters
    by home-region changes, gaps in the track and long trips, as a table of contents. A lab
    reader's JSON may change between releases; neither is in SPEC §3.2."""
    from ..labs import chapters as lab_chapters
    from ..labs import introductions as lab_introductions

    lb = Logbook.find()
    try:
        window = _rollup_days(lb, a)
        if a.verb == "chapters":
            settings = lab_chapters.Settings(a.min_trip_nights, a.min_gap_days, a.min_home_nights).check()
        if window is None:
            data = lab_chapters.empty(settings) if a.verb == "chapters" else lab_introductions.empty()
        else:
            read = reading.read(lb, window[0], window[1], _airports(a.airports))
            if a.verb == "chapters":
                data = lab_chapters.chapters(read, settings)
            else:
                whole = reading.record_days(lb, "location")
                data = lab_introductions.first_seen(read, whole[0] if whole else None)
    except (ValueError, stays.SettingsError) as e:
        print(f"lab {a.verb}: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(data, indent=2))
        return
    rows = lab_chapters.rows(data) if a.verb == "chapters" else lab_introductions.rows(data)
    for text in rows:
        print(text)


def cmd_hold(a: argparse.Namespace) -> None:
    """`lab hold census files PATH… | senders | drive [--tier N] [--json]`: one census, its report written
    as Markdown and JSON under `state/hold/` in the record folder (the names it holds stay there), and
    a summary printed: counts and the report's path, never a file name or an address. Nothing in a
    walked folder is written, and no line is appended."""
    from ..labs import hold

    lb = Logbook.find()
    try:
        done = hold.run(
            lb, a.census, [Path(p) for p in getattr(a, "paths", [])], getattr(a, "tier", MAX_TIER)
        )
    except (ValueError, OSError) as e:
        print(f"lab hold census {a.census}: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(done, indent=2))
        return
    for text in hold.summary_rows(done):
        print(text)
