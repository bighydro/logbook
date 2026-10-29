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
**Today**, the timed plan and the promises due, then the morning's: the task tool's tasks of the
day and the next trip (`plan.read`, tier 1), who you'll see (the attendees of the day's timed
entries), and the week's one proposal (its draft's `next_week`, pencil); **One person**, a birthday,
else one reconnect from the drift rule (`drifted`, `reconnect`); **Loose ends**, the promises made on
the day and due on it, both ways (`promises.extract` over `PROMISE_DAYS` before the day, so a promise
due on a day is one said in the fortnight before it), the replies owed (`peoples_mail.replies_owed`),
the decisions of the day's call syntheses and the decisions to revisit on the day (`revisits`, a
`note/v1` labelled `decision` whose `extra.revisit` is the day); **People**,
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
from ..core import (
    day_start,
    drafts,
    keepers,
    notes,
    people,
    peoples_mail,
    present,
    reading,
    signing,
    stars,
    stays,
    weather,
)
from ..core.chain import Line
from ..core.export import day_range
from ..core.flights import Airports
from ..core.store import RETRACTION, Logbook, retractions
from . import people_drift, promises, reflect, schedule, shelf_goals, week_paper
from . import plan as plan_reader

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
INTENTION_WITHHELD = "The week's intention is withheld here: it sets a number beside a person's name."
NO_FOR_DAY = "No chapter holds this day and it touched no goal."
FOOTER = "Every row is computed from the record. What a model wrote is in pencil, with the lines it rests on."
NO_PLAN = "nothing planned in the calendar"
NO_TRACK = "no location lines for the day"
NO_STAY = "no stay or move the day's location lines make"
LEGEND = (("stay", "stay"), ("move", "move"), ("aboard", "aboard"), ("call", "call"))
SINGULAR = {
    "promises": "promise",
    "decisions": "decision",
    "photos": "photo",
    "years": "year",
    "replies": "reply",
    "tasks": "task",
    "people": "person",
}
TASKS, SEEING, PROPOSAL = f"Today{RSQUO}s tasks", f"Who you{RSQUO}ll see", f"the week{RSQUO}s proposal"
DECISION = "decision"  # a kept decision's label (RFC 0043 §4.8): a `note/v1`, `extra.revisit` a local day
REVISIT = "revisit"
SEASONS = ("winter", "winter", "spring", "spring", "spring", "summer", "summer", "summer", "autumn", "autumn",
           "autumn", "winter")  # fmt: skip
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")  # fmt: skip
WORDS = (
    "no",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
)
VIA = {  # a real contact in words (`people_drift`)
    people_drift.TOGETHER: "a day together",
    people_drift.MEETING: "a meeting",
    people_drift.CALL: "a call",
    people_drift.MESSAGE: "a message",
}

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

