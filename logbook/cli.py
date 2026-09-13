"""logbook — init · add · show · verify · export. Three verbs and two you run once a year."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

from . import __version__
from .store import Logbook, now_utc


def _tz_default() -> str:
    key = getattr(datetime.now().astimezone().tzinfo, "key", None)
    return key if isinstance(key, str) else "UTC"


def cmd_init(a: argparse.Namespace) -> None:
    root = Path(a.path or Path.home() / "Logbook").expanduser()
    lb = Logbook.init(root, a.timezone or _tz_default())
    print(f'created {lb.root}\nDrop any export into {lb.root / "inbox"}, or: logbook add "what happened"')


def cmd_add(a: argparse.Namespace) -> None:
    lb = Logbook.find()
    what = " ".join(a.what).strip()
    p = Path(what).expanduser()
    if p.exists() and p.suffix == ".jsonl":  # observations produced by an adapter
        drafts = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
        n = lb.append_many(drafts)
        print(f"added {n} lines from {p.name}")
    elif p.exists():
        print(
            f"{p.name}: no adapter for this file yet (roadmap phase 1). "
            "Put it in inbox/ and it will be read when one exists."
        )
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
    out = Path(a.path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open("w", encoding="utf-8") as fh:
        for line in lb.lines():
            fh.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
            n += 1
    print(f"exported {n} lines to {out} — verify with: logbook verify")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="logbook", description="A diary that writes itself.")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init", help="create a logbook (default ~/Logbook)")
    s.add_argument("path", nargs="?")
    s.add_argument("--timezone")
    s.set_defaults(fn=cmd_init)
    s = sub.add_parser("add", help="a sentence in your words, or an adapter's .jsonl")
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
    s = sub.add_parser("export", help="the whole log as one .jsonl")
    s.add_argument("path")
    s.set_defaults(fn=cmd_export)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
