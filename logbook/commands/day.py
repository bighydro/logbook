"""The record read back a day at a time: `show`, `day`, `digest`, `questions`, `days`, `year` and
`search`."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from ..contrib import digest as digest_reader
from ..contrib import print_page, questions
from ..core import day as day_reader
from ..core import days as days_reader
from ..core import flights, keepers, pages, policy, reading, search, stays
from ..core import year as year_reader
from ..core.export import parse_day
from ..core.resolve import Ref, labels
from ..core.store import RETRACTION, Logbook, retractions
from .common import Subparsers, _airports, _csv, _print_target, _today, _under_home
from .rows import _day_rows, _line_row, _line_text


def show_arguments(sub: Subparsers) -> None:
    """`logbook show`."""
    s = sub.add_parser("show", help="one day (default today), or a page: person, asset or place")
    s.add_argument("day", nargs="?", help="YYYY-MM-DD, or person|asset|place")
    s.add_argument("name", nargs="?", help="with person|asset|place: the name, entity id or asset id")
    s.add_argument("--raw", action="store_true", help="print refs as the sources gave them, never a name")
    s.add_argument("--json", action="store_true", help="a page as one JSON object")
    s.set_defaults(fn=cmd_show)


def cmd_show(a: argparse.Namespace) -> None:
    """One local day (the owner's timezone), located through the index, read from the files,
    in time order (then chain order for the same instant). Senders, organizers and attendees
    are shown by the names the record's own resolution lines give them (RFC 0006), built once
    per call; `--raw` prints the refs as the sources gave them. Nothing is written."""
    from ..labs import describe

    lb = Logbook.find()
    if a.day in pages.PAGES:
        _show_page(lb, a)
        return
    if a.name is not None:
        print(f"show: {a.day!r} takes no name; a page is `show person|asset|place <name>`", file=sys.stderr)
        sys.exit(2)
    day = date.today().isoformat() if a.day in (None, "today") else a.day
    tz = ZoneInfo(lb.meta["timezone"])
    with lb.index() as idx:
        # A retraction is not an event of its own day; it shows as a marker where the line it hides was.
        rows = [line for line in idx.day(day) if line["kind"] != RETRACTION]
        retracted = retractions(idx.retractions())
        superseded = idx.superseded(flights.KIND)  # a flight another flight line replaced (RFC 0013 rule 4)
        names: dict[Ref, str] | None = None if a.raw else labels(lb, idx)
    if not rows:
        print(f"{day}: nothing logged")
        return
    rows.sort(key=lambda line: (line["at"], line["seq"]))
    print(day)
    hero = keepers.hero_row([*rows, *retracted.values()])  # RFC 0024 rule 4: the day's hero photos
    if hero:
        print(f"  {hero}")
    descriptions = describe.by_photo(line for line in rows if line["id"] not in retracted)
    for text in _day_rows(rows, retracted, tz, names, superseded, descriptions):
        print(text)
    note = lb.root / "notes" / day[:4] / f"{day}.md"
    if note.exists():
        print("  — note —\n" + "\n".join("  " + s for s in note.read_text(encoding="utf-8").splitlines()))


def day_arguments(sub: Subparsers) -> None:
    """`logbook day`."""
    s = sub.add_parser(
        "day", help="one day read back: nights, country, stays and moves with who and what, flights, health"
    )
    s.add_argument("day", nargs="?", metavar="YYYY-MM-DD", help="the local day (default today)")
    s.add_argument(
        "--airports",
        metavar="FILE",
        help=f"a CSV that adds to the airports table (else {flights.AIRPORTS_ENV})",
    )
    s.add_argument(
        "--json", action="store_true", help="the Day as one JSON object, every row with its line ids"
    )
    s.set_defaults(fn=cmd_day)


def cmd_day(a: argparse.Namespace) -> None:
    """`day [YYYY-MM-DD] [--json]`: the Day — the nights either side, the country, the timeline of
    stays, moves, stops and flights with what attached to each and who was there, the health
    line, the sources — read through the index from one reading of the day and the day before
    (`logbook.day`). Nothing is written, not even `policy/stays.json`."""
    lb = Logbook.find()
    day = date.today().isoformat() if a.day in (None, "today") else a.day
    try:
        data = day_reader.read(lb, day, _airports(a.airports))
    except (ValueError, stays.SettingsError) as e:
        print(f"day: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    for text in day_reader.rows(data):
        print(text)


def digest_arguments(sub: Subparsers) -> None:
    """`logbook digest`."""
    s = sub.add_parser(
        "digest",
        help="one day in 25 lines at most: where, with whom, what attached, flights, promises due, gaps,"
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
    s.set_defaults(fn=cmd_digest)


def cmd_digest(a: argparse.Namespace) -> None:
    """`digest [YYYY-MM-DD] [--json | --markdown]`: the day in at most `digest.LIMIT` lines — its
    shape in three (where, with whom confirmed, what attached), the flights, the open promises due
    within the week, the usual sources with no line, tomorrow's timed calendar entries and one
    closing question the owner answers in a word (`logbook.digest`, composed from the readers).
    Nothing is written and nothing is sent: delivery is a later decision (ADR 0005)."""
    lb = Logbook.find()
    day = _today() if a.day in (None, "today") else a.day
    try:
        data = digest_reader.read(lb, day, _airports(a.airports))
    except (ValueError, stays.SettingsError) as e:
        print(f"digest: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    for text in digest_reader.markdown(data) if a.markdown else digest_reader.rows(data):
        print(text)


def questions_arguments(sub: Subparsers) -> None:
    """`logbook questions`."""
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


def days_arguments(sub: Subparsers) -> None:
    """`logbook days`."""
    s = sub.add_parser(
        "days", help="a window of days one line each: night, km moved, flights, stays, people, health, gaps"
    )
    s.add_argument("--from", dest="since", metavar="YYYY-MM-DD", help="the first day (default the record's)")
    s.add_argument("--to", dest="until", metavar="YYYY-MM-DD", help="the last day (default the record's)")
    s.add_argument(
        "--airports",
        metavar="FILE",
        help=f"a CSV that adds to the airports table (else {flights.AIRPORTS_ENV})",
    )
    s.add_argument("--json", action="store_true", help="one JSON object per line (JSON Lines)")
    s.set_defaults(fn=cmd_days)


def cmd_days(a: argparse.Namespace) -> None:
    """`days [--from DAY] [--to DAY] [--json]`: a window of the record one line per day — the
    night, the kilometres moved, the flights, the stays with what attached, the people confirmed,
    the health triple, and a gap marker for a usual source with no line that day — streamed from
    readings of the window in chunks through the index (`logbook.days`), never one per day. The
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


def year_arguments(sub: Subparsers) -> None:
    """`logbook year`."""
    s = sub.add_parser(
        "year",
        help="one year read back: countries, trips, flights, places, people, health, keepers, a day a month",
    )
    s.add_argument("year", metavar="YYYY", help="the calendar year")
    s.add_argument(
        "--html", metavar="PATH", help="write one self-contained page (inline CSS, no script) instead"
    )
    s.add_argument(
        "--print",
        action="store_true",
        help="with --html: the paper edition — a cover, contents, one spread per month, for A4 and US Letter",
    )
    s.add_argument(
        "--airports",
        metavar="FILE",
        help=f"a CSV that adds to the airports table (else {flights.AIRPORTS_ENV})",
    )
    s.add_argument("--json", action="store_true", help="the Year as one JSON object, the picks' Days inside")
    s.set_defaults(fn=cmd_year)


def cmd_year(a: argparse.Namespace) -> None:
    """`year YYYY [--html PATH] [--json]`: the Year — days per country, nights, the trips, the
    flights, the places by nights, the people by days together, health and keepers by month, and
    twelve picks, one day a month, rendered with the day reader — composed from one reading of
    the year's days (`logbook.year`). `--html` writes one self-contained page. Nothing is written
    to the record."""
    lb = Logbook.find()
    try:
        if a.print:  # the paper edition (`logbook.print_page`), written where --html says
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
    if a.json:
        print(json.dumps(page, indent=2, ensure_ascii=False))
        return
    for text in pages.rows(page):
        print(text)


def search_arguments(sub: Subparsers) -> None:
    """`logbook search`."""
    s = sub.add_parser(
        "search",
        help='full-text search: words, "a phrase", kar* — literal, ranked, grouped by day, through the index',
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
        "--json", action="store_true", help="the query, the hits by day with rank, snippet, summary"
    )
    s.set_defaults(fn=cmd_search)


def cmd_search(a: argparse.Namespace) -> None:
    """`search TEXT [--since DAY] [--until DAY] [--kinds a,b] [--tier 1|2|3] [--limit N] [--json]`:
    full-text search through the index's FTS5 table (`logbook/search.py`): words and quoted
    phrases, literal (no stemming), case and accents aside; the hits ranked by bm25, grouped by
    local day, each as the row `show` prints with a snippet of the matching words under it. Tiers
    1 and 2 unless `--tier 3`. Nothing is written."""
    lb = Logbook.find()
    try:
        q = search.query(
            a.text,
            since=parse_day(a.since).isoformat() if a.since else None,
            until=parse_day(a.until).isoformat() if a.until else None,
            kinds=_csv(a.kinds),
            max_tier=a.tier,
            limit=a.limit,
        )
    except (search.QueryError, ValueError) as e:
        print(f"search: {e}", file=sys.stderr)
        sys.exit(2)
    tz = ZoneInfo(lb.meta["timezone"])
    try:
        with lb.index() as idx:
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
