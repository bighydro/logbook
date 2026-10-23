"""The record read back a day at a time: `show`, `day`, `digest`, `questions`, `days`, `year` and
`search`."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from ..contrib import digest as digest_reader
from ..contrib import (
    dream_events,
    dream_week,
    gaps,
    people_drift,
    print_layout,
    print_page,
    questions,
    reflect,
    sign_again,
    week_paper,
    year_poster,
)
from ..contrib import keep as keep_sign
from ..core import (
    chapter,
    day_start,
    drafts,
    flights,
    goals,
    keepers,
    notes,
    pages,
    policy,
    reading,
    search,
    signing,
    stays,
)
from ..core import day as day_reader
from ..core import days as days_reader
from ..core import year as year_reader
from ..core.chain import Line
from ..core.export import parse_day
from ..core.resolve import Ref, labels
from ..core.store import RETRACTION, Logbook, retractions
from .common import Subparsers, _airports, _clock, _csv, _print_target, _under_home
from .derive import TRANSCRIBE_DEFAULT_MODEL
from .rows import _day_rows, _line_row, _line_text, by_photo

if TYPE_CHECKING:
    from ..contrib import serve

HEARD = "heard"  # RFC 0046: what the podcasts and videos you played said (`commands.heard`)
READERS = ("year", "trip", "trips", "days", "keepers", "stats")  # commands of their own until 0.6
ORGS = ("org", "orgs")  # RFC 0037: one org's page, and the orgs (the Manifest's text)
IDEAS = ("idea", "ideas")  # RFC 0037: one idea's page, and the ideas (the Ideas shelf's text)
PLAN = "plan"  # RFC 0043 §9: the plan `sync notion` wrote, read and never run (`commands.plan`)


def show_arguments(sub: Subparsers) -> None:
    """`logbook show`: one day's lines, a page, or one of the readers that were commands of their own
    until 0.6 (`show year`, `show trip`, `show trips`, `show days`, `show keepers`, `show stats`)."""
    s = sub.add_parser(
        "show",
        help="one day, a page; year, trip(s), days, keepers, stats, orgs, ideas",
        description="one day's lines (default today), a page (person, asset, place, org, idea), or a reader:"
        " heard (what the podcasts and videos you played said: --day, or --since and --until, the last"
        " 14 days without), year, trip, trips, days, keepers, stats, orgs (the orgs you named under their"
        " status, the most"
        " recent touch first, stale ones said; the passed with their reasons; the people with more than one"
        " org), ideas (the ideas you named by stage, the most recent touch first, each with its reason),"
        " plan (today's tasks, the sprint and the next trip, from `sync notion`'s tier-1 lines)",
    )
    s.add_argument(
        "day",
        nargs="?",
        metavar="WHAT",
        help="YYYY-MM-DD or today; person|asset|place|org|idea NAME; year YYYY; trip ID-OR-DAY; trips; days;"
        " keepers; stats; orgs; ideas; plan [DAY]",
    )
    s.add_argument(
        "name",
        nargs="?",
        metavar="NAME",
        help="with person|asset|place: the name, entity id or asset id; with org: its name, a word of it,"
        " a domain or its id; with idea: its name, a word of it, a ref (notion:ID, a repository) or its"
        " id; with year: the calendar year; with trip: a trip id as `show trips` prints it"
        " (trip:YYYY-MM-DD:YYYY-MM-DD), or any day inside it",
    )
    s.add_argument("--raw", action="store_true", help="print refs as the sources gave them, never a name")
    s.add_argument("--day", dest="show_day", metavar="YYYY-MM-DD", help="one local day")
    s.add_argument(
        "--json",
        action="store_true",
        help="the page or the reader's answer as one JSON object (days: one object per line)",
    )
    s.add_argument(
        "--year",
        metavar="YYYY",
        help="trips: one calendar year (default: the whole record); orgs --money: the ledger's year (default"
        " this one); ideas: the year of the words written (default this one)",
    )
    s.add_argument(
        "--since",
        "--from",
        dest="since",
        metavar="YYYY-MM-DD",
        help="trips, days, keepers: the first day (default the record's); heard: the first day",
    )
    s.add_argument(
        "--until",
        "--to",
        dest="until",
        metavar="YYYY-MM-DD",
        help="trips, days, keepers: the last day, inclusive (default the record's); heard: default today",
    )
    s.add_argument(
        "--airports",
        metavar="FILE",
        help=f"year, trip, trips, days: a CSV that adds to the airports table (else {flights.AIRPORTS_ENV})",
    )
    s.add_argument(
        "--html",
        metavar="PATH",
        help="year, trip: write one self-contained page (inline CSS, no script; the trip's SVG map) instead",
    )
    s.add_argument(
        "--print",
        action="store_true",
        help="year, trip, with --html: the paper edition — a cover, contents, one spread per month (year)"
        " or per day (trip), for A4 and US Letter",
    )
    s.add_argument(
        "--poster",
        action="store_true",
        help="year: one sheet: a square a day in the ink of its night (home, away, aboard, in transit), the"
        " countries under it, no names; to --html PATH, else stdout",
    )
    s.add_argument(
        "--sheet",
        choices=sorted(print_layout.POSTER_SHEETS),
        help=f"year, with --poster: the sheet (default {year_poster.SHEET})",
    )
    s.add_argument("--lane", choices=keepers.LANES, help="keepers: only this lane")
    s.add_argument(
        "--people",
        action="store_true",
        help="keepers: who appears on them, per month: the faces the library named, proposed only",
    )
    s.add_argument(
        "--health",
        action="store_true",
        help="stats: one row per day of the health lines: sleep hours, steps, resting HR",
    )
    s.add_argument(
        "--money",
        action="store_true",
        help="org, orgs: the ledger's lines and its in, out and net too (tier 3)",
    )
    s.add_argument(
        "--portfolio",
        metavar="TEXT",
        help="orgs: only the orgs in this portfolio, case and spaces aside (tier 3, on their status lines)",
    )
    s.add_argument("--coverage", action="store_true", help="plan: the rows of each database the record knows")
    s.set_defaults(fn=cmd_show)


def _show_reader(a: argparse.Namespace) -> None:
    """`show year YYYY`, `show trip ID-OR-DAY`, `show trips`, `show days`, `show keepers`, `show stats`:
    the reader runs as it did under its own name, with the same options."""
    from .keepers import cmd_keepers
    from .record import cmd_stats
    from .trips import cmd_trip, cmd_trips

    if a.day in ("year", "trip"):
        if a.name is None:
            what = "the calendar year, YYYY" if a.day == "year" else "a trip id, or any day inside the trip"
            print(f"show {a.day}: {what} is needed", file=sys.stderr)
            sys.exit(2)
    elif a.name is not None:
        print(f"show {a.day}: takes no name", file=sys.stderr)
        sys.exit(2)
    if a.day == "year":
        a.year = a.name
        cmd_year(a)
    elif a.day == "trip":
        a.ref = a.name
        cmd_trip(a)
    elif a.day == "trips":
        cmd_trips(a)
    elif a.day == "days":
        cmd_days(a)
    elif a.day == "keepers":
        cmd_keepers(a)
    else:
        cmd_stats(a)


def instant_of(stamp: str) -> datetime:
    """An RFC 3339 stamp as an aware UTC datetime, for ordering: `10:00:00.5Z` after `10:00:00Z`,
    which the text of `at` gets wrong (SPEC §3.2: a day is ordered by the instant, then `seq`)."""
    parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _show_orgs(a: argparse.Namespace) -> None:
    """`show orgs [--portfolio TEXT] [--money [--year YYYY]] [--json]`: the orgs the owner named
    under their status, the most recent touch first, then the people with more than one org; with
    `--portfolio`, only the orgs in that portfolio; `show org NAME [--money] [--json]`: one org's page
    (`logbook.contrib.orgs`). Every tier is read, as the owner's own terminal reads it; the ledger
    only with `--money`. Nothing is written."""
    from ..contrib import entities, orgs

    lb = Logbook.find()
    try:
        if a.day == "orgs":
            if a.name is not None:
                raise orgs.OrgError("takes no name; one org is `show org NAME`")
            shelf = orgs.shelf(lb, money=a.money, year=a.year, portfolio=a.portfolio)
            if a.json:
                print(json.dumps(shelf.to_json(), indent=2, ensure_ascii=False))
                return
            for text in orgs.shelf_rows(shelf):
                print(text)
            return
        if a.name is None:
            raise orgs.OrgError("say which org: `show org NAME`, a word of its name, a domain or its id")
        if a.portfolio is not None:
            raise orgs.OrgError("--portfolio goes with `show orgs`; one org's page says its portfolio")
        page = orgs.page(lb, orgs.find(lb, a.name).id, money=a.money)
    except (orgs.OrgError, entities.EntityError, stays.SettingsError) as e:
        print(f"show {a.day}: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(page.to_json(), indent=2, ensure_ascii=False))
        return
    for text in orgs.page_rows(page):
        print(text)


def _show_ideas(a: argparse.Namespace) -> None:
    """`show ideas [--year YYYY] [--json]`: the ideas the owner named by stage, the most recent touch
    first, each with its reason; `show idea NAME [--json]`: one idea's page (`logbook.contrib.ideas`).
    Every tier is read, as the owner's own terminal reads it. Nothing is written."""
    from ..contrib import entities, ideas

    lb = Logbook.find()
    try:
        if a.day == "ideas":
            if a.name is not None:
                raise ideas.IdeaError("takes no name; one idea is `show idea NAME`")
            shelf = ideas.shelf(lb, year=a.year)
            if a.json:
                print(json.dumps(shelf.to_json(), indent=2, ensure_ascii=False))
                return
            for text in ideas.shelf_rows(shelf):
                print(text)
            return
        if a.name is None:
            raise ideas.IdeaError("say which idea: `show idea NAME`, a word of its name, a ref or its id")
        page = ideas.page(lb, ideas.find(lb, a.name).id)
    except (ideas.IdeaError, entities.EntityError, stays.SettingsError) as e:
        print(f"show {a.day}: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(page.to_json(), indent=2, ensure_ascii=False))
        return
    for text in ideas.page_rows(page):
        print(text)


def cmd_show(a: argparse.Namespace) -> None:
    """One local day (the owner's timezone), located through the index, read from the files,
    in time order (then chain order for the same instant). Senders, organizers and attendees
    are shown by the names the record's own resolution lines give them (RFC 0006), built once
    per call; `--raw` prints the refs as the sources gave them. Nothing is written."""
    if a.day == HEARD:
        from .heard import cmd_heard

        cmd_heard(a)
        return
    if a.day in READERS:
        _show_reader(a)
        return
    if a.day in ORGS:
        _show_orgs(a)
        return
    if a.day in IDEAS:
        _show_ideas(a)
        return
    if a.day == PLAN:
        from .plan import cmd_plan

        cmd_plan(a)
        return
    lb = Logbook.find()
    if a.day in pages.PAGES:
        _show_page(lb, a)
        return
    if a.name is not None:
        print(
            f"show: {a.day!r} takes no name; a page is `show person|asset|place|org|idea <name>`",
            file=sys.stderr,
        )
        sys.exit(2)
    days = day_start.of(lb.meta)  # RFC 0036: a boundary this reader cannot parse is refused, here
    day = days.today(gaps.now()).isoformat() if a.day in (None, "today") else a.day
    tz = ZoneInfo(lb.meta["timezone"])
    with lb.index() as idx:
        # A retraction is not an event of its own day; it shows as a marker where the line it hides was.
        rows = [line for line in idx.day(day) if line["kind"] != RETRACTION]
        retracted = retractions(idx.retractions())
        # a superseder not retracted (issue #321): a flight another flight line replaced (RFC 0013
        # rule 4), a transcript heard again and separated (RFC 0038 §2.8)
        superseded = {**idx.superseded(flights.KIND), **idx.superseded("transcript")}
        for kind in ("attribution", "scene-review"):  # RFC 0040: a scene's answer corrected, its no followed
            superseded.update(idx.superseded(kind))
        names: dict[Ref, str] | None = None if a.raw else labels(lb, idx)
        signature = signing.signature_of(idx, day, str(lb.meta["owner_id"]))  # RFC 0034: the header
        held = chapter.for_day(idx.by_kind(chapter.KIND), retracted, day)  # RFC 0036: the header too
        goal_texts, replaced = _owner_lines(idx, rows, retracted)
    if not rows:
        print(f"{day}: nothing logged")
        return
    superseded = {**superseded, **replaced}
    rows.sort(
        key=lambda line: (instant_of(line["at"]), line["seq"])
    )  # by the instant, then seq (SPEC §3.2, #123)
    head = f"{day}  {signing.state_text(signing.signed_json(signature, str(tz), None))}"
    if held is not None:
        head += f"{day_reader.DOT}{chapter.header_text(held)}"
    print(head if days.midnight else f"{head}{day_reader.DOT}{days.describe()}")
    hero = keepers.hero_row([*rows, *retracted.values()])  # RFC 0024 rule 4: the day's hero photos
    if hero:
        print(f"  {hero}")
    descriptions = by_photo(line for line in rows if line["id"] not in retracted)
    for text in _day_rows(rows, retracted, tz, names, superseded, descriptions, goal_texts):
        print(text)
    note = lb.root / "notes" / day[:4] / f"{day}.md"
    if note.exists():
        print("  — note —\n" + "\n".join("  " + s for s in note.read_text(encoding="utf-8").splitlines()))


def _owner_lines(
    idx: Any, rows: Sequence[Line], retracted: Mapping[str, Line]
) -> tuple[dict[str, str], dict[str, int]]:
    """For `show`, when the day has a goal, review or chapter line (RFC 0036): the current text of
    each goal a review names, and the seq of the line that superseded each goal and chapter line."""
    kinds = {line.get("kind") for line in rows}
    if not kinds & {goals.KIND, goals.REVIEW, chapter.KIND}:
        return {}, {}
    every_goal = goals.Goals(idx.by_kind(goals.KIND), retracted)
    replaced = {id_: int(every_goal.by_id[later]["seq"]) for id_, later in every_goal.successor.items()}
    found = chapter.chapter_lines(idx.by_kind(chapter.KIND), retracted)
    by_id = {str(line["id"]): line for line in found}
    replaced.update({id_: int(by_id[later]["seq"]) for id_, later in chapter.successors(found).items()})
    return goals.texts(every_goal, rows), replaced


def day_arguments(sub: Subparsers) -> None:
    """`logbook day`."""
    s = sub.add_parser(
        "day",
        help="one day read back: night, stays, company, health; reflect, sign",
        description="one day read back: nights, country, stays and moves with who and what, flights, health,"
        " whether every usual source is in, and whether you have signed it; `day sign YYYY-MM-DD` signs"
        " it: one tier-1 line saying you read the page and these are the day's facts (RFC 0034), and"
        " what became of each commitment on it: --kept, --missed, --dropped, --carried (amendment 1),"
        " and the events the dream proposed that you --accept, each written as an event line;"
        " `day reflect YYYY-MM-DD` closes it in your words: a reflection typed, heard or dictated becomes"
        " one note on the day, its commitments, delegations and dispositions proposed, and --sign signs"
        " the day with the ones you --accept; either keeps what you --keep of the dream's draft, the day"
        " in a --word and the plan's tasks answered, each written before the signature (RFC 0043 §5)",
    )
    s.add_argument(
        "day",
        nargs="?",
        metavar="YYYY-MM-DD",
        help="the local day (default today); or `sign` or `reflect`, then the day",
    )
    s.add_argument(
        "signed_day",
        nargs="?",
        metavar="YYYY-MM-DD",
        help="with sign or reflect: the local day to sign or reflect on",
    )
    s.add_argument("--note", metavar="TEXT", help="sign: one line in your words; it is tier 1 and crosses")
    s.add_argument(
        "--confirm",
        metavar="ID,ID|all|none",
        help="sign: the lines you confirm as the day's facts, by seq or id as `show` lists them"
        " (default: every line on the page; a day signed before keeps what its signature confirmed);"
        f" `{sign_again.EVERY}` confirms the whole page and `{signing.NOTHING}` nothing, each alone",
    )
    s.add_argument(
        "--at",
        metavar="RFC3339",
        help=f"sign: when you signed, if not now, e.g. {signing.AT_EXAMPLE}: with an offset or Z, at most"
        " five minutes ahead of this clock, not before the day; stored in UTC",
    )
    for value, meaning in DISPOSITION_HELP.items():
        s.add_argument(
            f"--{value}",
            metavar="ID,ID",
            help=f"sign: the commitments {meaning}, by seq or id; each is confirmed by that",
        )
    s.add_argument("--text", metavar="TEXT", help="reflect: the reflection, typed")
    s.add_argument(
        "--audio",
        metavar="FILE",
        help="reflect: a recording of the reflection, heard on this machine (openlogbook[transcribe])",
    )
    s.add_argument(
        "--mic",
        metavar="SECONDS",
        type=float,
        help="reflect, on macOS: record this many seconds from the microphone (ffmpeg), then hear them",
    )
    s.add_argument(
        "--from-wispr",
        nargs="?",
        const="",
        metavar="SEQ",
        help='reflect: take the day\'s latest Wispr Flow dictation that begins with "reflect" as it is,'
        " or the dictation SEQ names",
    )
    s.add_argument(
        "--sign",
        action="store_true",
        help="reflect: then sign the day, the reflection confirmed and the proposals you accept written",
    )
    s.add_argument(
        "--accept",
        metavar="N,N|none",
        help="sign, and reflect with --sign: the proposals you accept, by the numbers printed, a proposed"
        " event of the dream written as an event line; on a terminal reflect asks",
    )
    s.add_argument(
        "--dry-run",
        action="store_true",
        help="reflect: print the reflection and its proposals; write nothing",
    )
    kept = s.add_argument_group(
        "keep and sign",
        "with `day sign`, or `day reflect --sign`: each written as its line before the signature, every"
        " one checked before the first is written (RFC 0043 §5)",
    )
    kept.add_argument(
        "--keep",
        metavar="N,N",
        help="the draft's sentences, links and photo you keep, by the numbers `day YYYY-MM-DD` prints: a"
        " sentence as a note (learned, decision, idea), a link as an entity line, the photo as a star",
    )
    kept.add_argument(
        "--mend", metavar='N="..."', action="append", help="a sentence you keep, in your own words"
    )
    kept.add_argument(
        "--revisit",
        metavar="N=YYYY-MM-DD",
        action="append",
        help="a decision you keep, and the day it comes back to you",
    )
    kept.add_argument("--word", metavar="WORD", help="the day in a word, your own; one a day")
    for flag, said in (
        ("--done", "done"),
        ("--tomorrow", "moved to tomorrow"),
        ("--let-go", "let go, never deleted"),
    ):
        kept.add_argument(
            flag, metavar="T,T", help=f"the plan's tasks {said}, by the numbers `show plan YYYY-MM-DD` prints"
        )
    s.add_argument(
        "--model",
        metavar="NAME",
        help=f"reflect, with --audio or --mic: the whisper model (default {TRANSCRIBE_DEFAULT_MODEL})",
    )
    s.add_argument(
        "--fetch-model",
        action="store_true",
        help="reflect, with --audio or --mic: download the model first when it is not on this machine (the"
        " only time it uses the network)",
    )
    s.add_argument(
        "--airports",
        metavar="FILE",
        help=f"a CSV that adds to the airports table (else {flights.AIRPORTS_ENV})",
    )
    s.add_argument(
        "--json", action="store_true", help="the Day as one JSON object, every row with its line ids"
    )
    s.add_argument(
        "--no-anniversaries",
        action="store_true",
        help="leave out the days together 1, 2, 3, 5 and 10 years ago (`anniversaries`)",
    )
    s.add_argument(
        "--no-dream",
        action="store_true",
        help="leave out what a model drafted: the day's draft (`dream`) and its calls' syntheses"
        " (`transcript synthesize`)",
    )
    s.set_defaults(fn=cmd_day)


DISPOSITION_HELP = {
    signing.KEPT: "you kept",
    signing.MISSED: "you missed",
    signing.DROPPED: "you let go of, on purpose",
    signing.CARRIED: "still open, carried to a later day",
}
SIGN_FLAGS = ("--note", "--confirm", "--at", *(f"--{value}" for value in signing.DISPOSITIONS))


def cmd_day(a: argparse.Namespace) -> None:
    """`day [YYYY-MM-DD] [--json]`: the Day — the nights either side, the country, the timeline of
    stays, moves, stops and flights with what attached to each and who was there, the health
    line, the sources — read through the index from one reading of the day and the day before
    (`logbook.core.day`); then the anniversaries, the days together exactly 1, 2, 3, 5 and 10 years
    before with the same canonical person (`logbook.contrib.people_drift`), unless
    `--no-anniversaries`: under `--json` the key is there only on a day that has one, so the Day's
    object (SPEC §3.2.7) is otherwise unchanged. Nothing is written, not even `policy/stays.json`."""
    lb = Logbook.find()
    if a.day == signing_verb:
        _day_sign(lb, a)
        return
    if a.day == REFLECT_VERB:
        _day_reflect(lb, a)
        return
    if a.signed_day is not None:
        print(
            f"day: {a.day!r} takes no second argument; `day sign YYYY-MM-DD` signs a day and"
            " `day reflect YYYY-MM-DD` closes it in your words",
            file=sys.stderr,
        )
        sys.exit(2)
    if a.note is not None or a.confirm is not None or a.at is not None or _dispositions(a):
        flags = f"{', '.join(SIGN_FLAGS[:-1])} and {SIGN_FLAGS[-1]}"
        print(f"day: {flags} belong to `day sign YYYY-MM-DD`", file=sys.stderr)
        sys.exit(2)
    reflecting = _reflect_flags(a)
    if reflecting:
        print(f"day: {_listed(reflecting)} belong to `day reflect YYYY-MM-DD`", file=sys.stderr)
        sys.exit(2)
    keeping = keep_sign.given(a)
    if keeping:
        print(
            f"day: {_listed(keeping)} belong to `day sign YYYY-MM-DD` and `day reflect YYYY-MM-DD --sign`",
            file=sys.stderr,
        )
        sys.exit(2)
    try:
        day = day_start.of(lb.meta).today(gaps.now()).isoformat() if a.day in (None, "today") else a.day
        airports = _airports(a.airports)
        data = day_reader.read(lb, day, airports)
        if a.no_dream:
            data.pop("draft", None)
            data.pop("draft_withheld", None)
            data.pop("syntheses", None)
            data.pop("syntheses_withheld", None)
        else:
            data.update(_week_of(lb, day))
        if not a.no_anniversaries:
            found = people_drift.anniversaries(lb, day, airports)
            if found:
                data["anniversaries"] = found
    except (ValueError, stays.SettingsError, policy.PolicyError) as e:
        print(f"day: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    for text in day_reader.rows(data):
        print(text)
    if data.get("week"):  # a Sunday: the week it closes, after the day (`dream week`)
        print()
        for text in drafts.unit_rows(
            f"week {data['week']}", data.get("week_draft"), data.get("week_draft_withheld")
        ):
            print(text)


def _week_of(lb: Logbook, day: str) -> dict[str, Any]:
    """On a Sunday whose week has a draft, the week (`week`) and its standing draft (`week_draft`), or
    the row that says the `dream` entry withholds it (`week_draft_withheld`), as `dream_week.on_sunday`
    reads them; nothing on any other day, so the Day's object is otherwise what it was."""
    week, draft, withheld = dream_week.on_sunday(lb, day)
    out: dict[str, Any] = {}
    if draft is not None or withheld is not None:
        out["week"] = week
    if draft is not None:
        out["week_draft"] = draft
    if withheld is not None:
        out["week_draft_withheld"] = withheld
    return out


signing_verb = "sign"


def _dispositions(a: argparse.Namespace) -> dict[str, list[str]]:
    """`--kept ID,ID --missed ID,ID --dropped ID,ID --carried ID,ID` as `signing.sign` takes them:
    word → the entries typed, the flags given only, in the four words' order."""
    return {
        value: str(getattr(a, value)).split(",")
        for value in signing.DISPOSITIONS
        if getattr(a, value, None) is not None
    }


def _confirm(a: argparse.Namespace) -> tuple[list[str] | None, bool]:
    """`--confirm ID,ID` as `signing.sign` takes it (`sign_again.confirmation`): None for the whole
    page, the entries typed, or the empty list for `--confirm none` (amendment 2); and whether the
    standing signature's confirmations are kept, as they are when `--confirm` is not given
    (amendment 4). `all` and `none` each go alone."""
    entries = None if a.confirm is None else str(a.confirm).split(",")
    return sign_again.confirmation(entries, bool(_dispositions(a)))


def _day_sign(lb: Logbook, a: argparse.Namespace) -> None:
    """`day sign YYYY-MM-DD [--note TEXT] [--confirm ID,ID|all|none] [--at RFC3339] [--kept ID,ID]
    [--missed ID,ID] [--dropped ID,ID] [--carried ID,ID]` (RFC 0034 and its amendments,
    `logbook.core.signing`): the owner's reading of the day's page, appended as one `signed-day/v1`
    line, tier 1, source manual — the day, the ids confirmed (every line on the page by default, or
    `--confirm all`; a line given a disposition is confirmed by that; none at all for `--confirm
    none`), what became of each commitment named, the digest of the page as shown and the note, at
    the moment the owner signed (`--at`, else now) — and nothing else touched. A day signed before is
    signed again: the new line supersedes the standing one and, without `--confirm`, keeps what it
    said (`sign_again`, RFC 0034 amendment 4): its confirmed lines still on the page, its
    dispositions and its note, what is typed winning; a line added since stays unconfirmed. Only the
    owner signs: here, or through the MCP tool `sign_day` when the owner's policy allows it by name
    (ADR 0022), which signs through the same `sign_again` and `signing.sign`."""
    if a.signed_day is None or a.signed_day == signing_verb:
        print("day sign: the day, YYYY-MM-DD, is needed: logbook day sign 2026-06-09", file=sys.stderr)
        sys.exit(2)
    reflecting = [flag for flag in _reflect_flags(a) if flag != "--accept"]
    if reflecting:
        print(f"day sign: {_listed(reflecting)} belong to `day reflect YYYY-MM-DD`", file=sys.stderr)
        sys.exit(2)
    try:
        day_start.of(lb.meta)  # the page is the day so defined: a boundary not a clock is refused (RFC 0036)
        day = parse_day(a.signed_day).isoformat()
        wanted = [] if a.accept is None else reflect.numbers(a.accept)
        asking = keep_sign.from_args(a)
        (confirm, keep), dispositions = _confirm(a), _dispositions(a)
        reflect.no_draft(lb, day, [*(confirm or []), *(e for found in dispositions.values() for e in found)])
        found = dream_events.listed(lb, day)  # the draft the Day shows: a withheld one proposes nothing
        taken = dream_events.chosen(found, wanted, day, dream_events.held_back(lb, day) if wanted else None)
        if asking and confirm == []:
            raise keep_sign.KeepError(
                f"--confirm {signing.NOTHING} confirms nothing, and what you keep is confirmed by keeping it;"
                " give one or the other"
            )
        if taken or asking:  # every flag checked before an event or a kept line is written
            dream_events.check_signature(lb, day, confirm, dispositions, a.at, a.note)
        for text in dream_events.rows(found):
            print(text)
        line, kept = _sign_with_events(lb, day, taken, confirm, keep, a.note, a.at, dispositions, asking)
    except ValueError as e:  # SignError, EventError, a day that is not one, a day_start that is not a clock
        print(f"day sign: {e}", file=sys.stderr)
        sys.exit(2)
    for text in signing.summary(line):
        print(text)
    if kept is not None:
        print(f"  {kept}")
    left = [p for p in found if p.pending and p not in taken]
    if left:
        n = len(left)
        print(
            f"  {n} proposed event{'s' if n != 1 else ''} not written; `logbook day sign {day} --accept N`"
            " writes one into the record"
        )


def _sign_with_events(
    lb: Logbook,
    day: str,
    taken: Sequence[dream_events.Proposed],
    confirm: list[str] | None,
    keep: bool,
    note: str | None,
    at: str | None,
    dispositions: dict[str, list[str]],
    asking: keep_sign.Asked | None = None,
) -> tuple[Line, str | None]:
    """Under one hold of the writer lock: what the owner keeps checked and made (`keep.prepared`), the
    proposals read again and every event line made before the first is written
    (`dream_events.prepared`), each written, then what is kept (`keep.write`: the kept sentences,
    links and photo, the day in a word, the tasks answered), then the standing signature read
    (`sign_again.again`: kept when `keep`) and the signature through `signing.sign`, the events and
    the kept lines among the lines confirmed and never a draft line (`reflect.ink`, RFC 0043 §6 rule
    3); with what was kept from the standing signature, said in a sentence."""
    with lb.writer():
        items = keep_sign.prepared(lb, day, asking) if asking else []
        written = [_write_event(lb, p, line) for p, line in dream_events.prepared(lb, day, taken)]
        today = notes.today_in(day_start.of(lb.meta))
        written += [str(line["id"]) for line in keep_sign.write(lb, day, today, items, print, at)]
        args = sign_again.again(lb, day, confirm, keep, dispositions, note)
        confirm = args.confirm
        if confirm is not None and (confirm or keep):
            confirm = [*confirm, *written]
        confirm = reflect.ink(lb, day, confirm)
        line = signing.sign(lb, day, confirm=confirm, note=args.note, at=at, dispositions=args.dispositions)
        return line, args.kept


def _write_event(lb: Logbook, proposal: dream_events.Proposed, made: dict[str, Any]) -> str:
    line = dream_events.write(lb, made)
    print(dream_events.wrote_text(proposal, line))
    return str(line["id"])


# -- day reflect ---------------------------------------------------------------------------------------------

REFLECT_VERB = "reflect"
INPUTS = ("--text", "--audio", "--mic", "--from-wispr")


def _reflect_flags(a: argparse.Namespace) -> list[str]:
    """The flags of `day reflect` given, as typed, for the refusal of another verb."""
    given = [
        flag
        for flag, dest in (
            ("--text", "text"),
            ("--audio", "audio"),
            ("--mic", "mic"),
            ("--from-wispr", "from_wispr"),
            ("--accept", "accept"),
            ("--model", "model"),
        )
        if getattr(a, dest, None) is not None
    ]
    given += [
        flag
        for flag, dest in (("--sign", "sign"), ("--dry-run", "dry_run"), ("--fetch-model", "fetch_model"))
        if getattr(a, dest, False)
    ]
    return given


def _listed(flags: Sequence[str]) -> str:
    return flags[0] if len(flags) == 1 else f"{', '.join(flags[:-1])} and {flags[-1]}"


def _on_a_tty() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _refuse(text: str) -> None:
    print(f"day reflect: {text}", file=sys.stderr)
    sys.exit(2)


def _day_reflect(lb: Logbook, a: argparse.Namespace) -> None:
    """`day reflect YYYY-MM-DD [--text TEXT | --audio FILE | --mic SECONDS | --from-wispr [SEQ]] [--at
    RFC3339] [--sign [--accept N,N|none]] [--dry-run]` (`logbook.contrib.reflect`): the reflection, in
    the owner's words, typed, heard on this machine, recorded from the microphone on macOS, or taken
    from the day's Wispr Flow dictation that begins with "reflect" (offered as a draft when no input is
    given, written only when confirmed); printed back a sentence a line, numbered, with the proposals
    the rules read in it. Written as one `note/v1` line, label `reflection`, source `reflect`, through
    `notes.write`; nothing else unless `--sign`: then the delegations accepted are written as notes and
    the day is signed through `signing.sign`, the reflection among the lines confirmed, the accepted
    dispositions in the signature, at `--at` (when the owner spoke) or now; a day signed already is
    signed again, keeping what its standing signature said. Every number and every flag is checked
    before anything is written; with no input and no draft, the reflection on the day is the one read."""
    if a.signed_day is None or a.signed_day == REFLECT_VERB:
        _refuse('the day, YYYY-MM-DD, is needed: logbook day reflect 2026-06-09 --text "..."')
    signs = [
        flag
        for flag, given in (("--note", a.note is not None), ("--confirm", a.confirm is not None))
        if given
    ]
    signs += [f"--{value}" for value in _dispositions(a)]
    if signs:
        _refuse(
            f"{_listed(signs)} belong to `day sign`; a reflection signs with --sign and the proposals"
            " you --accept"
        )
    if a.accept is not None and not a.sign:
        _refuse("--accept goes with --sign: the proposals you accept are written when the day is signed")
    keeping = keep_sign.given(a)
    if keeping and not a.sign:
        _refuse(f"{_listed(keeping)} go with --sign: what you keep is written when the day is signed")
    inputs = [
        flag
        for flag, given in zip(INPUTS, (a.text, a.audio, a.mic, a.from_wispr), strict=True)
        if given is not None
    ]
    if len(inputs) > 1:
        _refuse(f"give one of {', '.join(INPUTS[:-1])} or {INPUTS[-1]}, not {' and '.join(inputs)}")
    if (a.model is not None or a.fetch_model) and not {"--audio", "--mic"} & set(inputs):
        _refuse("--model and --fetch-model go with --audio or --mic")
    try:
        day = parse_day(a.signed_day).isoformat()
        tz = str(lb.meta["timezone"])
        days = day_start.of(lb.meta)  # the page is the day so defined (RFC 0036)
        today = notes.today_in(days)
        reflect.on_or_before(day, today, tz)
        if a.at is not None:
            notes.moment(day, tz, a.at, today, days)  # the note's rules, checked before anything is heard
        wanted = None if a.accept is None else reflect.numbers(a.accept)
        _reflect(lb, a, day, today, wanted, keep_sign.from_args(a))
    except ValueError as e:  # ReflectError, SignError, NoteError, a day that is not one
        _refuse(str(e))


def _reflect(
    lb: Logbook,
    a: argparse.Namespace,
    day: str,
    today: str,
    wanted: list[int] | None,
    keeping: keep_sign.Asked | None = None,
) -> None:
    zone = ZoneInfo(str(lb.meta["timezone"]))
    lines, retracted = reflect.day_lines(lb, day)
    standing = reflect.reflections(lines, retracted)
    r, shown = _reflection(lb, a, day, lines, retracted, standing, zone)
    if r is None:
        return
    if not r.text.strip():
        raise reflect.ReflectError("the reflection is empty; say or type a few words")
    if r.note is None and r.how != reflect.DRAFT:
        existing = reflect.same(r.text, standing, r.dictation)
        if existing is not None:  # the same words on the day already: read, never written twice
            r, shown = reflect.on_the_day(existing), False
    exclude = {
        str(line["id"]) for line in (r.note, r.dictation.line if r.dictation else None) if line is not None
    }
    proposals = reflect.propose(r.text, day, reflect.commitments(lb, day, exclude))
    events = dream_events.listed(lb, day, first=len(proposals) + 1)  # numbered after the reflection's
    if not shown:
        _print_reflection(day, r, zone)
    for text in _proposal_rows(proposals):
        print(text)
    for text in dream_events.rows(events):
        print(text)
    if a.dry_run:
        print("dry run: nothing was written")
        return
    if r.how == reflect.DRAFT:
        print(
            f"nothing was written: take it as the reflection with `logbook day reflect {day} --from-wispr`,"
            " or name another dictation with --from-wispr SEQ"
        )
        return
    askable = [p for p in proposals if p.kind != reflect.COMMITMENT]
    open_events = [e for e in events if e.pending]
    asking = [(p.number, str(p.value if p.kind == reflect.DISPOSITION else p.kind)) for p in askable]
    asking += [(e.number, drafts.EVENT) for e in open_events]
    if not a.sign:
        if r.note is None:
            _write_reflection(lb, day, r, a.at, today, zone)
        else:
            print(f"nothing was written: the reflection #{r.note['seq']} is on the day already")
        accept = " --accept N,N" if asking else ""
        print(
            f"nothing else was written; `logbook day reflect {day} --sign{accept}` signs the day"
            + (" with the proposals you accept" if asking else "")
        )
        return
    if wanted is not None:
        chosen = wanted
    elif not asking:
        chosen = []
    elif _on_a_tty():
        answered = _ask_each(asking)
        if answered is None:
            print("stopped: nothing was written")
            return
        chosen = answered
    else:
        raise reflect.ReflectError(
            "not at a terminal, so say which proposals you accept: --accept N,N, or --accept none;"
            " nothing was written"
        )
    known = {p.number for p in proposals} | {e.number for e in events}
    missing = [str(n) for n in chosen if n not in known]
    if missing:
        have = f"{len(proposals)} proposal{'s' if len(proposals) != 1 else ''}"
        if events:
            have += f" and the dream {len(events)} proposed event{'s' if len(events) != 1 else ''}"
        text = f"no proposal {', '.join(missing)}; the reflection has {have}, numbered above"
        held = dream_events.held_back(lb, day)
        if held is not None:
            text += f"; the dream's standing draft is withheld with its proposed events, {held}"
        raise reflect.ReflectError(text)
    accepted = reflect.chosen(proposals, [n for n in chosen if n <= len(proposals)])
    taken = dream_events.chosen(events, [n for n in chosen if n > len(proposals)], day)
    _reflect_sign(lb, a, day, today, r, accepted, zone, taken, first=len(proposals) + 1, asking=keeping)


def _reflection(
    lb: Logbook,
    a: argparse.Namespace,
    day: str,
    lines: list[Line],
    retracted: set[str],
    standing: list[Line],
    zone: ZoneInfo,
) -> tuple[reflect.Reflection | None, bool]:
    """The reflection the flags name, and whether its lines were printed already (a draft confirmed on
    a terminal); None when the owner left a draft as it was."""
    if a.text is not None:
        return reflect.Reflection(a.text.strip(), reflect.TYPED), False
    if a.audio is not None:
        path = Path(a.audio)
        if not path.is_file():
            raise reflect.ReflectError(f"no recording at {a.audio}")
        return heard(path, a.model or TRANSCRIBE_DEFAULT_MODEL, a.fetch_model), False
    if a.mic is not None:
        with tempfile.TemporaryDirectory(prefix="logbook-reflect-") as folder:
            recorded = reflect.record(a.mic, Path(folder))
            return heard(recorded, a.model or TRANSCRIBE_DEFAULT_MODEL, a.fetch_model), False
    said = reflect.dictations(lb, lines, retracted)
    if a.from_wispr is not None:
        if a.from_wispr:
            return reflect.dictated(reflect.pick(said, a.from_wispr, day)), False
        found = reflect.drafts(said, [])
        if not found:
            raise reflect.ReflectError(f'no Wispr Flow dictation on {day} begins with "{reflect.CUE}"')
        return reflect.dictated(found[-1]), False
    pending = reflect.drafts(said, standing)
    if pending:
        draft = reflect.draft(pending[-1])
        if a.dry_run or not _on_a_tty():
            return draft, False
        _print_reflection(day, draft, zone)
        taken, edited = _confirm_draft()
        if not taken:
            print("left as it is: nothing was written")
            return None, True
        if edited is not None:
            return reflect.dictated(pending[-1], edited), False
        return reflect.dictated(pending[-1]), True
    if standing:
        return reflect.on_the_day(standing[-1]), False
    raise reflect.ReflectError(
        f"nothing to reflect on for {day}: give --text, --audio FILE or --mic SECONDS, or dictate in"
        " Wispr Flow"
        f' a note that begins with "{reflect.CUE}"'
    )


def heard(path: Path, model: str = TRANSCRIBE_DEFAULT_MODEL, fetch_model: bool = False) -> reflect.Reflection:
    """The recording at `path` heard by the local engine (`transcribe.hear`), its segments joined
    with a space so that a sentence the engine cut in two is one sentence again: `day reflect
    --audio` and `--mic`, and a recording sent from the Day page of `serve` (`voice`)."""
    from ..labs import transcribe

    try:
        engine = transcribe.detect(model)
        result = transcribe.hear(engine, path, fetch_model=fetch_model)
    except (transcribe.EngineMissing, transcribe.ModelMissing) as e:
        raise reflect.ReflectError(str(e)) from e
    except (OSError, RuntimeError) as e:  # a file the engine cannot decode
        raise reflect.ReflectError(f"{path.name} could not be heard: {e}") from e
    text = " ".join(s.text.strip() for s in result.segments if s.text.strip())
    if not text:
        raise reflect.ReflectError(f"no words were heard in {path.name}")
    heard_by = {"engine": engine.name, "model": engine.model, "language": result.language or None}
    return reflect.Reflection(text, reflect.HEARD, extra={"heard_by": heard_by})


def voice(model: str = TRANSCRIBE_DEFAULT_MODEL) -> serve.Voice:
    """Whether the Day page of `serve` can hear a recording, asked once when the server starts: the
    engine of the `openlogbook[transcribe]` extra and its model on this machine, then `heard` for each
    recording, never fetching; or why not, which the page says in place of the recording form."""
    from ..contrib import serve
    from ..labs import transcribe

    try:
        engine = transcribe.detect(model)
        ready = engine.ready()
    except transcribe.EngineMissing as e:
        return serve.Voice(None, str(e))
    except (ImportError, OSError) as e:
        return serve.Voice(
            None, f"the transcription engine could not be asked whether its model is here: {e}"
        )
    if not ready:
        return serve.Voice(
            None,
            f"model {model!r} is not on this machine; `logbook day reflect YYYY-MM-DD --audio FILE"
            " --fetch-model` fetches it once, the only time it uses the network; then restart `serve`",
        )
    return serve.Voice(lambda path: heard(path, model))


def _print_reflection(day: str, r: reflect.Reflection, zone: ZoneInfo) -> None:
    if r.note is not None:
        head = f"the reflection #{r.note['seq']} of {_clock(str(r.note['at']), zone)}"
    elif r.dictation is not None:
        when = f"the Wispr Flow dictation #{r.dictation.seq} of {_clock(r.dictation.at, zone)}"
        head = (
            f'{when} begins with "{reflect.CUE}"; the draft'
            if r.how == reflect.DRAFT
            else f"the reflection, from {when}"
        )
    elif r.how == reflect.HEARD:
        by = r.extra["heard_by"]
        language = f", {by['language']}" if by["language"] else ""
        head = f"the reflection, heard by {by['engine']} ({by['model']}{language})"
    else:
        head = "the reflection, typed"
    print(f"{day}  {head}:")
    for n, sentence in enumerate(reflect.sentences(r.text), 1):
        print(f"  {n:>3}  {sentence}")


def _proposal_rows(proposals: Sequence[reflect.Proposal]) -> Iterator[str]:
    """One row per proposal, numbered: what it is, the line of the reflection it was read in, and the
    evidence (the sentence, the cue, a due day; a disposition's commitment and the overlap)."""
    if not proposals:
        yield "no proposals: the rules read no commitment, delegation or disposition in it"
        return
    yield "proposals, by rules alone; each is a guess until you accept it:"
    for p in proposals:
        word, what = reflect.proposal_words(p)
        yield f"  {p.number:>3}  {word:<11} line {p.sentence}  {what}"


def _confirm_draft() -> tuple[bool, str | None]:
    """On a terminal: y takes the draft as it is, e asks for the words instead (an empty line ends
    them), n or q or the end of input leaves it. (taken, the words typed or None)."""
    while True:
        try:
            answer = input("      y takes it as the reflection, e edits it, n leaves it: ").strip().casefold()
        except EOFError:
            print()
            return False, None
        if answer in ("n", "q"):
            return False, None
        if answer == "y":
            return True, None
        if answer == "e":
            break
    print("      type the reflection; an empty line ends it:")
    typed: list[str] = []
    while True:
        try:
            row = input("      ")
        except EOFError:
            break
        if not row.strip():
            break
        typed.append(row.strip())
    return (True, "\n".join(typed)) if typed else (False, None)


def _ask_each(asking: Sequence[tuple[int, str]]) -> list[int] | None:
    """On a terminal, one y or n per proposal that would write something, (number, word) as printed;
    q or the end of input stops, and then nothing is written. The numbers accepted."""
    accepted: list[int] = []
    for number, word in asking:
        while True:
            try:
                answer = input(f"      {number} {word}: accept? y/n, q stops: ").strip().casefold()
            except EOFError:
                print()
                return None
            if answer == "q":
                return None
            if answer in ("y", "n"):
                break
        if answer == "y":
            accepted.append(number)
    return accepted


def _write_reflection(
    lb: Logbook, day: str, r: reflect.Reflection, at: str | None, today: str, zone: ZoneInfo
) -> Line:
    """The reflection as one note/v1 line on the day (`reflect.write`): at `--at` when given, else when
    the dictation was spoken, else the note's own default."""
    note = reflect.write(lb, day, r, at, today)
    print(reflect.wrote_text(note, zone))
    return note


def _reflect_sign(
    lb: Logbook,
    a: argparse.Namespace,
    day: str,
    today: str,
    r: reflect.Reflection,
    accepted: Sequence[reflect.Proposal],
    zone: ZoneInfo,
    taken: Sequence[dream_events.Proposed] = (),
    first: int = 1,
    asking: keep_sign.Asked | None = None,
) -> None:
    """The day closed through `reflect.close`, the code the Day page's Sign runs too: under one hold
    of the writer lock, the page read again (a disposition's line retracted while the owner answered
    is refused, nothing written), the proposed events accepted read again and made into their lines
    (`dream_events.prepared`) and what the owner keeps checked (`keep.prepared`), the reflection
    written when it is new, the accepted delegations written as notes, the accepted events as event
    lines, what is kept (`keep.write`), then the signature through `signing.sign`, never confirming a
    draft line; each step printed as it is done. HeadMoved and another writer are the store's own
    errors, said by `cli.main`; nothing is retried."""
    closed = reflect.close(
        lb, day, today, r, accepted, a.at, say=print, events=taken, first=first, keeping=asking
    )
    for text in signing.summary(closed.signature):
        print(text)


def digest_arguments(sub: Subparsers) -> None:
    """`logbook digest`."""
    s = sub.add_parser(
        "digest",
        help="one day in 25 lines at most, closing with one question",
        description="one day in 25 lines at most: where, with whom, what attached, flights, promises due,"
        " gaps,"
        " tomorrow, one question",
    )
    s.add_argument("day", nargs="?", metavar="YYYY-MM-DD", help="the local day (default today)")
    s.add_argument(
        "--airports",
        metavar="FILE",
        help=f"a CSV that adds to the airports table (else {flights.AIRPORTS_ENV})",
    )
    form = s.add_mutually_exclusive_group()
    form.add_argument("--json", action="store_true", help="the digest as one JSON object, with line ids")
    form.add_argument("--markdown", action="store_true", help="the same lines as Markdown")
    s.add_argument(
        "--paper",
        action="store_true",
        help="the week as four pages of A4: the days one line each, who was there and the keepers,"
        " the promises due, what was read (titles only); to --html PATH, else stdout",
    )
    s.add_argument("--week", metavar="YYYY-Www", help="with --paper: the ISO week (default the day's week)")
    s.add_argument("--html", metavar="PATH", help="with --paper: write the document here instead of stdout")
    s.set_defaults(fn=cmd_digest)


def cmd_digest(a: argparse.Namespace) -> None:
    """`digest [YYYY-MM-DD] [--json | --markdown]`: the day in at most `digest.LIMIT` lines — its
    shape in three (where, with whom confirmed, what attached), the flights, the open promises due
    within the week, the usual sources with no line, tomorrow's timed calendar entries and one
    closing question the owner answers in a word (`logbook.contrib.digest`, composed from the readers).
    Nothing is written and nothing is sent: delivery is a later decision (ADR 0005)."""
    lb = Logbook.find()
    if a.paper:  # the week's paper (`logbook.contrib.week_paper`), as a document
        _digest_paper(lb, a)
        return
    if a.week or a.html:
        print("digest: --week and --html belong to --paper; give it too", file=sys.stderr)
        sys.exit(2)
    try:  # today is the day the owner is in: under the record's day_start, at 05:59 still yesterday
        day = day_start.of(lb.meta).today(gaps.now()).isoformat() if a.day in (None, "today") else a.day
        data = digest_reader.read(lb, day, _airports(a.airports))
    except (ValueError, stays.SettingsError) as e:
        print(f"digest: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    for text in digest_reader.markdown(data) if a.markdown else digest_reader.rows(data):
        print(text)


def _digest_paper(lb: Logbook, a: argparse.Namespace) -> None:
    """`digest --paper [--week YYYY-Www | YYYY-MM-DD] [--html PATH | --json]`: the week as four
    pages of A4 (`logbook.contrib.week_paper`) — the days one line each, the people confirmed and the
    keepers, the promises due, what was read — written to `--html PATH` (its folder made), else
    to stdout; `--json` is the paper's object. The week is the one given, else the week of the
    day given, else of today in the record's zone. Nothing is written to the record."""
    if a.markdown:
        print("digest: --paper is a document; --markdown is the day's digest", file=sys.stderr)
        sys.exit(2)
    if a.week and a.day not in (None, "today"):
        print("digest: --paper takes a week or a day, not both", file=sys.stderr)
        sys.exit(2)
    try:
        if a.week:
            week = a.week
        elif a.day in (None, "today"):
            week = week_paper.week_of(day_start.of(lb.meta).today(gaps.now()).isoformat())
        else:
            week = week_paper.week_of(a.day)
        data = week_paper.read(lb, week, _airports(a.airports))
    except (ValueError, stays.SettingsError) as e:
        print(f"digest: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    page = week_paper.html(data)
    if a.html:
        out = Path(a.html)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(page.encode("utf-8"))
        print(f"digest {data['week']}: wrote {out}")
        return
    print(page, end="")


def questions_arguments(sub: Subparsers) -> None:
    """`logbook setup questions` (`logbook questions` until 0.6)."""
    s = sub.add_parser(
        "questions",
        help="the digest's closing questions (policy/questions.json): list, add one, disable one",
    )
    verbs = s.add_subparsers(dest="verb", required=True)
    v = verbs.add_parser("list", help="one line per question: id, kind, weight, when, text")
    v.add_argument("--json", action="store_true", help="the bank as JSON, as the file holds it")
    v.set_defaults(fn=cmd_questions)
    v = verbs.add_parser("add", help="one more question; the id must be new")
    v.add_argument("id", help="the question's own name, free text")
    v.add_argument(
        "--text", required=True, help="the question, in English; {person}, {place}, ... are filled"
    )
    v.add_argument("--kind", required=True, choices=questions.KINDS)
    v.add_argument(
        "--when",
        action="append",
        metavar="FACT",
        help=f"a fact of the day that must hold (prefix ! for one that must not); repeatable;"
        f" one of {', '.join(questions.FACTS)}",
    )
    v.add_argument("--weight", type=float, default=1.0, help="its share of the draw (default 1)")
    v.add_argument("--source", help="the research behind it, free text")
    v.add_argument("--de", metavar="TEXT", help="the same question in German")
    v.set_defaults(fn=cmd_questions)
    v = verbs.add_parser("disable", help="never ask this one again; it stays in the file")
    v.add_argument("id")
    v.set_defaults(fn=cmd_questions)


def cmd_questions(a: argparse.Namespace) -> None:
    """`questions list [--json]`: the question bank of the digest, `policy/questions.json`, one line
    per question — id, kind, weight, the facts it asks on, the text, `(disabled)` when it is.
    `questions add ID --text TEXT --kind KIND [--when FACT]... [--weight N] [--source TEXT] [--de TEXT]`:
    one more, refused when the id is taken or the shape is not the documented one. `questions
    disable ID`: kept in the file, never asked (RFC 0027). A record without the file gets the
    defaults first."""
    lb = Logbook.find()
    try:
        if a.verb == "add":
            q = questions.add(
                lb.root,
                questions.Question(
                    id=a.id,
                    text=a.text,
                    kind=a.kind,
                    when=tuple(a.when or ()),
                    weight=a.weight,
                    source=a.source or "",
                    text_de=a.de,
                ),
            )
            print(_question_row(q))
            return
        if a.verb == "disable":
            q = questions.disable(lb.root, a.id)
            print(f"{q.id}: disabled; it stays in {_under_home(questions.questions_path(lb.root))}")
            return
        bank = questions.read(lb.root)
    except policy.PolicyError as e:
        print(f"questions: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps({"questions": [q.to_json() for q in bank]}, indent=2, ensure_ascii=False))
        return
    for q in bank:
        print(_question_row(q))


def _question_row(q: questions.Question) -> str:
    weight = int(q.weight) if q.weight == int(q.weight) else q.weight
    row = f"  {q.id:<16} {q.kind:<10} {weight!s:<4} {' '.join(q.when):<32} {q.text}"
    return row if q.enabled else f"{row} (disabled)"


def cmd_days(a: argparse.Namespace) -> None:
    """`days [--from DAY] [--to DAY] [--json]`: a window of the record one line per day — the
    night, the kilometres moved, the flights, the stays with what attached, the people confirmed,
    the health triple, and a gap marker for a usual source with no line that day — streamed from
    readings of the window in chunks through the index (`logbook.core.days`), never one per day. The
    window defaults to the days the owner's track covers. `--json` is one object per line. Nothing
    is written."""
    lb = Logbook.find()
    try:
        window = _days_window(lb, a.since, a.until)
        if window is None:
            if not a.json:
                print("no days: the record has no lines")
            return
        for r in days_reader.read(lb, window[0], window[1], _airports(a.airports)):
            print(json.dumps(r, ensure_ascii=False) if a.json else days_reader.row(r))
    except (ValueError, stays.SettingsError) as e:
        print(f"days: {e}", file=sys.stderr)
        sys.exit(2)


def cmd_year(a: argparse.Namespace) -> None:
    """`year YYYY [--html PATH] [--json]`: the Year — days per country, nights, the trips, the
    flights, the places by nights, the people by days together, health and keepers by month, and
    twelve picks, one day a month, rendered with the day reader — composed from one reading of
    the year's days (`logbook.core.year`). `--html` writes one self-contained page. Nothing is written
    to the record."""
    lb = Logbook.find()
    if a.poster and a.print:
        print("year: --poster is one sheet and --print the paper edition; give one", file=sys.stderr)
        sys.exit(2)
    if a.sheet and not a.poster:
        print("year: --sheet is the poster's; give --poster too", file=sys.stderr)
        sys.exit(2)
    try:
        if a.poster:  # one sheet (`logbook.contrib.year_poster`), written where --html says, else to stdout
            poster = year_poster.read(lb, a.year, _airports(a.airports))
            page = year_poster.html(poster, a.sheet or year_poster.SHEET)
            if a.html:
                out = Path(a.html)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(page.encode("utf-8"))
                print(f"year {poster['year']}: wrote {out}")
            else:
                print(page, end="")
            return
        if a.print:  # the paper edition (`logbook.contrib.print_page`), written where --html says
            out = _print_target(a, "year")
            data = print_page.read_year(lb, a.year, _airports(a.airports))
            out.write_bytes(print_page.html(data).encode("utf-8"))
            print(f"year {data['year']}: wrote {out}")
            return
        data = year_reader.read(lb, a.year, _airports(a.airports))
    except (ValueError, stays.SettingsError) as e:
        print(f"year: {e}", file=sys.stderr)
        sys.exit(2)
    if a.html:
        out = Path(a.html)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(year_reader.html(data).encode("utf-8"))
        print(f"year {data['year']}: wrote {out}")
        return
    if a.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    for text in year_reader.rows(data):
        print(text)


def _days_window(lb: Logbook, since: str | None, until: str | None) -> tuple[str, str] | None:
    """`--from` and `--to`, each defaulting to the record's first or last day with a location line
    (else any line); None when a bound is missing and the record has no lines."""
    if since is not None and until is not None:
        return parse_day(since).isoformat(), parse_day(until).isoformat()
    whole = reading.record_days(lb, "location") or reading.record_days(lb)
    if whole is None:
        return None
    first = parse_day(since).isoformat() if since else whole[0]
    last = parse_day(until).isoformat() if until else whole[1]
    return first, last


def _show_page(lb: Logbook, a: argparse.Namespace) -> None:
    """`show person|asset|place <name> [--json]`: a page read from the whole record (the days the
    owner's track covers) through `pages`. Nothing is written."""
    if a.name is None:
        print(f"show {a.day}: say who or what, e.g. `logbook show {a.day} <name>`", file=sys.stderr)
        sys.exit(2)
    try:
        whole = reading.record_days(lb, "location") or reading.record_days(lb)
        if whole is None:
            raise pages.PageError("the record has no lines")
        read = reading.read(lb, whole[0], whole[1])
        page = {"person": pages.person, "asset": pages.asset, "place": pages.place}[a.day](read, a.name)
    except (pages.PageError, stays.SettingsError) as e:
        print(f"show {a.day}: {e}", file=sys.stderr)
        sys.exit(2)
    if a.day == "person":
        page["commitments"] = _commitments(lb, page)
    if a.json:
        print(json.dumps(page, indent=2, ensure_ascii=False))
        return
    for text in pages.rows(page):
        print(text)


def _commitments(lb: Logbook, page: dict[str, Any]) -> dict[str, Any]:
    """The open promises with the page's person, as `promises` reads them (`people_drift.promises_with`:
    by the speaker, else the counterpart's name), each with whether the owner owes it."""
    from ..contrib import people_drift, person_page
    from ..core import people

    who = people.Person(page["id"], page["name"], (), None, 0)
    found = people_drift.promises_with(lb, [who]).get(page["id"], [])
    return {
        "open": [{**person_page.promise_json(p), "you_owe": mine} for p, mine in found],
        "you_owe": sum(1 for _p, mine in found if mine),
        "they_owe": sum(1 for _p, mine in found if not mine),
    }


def search_arguments(sub: Subparsers) -> None:
    """`logbook search`."""
    s = sub.add_parser(
        "search",
        help='full-text search through the index: words, "a phrase", kar*',
        description='full-text search: words, "a phrase", kar* — literal, ranked, grouped by day, through'
        " the index",
    )
    s.add_argument("text", help='the words; "in quotes" a phrase; a word ending in * matches by prefix')
    s.add_argument("--since", metavar="YYYY-MM-DD", help="the first local day searched")
    s.add_argument("--until", metavar="YYYY-MM-DD", help="the last local day searched")
    s.add_argument(
        "--kinds",
        metavar="note,transcript,message,mail,event",
        help=f"only these kinds (default every kind with words: {', '.join(search.KINDS)})",
    )
    s.add_argument(
        "--tier",
        type=int,
        choices=(1, 2, 3),
        default=search.MAX_TIER,
        help="search up to this tier (default 2); tier 3 — money, health, the transcripts at 3 — only with 3",
    )
    s.add_argument("--limit", type=int, default=search.LIMIT, help=f"the hits shown (default {search.LIMIT})")
    s.add_argument(
        "--standing",
        action="store_true",
        help="standing hits only: leave out a line a later line of its kind supersedes (marked otherwise)",
    )
    s.add_argument(
        "--json",
        action="store_true",
        help="the query, the hits by day with rank, snippet, summary, standing and superseded_by",
    )
    s.set_defaults(fn=cmd_search)


def cmd_search(a: argparse.Namespace) -> None:
    """`search TEXT [--since DAY] [--until DAY] [--kinds a,b] [--tier 1|2|3] [--limit N] [--standing]
    [--json]`: full-text search through the index's FTS5 table (`logbook/core/search.py`): words and
    quoted phrases, literal (no stemming), case and accents aside; the hits ranked by bm25, grouped by
    local day, each as the row `show` prints with a snippet of the matching words under it, and
    `superseded by #N` after the row of a hit a later line of its kind supersedes (`--standing`: such
    a hit is left out). Tiers 1 and 2 unless `--tier 3`. Nothing is written to the record (an index built
    before `lines_kind_supersedes` is given it, as the Library gives it)."""
    lb = Logbook.find()
    day_start.of(lb.meta)  # a hit is listed on its day: a boundary not a clock is refused (RFC 0036)
    try:
        q = search.query(
            a.text,
            since=parse_day(a.since).isoformat() if a.since else None,
            until=parse_day(a.until).isoformat() if a.until else None,
            kinds=_csv(a.kinds),
            max_tier=a.tier,
            limit=a.limit,
            standing=a.standing,
        )
    except (search.QueryError, ValueError) as e:
        print(f"search: {e}", file=sys.stderr)
        sys.exit(2)
    tz = ZoneInfo(lb.meta["timezone"])
    try:
        with lb.index() as idx:
            # an index built before `lines_kind_supersedes` is given it, once (the Library's way, the
            # writer lock not waited for): the mark asks it, and without it reads every line of a kind
            idx.add_indexes()
            result = search.search(idx, q)
            names = labels(lb, idx)
    except RuntimeError as e:  # no FTS5 in this SQLite
        print(f"search: {e}", file=sys.stderr)
        sys.exit(1)
    if a.json:
        print(
            json.dumps(result.to_json(lambda line: _line_text(line, tz, names)), indent=2, ensure_ascii=False)
        )
        return
    for text in search.rows(result, lambda line: _line_row(line, None, tz, names)):
        print(text)
