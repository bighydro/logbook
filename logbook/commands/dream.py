"""`logbook dream`: a model reads a day, a journey or a week and drafts it (RFC 0036,
`logbook.contrib.dream`, `dream_journey`, `dream_week`)."""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

from ..contrib import dream as dreaming
from ..contrib import dream_journey, dream_person, dream_week, synthesis
from ..core import drafts, flights, stays
from ..core.store import HeadMoved, Logbook
from .common import Subparsers, _airports

VERB = "day"
JOURNEY, WEEK = "journey", "week"
PERSON = "person"  # `dream person NAME`: under the `relationship` entry (RFC 0036 amendment 1)
VERBS = (VERB, JOURNEY, WEEK, PERSON)
DEFAULT_DAYS = 14


def dream_arguments(sub: Subparsers) -> None:
    """`logbook dream day DAY [--dry-run] [--show-prompt]`, `logbook dream journey ID`, `logbook dream
    week [DAY|YYYY-Www]`, `logbook dream --catch-up [--days N] [--since DAY]`."""
    s = sub.add_parser(
        "dream",
        help="a model drafts a day, journey, week or person, each sentence cited",
        description="`dream day YYYY-MM-DD`: a model reads the day under the `dream` entry of"
        " policy/crossing.json and writes one draft/v1 line, the day in a paragraph, the threads it moved,"
        " two questions, the people and promises it proposes, every sentence pointing at the lines it came"
        " from; a proposal, never a fact, shown on the Day above your note. `dream journey ID` drafts a"
        " journey once it has closed (shown by `show trips` and `show trip`); `dream week [DAY|YYYY-Www]`"
        " drafts an ISO week once its Sunday is over, from its seven days and their drafts (shown on the"
        " Day of its Sunday). `dream --catch-up` dreams each of the last N days that has no draft or whose"
        f" lines changed, then synthesizes each call of the last {synthesis.WINDOW_DAYS} days that has none"
        " (`transcript synthesize`), or of the days from --since DAY on, an older call counted and named,"
        " never sent; then each journey that came home and each week whose Sunday is among the N days, when"
        " it needs it. The model is LOGBOOK_DREAM_ENDPOINT, LOGBOOK_DREAM_MODEL and, for a cloud model,"
        " LOGBOOK_DREAM_KEY (docs/dream.md)"
        ". `dream person NAME [--window FROM TO]` drafts what passed between you and one person, from their"
        " lines only, under the `relationship` entry of policy/crossing.json and never the `dream` entry"
        f" (default window: the {dream_person.DEFAULT_DAYS} days that end today; docs/relationship.md)",
    )
    s.add_argument(
        "verb",
        nargs="?",
        metavar="day|journey|week|person",
        help="`day` and the local day, `journey` and a journey's id, `week` and a week, `person` and a"
        " person",
    )
    s.add_argument(
        "day",
        nargs="?",
        metavar="YYYY-MM-DD|ID|YYYY-Www|NAME",
        help="with day: the local day, `yesterday` works; with journey: its id (`show trips` prints it) or"
        " any day of it; with week: any day of it or YYYY-Www (default the last week whose Sunday is over);"
        " with person: the person, as `people NAME` finds them",
    )
    s.add_argument("--dry-run", action="store_true", help="ask the model and check its answer; write nothing")
    s.add_argument(
        "--window",
        nargs=2,
        metavar=("FROM", "TO"),
        help=f"with person: the local days read, both inclusive (default the {dream_person.DEFAULT_DAYS}"
        " that end today)",
    )
    s.add_argument("--show-prompt", action="store_true", help="print the prompt and the material sent")
    s.add_argument(
        "--catch-up",
        action="store_true",
        help="dream each of the last N days that needs it, then synthesize the calls of the last"
        f" {synthesis.WINDOW_DAYS} of them that have no draft; one line each",
    )
    s.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        metavar="N",
        help=f"with --catch-up: how many days back (default {DEFAULT_DAYS})",
    )
    s.add_argument(
        "--since",
        metavar="YYYY-MM-DD",
        help="with --catch-up: synthesize the calls from this local day on, not only the last"
        f" {synthesis.WINDOW_DAYS} days' (the days dreamed are still the last N)",
    )
    s.add_argument(
        "--airports",
        metavar="FILE",
        help=f"a CSV that adds to the airports table (else {flights.AIRPORTS_ENV})",
    )
    s.set_defaults(fn=cmd_dream)


