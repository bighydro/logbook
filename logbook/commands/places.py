"""The named places of the record: `places`."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..core import places, reading, stays
from ..core.chain import Line
from ..core.export import parse_day
from ..core.store import Logbook
from .common import EN_DASH, Subparsers, _csv, _distance_text, _plural

if TYPE_CHECKING:
    from ..contrib.adapters.takeout import maps as takeout_maps


def _places_import_takeout(lb: Logbook, a: argparse.Namespace) -> None:
    """`places import-takeout <path> [--write]`: Google Maps' saved and starred places (the Takeout
    `Maps (your places)/` and `Saved/` folders, or one file of them) proposed as entries of
    <root>/places.json — a setting of the record, outside the chain — and written only with
    `--write`, never changing an entry already there (`logbook/contrib/adapters/takeout/places.py`)."""
    from ..contrib.adapters.takeout import places as takeout_places

    try:
        proposals = takeout_places.read(Path(a.path).expanduser())
        report = takeout_places.merge(lb.root, proposals, write=a.write)
    except FileNotFoundError as e:
        print(f"places: no such file or directory: {e}", file=sys.stderr)
        sys.exit(2)
    for p in report.new:
        print(f"  {p.name:<40} {p.lat:.4f}, {p.lon:.4f}  {p.category}")
    for p in report.existing:
        print(f"  {p.name:<40} already in {places.PLACES_FILE}")
    for p in report.without_coordinates:
        print(f"  {p.name:<40} no coordinates in the export ({p.category})")
    summary = [f"{_plural(len(report.new), 'place')} proposed"]
    if report.existing:
        summary.append(f"{len(report.existing)} already in {places.PLACES_FILE}")
    if report.without_coordinates:
        summary.append(f"{len(report.without_coordinates)} without coordinates")
    if report.written:
        print(f"wrote {_plural(len(report.new), 'place')} to {lb.root / places.PLACES_FILE}")
    elif a.write:
        print(f"{'; '.join(summary)}; nothing new to write")
    else:
        print(f"{'; '.join(summary)}; nothing written (add --write)")


def places_arguments(sub: Subparsers) -> None:
    """`logbook setup places` (`logbook places` until 0.6)."""
    s = sub.add_parser(
        "places", help="the named places of the record (places.json): list, add, name, propose, review"
    )
    verbs = s.add_subparsers(dest="verb", required=True)
    v = verbs.add_parser("list", help="one line per place")
    v.set_defaults(fn=cmd_places)
    for verb in ("add", "name"):
        v = verbs.add_parser(
            verb,
            help="add one place"
            if verb == "add"
            else "name a stay (or lat,lon) and put the naming in the record",
        )
        if verb == "name":
            v.add_argument("where", help="lat,lon or a stay id as `places propose` prints it")
        v.add_argument("name", help="what you call it")
        if verb == "add":
            v.add_argument("--lat", type=float, required=True)
            v.add_argument("--lon", type=float, required=True)
        v.add_argument("--radius", type=float, metavar="M", help="metres (default 150)")
        v.add_argument("--kind", choices=places.KINDS, help="home, asset-berth or other (default other)")
        v.add_argument("--tags", metavar="A,B", help="free text, comma-separated")
        v.set_defaults(fn=cmd_places)
    v = verbs.add_parser(
        "import-takeout", help="propose entries from Google Maps' saved and starred places (Takeout)"
    )
    v.add_argument("path", help="Takeout/, `Maps (your places)/`, `Saved/`, or one file of them")
    v.add_argument("--write", action="store_true", help="add the new entries to places.json")
    v.set_defaults(fn=cmd_places)
    v = verbs.add_parser("propose", help="unnamed stays ranked by hours, with what is near; appends nothing")
    v.add_argument("--since", metavar="YYYY-MM-DD", help="first day (default: the record's first)")
    v.add_argument("--until", metavar="YYYY-MM-DD", help="last day (default: the record's last)")
    v.add_argument("--top", type=int, metavar="N", help="only the N biggest")
    v.add_argument(
        "--write", action="store_true", help="ask for each name; accepted ones become places and a note"
    )
    v.add_argument("--json", action="store_true", help="the proposals as one JSON object")
    v.add_argument(
        "--takeout",
        metavar="PATH",
        help="Google Maps' saved places (Takeout/, `Maps (your places)/`, `Saved/` or one file) as"
        " candidates: one near an unnamed stay suggests its name; the rest are listed for `places add`",
    )
    v.set_defaults(fn=cmd_places)
    v = verbs.add_parser(
        "review",
        help="the places you return to, with the names the record already holds; accept, name or reject",
        description="The observed places (clusters of your stays), ranked by nights then hours, each"
        " proposed with the name the record's sources gave it and who said it, or a blank. Nothing is"
        " looked up and nothing leaves this machine. Nothing is written unless told; on a terminal it"
        " asks for each: y, n, or a name.",
    )
    v.add_argument("--top", type=int, metavar="N", help="only the first N")
    v.add_argument("--near", metavar="PLACE", help="only those within 5 km of a named place, or of lat,lon")
    v.add_argument(
        "--accept", action="append", metavar="N[,N]", help="write these into places.json, with their names"
    )
    v.add_argument(
        "--name",
        nargs=2,
        action="append",
        metavar=("N", "NAME"),
        help="write this one into places.json under your own name",
    )
    v.add_argument(
        "--reject", action="append", metavar="N[,N]", help="never propose this name for this spot again"
    )
    v.add_argument("--radius", type=float, metavar="M", help="metres: one spot (default 75)")
    v.add_argument("--json", action="store_true", help="the queue, or what was written, as one JSON object")
    v.set_defaults(fn=cmd_places)


def cmd_places(a: argparse.Namespace) -> None:
    """`places list|add|name|propose`: the named places of the record (`places.json`). `list` and
    `add` touch the registry only. `name` adds a place and appends one note/v1 line, "named
    <lat>,<lon> as <name>", so the naming is in the record. `propose` is a reader: the owner's
    unnamed stays of the window, grouped and ranked by hours, with the nearest known place, any
    Google Timeline visit overlapping them and a suggested name; `--write` asks for each and
    names the ones accepted (a name, Enter for the suggestion, `s` to skip, `q` to stop).
    `--takeout` adds Google Maps' saved places as candidates (`takeout.maps.candidates`): one near a
    proposal is shown under it with its list and the day it was saved and becomes the suggested
    name; the rest are listed after the proposals for `places add`. `import-takeout` proposes
    entries from Google Maps' saved places in bulk (`_places_import_takeout`). `review` is the
    observed places and the owner's say over them (`_places_review`)."""
    lb = Logbook.find()
    try:
        if a.verb == "list":
            _places_list(lb)
        elif a.verb == "add":
            place = _place_from_args(a.name, a.lat, a.lon, a.radius, a.kind, a.tags)
            places.add(lb.root, place)
            print(f"added {_place_row(place)}")
        elif a.verb == "name":
            lat, lon = places.parse_stay_id(a.where)
            _name_place(lb, _place_from_args(a.name, lat, lon, a.radius, a.kind, a.tags))
        elif a.verb == "import-takeout":
            _places_import_takeout(lb, a)
        elif a.verb == "review":
            _places_review(lb, a)
        else:
            _places_propose(lb, a)
    except (places.PlaceError, stays.SettingsError, ValueError) as e:
        print(f"places: {e}", file=sys.stderr)
        sys.exit(2)


