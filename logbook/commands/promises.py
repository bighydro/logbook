"""`promises`: what was promised in a transcript or a note, judged, and `promises done`."""

from __future__ import annotations

import argparse
import json
import sys
from zoneinfo import ZoneInfo

from .. import judge, promises
from ..export import parse_day
from ..store import Logbook, now_utc, utc
from .common import Subparsers, _clock


def promises_arguments(sub: Subparsers) -> None:
    """`logbook promises`."""
    s = sub.add_parser(
        "promises",
        help="commitments the transcripts and notes suggest, by rules, as proposals; `done <id>` closes one",
    )
    s.add_argument("--since", metavar="YYYY-MM-DD", help="only lines from this local day on")
    s.add_argument("--open", action="store_true", help="hide the ones a `promises done` closed")
    s.add_argument(
        "--all",
        action="store_true",
        help="every candidate the rules found, not only the judged commitments"
        f" (confidence {promises.THRESHOLD:g} or above)",
    )
    s.add_argument(
        "--judge",
        action="store_true",
        help=f"judge the unjudged candidates with a local model first ({judge.EXTRA}; never the network)",
    )
    s.add_argument("--limit", type=int, metavar="N", help="with --judge: judge at most N candidates this run")
    s.add_argument(
        "--model",
        default=judge.DEFAULT_MODEL,
        metavar="NAME",
        help=f"with --judge: the MLX instruct model's repository (default {judge.DEFAULT_MODEL})",
    )
    s.add_argument(
        "--fetch-model",
        action="store_true",
        help="with --judge: download the model if it is not on this machine (the only network use)",
    )
    s.add_argument("--json", action="store_true", help="the report as one JSON object, with line ids")
    s.set_defaults(fn=cmd_promises, verb=None)
    verbs = s.add_subparsers(dest="verb", required=False)
    v = verbs.add_parser("done", help="mark one proposal done: appends a task/v1 line (RFC 0016)")
    v.add_argument("id", help="the proposal's id, as `promises` prints it")
    v.add_argument("--note", metavar="TEXT", help="your words on how it was kept, kept in the task's notes")
    v.set_defaults(fn=cmd_promises)


def cmd_promises(a: argparse.Namespace) -> None:
    """`promises [--since DAY] [--open] [--all] [--judge [--limit N] [--model NAME] [--fetch-model]]
    [--json]`: the commitments the transcript and note lines suggest, found by rules
    (`logbook.promises`), printed as proposals and never as facts. By default the ones a local model
    judged a commitment at confidence 0.6 or above (`logbook.judge`, the verdicts kept in
    `policy/promises-cache.json`); `--all` every candidate; `--judge` runs the model on the unjudged
    ones first, at most `--limit`. `promises done <id>` appends the `task/v1` line (RFC 0016) that
    marks one done, so `--open` hides it. Nothing else is written to the chain."""
    since = a.since
    if since is not None:
        try:
            parse_day(since)
        except ValueError as e:
            print(f"promises: {e}", file=sys.stderr)
            sys.exit(2)
    lb = Logbook.find()
    if a.verb == "done":
        _promises_done(lb, a)
        return
    report = promises.extract(lb, since)
    judged: judge.Judged | None = None
    try:
        if a.judge:
            try:
                engine = judge.detect(a.model)
            except judge.EngineMissing as e:
                print(f"promises: {e}", file=sys.stderr)
                sys.exit(2)
            judged = judge.run(
                lb.root,
                report,
                engine,
                limit=a.limit,
                fetch_model=bool(a.fetch_model),
                progress=lambda text: print(text, file=sys.stderr),
            )
        report = promises.with_judgements(report, judge.read_cache(lb.root))
    except (judge.ModelMissing, judge.CacheError) as e:
        print(f"promises: {e}", file=sys.stderr)
        sys.exit(2)
    judged_only = not a.all
    found = [
        p
        for p in report.proposals
        if (not a.open or p.status == "open")
        and (not judged_only or (p.judgement is not None and p.judgement.shows()))
    ]
    if a.json:
        out = {
            "since": report.since,
            "open_only": bool(a.open),
            "judged_only": judged_only,
            "threshold": promises.THRESHOLD,
            "extractor": report.extractor,
            "judge": None if judged is None else judged.to_json(),
            "unjudged": len(report.unjudged),
            "proposals": [p.to_json() for p in found],
            "skipped": report.skipped,
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return
    zone = ZoneInfo(str(lb.meta["timezone"]))
    for text in promises.rows(
        report,
        found,
        lambda at: _clock(at, zone),
        open_only=bool(a.open),
        judged_only=judged_only,
        judge=None if judged is None else judged.to_json(),
    ):
        print(text)


def _promises_done(lb: Logbook, a: argparse.Namespace) -> None:
    report = promises.extract(lb)
    found = next((p for p in report.proposals if p.id == a.id), None)
    if found is None:
        print(f"promises: no proposal {a.id}; `logbook promises` lists them with their ids", file=sys.stderr)
        sys.exit(2)
    if found.closed_by:
        print(f"already done: \u201c{found.match.quote}\u201d (task line {found.closed_by})")
        return
    at = utc(now_utc())
    line = lb.append(
        at=at,
        source="manual",
        kind=promises.TASK,
        tier=promises.TASK_TIER,
        payload=promises.draft_done(found, at, report.extractor, a.note),
    )
    print(
        f"#{line['seq']} {line['at']}  done: \u201c{found.match.quote}\u201d"
        f"  ({found.day}, task/v1 line {line['id']})"
    )
