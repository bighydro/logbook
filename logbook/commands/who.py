"""Who was there (RFC 0043 §11, §12), the command line of `logbook.contrib.who_was_there` and
`logbook.contrib.review_with`, no new top-level command (the help is one screen, the October 2026
audit): `with --from D1 --to D2 NAME…` beside `with DAY`; `people not-with NAME --from D1 --to D2`,
`people lives-with NAME --from D [--until D]`, `people lives-in NAME CITY [--from D]` and `people city
CITY [--journey ID]` beside the other forms of `people`; `review with (--journey ID | --week YYYY-Www |
--from D1 --to D2)` beside the other queues, answered with `--accept NAME [--days D,D]` and `--not
NAME`. A refusal is one sentence on stderr, exit 2, and nothing written."""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any, NoReturn

from ..core import presence, stays
from ..core.store import Logbook

NOT_WITH, LIVES_WITH, LIVES_IN, CITY = "not-with", "lives-with", "lives-in", "city"
PEOPLE_FORMS = (NOT_WITH, LIVES_WITH, LIVES_IN, CITY)
WITH = "with"  # `review with`: the queue of a stretch, beside the kinds of `review`
REVIEW_FLAGS = (("--week", "week"), ("--days", "with_days"), ("--not", "not_with"))
STRETCH_FLAGS = (("--journey", "journey"), ("--from", "from_"), ("--to", "to"))
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")  # a word that is a day, never a name
# the options of the other forms of `people`, refused by these
PEOPLE_OTHERS = (
    ("--priority", "priority"),
    ("--year", "year"),
    ("--window", "window"),
    ("--show-prompt", "show_prompt"),
    ("--min-days", "min_days"),
    ("--quiet-days", "quiet_days"),
    ("--show", "show"),
    ("--days", "days"),
    ("--radius", "radius"),
    ("--accept", "accept"),
    ("--reject", "reject"),
    ("--all-above", "all_above"),
    ("--from-google", "from_google"),
    ("--propose", "propose"),
    ("--apply", "apply"),
    ("--export-review", "export_review"),
    ("--apply-review", "apply_review"),
)


def _refuse(prog: str, reason: str) -> NoReturn:
    print(f"{prog}: {reason}", file=sys.stderr)
    sys.exit(2)


# -- with --from D1 --to D2 ----------------------------------------------------------------------------------


def with_stretch(a: argparse.Namespace) -> None:
    """`with --from D1 --to D2 NAME…`: `who_was_there.with_stretch`."""
    from ..contrib import who_was_there

    if a.from_ is None or a.to is None:
        _refuse("with", "--from and --to go together: `logbook with --from D1 --to D2 NAME`")
    if a.at is not None:
        _refuse("with", "--at goes with one DAY; across a stretch each day is stated at its longest stay")
    if a.day is not None and DAY.match(a.day):
        _refuse("with", "a DAY or --from and --to, not both: `logbook with --from D1 --to D2 NAME`")
    names = [*([a.day] if a.day is not None else []), *a.names]
    if not names:
        _refuse("with", "name at least one person: `logbook with --from D1 --to D2 NAME`")
    try:
        found = who_was_there.with_stretch(Logbook.find(), a.from_, a.to, names)
    except (who_was_there.CompanyError, presence.WithError, ValueError, stays.SettingsError) as e:
        _refuse("with", str(e))
    _print_stated(found)


def _print_stated(found: Any) -> None:
    for day in found:
        for item in day.stated:
            if item.line is None:
                print(f"{item.name}: stated on {day.day} already; nothing written")
            else:
                print(f"#{item.line['seq']} {presence.text_of(item.name)}  {day.day} {_clock(item.line)}")


def _clock(line: Any) -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    at = datetime.fromisoformat(str(line["at"]).replace("Z", "+00:00"))
    return at.astimezone(ZoneInfo(str(line.get("tz")))).strftime("%H:%M")


# -- people not-with, lives-with, lives-in, city ------------------------------------------------------------


def people_arguments(s: argparse.ArgumentParser) -> None:
    """The options of `people not-with`, `lives-with` and `lives-in` (`--journey` is `people`'s)."""
    g = s.add_argument_group("who was there", "with `people not-with`, `lives-with`, `lives-in` and `city`")
    g.add_argument(
        "--from",
        dest="from_",
        metavar="DAY",
        help="not-with: the first day; lives-with, lives-in: since when (default today)",
    )
    g.add_argument("--to", metavar="DAY", help="not-with: the last day")
    g.add_argument(
        "--until", metavar="DAY", help="lives-with: the last day lived together; alone, it ends it"
    )