# the Day in the doors' look (`doors.library_style` before it): no token of its own but the chart colours
# `doors.PAGES` sets on `main`; ink the owner's words in the serif, pencil a model's in the pencil colour
# with a dotted rule and the model named in a title (RFC 0043 §3, RFC 0047 §7); counts in the mono
STYLE = """
section.part{margin:0}
section.part>h2,p.eyebrow,div.paper p.eyebrow{font-weight:500;font-size:13px;line-height:1.4;
font-family:var(--mono);letter-spacing:.13em;text-transform:uppercase;color:var(--pencil);margin:36px 0 12px}
section.part>h2 small,p.eyebrow small{text-transform:none;letter-spacing:0;font-weight:400;float:right}
section.header p.eyebrow{margin:0 0 10px}
section.header h1{margin:0 0 10px}
p.meta{margin:0 0 14px;font-size:17px}
p.asked{font-size:14px;color:var(--pencil);margin:0 0 8px}
p.for{margin:14px 0 10px}p.for .ink{font-family:var(--serif);color:var(--ink)}
.ink,.person,div.reflection p{font-family:var(--serif);color:var(--ink)}
div.reflection p{font-size:22px;line-height:1.4}
div.reflection p.mute{font-family:var(--sans);font-size:14px;color:var(--pencil)}
.mono,div.t,svg.ribbon text,span.ev{font-family:var(--mono)}
div.card{background:var(--surface);border:1px solid var(--line);border-radius:20px;padding:28px 32px}
div.card p{margin:0 0 8px}div.card p:last-child{margin:0}
ul.rows{list-style:none;padding:0;margin:0}
ul.rows li{display:flex;gap:.9rem;padding:12px 0;border-bottom:1px solid var(--line-soft);font-size:15px}
ul.rows li:last-child{border-bottom:0}
ul.rows li.back{flex-wrap:wrap;column-gap:.4rem}
ul.rows div.t{flex:0 0 3.4rem;color:var(--pencil);font-size:14px;padding-top:3px}
ul.rows span.sub{display:block;color:var(--pencil);font-size:14px}
svg.ribbon{display:block;width:100%;max-width:36rem;height:auto;margin:8px 0 4px}
svg.ribbon text{font-size:12px;fill:var(--pencil)}
svg.ribbon text.lane{letter-spacing:.13em}
svg.ribbon line.hour{stroke:var(--line)}
svg.ribbon rect.plan.filled{fill:var(--plan)}
svg.ribbon rect.plan.hollow{fill:none;stroke:var(--plan);stroke-width:1.2;stroke-dasharray:3 2}
svg.ribbon rect.stay{fill:var(--stay)}svg.ribbon rect.move{fill:var(--move)}
svg.ribbon rect.aboard{fill:var(--aboard)}
svg.ribbon line.call{stroke:var(--call);stroke-width:1.5}
svg.ribbon line.task{stroke:var(--plan);stroke-width:2}
svg.ribbon line.now{stroke:var(--signal);stroke-width:1.5}
p.legend{font-size:14px;color:var(--pencil);margin:0 0 4px}
p.legend span{font-weight:500;color:var(--ink)}
p.legend span::before{content:"";display:inline-block;width:.7em;height:.7em;margin-right:.3em;
border-radius:2px;
background:var(--plan)}
p.legend .stay::before{background:var(--stay)}p.legend .move::before{background:var(--move)}
p.legend .aboard::before{background:var(--aboard)}p.legend .call::before{background:var(--call)}
p.nothing,p.quiet{color:var(--pencil);font-size:14px;margin:14px 0}
section.record{margin:0 0 8px;padding:4px 28px;background:var(--surface);border:1px solid var(--line);
border-radius:20px}
section.record>h2{margin-top:20px}
section.record details.fold{margin:0;padding:0;border-top:1px solid var(--line-soft)}
details.fold>summary{list-style:none;cursor:pointer;display:flex;flex-wrap:wrap;align-items:center;
column-gap:.6rem;min-height:56px;padding:6px 0;color:var(--ink)}
details.fold>summary::marker{content:""}
details.fold>summary::before{content:"\\25B8";font-size:11px;color:var(--pencil);display:inline-block;
transition:transform .15s}
details.fold[open]>summary::before{transform:rotate(90deg)}
details.fold>summary h2{display:inline;font-weight:400;font-size:22px;line-height:1.25;
font-family:var(--serif);
margin:0;letter-spacing:0;text-transform:none;color:var(--ink)}
details.fold>summary span.sum{color:var(--pencil);font-size:14px}
div.fold{padding:0 0 16px 20px;font-size:14px}
div.fold h3{margin:14px 0 6px}
div.fold ol.timeline>li,div.fold ul.unplaced>li{border-bottom:1px solid var(--line-soft);padding:6px 0}
section.record section.held details.held{margin:0;min-height:44px}
div.paper{margin:12px 0;padding:24px 32px;background:var(--tint);border:1px solid var(--line);
border-radius:20px;color:var(--pencil);font-size:17px;line-height:1.6;font-family:var(--serif)}
div.paper p{margin:0 0 14px}div.paper p.eyebrow{margin:0 0 12px}
div.paper p.segment{text-decoration:underline dotted var(--pencil-rule);text-underline-offset:.25em;
text-decoration-thickness:1px}
div.paper h2{display:none}
div.paper .sc{font-variant:normal;text-transform:none;letter-spacing:.04em;color:var(--ink)}
div.paper p.mute,div.paper .mute{color:var(--pencil)}
div.paper p.mute{font-size:14px;font-family:var(--sans)}
div.paper p.segment small,div.paper p.segment span.kind{display:inline-block;margin-right:.4rem}
div.paper p.segment.unsupported{font-style:italic}
div.paper span.id{font-size:14px;font-family:var(--mono);color:var(--pencil)}
div.paper span.kind,span.tag{min-width:0;font-size:13px;line-height:1.4;font-family:var(--mono);
border:1px solid var(--line);border-radius:999px;padding:0 6px;color:var(--pencil)}
li.decision{color:var(--pencil);font-family:var(--serif);background:var(--tint);
text-decoration:underline dotted var(--pencil-rule);text-underline-offset:.25em}
p.proposal{color:var(--pencil);font-family:var(--serif);font-size:17px;background:var(--tint);border-radius:14px;
padding:10px 16px;margin:12px 0;text-decoration:underline dotted var(--pencil-rule);
text-underline-offset:.25em}
p.proposal .sc{font-variant:normal;letter-spacing:.12em;text-transform:uppercase;font-family:var(--mono);
font-size:13px;text-decoration:none}
li.decision small{font-size:13px;font-family:var(--mono);color:var(--pencil)}
blockquote.ink{margin:6px 0 0;font-style:italic;font-size:19px}
ul.gallery{list-style:none;display:flex;flex-wrap:wrap;gap:.5rem;padding:0;margin:.5rem 0}
ul.gallery img{display:block;width:8rem;max-width:100%;height:auto;border-radius:12px}
ul.gallery li.starred{outline:2px solid var(--star);border-radius:12px}
section.review button[value=pass]{background:transparent;color:var(--ink);border-color:var(--line)}
p.foot{color:var(--pencil);font-size:14px;margin:30px 0 10px}
@media (max-width:40rem){div.fold{padding-left:12px}ul.rows div.t{flex-basis:2.8rem}
section.record{padding:2px 20px}div.card{padding:20px}div.paper{padding:20px}}
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
    """`Saturday · evening · 21:40` on today; any other day its weekday alone, since a day read weeks
    later is in no morning or evening (the stranger test); a signed day `Saturday · signed 21:52`, with
    the date when it was signed on a later one."""
    if shape == SIGNED and signed is not None:
        local = str(signed["at_local"])
        when = local[11:16] if local[:10] == day else f"{local[:10]} {local[11:16]}"
        return f"{weekday}{DOT}signed {when}"
    if now is None:
        return weekday
    return DOT.join([weekday, shape, now.strftime("%H:%M")])


def meta_line(
    data: Mapping[str, Any], company: Sequence[Mapping[str, Any]], person: Callable[[Mapping[str, Any]], str]
) -> str:
    """The header's one line: where the night after was spent, the weather when the record has it,
    and who was there, as the `with` row says them."""
    night = data["nights"]["after"]
    if night["in_transit"]:  # `in transit` only with a move or a flight across the night (`day.night_moving`)
        said = day_reader.night_said(data, "after")
        where = said if said == "in transit" else f"night {said}"
    else:
        where = str(night["where"] or "unknown")
    parts = [escape(where)]
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


def intention_html(text: str, sunday: str, link: Callable[[str, str], str], withheld: bool = False) -> str:
    """The week's intention, kept on the Sunday before (RFC 0043 §8), under For: the owner's words, in
    ink, and the Sunday it was kept on, linked to that Day; when it would set a number beside a
    person's name, the sentence that says it is withheld instead."""
    when = date.fromisoformat(sunday)
    on = link(f"Sunday {when.day} {MONTHS[when.month - 1]}", f"/day/{sunday}")
    said = (
        f'<span class="mute">{escape(INTENTION_WITHHELD)}</span>'
        if withheld
        else f'<span class="ink">{escape(text)}</span>'
    )
    return (
        f'<p class="for intention"><span class="eyebrow-inline mute">This week</span> {said}'
        f'<span class="mute">{DOT}kept on {on}</span></p>\n'
    )


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
    ticks: Sequence[tuple[datetime, str]] = (),
) -> str:
    """The day in two lanes from its start to its end, inline: PLANNED, the calendar's timed entries
    (filled when something lived is beside one, hollow and dashed when nothing is) and the task
    tool's tasks dated today with a time, as ticks (`ticks`, RFC 0043 §4.2); LIVED, the stays,
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

    def between(a: datetime, b: datetime) -> str:
        """`from 19:30 to 21:00`, `from 19:30` for a moment: after the title and a word, so a clock
        touches no name at either end of it (the desk, 29 October)."""
        return f"from {hm(a)}" if b <= a else f"from {hm(a)} to {hm(b)}"

    plan = [p for p in planned(data, lines) if p.end > start and p.start < end]
    out: list[str] = [f'<text class="lane" x="0" y="{PLAN_Y - 3}">PLANNED</text>']
    for p in plan:
        a, b = x(p.start), x(p.end)
        cls = "plan filled" if p.beside else "plan hollow"
        out.append(
            f'<rect class="{cls}" x="{a}" y="{PLAN_Y}" width="{max(b - a, 2.0):.1f}" height="{LANE}" rx="2">'
            f"<title>{escape(p.title)}, {between(p.start, p.end)}</title></rect>"
        )
    tasks = sorted((t, title) for t, title in ticks if start <= t < end)
    for t, title in tasks:
        out.append(
            f'<line class="task" x1="{x(t)}" y1="{PLAN_Y - 2}" x2="{x(t)}" y2="{PLAN_Y + LANE + 2}">'
            f"<title>{escape(title)}, at {hm(t)}</title></line>"
        )
    if not plan and not tasks:
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
        when = between(_instant(within["start"]), _instant(within["end"]))
        out.append(
            f'<rect class="{kind}" x="{a}" y="{LIVED_Y}" width="{max(b - a, 1.5):.1f}" height="{LANE}">'
            f"<title>{escape(what)}, {when}</title></rect>"
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
    # the entry first, then its time after a word: a clock never touches a name the title holds
    entries = [f"{p.title}, from {hm(p.start)}{'' if p.beside else ', nothing beside it'}" for p in plan]
    entries += [f"{title}, a task at {hm(t)}" for t, title in tasks]
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
    legend says it), and what was lived, counted, or why nothing was. The entries planned are one text
    read aloud: `; then ` between them, so one's clock never touches the name the next one opens with."""
    planned_said = f"Planned: {'; then '.join(plan) if plan else NO_PLAN}."
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
            f'<li class="plan"><div class="t">{p.start.astimezone(zone).strftime("%H:%M")}</div>'
            f'<span>{escape(p.title)}<span class="sub">{where}from the calendar</span></span></li>\n'
        )
    for promise in due:
        rows.append(
            f'<li class="due"><div class="t">due</div><span>“{escape(promise.match.quote)}”'
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
    owed: Sequence[Mapping[str, Any]] = (),
    revisit: Sequence[Mapping[str, Any]] = (),
    link: Callable[[str, str], str] | None = None,
) -> tuple[str, str]:
    """(summary, body) of Loose ends; ("", "") when the day has none. Read-only: no form. `owed` the
    replies the day owes (`replies_owed`), `revisit` its decisions to revisit (`revisits`)."""
    made, due = made_on(found, day), [p for p in due_on(found, day) if p.day != day]
    decided = decisions(data)
    if not made and not due and not decided and not owed and not revisit:
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
            (len(owed), "replies", " owed"),
            (len(decided), "decisions", ""),
            (len(revisit), "", "to revisit"),
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
                f'<li class="promise"><div class="t">{_local(p.at, zone)}</div><span>'
                f"“{escape(p.match.quote)}”"
                f'<span class="sub">{promise_said(p, day, person)}{due_said}</span></span></li>\n'
            )
        body.append("</ul>\n")

    rows("Made on the day", made)
    rows("Due on the day", due)
    if owed:
        body.append('<h3>Replies owed</h3>\n<ul class="rows">\n')
        for o in owed:
            body.append(
                f'<li class="owed"><div class="t">reply</div><span>{wrote_said(o, day, person)}</span></li>\n'
            )
        body.append("</ul>\n")
    if revisit:
        body.append('<h3>To revisit</h3>\n<ul class="rows">\n')
        for r in revisit:
            body.append(_revisit_row(r, day, link))
        body.append("</ul>\n")
    if decided:
        body.append('<h3>Decisions</h3>\n<ul class="rows">\n')
        for block, segment in decided:
            mark = ""
            if segment.get("supported"):
                where = escape(str(segment.get("where") or "")) if segment.get("where") else ""
                mark = f' <small title="line {escape(str(block["transcript"]))}">[{where or "call"}]</small>'
            unsupported = "" if segment.get("supported") else ' <span class="tag">unsupported</span>'
            body.append(
                f'<li class="decision" title="Pencil: drafted by {escape(model_of(block))}">'
                '<div class="t">pencil</div>'
                f"<span>{escape(str(segment['text']))}"
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
    revisit: Sequence[Mapping[str, Any]] = (),
    day: str = "",
) -> tuple[str, str]:
    """(summary, body) of Looking back; ("", "") when the record has none of the years and no
    decision to revisit on the day (`revisits`), which come first."""
    if not found and not revisit:
        return "", ""
    rows = [_revisit_row(r, day, link) for r in revisit]
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
            (len(revisit), "decisions", " to revisit"),
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


