"""`keepers`: the photos marked keepers (RFC 0024), by day."""

from __future__ import annotations

import argparse
import json
import sys
from zoneinfo import ZoneInfo

from .. import keepers
from ..export import parse_day
from ..index import local_date
from ..store import Logbook
from .common import Subparsers, _clock


def keepers_arguments(sub: Subparsers) -> None:
    """`logbook keepers`."""
    s = sub.add_parser("keepers", help="the photos marked keepers (RFC 0024), by day")
    s.add_argument("--since", metavar="YYYY-MM-DD", help="from this local day")
    s.add_argument("--until", metavar="YYYY-MM-DD", help="up to this local day, inclusive")
    s.add_argument("--lane", choices=keepers.LANES, help="only this lane")
    s.add_argument("--json", action="store_true", help="the keepers as one JSON object")
    s.set_defaults(fn=cmd_keepers)


def cmd_keepers(a: argparse.Namespace) -> None:
    """`keepers [--since DAY] [--until DAY] [--lane memory|art] [--json]`: the keeper lines
    standing (RFC 0024), by day. Nothing is written."""
    lb = Logbook.find()
    for day in (a.since, a.until):
        if day is not None:
            try:
                parse_day(day)
            except ValueError as e:
                print(f"keepers: {e}", file=sys.stderr)
                sys.exit(2)
    tz = str(lb.meta["timezone"])
    with lb.index() as idx:
        found = keepers.standing([*idx.by_kind(keepers.KIND, a.since, a.until), *idx.retractions()])
    rows = [
        keepers.summary(line, local_date(str(line["at"]), tz))
        for line in found
        if a.lane is None or (line.get("payload") or {}).get("lane") == a.lane
    ]
    rows.sort(key=lambda r: (r["day"], r["at"], r["lane"]))
    if a.json:
        print(json.dumps({"keepers": rows}, indent=2, ensure_ascii=False))
        return
    if not rows:
        print(
            "no keepers"
            + (f" in lane {a.lane}" if a.lane else "")
            + "; `logbook infer keepers` reads the marks"
        )
        return
    zone = ZoneInfo(tz)
    for r in rows:
        photo = r["photo"] if isinstance(r["photo"], dict) else {}
        name = photo.get("file_name") or photo.get("asset_id") or "?"
        print(f"  {r['day']}  {_clock(r['at'], zone)}  {r['lane']:<6} {r['source']:<10} {name}")
