"""logbook — init · add · sync · retract · show · verify · export. Three verbs and four you run rarely."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Any

from . import __version__, adapters
from .export import day_packages, day_range, parse_day, write_package
from .store import RETRACTION, CodeCheckoutError, Logbook, now_utc, retractions


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


def _page_progress(n: int, elapsed: float) -> None:
    """One line per page pulled from a live source, dry runs included."""
    print(f"  {n:,} assets in {elapsed:,.0f}s", file=sys.stderr)


def _jsonl(p: Path) -> Iterator[dict[str, Any]]:
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


PATH_SUFFIXES = (".json", ".jsonl", ".geojson", ".zip", ".csv", ".txt")


def looks_like_path(arg: str) -> bool:
    """Something the shell would have expanded from a glob, or a file name."""
    return "/" in arg or arg.startswith("~") or arg.lower().endswith(PATH_SUFFIXES)


def cmd_add(a: argparse.Namespace) -> None:
    lb = Logbook.find()
    paths = [Path(w).expanduser() for w in a.what]
    # When nothing exists, the arguments are a sentence unless every one of them looks like a
    # path: "had 5/10 sleep" is a note, "~/Downloads/typo.json" is a typo.
    if not any(p.exists() for p in paths) and not all(looks_like_path(w) for w in a.what):
        _add_sentence(lb, " ".join(a.what).strip(), a.at)
        return
    # Something exists, so every argument is a path. A glob that matched two files must never
    # become a note, and a path that does not exist is a typo, so nothing is written until every
    # argument checks out.
    for w, p in zip(a.what, paths, strict=True):
        if not p.exists():
            print(f"add: no such file or directory: {w}", file=sys.stderr)
            sys.exit(2)
    ok = True
    for p in paths:
        if p.is_dir():  # every file in it, in name order; hidden files are not exports
            for f in sorted(p.iterdir()):
                if f.is_file() and not f.name.startswith("."):
                    _add_file(lb, f)
        elif not _add_file(lb, p):
            ok = False
    if not ok:
        sys.exit(2)


def _add_sentence(lb: Logbook, what: str, at: str | None) -> None:
    """A sentence, in your own words."""
    line = lb.append(
        at=at or now_utc(), source="manual", kind="note", tier=2, payload={"schema": "note/v1", "text": what}
    )
    print(f"#{line['seq']} {line['at']}  {what}")


def cmd_sync(a: argparse.Namespace) -> None:
    """Pull from a live source since its stored watermark (or --since), append, advance the watermark.
    The watermark is the source's own clock (adapter.watermark), not the event time, so late uploads of
    old items are still picked up. It lives in <root>/state/<name>.json — bookkeeping, not the record."""
    adapter = adapters.live(a.name)
    if adapter is None:
        known = ", ".join(x.NAME for x in adapters.live_adapters()) or "none"
        print(f"sync: no live source named {a.name!r} (known: {known})", file=sys.stderr)
        sys.exit(2)
    config = adapter.configure(os.environ)
    if config is None:
        missing = [v for v in adapter.ENV if not os.environ.get(v, "").strip()]
        print(f"sync: {a.name}: set {' and '.join(missing)}", file=sys.stderr)
        sys.exit(2)
    if a.since is not None and not _is_rfc3339(a.since):
        print(
            f"sync: --since must be RFC3339 UTC, e.g. 2026-03-01T00:00:00Z, not {a.since!r}", file=sys.stderr
        )
        sys.exit(2)
    lb = Logbook.find()
    state_path = lb.root / "state" / f"{a.name}.json"
    since = a.since if a.since is not None else _read_state(state_path).get("since")
    seen: dict[str, Any] = {
        "count": 0,
        "first": None,
        "last": None,
        "watermark": None,
        "provenance": Counter(),
    }
    counts: dict[str, int] = {}
    drafts = _watch(
        adapter.pull(config, since, progress=_page_progress, counts=counts), adapter.watermark, seen
    )
    try:
        if a.dry_run:
            for _ in drafts:
                pass
        else:
            n = lb.append_many(drafts)  # the page lines above are the progress; one stream, not two
    except OSError as e:  # urllib's errors are OSErrors; what was pulled before is already checkpointed
        print(f"sync: {a.name}: {e}", file=sys.stderr)
        sys.exit(1)
    where = f"since {since}" if since else "from the beginning"
    pending = counts.get("pending", 0)
    if a.dry_run:
        print(f"{a.name}: {seen['count']} lines {where} (dry run, nothing written)")
        if seen["count"]:
            print(f"  first {seen['first']}  last {seen['last']}  watermark {seen['watermark'] or '-'}")
            for provenance, count in sorted(seen["provenance"].items()):
                print(f"  {provenance}: {count}")
        _report_pending(pending)
        return
    if seen["watermark"] is not None:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({"since": seen["watermark"]}, indent=2) + "\n", encoding="utf-8")
    print(
        f"{a.name}: {n} new lines of {seen['count']} seen {where}; "
        f"watermark {seen['watermark'] or since or '-'}"
    )
    _report_pending(pending)


def _report_pending(pending: int) -> None:
    """Assets the source has not finished processing; the adapter left them for a later sync."""
    if pending:
        print(f"  {pending:,} pending (metadata not extracted yet; will arrive on a later sync)")


def _watch(
    drafts: Iterable[dict[str, Any]],
    watermark: Callable[[dict[str, Any]], str | None],
    seen: dict[str, Any],
) -> Iterator[dict[str, Any]]:
    """Pass drafts through, noting count, earliest/latest `at`, the largest watermark and
    per-provenance counts."""
    for d in drafts:
        seen["count"] += 1
        at = d["at"]
        if seen["first"] is None or at < seen["first"]:
            seen["first"] = at
        if seen["last"] is None or at > seen["last"]:
            seen["last"] = at
        mark = watermark(d)
        if mark is not None and (seen["watermark"] is None or mark > seen["watermark"]):
            seen["watermark"] = mark
        seen["provenance"][d["payload"].get("provenance", "-")] += 1
        yield d


def _read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _is_rfc3339(value: str) -> bool:
    try:
        return datetime.fromisoformat(value).tzinfo is not None
    except ValueError:
        return False


def cmd_retract(a: argparse.Namespace) -> None:
    lb = Logbook.find()
    try:
        line = lb.retract(a.seq, a.reason)
    except ValueError as e:
        print(f"retract: {e}", file=sys.stderr)
        sys.exit(2)
    print(f"#{line['seq']} {line['at']}  retracted #{a.seq}: {a.reason}")


def cmd_show(a: argparse.Namespace) -> None:
    lb = Logbook.find()
    day = date.today().isoformat() if a.day in (None, "today") else a.day
    lines = list(lb.lines())
    retracted = retractions(lines)
    # A retraction is not an event of its own day; it shows as a marker where the line it hides was.
    rows = [line for line in lines if line["at"].startswith(day) and line["kind"] != RETRACTION]
    if not rows:
        print(f"{day}: nothing logged")
        return
    print(day)
    for line in rows:
        retraction = retracted.get(line["id"])
        if retraction is not None:
            print(
                f"  {line['at'][11:16]}  retracted #{line['seq']}: {retraction['payload'].get('reason', '')}"
            )
            continue
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
    s = sub.add_parser("sync", help="pull new items from a live source (immich); safe to re-run")
    s.add_argument("name", help="the source, e.g. immich")
    s.add_argument("--since", metavar="RFC3339", help="pull from here instead of the stored watermark")
    s.add_argument("--dry-run", action="store_true", help="show what would be appended; write nothing")
    s.set_defaults(fn=cmd_sync)
    s = sub.add_parser("retract", help="take back line SEQ with a new line; nothing is rewritten")
    s.add_argument("seq", type=int)
    s.add_argument("reason")
    s.set_defaults(fn=cmd_retract)
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
