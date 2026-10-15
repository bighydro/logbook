"""The owner's acts on lines already in the record: `star`, `unstar` (RFC 0041) and `with`. Each is a
function of `logbook.core` (`stars.star`, `stars.unstar`, `presence.state`) that the Day page of
`logbook serve` calls too, so the line is the same from either."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from ..core import presence, stars
from ..core.chain import Line
from ..core.store import Logbook
from .common import Subparsers


def star_arguments(sub: Subparsers) -> None:
    """`logbook star LINE [--note TEXT]`."""
    s = sub.add_parser(
        "star",
        help="mark a line worth keeping; a photo's star is the press's pick",
        description="mark a line worth keeping (RFC 0041): one star/v1 line at the line's own time and"
        " tier, so it travels where the line does; a photo's star is a memory keeper (RFC 0024), the"
        " Day's hero photo and the photo the press picks",
    )
    s.add_argument("line", metavar="LINE", help="the line's id, or #SEQ")
    s.add_argument("--note", help="your words on the star, one line; it travels with the star")
    s.set_defaults(fn=cmd_star)


def cmd_star(a: argparse.Namespace) -> None:
    """`star LINE [--note TEXT]`: `stars.star`; a refusal is one sentence on stderr, exit 2."""
    try:
        line, written = stars.star(Logbook.find(), a.line, a.note)
    except stars.StarError as e:
        print(f"star: {e}", file=sys.stderr)
        sys.exit(2)
    if written is None:
        print(f"#{line['seq']} is starred already; nothing written")
        return
    note = (written.get("payload") or {}).get("note")
    print(
        f"#{written['seq']} {_schema(written)}  {stars.SYMBOL} {_named(line)}"
        + (f" · {note}" if note else "")
    )


def unstar_arguments(sub: Subparsers) -> None:
    """`logbook unstar LINE`."""
    s = sub.add_parser(
        "unstar",
        help="take a star back: a retraction at its tier, nothing rewritten",
        description="take a star back (RFC 0041): a retraction of the line's star, or of each memory"
        " keeper of a photo, at the star's tier",
    )
    s.add_argument("line", metavar="LINE", help="the starred line's id or #SEQ, or the star's own")
    s.set_defaults(fn=cmd_unstar)


def cmd_unstar(a: argparse.Namespace) -> None:
    """`unstar LINE`: `stars.unstar`; a refusal is one sentence on stderr, exit 2."""
    try:
        line, written = stars.unstar(Logbook.find(), a.line)
    except stars.StarError as e:
        print(f"unstar: {e}", file=sys.stderr)
        sys.exit(2)
    for retraction in written:
        print(f"#{retraction['seq']} {_schema(retraction)}  unstarred {_named(line)}")


def with_arguments(sub: Subparsers) -> None:
    """`logbook with DAY NAME [NAME…] [--at HH:MM]`."""
    s = sub.add_parser(
        "with",
        help="who was there when the record could not see: one note per person",
        description="who was with you on DAY, in your words: one note/v1 line per person, `with"
        " <name>`, labelled with, the company the people reader already reads (SPEC §3.2.5 rule 3)",
    )
    s.add_argument("day", metavar="DAY", help="YYYY-MM-DD")
    s.add_argument(
        "names",
        metavar="NAME",
        nargs="+",
        help='a person the record names: a label, quoted ("Ola Nordmann"), a first or last name, an address',
    )
    s.add_argument("--at", metavar="HH:MM", help="the clock on the day; default noon, or now for today")
    s.set_defaults(fn=cmd_with)


def cmd_with(a: argparse.Namespace) -> None:
    """`with DAY NAME… [--at HH:MM]`: `presence.state`; a refusal is one sentence on stderr, exit 2."""
    try:
        found = presence.state(Logbook.find(), a.day, a.names, a.at)
    except (presence.WithError, ValueError) as e:
        print(f"with: {e}", file=sys.stderr)
        sys.exit(2)
    for item in found:
        if item.line is None:
            print(f"{item.name}: stated on {a.day} already; nothing written")
        else:
            print(f"#{item.line['seq']} {presence.text_of(item.name)}  {a.day} {_clock(item.line)}")


def _schema(line: Line) -> str:
    return str((line.get("payload") or {}).get("schema") or line.get("kind"))


def _named(line: Line) -> str:
    """`#57 event  Lunch`: the starred line as the commands name it."""
    return f"#{line['seq']} {line.get('kind')}  {stars.title(line)}"


def _clock(line: Line) -> str:
    """The line's `at` on the record's clock, `HH:MM`."""
    at = datetime.fromisoformat(str(line["at"]).replace("Z", "+00:00"))
    return at.astimezone(ZoneInfo(str(line.get("tz")))).strftime("%H:%M")
