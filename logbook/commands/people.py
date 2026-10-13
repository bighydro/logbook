"""The people: `people`, `people --priority`, `people NAME` (the command `person` until 0.6), `people merge`,
`people review`, `people drift` and `people nearby`."""

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
    from ..contrib import google_contacts, people_merge


MERGE = "merge"  # `people merge`: never a person's name
REVIEW = "review"  # `people review`: nor this
DRIFT = "drift"  # `people drift`
NEARBY = "nearby"  # `people nearby`
MERGE_FLAGS = ("propose", "apply", "export_review", "apply_review")
REVIEW_FLAGS = ("accept", "reject", "all_above", "from_google")
DRIFT_FLAGS = ("min_days", "quiet_days", "show")
NEARBY_FLAGS = ("journey", "days", "radius")


def people_arguments(sub: Subparsers) -> None:
    """`logbook people [NAME|merge|review]`."""
    s = sub.add_parser(
        "people",
        help="everyone the record names; NAME, merge, review, drift, nearby",
        description="everyone the record names, never the owner: channels, days together, last real contact;"
        " --priority: ranked by a plain score; NAME: one person's page; merge: the same person named twice;"
        " review: who the sources saw that the record has not placed, proposed against the people it names;"
        " drift: who you used to see and have drifted from; nearby PLACE: who has been seen where you go",
    )
    s.add_argument(
        "name",
        nargs="?",
        metavar="NAME|merge|review|drift|nearby",
        help="one person's page: a name, an entity id, an email address, a phone number or kind:value;"
        " `merge`: the same person named twice or more, proposals with the evidence, merged only when told;"
        " `review`: the observed people not yet placed, proposed against the canonical ones, numbered,"
        " accepted or rejected only when told; `drift`: many days together in a year, no real contact"
        " for long; `nearby PLACE`: the people seen at or near a place",
    )
    s.add_argument(
        "place",
        nargs="?",
        metavar="PLACE",
        help="nearby: lat,lon, a name of places.json, a city of the airports table, or an airport code",
    )
    s.add_argument(
        "--year",
        metavar="YYYY",
        help="one year (default the whole record; --priority: the last year; drift: the year the days"
        " together are counted in)",
    )
    s.add_argument(
        "--min-days",
        type=int,
        metavar="N",
        help=f"drift: at least N days together in one year (default {people_drift_default('min')})",
    )
    s.add_argument(
        "--quiet-days",
        type=int,
        metavar="M",
        help=f"drift: no real contact in more than M days (default {people_drift_default('quiet')})",
    )
    s.add_argument(
        "--show", action="store_true", help="drift: the days together of each, with where; never a word"
    )
    s.add_argument("--journey", metavar="ID", help="nearby: where this journey or flight line goes")
    s.add_argument(
        "--days",
        nargs=2,
        metavar=("FROM", "TO"),
        help="nearby: the places planned on these days: located calendar entries, flights, journeys",
    )
    s.add_argument(
        "--radius",
        type=float,
        metavar="KM",
        help=f"nearby: how near a stay must be to the place (default {people_drift_default('radius')} km)",
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
    s.add_argument(
        "--from-google",
        action="store_true",
        help="review: your Google contacts and other contacts as a name source, read with the one Google key"
        " (LOGBOOK_DRIVE_SA_KEY, LOGBOOK_DRIVE_USER): evidence for a pair, a name for a new person, and the"
        " contacts that share an address or a number; never a line of them; kept 24 h in"
        " state/google-contacts.json; give it with --accept and --reject too",
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
    if a.place is not None and a.name != NEARBY:
        print(f"people: {a.place!r}: a second word goes with `people nearby PLACE` only", file=sys.stderr)
        sys.exit(2)
    if a.name == MERGE:
        _people_merge(Logbook.find(), a)
        return
    if a.name == REVIEW:
        _people_review(Logbook.find(), a)
        return
    if a.name == NEARBY:
        _people_nearby(Logbook.find(), a)
        return
    if any(getattr(a, flag) is not None for flag in NEARBY_FLAGS):
        print("people: --journey, --days and --radius go with `people nearby`", file=sys.stderr)
        sys.exit(2)
    if a.name == DRIFT:
        _people_drift(Logbook.find(), a)
        return
    if any(getattr(a, flag) not in (None, False) for flag in DRIFT_FLAGS):
        print("people: --min-days, --quiet-days and --show go with `people drift`", file=sys.stderr)
        sys.exit(2)
    if any(getattr(a, flag) for flag in MERGE_FLAGS):
        print(
            "people: --propose, --apply, --export-review and --apply-review go with `people merge`",
            file=sys.stderr,
        )
        sys.exit(2)
    if any(getattr(a, flag) for flag in REVIEW_FLAGS):
        print(
            "people: --accept, --reject, --all-above and --from-google go with `people review`",
            file=sys.stderr,
        )
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
        print(
            "people merge: --accept, --reject, --all-above and --from-google go with `people review`",
            file=sys.stderr,
        )
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
    """`people review [--from-google] [--accept N[,N]] [--reject N[,N]] [--all-above SCORE] [--json]`:
    the observed people the record has not placed, proposed against the canonical ones, ranked by the
    evidence and numbered (`logbook.contrib.people_review`); nothing is written unless told. `--accept`
    and `--all-above` append the alias lines `people merge` writes, `--reject` one `people-review/v1`
    line per pair, all through `Logbook.append`; every number is checked before the first line. With
    `--from-google` the owner's Google contacts are a name source too (`logbook.contrib.google_contacts`):
    read on the one Google key, or from the cache in state/ within its TTL, never a line of them."""
    from ..contrib import people_review

    if any(getattr(a, flag) for flag in MERGE_FLAGS):
        print(
            "people review: --propose, --apply, --export-review and --apply-review go with `people merge`",
            file=sys.stderr,
        )
        sys.exit(2)
    book = _google_contacts(lb) if a.from_google else None
    try:
        report = people_review.read(lb, book)
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


def _google_contacts(lb: Logbook) -> google_contacts.Book:
    """The owner's Google contacts for `people review --from-google`: the cache within its TTL, else read
    on the one Google key. Exit 2 when the key is not set or not good, 1 when Google cannot be read; a
    book whose scope is not delegated is said on stderr and left out."""
    import os

    from ..contrib import google_contacts
    from ..contrib.adapters import service_account

    try:
        account = service_account.configure(os.environ)
    except ValueError as e:
        print(f"people review: --from-google: {e}", file=sys.stderr)
        sys.exit(2)
    if account is None:
        print(f"people review: --from-google: set {' and '.join(service_account.ENV)}", file=sys.stderr)
        sys.exit(2)
    try:
        book = google_contacts.load(lb.root, account)
    except OSError as e:  # service_account.GoogleError is one
        print(f"people review: --from-google: {e}", file=sys.stderr)
        sys.exit(1)
    for name in book.refused:
        print(
            f"people review: --from-google: {name} not read; the delegation does not grant"
            f" {service_account.SCOPES[name]}",
            file=sys.stderr,
        )
    return book


def people_drift_default(what: str) -> str:
    """The defaults the help names, without importing the readers at parser time."""
    return {"min": "20", "quiet": "365", "radius": "50"}[what]


def _people_drift(lb: Logbook, a: argparse.Namespace) -> None:
    """`people drift [--min-days N] [--quiet-days M] [--year YYYY] [--show] [--json]`: the canonical
    people with at least N days together in one year whose last real contact is more than M days
    ago (`logbook.contrib.people_drift`), most days together first. Nothing is written."""
    from ..contrib import people_drift

    if a.priority:
        print("people drift: --priority ranks everyone; drift is its own list", file=sys.stderr)
        sys.exit(2)
    try:
        found = people_drift.drift(
            lb,
            people_drift.DEFAULT_MIN_DAYS if a.min_days is None else a.min_days,
            people_drift.DEFAULT_QUIET_DAYS if a.quiet_days is None else a.quiet_days,
            a.year,
        )
    except (ValueError, stays.SettingsError, policy.PolicyError) as e:
        print(f"people drift: {e}", file=sys.stderr)
        sys.exit(2)
    if found is None:
        print(json.dumps({"window": None, "people": []}) if a.json else "no people: the record has no lines")
        return
    if a.json:
        print(json.dumps(found.to_json(a.show), indent=2, ensure_ascii=False))
        return
    for text in people_drift.drift_rows(found, a.show):
        print(text)


def _people_nearby(lb: Logbook, a: argparse.Namespace) -> None:
    """`people nearby PLACE | --journey ID | --days FROM TO [--radius KM] [--json]`: the canonical
    people seen at or near a place, or at each place the owner has planned on those days
    (`logbook.contrib.people_nearby`), with their last contact. Nothing is written."""
    from ..contrib import people_nearby
    from ..core.export import parse_day
    from ..core.flights import Airports

    asked = [x for x in (a.place, a.journey, a.days) if x is not None]
    if len(asked) != 1:
        print("people nearby: say one of PLACE, --journey ID or --days FROM TO", file=sys.stderr)
        sys.exit(2)
    if a.priority or any(getattr(a, flag) not in (None, False) for flag in DRIFT_FLAGS):
        print(
            "people nearby: --priority, --min-days, --quiet-days and --show do not go with it",
            file=sys.stderr,
        )
        sys.exit(2)
    radius = people_nearby.DEFAULT_RADIUS_KM if a.radius is None else a.radius
    try:
        airports = Airports.load()
        known = stays.read_places(lb.root, stays.read_settings(lb.root).radius_m)
        span = None
        unplaced: list[dict[str, object]] = []
        if a.place is not None:
            targets = [people_nearby.place(a.place, known, airports)]
        elif a.journey is not None:
            targets = [people_nearby.journey(lb, a.journey, known, airports)]
        else:
            span = (parse_day(a.days[0]).isoformat(), parse_day(a.days[1]).isoformat())
            targets, unplaced = people_nearby.planned(lb, *span, known, airports, radius)
        found = people_nearby.nearby(lb, targets, radius, airports, span, unplaced)
    except (ValueError, stays.SettingsError, policy.PolicyError) as e:
        print(f"people nearby: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(found.to_json(), indent=2, ensure_ascii=False))
        return
    for text in people_nearby.rows(found):
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