def _place_from_args(
    name: str, lat: float, lon: float, radius: float | None, kind: str | None, tags: str | None
) -> places.Place:
    return places.Place(
        name.strip(),
        float(lat),
        float(lon),
        places.DEFAULT_RADIUS_M if radius is None else float(radius),
        kind or places.OTHER,
        tuple(_csv(tags) or ()),
    ).check()


def _places_list(lb: Logbook) -> None:
    found = places.read(lb.root)
    if not found:
        print(f"no places ({places.path_of(lb.root)}); `logbook places add` or `logbook places propose`")
        return
    for place in found:
        print(_place_row(place))


def _place_row(place: places.Place) -> str:
    parts = [
        f"{place.name:<24}",
        f"{place.lat:.4f},{place.lon:.4f}",
        f"{_number_text(place.radius_m)} m",
        place.kind,
    ]
    if place.tags:
        parts.append(", ".join(place.tags))
    return "  ".join(parts)


def _number_text(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _name_place(lb: Logbook, place: places.Place) -> Line:
    """Add the place to places.json and put the naming in the record as one note/v1 line."""
    line = places.name(lb, place)
    print(f"{places.naming_text(place.lat, place.lon, place.name)} (#{line['seq']}); {_place_row(place)}")
    return line


def _places_propose(lb: Logbook, a: argparse.Namespace) -> None:
    """The owner's unnamed stays of the window, from the index alone (`reading.owner_track`): the
    window cut in the query, the points and the evidence its own columns, no month file opened."""
    from ..contrib.adapters.takeout import maps as takeout_maps

    first, last = _reader_days(lb, a.since, a.until)
    read = reading.owner_track(lb, first, last)
    unnamed = [
        places.Stay(s.id, s.start, s.end, s.lat, s.lon, s.aboard, s.first_line, s.last_line, s.points)
        for s in read.stays
        if s.place is None and s.lat is not None and s.lon is not None
    ]
    proposals = places.propose(unnamed, read.places, read.timeline_visits)
    if a.top is not None:
        proposals = proposals[: a.top]
    saved = _saved_candidates(a.takeout) if getattr(a, "takeout", None) else []
    nearby = {p.id: takeout_maps.near(saved, p.lat, p.lon, places.GROUP_M) for p in proposals}
    if saved:  # a saved place at the stay is the better name than a timeline's semantic type
        proposals = [
            dataclasses.replace(p, suggested=nearby[p.id][0].name) if nearby[p.id] else p for p in proposals
        ]
    at_a_proposal = {c.name.casefold() for found in nearby.values() for c in found}
    named = {place.name.casefold() for place in read.places}
    elsewhere = [
        c for c in saved if c.name.casefold() not in at_a_proposal and c.name.casefold() not in named
    ]
    if a.json:
        out: dict[str, Any] = {"window": reading.window_json(read), "proposals": []}
        for p in proposals:
            row = p.to_json()
            if saved:
                row["saved"] = [c.to_json() for c in nearby[p.id]]
            out["proposals"].append(row)
        if saved:
            out["saved_elsewhere"] = [c.to_json() for c in elsewhere]
        print(json.dumps(out, indent=2))
        return
    if not proposals:
        print(f"{first} {EN_DASH} {last}: no unnamed stays")
        _say_saved_elsewhere(elsewhere)
        return
    print(f"{first} {EN_DASH} {last}: {_plural(len(proposals), 'unnamed place')}, by hours")
    for n, proposal in enumerate(proposals, 1):
        for text in _proposal_rows(n, proposal):
            print(text)
        for c in nearby[proposal.id][:3]:
            print(f"      saved: {_saved_row(c)}")
        if a.write:
            accepted = _ask_name(proposal)
            if accepted is None:
                break
            if accepted:
                _name_place(lb, places.Place(accepted, proposal.lat, proposal.lon, read.settings.radius_m))
    _say_saved_elsewhere(elsewhere)


def _saved_candidates(path: str) -> list[takeout_maps.Candidate]:
    from ..contrib.adapters.takeout import maps as takeout_maps

    try:
        return takeout_maps.candidates(Path(path).expanduser())
    except FileNotFoundError as e:
        raise ValueError(f"--takeout: no such file or directory: {e}") from e


def _saved_row(c: takeout_maps.Candidate) -> str:
    parts = [c.name, f"{c.lat:.4f},{c.lon:.4f}", c.list]
    if c.saved_at:
        parts.append(f"saved {c.saved_at}")
    if c.metres is not None:
        parts.append(f"{_distance_text(c.metres)} away")
    return " · ".join(parts)


def _say_saved_elsewhere(elsewhere: list[takeout_maps.Candidate]) -> None:
    """The saved places at no unnamed stay and not yet named: for `places add`, by hand."""
    if not elsewhere:
        return
    print(f"{_plural(len(elsewhere), 'saved place')} near no unnamed stay; `logbook places add` names one:")
    for c in elsewhere:
        print(f"      {_saved_row(c)}")


def _proposal_rows(n: int, p: places.Proposal) -> Iterator[str]:
    parts = [f"{p.hours:6.1f} h", f"{p.lat:.4f},{p.lon:.4f}", _plural(len(p.stays), "stay")]
    if p.aboard:
        parts.append(f"aboard {p.aboard}")
    if p.nearest is not None:
        parts.append(f"{_distance_text(p.nearest[1])} from {p.nearest[0].name}")
    yield f"{n:3}. {' · '.join(parts)}   {p.id}"
    details = []
    for visit in p.timeline[:3]:
        details.append(f"timeline {visit.semantic_type or 'visit'} {visit.place_id or ''}".rstrip())
    if p.suggested:
        details.append(f"suggested: {p.suggested}")
    if details:
        yield f"      {' · '.join(details)}"


def _ask_name(p: places.Proposal) -> str | None:
    """The name the captain gives a proposal: Enter for the suggestion, `s` (or Enter with none)
    to skip (empty), `q` or the end of input to stop (None)."""
    hint = f" [{p.suggested}]" if p.suggested else ""
    try:
        answer = input(f"      name{hint}, s to skip, q to stop: ").strip()
    except EOFError:
        return None
    if answer.casefold() == "q":
        return None
    if answer.casefold() == "s" or (not answer and not p.suggested):
        return ""
    return answer or p.suggested


def _places_review(lb: Logbook, a: argparse.Namespace) -> None:
    """`places review [--top N] [--near PLACE] [--accept N[,N]] [--name N NAME] [--reject N[,N]]
    [--radius M] [--json]`: the observed places at no named place, ranked and numbered, each with the
    name the record's sources gave it and the evidence (`logbook.contrib.places_review`). Nothing is
    written unless told: `--accept` and `--name` write places.json and one naming note each,
    `--reject` the pair into `state/places-review.json`; every number is checked before anything is
    written. On a terminal, with nothing told, it asks for each proposal shown."""
    from ..contrib import places_review

    radius = places_review.CLUSTER_M if a.radius is None else float(a.radius)
    if a.top is not None and a.top < 1:
        raise places_review.ReviewError(f"--top takes a number from 1, not {a.top}")
    report = places_review.read(lb, radius)
    accepted = places_review.numbers(a.accept)
    rejected = places_review.numbers(a.reject)
    named: list[tuple[int, str]] = []
    for number, text in a.name or []:
        found = places_review.numbers([number])
        if len(found) != 1:
            raise places_review.ReviewError(
                f'--name takes one number and a name: --name 3 "The cabin", not {number!r}'
            )
        named.append((found[0], text))
    told = [*accepted, *(n for n, _ in named)]
    both = sorted(set(told) & set(rejected))
    if both:
        raise places_review.ReviewError(
            f"proposal {', '.join(map(str, both))} is both accepted and rejected; say one"
        )
    twice = sorted({n for n in told if told.count(n) > 1})
    if twice:
        raise places_review.ReviewError(
            f"proposal {', '.join(map(str, twice))} is given --accept and --name, or --name twice; say one"
        )
    if told or rejected:
        chosen: list[tuple[places_review.Proposal, str | None]] = [
            (p, None) for p in places_review.pick(report, accepted)
        ]
        chosen += [
            (p, text)
            for p, (_n, text) in zip(places_review.pick(report, [n for n, _ in named]), named, strict=True)
        ]
        written = [
            *places_review.accept(lb, chosen),
            *places_review.reject(lb, places_review.pick(report, rejected)),
        ]
        if a.json:
            print(json.dumps({"written": [w.to_json() for w in written]}, indent=2, ensure_ascii=False))
            return
        for text in places_review.written_rows(written):
            print(text)
        return
    shown = places_review.near(report, a.near) if a.near else report.proposals
    if a.top is not None:
        shown = shown[: a.top]
    if a.json:
        print(json.dumps(report.to_json(shown), indent=2, ensure_ascii=False))
        return
    if shown and _on_a_tty():
        _review_on_a_tty(lb, report, shown)
        return
    for text in places_review.rows(report, shown):
        print(text)


def _on_a_tty() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _review_on_a_tty(lb: Logbook, report: Any, shown: list[Any]) -> None:
    """One proposal at a time: y accepts its name, n rejects it, anything else is the name to give
    it; Enter skips, q or the end of input stops. Each answer is written at once."""
    from ..contrib import places_review

    print(places_review.head(report))
    for p in shown:
        print(f"  {p.number}  {places_review.summary(p, report.tz)} → {p.name or places_review.BLANK}")
        print(f"      {places_review.evidence_text(p.observed.names)}")
        hint = "y to accept, n to reject, or type a name" if p.name else "type a name, or n to reject"
        while True:
            try:
                answer = input(f"      {hint}; Enter skips, q stops: ").strip()
            except EOFError:
                print()
                return
            if answer.casefold() == "q":
                return
            if not answer:
                break
            if answer.casefold() == "n":
                written = places_review.reject(lb, [p])
            elif answer.casefold() == "y" and not p.name:
                print("      no name to accept: type one, n to reject, or Enter to skip")
                continue
            else:
                try:
                    written = places_review.accept(lb, [(p, None if answer.casefold() == "y" else answer)])
                except places_review.ReviewError as e:
                    print(f"      {e}")
                    continue
            for text in places_review.written_rows(written):
                print(f"      {text}")
            break


def _reader_days(lb: Logbook, since: str | None, until: str | None) -> tuple[str, str]:
    """A reader's window: `--since` and `--until` (local days, each defaulting to the first or
    last day with a location line); a record with none is today."""
    whole = reading.record_days(lb, "location")
    today = date.today().isoformat()
    first = parse_day(since).isoformat() if since else (whole[0] if whole else today)
    last = parse_day(until).isoformat() if until else (whole[1] if whole else today)
    if last < first:
        raise ValueError(f"range runs backwards: {first} > {last}")
    return first, last