# -- the morning's plan: the task tool, who you'll see, the week's proposal ------------------------------


def plan_of(lb: Logbook, day: str) -> plan_reader.Plan | str:
    """The task tool's plan for `day` as `show plan` reads it (tier-1 `sync notion` lines alone), or
    the sentence that says why the mapping cannot be read (`plan.PlanError`): never a page's error."""
    try:
        return plan_reader.read(lb, day)
    except plan_reader.PlanError as e:
        return str(e)


def task_ticks(found: object, zone: ZoneInfo) -> list[tuple[datetime, str]]:
    """The ribbon's ticks: each of today's tasks whose day carries a time, at that time; none for
    anything but a plan (its mapping's error, no reading, a reading that failed)."""
    if not isinstance(found, plan_reader.Plan) or not found.tasks:
        return []
    out = []
    for t in found.tasks["rows"]:
        at = _task_at(t, zone)
        if at is not None and not t.get("overdue"):
            out.append((at.astimezone(UTC), str(t.get("title") or plan_reader.UNTITLED)))
    return out


def _task_at(task: Mapping[str, Any], zone: ZoneInfo) -> datetime | None:
    """When a task is, when its day (`date`, the plan's: `Planned`, else `Due`) carries a time; a time
    with no zone is the record's."""
    when = str((task.get("date") or {}).get("start") or "")
    if len(when) <= 10:
        return None
    try:
        at = datetime.fromisoformat(when.replace("Z", "+00:00"))
    except ValueError:
        return None
    return at.replace(tzinfo=zone) if at.tzinfo is None else at


