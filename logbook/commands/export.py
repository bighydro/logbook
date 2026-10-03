"""`export`: a day range as packages, or the lines a border crossing may ask for."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from pathlib import Path

from .. import crossing, policy
from ..chain import Line
from ..export import day_packages, day_range, parse_day, write_package
from ..store import Logbook, UnsortedFile, now_utc
from .common import EN_DASH, Subparsers, _plural


def export_arguments(sub: Subparsers) -> None:
    """`logbook export`."""
    s = sub.add_parser(
        "export",
        help="the whole log as one .jsonl, one day-package/v1 per day, or `crossing`: a crossing-package/v1",
    )
    s.add_argument("path", nargs="?", help=".jsonl file for the whole log, or `crossing` (RFC 0005)")
    s.add_argument("--day", metavar="YYYY-MM-DD", help="one day-package/v1 directory")
    s.add_argument("--days", nargs=2, metavar=("FROM", "TO"), help="one directory per day, inclusive")
    s.add_argument("--out", metavar="DIR", help="where to write (default <root>/export/<date>/)")
    s.add_argument("--empty", action="store_true", help="with --days: also write days with no entries")
    s.add_argument("--to", metavar="DESTINATION", help="crossing: the circle member, e.g. hermes")
    s.add_argument("--since", metavar="RFC3339|last", help="crossing: window start, or the last window's end")
    s.add_argument("--until", metavar="RFC3339", help="crossing: window end, exclusive (default now)")
    s.add_argument("--tier", metavar="1|1,2|1,2,3", help="crossing: tiers to cross (default 1)")
    s.add_argument("--kinds", metavar="a,b", help="crossing: only these kinds")
    s.add_argument(
        "--dry-run", action="store_true", help="crossing: count and show the policy; write nothing"
    )
    s.set_defaults(fn=cmd_export)


def cmd_export(a: argparse.Namespace) -> None:
    lb = Logbook.find()
    if a.path == crossing.KIND:
        _export_crossing(lb, a)
        return
    if a.day or a.days:
        _export_days(lb, a)
        return
    if not a.path:
        print("export: give a .jsonl path, or --day YYYY-MM-DD, or --days FROM TO", file=sys.stderr)
        sys.exit(2)
    out = Path(a.path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    n = _write_lines(lb.lines(), out)
    if n is None:  # a month file not in seq order (not one this code wrote): the sorted read
        n = _write_lines(lb._lines_by_seq(), out)
    print(f"exported {n} lines to {out} — verify with: logbook verify")


def _write_lines(lines: Iterator[Line], out: Path) -> int | None:
    """Stream `lines` to `out` as JSON lines, one in memory at a time; the count, or None when
    the files turned out to need the sorted read (the caller starts the file over)."""
    n = 0
    with out.open("w", encoding="utf-8") as fh:
        try:
            for line in lines:
                fh.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
                n += 1
        except UnsortedFile:
            return None
    return n


def _export_days(lb: Logbook, a: argparse.Namespace) -> None:
    """--day DATE [--out DIR]: one package at DIR (default <root>/export/DATE).
    --days FROM TO [--out DIR] [--empty]: one package per day at DIR/DATE (default <root>/export/DATE)."""
    try:
        if a.day:
            days = [parse_day(a.day).isoformat()]
            dirs = [Path(a.out).expanduser() if a.out else lb.root / "export" / a.day]
        else:
            days = day_range(*a.days)
            base = Path(a.out).expanduser() if a.out else lb.root / "export"
            dirs = [base / d for d in days]
    except ValueError as e:
        print(f"export: {e}", file=sys.stderr)
        sys.exit(2)
    written = 0
    packages = day_packages(lb, days)  # one read of the log for the whole range
    for day, out in zip(days, dirs, strict=True):
        package = packages[day]
        n = len(package["entries"])
        if a.days and not a.empty and n == 0:
            continue
        write_package(package, out)
        written += 1
        print(f"{day}: {n} entries → {out}")
    if a.days:
        print(f"wrote {written} day package(s)")


def _export_crossing(lb: Logbook, a: argparse.Namespace) -> None:
    """crossing --to DEST --since RFC3339|last [--until RFC3339] [--tier 1|1,2|1,2,3] [--kinds a,b]
    [--out DIR] [--dry-run]: one crossing-package/v1 (RFC 0005) under the destination's ceiling
    in policy/crossing.json (ADR 0016), recorded as a crossing/v1 line (RFC 0011)."""
    generated_at = now_utc()  # also the default window end, and the crossing line's `at`
    try:
        if not a.to or not a.since:
            raise crossing.CrossingError(
                "export crossing needs --to <destination> and --since <RFC3339|last>"
            )
        req = crossing.request(
            lb,
            a.to,
            a.since,
            a.until or generated_at,
            crossing.parse_tiers("1" if a.tier is None else a.tier),
            crossing.parse_kinds(a.kinds),
        )
    except crossing.EmptyWindow as e:
        print(f"{a.to}: {e}; nothing written")
        return
    except crossing.CrossingError as e:
        print(f"export crossing: {e}", file=sys.stderr)
        sys.exit(2)
    out = Path(a.out).expanduser() if a.out else crossing.default_out(lb, req.destination, generated_at)
    sel = crossing.select(lb, req)
    window = f"{req.since} {EN_DASH} {req.until}"
    tiers = ",".join(map(str, req.tiers))
    if a.dry_run:
        policy_file = policy.policy_path(lb.root)
        state = "" if policy_file.exists() else " (default; the first export writes it)"
        print(f"dry run: {req.destination}, {window}, tiers {tiers}; nothing written")
        print(f"  policy: {policy_file} {req.destination} max_tier {req.max_tier}{state}")
        for text in _crossing_rows(sel):
            print(text)
        if req.tier3:
            _tier3_warning(req, sel)
        return
    try:
        result = crossing.export(lb, req, sel, out, generated_at)
    except (crossing.CrossingError, OSError) as e:
        print(f"export crossing: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"{req.destination}: {sel.counts()['crossed']} lines crossed, {window}, tiers {tiers} → {out}")
    for text in _crossing_rows(sel):
        print(text)
    review = result.manifest.get("review")
    if review is not None:
        print(f"  review: {len(review)} tier-2 line(s) listed in {crossing.MANIFEST_FILE}")
    if req.tier3:
        _tier3_warning(req, sel)
    seq, digest = result.line["seq"], result.package_sha256[:12]
    print(f"  recorded as #{seq} {crossing.LINE_SCHEMA}, package sha256 {digest}…; watermark {req.until}")


def _crossing_rows(sel: crossing.Selection) -> Iterator[str]:
    c = sel.counts()
    yield f"  {c['logged']} lines in the window, {c['crossed']} cross, {c['held_back']} held back"
    yield "  " + "   ".join(f"tier {t}: {n}" for t, n in c["by_tier"].items())
    if c["by_kind"]:
        yield "  " + "   ".join(f"{k}: {n}" for k, n in c["by_kind"].items())
    yield f"  resolutions: {c['resolutions']} cross, {c['resolutions_held_back']} held back by tier"
    m = c["attachments"]
    files, missing = _plural(m["included"], "file"), m["missing"]
    yield f"  attachments: {files}, {m['bytes']:,} bytes; {missing} missing from the store"


def _tier3_warning(req: crossing.Request, sel: crossing.Selection) -> None:
    n = sum(1 for line in [*sel.lines, *sel.resolutions] if int(line["tier"]) == 3)
    text = f"WARNING: {crossing.TIER3_WARNING}: {_plural(n, 'tier-3 line')} for {req.destination}"
    print(text)
    print(text, file=sys.stderr)
