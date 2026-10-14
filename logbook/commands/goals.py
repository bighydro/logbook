"""The owner's goals and the verdicts on them (RFC 0036): `goal add`, `goal review`, `goal list` and
`goal import`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..core import day_start, goals
from ..core.store import Logbook
from .common import Subparsers


def goal_arguments(sub: Subparsers) -> None:
    """`logbook goal add | review | list | import`."""
    s = sub.add_parser(
        "goal",
        help="a goal in your words; review one, list them, import a file of them",
        description="your goals, one line each in your own words (goal/v1, RFC 0036), and your verdict on"
        " one at a date (review/v1): advancing, stalled, done, let go or superseded; tier 2, never"
        " crossing a ceiling below it; a goal reworded is a new goal that supersedes the old one",
    )
    s.set_defaults(fn=cmd_goal)
    verbs = s.add_subparsers(dest="verb", required=True, metavar="<verb>")
    v = verbs.add_parser("add", help="write one goal: the words, its horizon, the day it starts")
    v.add_argument("text", metavar="TEXT", help="the goal, in your words")
    v.add_argument("--horizon", required=True, choices=goals.HORIZONS, help="what the goal is for")
    v.add_argument(
        "--from", dest="start", metavar="YYYY-MM-DD", help="the first day it holds for (default today)"
    )
    v.add_argument("--until", metavar="YYYY-MM-DD", help="the last day it holds for (default: open)")
    v.add_argument(
        "--supersedes",
        metavar="GOAL",
        help="the goal this one rewords or re-bounds, by id or seq as `goal list` prints it",
    )
    v = verbs.add_parser("review", help="your verdict on one goal at a date")
    v.add_argument("goal", metavar="GOAL", help="the goal, by id or seq as `goal list` prints it")
    v.add_argument("disposition", metavar="DISPOSITION", help=f"the verdict: {goals.words()}")
    v.add_argument("--note", metavar="TEXT", help="the verdict in your words")
    v.add_argument(
        "--at",
        metavar="YYYY-MM-DD|RFC3339",
        help="the day the verdict is about, if not today: its last minute, or the moment given (with an"
        f" offset or Z, e.g. {goals.AT_EXAMPLE}); a review written in October of August is on August",
    )
    v.add_argument(
        "--period",
        choices=goals.PERIODS,
        help="the stretch the verdict covers (default: the goal's horizon, a year for a life goal)",
    )
    v = verbs.add_parser("list", help="every standing goal with its latest review")
    v.add_argument("--open", action="store_true", help="only the goals still open")
    v.add_argument("--json", action="store_true", help="the goals as one JSON object, with line ids")
    v = verbs.add_parser(
        "import",
        help="the first backfill: a text file of goals, one per line (`text | horizon | from`)",
    )
    v.add_argument("file", metavar="FILE", help="plain text: a goal per line; `#` and blank lines skipped")
    v.add_argument("--horizon", choices=goals.HORIZONS, help="the horizon of a line that gives none")
    v.add_argument(
        "--from", dest="start", metavar="YYYY-MM-DD", help="the first day of a line that gives none (today)"
    )
    v.add_argument(
        "--review",
        metavar="DISPOSITION",
        help=f"one verdict for every goal imported: {goals.words()}",
    )
    v.add_argument("--at", metavar="YYYY-MM-DD|RFC3339", help="with --review: the day it is about")
    v.add_argument("--period", choices=goals.PERIODS, help="with --review: the stretch it covers")
    v.add_argument("--note", metavar="TEXT", help="with --review: the verdict in your words")
    v.add_argument("--dry-run", action="store_true", help="print what would be written; write nothing")


def cmd_goal(a: argparse.Namespace) -> None:
    """`goal add TEXT --horizon H [--from DAY] [--until DAY] [--supersedes GOAL]`, `goal review GOAL
    DISPOSITION [--note TEXT] [--at DAY|RFC3339] [--period P]`, `goal list [--open] [--json]`, `goal
    import FILE [--horizon H] [--from DAY] [--review DISPOSITION [--at …] [--period P] [--note TEXT]]
    [--dry-run]`. Each writer appends its profile's line under the writer lock (`logbook.core.goals`);
    a refusal is one sentence on stderr and exit 2, with nothing written."""
    lb = Logbook.find()
    try:
        if a.verb == "add":
            _add(lb, a)
        elif a.verb == "review":
            _review(lb, a)
        elif a.verb == "list":
            _list(lb, a)
        else:
            _import(lb, a)
    except goals.GoalError as e:
        print(f"goal {a.verb}: {e}", file=sys.stderr)
        sys.exit(2)


def _add(lb: Logbook, a: argparse.Namespace) -> None:
    line = goals.add(lb, a.text, a.horizon, a.start, a.until, a.supersedes)
    payload = line["payload"]
    print(f"#{line['seq']} {goals.SCHEMA}: {goals.goal_text(payload)}")
    tail = f"{goals.DOT}supersedes {payload['supersedes']}" if payload.get("supersedes") else ""
    print(f"  {line['id']}{goals.DOT}tier {line['tier']}{tail}")


def _review(lb: Logbook, a: argparse.Namespace) -> None:
    done = goals.review(lb, a.goal, a.disposition, a.period, a.note, a.at)
    goal_text = str((done.goal.get("payload") or {}).get("text"))
    days = day_start.of(lb.meta)
    if done.line is None:
        existing = done.existing or {}
        payload = existing.get("payload") or {}
        print(
            f"goal #{done.goal['seq']} has a {payload.get('period')} review on"
            f" {days.day_of(str(existing.get('at')))} already (#{existing.get('seq')},"
            f" {payload.get('disposition')}); nothing was written"
        )
        return
    line, payload = done.line, done.line["payload"]
    print(f"#{line['seq']} {goals.REVIEW_SCHEMA}: {goals.review_text(payload, goal_text)}")
    on = days.day_of(str(line["at"]))
    written = days.day_of(str(line["recorded_at"]))
    when = f"on {on}" + (f", written {written}" if written != on else "")
    print(
        f"  {when}{goals.DOT}{line['id']}" + (f"{goals.DOT}{payload['note']}" if payload.get("note") else "")
    )


def _list(lb: Logbook, a: argparse.Namespace) -> None:
    found = goals.listing(lb, a.open)
    if a.json:
        print(json.dumps(found, indent=2, ensure_ascii=False))
        return
    for text in goals.listing_rows(found):
        print(text)


def _import(lb: Logbook, a: argparse.Namespace) -> None:
    try:
        text = Path(a.file).expanduser().read_text(encoding="utf-8-sig")  # a BOM from a Windows editor
    except (OSError, UnicodeDecodeError) as e:
        raise goals.GoalError(f"cannot read {a.file}: {e}") from None
    done = goals.import_goals(lb, text, a.horizon, a.start, a.review, a.period, a.note, a.at, a.dry_run)
    count = _counts(done)
    if a.dry_run:
        for draft in done.goals:
            print(f"  goal    {goals.goal_text(draft['payload'])}")
        texts = {draft["id"]: draft["payload"]["text"] for draft in done.goals}
        for draft in done.reviews:
            print(f"  review  {goals.review_text(draft['payload'], texts.get(draft['payload']['goal']))}")
        print(f"would write {count}; nothing was written (--dry-run)")
        return
    seq = int(lb.meta["seq"])
    first = seq - len(done.goals) - len(done.reviews) + 1
    print(f"{count} written, #{first} to #{seq}")


def _counts(done: goals.Imported) -> str:
    n, m = len(done.goals), len(done.reviews)
    text = f"{n} goal{'s' if n != 1 else ''}"
    return f"{text} and {m} review{'s' if m != 1 else ''}" if m else text