def cmd_dream(a: argparse.Namespace) -> None:
    """`dream day DAY`: one draft line, or nothing and one sentence why; `dream --catch-up`: one line
    per day, `dreamed`, `unchanged`, `empty` or `refused` and why. The policy's refusal (no `dream`
    entry, an expired one) and the endpoint's (a variable not set) exit 2 before anything is read;
    a day the model's answer failed exits 1 (`--catch-up`: when any day did). A head that moved under
    the reading is the record's HeadMoved, one sentence, exit 2."""
    lb = Logbook.find()
    if a.window is not None and a.verb != PERSON:
        print("dream: --window goes with `dream person NAME`", file=sys.stderr)
        sys.exit(2)
    if a.since is not None and not a.catch_up:
        print("dream: --since goes with --catch-up: dream --catch-up --since 2026-06-01", file=sys.stderr)
        sys.exit(2)
    if a.catch_up:
        if a.verb is not None or a.day is not None:
            print("dream: --catch-up takes no day; `dream day YYYY-MM-DD` dreams one", file=sys.stderr)
            sys.exit(2)
        _catch_up(lb, a)
        return
    if a.verb == JOURNEY:
        _dream_unit(lb, a, JOURNEY)
        return
    if a.verb == WEEK:
        _dream_unit(lb, a, WEEK)
        return
    if a.verb == PERSON:
        _dream_unit(lb, a, PERSON)
        return
    if a.verb != VERB or a.day is None:
        print("dream: the day is needed: logbook dream day 2026-06-13, or dream --catch-up", file=sys.stderr)
        sys.exit(2)
    day = (date.today() - timedelta(days=1)).isoformat() if a.day == "yesterday" else a.day
    try:
        found = dreaming.dream(
            lb,
            day,
            airports=_airports(a.airports),
            dry_run=a.dry_run,
            say=print if a.show_prompt else None,
        )
    except (dreaming.DreamError, HeadMoved, ValueError, stays.SettingsError) as e:
        print(f"dream: {e}", file=sys.stderr)
        sys.exit(1 if isinstance(e, dreaming.AnswerError) else 2)
    p = found.payload
    n = len(p["segments"])
    unsupported = sum(1 for s in p["segments"] if s.get("unsupported"))
    counts = f"{n} segment{'s' if n != 1 else ''}" + (f", {unsupported} unsupported" if unsupported else "")
    if found.proposals:
        k = len(found.proposals)
        counts += f"{drafts.DOT}{k} proposed event{'s' if k != 1 else ''}"
    if found.line is None:
        print(f"{found.day}: dry run, nothing written{drafts.DOT}tier {found.tier}{drafts.DOT}{counts}")
    else:
        line = found.line
        print(
            f"{found.day}: dreamed as #{line['seq']} {drafts.SCHEMA}{drafts.DOT}{line['source']}"
            f"{drafts.DOT}tier {found.tier}{drafts.DOT}{p['read_count']} lines read at {p['read_head'][:8]}"
            f"{drafts.DOT}{counts}"
        )
        if p.get("supersedes"):
            print(f"  dreamed again: supersedes {p['supersedes']}")
    shown = {
        "segments": [drafts.segment_json(s, None) for s in p["segments"]],
        "proposals": found.proposals,
    }
    parts = p["extra"]["parts"]
    for segment, part in zip(shown["segments"], parts, strict=True):
        segment["part"] = part
    for text in drafts.rows(shown, indent="  "):
        print(text)
    if found.dropped:
        k = sum(found.dropped.values())
        why = ", ".join(f"{reason} {count}" for reason, count in found.dropped.items())
        print(f"  {k} proposed event{'s' if k != 1 else ''} dropped: {why}")
    if found.proposals and found.line is not None:
        print(f"  `logbook day sign {found.day} --accept N` writes a proposed event into the record")
    print("  a draft is a proposal: your signature and your notes are the facts (`day sign`)")