def tasks_html(found: object, zone: ZoneInfo, link: Callable[[str, str], str]) -> tuple[str, str]:
    """(summary, body) of Today's tasks from the task tool (RFC 0043 §9): the tasks of the day, five at
    most, each linked to its line and to its page in Notion, the rest one line; then the next trip as
    one countdown in words. ("", "") when the plan holds neither; the mapping's error as its body."""
    if isinstance(found, str):
        return "the plan", f'<p class="mute">{escape(found)}</p>\n'
    if not isinstance(found, plan_reader.Plan) or not found.mapped:
        return "", ""  # anything else is no plan: a reading beside the page that failed holds `()`
    tasks = found.tasks or {"rows": [], "more": 0}
    rows = []
    for t in tasks["rows"]:
        at = _task_at(t, zone)
        clock = "task" if at is None else at.astimezone(zone).strftime("%H:%M")
        said = [escape(str(t["status"]))] if t.get("status") else []
        if t.get("overdue"):
            said.append("carried from an earlier day")
        said.append(_notion(str(t["url"]), "open in Notion"))
        name = str(t.get("title") or plan_reader.UNTITLED)
        title = link(name, f"/line/{t['line']}") if t.get("line") else escape(name)
        rows.append(
            f'<li class="task"><div class="t">{clock}</div><span>{title}'
            f'<span class="sub">{DOT.join(said)}</span></span></li>\n'
        )
    if tasks.get("more"):
        sprint = found.sprint
        where = plan_reader._in_sprint(tasks)
        notion = f" — {_notion(str(sprint['url']), 'open in Notion')}" if sprint else ""
        rows.append(
            f'<li class="task more"><div class="t"></div><span>and {tasks["more"]} more'
            f"{escape(where)}{notion}</span></li>\n"
        )
    if tasks.get("said"):
        rows.append(
            f'<li class="task said"><div class="t"></div>'
            f'<span class="mute">{escape(tasks["said"])}</span></li>\n'
        )
    trip = found.trip
    if trip is not None:
        title = str(trip.get("title") or plan_reader.UNTITLED)
        named = link(title, "/line/" + str(trip["line"])) if trip.get("line") else escape(title)
        rows.append(
            f'<li class="trip"><div class="t">trip</div><span>{named} — {in_words(int(trip["days"]))}'
            f'<span class="sub">{_notion(str(trip["url"]), "open in Notion")}</span></span></li>\n'
        )
    if not rows:
        return "", ""
    n = len(tasks["rows"]) + int(tasks.get("more") or 0)
    summary = _counts([(n, "tasks", "")])
    if trip is not None:
        summary = DOT.join(x for x in (summary, f"the next trip {in_words(int(trip['days']))}") if x)
    return summary, '<ul class="rows">\n' + "".join(rows) + "</ul>\n"


