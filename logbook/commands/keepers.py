"""The keepers (RFC 0024): `keepers`."""

from __future__ import annotations

import argparse
import json
import sys
from zoneinfo import ZoneInfo

from .. import keepers
from ..chain import Line
from ..export import parse_day
from ..index import Index, local_date
from ..resolve import identities_from
from ..store import Logbook
from .common import Subparsers, _clock, _plural


def keepers_arguments(sub: Subparsers) -> None:
    """`logbook keepers`."""
    s = sub.add_parser("keepers", help="the photos marked keepers (RFC 0024), by day")
    s.add_argument("--since", metavar="YYYY-MM-DD", help="from this local day")
    s.add_argument("--until", metavar="YYYY-MM-DD", help="up to this local day, inclusive")
    s.add_argument("--lane", choices=keepers.LANES, help="only this lane")
    s.add_argument(
        "--people",
        action="store_true",
        help="who appears on the keepers, per month: the faces the library named, proposed only",
    )
    s.add_argument("--json", action="store_true", help="the keepers as one JSON object")
    s.set_defaults(fn=cmd_keepers)


def cmd_keepers(a: argparse.Namespace) -> None:
    """`keepers [--since DAY] [--until DAY] [--lane memory|art] [--people] [--json]`: the keeper
    lines standing (RFC 0024), by day; with `--people`, who appears on them per month — the faces
    the library named and the people it tagged on each keeper's photo, resolved through the
    resolution lines where a name is exactly a label, every one proposed (`keepers.people_by_month`).
    Nothing is written."""
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
        if a.lane is not None:
            found = [line for line in found if (line.get("payload") or {}).get("lane") == a.lane]
        if a.people:
            _keepers_people(lb, idx, found, tz, a)
            return
    rows = [keepers.summary(line, local_date(str(line["at"]), tz)) for line in found]
    rows.sort(key=lambda r: (r["day"], r["at"], r["lane"]))
    if a.json:
        print(json.dumps({"keepers": rows}, indent=2, ensure_ascii=False))
        return
    if not rows:
        print(_no_keepers(a))
        return
    zone = ZoneInfo(tz)
    for r in rows:
        photo = r["photo"] if isinstance(r["photo"], dict) else {}
        name = photo.get("file_name") or photo.get("asset_id") or "?"
        print(f"  {r['day']}  {_clock(r['at'], zone)}  {r['lane']:<6} {r['source']:<10} {name}")


def _no_keepers(a: argparse.Namespace) -> str:
    lane = f" in lane {a.lane}" if a.lane else ""
    return f"no keepers{lane}; `logbook infer keepers` reads the marks"


def _keepers_people(lb: Logbook, idx: Index, found: list[Line], tz: str, a: argparse.Namespace) -> None:
    """`keepers --people`: the keepers' photo lines by id and the identities through the index, then
    `keepers.people_by_month`; a table by month, or `{"people": [...]}`."""
    photo_ids = {
        str(ref.get("line"))
        for line in found
        if isinstance(ref := (line.get("payload") or {}).get("photo"), dict) and ref.get("line")
    }
    photos = idx.by_ids(photo_ids)
    identities = identities_from([*idx.retractions(), *idx.resolutions()])
    rows = keepers.people_by_month(found, photos, identities, tz)
    if a.json:
        print(json.dumps({"people": rows}, indent=2, ensure_ascii=False))
        return
    if not found:
        print(_no_keepers(a))
        return
    if not rows:
        print(f"{_plural(len(found), 'keeper')}, nobody named on them")
        return
    month = None
    for r in rows:
        if r["month"] != month:
            month = r["month"]
            print(month)
        lanes = " · ".join(f"{lane} {n}" for lane, n in r["lanes"].items() if n)
        who = r["name"] if r["person"] else f"{r['name']} (no person)"
        print(f"  {who:<28} {_plural(r['keepers'], 'keeper'):>11}  {lanes:<22} {r['status']}")