def _dream_unit(lb: Logbook, a: argparse.Namespace, unit: str) -> None:
    """`dream journey ID`, `dream week [DAY|YYYY-Www]`: one draft line, or nothing and one sentence why;
    exit 1 when the model's answer failed, 2 for every other refusal (the policy, the endpoint, a journey
    that has not closed, a week that is not over or lacks a day's draft)."""
    if unit == JOURNEY and a.day is None:
        print(
            "dream journey: the journey is needed: its id as `show trips` prints it, or any day of it",
            file=sys.stderr,
        )
        sys.exit(2)
    if unit == PERSON and a.day is None:
        print('dream person: the person is needed: dream person "Ola Nordmann"', file=sys.stderr)
        sys.exit(2)
    try:
        if unit == PERSON:
            found = dream_person.run(
                lb,
                a.day,
                None if a.window is None else (a.window[0], a.window[1]),
                dry_run=a.dry_run,
                say=print if a.show_prompt else None,
            )
        elif unit == JOURNEY:
            found = dream_journey.run(
                lb,
                a.day,
                airports=_airports(a.airports),
                dry_run=a.dry_run,
                say=print if a.show_prompt else None,
            )
        else:
            found = dream_week.run(
                lb,
                a.day,
                airports=_airports(a.airports),
                dry_run=a.dry_run,
                say=print if a.show_prompt else None,
            )
    except (dreaming.DreamError, HeadMoved, ValueError, stays.SettingsError) as e:
        print(f"dream {unit}: {e}", file=sys.stderr)
        sys.exit(1 if isinstance(e, dreaming.AnswerError) else 2)
    p = found.payload
    n = len(p["segments"])
    unsupported = sum(1 for s in p["segments"] if s.get("unsupported"))
    counts = f"{n} segment{'s' if n != 1 else ''}" + (f", {unsupported} unsupported" if unsupported else "")
    if found.line is None:
        print(f"{found.day}: dry run, nothing written{drafts.DOT}tier {found.tier}{drafts.DOT}{counts}")
    else:
        line = found.line
        print(
            f"{found.day}: dreamed as #{line['seq']} {drafts.SCHEMA}{drafts.DOT}{line['source']}"
            f"{drafts.DOT}tier {found.tier}{drafts.DOT}{p['read_count']} lines read at {p['read_head'][:8]}"
            f"{drafts.DOT}{counts}"
        )
        if p.get("supersedes"):
            print(f"  dreamed again: supersedes {p['supersedes']}")
    shown = {"segments": [drafts.segment_json(s, None) for s in p["segments"]], "proposals": []}
    for segment, part in zip(shown["segments"], p["extra"]["parts"], strict=True):
        segment["part"] = part
    for text in drafts.rows(shown, indent="  "):
        print(text)
    for text in drafts.extra_rows(p, indent="  "):
        print(text)
    print("  a draft is a proposal: your notes, your stars, your names and your reviews are the facts")


def _catch_up(lb: Logbook, a: argparse.Namespace) -> None:
    """The days, one row each; then each week whose seven days are among them (`dream_week.catch_up`,
    which reads the days' drafts); then each call of the last `synthesis.WINDOW_DAYS` days (from
    `--since` when given) that no model has synthesized, one row each sent (`synthesis.catch_up`); then
    each journey that came home on one of the days (`dream_journey.catch_up`, which reads the calls'
    syntheses); then the count, with the transcripts the ceiling held back and those without their
    text; then one line for the calls before the window that have no synthesis, never sent. Exit 1
    when a day, a week, a transcript or a journey was refused."""
    if a.days < 1:
        print("dream: --days N is at least 1", file=sys.stderr)
        sys.exit(2)
    today = dreaming.today()
    try:
        first, last = synthesis.window(today, a.days, a.since)
    except ValueError as e:
        print(f"dream: --since: {e}", file=sys.stderr)
        sys.exit(2)
    try:
        outcomes = dreaming.catch_up(lb, a.days, today=today)
        outcomes += dream_week.catch_up(lb, a.days, today, airports=_airports(a.airports))  # reads the days'
        caught = synthesis.catch_up(lb, first, last)
        outcomes += caught.outcomes
        outcomes += dream_journey.catch_up(
            lb, a.days, today, airports=_airports(a.airports)
        )  # and the calls'
    except dreaming.DreamError as e:
        print(f"dream: {e}", file=sys.stderr)
        sys.exit(2)
    for row in outcomes:
        print(f"{row.day}  {row.state:<9} {row.detail}")
    states = ("dreamed", "unchanged", "empty", synthesis.SYNTHESIZED, "refused")
    counted = {state: sum(1 for row in outcomes if row.state == state) for state in states}
    said = [f"{n} {state}" for state, n in counted.items() if n]
    if caught.held_back:
        n = caught.held_back
        said.append(f"{n} transcript{'s' if n != 1 else ''} held back above max_tier {caught.max_tier}")
    if caught.no_text:
        n = caught.no_text
        said.append(f"{n} transcript{'s' if n != 1 else ''} without their text")
    print(drafts.DOT.join(said) or "no days")
    left = None if caught.left is None else synthesis.before_text(caught.left)
    if left is not None:
        print(left)
    if counted["refused"]:
        sys.exit(1)