def _notion(url: str, text: str) -> str:
    """A link to a page in the task tool: followed only when the owner clicks it; nothing is fetched."""
    return f'<a class="notion" href="{escape(url)}" rel="noreferrer">{escape(text)}</a>'


def in_words(days: int) -> str:
    """A countdown in words, never a digit: `today`, `tomorrow`, `in three days`, `in a week`, `in five
    weeks`, `in two months`, `in over a year`."""
    if days <= 0:
        return "today"
    if days == 1:
        return "tomorrow"
    if days < WEEK:
        return f"in {WORDS[days]} days"
    weeks = round(days / WEEK)
    if days < 8 * WEEK:
        return "in a week" if weeks == 1 else f"in {WORDS[weeks]} weeks"
    months = round(days / 30.4)
    if months <= 12:
        return f"in {WORDS[months]} months"
    return "in over a year"


def seeing(
    plan: Sequence[Planned], lines: Mapping[str, Line], directory: people.Report, tiers: Sequence[int] | None
) -> list[dict[str, Any]]:
    """Who you'll see: the attendees of the day's timed calendar entries who did not decline, each
    once, by name and in the order the entries come, never the owner. A person the record resolves is
    named as it names them while the gate reads their resolution; else by the name the entry itself
    gives, which is of its line's tier; a bare address nobody named is nobody."""
    allowed = None if tiers is None else {int(t) for t in tiers}
    found: dict[str, dict[str, Any]] = {}
    for p in plan:
        payload = (lines.get(p.line) or {}).get("payload") or {}
        attendees = payload.get("attendees")
        for a in attendees if isinstance(attendees, list) else []:
            if not isinstance(a, dict) or a.get("response") == "declined":
                continue
            ref = _attendee_ref(a.get("ref"))
            if ref is None or ref in directory.owner.refs:
                continue
            if ref[0] == "email" and present.SYSTEM_ADDRESS.search(ref[1].strip().casefold()):
                continue
            who = directory.identities.get(ref)
            entity = who.entity if who is not None and who.type in present.PERSON_TYPES else None
            if entity is not None and entity in directory.owner.entities:
                continue
            known = directory.known.get(entity) if entity is not None else None
            if known is not None and (allowed is None or known.tier in allowed):
                found.setdefault(known.entity, {"name": known.name, "person": known.entity})
                continue
            given = a.get("name")
            if isinstance(given, str) and given.strip():
                found.setdefault(given.strip().casefold(), {"name": given.strip(), "person": None})
    return list(found.values())


