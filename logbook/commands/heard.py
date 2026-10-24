"""`logbook show heard`: the words of the podcasts and videos the owner played, as `sync heard` stored
them (RFC 0046). A reader of `show`'s (`logbook.commands.day` names it and dispatches here, so the root
help keeps its commands): it lists the `heard/v1` lines of a window of local days, each with its source,
language, length and a one-line excerpt, and writes nothing."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from ..core import day_start
from ..core import heard as profile
from ..core.export import parse_day
from ..core.store import Logbook
from .common import _today

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def cmd_heard(a: argparse.Namespace) -> None:
    """`show heard [--day D | --since D --until D] [--json]`: the texts of the window, the latest day
    first and in time order within a day, read through the index (`heard.read`). `--day` is `show`'s
    `show_day`, defined once for every reader of `show` that takes one day (its positional is already
    `day`). Exit 2 on a date that is not one, a window that
    runs backwards, `--day` beside `--since` or `--until`, or a name after `heard`."""
    if a.name is not None:
        print(f"show heard: takes no name; one day is `--day {a.name}`", file=sys.stderr)
        sys.exit(2)
    if a.show_day is not None and (a.since is not None or a.until is not None):
        print("show heard: give --day, or --since and --until, not both", file=sys.stderr)
        sys.exit(2)
    lb = Logbook.find()
    try:
        days = day_start.of(lb.meta)
    except day_start.DayStartError as e:
        print(f"show heard: {e}", file=sys.stderr)
        sys.exit(2)
    try:
        first, last = _window(a)
    except ValueError as e:
        print(f"show heard: {e}", file=sys.stderr)
        sys.exit(2)
    rows = profile.read(lb, first, last, days.day_of)
    if a.json:
        out = {"since": first, "until": last, "count": len(rows), "texts": [row.to_json() for row in rows]}
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return
    zone = ZoneInfo(str(lb.meta["timezone"]))
    for text in _rows(rows, zone, first, last):
        print(text)


def _window(a: argparse.Namespace) -> tuple[str, str]:
    """The window's first and last local day: `--day`, `--since`/`--until` (until today when only
    `--since` is given, two weeks back when only `--until` is), or the last `DAYS` days."""
    if a.show_day is not None:
        day = parse_day(a.show_day).isoformat()
        return day, day
    last = parse_day(a.until) if a.until is not None else parse_day(_today())
    first = parse_day(a.since) if a.since is not None else last - timedelta(days=profile.DAYS - 1)
    if last < first:
        raise ValueError(f"the window runs backwards: {first.isoformat()} > {last.isoformat()}")
    return first.isoformat(), last.isoformat()


def _rows(rows: list[profile.Row], zone: ZoneInfo, first: str, last: str) -> list[str]:
    """Per day its date and weekday, the latest first; per text its clock, source, language, length,
    title and show, and the excerpt under it; last, the count."""
    window = first if first == last else f"{first} to {last}"
    if not rows:
        where = "on" if first == last else "from"
        return [f"nothing heard {where} {window}; `logbook sync heard` stores the texts"]
    out: list[str] = []
    by_day: dict[str, list[profile.Row]] = {}
    for row in rows:
        by_day.setdefault(row.day, []).append(row)
    for day in sorted(by_day, reverse=True):
        out.append(f"{day} {WEEKDAYS[date.fromisoformat(day).weekday()]}")
        for row in by_day[day]:
            clock = datetime.fromisoformat(row.at.replace("Z", "+00:00")).astimezone(zone).strftime("%H:%M")
            title = f"{row.title} — {row.by}" if row.by else row.title or "[sealed heard/v1]"
            length = f"{row.chars:>7,} chars  {row.words:>6,} words"
            out.append(f"  {clock}  {row.text_source:<8}  {row.language:<5}  {length}  {title}")
            if row.excerpt is not None:
                out.append(f"         «{row.excerpt}»")
            elif row.sealed:
                out.append("         (sealed; no identity on this machine to open it)")
            else:
                out.append("         (the text is not in the attachment store)")
    texts = f"{len(rows):,} {'text' if len(rows) == 1 else 'texts'}"
    out.append(f"{texts}, {window}")
    return out
