"""The people: `people` (with `people merge`) and `person`."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from ..core import people, policy, reading, stays
from ..core.store import Logbook
from .common import Subparsers, _plural

if TYPE_CHECKING:
    from .. import people_merge


def people_arguments(sub: Subparsers) -> None:
    """`logbook people`."""
    s = sub.add_parser(
        "people",
        help="everyone the record names, never the owner: channels, days together, last real contact",
    )
    s.add_argument("--year", metavar="YYYY", help="one year (default the whole record)")
    s.add_argument("--json", action="store_true", help="the report as one JSON object")
    s.set_defaults(fn=cmd_people, verb=None)
    verbs = s.add_subparsers(dest="verb", required=False)
    v = verbs.add_parser(
        "merge",
        help="the same person named twice or more: proposals with the evidence; merged only when told",
    )
    g = v.add_mutually_exclusive_group()
    g.add_argument(
        "--propose", action="store_true", help="list the proposals with their evidence (the default)"
    )
    g.add_argument(
        "--apply",
        nargs="+",
        metavar="ID",
        help="merge these proposals: one alias line per ref of a secondary",
    )
    g.add_argument(
        "--export-review", metavar="FILE", help="write the proposals as a CSV to mark, one row per secondary"
    )
    g.add_argument("--apply-review", metavar="FILE", help="merge the rows marked `yes` in a review file")
    v.add_argument(
        "--json", action="store_true", help="the proposals, or the lines written, as one JSON object"
    )
    v.set_defaults(fn=cmd_people)


def cmd_people(a: argparse.Namespace) -> None:
    """`people [--year YYYY] [--json]`: every person the record's resolution lines name and has
    heard from in the window, never the owner — the channels, first and last contact, days
    together, nights under one roof, places shared, birthday and last real contact — read through
    the index (`logbook.people`). The window is the whole record, or one year, clipped to the days
    the record has a line on. Nothing is written."""
    lb = Logbook.find()
    if a.verb == "merge":
        _people_merge(lb, a)
        return
    try:
        window = _people_window(lb, a.year)
        if window is None:
            print(json.dumps(people.empty(), indent=2) if a.json else f"no people: {_no_days(a.year)}")
            return
        report = people.read(lb, *window)
    except (ValueError, stays.SettingsError, policy.PolicyError) as e:
        print(f"people: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(report.to_json(), indent=2, ensure_ascii=False))
        return
    for text in people.rows(report):
        print(text)


def _people_merge(lb: Logbook, a: argparse.Namespace) -> None:
    """`people merge [--propose | --apply ID... | --export-review FILE | --apply-review FILE] [--json]`:
    the same person named twice or more by the resolution lines (`logbook.people_merge`), proposed
    with the evidence and never merged on its own. `--apply` and `--apply-review` append the alias
    lines (RFC 0006) through `Logbook.append`; every id or row is checked before the first one."""
    from .. import people_merge

    try:
        report = people_merge.read(lb)
        if a.apply:
            _say_merged(people_merge.apply(lb, report, a.apply), a.json)
            return
        if a.apply_review:
            rows = people_merge.read_review(Path(a.apply_review))
            applied, done = people_merge.apply_review(lb, report, rows)
            for row in done:
                print(f"row {row.line}: already merged, skipped")
            if not applied and not done:
                print(f"nothing marked in {a.apply_review}: write `yes` in `apply` on the rows to merge")
            _say_merged(applied, a.json)
            return
        if a.export_review:
            n = people_merge.export_review(report, Path(a.export_review))
            proposals = _plural(len(report.proposals), "proposal")
            count = _plural(n, "row")
            print(f"wrote {count} for {proposals} to {a.export_review}; mark `apply` and run --apply-review")
            return
    except (people_merge.MergeError, ValueError, stays.SettingsError, policy.PolicyError) as e:
        print(f"people merge: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(report.to_json(), indent=2, ensure_ascii=False))
        return
    for text in people_merge.rows(report):
        print(text)


def _say_merged(applied: list[people_merge.Applied], as_json: bool) -> None:
    from .. import people_merge

    if as_json:
        print(json.dumps({"applied": [a.to_json() for a in applied]}, indent=2, ensure_ascii=False))
        return
    for text in people_merge.applied_rows(applied):
        print(text)


def person_arguments(sub: Subparsers) -> None:
    """`logbook person`."""
    s = sub.add_parser(
        "person", help="one person's page: the numbers, then the shared days, most recent first"
    )
    s.add_argument("name", help="a name, an entity id, an email address, a phone number or kind:value")
    s.add_argument("--year", metavar="YYYY", help="one year (default the whole record)")
    s.add_argument("--json", action="store_true", help="the page as one JSON object")
    s.set_defaults(fn=cmd_person)


def cmd_person(a: argparse.Namespace) -> None:
    """`person <name-or-ref> [--year YYYY] [--json]`: one person's page — the same numbers as
    `people`, then the shared days, most recent first. The name is a label, a unique first or last
    name, an entity id, an email address, a phone number or `kind:value`. Nothing is written."""
    lb = Logbook.find()
    try:
        window = _people_window(lb, a.year)
        if window is None:
            raise ValueError(_no_days(a.year))
        report = people.read(lb, *window)
        who = people.find(a.name, report)
    except (ValueError, stays.SettingsError, policy.PolicyError) as e:
        print(f"person: {e}", file=sys.stderr)
        sys.exit(2)
    data = people.page(report, who)
    if a.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    for text in people.person_rows(data):
        print(text)


def _people_window(lb: Logbook, year: str | None) -> tuple[str, str] | None:
    """The whole record (the first to the last local day with a line of any kind), or `--year`
    clipped to it; None for an empty record or a year the record has no day in."""
    whole = reading.record_days(lb)
    if whole is None:
        return None
    if year is None:
        return whole
    if not re.fullmatch(r"\d{4}", year):
        raise ValueError(f"not a year (YYYY): {year!r}")
    first, last = max(f"{year}-01-01", whole[0]), min(f"{year}-12-31", whole[1])
    return None if last < first else (first, last)


def _no_days(year: str | None) -> str:
    return "the record has no lines" if year is None else f"the record has no days in {year}"
