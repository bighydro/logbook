"""The people the record names: `people` and `person`."""

from __future__ import annotations

import argparse
import json
import re
import sys

from .. import people, policy, reading, stays
from ..store import Logbook
from .common import Subparsers


def people_arguments(sub: Subparsers) -> None:
    """`logbook people`."""
    s = sub.add_parser(
        "people",
        help="everyone the record names, never the owner: channels, days together, last real contact",
    )
    s.add_argument("--year", metavar="YYYY", help="one year (default the whole record)")
    s.add_argument("--json", action="store_true", help="the report as one JSON object")
    s.set_defaults(fn=cmd_people)


def cmd_people(a: argparse.Namespace) -> None:
    """`people [--year YYYY] [--json]`: every person the record's resolution lines name and has
    heard from in the window, never the owner — the channels, first and last contact, days
    together, nights under one roof, places shared, birthday and last real contact — read through
    the index (`logbook.people`). The window is the whole record, or one year, clipped to the days
    the record has a line on. Nothing is written."""
    lb = Logbook.find()
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
