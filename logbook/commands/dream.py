"""`logbook dream`: a model reads a day and drafts it (RFC 0036, `logbook.contrib.dream`)."""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

from ..contrib import dream as dreaming
from ..contrib import synthesis
from ..core import drafts, flights, stays
from ..core.store import HeadMoved, Logbook
from .common import Subparsers, _airports

VERB = "day"
DEFAULT_DAYS = 14


def dream_arguments(sub: Subparsers) -> None:
    """`logbook dream day DAY [--dry-run] [--show-prompt]`, `logbook dream --catch-up [--days N]`."""
    s = sub.add_parser(
        "dream",
        help="a model reads one day and drafts it, every sentence with its lines",
        description="`dream day YYYY-MM-DD`: a model reads the day under the `dream` entry of"
        " policy/crossing.json and writes one draft/v1 line, the day in a paragraph, the threads it moved,"
        " two questions, the people and promises it proposes, every sentence pointing at the lines it came"
        " from; a proposal, never a fact, shown on the Day above your note. `dream --catch-up` dreams each"
        " of the last N days that has no draft or whose lines changed, then synthesizes each transcript of"
        " those days that has none (`transcript synthesize`). The model is LOGBOOK_DREAM_ENDPOINT,"
        " LOGBOOK_DREAM_MODEL and, for a cloud model, LOGBOOK_DREAM_KEY (docs/dream.md)",
    )
    s.add_argument("verb", nargs="?", metavar="day", help="`day`, then the local day to dream")
    s.add_argument("day", nargs="?", metavar="YYYY-MM-DD", help="with day: the local day; `yesterday` works")
    s.add_argument("--dry-run", action="store_true", help="ask the model and check its answer; write nothing")
    s.add_argument("--show-prompt", action="store_true", help="print the prompt and the material sent")
    s.add_argument(
        "--catch-up",
        action="store_true",
        help="dream each of the last N days that needs it, then synthesize their transcripts that have no"
        " draft; one line each",
    )
    s.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        metavar="N",
        help=f"with --catch-up: how many days back (default {DEFAULT_DAYS})",
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
    if a.catch_up:
        if a.verb is not None or a.day is not None:
            print("dream: --catch-up takes no day; `dream day YYYY-MM-DD` dreams one", file=sys.stderr)
            sys.exit(2)
        _catch_up(lb, a)
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


def _catch_up(lb: Logbook, a: argparse.Namespace) -> None:
    """The days, one row each; then each transcript of those days that no model has synthesized,
    one row each sent (`synthesis.catch_up`); then the count, with the transcripts the ceiling held
    back and those without their text. Exit 1 when a day or a transcript was refused."""
    if a.days < 1:
        print("dream: --days N is at least 1", file=sys.stderr)
        sys.exit(2)
    today = dreaming.today()
    try:
        outcomes = dreaming.catch_up(lb, a.days, today=today)
        caught = synthesis.catch_up(lb, dreaming.days_to_catch_up(today, a.days))
    except dreaming.DreamError as e:
        print(f"dream: {e}", file=sys.stderr)
        sys.exit(2)
    outcomes += caught.outcomes
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
    if counted["refused"]:
        sys.exit(1)