def _attendee_ref(value: object) -> tuple[str, str] | None:
    if not isinstance(value, dict):
        return None
    kind, ref = value.get("kind"), value.get("value")
    return (kind, ref) if isinstance(kind, str) and isinstance(ref, str) and ref else None


def week_proposal(lb: Logbook, day: str, tiers: Sequence[int] | None) -> dict[str, Any] | None:
    """The week's one proposal (RFC 0043 §3.1): the `next_week` segment of the standing draft of the
    week before the day's (written on its Sunday, so it proposes for the day's week), through the gate
    and the `dream` entry as every draft on the page (`drafts.for_unit`); None when it made none."""
    before = (date.fromisoformat(day) - timedelta(days=WEEK)).isoformat()
    week, monday, sunday = week_paper.parse_week(week_paper.week_of(before))
    with lb.index() as idx:
        retracted = frozenset(retractions(idx.retractions()))
        found = drafts.by_unit(idx.by_kind(drafts.KIND), retracted, drafts.UNIT_WEEK).get(week, [])
        if not found:
            return None
        on_week = {
            str(line["id"])
            for d in day_range(monday, sunday)
            for line in idx.day(d)
            if str(line["id"]) not in retracted
        }
        people = drafts.people_of(idx)
    draft, _withheld = drafts.for_unit(
        found, on_week, tiers, drafts.allowed(lb.root), drafts.NOT_ON_WEEK, people=people
    )
    if draft is None:
        return None
    for segment in draft["segments"]:
        if segment.get("part") == "next_week" and segment.get("text"):
            return {
                "text": str(segment["text"]),
                "supported": bool(segment.get("supported")),
                "model": str(draft.get("model") or ""),
                "line": str(draft["line"]),
                "week": week,
                "sunday": sunday,
            }
    return None