def people_form(a: argparse.Namespace) -> None:
    """`people not-with|lives-with|lives-in|city …`."""
    from ..contrib import review_with, who_was_there

    prog = f"people {a.name}"
    others = [flag for flag, dest in PEOPLE_OTHERS if getattr(a, dest, None) not in (None, False)]
    if others:
        _refuse(prog, f"{', '.join(others)}: not with `people {a.name}`")
    lb = Logbook.find()
    if a.name == CITY:
        if a.place is None or a.question is not None:
            _refuse(prog, "say the city: `logbook people city CITY [--journey ID]`")
        if a.from_ is not None or a.to is not None or a.until is not None:
            _refuse(prog, "--from, --to and --until go with not-with, lives-with and lives-in")
        try:
            data = review_with.people_in_city(lb, a.place, a.journey)
        except (who_was_there.CompanyError, ValueError, stays.SettingsError) as e:
            _refuse(prog, str(e))
        if a.json:
            print(json.dumps(data, indent=2, ensure_ascii=False))
            return
        for text in review_with.city_rows(data):
            print(text)
        return
    if a.journey is not None:
        _refuse(prog, "--journey goes with `people city` and `people nearby`")
    if a.place is None:
        _refuse(prog, f"name the person: `logbook people {a.name} NAME …`")
    try:
        if a.name == NOT_WITH:
            if a.question is not None or a.until is not None:
                _refuse(prog, "`logbook people not-with NAME --from D1 --to D2`, nothing more")
            if a.from_ is None or a.to is None:
                _refuse(prog, "say the stretch: `logbook people not-with NAME --from D1 --to D2`")
            line = who_was_there.not_with(lb, a.place, a.from_, a.to)
        elif a.name == LIVES_WITH:
            if a.question is not None or a.to is not None:
                _refuse(prog, "`logbook people lives-with NAME --from D [--until D]`, nothing more")
            line = who_was_there.lives_with(lb, a.place, a.from_, a.until)
        else:
            if a.question is None:
                _refuse(prog, "say the city: `logbook people lives-in NAME CITY [--from D]`")
            if a.to is not None or a.until is not None:
                _refuse(prog, "`logbook people lives-in NAME CITY [--from D]`, nothing more")
            line = who_was_there.lives_in(lb, a.place, a.question, a.from_)
    except who_was_there.CompanyError as e:
        _refuse(prog, str(e))
    if a.json:
        print(
            json.dumps(
                {"line": line["id"], "seq": line["seq"], "payload": line["payload"]}, ensure_ascii=False
            )
        )
        return
    print(f"#{line['seq']} note  {line['payload']['text']}")


def refuse_people_flags(a: argparse.Namespace) -> None:
    """Refuse the options of the forms above on any other `people`."""
    given = [
        flag for flag, dest in (("--from", "from_"), ("--to", "to"), ("--until", "until")) if getattr(a, dest)
    ]
    if given:
        _refuse("people", f"{', '.join(given)} go with `people not-with`, `lives-with` and `lives-in`")


# -- review with ---------------------------------------------------------------------------------------------


def review_arguments(s: argparse.ArgumentParser) -> None:
    """The options of `review with` (`--accept` and `--json` are `review`'s)."""
    g = s.add_argument_group(
        "with",
        "with `review with`: who the record puts with you over a stretch, asked once; --accept takes a NAME",
    )
    g.add_argument(
        "--journey", metavar="ID", help="the stretch of a journey: trip:YYYY-MM-DD:YYYY-MM-DD, or a day of it"
    )
    g.add_argument("--week", metavar="YYYY-Www", help="the stretch of an ISO week")
    g.add_argument("--from", dest="from_", metavar="DAY", help="the stretch's first day (with --to)")
    g.add_argument("--to", metavar="DAY", help="the stretch's last day")
    g.add_argument(
        "--days", dest="with_days", metavar="D,D", help="with --accept NAME: only these days of it"
    )
    g.add_argument(
        "--not",
        dest="not_with",
        action="append",
        metavar="NAME",
        help="not with me on any day of it: one not-with note",
    )


def refuse_review_flags(kind: str | None, a: argparse.Namespace) -> None:
    """Refuse the options of `review with` on any other `review`."""
    given = [flag for flag, dest in (*STRETCH_FLAGS, *REVIEW_FLAGS) if getattr(a, dest, None) is not None]
    if given:
        _refuse(f"review {kind}" if kind else "review", f"{', '.join(given)} go with `review with`")


def review_with(a: argparse.Namespace) -> None:
    """`review with (--journey ID | --week YYYY-Www | --from D1 --to D2) [--json]`, and its answers."""
    from ..contrib import review_with as reader
    from ..contrib import who_was_there

    prog = "review with"
    from . import review, speakers

    others = (
        *(tell for tell in review.TELLS if tell[0] != "--accept"),
        *review.TOP_FLAGS,
        *review.PLACE_FLAGS,
        *review.VIDEO_FLAGS,
        *review.GOAL_FLAGS,
        *speakers.FLAGS,
    )
    told = [flag for flag, dest in others if getattr(a, dest, None) not in (None, False)]
    if told:
        _refuse(prog, f"{', '.join(told)}: not here; answer with --accept NAME, --days D,D, --not NAME")
    accept = [name.strip() for given in a.accept or [] for name in given.split(",") if name.strip()]
    nots = [name.strip() for given in a.not_with or [] for name in given.split(",") if name.strip()]
    days = None if a.with_days is None else [d.strip() for d in a.with_days.split(",") if d.strip()]
    if days is not None and not accept:
        _refuse(prog, "--days goes with --accept NAME")
    lb = Logbook.find()
    try:
        if accept or nots:
            stretch, _rd = reader.stretch_of(lb, a.journey, a.week, a.from_, a.to, read_it=False)
            done = reader.answer(lb, stretch, accept, days, nots)
            if a.json:
                print(json.dumps(done.to_json(), indent=2, ensure_ascii=False))
                return
            for _name, found in done.stated:
                _print_stated(found)
            for line in done.not_with:
                print(f"#{line['seq']} note  {line['payload']['text']}")
            return
        queue = reader.read(lb, a.journey, a.week, a.from_, a.to)
    except (who_was_there.CompanyError, presence.WithError, ValueError, stays.SettingsError) as e:
        _refuse(prog, str(e))
    if a.json:
        print(json.dumps(queue.to_json(), indent=2, ensure_ascii=False))
        return
    for text in reader.rows(queue):
        print(text)
