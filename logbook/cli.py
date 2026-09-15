"""logbook — init · add · show · verify · export. Three verbs and two you run once a year."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Any

from . import __version__, adapters
from .export import day_package, day_range, parse_day, write_package
from .store import CodeCheckoutError, Logbook, now_utc


def _tz_default() -> str:
    key = getattr(datetime.now().astimezone().tzinfo, "key", None)
    return key if isinstance(key, str) else "UTC"


def cmd_init(a: argparse.Namespace) -> None:
    root = Path(a.path or Path.home() / "Logbook").expanduser()
    try:
        lb = Logbook.init(root, a.timezone or _tz_default())
    except CodeCheckoutError as e:
        print(f"refusing to init: {e}", file=sys.stderr)
        sys.exit(2)
    print(f'created {lb.root}\nDrop any export into {lb.root / "inbox"}, or: logbook add "what happened"')


def _add_file(lb: Logbook, p: Path) -> bool:
    """Append one file through the adapter that recognises it. False when nothing does."""
    adapter = adapters.find(p)
    if adapter is not None:
        n = lb.append_many(adapter.run(p), progress=_progress)
        print(f"added {n} lines from {adapter.NAME}")
        return True
    if p.suffix == ".jsonl":  # observations produced by an adapter run by hand
        n = lb.append_many(_jsonl(p), progress=_progress)
        print(f"added {n} lines from {p.name}")
        return True
    print(
        f"{p.name}: no adapter for this file yet (roadmap phase 1). "
        "Put it in inbox/ and it will be read when one exists."
    )
    return False


def _progress(n: int, elapsed: float) -> None:
    print(f"  {n:,} lines in {elapsed:,.0f}s", file=sys.stderr)


def _jsonl(p: Path) -> Iterator[dict[str, Any]]:
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def cmd_add(a: argparse.Namespace) -> None:
    lb = Logbook.find()
    what = " ".join(a.what).strip()
    p = Path(what).expanduser()
    if p.is_dir():  # every file in it, in name order; hidden files are not exports
        for f in sorted(p.iterdir()):
            if f.is_file() and not f.name.startswith("."):
                _add_file(lb, f)
    elif p.exists():
        if not _add_file(lb, p):
            sys.exit(2)
    else:  # a sentence, in your own words
        at = a.at or now_utc()
        line = lb.append(
            at=at, source="manual", kind="note", tier=2, payload={"schema": "note/v1", "text": what}
        )
        print(f"#{line['seq']} {line['at']}  {what}")


def cmd_show(a: argparse.Namespace) -> None:
    lb = Logbook.find()
    day = date.today().isoformat() if a.day in (None, "today") else a.day
    rows = [line for line in lb.lines() if line["at"].startswith(day)]
    if not rows:
        print(f"{day}: nothing logged")
        return
    print(day)
    for line in rows:
        p = line["payload"]
        text = (
            p.get("text")
            or p.get("title")
            or p.get("name")
            or ", ".join(f"{k}={v}" for k, v in p.items() if k != "schema")
        )
        print(f"  {line['at'][11:16]}  {line['kind']:<10} {line['source']:<14} {text}")
    note = lb.root / "notes" / day[:4] / f"{day}.md"
    if note.exists():
        print("  — note —\n" + "\n".join("  " + s for s in note.read_text(encoding="utf-8").splitlines()))


def cmd_verify(a: argparse.Namespace) -> None:
    lb = Logbook(Path(a.root).expanduser()) if a.root else Logbook.find()
    seq, head, errors = lb.verify()
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


def cmd_export(a: argparse.Namespace) -> None:
    lb = Logbook.find()
    if a.day or a.days:
        _export_days(lb, a)
        return
    if not a.path:
        print("export: give a .jsonl path, or --day YYYY-MM-DD, or --days FROM TO", file=sys.stderr)
        sys.exit(2)
    out = Path(a.path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open("w", encoding="utf-8") as fh:
        for line in lb.lines():
            fh.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
            n += 1
    print(f"exported {n} lines to {out} — verify with: logbook verify")


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
    for day, out in zip(days, dirs, strict=True):
        package = day_package(lb, day)
        n = len(package["entries"])
        if a.days and not a.empty and n == 0:
            continue
        write_package(package, out)
        written += 1
        print(f"{day}: {n} entries → {out}")
    if a.days:
        print(f"wrote {written} day package(s)")


def main(argv: list[str] | None = None) -> None:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252; the CLI speaks UTF-8
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="logbook", description="A diary that writes itself.")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init", help="create a logbook (default ~/Logbook)")
    s.add_argument("path", nargs="?")
    s.add_argument("--timezone")
    s.set_defaults(fn=cmd_init)
    s = sub.add_parser("add", help="a sentence in your words, an export file, or a folder of them")
    s.add_argument("what", nargs="+")
    s.add_argument("--at", help="RFC3339 UTC, default now")
    s.set_defaults(fn=cmd_add)
    s = sub.add_parser("show", help="one day (default today)")
    s.add_argument("day", nargs="?")
    s.set_defaults(fn=cmd_show)
    s = sub.add_parser("verify", help="check the chain")
    s.add_argument("--root", help="logbook folder (default: find)")
    s.add_argument("--expect", help="expected.json with seq and head (conformance)")
    s.set_defaults(fn=cmd_verify)
    s = sub.add_parser("export", help="the whole log as one .jsonl, or one day-package/v1 per day")
    s.add_argument("path", nargs="?", help=".jsonl file for the whole log")
    s.add_argument("--day", metavar="YYYY-MM-DD", help="one day-package/v1 directory")
    s.add_argument("--days", nargs=2, metavar=("FROM", "TO"), help="one directory per day, inclusive")
    s.add_argument("--out", metavar="DIR", help="where to write (default <root>/export/<date>/)")
    s.add_argument("--empty", action="store_true", help="with --days: also write days with no entries")
    s.set_defaults(fn=cmd_export)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