def proposal_html(found: Mapping[str, Any], link: Callable[[str, str], str]) -> str:
    """The week's one proposal, one line in pencil under Today, headed by the model that wrote it."""
    unsupported = "" if found["supported"] else ' <span class="tag">unsupported</span>'
    return (
        f'<p class="proposal" title="Pencil: drafted by {escape(str(found["model"]))}">'
        f'<span class="sc">{escape(str(found["model"]))}</span> '
        f"{escape(str(found['text']))}{unsupported} "
        f'<span class="mute">{link(f"the week{RSQUO}s draft", "/line/" + str(found["line"]))}</span></p>\n'
    )


# -- one reconnect (RFC 0043 §4.9) ------------------------------------------------------------------------


@dataclass(frozen=True)
class Drifted:
    """A person the drift reader names: who, the tier of what names them, their best year together
    and the last real contact (`people_drift.verdict`). Never a count."""

    name: str
    person: str
    tier: int
    year: str
    contact: people_drift.Contact | None


def drifted(lb: Logbook, day: str, airports: Airports | None = None) -> tuple[Drifted, ...]:
    """The people the drift rule names (`people_drift`, its defaults) with a silence counted to `day`,
    in the order of their ids so a day's pick is stable; the open promises the CLI adds are not read.
    It reads the whole record (`people.read_whole`, kept beside the index, and `real_contacts`, kept
    too): the page reads it once a day, off the request."""
    whole = reading.record_days(lb)
    if whole is None:
        return ()
    report = people.read_whole(lb, airports)
    if report is None:
        return ()
    until = min(whole[1], day)
    contacts = people_drift.real_contacts(lb, report)
    found = []
    for p in report.people:
        v = people_drift.verdict(p, contacts.get(p.entity), until)
        if v.drifted and v.year is not None:
            found.append(Drifted(p.name, p.entity, p.tier, v.year, v.contact))
    return tuple(sorted(found, key=lambda d: d.person))


def reads_up_to(tier: int, tiers: Sequence[int] | None) -> bool:
    """Whether a gate reads every tier from 1 up to `tier`: a person whose evidence reaches tier 3 is
    shown through (1, 2, 3), never through (1, 3), where what put them at 3 may rest on a tier-2 line."""
    return tiers is None or all(t in {int(x) for x in tiers} for t in range(1, int(tier) + 1))


def reconnect(found: Sequence[Drifted], day: str, tiers: Sequence[int] | None) -> Drifted | None:
    """One person to reconnect with this morning, stateless: the one the day's ordinal picks among
    those the gate reads, skipping the one the day before would pick, so never the same person two
    mornings running; with only one, every other morning."""
    shown = [d for d in found if reads_up_to(d.tier, tiers)]
    n = date.fromisoformat(day).toordinal()
    if not shown or (len(shown) == 1 and n % 2):
        return None
    pick = shown[n % len(shown)]
    return pick if len(shown) == 1 or pick != shown[(n - 1) % len(shown)] else None


def reconnect_said(d: Drifted, day: str, person: Callable[[Mapping[str, Any]], str]) -> str:
    """`Per Hansen: you saw each other often the year before last; the last real contact was a call in
    the spring that year.`: the reason in words, never a digit, the years said in words."""
    often = f"you saw each other often {_year_words(int(d.year), day)}"
    if d.contact is None:
        last = "there has been no real contact since"
    else:
        then = date.fromisoformat(d.contact.day)
        when = "that year" if str(then.year) == d.year else _year_words(then.year, day)
        last = (
            f"the last real contact was {VIA.get(d.contact.via, 'a word')} in the "
            f"{SEASONS[then.month - 1]}{' ' if when == 'that year' else ', '}{when}"
        )
    return f"{person({'name': d.name, 'person': d.person})}: {often}; {last}."


