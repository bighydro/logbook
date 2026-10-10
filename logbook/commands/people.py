"""The people: `people`, `people --priority`, `people NAME` (the command `person` until 0.6), `people merge`
and `people review`."""

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
    from ..contrib import people_merge


MERGE = "merge"  # `people merge`: never a person's name
REVIEW = "review"  # `people review`: nor this
MERGE_FLAGS = ("propose", "apply", "export_review", "apply_review")
REVIEW_FLAGS = ("accept", "reject", "all_above")


def people_arguments(sub: Subparsers) -> None:
    """`logbook people [NAME|merge|review]`."""
    s = sub.add_parser(
        "people",
        help="everyone the record names; NAME: one person's page; merge; review",
        description="everyone the record names, never the owner: channels, days together, last real contact;"
        " --priority: ranked by a plain score; NAME: one person's page; merge: the same person named twice;"
        " review: who the sources saw that the record has not placed, proposed against the people it names",
    )
    s.add_argument(
        "name",
        nargs="?",
        metavar="NAME|merge|review",
        help="one person's page: a name, an entity id, an email address, a phone number or kind:value;"
        " `merge`: the same person named twice or more, proposals with the evidence, merged only when told;"
        " `review`: the observed people not yet placed, proposed against the canonical ones, numbered,"
        " accepted or rejected only when told",
    )
    s.add_argument(
        "--year", metavar="YYYY", help="one year (default the whole record; --priority: the last year)"
    )
    s.add_argument(
        "--json",
        action="store_true",
        help="the report, the page, the ranking, or merge's and review's proposals or lines written, as JSON",
    )
    s.add_argument(
        "--accept",
        action="append",
        metavar="N[,N]",
        help="review: accept these proposals: the alias lines `people merge` writes, one per identifier seen",
    )
    s.add_argument(
        "--reject",
        action="append",
        metavar="N[,N]",
        help="review: reject these proposals: one line each saying the two are not the same person",
    )
    s.add_argument(
        "--all-above", metavar="SCORE", help="review: accept every proposal at or above this score"
    )
    g = s.add_mutually_exclusive_group()
    g.add_argument(
        "--priority",
        action="store_true",
        help="rank the people by a plain score: days together, messages both ways, meetings, recency",
    )
    g.add_argument(
        "--propose", action="store_true", help="merge: list the proposals with their evidence (the default)"
    )
    g.add_argument(
        "--apply",
        nargs="+",
        metavar="ID",
        help="merge: merge these proposals: one alias line per ref of a secondary",
    )
    g.add_argument(
        "--export-review",
        metavar="FILE",
        help="merge: write the proposals as a CSV to mark, one row per secondary",
    )
    g.add_argument(
        "--apply-review", metavar="FILE", help="merge: merge the rows marked `yes` in a review file"
    )
    s.set_defaults(fn=cmd_people)


