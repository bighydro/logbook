"""`logbook transcript synthesize`: a model reads one transcript and drafts it (RFC 0036,
`logbook.contrib.synthesis`)."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from ..contrib import dream as dreaming
from ..contrib import synthesis
from ..core import day_start, drafts
from ..core.store import HeadMoved, Logbook
from .common import Subparsers

VERB = "synthesize"


def transcript_arguments(sub: Subparsers) -> None:
    """`logbook transcript synthesize ID|--day DAY [--dry-run] [--show-prompt] [--again]`."""
    s = sub.add_parser(
        "transcript",
        help="synthesize: a model drafts one call, actions on top, items cited",
        description="`transcript synthesize ID`: a model reads one transcript under the `dream` entry of"
        " policy/crossing.json and writes one draft/v1 line about the call (unit event): the actions"
        " proposed on top with assignee and due hint, the topics consolidated across the call, the"
        " decisions, the open threads and a short personal part, every item pointing at the utterances it"
        " rests on or marked unsupported. `--day YYYY-MM-DD` synthesizes each transcript of the day; a"
        " transcript above the entry's max_tier stays home. A proposal, never a fact: the transcript is the"
        " record. The model is the dream's: LOGBOOK_DREAM_ENDPOINT, LOGBOOK_DREAM_MODEL and, for a cloud"
        " model, LOGBOOK_DREAM_KEY (docs/transcript-synthesis.md)",
    )
    s.add_argument("verb", nargs="?", metavar="synthesize", help="`synthesize`, then the transcript or --day")
    s.add_argument(
        "id",
        nargs="?",
        metavar="ID",
        help="the transcript line: its id, #seq, or the last 8 characters of its id",
    )
    s.add_argument("--day", metavar="YYYY-MM-DD", help="each transcript of this local day; `yesterday` works")
    s.add_argument("--dry-run", action="store_true", help="ask the model and check its answer; write nothing")
    s.add_argument("--show-prompt", action="store_true", help="print the prompt and the material sent")
    s.add_argument(
        "--again",
        action="store_true",
        help="ask again when this model already synthesized the call; the new draft supersedes",
    )
    s.set_defaults(fn=cmd_transcript)


def cmd_transcript(a: argparse.Namespace) -> None:
    """`synthesize ID`: one draft line, or nothing and one sentence why; a home video's soundtrack (no
    call), the policy's refusal (no `dream` entry, an expired one), the endpoint's, a transcript above
    the ceiling or without its text exit 2 before anything is sent; an answer that failed exits 1.
    `synthesize --day DAY`: one block or row per transcript and a count; exit 1 when any answer was
    refused."""
    if a.verb != VERB:
        print("transcript: the verb is synthesize: logbook transcript synthesize ID", file=sys.stderr)
        sys.exit(2)
    if (a.id is None) == (a.day is None):
        print(
            "transcript synthesize: name one transcript (ID, #seq) or one day (--day YYYY-MM-DD), not both",
            file=sys.stderr,
        )
        sys.exit(2)
    lb = Logbook.find()
    say: Callable[[str], None] | None = print if a.show_prompt else None
    if a.day is not None:
        _day(lb, a, say)
        return
    try:
        line = synthesis.find(lb, a.id)
        made = synthesis.synthesize(lb, line, dry_run=a.dry_run, again=a.again, say=say)
    except (dreaming.DreamError, HeadMoved, ValueError) as e:
        print(f"transcript synthesize: {e}", file=sys.stderr)
        sys.exit(1 if isinstance(e, dreaming.AnswerError) else 2)
    for text in block(made, synthesis.head_of(lb, made.transcript)):
        print(text)


def _day(lb: Logbook, a: argparse.Namespace, say: Callable[[str], None] | None) -> None:
    day = a.day
    if day == "yesterday":
        day = (day_start.of(lb.meta).today(datetime.now(UTC)) - timedelta(days=1)).isoformat()
    try:
        tried = synthesis.synthesize_day(lb, day, dry_run=a.dry_run, again=a.again, say=say)
    except (dreaming.DreamError, ValueError) as e:
        print(f"transcript synthesize: {e}", file=sys.stderr)
        sys.exit(2)
    if not tried:
        print(f"no transcript on {day}")
        return
    for row in tried:
        head = synthesis.head_of(lb, row.transcript)
        if row.synthesis is not None:
            for text in block(row.synthesis, head):
                print(text)
        else:
            print(f"{head}: {row.state}: {row.detail}")
    counted = {state: sum(1 for row in tried if row.state == state) for state in synthesis.STATES}
    print(drafts.DOT.join(f"{n} {state}" for state, n in counted.items() if n))
    if counted[synthesis.REFUSED]:
        sys.exit(1)


def block(made: synthesis.Synthesis, head: str) -> list[str]:
    """What a synthesis prints: one line saying what happened, then one row per segment, actions on
    top, then the sentence that says what a synthesis is."""
    p = made.payload
    n = len(p.get("segments") or [])
    unsupported = sum(1 for s in p.get("segments") or [] if isinstance(s, dict) and s.get("unsupported"))
    counts = f"{n} segment{'s' if n != 1 else ''}" + (f", {unsupported} unsupported" if unsupported else "")
    out: list[str] = []
    if made.state == synthesis.UNCHANGED and made.line is not None:
        out.append(
            f"{head}: unchanged: synthesized by {made.line['source']} as #{made.line['seq']}; nothing sent"
            f" (--again asks once more)"
        )
    elif made.line is None:
        out.append(f"{head}: dry run, nothing written{drafts.DOT}tier {made.tier}{drafts.DOT}{counts}")
    else:
        line = made.line
        utterances = (p.get("extra") or {}).get("utterances")
        out.append(
            f"{head}: synthesized as #{line['seq']} {drafts.SCHEMA}{drafts.DOT}{line['source']}"
            f"{drafts.DOT}tier {made.tier}{drafts.DOT}{utterances} utterances read at {p['read_head'][:8]}"
            f"{drafts.DOT}{counts}"
        )
        if p.get("supersedes"):
            out.append(f"  synthesized again: supersedes {p['supersedes']}")
    out.extend(drafts.synthesis_rows(drafts.synthesis_segments(p, None), indent="  "))
    out.append(f"  {synthesis.PROPOSAL}")
    return out