def _year_words(year: int, day: str) -> str:
    gap = date.fromisoformat(day).year - year
    if gap <= 0:
        return "this year"
    if gap == 1:
        return "last year"
    if gap == 2:
        return "the year before last"
    return "a few years ago" if gap < 7 else "many years ago"


# -- replies owed and decisions to revisit (RFC 0043 §4.5, §4.8) ------------------------------------------


def replies_owed(
    lb: Logbook, day: str, directory: people.Report, tiers: Sequence[int] | None
) -> list[dict[str, Any]]:
    """The replies the day owes (`peoples_mail.replies_owed`, through the gate): who, and when their
    last word came, longest owed first."""
    days = day_start.of(lb.meta)
    out = []
    for o in peoples_mail.replies_owed(lb, day, tiers):
        known = directory.known.get(o.person)
        if known is None or not reads_up_to(known.tier, tiers):
            continue  # named only when the gate reads every tier up to the person's
        out.append({"name": known.name, "person": known.entity, "day": days.day_of(o.last_at)})
    return out


def wrote_said(owed: Mapping[str, Any], day: str, person: Callable[[Mapping[str, Any]], str]) -> str:
    """`Kari Nordmann wrote on Tuesday last week`: a name and weekday words, never a date or a count."""
    then, on = date.fromisoformat(str(owed["day"])), date.fromisoformat(day)
    weekday = day_reader.WEEKDAYS[then.weekday()]
    gap = (on - then).days
    if gap < WEEK:
        when = f"on {weekday}"
    elif then.isocalendar()[:2] == (on - timedelta(days=WEEK)).isocalendar()[:2]:
        when = f"on {weekday} last week"
    elif (then.year, then.month) == (on.year, on.month):
        when = f"on a {weekday} earlier this month"
    else:
        when = f"on a {weekday} in {MONTHS[then.month - 1]}"
    return f"{person(owed)} wrote {when}"


def revisits(lb: Logbook, day: str, tiers: Sequence[int] | None) -> list[dict[str, Any]]:
    """The decisions to revisit on `day` (RFC 0043 §4.8): the standing `note/v1` lines labelled
    `decision` whose `extra.revisit` is the day, a local day `YYYY-MM-DD`, through the gate; each with
    its words and the local day it was written, the oldest first."""
    days = day_start.of(lb.meta)
    with lb.index() as idx:
        lines = reading.crossing(idx.by_kind(notes.KIND, None, day), tiers)
        retracted = retractions(idx.retractions())
    out = []
    for line in notes.standing(lines, DECISION, retracted):
        payload = line.get("payload") or {}
        extra = payload.get("extra")
        if not isinstance(extra, dict) or extra.get(REVISIT) != day:
            continue
        out.append(
            {"line": str(line["id"]), "text": str(payload.get("text") or ""), "day": days.day_of(line["at"])}
        )
    return out


def _revisit_row(found: Mapping[str, Any], day: str, link: Callable[[str, str], str] | None) -> str:
    said = escape(revisit_said(found, day))
    line = f'<span class="sub">{link("the decision", "/line/" + str(found["line"]))}</span>' if link else ""
    return f'<li class="revisit"><div class="t">revisit</div><span>{said}{line}</span></li>\n'


def revisit_said(found: Mapping[str, Any], day: str) -> str:
    """`A year ago you decided: “Keep the berth in Vollen.” How did it turn out?`"""
    return f"{_ago(str(found['day']), day)} you decided: “{found['text']}” How did it turn out?"


def _ago(then: str, day: str) -> str:
    a, b = date.fromisoformat(then), date.fromisoformat(day)
    months = (b.year - a.year) * 12 + b.month - a.month - (1 if b.day < a.day else 0)
    if months >= 12:
        years = months // 12
        return (
            "A year ago"
            if years == 1
            else f"{WORDS[years].capitalize()} years ago"
            if years <= 12
            else "Years ago"
        )
    if months >= 1:
        return "A month ago" if months == 1 else f"{WORDS[months].capitalize()} months ago"
    gap = (b - a).days
    if gap >= 2 * WEEK:
        return "A few weeks ago"
    if gap >= WEEK:
        return "A week ago"
    return "Today" if gap == 0 else "Yesterday" if gap == 1 else "A few days ago"


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
