"""The Day page's rhythm (v1): one page with four shapes that follow the hour, and the parts the
shapes are made of, each read from a reader the record already has. Nothing here is stored, nothing
is written, no model is asked and no connection is opened: every part is computed on the request
from the record, through the page's gate (`tiers`).

**The shape** (`shape_of`): `signed` when the day has a standing signature; on today, `morning` from
the day's start until 11:00 local or the day's first stay of note after the night (a stay or a time
aboard that is not where the night was spent), whichever comes first; `evening` from the evening
hour (`LOGBOOK_NOTIFY_EVENING_HOUR`, as the daily loop reads it: the environment, else the install's
`sync.env`; with none set, today is never evening); `live` otherwise. A day before today that is
not signed is `evening`; a day ahead of today is `live` (nothing lived yet, the plan so far). The
page's `?shape=` shows another shape of the same day for reading only: the forms on it are the
page's own, and an unknown value is the computed shape.

**The parts**, each one function below: the eyebrow and the meta line of the header; **For**, the
chapter the day is in (and its rules) and the goals the day touched (`touched`: a line of the
goal's chain written on the day, a review of it written on the day, or a review that names a line
of the day as what it rests on, the grounds the Goals shelf reads a review by), each linked;
**Yesterday**, signed or open, what arrived after its signature, what it carried, and the nearest
earlier day still open; **the ribbon** (`ribbon`), the day from its start to its end in two lanes,
the calendar's timed entries planned (hollow and dashed when nothing lived is beside them: an entry
the Day leaves unplaced) and the stays, moves and time aboard lived, calls as ticks, now on today;
**Today**, the timed plan and the promises due; **Loose ends**, the promises made on the day and due
on it, both ways (`promises.extract` over `PROMISE_DAYS` before the day, so a promise due on a day
is one said in the fortnight before it), and the decisions of the day's call syntheses; **People**,
who showed up, by time together; the birthdays of the coming week (`people.directory`, the
`extra.birthday` of a resolution line); **Looking back**, this day 1, 2, 3, 5 and 10 years ago,
the ones the record has (`looking_back`); **Nothing from**, every part with nothing for the day,
named once. A person's name is never beside a count, an age or a score."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from html import escape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..core import day as day_reader
from ..core import day_start, keepers, notes, people, reading, signing, stars, stays, weather
from ..core.chain import Line
from ..core.flights import Airports
from ..core.store import RETRACTION, Logbook, retractions
from . import promises, reflect, schedule, shelf_goals

MORNING, LIVE, EVENING, SIGNED = "morning", "live", "evening", "signed"
SHAPES = (MORNING, LIVE, EVENING, SIGNED)
MORNING_ENDS = time(11)  # a morning ends at 11:00 local, or at the first stay of note, whichever first
YEARS_BACK = (1, 2, 3, 5, 10)  # Looking back: this day so many years ago, as `people_drift.YEARS`
PROMISE_DAYS = 14  # Loose ends and Today read the promises said in this many days before the day
WEEK = 7  # the birthdays of the coming week: today and the seven days after it
OPEN_DAYS = 60  # Yesterday looks this far back for the nearest day still open
DOT = day_reader.DOT
RSQUO = "\u2019"
DASH = day_reader.EN_DASH
NO_FOR = "No goals or chapter set yet — the page can't say what a day was for."
NO_FOR_DAY = "No chapter holds this day and it touched no goal."
FOOTER = "Every row is computed from the record. What a model wrote is in pencil, with the lines it rests on."
NO_PLAN = "nothing planned in the calendar"
NO_TRACK = "no location lines for the day"
NO_STAY = "no stay or move the day's location lines make"
LEGEND = (("stay", "stay"), ("move", "move"), ("aboard", "aboard"), ("call", "call"))
SINGULAR = {"promises": "promise", "decisions": "decision", "photos": "photo", "years": "year"}

ORDER = {  # each shape's parts, top to bottom; a part with nothing for the day is not drawn
    MORNING: ("header", "for", "yesterday", "today", "words", "one-person", "record", "nothing-from", "add",
              "foot"),
    LIVE: ("header", "for", "so-far", "words", "photos", "add", "record", "nothing-from", "pencil", "quiet",
           "foot"),
    EVENING: ("header", "for", "tiers", "the-day", "words", "pencil", "record", "photos", "nothing-from",
              "close", "foot"),
    SIGNED: ("header", "words", "photos", "the-day", "record", "nothing-from", "pencil", "close", "foot"),
}  # fmt: skip
FOLDS = {  # each shape's folds of the record, in order: the shape's own first, then the rest
    MORNING: ("reviews", "goals", "timeline", "looking-back", "sources", "loose-ends", "people", "photos",
              "outside", "unplaced", "health", "weather", "circle", "held", "pencil"),
    LIVE: ("loose-ends", "reviews", "goals", "timeline", "sources", "people", "outside", "unplaced",
           "looking-back", "health", "weather", "circle", "held"),
    EVENING: ("loose-ends", "people", "reviews", "goals", "timeline", "looking-back", "outside", "unplaced",
              "health", "weather", "circle", "held", "sources"),
    SIGNED: ("people", "reviews", "goals", "timeline", "looking-back", "sources", "loose-ends", "outside",
             "unplaced", "health", "weather", "circle", "held"),
}  # fmt: skip
HEADINGS = {
    **{(shape, name): word for shape in SHAPES for name, word in (
        ("yesterday", "Yesterday"), ("today", "Today"), ("one-person", "One person"), ("so-far", "So far"),
        ("the-day", "The day"), ("photos", "Photos"),
    )},
    **{(shape, "record"): "The record so far" if shape in (MORNING, LIVE) else "The record"
       for shape in SHAPES},
}  # fmt: skip
CLOSE_HEADING = {
    MORNING: "Add to today",
    LIVE: "Add to today",
    EVENING: "Close the day",
    SIGNED: "Reflect and sign",
}

# the owner's design: these tokens, as custom properties on the Day page only. Text keeps 4.5:1 in
# both themes: --gfaint (4.41:1 on --paper in light) carries no text, --plan and --star only graphics (3:1)
LIGHT = (
    "--bg:#fbfaf7;--fg:#22252a;--ink:#1c1a17;--mute:#666a71;--line:#e6e2d8;--accent:#2f5d7c;"
    "--paper:#f4efe3;--rule:#e8dfcc;--graphite:#47433c;--gfaint:#746e62;--star:#9a760f;--stay:#2e7d4f;"
    "--move:#3a62b0;--aboard:#1f6f88;--call:#a35a16;--plan:#868b93;--card:#ffffff"
)
DARK = (
    "--bg:#121315;--fg:#e6e6e3;--ink:#f3f0e9;--mute:#a4a7ac;--line:#2c2e32;--accent:#8fb8d6;"
    "--paper:#1d1c19;--rule:#2b2924;--graphite:#dcd6c8;--gfaint:#a8a295;--star:#e2bf52;--stay:#6cc08a;"
    "--move:#88a8ea;--aboard:#6fc2da;--call:#e39a55;--plan:#8d9299;--card:#1b1c1f"
)
SERIF = '"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif'
SANS = 'system-ui,-apple-system,"Segoe UI",sans-serif'
MONO = "ui-monospace,SFMono-Regular,Menlo,monospace"
STYLE = f"""
:root{{{LIGHT};--serif:{SERIF};--sans:{SANS};--mono:{MONO}}}
@media (prefers-color-scheme:dark){{:root{{{DARK}}}}}
body{{font-size:15px;line-height:1.5;font-family:var(--sans);background:var(--bg);color:var(--fg)}}
main a{{color:var(--accent)}}
section.part{{margin:0}}
section.part>h2,p.eyebrow,div.paper p.eyebrow{{font-weight:600;font-size:11px;line-height:1.4;
font-family:var(--sans);letter-spacing:.13em;
text-transform:uppercase;color:var(--mute);margin:26px 0 8px}}
section.part>h2 small,p.eyebrow small{{text-transform:none;letter-spacing:0;font-weight:400;float:right}}
section.header p.eyebrow{{margin:18px 0 4px}}
section.header h1{{font-weight:500;font-size:31px;line-height:1.1;font-family:var(--serif);color:var(--ink);
margin:0 0 6px}}
section.header h1 small{{font-weight:400;font-size:15px;line-height:1.5;font-family:var(--sans);
color:var(--mute)}}
p.meta{{margin:0 0 10px;color:var(--fg)}}
p.asked{{font-size:13.5px;color:var(--mute);margin:0 0 8px}}
p.for{{margin:14px 0 10px}}p.for .ink{{font-family:var(--serif);color:var(--ink)}}
.ink,.person,div.reflection p{{font-family:var(--serif);color:var(--ink)}}
div.reflection p.mute{{font-family:var(--sans);color:var(--mute)}}
.mono,span.t,svg.ribbon text,span.ev{{font-family:var(--mono)}}
div.card{{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:14px}}
div.card p{{margin:0 0 6px}}div.card p:last-child{{margin:0}}
ul.rows{{list-style:none;padding:0;margin:0}}
ul.rows li{{display:flex;gap:.7rem;padding:7px 0;border-bottom:1px solid var(--line);font-size:13.5px}}
ul.rows li:last-child{{border-bottom:0}}
ul.rows span.t{{flex:0 0 3.2rem;color:var(--mute);font-size:12.5px;padding-top:1px}}
ul.rows span.sub{{display:block;color:var(--mute);font-size:12.5px}}
svg.ribbon{{display:block;width:100%;max-width:100%;height:auto;margin:4px 0 2px}}
svg.ribbon text{{font-size:10px;fill:var(--mute)}}
svg.ribbon text.lane{{letter-spacing:.13em}}
svg.ribbon line.hour{{stroke:var(--line)}}
svg.ribbon rect.plan.filled{{fill:var(--plan)}}
svg.ribbon rect.plan.hollow{{fill:none;stroke:var(--plan);stroke-width:1.2;stroke-dasharray:3 2}}
svg.ribbon rect.stay{{fill:var(--stay)}}svg.ribbon rect.move{{fill:var(--move)}}
svg.ribbon rect.aboard{{fill:var(--aboard)}}
svg.ribbon line.call{{stroke:var(--call);stroke-width:1.5}}
svg.ribbon line.now{{stroke:var(--accent);stroke-width:1.5}}
p.legend{{font-size:12px;color:var(--mute);margin:0 0 4px}}
p.legend span{{font-weight:600}}p.legend .stay{{color:var(--stay)}}p.legend .move{{color:var(--move)}}
p.legend .aboard{{color:var(--aboard)}}p.legend .call{{color:var(--call)}}
p.nothing,p.quiet{{color:var(--mute);font-size:13.5px;margin:14px 0}}
section.record details.fold{{margin:0;padding:0;border-top:1px solid var(--line)}}
section.record{{border-bottom:1px solid var(--line)}}
details.fold>summary{{list-style:none;cursor:pointer;display:flex;flex-wrap:wrap;align-items:center;
column-gap:.5rem;min-height:44px}}
details.fold>summary::marker{{content:""}}
details.fold>summary::before{{content:"\\25B8";font-size:11px;color:var(--mute);display:inline-block;
transition:transform .15s}}
details.fold[open]>summary::before{{transform:rotate(90deg)}}
details.fold>summary h2{{display:inline;font-weight:600;font-size:15px;line-height:1.3;
font-family:var(--sans);
margin:0;letter-spacing:0;
text-transform:none;color:var(--fg)}}
details.fold>summary span.sum{{color:var(--mute);font-size:13.5px}}
div.fold{{padding:0 0 12px 20px;font-size:13.5px}}
div.fold h3{{font-weight:600;font-size:11px;line-height:1.4;font-family:var(--sans);letter-spacing:.13em;
text-transform:uppercase;color:var(--mute);
margin:12px 0 4px}}
div.fold ol.timeline>li,div.fold ul.unplaced>li{{border-bottom:1px solid var(--line);padding:4px 0}}
section.record section.held details.held{{margin:0;min-height:44px}}
div.paper{{background-color:var(--paper);background-image:repeating-linear-gradient(to bottom,
transparent 0,transparent 27px,var(--rule) 27px,var(--rule) 28px);border-radius:3px;color:var(--graphite);
font-size:16px;line-height:28px;font-family:var(--serif);padding:0 14px 1px}}
div.paper p{{margin:0 0 28px}}div.paper p.eyebrow{{margin:0;padding-top:0;line-height:28px}}
div.paper h2{{display:none}}
div.paper .sc{{font-variant:small-caps;text-transform:none;letter-spacing:.04em}}
div.paper p.mute,div.paper .mute{{color:var(--mute)}}
div.paper p.segment.unsupported{{font-style:italic}}
div.paper span.id{{font-size:10.5px;font-family:var(--mono);color:var(--accent)}}
div.paper span.kind,span.tag{{font-size:10.5px;line-height:1.4;font-family:var(--sans);
border:1px solid var(--rule);border-radius:999px;
padding:0 6px;color:var(--graphite)}}
li.decision{{color:var(--graphite);font-family:var(--serif);background:var(--paper)}}
li.decision small{{font-size:10.5px;font-family:var(--mono);color:var(--accent)}}
blockquote.ink{{margin:4px 0 0;font-style:italic}}
ul.gallery{{list-style:none;display:flex;flex-wrap:wrap;gap:.4rem;padding:0;margin:.4rem 0}}
ul.gallery img{{display:block;width:8rem;max-width:100%;height:auto;border-radius:3px}}
ul.gallery li.starred{{outline:2px solid var(--star);border-radius:3px}}
section.close button,section.review button,section.add button,form.with button{{min-height:44px;
border-radius:22px;background:var(--ink);color:var(--bg);border:1px solid var(--ink);padding:0 18px;
font-weight:600;font-size:14px;font-family:var(--sans);cursor:pointer}}
section.review button[value=pass]{{background:transparent;color:var(--ink)}}
form.star button{{min-width:44px;min-height:44px;background:transparent;border:0;color:var(--ink)}}
p.foot{{color:var(--mute);font-size:12.5px;margin:30px 0 10px}}
@media (max-width:40rem){{div.fold{{padding-left:12px}}ul.rows span.t{{flex-basis:2.8rem}}}}
"""


# -- the shape ------------------------------------------------------------------------------------------


def evening_hour() -> int | None:
    """The evening hour as the daily loop reads it: `LOGBOOK_NOTIFY_EVENING_HOUR` in the environment,
    else in `~/.config/logbook/sync.env`; None when neither sets an hour."""
    return schedule.evening_hour_of(os.environ, Path.home())


def shape_of(
    day: date,
    now: datetime,
    *,
    signed: bool,
    first_stay: datetime | None,
    evening: int | None,
    today: date | None = None,
) -> str:
    """The shape of `day` at `now` (local, aware): the module's rule. `today` is the day the owner is
    in (the record's `day_start`), `now`'s date when not given; `first_stay` when the day's first stay
    of note after the night began."""
    if signed:
        return SIGNED
    on = now.date() if today is None else today
    if day < on:
        return EVENING
    if day > on:
        return LIVE
    clock = now.replace(tzinfo=None)
    if evening is not None and clock >= datetime.combine(on, time(evening)):
        return EVENING
    morning = clock < datetime.combine(on, MORNING_ENDS)
    if morning and (first_stay is None or clock < first_stay.replace(tzinfo=None)):
        return MORNING
    return LIVE


def asked(value: str | None) -> str | None:
    """The shape `?shape=` asks for, or None for none and for a word that is not one."""
    return value if value in SHAPES else None


def first_stay(data: Mapping[str, Any], zone: ZoneInfo) -> datetime | None:
    """When the day's first stay of note after the night began, local: the first stay or time aboard
    that is not where the night before was spent; None before there is one, and on a day whose night
    before has no stay."""
    night = (data["nights"]["before"] or {}).get("stay")
    if night is None:  # no night to leave (the phone off, in transit, the first day tracked): 11:00 alone
        return None
    for entry in data["timeline"]:
        if entry["kind"] not in (stays.STAY, day_reader.ABOARD) or entry.get("gap") or entry["id"] == night:
            continue
        return _instant(entry["within_day"]["start"]).astimezone(zone)
    return None


def clock_tag(day: str, meta: Mapping[str, Any], now: datetime) -> str:
    """What a Day's tag adds for its shape: the evening hour (the live shape names it), and on today
    the minute (the shape and the now line move with it); any other day's shape the head decides."""
    try:
        bounds = day_start.of(meta)
    except day_start.DayStartError:
        return "-"
    hour = evening_hour()
    if bounds.today(now).isoformat() != day:
        return f"{hour}"
    return f"{now.astimezone(bounds.zone).strftime('%H:%M')} {hour}"


def eyebrow(
    weekday: str, shape: str, now: datetime | None, signed: Mapping[str, Any] | None, day: str
) -> str:
    """`Saturday · evening · 21:40` on today; the clock left out on any other day; a signed day
    `Saturday · signed 21:52`, with the date when it was signed on a later one."""
    if shape == SIGNED and signed is not None:
        local = str(signed["at_local"])
        when = local[11:16] if local[:10] == day else f"{local[:10]} {local[11:16]}"
        return f"{weekday}{DOT}signed {when}"
    parts = [weekday, shape]
    if now is not None:
        parts.append(now.strftime("%H:%M"))
    return DOT.join(parts)


def meta_line(
    data: Mapping[str, Any], company: Sequence[Mapping[str, Any]], person: Callable[[Mapping[str, Any]], str]
) -> str:
    """The header's one line: where the night after was spent, the weather when the record has it,
    and who was there, as the `with` row says them."""
    night = data["nights"]["after"]
    parts = [escape("in transit" if night["in_transit"] else str(night["where"] or "unknown"))]
    if data.get("weather"):
        short = weather.short_text(data["weather"])
        if short:
            parts.append(escape(short))
    if company:
        parts.append(
            "with "
            + ", ".join(person(c) + (f" ({day_reader.STATED})" if c.get("stated") else "") for c in company)
        )
    return f'<p class="meta">{DOT.join(parts)}</p>\n'


# -- For ---------------------------------------------------------------------------------------------------


def touched(shelf: shelf_goals.Shelf, on_day: Iterable[str]) -> list[shelf_goals.Goal]:
    """The goals the day touched, in the shelf's order: a line of the goal's chain written on the
    day, a review of it written on the day, or a review that names a line of the day."""
    ids = set(on_day)
    chain: dict[str, set[str]] = {}
    for line, standing in shelf.by_line.items():
        chain.setdefault(standing, set()).add(line)
    found = []
    for g in shelf.goals:
        if chain.get(g.line, {g.line}) & ids or any(
            r.line in ids or ids.intersection(r.lines) for r in g.reviews
        ):
            found.append(g)
    return found


def for_html(
    shelf: shelf_goals.Shelf | None, goals: Sequence[shelf_goals.Goal], link: Callable[[str, str], str]
) -> str:
    """For: the chapter the day is in, its rules in quotes, then the goals it touched, each linked;
    the sentence that says so when the record sets neither. Never a guess."""
    chapter = shelf.chapter if shelf is not None else None
    named = []
    if chapter is not None:
        rules = f" “{escape(chapter.rules)}”" if chapter.rules else ""
        named.append(f'<span class="ink">{link(chapter.name, "/goals")}</span>{rules}')
    named += [link(g.text, shelf_goals.goal_path(g.line)) for g in goals]
    if not named:
        written = shelf is not None and (shelf.goals or shelf.chapters)
        said = NO_FOR_DAY if written else NO_FOR
        return f'<p class="for mute">{escape(said, quote=False)} {link("Goals", "/goals")}</p>\n'
    return f'<p class="for"><span class="eyebrow-inline mute">For</span> {DOT.join(named)}</p>\n'


# -- the ribbon -----------------------------------------------------------------------------------------

W, LANE = 360, 14
PLAN_Y, LIVED_Y, HOURS_Y, HEIGHT = 12, 44, 78, 84


@dataclass(frozen=True)
class Planned:
    title: str
    start: datetime
    end: datetime
    beside: bool  # something lived beside it: the Day placed it at a stay or a move
    where: str | None
    line: str


def planned(data: Mapping[str, Any], lines: Mapping[str, Line]) -> list[Planned]:
    """The day's timed calendar entries in time order: those the Day placed at a row (something
    lived beside them) and those it left unplaced; an all-day entry is not one."""
    found: dict[str, Planned] = {}

    def add(item: Mapping[str, Any], start: str, end: str | None, beside: bool, where: str | None) -> None:
        line = str(item["line"])
        payload = (lines.get(line) or {}).get("payload") or {}
        if payload.get("all_day") is True or line in found:
            return
        a = _instant(start)
        b = _instant(end) if end else a + timedelta(minutes=30)
        found[line] = Planned(str(item["title"]), a, max(a, b), beside, where, line)

    for entry in _rows(data["timeline"]):
        for event in (entry.get("attached") or {}).get("events") or []:
            add(event, event["start"], event.get("end"), True, named(entry) or None)
    for item in data["unplaced"]:
        if item["kind"] == "event":
            add(item, item["at"], item.get("end"), False, None)
    return sorted(found.values(), key=lambda p: (p.start, p.title))


def calls(data: Mapping[str, Any], lines: Mapping[str, Line]) -> list[datetime]:
    """When each of the day's calls was, from its line."""
    found: dict[str, datetime] = {}
    for entry in _rows(data["timeline"]):
        for call in (entry.get("attached") or {}).get("calls") or []:
            line = lines.get(str(call["line"]))
            if line is not None:
                found[str(call["line"])] = _instant(str(line["at"]))
    for item in data["unplaced"]:
        if item["kind"] == "call":
            found[str(item["line"])] = _instant(str(item["at"]))
    return sorted(found.values())


def ribbon(
    data: Mapping[str, Any],
    lines: Mapping[str, Line],
    span: tuple[datetime, datetime],
    now: datetime | None,
) -> str:
    """The day in two lanes from its start to its end, inline: PLANNED, the calendar's timed entries
    (filled when something lived is beside one, hollow and dashed when nothing is); LIVED, the stays,
    moves and time aboard in their colours and the calls as thin ticks; the hours every three; now,
    on today. Its `aria-label` says the same in a sentence; the legend under it names the colours.
    Nothing here weighs the plan against the day."""
    zone = span[0].tzinfo
    start, end = (
        t.astimezone(UTC) for t in span
    )  # in UTC: two stamps of one zone subtract by the wall clock
    whole = (end - start).total_seconds()

    def x(t: datetime) -> float:
        return round(max(0.0, min(1.0, (t - start).total_seconds() / whole)) * W, 1)

    def hm(t: datetime) -> str:
        return t.astimezone(zone).strftime("%H:%M")

    plan = [p for p in planned(data, lines) if p.end > start and p.start < end]
    out: list[str] = [f'<text class="lane" x="0" y="{PLAN_Y - 3}">PLANNED</text>']
    for p in plan:
        a, b = x(p.start), x(p.end)
        cls = "plan filled" if p.beside else "plan hollow"
        out.append(
            f'<rect class="{cls}" x="{a}" y="{PLAN_Y}" width="{max(b - a, 2.0):.1f}" height="{LANE}" rx="2">'
            f"<title>{escape(p.title)} {hm(p.start)}{DASH}{hm(p.end)}</title></rect>"
        )
    if not plan:
        out.append(f'<text x="0" y="{PLAN_Y + 10}">{NO_PLAN}</text>')
    out.append(f'<text class="lane" x="0" y="{LIVED_Y - 3}">LIVED</text>')
    lived: dict[str, int] = {}
    for entry in data["timeline"]:
        if entry.get("gap"):
            continue
        kind = _lived_kind(entry)
        if kind is None:
            continue
        within = entry.get("within_day") or {
            "start": entry["start"],
            "end": entry.get("end") or entry["start"],
        }
        a, b = x(_instant(within["start"])), x(_instant(within["end"]))
        lived[kind] = lived.get(kind, 0) + 1
        what = " ".join(x for x in (kind, named(entry)) if x)
        out.append(
            f'<rect class="{kind}" x="{a}" y="{LIVED_Y}" width="{max(b - a, 1.5):.1f}" height="{LANE}">'
            f"<title>{escape(what)} {hm(_instant(within['start']))}{DASH}"
            f"{hm(_instant(within['end']))}</title></rect>"
        )
    rang = [t for t in calls(data, lines) if start <= t < end]
    for t in rang:
        out.append(
            f'<line class="call" x1="{x(t)}" y1="{LIVED_Y - 4}" x2="{x(t)}" y2="{LIVED_Y + LANE + 4}"/>'
        )
    why = NO_STAY if any(line.get("kind") == "location" for line in lines.values()) else NO_TRACK
    if not lived:
        out.append(f'<text x="0" y="{LIVED_Y + 10}">{why}</text>')
    wall = start.astimezone(zone).replace(tzinfo=None)  # the hours by the clock on the wall: a DST day too
    for h in range(0, 25, 3):
        t = end if h == 24 else (wall + timedelta(hours=h)).replace(tzinfo=zone)
        at = x(t)
        anchor = "start" if h == 0 else "end" if h == 24 else "middle"
        label = f"{(wall.hour + h) % 24:02d}" if h < 24 else f"{wall.hour or 24:02d}"
        out.append(f'<line class="hour" x1="{at}" y1="{LIVED_Y + LANE + 2}" x2="{at}" y2="{HOURS_Y - 9}"/>')
        out.append(f'<text x="{at}" y="{HOURS_Y}" text-anchor="{anchor}">{label}</text>')
    if now is not None and start <= now < end:
        out.append(
            f'<line class="now" x1="{x(now)}" y1="{PLAN_Y - 2}" x2="{x(now)}" y2="{LIVED_Y + LANE + 2}"/>'
        )
    entries = [f"{p.title} {hm(p.start)}{'' if p.beside else ', nothing beside it'}" for p in plan]
    said = _ribbon_said(entries, lived, len(rang), hm(start), hm(end), why)
    said += " A line marks now." if now is not None and start <= now < end else ""
    legend = DOT.join(f'<span class="{cls}">{word}</span>' for cls, word in LEGEND)
    return (
        f'<svg class="ribbon" viewBox="0 0 {W} {HEIGHT}" role="img" aria-label="{escape(said)}">'
        + "".join(out)
        + "</svg>\n"
        + f'<p class="legend">{legend}{DOT}dashed: planned, nothing beside it</p>\n'
    )


def _ribbon_said(
    plan: Sequence[str], lived: Mapping[str, int], rang: int, first: str, last: str, why: str
) -> str:
    """The ribbon in a sentence: the day's span, the entries planned (one drawn hollow said so, as the
    legend says it), and what was lived, counted, or why nothing was."""
    planned_said = f"Planned: {'; '.join(plan) if plan else NO_PLAN}."
    counts = [_plural(n, k) for k, n in lived.items()] + ([_plural(rang, "call")] if rang else [])
    lived_said = f"Lived: {', '.join(counts)}." if counts else f"Lived: {why}."
    return f"The day from {first} to {last}. {planned_said} {lived_said}"


def named(entry: Mapping[str, Any]) -> str:
    """A row's name where the record names it: the place of a stay, the boat of a time aboard, the
    flight; a stay the record has not named is left unnamed (its coordinates are the timeline's)."""
    if entry["kind"] == day_reader.ABOARD:
        return str((entry.get("asset") or {}).get("name") or "")
    if entry["kind"] == day_reader.FLIGHT:
        return f"{entry.get('carrier') or ''} {entry.get('number') or ''}".strip()
    if entry["kind"] == stays.MOVE:
        return str(entry.get("mode") or "")
    return str(entry.get("place") or "")


def _lived_kind(entry: Mapping[str, Any]) -> str | None:
    kind = entry["kind"]
    if kind in (stays.STAY, stays.STOP):
        return "stay"
    if kind in (stays.MOVE, day_reader.FLIGHT):
        return "move"
    if kind == day_reader.ABOARD:
        return "aboard"
    return None


# -- Today and the loose ends ---------------------------------------------------------------------------


def promises_near(lb: Logbook, day: str, tiers: Sequence[int] | None) -> list[promises.Proposal]:
    """The promises said in the `PROMISE_DAYS` before `day` and on it, through the gate, that the
    promises reader shows and that are owed one way or the other."""
    allowed = None if tiers is None else {int(t) for t in tiers}

    def admit(line: Line) -> bool:
        return allowed is None or int(line.get("tier") or 0) in allowed

    since = (date.fromisoformat(day) - timedelta(days=PROMISE_DAYS)).isoformat()
    report = promises.extract(lb, since, until=day, admit=admit)
    return [p for p in report.proposals if p.shows and p.direction is not None]


def due_on(found: Sequence[promises.Proposal], day: str) -> list[promises.Proposal]:
    return [p for p in found if p.due == day and p.status == "open"]


def made_on(found: Sequence[promises.Proposal], day: str) -> list[promises.Proposal]:
    return [p for p in found if p.day == day]


def promise_said(p: promises.Proposal, day: str, person: Callable[[Mapping[str, Any]], str]) -> str:
    """The sub-line of a promise: whose, and the day it was said (`you promised on Thursday`)."""
    when = _day_word(p.day, day)
    who = p.counterpart or (p.speaker.label if p.speaker is not None and not p.speaker.owner else None)
    named = f"{DOT}{person({'name': who, 'person': None})}" if who else ""
    if p.direction == promises.OWED_TO_OWNER:
        return f"you were promised {when}{named}"
    if p.role == promises.ASKED:
        return f"you were asked {when}{named}"
    return f"you promised {when}{named}"


def today_html(
    plan: Sequence[Planned],
    due: Sequence[promises.Proposal],
    day: str,
    zone: ZoneInfo,
    person: Callable[[Mapping[str, Any]], str],
) -> str:
    """Today's timed plan in time order, then what is due on it: one row each."""
    rows = []
    for p in plan:
        where = f"at {escape(p.where)}{DOT}" if p.where else ""
        rows.append(
            f'<li class="plan"><span class="t">{p.start.astimezone(zone).strftime("%H:%M")}</span>'
            f'<span>{escape(p.title)}<span class="sub">{where}from the calendar</span></span></li>\n'
        )
    for promise in due:
        rows.append(
            f'<li class="due"><span class="t">due</span><span>“{escape(promise.match.quote)}”'
            f'<span class="sub">{promise_said(promise, day, person)}</span></span></li>\n'
        )
    if not rows:
        return '<p class="mute">Nothing timed in the calendar and nothing due.</p>\n'
    return '<ul class="rows">\n' + "".join(rows) + "</ul>\n"


def decisions(data: Mapping[str, Any]) -> list[tuple[Mapping[str, Any], Mapping[str, Any]]]:
    """(synthesis, segment) for each decision the day's call syntheses wrote."""
    return [
        (block, segment)
        for block in data.get("syntheses") or []
        for segment in block.get("segments") or []
        if segment.get("part") == "decisions"
    ]


def loose_ends(
    found: Sequence[promises.Proposal],
    data: Mapping[str, Any],
    day: str,
    zone: ZoneInfo,
    person: Callable[[Mapping[str, Any]], str],
) -> tuple[str, str]:
    """(summary, body) of Loose ends; ("", "") when the day has none. Read-only: no form."""
    made, due = made_on(found, day), [p for p in due_on(found, day) if p.day != day]
    decided = decisions(data)
    if not made and not due and not decided:
        return "", ""
    mine = [p for p in made if p.direction == promises.OWED_BY_OWNER and p.role != promises.ASKED]
    asked_of = [p for p in made if p.role == promises.ASKED]
    theirs = [p for p in made if p.direction == promises.OWED_TO_OWNER]
    summary = _counts(
        [
            (len(mine), "promises", " made"),
            (len(asked_of), "", "asked of you"),
            (len(theirs), "", "owed to you"),
            (len(due), "", "due"),
            (len(decided), "decisions", ""),
        ]
    )
    body: list[str] = []

    def rows(title: str, items: Sequence[promises.Proposal]) -> None:
        if not items:
            return
        body.append(f'<h3>{title}</h3>\n<ul class="rows">\n')
        for p in items:
            due_said = f"{DOT}due {_day_word(p.due, day, after=True)}" if p.due and p.due != day else ""
            body.append(
                f'<li class="promise"><span class="t">{_local(p.at, zone)}</span><span>'
                f"“{escape(p.match.quote)}”"
                f'<span class="sub">{promise_said(p, day, person)}{due_said}</span></span></li>\n'
            )
        body.append("</ul>\n")

    rows("Made on the day", made)
    rows("Due on the day", due)
    if decided:
        body.append('<h3>Decisions</h3>\n<ul class="rows">\n')
        for block, segment in decided:
            mark = ""
            if segment.get("supported"):
                where = escape(str(segment.get("where") or "")) if segment.get("where") else ""
                mark = f' <small title="line {escape(str(block["transcript"]))}">[{where or "call"}]</small>'
            unsupported = "" if segment.get("supported") else ' <span class="tag">unsupported</span>'
            body.append(
                f'<li class="decision"><span class="t">pencil</span><span>{escape(str(segment["text"]))}'
                f'{mark}{unsupported}<span class="sub">from the call{RSQUO}s synthesis{DOT}'
                f'<span class="sc">{escape(model_of(block))}</span></span>'
                "</span></li>\n"
            )
        body.append("</ul>\n")
    return summary, "".join(body)


# -- people ------------------------------------------------------------------------------------------------


def people_of_day(data: Mapping[str, Any], lines: Mapping[str, Line]) -> list[dict[str, Any]]:
    """Who showed up, the most time together first: the people confirmed at a row (an attendee, a
    speaker, a note's `with`), for as long as the line that confirms them lasted (the row when it
    has no end), the people the owner said were there, and the people of the day's calls."""
    time_with: dict[str, dict[str, Any]] = {}

    def add(key: str, name: str, person: str | None, seconds: float, where: str | None) -> None:
        found = time_with.setdefault(
            key, {"name": name, "person": person, "seconds": 0.0, "where": [], "stated": False}
        )
        found["seconds"] += seconds
        if where and where not in found["where"]:
            found["where"].append(where)

    for entry in _rows(data["timeline"]):
        row = float((entry.get("within_day") or {}).get("duration_s") or 0)
        for c in (entry.get("with") or {}).get("confirmed") or []:
            evidence = [lines.get(str(i)) or {} for i in c.get("lines") or [c.get("line")]]
            timed = [line for line in evidence if line.get("end")]
            seconds = (  # as long as what confirms them lasted (an entry, a call), else the row
                sum(
                    (_instant(str(line["end"])) - _instant(str(line["at"]))).total_seconds() for line in timed
                )
                if timed
                else row
            )
            key = str(c.get("person") or str(c.get("name") or "").casefold())
            add(key, str(c["name"]), c.get("person"), seconds, named(entry) or None)
        for call in (entry.get("attached") or {}).get("calls") or []:
            if call.get("who") and call["who"] != "withheld":  # by name: the person a row confirms too
                who = str(call["who"])
                same = (k for k, p in time_with.items() if str(p["name"]).casefold() == who.casefold())
                add(next(same, who.casefold()), who, None, float(call.get("duration_s") or 0), None)
    for s in data.get("stated") or []:
        key = str(s.get("person") or str(s.get("name") or "").casefold())
        add(key, str(s["name"]), s.get("person"), 0.0, None)
        time_with[key]["stated"] = True
    return sorted(time_with.values(), key=lambda p: -p["seconds"])


@dataclass(frozen=True)
class Birthday:
    """A birthday the record holds: whose, and the day it falls on. Never an age: a person's name is
    not shown beside a number (RFC 0043 principle 5)."""

    name: str
    person: str
    on: date


def birthdays(directory: people.Report, day: str, days: int, tiers: Sequence[int] | None) -> list[Birthday]:
    """The birthdays the record holds from `day` to `days` after it, the nearest first; a person
    whose resolution lines the gate does not read is not among them."""
    allowed = None if tiers is None else {int(t) for t in tiers}
    first = date.fromisoformat(day)
    found = []
    for p in directory.known.values():
        if not p.birthday or (allowed is not None and p.tier not in allowed):
            continue
        month, dom = int(p.birthday[-5:-3]), int(p.birthday[-2:])
        for k in range(days + 1):
            d = first + timedelta(days=k)
            leap = month == 2 and dom == 29 and not _leap(d.year) and (d.month, d.day) == (2, 28)
            if (d.month, d.day) == (month, dom) or leap:
                found.append(Birthday(p.name, p.entity, d))
                break
    return sorted(found, key=lambda b: (b.on, b.name))


def birthday_said(b: Birthday, day: str, person: Callable[[Mapping[str, Any]], str]) -> str:
    """`Per Hansen's birthday is on Tuesday.`: the birthday alone, never an age and never a digit
    beside the name (`today`, a weekday within the week, `a week today` on the eighth day)."""
    gap = (b.on - date.fromisoformat(day)).days
    when = (
        "today" if gap == 0 else f"on {day_reader.WEEKDAYS[b.on.weekday()]}" if gap < WEEK else "a week today"
    )
    return f"{person({'name': b.name, 'person': b.person})}{RSQUO}s birthday is {when}."


# -- looking back ------------------------------------------------------------------------------------------


def years_back(day: str) -> list[tuple[int, str]]:
    """(years, the same day so many years before) for `YEARS_BACK`; 29 February is the 28th."""
    d = date.fromisoformat(day)
    out = []
    for years in YEARS_BACK:
        dom = 28 if (d.month, d.day) == (2, 29) and not _leap(d.year - years) else d.day
        out.append((years, date(d.year - years, d.month, dom).isoformat()))
    return out


def looking_back(
    lb: Logbook, day: str, airports: Airports, tiers: Sequence[int] | None
) -> list[dict[str, Any]]:
    """This day 1, 2, 3, 5 and 10 years ago, the ones the record has a line on through the gate: the
    night's place, the people, how many photos were starred, and the first sentence of that day's
    reflection. A year with no line is one count on the index and nothing read; a year with lines
    is read alone, the day and the night after it (`reading.read`)."""
    found = []
    for years, then in years_back(day):
        with lb.index() as idx:
            if idx.source_days(then, then, tiers)[0] == 0:
                continue
            on_day = reading.crossing(idx.day(then), tiers)
            retracted = retractions(idx.retractions())
        rd = reading.read(
            lb, then, then, airports, tiers
        )  # the day and its night after: no night before needed
        data = day_reader.of_reading(rd, then, None)
        data["stated"] = day_reader.stated_of(on_day, retracted)
        marks = [line for line in on_day if line.get("kind") in (stars.KIND, keepers.KIND)]
        by_id = {str(line["id"]): line for line in on_day}
        starred = stars.shown(stars.standing(marks, retracted), by_id)
        photos = sum(1 for i in starred if (by_id.get(i) or {}).get("kind") == stars.PHOTO)
        reflected = notes.standing(on_day, notes.REFLECTION, retracted)
        said = None
        if reflected:
            first = reflect.sentences(str((reflected[-1].get("payload") or {}).get("text") or ""))
            said = first[0] if first else None
        night = data["nights"]["after"]
        found.append(
            {
                "years": years,
                "day": then,
                "weekday": data["weekday"],
                "where": None if night["in_transit"] else night["where"],
                "people": day_reader.company_of_day(data),
                "starred": photos,
                "said": said,
            }
        )
    return found


def looking_back_html(
    found: Sequence[Mapping[str, Any]],
    link: Callable[[str, str], str],
    person: Callable[[Mapping[str, Any]], str],
) -> tuple[str, str]:
    """(summary, body) of Looking back; ("", "") when the record has none of the years."""
    if not found:
        return "", ""
    rows = []
    for b in found:
        ago = f"{b['years']} year{'s' if b['years'] != 1 else ''} ago"
        bits = [f'<span class="sub">{escape(b["weekday"])} {b["day"]}</span>']
        if b["starred"]:
            bits.append(_plural(b["starred"], "starred photo"))
        if b["where"]:
            bits.append(f"night at {escape(str(b['where']))}")
        if b["people"]:
            bits.append("with " + ", ".join(person(p) for p in b["people"]))
        said = f'<blockquote class="ink">“{escape(b["said"])}”</blockquote>' if b["said"] else ""
        rows.append(f'<li class="back">{link(ago, "/day/" + b["day"])} {DOT.join(bits)}{said}</li>\n')
    starred = sum(int(b["starred"]) for b in found)
    words = sum(1 for b in found if b["said"])
    summary = _counts(
        [
            (len(found), "", f"of {len(YEARS_BACK)} years"),
            (starred, "", "starred photos" if starred != 1 else "starred photo"),
            (words, "", "reflections" if words != 1 else "reflection"),
        ]
    )
    return summary, '<ul class="rows back">\n' + "".join(rows) + "</ul>\n"


# -- Yesterday ----------------------------------------------------------------------------------------


def yesterday(lb: Logbook, day: str, tiers: Sequence[int] | None) -> dict[str, Any]:
    """The day before `day`: its standing signature's when and what it kept and carried, what arrived
    on it after that signature (kind → count), and the nearest earlier day with a line and no
    signature, within `OPEN_DAYS`."""
    d = date.fromisoformat(day)
    y = (d - timedelta(days=1)).isoformat()
    owner = str(lb.meta.get("owner_id") or "") or None
    with lb.index() as idx:
        signed = signing.standing(idx, owner)
        on_y = reading.crossing(idx.day(y), tiers)
        first = (d - timedelta(days=OPEN_DAYS)).isoformat()
        logged = {
            day_ for row in idx.activity(first, (d - timedelta(days=2)).isoformat()) for day_ in row["days"]
        }
        # the nearest of them not signed that has a line through the gate: a count each, nothing read
        still_open = next(
            (
                x
                for x in sorted(logged, reverse=True)
                if x not in signed and (tiers is None or idx.source_days(x, x, tiers)[0])
            ),
            None,
        )
    signature = signed.get(y)
    after: dict[str, int] = {}
    kept = carried = 0
    if signature is not None:
        for line in on_y:
            if int(line["seq"]) > int(signature["seq"]) and line.get("kind") not in (
                RETRACTION,
                signing.KIND,
            ):
                after[str(line["kind"])] = after.get(str(line["kind"]), 0) + 1
        dispositions = signing.dispositions_of(signature.get("payload") or {})
        kept = sum(1 for v in dispositions.values() if v == signing.KEPT)
        carried = sum(1 for v in dispositions.values() if v == signing.CARRIED)
    return {
        "day": y,
        "signed": signature is not None,
        "kept": kept,
        "carried": carried,
        "after": after,
        "open": still_open,
    }


def yesterday_html(
    found: Mapping[str, Any], link: Callable[[str, str], str], close: Callable[[str], str]
) -> str:
    y = str(found["day"])
    weekday = day_reader.WEEKDAYS[date.fromisoformat(y).weekday()]
    rows = []
    if found["signed"]:
        kept = f"{DOT}you kept {found['kept']}" if found["kept"] else ""
        rows.append(f"<p>{link(f'{weekday} is signed', f'/day/{y}')}{kept}</p>")
        if found["after"]:
            rows.append(f"<p>{escape(_arrived(found['after']))} arrived after you signed{DOT}{close(y)}</p>")
        if found["carried"]:
            rows.append(f"<p>{weekday} carried {_plural(found['carried'], 'line')}, still open.</p>")
    else:
        rows.append(f"<p>{link(f'{weekday} is open', f'/day/{y}')}</p>")
    if found["open"]:
        o = str(found["open"])
        other = day_reader.WEEKDAYS[date.fromisoformat(o).weekday()]
        when = other if (date.fromisoformat(y) - date.fromisoformat(o)).days < 7 else f"{other} {o}"
        rows.append(f"<p>{link(f'{when} is still open', f'/day/{o}')} — anything to say about it?</p>")
    return '<div class="card">\n' + "\n".join(rows) + "\n</div>\n"


def _arrived(after: Mapping[str, int]) -> str:
    named = {"photo": "photo", "location": "tracker point", "message": "message", "mail": "mail"}
    parts = [
        _plural(n, named.get(kind, f"{kind} line"))
        for kind, n in sorted(after.items(), key=lambda kv: -kv[1])
    ]
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def timeline_summary(data: Mapping[str, Any], photos: Mapping[str, str]) -> str:
    """`2 stays · 2 moves · 11 km · 9 photos · 1 call`: the timeline's fold in counts."""
    counted: dict[str, int] = {}
    metres = 0
    for entry in data["timeline"]:
        kind = _lived_kind(entry) or str(entry["kind"])
        counted[kind] = counted.get(kind, 0) + 1
        if entry["kind"] == stays.MOVE and not entry.get("gap"):
            metres += int(entry.get("distance_m") or 0)
    parts = [_plural(counted[k], k) for k in ("stay", "move", "aboard") if counted.get(k)]
    if metres:
        parts.append(f"{metres / 1000:.0f} km" if metres >= 1000 else f"{metres} m")
    if photos:
        parts.append(_plural(len(photos), "photo"))
    rang = sum(len((e.get("attached") or {}).get("calls") or ()) for e in _rows(data["timeline"]))
    if rang:
        parts.append(_plural(rang, "call"))
    return DOT.join(parts)


# -- small things ------------------------------------------------------------------------------------------


def fold(title: str, summary: str, body: str, expanded: bool, cls: str = "") -> str:
    """One fold of the record: its title, the summary in counts beside it, the body indented."""
    extra = f" {cls}" if cls else ""
    return (
        f'<details class="fold{extra}"{" open" if expanded else ""}><summary><h2>{escape(title)}</h2>'
        f' <span class="sum">{escape(summary)}</span></summary>\n<div class="fold">\n{body}</div>\n'
        "</details><!--fold-->\n"
    )


def part(name: str, body: str, heading: str | None = None) -> str:
    """One part of the page, its name in the class the shapes order it by."""
    head = f"<h2>{heading}</h2>\n" if heading else ""
    return f'<section class="part {name}">\n{head}{body}</section><!--part-->\n'


def nothing_from(names: Sequence[str]) -> str:
    return f'<p class="nothing">Nothing from: {escape(DOT.join(names))}</p>\n' if names else ""


def _counts(items: Sequence[tuple[int, str, str]]) -> str:
    """`2 promises made · 1 owed to you`: (n, a plural noun or "", the words after) for each n."""
    out = []
    for n, noun, words in items:
        if not n:
            continue
        said = (SINGULAR.get(noun, noun) if n == 1 else noun) + words
        out.append(f"{n} {said.strip()}")
    return DOT.join(out)


def model_of(block: Mapping[str, Any]) -> str:
    """The model that wrote a draft or a synthesis, as its line names it."""
    return str(block.get("model") or block.get("source") or "")


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def _rows(timeline: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The timeline's rows and the rows inside a time aboard."""
    out: list[Mapping[str, Any]] = []
    for entry in timeline:
        out.append(entry)
        out.extend(entry.get("inside") or ())
    return out


def _instant(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(UTC)


def _local(stamp: str, zone: ZoneInfo) -> str:
    return _instant(stamp).astimezone(zone).strftime("%H:%M")


def _day_word(when: str | None, day: str, after: bool = False) -> str:
    """`on Thursday` within a week of `day`, `today`, else `on 2026-06-03`."""
    if not when:
        return ""
    if when == day:
        return "today"
    gap = (date.fromisoformat(day) - date.fromisoformat(when)).days
    if (0 < gap < 7 and not after) or (after and -7 < gap < 0):
        return f"on {day_reader.WEEKDAYS[date.fromisoformat(when).weekday()]}"
    return f"on {when}"


def _leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
