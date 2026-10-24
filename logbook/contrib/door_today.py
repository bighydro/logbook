"""Today, the front door of the Library (RFC 0047 §4.1): the Day page's morning (RFC 0043 §3.1, §4)
promoted to `/`. `/day/DATE` stays the page of any one day; Today is always today's, in the record's
zone and from its `day_start`.

From the top, each part read from a reader the Day page already has, through the page's gate
(`Site.tiers`) and kept as the Day keeps it (`Site._day_reading`, `Site._day_later`, `Site.shared`), so
Today and today's Day read the record once between them:

1. **The day**: the place of the night and the time, the date in words, the weather in one phrase
   when the record holds it, and whether the day is signed.
2. **The photo of the day**: a photo of the day the owner starred (a `memory` keeper: the Day's hero
   and the Volume's pick), when this machine holds its pixels; else nothing.
3. **A year ago today** (`year_ago`): the same date a year back, when it holds something worth showing
   (its signed reflection's first sentence, else where the owner was and with whom, else a journey's
   name); else the same date in the nearest earlier year that holds a signed reflection, a starred
   photo or a journey; else no card (RFC 0047 §14 q2, until the owner answers it).
4. **What you owe**: the owner's open promises and what was asked of them (the Promises shelf,
   `shelf_promises.read`), today's tasks from the plan (`day_rhythm.plan_of`, read and never run) and
   the replies owed (`day_rhythm.replies_owed`): `MOST` rows, the oldest first, each linked to its
   moment, and the rest counted.
5. **Owed to you**: the open promises made to the owner (`owed_to_you`, the promises reader's third
   way), the same rows.
6. **Your day, in your words**: the reflection standing on the day, in ink; the evening's three
   questions answered from the record; and the Day's two acts, Reflect and Sign, the same forms
   posting to the same routes (`/day/DATE/reflect`, `/day/DATE/sign`): no write path of their own.
7. **The aside**: the week's signed days, the next `AHEAD` days' calendar entries with whom, the week's
   proposal (a model's, in pencil), the legend of ink and pencil, and one line on where it all is.

A person's name is never beside a number, in the text, a title or a label: dates lead with their
weekday and counts sit beside no name. Nothing here is written, no model is asked and no connection is
opened; a static page (`href`) carries no form and reads nothing beside the day."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html import escape
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from ..core import day as day_reader
from ..core import day_start, keepers, notes, people, reading, signing, stars, weather
from ..core.chain import Line
from ..core.store import retractions
from . import day_rhythm, entities, ideas, journeys, promises, reflect, shelf_promises
from . import plan as plan_reader

if TYPE_CHECKING:  # the Site passes itself; serve imports this module, never the other way at import
    from ..core.index import Index
    from .serve import Closing, DayMarks, Site

MOST = 7  # rows of a list of loose ends before the rest are counted
AHEAD = 4  # days of the calendar the aside looks ahead
CALENDAR = "event"
MARKED = (notes.KIND, stars.KIND, keepers.KIND)  # what a year's memory is chosen by, besides its signature
DOT = " · "
WEEKDAYS = day_reader.WEEKDAYS
SHORT_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = day_rhythm.MONTHS
WORDS = day_rhythm.WORDS
LEGEND = "Ink is what you confirmed. Pencil is what a model drafted, or what the record doesn't know yet."
HERE = "On this machine. Nothing leaves until you sign."
OWED_EMPTY = "When someone promises you something, it waits here."
OWE_EMPTY = "Nothing open. When you promise something in a message, a call or a note, it waits here."
RULES = "Proposed by the promises reader's rules (logbook promises), not yet confirmed"
OWED_RULE = "Proposed by the replies-owed rule: their word was the last, more than a week ago"
KINDS = {
    "message": "in a message",
    "mail": "in a mail",
    "transcript": "in a conversation",
    "note": "in a note",
}
CHECK = (
    '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8"'
    ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'
    '<path d="M3 8.5l3.2 3L13 4.5"/></svg>'
)

STYLE = """
body.today{background:var(--paper,#F4F1EA);color:var(--ink,#16181D)}
main.today{max-width:none;padding:28px 1.5rem 3rem;font:15px/1.5 var(--sans,system-ui,sans-serif);
color:var(--ink,#16181D)}
main.today a{color:inherit}
main.today h1,main.today h2{font-family:var(--serif,Georgia,serif);font-weight:400;color:var(--ink,#16181D)}
.today-grid{display:grid;grid-template-columns:minmax(0,1fr);gap:28px}
.today-main{display:flex;flex-direction:column;gap:28px;min-width:0}
.mono-label{font:12px/1.4 var(--mono,ui-monospace,monospace);font-weight:500;letter-spacing:.13em;
text-transform:uppercase;color:var(--pencil,#62666D);margin:0 0 8px}
.muted{color:var(--pencil,#62666D)}
.pencil{color:var(--pencil,#62666D);text-decoration:underline dotted var(--pencil-rule,#8C8F95);
text-decoration-thickness:1px;text-underline-offset:3px}
.card{background:var(--surface,#FBFAF6);border:1px solid var(--line,#E3DED3);border-radius:20px;padding:32px}
section.the-day h1{font-size:72px;line-height:1.02;margin:.1rem 0 .4rem}
section.the-day p{margin:0}
p.weather{font-size:15px;margin:0 0 .5rem}
p.state{display:flex;align-items:center;gap:.4rem;font-size:15px}
p.state.signed{color:var(--ink,#16181D)}
p.state a{display:inline-flex;align-items:center;min-height:44px;color:var(--ink,#16181D)}
p.empty-record{margin:.8rem 0 0}
figure.photo{margin:0}
figure.photo img{display:block;width:100%;height:auto;max-height:34rem;object-fit:cover;border-radius:20px;
border:0}
section.year-ago{background:var(--card-dark,#16181D);color:var(--card-dark-text,#F4F1EA);border-radius:20px;
padding:32px}
section.year-ago .mono-label,section.year-ago p.where{color:var(--card-dark-muted,#C9C4B8)}
section.year-ago p.said{font:30px/1.2 var(--serif,Georgia,serif);font-weight:400;margin:0 0 .7rem}
section.year-ago p.where{font-size:13px;margin:0 0 1.1rem}
a.pill,button.pill,section.acts button{display:inline-flex;align-items:center;justify-content:center;
min-height:44px;padding:0 1.3rem;border-radius:23px;
font:15px var(--sans,system-ui,sans-serif);font-weight:500;
text-decoration:none;cursor:pointer;box-sizing:border-box;border:1px solid var(--ink,#16181D);
background:transparent;color:var(--ink,#16181D);margin:0}
section.acts button.primary,section.acts form.sign button{background:var(--ink,#16181D);
color:var(--paper,#F4F1EA)}
section.year-ago a.pill{border-color:var(--card-dark-text,#F4F1EA);color:var(--card-dark-text,#F4F1EA)}
section.acts button[disabled]{opacity:.45;cursor:default}
section.owe h2,section.owed h2{font-size:36px;line-height:1.1;margin:0 0 .3rem}
p.count{font-size:13px;margin:0 0 1rem}
ol.loose{list-style:none;margin:0;padding:0}
ol.loose li{border-top:1px solid var(--line-soft,#ECE7DD)}
ol.loose li:first-child{border-top:0}
ol.loose a.row{display:grid;grid-template-columns:22px minmax(0,1fr) auto;gap:14px;align-items:start;
padding:14px 0;text-decoration:none;color:inherit;min-height:44px}
ol.loose a.row:hover .what{text-decoration:underline;text-decoration-thickness:1px}
span.circle{width:18px;height:18px;border:1.5px solid var(--pencil-rule,#8C8F95);border-radius:50%;
margin-top:5px;box-sizing:border-box}
span.what{display:block;font:22px/1.25 var(--serif,Georgia,serif);font-weight:400;color:var(--ink,#16181D);
overflow-wrap:anywhere}
span.prov{display:block;font-size:13px;margin-top:3px;color:var(--pencil,#62666D);overflow-wrap:anywhere}
span.due{font:12px/1 var(--mono,ui-monospace,monospace);font-weight:500;letter-spacing:.06em;
text-transform:uppercase;
padding:6px 10px;border-radius:12px;border:1px solid var(--line,#E3DED3);color:var(--pencil,#62666D);
white-space:nowrap;margin-top:4px}
span.due.today{color:var(--signal,#C8401A);border-color:var(--signal,#C8401A)}
p.more{font-size:13px;margin:.6rem 0 0}
section.words .ink{font:24px/1.35 var(--serif,Georgia,serif);font-weight:400;color:var(--ink,#16181D);
margin:0 0 .6rem}
dl.questions{margin:1.2rem 0 1.4rem;display:grid;grid-template-columns:max-content minmax(0,1fr);
gap:.35rem 1rem;color:var(--pencil,#62666D);font-size:15px}
dl.questions dt{margin:0}dl.questions dd{margin:0;overflow-wrap:anywhere}
section.acts{display:flex;flex-direction:column;gap:14px;align-items:stretch}
section.acts form{margin:0;display:flex;flex-direction:column;gap:10px;min-width:0}
section.acts textarea{width:100%;box-sizing:border-box;min-height:6.5rem;
font:15px/1.5 var(--sans,system-ui,sans-serif);padding:.7rem .9rem;border-radius:14px;
border:1px solid var(--line,#E3DED3);background:var(--paper,#F4F1EA);
color:var(--ink,#16181D)}
section.acts form.sign p.mute,section.acts form.sign details,section.acts form.sign ol{font-size:13px;
color:var(--pencil,#62666D);margin:0}
section.acts form.sign ol.proposals li{padding:.3rem 0}
section.acts form button{align-self:flex-start}
p.sign-later{font-size:13px;margin:0}
aside.today-aside{display:flex;flex-direction:column;gap:22px;min-width:0}
aside.today-aside .card{padding:28px}
ol.week{list-style:none;display:flex;gap:8px;margin:0 0 .8rem;padding:0}
ol.week a,ol.week span.day{display:flex;flex-direction:column;align-items:center;gap:6px;min-width:32px;
min-height:44px;text-decoration:none;color:var(--pencil,#62666D);
font:12px var(--mono,ui-monospace,monospace);font-weight:500}
ol.week i{display:block;width:22px;height:22px;border-radius:50%;
border:1.5px solid var(--pencil-rule,#8C8F95);box-sizing:border-box}
ol.week .signed i{background:var(--ink,#16181D);border-color:var(--ink,#16181D)}
ol.week .today{color:var(--ink,#16181D)}
ul.ahead{list-style:none;margin:0;padding:0}
ul.ahead li{display:grid;grid-template-columns:4.2rem minmax(0,1fr);gap:10px;padding:8px 0;
border-top:1px solid var(--line-soft,#ECE7DD)}
ul.ahead li:first-child{border-top:0}
ul.ahead .mono-label{margin:3px 0 0}
ul.ahead span.what{font-size:18px}
aside p{margin:0}
p.legend,p.here{font-size:13px}
@media (min-width:64rem){
.today-grid{grid-template-columns:minmax(0,1fr) 22rem;gap:40px;align-items:start}
}
@media (max-width:40rem){
main.today{padding:18px 16px 2rem}
section.the-day h1{font-size:40px}
.card,section.year-ago,aside.today-aside .card{padding:20px;border-radius:18px}
section.year-ago p.said{font-size:24px}
section.owe h2,section.owed h2{font-size:30px}
span.what{font-size:20px}
dl.questions{grid-template-columns:minmax(0,1fr);gap:0}
dl.questions dd{color:var(--ink,#16181D);margin:0 0 .6rem}
}
"""


@dataclass(frozen=True)
class Loose:
    """One row of What you owe or Owed to you: when it arose (the order), what, where it came from,
    when it is due, the moment it opens, and the rule that proposed it (pencil) when one did."""

    at: str
    what: str  # already escaped
    said: str  # already escaped, may hold a person's link
    due: str | None  # the chip's words (`due_words`)
    href: str
    rule: str | None = None
    made_today: bool = False  # one of the owner's own promises, said today


@dataclass(frozen=True)
class Morning:
    """What Today reads of the record beside the readers it shares with the Day, once for the record as
    it stands (`Site._day_reading`): the day as Looking back reads one (its nights, weather and company,
    who the owner said was there, its reflection), when it was signed, the week's signed days, the memory
    of a year ago and the days ahead."""

    total: int
    data: dict[str, Any]
    marks: DayMarks  # the Day's marks of the day: its stars, photos and lines standing (`Site._day_marks`)
    signed_at: str | None  # `22:56`, or `2026-06-21 08:02` when signed on a later day
    signed_week: frozenset[str]
    year_ago: dict[str, Any] | None
    ahead: list[dict[str, Any]]


def read_today(site: Site, day: str) -> Morning:
    """Today's reading, through the gate: a count on the index, the day's lines, the signatures, one
    reading of the night before and the day (`reading.read`, the stays and company alone), and the
    year ago and the days ahead."""
    lb, tiers = site.lb, site.tiers
    tz = ZoneInfo(str(lb.meta["timezone"]))
    owner = str(lb.meta.get("owner_id") or "") or None
    with lb.index() as idx:
        total = idx.totals()[0]
        retracted = retractions(idx.retractions())
        standing = {
            d: line for d, line in signing.standing(idx, owner).items() if reading.crossing([line], tiers)
        }
    marks = site._day_marks(day)  # the day's lines standing, through the gate
    if not total:
        empty = {"tz": str(tz), "nights": {"before": {}}, "stated": []}
        return Morning(0, empty, marks, None, frozenset(), None, [])
    on_day = list(marks.lines.values())
    before = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    rd = reading.read(lb, before, day, site.airports, tiers)
    data = day_reader.of_reading(rd, day, None)
    data["stated"] = day_reader.stated_of(on_day, retracted)
    reflected = notes.standing(on_day, notes.REFLECTION, retracted)
    if reflected:
        data["reflection"] = day_reader.reflection_json(reflected[-1], str(tz))
    signed_at = None
    if day in standing:
        at = day_rhythm._instant(str(standing[day]["at"])).astimezone(tz)
        signed_at = at.strftime("%H:%M") if at.date().isoformat() == day else at.strftime("%Y-%m-%d %H:%M")
    d = date.fromisoformat(day)
    monday = d - timedelta(days=d.weekday())
    week = frozenset(x for k in range(7) if (x := (monday + timedelta(days=k)).isoformat()) in standing)
    return Morning(
        total, data, marks, signed_at, week, year_ago(site, day, frozenset(standing)), coming_up(site, day)
    )


def page_today(site: Site) -> str:
    """`/`: Today, for the day the owner is in now (`day_start`)."""
    bounds = day_start.of(site.lb.meta)
    now = site.now()
    day = bounds.today(now).isoformat()
    morning = site._day_reading(("today", day), lambda: read_today(site, day))
    data = morning.data
    tz = ZoneInfo(data["tz"])
    local = now.astimezone(tz)
    empty = not morning.total

    def person(c: Mapping[str, Any]) -> str:
        name = escape(str(c.get("name") or ""))
        href = site.href(f"/people/{c['person']}") if c.get("person") else None
        return name if href is None else f'<a class="person" href="{escape(href)}">{name}</a>'

    def named(c: Mapping[str, Any]) -> str:  # inside a row, itself a link to its moment: a name, no link
        return escape(str(c.get("name") or ""))

    main: list[str] = [_the_day(site, day, morning, local)]
    if not empty:
        main.append(_photo(site, morning.marks))
        main.append(_year_ago_html(site, morning.year_ago))
        mine = _you_owe(site, day, tz, named)
        main.append(_section("owe", "What you owe", mine, OWE_EMPTY, site.href("/promises")))
        theirs = _owed_to_you(site, day, named)
        main.append(_section("owed", "Owed to you", theirs, OWED_EMPTY, None))
        main.append(_words(site, day, data, person, mine))
    body = (
        '<div class="today-grid"><div class="today-main">'
        + "".join(p for p in main if p)
        + "</div>"
        + _aside(site, day, morning, person)
        + "</div>\n"
    )
    site._day_later_start()  # what the page asked to read beside it, once it is rendered
    return site.document("Today", body, style=STYLE, main="today")


# -- 1. the day ------------------------------------------------------------------------------------------


def date_words(day: str) -> str:
    """`Saturday, 24 October`: the weekday and the date, in words."""
    d = date.fromisoformat(day)
    return f"{WEEKDAYS[d.weekday()]}, {d.day} {MONTHS[d.month - 1]}"


def _the_day(site: Site, day: str, morning: Morning, local: datetime) -> str:
    data, empty = morning.data, not morning.total
    night = data["nights"]["before"]
    where = "in transit" if night.get("in_transit") else (night.get("where") or "")
    label = DOT.join(x for x in (str(where).upper(), local.strftime("%H:%M")) if x)
    parts = [
        '<section class="the-day">\n',
        f'<p class="mono-label">{escape(label)}</p>\n',
        f"<h1>{escape(date_words(day))}</h1>\n",
    ]
    if data.get("weather"):
        short = weather.short_text(data["weather"])
        if short:
            parts.append(f'<p class="weather muted">{escape(short)}</p>\n')
    if morning.signed_at is not None:
        signed = f"<span>Signed at {escape(morning.signed_at)}</span>"
        parts.append(f'<p class="state signed">{CHECK}{signed}</p>\n')
    elif not empty:
        act = "Sign it" if data.get("reflection") else "Reflect, then sign"  # Sign signs with your words
        sign = "" if site.static else f' <a href="/#acts">{act}</a>'
        parts.append(f'<p class="state muted">Not signed yet.{sign}</p>\n')
    if empty:
        parts.append(
            '<p class="empty-record muted">The record has no lines yet. Today fills from what your'
            " sources send: where you were, who you were with, what you promised.</p>\n"
        )
    parts.append("</section>\n")
    return "".join(parts)


# -- 2. the photo of the day -----------------------------------------------------------------------------


def _photo(site: Site, marks: DayMarks) -> str:
    """The first photo of the day the owner starred whose pixels this machine holds; nothing else."""
    for line_id in marks.photos:
        if line_id in marks.starred:
            img = site._thumbnail(line_id, marks)
            if img:
                return f'<figure class="photo">{img}</figure>\n'
    return ""


# -- 3. a year ago today ---------------------------------------------------------------------------------


def same_date(day: str, years: int) -> str:
    """The same date `years` before `day`; 29 February is the 28th in a year that has none."""
    d = date.fromisoformat(day)
    leap = d.year - years
    dom = 28 if (d.month, d.day) == (2, 29) and not day_rhythm._leap(leap) else d.day
    return date(leap, d.month, dom).isoformat()


def year_ago(site: Site, day: str, signed: frozenset[str]) -> dict[str, Any] | None:
    """The memory of Today (RFC 0047 §14 q2, the rule until the owner answers it): the same date a year
    back when it holds something worth showing (its signed reflection, else where the owner was and with
    whom, else a journey), else the same date in the nearest earlier year that holds a signed reflection,
    a starred photo or a journey; None when no year does. Through the gate: a count on the index for each
    year, the lines of a year with any, and one reading of the day chosen."""
    lb, tiers = site.lb, site.tiers
    with lb.index() as idx:
        _total, earliest, _latest = idx.totals()
    if earliest is None:
        return None
    first = day_start.of(lb.meta).day_of(earliest)  # the record's first line, tracked or not
    with lb.index() as idx:
        retracted = retractions(idx.retractions())
        named = journeys.names_in(reading.crossing(idx.by_kind(notes.KIND), tiers), frozenset(retracted))
        years = 1
        while True:
            then = same_date(day, years)
            if then < first:
                return None
            if idx.source_days(then, then, tiers)[0]:
                on_day = _marked(idx, then, tiers)
                said = _reflected(on_day, retracted) if then in signed else None
                trip = _journey(named, then)
                starred = _starred_photo(on_day, retracted)
                if years == 1 or said or trip or starred:
                    break
            years += 1
    found = _the_day_then(site, then)
    sentence = said or found["sentence"] or (f"On {trip}." if trip else None)
    if sentence is None:
        if years == 1:  # nothing worth showing a year back: the nearest earlier year that holds something
            return _earlier(site, day, years + 1, first, signed, named, retracted)
        sentence = "A photo you starred." if starred else None
    if sentence is None:
        return None
    return {"years": years, "day": then, "sentence": sentence, "where": found["where"]}


def _earlier(
    site: Site,
    day: str,
    years: int,
    first: str,
    signed: frozenset[str],
    named: Sequence[Line],
    retracted: Mapping[str, Line],
) -> dict[str, Any] | None:
    lb, tiers = site.lb, site.tiers
    with lb.index() as idx:
        while True:
            then = same_date(day, years)
            if then < first:
                return None
            if idx.source_days(then, then, tiers)[0]:
                on_day = _marked(idx, then, tiers)
                said = _reflected(on_day, retracted) if then in signed else None
                trip = _journey(named, then)
                starred = _starred_photo(on_day, retracted)
                if said or trip or starred:
                    break
            years += 1
    found = _the_day_then(site, then)
    sentence = said or found["sentence"] or (f"On {trip}." if trip else "A photo you starred.")
    return {"years": years, "day": then, "sentence": sentence, "where": found["where"]}


def _reflected(on_day: Sequence[Line], retracted: Mapping[str, Line]) -> str | None:
    standing = notes.standing(on_day, notes.REFLECTION, retracted)
    if not standing:
        return None
    first = reflect.sentences(str((standing[-1].get("payload") or {}).get("text") or ""))
    return first[0] if first else None


def _marked(idx: Index, day: str, tiers: Sequence[int] | None) -> list[Line]:
    """The day's notes, stars and keepers through the gate: what a year's memory is chosen by, read by
    kind on the index and never the whole day."""
    return [line for kind in MARKED for line in reading.crossing(idx.by_kind(kind, day, day), tiers)]


def _starred_photo(on_day: Sequence[Line], retracted: Mapping[str, Line]) -> bool:
    """Whether a photo of the day is starred: a star on a photo, or a photo's `memory` keeper, standing,
    each at its photo's tier (the gate read it)."""
    marks = [line for line in on_day if line.get("kind") in (stars.KIND, keepers.KIND)]
    return any(s.kind == stars.PHOTO for s in stars.standing(marks, retracted).values())


def _journey(named: Sequence[Line], day: str) -> str | None:
    """The name of the journey `day` was on, from its name note (`trip:FIRST:LAST`), the latest first."""
    for line in reversed(named):
        trip = str(((line.get("payload") or {}).get("extra") or {}).get("trip") or "")
        parts = trip.split(":")
        if len(parts) == 3 and parts[1] <= day <= parts[2]:
            return " ".join(str((line.get("payload") or {}).get("text") or "").split()) or None
    return None


def _the_day_then(site: Site, then: str) -> dict[str, Any]:
    """Where the owner was on `then` and with whom, from one reading of the day, as Looking back reads
    a year (`day_rhythm.looking_back`): the sentence, and the place for the date line."""
    rd = reading.read(site.lb, then, then, site.airports, site.tiers)
    data = day_reader.of_reading(rd, then, None)
    night = data["nights"]["after"]
    where = None if night["in_transit"] else night["where"]
    names = [str(c["name"]) for c in day_reader.company_of_day(data) if c.get("name")]
    sentence = None
    if where and names:
        sentence = f"At {where}, with {_and(names)}."
    elif where:
        sentence = f"At {where}."
    elif names:
        sentence = f"With {_and(names)}."
    return {"sentence": sentence, "where": where}


def _year_ago_html(site: Site, found: Mapping[str, Any] | None) -> str:
    if found is None:
        return ""
    years = int(found["years"])
    label = "A year ago today" if years == 1 else f"{years} years ago today"
    then = date.fromisoformat(str(found["day"]))
    when = f"{WEEKDAYS[then.weekday()]} {then.day} {MONTHS[then.month - 1]} {then.year}"
    place = str(found["where"] or "")
    named = place and place in str(found["sentence"])  # the sentence names it already: the date alone
    where = when if named else DOT.join(x for x in (when, place) if x)
    link = site.href(f"/day/{found['day']}")
    pill = "" if link is None else f'<a class="pill" href="{escape(link)}">Open that day</a>'
    return (
        '<section class="year-ago">\n'
        f'<p class="mono-label">{escape(label)}</p>\n'
        f'<p class="said">{escape(str(found["sentence"]))}</p>\n'
        f'<p class="where">{escape(where)}</p>\n'
        f"{pill}</section>\n"
    )


# -- 4. and 5. what you owe, owed to you -----------------------------------------------------------------


def _when(at: str, day: str, tz: ZoneInfo, clock: bool = False) -> str:
    """`today`, `yesterday`, `on Thursday` within the week, else `on 3 June`; `at 13:28` with `clock`
    on today."""
    instant = day_rhythm._instant(at).astimezone(tz)
    then, on = instant.date(), date.fromisoformat(day)
    gap = (on - then).days
    if gap == 0:
        return f"today at {instant.strftime('%H:%M')}" if clock else "today"
    if gap == 1:
        return "yesterday"
    if 0 < gap < day_rhythm.WEEK:
        return f"on {WEEKDAYS[then.weekday()]}"
    year = "" if then.year == on.year else f" {then.year}"
    return f"on {then.day} {MONTHS[then.month - 1]}{year}"


def due_words(due: str, day: str) -> str:
    """The chip of a row with a day: `Today`, `Tomorrow`, else the weekday first (`Fri 30 Oct`), so no
    digit ever follows a name."""
    d, on = date.fromisoformat(due), date.fromisoformat(day)
    if d == on:
        return "Today"
    if d == on + timedelta(days=1):
        return "Tomorrow"
    year = "" if d.year == on.year else f" {d.year}"
    return f"{SHORT_DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1][:3]}{year}"


def near(site: Site, day: str) -> list[promises.Proposal]:
    """The open promises both ways as the Day's morning reads them (`day_rhythm.promises_near`: said in
    the `PROMISE_DAYS` before the day and on it, through the gate), the same reading as today's Day."""
    if site.static:
        return []
    found = site._day_reading(("promises", day), lambda: day_rhythm.promises_near(site.lb, day, site.tiers))
    return [p for p in found if p.status == "open"]


def _promise(
    p: promises.Proposal, day: str, tz: ZoneInfo, person: Callable[[Mapping[str, Any]], str]
) -> Loose:
    """A promise as a row: the words as said, then who and where and when, a name never beside a digit."""
    kind = KINDS.get(p.kind, f"in a {p.kind}")
    when = _when(p.at, day, tz, clock=p.kind == "transcript")
    who = shelf_promises._who(p)
    named = who not in ("?", shelf_promises.NOTE_WHO, "")
    if p.direction == promises.OWED_TO_OWNER:
        said = (
            f"{person({'name': who})} promised, {kind} {when}" if named else f"promised to you, {kind} {when}"
        )
    elif p.role == promises.ASKED:
        said = f"{person({'name': who})} asked, {kind} {when}" if named else f"asked of you, {kind} {when}"
    else:
        said = (
            f"you promised {person({'name': who})}, {kind} {when}"
            if named
            else f"you promised, {kind} {when}"
        )
    chip = due_words(p.due, day) if p.due else None
    own = p.direction == promises.OWED_BY_OWNER and p.role != promises.ASKED and p.day == day
    said = said[:1].upper() + said[1:]
    href = shelf_promises.day_line(p.day, p.line)
    return Loose(p.at, f"\u201c{escape(p.match.quote)}\u201d", said, chip, href, RULES, own)


def _you_owe(site: Site, day: str, tz: ZoneInfo, person: Callable[[Mapping[str, Any]], str]) -> list[Loose]:
    """The owner's open promises and what was asked of them, today's tasks, and the replies owed."""
    rows = [_promise(p, day, tz, person) for p in near(site, day) if p.direction == promises.OWED_BY_OWNER]
    plan = _plan(site, day)
    if isinstance(plan, plan_reader.Plan) and plan.mapped and plan.tasks:
        for t in plan.tasks["rows"]:
            name = str(t.get("title") or plan_reader.UNTITLED)
            start = str((t.get("date") or {}).get("start") or day)
            from_plan = ["From your plan"]
            if t.get("status"):
                from_plan.append(escape(str(t["status"])))
            if t.get("overdue"):
                from_plan.append("carried from an earlier day")
            href = f"/line/{t['line']}" if t.get("line") else f"/day/{day}"
            at = start if len(start) > 10 else f"{start[:10]}T00:00:00Z"
            rows.append(Loose(at, escape(name), DOT.join(from_plan), due_words(start[:10], day), href))
    for o in _owed(site, day) or ():
        said = day_rhythm.wrote_said(o, day, person)
        at, what = f"{o['day']}T12:00:00Z", f"A reply to {escape(str(o['name']))}"
        rows.append(Loose(at, what, said, None, f"/day/{o['day']}", OWED_RULE))
    return sorted(rows, key=lambda r: day_rhythm._instant(r.at))


def _plan(site: Site, day: str) -> object:
    """Today's plan from the task tool, as the Day's morning reads it (tier 1 alone, beside the page)."""
    if site.static or (site.tiers is not None and 1 not in site.tiers):
        return None
    head = str(site.lb.meta.get("head"))
    return site._day_later(("plan", day, head), lambda: day_rhythm.plan_of(site.lb, day))


def _owed(site: Site, day: str) -> Sequence[Mapping[str, Any]] | None:
    """The replies owed, as the Day's morning reads them (beside the page)."""
    if site.static:
        return None
    head = str(site.lb.meta.get("head"))
    directory = site._day_reading(("directory",), lambda: people.directory(site.lb))
    return site._day_later(
        ("owed", day, head), lambda: day_rhythm.replies_owed(site.lb, day, directory, site.tiers)
    )


def _owed_to_you(site: Site, day: str, person: Callable[[Mapping[str, Any]], str]) -> list[Loose]:
    """The open promises made to the owner, the same reading as What you owe."""
    tz = site.tz
    rows = [_promise(p, day, tz, person) for p in near(site, day) if p.direction == promises.OWED_TO_OWNER]
    return sorted(rows, key=lambda r: day_rhythm._instant(r.at))


def _section(name: str, title: str, rows: Sequence[Loose], empty: str, more: str | None) -> str:
    """A list of loose ends: the title, the count line, `MOST` rows the oldest first, the rest counted
    (a link to the full list when there is one); one sentence when there is none."""
    out = [f'<section class="{name}">\n<h2>{escape(title)}</h2>\n']
    if not rows:
        out.append(f'<p class="muted">{escape(empty)}</p>\n</section>\n')
        return "".join(out)
    out.append(f'<p class="count muted">{len(rows)} open{DOT}read from your record</p>\n')
    out.append('<ol class="loose">\n')
    for r in rows[:MOST]:
        out.append(_row(r))
    out.append("</ol>\n")
    rest = len(rows) - MOST
    if rest > 0:
        said = f"and {rest} more"
        shown = said if more is None else f'<a href="{escape(more)}">{said}</a>'
        out.append(f'<p class="more muted">{shown}</p>\n')
    out.append("</section>\n")
    return "".join(out)


def _row(r: Loose) -> str:
    today = " today" if r.due == "Today" else ""
    chip = f'<span class="due{today}">{escape(r.due)}</span>' if r.due else "<span></span>"
    prov = (
        f'<span class="prov pencil" title="{escape(r.rule)}">{r.said}</span>'
        if r.rule
        else f'<span class="prov">{r.said}</span>'
    )
    return (
        f'<li><a class="row" href="{escape(r.href)}"><span class="circle" aria-hidden="true"></span>'
        f'<span><span class="what">{r.what}</span>{prov}</span>{chip}</a></li>\n'
    )


# -- 6. your day, in your words --------------------------------------------------------------------------


def _words(
    site: Site,
    day: str,
    data: Mapping[str, Any],
    person: Callable[[Mapping[str, Any]], str],
    mine: Sequence[Loose],
) -> str:
    out = ['<section class="words card">\n']
    reflection = data.get("reflection")
    if reflection:
        at = str(reflection["at_local"])[11:16]
        out.append(f'<p class="mono-label">Ink{DOT}written {escape(at)}</p>\n')
        out.extend(
            f'<p class="ink">{escape(text)}</p>\n'
            for text in str(reflection["text"]).splitlines()
            if text.strip()
        )
    else:
        out.append('<p class="mono-label">Your day, in your words</p>\n')
        out.append('<p class="muted">Your words come here when you reflect on the day.</p>\n')
    made = sum(1 for r in mine if r.made_today)
    above = all(r in mine[:MOST] for r in mine if r.made_today)
    promised = (
        "Nothing yet today." if not made else f"{made}, above" if above else f"{made}, further down the list"
    )
    company = day_reader.company_of_day(data)
    with_ = ", ".join(person(c) for c in company) if company else "Nobody the record saw yet."
    touched = site._day_reading(("ideas moved", day), lambda: ideas_moved(site, day))
    moved = "; ".join(escape(t) for t in touched) if touched else "No idea moved yet today."
    out.append(
        '<dl class="questions">\n'
        f"<dt>What did I promise?</dt><dd>{escape(promised)}</dd>\n"
        f"<dt>Who was I with?</dt><dd>{with_}</dd>\n"
        f"<dt>How did my ideas move?</dt><dd>{moved}</dd>\n"
        "</dl>\n"
    )
    if not site.static:
        out.append(_acts(site, day))
    out.append("</section>\n")
    return "".join(out)


def ideas_moved(site: Site, day: str) -> list[str]:
    """How the ideas moved on `day`: each idea the record names whose status the owner set on the day
    (`status idea`, the Ideas shelf's act), by name and the stage it moved to, through the gate. The
    status lines of the day, by kind on the index: never the Ideas shelf's whole-record reading."""
    named = ideas.named(site.lb, site.tiers)
    if not named:
        return []
    with site.lb.index() as idx:
        lines = reading.crossing(idx.by_kind(entities.STATUS, day, day), site.tiers)
        marks = idx.retractions()
    moved: dict[str, str] = {}
    for (kind, idea), history in entities.statuses([*marks, *lines]).items():
        if kind == entities.IDEA and idea in named and history:
            moved[idea] = f"{named[idea].label}, now {history[-1].status}"
    return list(moved.values())


def _acts(site: Site, day: str) -> str:
    """The Day's two acts, Reflect and Sign: the same fields, posting to the same routes, as the Day's
    Reflect and sign (`Site._close_html`)."""
    found: Closing = site._closing(day)
    r = found.reflection
    has = r is not None and r.note is not None
    out = ['<section class="acts" id="acts">\n']
    out.append(f'<form class="reflect" method="post" action="/day/{day}/reflect">\n')
    if found.draft is not None:
        out.append(f'<input type="hidden" name="dictation" value="{escape(found.draft.id)}">\n')
        text = reflect.without_cue(found.draft.text)
    else:
        text = r.text if has and r is not None else ""
    out.append(
        f'<textarea name="text" rows="4" aria-label="your reflection" spellcheck="true"'
        ' placeholder="A few sentences about the day, in your words.">'
        f"{escape(text, quote=False)}</textarea>\n"
        f'<button name="act" value="reflect" class="{"" if has else "primary"}">'
        f"{'Add to the reflection' if has else 'Reflect'}</button>\n</form>\n"
    )
    if has and r is not None and r.note is not None:
        out.append(site._sign_html(day, found, r.note))
    else:
        out.append(
            '<p class="sign-later muted">Sign comes once you have reflected: it signs the day with your'
            " words among the lines it confirms.</p>\n"
        )
    out.append("</section>\n")
    return "".join(out)


# -- 7. the aside ----------------------------------------------------------------------------------------


def _aside(site: Site, day: str, morning: Morning, person: Callable[[Mapping[str, Any]], str]) -> str:
    out = ['<aside class="today-aside">\n', _week(site, day, morning.signed_week)]
    if morning.total:
        out.append(_ahead(morning.ahead, person))
        if site.with_drafts:
            proposal = site._day_reading(
                ("proposal", day), lambda: day_rhythm.week_proposal(site.lb, day, site.tiers)
            )
            if proposal is not None:
                out.append(
                    '<div class="card"><p class="mono-label">The week, proposed</p>\n'
                    f'<p class="pencil" title="{escape("drafted by " + str(proposal["model"]))}">'
                    f"{escape(str(proposal['text']))}</p></div>\n"
                )
    out.append(f'<p class="legend muted">{escape(LEGEND)}</p>\n')
    out.append(f'<p class="here muted">{escape(HERE)}</p>\n')
    out.append("</aside>\n")
    return "".join(out)


def _week(site: Site, day: str, signed: frozenset[str]) -> str:
    """Monday to Sunday of the day's week, a circle each, filled for a day signed, each a link to its Day."""
    monday = date.fromisoformat(day) - timedelta(days=date.fromisoformat(day).weekday())
    days = [(x, x in signed) for k in range(7) if (x := (monday + timedelta(days=k)).isoformat())]
    n = sum(1 for _d, s in days if s)
    items = []
    for d, s in days:
        dd = date.fromisoformat(d)
        label = f"{WEEKDAYS[dd.weekday()]} {dd.day} {MONTHS[dd.month - 1]}: {'signed' if s else 'not signed'}"
        cls = " ".join(x for x in ("signed" if s else "", "today" if d == day else "") if x)
        inner = f"<i></i>{WEEKDAYS[dd.weekday()][0]}"
        link = site.href(f"/day/{d}")
        attrs = f' class="{cls}"' if cls else ""
        if link is None or d > day:
            spanned = f"day {cls}".strip()
            items.append(f'<li><span class="{spanned}" aria-label="{escape(label)}">{inner}</span></li>')
        else:
            items.append(f'<li><a href="{escape(link)}"{attrs} aria-label="{escape(label)}">{inner}</a></li>')
    said = (
        "No day signed yet this week."
        if n == 0
        else "One day signed this week."
        if n == 1
        else f"{WORDS[n].capitalize()} days signed this week."
    )
    return (
        '<div class="card week">\n<p class="mono-label">This week, signed</p>\n'
        f'<ol class="week">{"".join(items)}</ol>\n<p class="muted">{escape(said)}</p>\n</div>\n'
    )


def coming_up(site: Site, day: str) -> list[dict[str, Any]]:
    """The calendar's entries of the `AHEAD` days after `day`, in time order, each with whom (names, as
    the morning's Who you'll see names them), through the gate; one entry once whatever its sources."""
    d = date.fromisoformat(day)
    directory = site._day_reading(("directory",), lambda: people.directory(site.lb))
    days = day_start.of(site.lb.meta)
    first, last = (d + timedelta(days=1)).isoformat(), (d + timedelta(days=AHEAD)).isoformat()
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    with site.lb.index() as idx:
        retracted = retractions(idx.retractions())
        lines = [
            line
            for line in reading.crossing(idx.by_kind(CALENDAR, first, last), site.tiers)
            if str(line["id"]) not in retracted
        ]
    for line in sorted(lines, key=lambda x: (day_rhythm._instant(str(x["at"])), int(x["seq"]))):
        payload = line.get("payload") or {}
        title = str(payload.get("title") or "").strip()
        if not title or (title.casefold(), str(line.get("at"))) in seen:
            continue
        seen.add((title.casefold(), str(line.get("at"))))
        at = day_rhythm._instant(str(line["at"]))
        planned = day_rhythm.Planned(title, at, at, False, None, str(line["id"]))
        who = day_rhythm.seeing([planned], {str(line["id"]): line}, directory, site.tiers)
        out.append({"day": days.day_of(str(line["at"])), "title": title, "who": who})
    return out


def _ahead(found: Sequence[Mapping[str, Any]], person: Callable[[Mapping[str, Any]], str]) -> str:
    out = ['<div class="card ahead">\n<p class="mono-label">Coming up</p>\n']
    if not found:
        out.append(
            '<p class="muted">The next days\u2019 calendar entries come here once your calendar is in'
            " the record.</p>\n"
        )
    else:
        out.append('<ul class="ahead">\n')
        for e in found:
            dd = date.fromisoformat(str(e["day"]))
            # the month after the date: never a digit right before a title, which may begin with a name
            label = f"{SHORT_DAYS[dd.weekday()]} {dd.day} {MONTHS[dd.month - 1][:3]}"
            who = (
                f'<span class="prov">with {", ".join(person(w) for w in e["who"])}</span>' if e["who"] else ""
            )
            out.append(
                f'<li><span class="mono-label">{escape(label)}</span>'
                f'<span><span class="what">{escape(str(e["title"]))}</span>{who}</span></li>\n'
            )
        out.append("</ul>\n")
    out.append("</div>\n")
    return "".join(out)


def _and(names: Sequence[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
