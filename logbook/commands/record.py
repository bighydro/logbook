"""The record itself: `init`, `setup`, `stats`, `index`, `verify`, `doctor`, `backup`, `migrate`,
`retract`, `repair` and `demo`, the synthetic record to try the commands on."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import zoneinfo
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path, PurePath
from typing import Any

from .. import FORMAT
from ..contrib import demo
from ..core import health, repair
from ..core.store import CodeCheckoutError, FormatError, Logbook
from .common import Subparsers, _plural, _progress, _under_home

_LOCALTIME = "/etc/localtime"


def _zone_or_none(candidate: object) -> str | None:
    """The candidate when it names a real IANA zone, else None."""
    if not isinstance(candidate, str) or not candidate:
        return None
    try:
        zoneinfo.ZoneInfo(candidate)
    except (KeyError, ValueError, OSError):  # ZoneInfoNotFoundError is a KeyError
        return None
    return candidate


def _detect_timezone() -> str | None:
    """The local IANA zone, or None when nothing on this machine says which it is.

    datetime.now().astimezone() has no zone name on macOS (issue #25), so /etc/localtime
    comes first: it is a symlink into a zoneinfo tree whose tail is the zone name.
    """
    parts = PurePath(os.path.realpath(_LOCALTIME)).parts  # Windows: backslash-split
    if "zoneinfo" in parts:
        after_last = len(parts) - parts[::-1].index("zoneinfo")
        if zone := _zone_or_none("/".join(parts[after_last:])):
            return zone
    if zone := _zone_or_none(getattr(datetime.now().astimezone().tzinfo, "key", None)):
        return zone
    return _zone_or_none(os.environ.get("TZ"))


def _tz_default() -> str:
    return _detect_timezone() or "UTC"


def init_arguments(sub: Subparsers) -> None:
    """`logbook init`."""
    s = sub.add_parser("init", help="create a logbook (default ~/Logbook)")
    s.add_argument("path", nargs="?")
    s.add_argument("--timezone")
    s.set_defaults(fn=cmd_init)


def cmd_init(a: argparse.Namespace) -> None:
    root = Path(a.path or Path.home() / "Logbook").expanduser()
    timezone_name, hint = a.timezone, ""
    if not timezone_name:
        timezone_name = _detect_timezone()
    if not timezone_name:
        timezone_name = "UTC"
        hint = " (could not detect; pass --timezone Europe/Zurich to change)"
    try:
        lb = Logbook.init(root, timezone_name)
    except CodeCheckoutError as e:
        print(f"refusing to init: {e}", file=sys.stderr)
        sys.exit(2)
    print(
        f"created {_under_home(lb.root)}\ntimezone: {timezone_name}{hint}\n"
        f'Drop any export into {_under_home(lb.root / "inbox")}, or: logbook add "what happened"'
    )


def _file_progress(n_files: int) -> Callable[[str, int, int, float], None]:
    """`verify --progress`: one line per month file in path order, on stderr, so
    stdout stays the one line it always was. `file i of N` is that path rank."""
    i = 0

    def report(file: str, n: int, total: int, elapsed: float) -> None:
        nonlocal i
        i += 1
        print(
            f"  file {i} of {n_files}: {file}: {n:,} lines ({total:,} so far, {elapsed:,.0f}s)",
            file=sys.stderr,
        )

    return report


def retract_arguments(sub: Subparsers) -> None:
    """`logbook retract`."""
    s = sub.add_parser("retract", help="take back line SEQ with a new line; nothing is rewritten")
    s.add_argument("seq", type=int)
    s.add_argument("reason")
    s.set_defaults(fn=cmd_retract)


def cmd_retract(a: argparse.Namespace) -> None:
    lb = Logbook.find()
    try:
        line = lb.retract(a.seq, a.reason)
    except ValueError as e:
        print(f"retract: {e}", file=sys.stderr)
        sys.exit(2)
    print(f"#{line['seq']} {line['at']}  retracted #{a.seq}: {a.reason}")


def repair_arguments(sub: Subparsers) -> None:
    """`logbook repair`."""
    s = sub.add_parser("repair", help="append the lines that put a known mistake right; nothing is rewritten")
    verbs = s.add_subparsers(dest="verb", required=True)
    v = verbs.add_parser(
        "health-units",
        help="retract apple-health resting_hr and hrv lines written 60 and 1,000 times too large and"
        " re-emit them corrected (RFC 0014)",
    )
    v.add_argument(
        "--dry-run", action="store_true", help="print how many lines would be appended; write nothing"
    )
    v.set_defaults(fn=cmd_repair)


def cmd_repair(a: argparse.Namespace) -> None:
    """`repair health-units`: the migration for a record whose `apple-health` lines carry resting
    heart rate and HRV in the wrong unit (RFC 0014). Appends a corrected line and a retraction per
    wrong line; `--dry-run` prints the counts and writes nothing. Nothing is ever rewritten."""
    lb = Logbook.find()
    report = repair.health_units(lb, dry_run=a.dry_run)
    print(repair.describe_health_units(report))


DIGEST = re.compile(r"[0-9a-f]{64}")  # an attachment's name (SPEC §1.1); anything else is never looked up


BAR = "\u2588"  # one full block per ~1% of the busiest year


BAR_WIDTH = 100


def stats_arguments(sub: Subparsers) -> None:
    """`logbook stats`."""
    s = sub.add_parser("stats", help="what the record holds: counts by kind, source and year, never its text")
    s.add_argument("--json", action="store_true", help="the same numbers as one JSON object")
    s.add_argument(
        "--health",
        action="store_true",
        help="one row per day of the health lines: sleep hours, steps, resting HR",
    )
    s.set_defaults(fn=cmd_stats)


def cmd_stats(a: argparse.Namespace) -> None:
    """One screen of what the record holds, counted through the index (one SELECT per table,
    nothing read from the files): kinds, sources, years, retractions, resolutions, attachments.
    Numbers, kinds, sources and dates only; never what a line says. Nothing is written.

    `--health` is the one summary that reads lines: every `health` line (RFC 0014) through the
    index, one row per local day — sleep hours, steps, resting heart rate — and no device, no
    zone, no other field of any line."""
    lb = Logbook.find()
    if a.health:
        days = health_days(lb)
        if a.json:
            print(json.dumps({"days": days}, indent=2))
        elif not days:
            print("no health lines")
        else:
            for text in _health_rows(days):
                print(text)
        return
    started = time.monotonic()
    stats = record_stats(lb)
    stats["took_seconds"] = round(time.monotonic() - started, 3)
    if a.json:
        print(json.dumps(stats, indent=2))
        return
    for text in _stats_rows(stats):
        print(text)


def record_stats(lb: Logbook) -> dict[str, Any]:
    """The numbers `stats` prints, as one JSON-ready object (no `took_seconds`)."""
    meta = lb.meta
    store = lb.root / "attachments"

    def present(sha256: str) -> bool:
        return DIGEST.fullmatch(sha256) is not None and (store / sha256).is_file()

    with lb.index() as idx:
        lines, first, last = idx.totals()
        return {
            "format": meta.get("format"),
            "head": meta.get("head"),
            "lines": lines,
            "first": first,
            "last": last,
            "kinds": idx.kinds(),
            "sources": idx.sources(),
            "years": idx.years(),
            "retractions": idx.retraction_counts(),
            "resolutions": idx.resolution_counts(),
            "attachments": idx.attachment_counts(present),
        }


def health_days(lb: Logbook) -> list[dict[str, Any]]:
    """One row per local day of the record's health lines, through `health.summary` (the rules are
    there): every `health` line streamed through the index, the retractions beside them; the
    `lines` each row carries are dropped here, since `stats` prints numbers and never ids."""
    tz = str(lb.meta["timezone"])
    with lb.index() as idx:
        rows = health.summary([*idx.of_kind(health.KIND), *idx.retractions()], tz)
    return [{k: v for k, v in row.items() if k not in ("lines", "by")} for row in rows]


def _health_rows(days: list[dict[str, Any]]) -> Iterator[str]:
    yield f"  {'day':<10}  {'sleep':>5}  {'steps':>6}  {'resting':>7}"
    for d in days:
        sleep = "-" if d["sleep_h"] is None else f"{d['sleep_h']:.1f}"
        steps = "-" if d["steps"] is None else f"{d['steps']:,}"
        resting = "-" if d["resting_hr"] is None else str(d["resting_hr"])
        yield f"  {d['day']:<10}  {sleep:>5}  {steps:>6}  {resting:>7}"
    yield ""
    yield f"{_plural(len(days), 'day')}; sleep in hours, steps per day, resting heart rate in bpm"


def _stats_rows(s: dict[str, Any]) -> Iterator[str]:
    yield f"{s['format']}  head {s['head']}"
    if not s["lines"]:
        yield "0 lines"
    else:
        yield f"{s['lines']:,} lines  first {s['first']}  last {s['last']}"
    width = max(5, len(f"{s['lines']:,}"))
    if s["kinds"]:
        name = max(10, *(len(k["kind"]) for k in s["kinds"]))
        yield ""
        yield f"  {'kind':<{name}}  {'lines':>{width}}   first       last"
        for k in s["kinds"]:
            yield (
                f"  {k['kind']:<{name}}  {k['lines']:>{width},}   {k['first']}  {k['last']}"
                f"   {_plural(k['sources'], 'source')}"
            )
    if s["sources"]:
        name = max(10, *(len(x["source"]) for x in s["sources"]))
        yield ""
        yield f"  {'source':<{name}}  {'lines':>{width}}"
        for x in s["sources"]:
            yield f"  {x['source']:<{name}}  {x['lines']:>{width},}"
    if s["years"]:
        busiest = max(y["lines"] for y in s["years"])
        yield ""
        yield f"  year  {'lines':>{width}}"
        for y in s["years"]:
            bar = BAR * max(1, round(BAR_WIDTH * y["lines"] / busiest))  # a year with any line shows
            yield f"  {y['year']}  {y['lines']:>{width},}  {bar}"
    r, e, m = s["retractions"], s["resolutions"], s["attachments"]
    yield ""
    yield f"{_plural(r['lines'], 'retraction')} hiding {_plural(r['hidden'], 'line')}"
    yield f"{_plural(e['lines'], 'resolution line')} minting {_plural(e['entities'], 'entity', 'entities')}"
    yield (
        f"{_plural(m['referenced'], 'attachment')} referenced by {_plural(m['lines'], 'line')},"
        f" {m['present']:,} present under attachments/"
    )
    yield ""
    yield f"took {s['took_seconds']:.3f}s"


def demo_arguments(sub: Subparsers) -> None:
    """`logbook demo`."""
    s = sub.add_parser("demo", help="write a synthetic record to try the commands on; nothing in it is real")
    s.add_argument("--days", type=int, metavar="N", help="local days from 2026-06-01 (default 30)")
    s.add_argument(
        "--years",
        type=int,
        metavar="N",
        help="instead: the persona's whole life, N years from her birth to 2026-06-30, in phases",
    )
    s.add_argument("--seed", type=int, default=1, metavar="S", help="the same seed gives the same record")
    s.add_argument("--out", required=True, metavar="DIR", help="a folder that is not yet a logbook")
    s.set_defaults(fn=cmd_demo)


def cmd_demo(a: argparse.Namespace) -> None:
    """`demo [--days N | --years N] [--seed S] --out DIR`: a complete synthetic record of the Oslo
    persona, invented in `logbook/demo.py` (a month) or `logbook/demo_life.py` (a life), written
    to a new folder; the same days or years and seed give the same head. Nothing in it is real
    and nothing outside the folder is read."""
    from ..labs import demo_life

    root = Path(a.out).expanduser()
    if a.years is not None and a.days is not None:
        print("demo: give --days or --years, not both", file=sys.stderr)
        sys.exit(2)
    if a.years is not None and a.years < 1:
        print("demo: --years must be at least 1", file=sys.stderr)
        sys.exit(2)
    if a.days is not None and a.days < 1:
        print("demo: --days must be at least 1", file=sys.stderr)
        sys.exit(2)
    try:
        if a.years is not None:
            lb = demo_life.generate(root, a.years, a.seed)  # the life is labs, built on the month
        else:
            lb = demo.generate(root, days=a.days, seed=a.seed)
    except (FileExistsError, CodeCheckoutError, OSError) as e:
        print(f"demo: {e}", file=sys.stderr)
        sys.exit(2)
    meta = lb.meta
    if a.years is not None:
        first, last = demo_life.birthday(a.years), demo_life.TODAY
        span = _plural(a.years, "year")
        show = last if a.years < demo_life.FULL_MONTH_FROM else first.replace(year=last.year, month=6, day=17)
    else:
        days = 30 if a.days is None else a.days
        first, last = demo.START, demo.START + timedelta(days=days - 1)
        span = _plural(days, "day")
        show = min(last, first + timedelta(days=7))
    where = _under_home(lb.root)
    print(
        f"demo record: {span}, {first} to {last}, seed {a.seed}; nothing in it is real\n"
        f"wrote {meta['seq']:,} lines to {where}, head {str(meta['head'])[:12]}…\n"
        f"  export LOGBOOK_HOME={where}\n"
        f"  logbook show {show}"
    )


def index_arguments(sub: Subparsers) -> None:
    """`logbook index`."""
    s = sub.add_parser("index", help="rebuild index.sqlite from the files (readers do it when needed)")
    s.set_defaults(fn=cmd_index)


def cmd_index(a: argparse.Namespace) -> None:
    """Rebuild index.sqlite from the files. Readers do this by themselves when it is missing or
    stale; this is the command that shows progress, or that you run after copying a logbook."""
    lb = Logbook.find()
    started = time.monotonic()
    n = lb.index_rebuild(progress=_progress)
    print(f"indexed {n:,} lines in {time.monotonic() - started:,.1f}s → {lb.root / 'index.sqlite'}")


def verify_arguments(sub: Subparsers) -> None:
    """`logbook verify`."""
    s = sub.add_parser("verify", help="check the chain")
    s.add_argument("--root", help="logbook folder (default: find)")
    s.add_argument("--expect", help="expected.json with seq and head (conformance)")
    s.add_argument(
        "--progress",
        action="store_true",
        help="one line per month file on stderr, in path order, as file n of N",
    )
    s.set_defaults(fn=cmd_verify)


def cmd_verify(a: argparse.Namespace) -> None:
    """Files only, never the index (ADR 0001)."""
    lb = Logbook(Path(a.root).expanduser()) if a.root else Logbook.find()
    warnings: list[str] = []
    seq, head, errors = lb.verify(warnings, progress=_file_progress(len(lb.files())) if a.progress else None)
    if a.expect:
        exp = json.loads(Path(a.expect).read_text(encoding="utf-8"))
        if (exp["seq"], exp["head"]) != (seq, head):
            errors.append(
                f"expected seq={exp['seq']} head={exp['head'][:12]}…, got seq={seq} head={head[:12]}…"
            )
    if errors:
        print(f"INVALID — {len(errors)} problem(s):")
        for e in errors:
            print("  " + e)
        sys.exit(1)
    print(f"valid — {seq} lines, head {head}")
    if warnings:
        print(f"WARNING — {len(warnings)} timestamp(s) the next release will reject:")
        for w in warnings:
            print("  " + w)


# The steps `setup --step` names in its help. `logbook.setup` owns the tuple and is imported only when
# the command runs (it reaches the adapters); a test holds this copy to it.
SETUP_STEPS = ("folder", "timezone", "owner", "home", "sources", "doctor")


def setup_arguments(sub: Subparsers) -> None:
    """`logbook setup`."""
    s = sub.add_parser(
        "setup",
        help="the guided first run: where the record lives, your timezone, who you are, your home, what is"
        " on this machine to import; one question at a time, resumable; --yes takes every default",
    )
    s.add_argument("--yes", action="store_true", help="take every default, ask nothing (tests, scripts)")
    s.add_argument("--step", metavar="NAME", help="run one step again: " + ", ".join(SETUP_STEPS))
    s.add_argument("--again", action="store_true", help="run every step again (the record is kept)")
    s.set_defaults(fn=cmd_setup)


def cmd_setup(a: argparse.Namespace) -> None:
    """The guided first run (`logbook/setup.py`): one question at a time, each with its default and why
    it is asked; resumable through `state/setup.json`; `--yes` takes every default and asks nothing."""
    from . import setup

    status = setup.run(a, os.environ)
    if status:
        sys.exit(status)


def doctor_arguments(sub: Subparsers) -> None:
    """`logbook doctor`."""
    s = sub.add_parser(
        "doctor", help="is this machine set up to keep the record? one line per check; exit 1 on a fail"
    )
    s.set_defaults(fn=cmd_doctor)


def cmd_doctor(a: argparse.Namespace) -> None:
    """One line per check of the record and this machine (`logbook/doctor.py`); exit 1 when one fails.
    Reads only: a missing settings file is reported, never written."""
    from ..contrib import doctor as doctor_checks

    try:
        lb: Logbook | None = Logbook.find()
    except FileNotFoundError:
        lb = None
    status = doctor_checks.report(doctor_checks.run(lb, os.environ), sys.stdout)
    if status:
        sys.exit(status)


def backup_arguments(sub: Subparsers) -> None:
    """`logbook backup`."""
    s = sub.add_parser(
        "backup",
        help="a verified snapshot of the record under DEST/<owner_id>/<timestamp>/, hard-linked to the"
        " previous one where nothing changed; `backup list DEST`; `backup restore SNAPSHOT TARGET`",
    )
    s.add_argument(
        "paths",
        nargs="+",
        metavar="DEST",
        help="where the snapshots go (another disk; never inside the record, never a sync client's"
        " folder); or `list DEST`; or `restore SNAPSHOT TARGET`",
    )
    s.add_argument(
        "--keep", type=int, metavar="N", help="after the new snapshot verifies, prune the oldest so N remain"
    )
    s.add_argument(
        "--verify",
        action="store_true",
        help="also hash every attachment in the copy against its name (the chain is always verified)",
    )
    s.set_defaults(fn=cmd_backup)


def cmd_backup(a: argparse.Namespace) -> None:
    """`backup DEST [--keep N] [--verify]`: one snapshot of the record under `DEST/<owner_id>/`, hard
    links to the previous one for what did not change, verified there, its head the live head.
    `backup list DEST`: every snapshot with its lines, head and size. `backup restore SNAPSHOT
    TARGET`: a copy back, verified (`logbook/backup.py`, docs/backup.md). A refusal exits 2; a copy
    that does not verify is removed and exits 1."""
    from ..contrib import backup

    verb, paths = (a.paths[0], a.paths[1:]) if a.paths[0] in ("list", "restore") else (None, a.paths)
    usage = {None: "backup DEST", "list": "backup list DEST", "restore": "backup restore SNAPSHOT TARGET"}
    if len(paths) != (2 if verb == "restore" else 1):
        print(f"backup: usage: logbook {usage[verb]}", file=sys.stderr)
        sys.exit(2)
    if verb is not None and (a.keep is not None or a.verify):
        print(f"backup {verb}: --keep and --verify belong to `logbook backup DEST`", file=sys.stderr)
        sys.exit(2)
    if a.keep is not None and a.keep < 1:
        print("backup: --keep takes a number of snapshots to keep, 1 or more", file=sys.stderr)
        sys.exit(2)
    try:
        if verb == "list":
            _backup_list(Path(paths[0]).expanduser())
        elif verb == "restore":
            _backup_restore(Path(paths[0]).expanduser(), Path(paths[1]).expanduser())
        else:
            _backup_snapshot(Logbook.find(), Path(paths[0]).expanduser(), a)
    except backup.Invalid as e:
        print(f"backup: {e}; nothing kept", file=sys.stderr)
        sys.exit(1)
    except backup.Refused as e:
        print(f"backup: {e}", file=sys.stderr)
        sys.exit(2)


def _backup_snapshot(lb: Logbook, dest: Path, a: argparse.Namespace) -> None:
    from ..contrib import backup

    result = backup.snapshot(lb, dest, verify_attachments=a.verify)
    print(f"backup: {result.path.name} → {result.path}")
    for text in backup.describe(result):
        print(text)
    if result.attachments_checked is not None:
        print(f"  {_plural(result.attachments_checked, 'attachment')} checked, every one matches its name")
    if a.keep is not None:
        removed = backup.prune(result.path.parent, a.keep, result.path)
        kept = len(backup.snapshots(result.path.parent))
        pruned = ", ".join(p.name for p in removed) if removed else "nothing"
        print(f"  kept {_plural(kept, 'snapshot')}; pruned {pruned}")


def _backup_list(dest: Path) -> None:
    from ..contrib import backup

    shown = 0
    for owner, entries in backup.listing(dest):
        print(owner)
        for e in entries:
            size = f"{backup.human(e.bytes)} ({backup.human(e.new_bytes)} new)"
            if e.error is not None:
                print(f"  {e.path.name}  not a readable snapshot: {e.error}  {size}")
            else:
                print(f"  {e.path.name}  {_plural(e.seq or 0, 'line')}  head {(e.head or '')[:12]}…  {size}")
            shown += 1
    if not shown:
        print(f"no snapshots under {dest}")


def _backup_restore(source: Path, target: Path) -> None:
    from ..contrib import backup

    result = backup.restore(source, target)
    print(f"restored {source.name} → {result.path}")
    for text in backup.describe(result):
        print(text)
    print(f"  point LOGBOOK_HOME at {result.path}; the next reader builds its index")


def migrate_arguments(sub: Subparsers) -> None:
    """`logbook migrate`."""
    s = sub.add_parser("migrate", help="bring a logbook/0.1 record to logbook/0.2 (same lines, new hashes)")
    s.add_argument("--root", help="logbook folder (default: find)")
    s.set_defaults(fn=cmd_migrate)


def cmd_migrate(a: argparse.Namespace) -> None:
    """A logbook/0.1 record becomes logbook/0.2: same lines, hashes recomputed, lineage kept (SPEC §3.1)."""
    lb = Logbook(Path(a.root).expanduser()) if a.root else Logbook.find()
    try:
        result = lb.migrate(progress=_progress)
    except (FormatError, FileExistsError, ValueError) as e:
        print(f"migrate: {e}", file=sys.stderr)
        sys.exit(2)
    old, new = result["from_head"][:12], result["head"][:12]
    print(
        f"migrated {result['lines']} lines to {FORMAT}: head {old}… → {new}…\n"
        f"the 0.1 files are kept at {result['kept']}; delete them once `logbook verify` is green"
    )
