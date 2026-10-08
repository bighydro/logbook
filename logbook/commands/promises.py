"""The commitments and the tasks: `promises` and `tasks`."""

from __future__ import annotations

import argparse
import json
import sys
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from ..contrib import promises, taskdone
from ..core.export import parse_day
from ..core.store import Logbook, now_utc, utc
from .common import Subparsers, _clock

if TYPE_CHECKING:
    from ..labs import judge


# What `promises --judge` names in its help. `logbook.labs.judge` owns both and is imported only when the
# command runs, so `--help` loads no model code; a test holds these copies to it.
JUDGE_EXTRA = "openlogbook[judge]"
JUDGE_DEFAULT_MODEL = "mlx-community/Qwen2.5-7B-Instruct-4bit"


def promises_arguments(sub: Subparsers) -> None:
    """`logbook promises [done ID | tasks ...]`: the proposals, and the tasks they become."""
    s = sub.add_parser(
        "promises",
        help="promises you made and requests to you; done ID; tasks",
        description="what you promised (in mail and messages you sent, your turns of a transcript, your"
        " notes) and what you were asked (in mail and messages you received, others' turns), by rules,"
        " as proposals; `done <id>` closes one; `tasks`: the tasks (task/v1), each as it stands",
    )
    s.add_argument("--since", metavar="YYYY-MM-DD", help="only lines from this local day on")
    s.add_argument(
        "--open",
        action="store_true",
        help="hide the ones a `promises done` or a signed day (kept, missed, dropped) closed",
    )
    s.add_argument("--mine", action="store_true", help="only `I promised`")
    s.add_argument("--theirs", action="store_true", help="only `I was asked`")
    s.add_argument(
        "--source",
        action="append",
        metavar="KIND",
        help="read only these kinds: mail, message, transcript, note (repeat, or comma-separate)",
    )
    s.add_argument(
        "--all",
        action="store_true",
        help="every candidate the rules found: others' commitments, unresolved speakers, and what the"
        f" judge set aside (below confidence {promises.THRESHOLD:g})",
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
    tasks_arguments(verbs)


def cmd_promises(a: argparse.Namespace) -> None:
    """`promises [--since DAY] [--open] [--mine | --theirs] [--source KIND] [--all] [--judge [--limit N]
    [--model NAME] [--fetch-model]] [--json]`: what the owner promised and what they were asked, read
    from the mail, message, transcript and note lines by rules (`logbook.contrib.promises`), printed
    in two sections as proposals and never as facts. The rules alone by default; `--judge` runs a
    local model on the commitments it has not read yet (`logbook.labs.judge`, the verdicts kept in
    `policy/promises-cache.json`), and a judged non-commitment, or one below confidence 0.6, then
    leaves the sections; `--all` shows every candidate. `promises done <id>` appends the `task/v1`
    line (RFC 0016) that marks one done, so `--open` hides it; so does the signed day of the line it
    was read in, when the signature kept, missed or dropped it (RFC 0034 amendment 1; a carried one
    stays open). Nothing else is written to the chain."""
    from ..labs import judge

    since = a.since
    if since is not None:
        try:
            parse_day(since)
        except ValueError as e:
            print(f"promises: {e}", file=sys.stderr)
            sys.exit(2)
    if a.mine and a.theirs:
        print("promises: --mine and --theirs are one or the other", file=sys.stderr)
        sys.exit(2)
    sources = _sources(a.source)
    lb = Logbook.find()
    if a.verb == "done":
        _promises_done(lb, a)
        return
    report = promises.extract(lb, since, sources=sources)
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
    found = [
        p
        for p in report.proposals
        if (not a.open or p.status == "open")
        and (a.all or (p.shows and p.role in (promises.PROMISE, promises.ASKED)))
        and (not a.mine or p.role == promises.PROMISE)
        and (not a.theirs or p.role == promises.ASKED)
    ]
    if a.json:
        out = {
            "since": report.since,
            "open_only": bool(a.open),
            "mine_only": bool(a.mine),
            "theirs_only": bool(a.theirs),
            "sources": list(report.sources),
            "all": bool(a.all),
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
        every=bool(a.all),
        judge=None if judged is None else judged.to_json(),
        mine=bool(a.mine),
        theirs=bool(a.theirs),
    ):
        print(text)


def _sources(given: list[str] | None) -> list[str] | None:
    """`--source` as the kinds to read, in `promises.SOURCES` order; None when none was given; a
    kind that is not one the reader knows stops the command naming it."""
    if not given:
        return None
    wanted = [k.strip().casefold() for value in given for k in value.split(",") if k.strip()]
    unknown = [k for k in wanted if k not in promises.SOURCES]
    if unknown:
        print(
            f"promises: --source takes {', '.join(promises.SOURCES)}, not {', '.join(unknown)}",
            file=sys.stderr,
        )
        sys.exit(2)
    return [k for k in promises.SOURCES if k in set(wanted)]


def _promises_done(lb: Logbook, a: argparse.Namespace) -> None:
    report = promises.extract(lb)
    found = next((p for p in report.proposals if p.id == a.id), None)
    if found is None:
        print(f"promises: no proposal {a.id}; `logbook promises` lists them with their ids", file=sys.stderr)
        sys.exit(2)
    if found.closed_by:
        print(f"already done: \u201c{found.match.quote}\u201d (task line {found.closed_by})")
        return
    if found.status != "open" and found.disposition is not None:  # the signed day kept, missed or dropped it
        d = found.disposition
        print(
            f"already {d.value} on {d.day}: \u201c{found.match.quote}\u201d (signed-day line {d.line});"
            " a task line would add nothing"
        )
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
    """`logbook promises tasks` (`logbook tasks` until 0.6)."""
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
    verbs = s.add_subparsers(dest="task_verb", required=False)
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
    its latest standing snapshot (`logbook.contrib.taskdone`); `--propose-done` adds, for every open task,
    the mail, calendar entry or transaction of the fortnight after it that the rules read as evidence
    it was done, each with its line id, as proposals and never as facts. `tasks done <id> [--evidence
    LINE-ID]` appends the `task/v1` line that marks one done and nothing else."""
    lb = Logbook.find()
    if a.task_verb == "done":
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
