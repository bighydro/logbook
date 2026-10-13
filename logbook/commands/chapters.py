"""The stretches of life the owner names (RFC 0036, `chapter/v1`): `chapter open`, `chapter close`
and `chapter list`. Not `lab chapters`, which derives a table of contents and writes nothing."""

from __future__ import annotations

import argparse
import json
import sys

from ..core import chapter
from ..core.chain import Line
from ..core.store import Logbook
from .common import Subparsers


def chapter_arguments(sub: Subparsers) -> None:
    """`logbook chapter open | close | list`."""
    s = sub.add_parser(
        "chapter",
        help="a stretch of your life you name; open, close, list",
        description="a named stretch of the record (chapter/v1, RFC 0036): a sabbatical, a passage, the"
        " year after a move, with its first day, its last once you close it, and its rules in your"
        " words; tier 2; the Day's header names the chapter a day is in; chapters do not overlap",
    )
    s.set_defaults(fn=cmd_chapter)
    verbs = s.add_subparsers(dest="verb", required=True, metavar="<verb>")
    v = verbs.add_parser("open", help="name a chapter from a day on")
    v.add_argument("name", metavar="NAME", help="the chapter's name, in your words")
    v.add_argument("--from", dest="start", metavar="YYYY-MM-DD", help="its first day (default today)")
    v.add_argument(
        "--to", metavar="YYYY-MM-DD", help="its last day, when you name it once it is over (default: open)"
    )
    v.add_argument("--rules", metavar="TEXT", help="what counts in this stretch, what you are for in it")
    v = verbs.add_parser("close", help="close the open chapter: written again with its last day")
    v.add_argument("--to", metavar="YYYY-MM-DD", help="its last day (default today)")
    v = verbs.add_parser("list", help="every standing chapter, and the one today is in")
    v.add_argument("--json", action="store_true", help="the chapters as one JSON object, with line ids")


def cmd_chapter(a: argparse.Namespace) -> None:
    """`chapter open NAME [--from DAY] [--to DAY] [--rules TEXT]`, `chapter close [--to DAY]`,
    `chapter list [--json]`. Each writer appends one `chapter/v1` line under the writer lock
    (`logbook.core.chapter`); a refusal is one sentence on stderr and exit 2, with nothing written."""
    lb = Logbook.find()
    try:
        if a.verb == "open":
            _open(lb, a)
        elif a.verb == "close":
            _close(lb, a)
        else:
            _list(lb, a)
    except chapter.ChapterError as e:
        print(f"chapter {a.verb}: {e}", file=sys.stderr)
        sys.exit(2)


def _open(lb: Logbook, a: argparse.Namespace) -> None:
    done = chapter.open_chapter(lb, a.name, a.start, a.to, a.rules)
    if done.line is None:
        existing = done.existing or {}
        payload = existing.get("payload") or {}
        print(
            f"{payload.get('name')} from {payload.get('from')} is in the record already"
            f" (#{existing.get('seq')}); nothing was written"
        )
        return
    _said(done.line)


def _close(lb: Logbook, a: argparse.Namespace) -> None:
    _said(chapter.close(lb, a.to))


def _said(line: Line) -> None:
    payload = line["payload"]
    tail = f"{chapter.DOT}closes {payload['supersedes']}" if payload.get("supersedes") else ""
    print(f"#{line['seq']} {chapter.SCHEMA}: {chapter.row_text(payload)}")
    print(f"  {line['id']}{chapter.DOT}tier {line['tier']}{tail}")
    if payload.get("rules"):
        print(f"  {payload['rules']}")


def _list(lb: Logbook, a: argparse.Namespace) -> None:
    found = chapter.listing(lb)
    if a.json:
        print(json.dumps(found, indent=2, ensure_ascii=False))
        return
    for text in chapter.listing_rows(found):
        print(text)
