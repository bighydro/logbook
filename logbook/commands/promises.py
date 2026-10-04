"""The commitments and the tasks: `promises` and `tasks`."""

from __future__ import annotations

import argparse
import json
import sys
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from .. import promises, taskdone
from ..export import parse_day
from ..store import Logbook, now_utc, utc
from .common import Subparsers, _clock

if TYPE_CHECKING:
    from .. import judge


# What `promises --judge` names in its help. `logbook.judge` owns both and is imported only when the
# command runs, so `--help` loads no model code; a test holds these copies to it.
JUDGE_EXTRA = "openlogbook[judge]"
JUDGE_DEFAULT_MODEL = "mlx-community/Qwen2.5-7B-Instruct-4bit"


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
        help=f"judge the unjudged candidates with a local model first ({JUDGE_EXTRA}; never the network)",
    )
    s.add_argument("--limit", type=int, metavar="N", help="with --judge: judge at most N candidates this run")
    s.add_argument(
        "--model",
        default=JUDGE_DEFAULT_MODEL,
        metavar="NAME",
        help=f"with --judge: the MLX instruct model's repository (default {JUDGE_DEFAULT_MODEL})",
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
    from .. import judge

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


def tasks_arguments(sub: Subparsers) -> None:
    """`logbook tasks`."""
    s = sub.add_parser(
        "tasks",
        help="the tasks (task/v1), each as it stands; `--propose-done` the evidence an open one was done;"
        " `done <id>` closes one",
    )
    s.add_argument("--open", action="store_true", help="only the tasks still open")
    s.add_argument(
        "--propose-done",
        action="store_true",
        help="for every open task, the mail, calendar entry or transaction of the"
        f" {taskdone.WINDOW.days} days after it that reads as evidence it was done, by rules;"
        " proposals, with the evidence line's id",
    )
    s.add_argument("--json", action="store_true", help="the report as one JSON object, with line ids")
    s.set_defaults(fn=cmd_tasks, verb=None)
    verbs = s.add_subparsers(dest="verb", required=False)
    v = verbs.add_parser("done", help="mark one task done: appends a task/v1 line (RFC 0016), nothing else")
    v.add_argument("id", help="the task's id, as `tasks` prints it")
    v.add_argument(
        "--evidence",
        metavar="LINE-ID",
        help="the id of the line that shows it was done, kept under the task's extra",
    )
    v.set_defaults(fn=cmd_tasks)


def cmd_tasks(a: argparse.Namespace) -> None:
    """`tasks [--open] [--propose-done] [--json]`: the record's tasks (`task/v1`, RFC 0016), each as
    its latest standing snapshot (`logbook.taskdone`); `--propose-done` adds, for every open task,
    the mail, calendar entry or transaction of the fortnight after it that the rules read as evidence
    it was done, each with its line id, as proposals and never as facts. `tasks done <id> [--evidence
    LINE-ID]` appends the `task/v1` line that marks one done and nothing else."""
    lb = Logbook.find()
    if a.verb == "done":
        _tasks_done(lb, a)
        return
    report = taskdone.propose(lb) if a.propose_done else taskdone.read(lb)
    found = [t for t in report.tasks if not a.open or t.open]
    if a.json:
        out = {
            "open_only": bool(a.open),
            "propose_done": bool(a.propose_done),
            "window_days": report.window_days,
            "matcher": report.matcher or None,
            "tasks": [t.to_json() for t in found],
            "proposals": [p.to_json() for p in report.proposals],
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return
    zone = ZoneInfo(str(lb.meta["timezone"]))
    clock = lambda at: _clock(at, zone)  # noqa: E731
    texts = (
        taskdone.proposal_rows(report, clock)
        if a.propose_done
        else taskdone.rows(report, found, clock, open_only=bool(a.open))
    )
    for text in texts:
        print(text)


def _tasks_done(lb: Logbook, a: argparse.Namespace) -> None:
    report = taskdone.read(lb)
    found = next((t for t in report.tasks if t.id == a.id), None)
    if found is None:
        print(f"tasks: no task {a.id}; `logbook tasks` lists them with their ids", file=sys.stderr)
        sys.exit(2)
    if not found.open:
        print(f"already {found.status}: “{found.title}” (task line {found.line})")
        return
    if a.evidence is not None:
        with lb.index() as idx:
            line = idx.by_id(a.evidence)
        if line is None:
            print(
                f"tasks: no line {a.evidence} in the record; `--evidence` names a line by its id",
                file=sys.stderr,
            )
            sys.exit(2)
    at = utc(now_utc())
    line = lb.append(
        at=at,
        source="manual",
        kind=taskdone.TASK,
        tier=taskdone.TASK_TIER,
        payload=taskdone.draft_done(found, at, a.evidence),
    )
    tail = f", evidence {a.evidence}" if a.evidence else ""
    print(
        f"#{line['seq']} {line['at']}  done: “{found.title}”  ({found.day}, task/v1 line {line['id']}{tail})"
    )