def cmd_people(a: argparse.Namespace) -> None:
    """`people [--year YYYY] [--json]`: every person the record's resolution lines name and has
    heard from in the window, never the owner — the channels, first and last contact, days
    together, nights under one roof, places shared, birthday and last real contact — read through
    the index (`logbook.core.people`). The window is the whole record, or one year, clipped to the days
    the record has a line on. Nothing is written. `people NAME` is one person's page (`cmd_person`);
    `people merge` the duplicates (`_people_merge`)."""
    if a.name == MERGE:
        _people_merge(Logbook.find(), a)
        return
    if a.name == REVIEW:
        _people_review(Logbook.find(), a)
        return
    if any(getattr(a, flag) for flag in MERGE_FLAGS):
        print(
            "people: --propose, --apply, --export-review and --apply-review go with `people merge`",
            file=sys.stderr,
        )
        sys.exit(2)
    if any(getattr(a, flag) for flag in REVIEW_FLAGS):
        print("people: --accept, --reject and --all-above go with `people review`", file=sys.stderr)
        sys.exit(2)
    if a.name is not None:
        if a.priority:
            print("people: --priority ranks everyone; it takes no NAME", file=sys.stderr)
            sys.exit(2)
        cmd_person(a)
        return
    lb = Logbook.find()
    if a.priority:
        _people_priority(lb, a)
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
    the same person named twice or more by the resolution lines (`logbook.contrib.people_merge`), proposed
    with the evidence and never merged on its own. `--apply` and `--apply-review` append the alias
    lines (RFC 0006) through `Logbook.append`; every id or row is checked before the first one."""
    from ..contrib import people_merge

    if any(getattr(a, flag) for flag in REVIEW_FLAGS):
        print("people merge: --accept, --reject and --all-above go with `people review`", file=sys.stderr)
        sys.exit(2)
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
    from ..contrib import people_merge

    if as_json:
        print(json.dumps({"applied": [a.to_json() for a in applied]}, indent=2, ensure_ascii=False))
        return
    for text in people_merge.applied_rows(applied):
        print(text)


def _people_review(lb: Logbook, a: argparse.Namespace) -> None:
    """`people review [--accept N[,N]] [--reject N[,N]] [--all-above SCORE] [--json]`: the observed
    people the record has not placed, proposed against the canonical ones, ranked by the evidence
    and numbered (`logbook.contrib.people_review`); nothing is written unless told. `--accept` and
    `--all-above` append the alias lines `people merge` writes, `--reject` one `people-review/v1`
    line per pair, all through `Logbook.append`; every number is checked before the first line."""
    from ..contrib import people_review

    if any(getattr(a, flag) for flag in MERGE_FLAGS):
        print(
            "people review: --propose, --apply, --export-review and --apply-review go with `people merge`",
            file=sys.stderr,
        )
        sys.exit(2)
    try:
        report = people_review.read(lb)
        accepted = people_review.numbers(a.accept)
        rejected = people_review.numbers(a.reject)
        both = sorted(set(accepted) & set(rejected))
        if both:
            raise people_review.ReviewError(
                f"proposal {', '.join(map(str, both))} is both accepted and rejected; say one"
            )
        if a.all_above is not None:
            accepted = [
                *accepted,
                *(p.number for p in people_review.above(report, a.all_above) if p.number not in accepted),
            ]
        if accepted or rejected:
            to_accept = people_review.pick(report, accepted)
            to_reject = people_review.pick(report, rejected)
            written = [
                *people_review.accept(lb, report, to_accept),
                *people_review.reject(lb, report, to_reject),
            ]
            if a.json:
                print(json.dumps({"written": [w.to_json() for w in written]}, indent=2, ensure_ascii=False))
                return
            if not written:
                print("nothing to write: no proposal at or above that score")
            for text in people_review.written_rows(written):
                print(text)
            return
        if a.all_above is not None:
            print("nothing to write: no proposal at or above that score")
            return
    except (people_review.ReviewError, ValueError, stays.SettingsError, policy.PolicyError) as e:
        print(f"people review: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(report.to_json(), indent=2, ensure_ascii=False))
        return
    for text in people_review.rows(report):
        print(text)


def _people_priority(lb: Logbook, a: argparse.Namespace) -> None:
    """`people --priority [--year YYYY] [--json]`: the canonical people heard in the last year (or
    the year), ranked by the plain score `logbook.contrib.people_review.score` documents. Nothing
    is written."""
    from ..contrib import people_review

    try:
        ranked = people_review.priority(lb, a.year)
    except (ValueError, stays.SettingsError, policy.PolicyError) as e:
        print(f"people: {e}", file=sys.stderr)
        sys.exit(2)
    if ranked is None:
        print(json.dumps({"window": None, "people": []}) if a.json else f"no people: {_no_days(a.year)}")
        return
    if a.json:
        print(json.dumps(ranked.to_json(), indent=2, ensure_ascii=False))
        return
    for text in people_review.priority_rows(ranked):
        print(text)


def cmd_person(a: argparse.Namespace) -> None:
    """`people <name-or-ref> [--year YYYY] [--json]` (`person` until 0.6): one person's page — the
    same numbers as `people`, then the shared days, most recent first. The name is a label, a unique
    first or last name, an entity id, an email address, a phone number or `kind:value`. Nothing is
    written."""
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
