"""The week's paper: `logbook digest --paper [--week YYYY-Www] [--html PATH]` writes the week as
four pages of A4 — the days with their one line each (the line `logbook days` prints), the people
confirmed present and the week's keepers, the promises due, and what was read: the browse lines of
the week, titles only, never a URL. It is set from the Year's typographic constants
(`print_layout.paper_stylesheet`, the paper edition's stylesheet with the sheet pinned), one
inline stylesheet, no script, no photo, nothing fetched.

A week is an ISO week, Monday to Sunday (`parse_week`); without `--week` it is the week of the
day given, or of today in the record's zone. Everything is composed from the readers: the days
from `days.read` (one reading a chunk, the night after, the kilometres, the flights, the stays,
the people confirmed, the health triple, the gaps), the keepers from the keeper lines standing
(RFC 0024), the promises from `promises.extract` narrowed by `digest.due_promises` to the seven
days, the titles from the browse lines standing. Nothing is derived anew and nothing is written
(ADR 0013); the same record gives the same paper."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from . import days as days_reader
from . import digest, keepers, print_page, promises
from . import print_layout as layout
from .export import parse_day
from .flights import Airports
from .index import local_date
from .store import Logbook, retractions
from .year import DOT, MONTHS, escape, table

PAPER = "paper"
BROWSE = "browse"
WEEK = re.compile(r"(\d{4})-W(\d{2})")
WEEK_DAYS = 7


# -- the week -----------------------------------------------------------------------------------------------


def parse_week(text: str) -> tuple[str, str, str]:
    """`YYYY-Www` as (the week as given, its Monday, its Sunday); `ValueError` for anything else,
    a week the year does not have included."""
    found = WEEK.fullmatch(text)
    if found is None:
        raise ValueError(f"not a week (YYYY-Www): {text!r}")
    year, number = int(found.group(1)), int(found.group(2))
    try:
        monday = date.fromisocalendar(year, number, 1)
    except ValueError as e:
        raise ValueError(f"{text}: {e}") from e
    return text, monday.isoformat(), (monday + timedelta(days=WEEK_DAYS - 1)).isoformat()


def week_of(day: str) -> str:
    """The ISO week a local day is in, as `YYYY-Www`."""
    year, number, _weekday = parse_day(day).isocalendar()
    return f"{year}-W{number:02d}"


# -- the reading --------------------------------------------------------------------------------------------


def read(lb: Logbook, week: str, airports: Airports | None = None) -> dict[str, Any]:
    """The week's paper as one JSON-ready object: the week and its days, the owner's name as the
    paper edition names them, the head; the seven days as `days.read` gives them with the line
    `days.row` prints; the people confirmed with how many days each; the keepers (day, lane,
    name); the open promises due in the week; the titles read by day. `ValueError` for a week
    that is not one; `stays.SettingsError` when the record's settings, places or assets file is
    not what it should be."""
    week, first, last = parse_week(week)
    airports = airports or Airports.load()
    tz = str(lb.meta["timezone"])
    rows = [{**r, "line": days_reader.row(r)} for r in days_reader.read(lb, first, last, airports)]
    together: Counter[str] = Counter()
    for r in rows:
        together.update(r["people"]["names"])
    with lb.index() as idx:
        marks = idx.retractions()
        retracted = retractions(marks)
        kept = keepers.standing([*idx.by_kind(keepers.KIND, first, last), *marks])
        browsed = [line for line in idx.by_kind(BROWSE, first, last) if str(line["id"]) not in retracted]
    order = {lane: n for n, lane in enumerate(keepers.LANES)}
    found_keepers = sorted(
        (
            {
                "day": local_date(str(line["at"]), tz),
                "lane": str((line.get("payload") or {}).get("lane") or ""),
                "name": keepers.name_of(line),
            }
            for line in kept
        ),
        key=lambda k: (k["day"], order.get(k["lane"], len(order)), k["name"]),
    )
    due = digest.due_promises(promises.extract(lb), first, within=WEEK_DAYS - 1)
    return {
        "kind": PAPER,
        "week": week,
        "first": first,
        "last": last,
        "name": print_page.owner_name(lb, None),
        "head": str(lb.meta.get("head") or ""),
        "tz": tz,
        "days": rows,
        "people": [
            {"name": name, "days": n} for name, n in sorted(together.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "keepers": found_keepers,
        "promises": [p.to_json() for p in due],
        "read": titles(browsed, tz),
    }


def titles(lines: Sequence[Mapping[str, Any]], tz: str) -> list[dict[str, str]]:
    """The browse lines as (day, title) in time order, a title once a day, a line with no title
    left out; never the URL, never the source."""
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for line in sorted(lines, key=lambda line: (str(line["at"]), int(line["seq"]))):
        title = " ".join(str((line.get("payload") or {}).get("title") or "").split())
        day = local_date(str(line["at"]), tz)
        if title and (day, title) not in seen:
            seen.add((day, title))
            out.append({"day": day, "title": title})
    return out


# -- the paper ----------------------------------------------------------------------------------------------


def html(data: Mapping[str, Any]) -> str:
    """The week as one HTML document of four pages: the days, with whom and the keepers, the
    promises due, what was read; one inline stylesheet, no script, nothing fetched."""
    out = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{escape(data['week'])} · Logbook</title>",
        f"<style>{layout.paper_stylesheet()}</style>",
        "</head>",
        "<body>",
        *_days_page(data),
        *_with_page(data),
        *_promises_page(data),
        *_read_page(data),
        "</body>",
        "</html>",
    ]
    return "\n".join(out) + "\n"


def _header(data: Mapping[str, Any], heading: str, lead: str) -> list[str]:
    return [
        "<header>",
        f'<p class="kicker">Logbook{DOT}{escape(data["week"])}</p>',
        f"<h2>{escape(heading)}</h2>",
        f'<p class="lead">{escape(lead)}</p>',
        "</header>",
    ]


def _days_page(data: Mapping[str, Any]) -> list[str]:
    span = print_page.span_text(str(data["first"]), str(data["last"]))
    out = ['<section class="page" id="p-days">']
    out += _header(data, "The week", f"{span}{DOT}{data['name']}")
    out.append('<ol class="contents days">')
    for r in data["days"]:
        night = f"{days_reader.night_text(r)}{DOT}{days_reader.km_text(float(r['moved_m']))}"
        rest = DOT.join(days_reader.parts(r))
        out.append(
            f'<li class="day"><span class="what">{escape(day_text(r))}</span>'
            f'<span class="about"><span class="night">{escape(night)}</span>{DOT}{escape(rest)}</span></li>'
        )
    out += ["</ol>", "</section>"]
    return out


def _with_page(data: Mapping[str, Any]) -> list[str]:
    out = ['<section class="page" id="p-with">']
    out += _header(data, "With", "the people confirmed present, by days; the week's keepers")
    if data["people"]:
        out += table(
            [("who", ""), ("days", "n")],
            [[(str(p["name"]), ""), (f"{p['days']:,}", "n")] for p in data["people"]],
        )
    else:
        out.append('<p class="muted">nobody confirmed</p>')
    out.append("<h3>Keepers</h3>")
    if data["keepers"]:
        out += table(
            [("day", ""), ("lane", ""), ("photo", "")],
            [[(_long(k["day"]), "d"), (str(k["lane"]), ""), (str(k["name"]), "")] for k in data["keepers"]],
        )
    else:
        out.append('<p class="muted">none</p>')
    out.append("</section>")
    return out


def _promises_page(data: Mapping[str, Any]) -> list[str]:
    out = ['<section class="page" id="p-due">']
    out += _header(data, "Promises due", "open, due this week, as the promises reader proposes them")
    if data["promises"]:
        rows_ = []
        for p in data["promises"]:
            due = p.get("due") or {}
            when = str(due.get("date") or "")
            if due.get("phrase"):
                when += f" ({due['phrase']})"
            rows_.append(
                [
                    (when, "d"),
                    (_who(p), ""),
                    (digest._quote(str(p["quote"])), ""),
                    (f"{p.get('title') or p['kind']}{DOT}{_long(str(p['day']))}", ""),
                ]
            )
        out += table([("due", ""), ("who", ""), ("said", ""), ("in", "")], rows_)
    else:
        out.append('<p class="muted">none due this week</p>')
    out.append("</section>")
    return out


def _read_page(data: Mapping[str, Any]) -> list[str]:
    out = ['<section class="page" id="p-read">']
    out += _header(data, "Read", "the pages visited, titles only")
    by_day: dict[str, list[str]] = {}
    for r in data["read"]:
        by_day.setdefault(str(r["day"]), []).append(str(r["title"]))
    if not by_day:
        out.append('<p class="muted">nothing read</p>')
    for day, found in by_day.items():
        out.append(f"<h3>{escape(_weekday_long(day))}</h3>")
        out.append('<ul class="titles">' + "".join(f"<li>{escape(t)}</li>" for t in found) + "</ul>")
    head = str(data.get("head") or "")
    at = f" at head {escape(head[:12])}…" if head else ""
    out.append(
        f'<footer class="note"><p>Read from the record{at}: derived, never written; the same record'
        " gives the same paper. The titles are the browse lines' own; no address is printed.</p></footer>"
    )
    out.append("</section>")
    return out


# -- text ----------------------------------------------------------------------------------------------------


def day_text(r: Mapping[str, Any]) -> str:
    """`Monday 15 June`."""
    return f"{r['weekday']} {_long(str(r['day']), year=False)}"


def _weekday_long(day: str) -> str:
    d = date.fromisoformat(day)
    return f"{d.strftime('%A')} {d.day} {MONTHS[d.month - 1]}"


def _long(day: str, year: bool = True) -> str:
    return print_page.long_date(day, year=year)


def _who(p: Mapping[str, Any]) -> str:
    speaker = p.get("speaker") or {}
    if speaker.get("owner"):
        return "you"
    return str(speaker.get("label") or speaker.get("spoken") or "?")
