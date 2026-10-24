"""Life, the second door of the Library (RFC 0047 §4.2): `/life`, one page that answers "where am I in
my life, and what is it for?". Read-only: no form, no act, no script; every zoom and every move is a
link whose address carries the moment (RFC §5).

From the top:

- **This chapter**: the chapter today is in (`chapter/v1`, RFC 0036, read through the Goals shelf's
  reader, `shelf_goals.read`), since when, its rules in the owner's words (ink), and the first sentence
  of a model's draft of it when the `dream` entry allows one (`draft/v1` unit `chapter`, pencil).
- **Goals for the year**: the year's and the quarter's goals that hold this year, then **for life**,
  each with its last review or the day it began, and one **next look** when a standing review names
  a day to look again (its `extra.revisit`, the key the Day's decisions use). Never a percentage, a
  score or a streak.
- **The timeline**, between the bounds of a life: `life` in `logbook.json`, `{"from": "YYYY-MM-DD",
  "to": "YYYY-MM-DD"}` (`setting`, docs/settings.md), else the record's first day to the end of next
  year, and never to the last line the record holds: a calendar entry in 2055 draws no thirty years of
  nothing. Five zooms: **Life** (one line across the bounds: chapters as bands, the trips the owner
  named, the reflections the owner starred on a signed day, the first signed day, the record's silences
  drawn as silence, before the record dotted, NOW, and AHEAD lighter; at most `LABELS_MOST` labels,
  the rest marks with a title), **Year** (the default: twelve months, the trips as spans with their
  names, the chapters, the signed days as dots, the silences), **Month** (its weeks, each a link to
  the week page, `week_page`, and each day to its Day), **Week** (its seven days) and **Day** (a
  window of days, a fortnight by default, `?from=&to=` as `/days` takes it). `?trip=FIRST/LAST` is one
  trip's days. Earlier and later are two links beside the zoom tabs.
- **Not yet placed**: chapter lines with no first day, and the one command that dates one.
- **Volumes**: the years of the record as spines, each a link to its days (the printed edition has no
  route in the Library yet).

What it reads, through the page's gate (`Site.tiers`, `reading.crossing`): the chapters, goals and
reviews (tier 2, so a gate without tier 2 shows none and says why), the standing signatures
(`signing.signatures`), the stars on reflections, the journeys' names (`note/v1` label `name`), the
trips of the years in view (`journeys.shelf`, the reading the Journeys door shares, `Site.shared`),
and the days the record holds a line on (`gaps.activity_of`, kept beside the index; through a gate, the
index's own days at those tiers). Nothing is read over the whole record but kinds the index hands out
whole and what is kept beside it. No number is ever set beside a person's name: a trip's dates follow
its name after a word ("from"), and no count is shown at all."""

from __future__ import annotations

import calendar
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from html import escape
from typing import TYPE_CHECKING, Any

from ..core import chapter as chapters
from ..core import day_start, drafts, goals, notes, reading, signing, stars, trips
from ..core.export import parse_day
from ..core.index import Index
from ..core.store import retractions
from . import gaps, journeys, shelf_goals

if TYPE_CHECKING:  # the Site passes itself; serve imports this module, never the other way at import
    from .serve import Site

KEY = "life"  # the key of logbook.json
LIFE, YEAR, MONTH, WEEK, DAY, TRIP = "life", "year", "month", "week", "day", "trip"
ZOOMS = (LIFE, YEAR, MONTH, WEEK, DAY)
ZOOM_NAMES = {LIFE: "Life", YEAR: "Year", MONTH: "Month", WEEK: "Week", DAY: "Day"}
LABELS_MOST = 12  # labels on the Life zoom; every other moment is a mark with a title
LANES = 3  # rows of labels above the Life line
TICK_YEARS = 5
SILENT_LIFE, SILENT_YEAR = 30, 7  # days with no line, at least, drawn as a silence on the Life and the Year
DAY_WINDOW, DAY_MOST, TRIP_MOST = 14, 92, 366  # the Day zoom's window, the most it shows; a trip's most
MARGIN_DAYS = journeys.MARGIN_DAYS  # a window early in January reads the year before's trips too
CANVAS_PX = 960  # the Life and the Year are drawn this wide at least: a phone scrolls them in their box
LABEL_PX, CHAR_PX = 20, 7.4  # a label's width, estimated, to keep two from overlapping
CHAPTER_COMMAND = 'logbook chapter open "NAME" --from YYYY-MM-DD'
GOAL_COMMAND = 'logbook goal add "…" --horizon year'
VOLUMES_LINE = "A year of your life, bound. Signed days in ink, the rest left honest."
MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)  # fmt: skip
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
STYLE = """
.door-life{background:var(--paper, #F4F1EA);color:var(--ink, #16181D);border-radius:22px;padding:36px;
margin:0 0 1rem;font:400 15px/1.5 Inter,system-ui,sans-serif;overflow-wrap:anywhere}
.door-life a{color:var(--ink, #16181D);text-underline-offset:3px}
.door-life h1,.door-life h2,.door-life h3,.door-life .serif{font-family:'Instrument Serif',Georgia,serif;
font-weight:400;letter-spacing:-.01em;margin:0}
.door-life h1{font-size:72px;line-height:1;margin:0 0 32px}
.door-life h2{font-size:36px;line-height:1.1}
.door-life h3{font-size:24px;line-height:1.2}
.door-life .label{font:500 12px/1.4 'JetBrains Mono',ui-monospace,monospace;text-transform:uppercase;
letter-spacing:.13em;color:var(--pencil, #62666D);margin:0 0 12px}
.door-life .ink{color:var(--ink, #16181D)}
.door-life .pencil{color:var(--pencil, #62666D);text-decoration:underline dotted var(--pencil-rule, #8C8F95);
text-underline-offset:4px}
.door-life .prov{font-size:13px;color:var(--pencil, #62666D);margin:4px 0 0}
.door-life .empty{color:var(--pencil, #62666D);margin:0}
.door-life code{font:400 13px 'JetBrains Mono',ui-monospace,monospace;background:var(--tint, #EDE8DE);
border-radius:6px;padding:1px 6px}
.door-life .top{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin:0 0 44px;align-items:start}
.door-life .card{background:var(--surface, #FBFAF6);border:1px solid var(--line, #E3DED3);border-radius:20px;
padding:32px;min-width:0}
.door-life .chapter h2{margin:0 0 12px}
.door-life .rules{font-size:17px;margin:0}
.door-life .card .pencil{margin:12px 0 0}
.door-life ol.goals{list-style:none;padding:0;margin:0 0 24px}
.door-life ol.goals li{padding:12px 0;border-top:1px solid var(--line-soft, #ECE7DD)}
.door-life ol.goals li:first-child{border-top:0;padding-top:0}
.door-life .goal{font:400 24px/1.2 'Instrument Serif',Georgia,serif;margin:0}
.door-life .goal-note{font-size:15px;margin:4px 0 0}
.door-life section.timeline{margin:0 0 20px}
.door-life section.timeline>h2{margin:0 0 16px}
.door-life nav.zoom{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 16px}
.door-life nav.zoom a,.door-life nav.zoom>span[aria-current],.door-life .pill{display:inline-flex;
align-items:center;min-height:44px;padding:0 18px;
border-radius:23px;border:1px solid var(--line, #E3DED3);background:var(--surface, #FBFAF6);
color:var(--ink, #16181D);text-decoration:none;margin:0;box-sizing:border-box;font-weight:500}
.door-life nav.zoom>span[aria-current=page]{background:var(--ink, #16181D);border-color:var(--ink, #16181D);
color:var(--paper, #F4F1EA)}
.door-life nav.zoom .moves{display:flex;gap:8px;margin-left:auto}
.door-life nav.zoom .off{color:var(--pencil-rule, #8C8F95);background:transparent}
.door-life .box{overflow-x:auto;background:var(--surface, #FBFAF6);border:1px solid var(--line, #E3DED3);
border-radius:20px;padding:20px;margin:0 0 16px}
.door-life .canvas{position:relative;min-width:960px}
.door-life .canvas>*{position:absolute;box-sizing:border-box}
.door-life .canvas .label{margin:0;height:44px;display:flex;align-items:center;white-space:nowrap;
font:400 15px/1.2 'Instrument Serif',Georgia,serif;font-size:19px;letter-spacing:0;text-transform:none;
color:var(--ink, #16181D);text-decoration:none}
.door-life .seg{height:2px;background:var(--ink, #16181D)}
.door-life .seg.before{background:none;border-top:2px dotted var(--pencil-rule, #8C8F95)}
.door-life .seg.silence{background:var(--surface, #FBFAF6);border-top:2px dotted var(--line, #E3DED3);
height:0}
.door-life .seg.ahead{background:var(--line, #E3DED3)}
.door-life .band{background:var(--ink, #16181D);border-radius:7px;min-width:4px;opacity:.55}
.door-life .band.current{opacity:1}
.door-life .span{background:var(--pencil-rule, #8C8F95);border-radius:4px;min-width:10px;height:8px}
.door-life .tick{width:12px;height:44px;margin-left:-6px}
.door-life .tick::after{content:"";position:absolute;left:5px;top:12px;width:2px;height:20px;
background:var(--ink, #16181D)}
.door-life .tick.signed::after{background:var(--pencil, #62666D)}
.door-life .tick.reflection::after,.door-life .dot.reflection::after{content:"\\2605";background:none;
width:auto;height:auto;left:0;top:12px;border:0;border-radius:0;font:400 14px/1 Georgia,serif;
color:var(--ink, #16181D)}
.door-life .year-tick{font:400 12px 'JetBrains Mono',ui-monospace,monospace;color:var(--pencil, #62666D);
transform:translateX(-50%);padding-top:10px;white-space:nowrap}
.door-life .year-tick::before{content:"";position:absolute;left:50%;top:0;width:1px;height:6px;
background:var(--pencil-rule, #8C8F95)}
.door-life .now{width:2px;background:var(--signal, #C8401A);scroll-initial-target:nearest;
scroll-margin-left:240px}
.door-life .now-label{font:500 12px 'JetBrains Mono',ui-monospace,monospace;letter-spacing:.12em;
color:var(--signal-deep, #A93413);transform:translateX(-50%);white-space:nowrap}
.door-life .ahead-label{font:500 12px 'JetBrains Mono',ui-monospace,monospace;letter-spacing:.12em;
color:var(--pencil-rule, #8C8F95);margin-left:28px;white-space:nowrap}
.door-life .ahead{background:var(--tint, #EDE8DE);opacity:.55}
.door-life .rule{width:1px;background:var(--line-soft, #ECE7DD)}
.door-life .month{font:500 12px 'JetBrains Mono',ui-monospace,monospace;letter-spacing:.12em;
color:var(--pencil, #62666D);text-decoration:none;height:44px;display:flex;align-items:center;
padding-left:8px}
.door-life .dot{width:12px;height:44px;margin-left:-6px}
.door-life .dot::after{content:"";position:absolute;left:2px;top:18px;width:8px;height:8px;border-radius:50%;
background:var(--ink, #16181D)}
.door-life .weeks{display:grid;grid-template-columns:72px repeat(7,minmax(44px,1fr));gap:4px;min-width:440px}
.door-life .weeks .h{font:500 12px 'JetBrains Mono',ui-monospace,monospace;letter-spacing:.12em;
color:var(--pencil, #62666D);text-align:center;padding:4px 0}
.door-life .weeks .wk{font:500 12px 'JetBrains Mono',ui-monospace,monospace;color:var(--ink, #16181D);
display:flex;align-items:center;min-height:56px}
.door-life .cell{position:relative;display:block;min-height:56px;border:1px solid var(--line-soft, #ECE7DD);
border-radius:10px;padding:6px 8px;text-decoration:none;background:var(--paper, #F4F1EA)}
.door-life .cell .n{font:400 20px/1 'Instrument Serif',Georgia,serif}
.door-life .cell.out{opacity:.45}
.door-life .cell.silent,.door-life .cell.ahead{background:transparent;color:var(--pencil-rule, #8C8F95)}
.door-life .cell.today{border:2px solid var(--signal, #C8401A)}
.door-life .cell.away{box-shadow:inset 0 -6px 0 var(--pencil-rule, #8C8F95)}
.door-life .cell .marks{position:absolute;right:8px;top:8px;display:flex;gap:4px}
.door-life i.m{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--ink, #16181D)}
.door-life i.m.reflection{background:none;border:2px solid var(--ink, #16181D);box-sizing:border-box}
.door-life i.m.chapter{border-radius:2px}
.door-life .sevens{display:grid;grid-template-columns:repeat(7,minmax(120px,1fr));gap:8px;min-width:880px}
.door-life .wday{border:1px solid var(--line-soft, #ECE7DD);border-radius:14px;padding:14px;
background:var(--paper, #F4F1EA);min-height:160px}
.door-life .wday.silent,.door-life .wday.ahead{background:transparent}
.door-life .wday.today{border:2px solid var(--signal, #C8401A)}
.door-life .wday .label{margin:0 0 4px}
.door-life .wday .date{font:400 22px/1.2 'Instrument Serif',Georgia,serif;text-decoration:none;
display:inline-flex;min-height:44px;align-items:center}
.door-life ul.marks{list-style:none;padding:0;margin:6px 0 0;font-size:13px}
.door-life ul.marks li{padding:3px 0}
.door-life ul.marks a,.door-life ol.days .marks a,.door-life ul.this a{display:inline-flex;align-items:center;
min-height:44px}
.door-life .quiet{color:var(--pencil-rule, #8C8F95)}
.door-life ol.days{list-style:none;padding:0;margin:0}
.door-life ol.days li{display:flex;flex-wrap:wrap;gap:4px 14px;align-items:center;padding:6px 0;
border-top:1px solid var(--line-soft, #ECE7DD)}
.door-life ol.days li:first-child{border-top:0}
.door-life ol.days .date{font:400 22px/1.2 'Instrument Serif',Georgia,serif;text-decoration:none;
min-height:44px;display:inline-flex;align-items:center;min-width:12rem}
.door-life ol.days .yr{font:400 12px 'JetBrains Mono',ui-monospace,monospace;color:var(--pencil, #62666D)}
.door-life ol.days .marks{font-size:13px;color:var(--pencil, #62666D)}
.door-life ol.days .marks .ink{font-size:15px}
.door-life ul.this{list-style:none;padding:0;margin:8px 0 0}
.door-life ul.this li{padding:6px 0;display:flex;gap:4px 10px;align-items:baseline}
.door-life ul.this .v{flex:1;min-width:0}
.door-life ul.this .k{font:500 12px 'JetBrains Mono',ui-monospace,monospace;letter-spacing:.12em;
text-transform:uppercase;color:var(--pencil, #62666D);min-width:6.5rem}
.door-life ul.this a{font:400 19px/1.3 'Instrument Serif',Georgia,serif}
.door-life .trip-head{margin:0 0 12px}
.door-life .trip-head h3{margin:0 0 4px}
.door-life section.unplaced{border-top:1px solid var(--line, #E3DED3);padding:20px 0 0;margin:0 0 20px}
.door-life section.unplaced .names{font:400 22px/1.3 'Instrument Serif',Georgia,serif;margin:0 0 6px}
.door-life section.volumes{border-top:1px solid var(--line, #E3DED3);padding:28px 0 0}
.door-life section.volumes .lede{font:400 26px/1.25 'Instrument Serif',Georgia,serif;margin:0 0 20px}
.door-life ol.spines{list-style:none;padding:0;margin:0;display:flex;flex-wrap:wrap;gap:10px}
.door-life a.spine{display:flex;align-items:center;min-height:160px;width:52px;padding:14px 0;
writing-mode:vertical-rl;transform:rotate(180deg);justify-content:flex-end;
box-sizing:border-box;border-radius:8px 8px 4px 4px;background:var(--ink, #16181D);
color:var(--paper, #F4F1EA);text-decoration:none;font:400 20px/1.1 'Instrument Serif',Georgia,serif}
.door-life a.spine.current{background:var(--surface, #FBFAF6);color:var(--ink, #16181D);
border:1px dashed var(--pencil-rule, #8C8F95)}
.door-life .problem{font-size:13px;color:var(--signal-deep, #A93413);margin:0 0 12px}
@media (max-width:40rem){
.door-life{margin:0 -1rem 1rem;border-radius:0;padding:24px 16px}
.door-life h1{font-size:40px;margin:0 0 20px}
.door-life .top{grid-template-columns:1fr;gap:12px;margin:0 0 32px}
.door-life .card{padding:20px}
.door-life .box{padding:12px;border-radius:18px}
.door-life nav.zoom .moves{margin-left:0;flex-basis:100%}
.door-life .box.calendar{padding:8px}
.door-life .weeks{grid-template-columns:repeat(7,minmax(0,1fr));gap:2px;min-width:0}
.door-life .weeks .h.week{display:none}
.door-life .weeks .wk{grid-column:1/-1;min-height:44px}
.door-life .cell{min-height:52px;padding:4px 5px;border-radius:8px}
.door-life .cell .marks{top:auto;bottom:8px;right:4px;gap:2px}
.door-life ul.this li{flex-direction:column;gap:0}
.door-life ol.days .date{min-width:0}
}
"""  # Life's own, scoped under `.door-life`: the shell's tokens (custom properties) with the face's values


class LifeError(ValueError):
    """`life` in `logbook.json` is not two local days, `from` on or before `to`; the message names the
    key and the value."""


@dataclass(frozen=True)
class Bounds:
    """The days a life runs between on the page: the setting's, or the record's first day to the end of
    next year; `problem`, when there is a setting this reader could not read, why."""

    first: str
    last: str
    problem: str | None = None


@dataclass(frozen=True)
class View:
    """What the timeline shows: its zoom, the day in focus, the window's first and last day, and the
    trip's first and last day when it is one trip's."""

    zoom: str
    at: str
    first: str
    last: str
    trip: tuple[str, str] | None = None


@dataclass(frozen=True)
class Trip:
    """A trip as the timeline draws it: its first day away, its last night away (its id's two days),
    the day home, the owner's name for it, the places it went."""

    first: str
    last: str
    home: str
    name: str | None
    places: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return self.name or ", ".join(self.places[:2]) or "Away"

    @property
    def query(self) -> str:
        return f"trip={self.first}/{self.last}"


@dataclass(frozen=True)
class Starred:
    """A reflection the owner starred, on a day they signed: its day, its line, its first words."""

    day: str
    line: str
    text: str


@dataclass
class Record:
    """What the door reads of the record through its gate, once a request."""

    today: str
    first_day: str | None
    words: bool  # the gate reads tier 2, the owner's words: chapters, goals, names, reflections
    shelf: shelf_goals.Shelf | None
    undated: list[str] = field(default_factory=list)
    signed: list[str] = field(default_factory=list)
    starred: list[Starred] = field(default_factory=list)
    named: list[Trip] = field(default_factory=list)
    draft: tuple[str, str] | None = None  # the chapter's pencil: its first sentence, the model
    revisits: dict[str, str] = field(default_factory=dict)  # goal line → the day a review asks to look again


# -- the setting -------------------------------------------------------------------------------------------


def setting(meta: Mapping[str, Any]) -> tuple[str, str] | None:
    """`life` in `meta` (`logbook.json`) as its two days; None when absent. `LifeError` for anything
    that is not `{"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}` with `from` on or before `to`."""
    found = meta.get(KEY)
    if found is None:
        return None
    shape = f'logbook.json has {KEY} {found!r}, which is not {{"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}}'
    if not isinstance(found, Mapping):
        raise LifeError(shape)
    first, last = _day_or_none(found.get("from")), _day_or_none(found.get("to"))
    if first is None or last is None:
        raise LifeError(shape)
    if last < first:
        raise LifeError(f"logbook.json has {KEY} to {last}, before its from {first}")
    return first, last


def bounds(meta: Mapping[str, Any], first_day: str | None, today: str) -> Bounds:
    """The setting's bounds, else from the record's first day (today on an empty record) to the last
    day of next year: never to the last line the record holds."""
    problem = None
    try:
        found = setting(meta)
    except LifeError as e:
        found, problem = None, str(e)
    if found is not None:
        return Bounds(*found)
    return Bounds(min(first_day or today, today), f"{int(today[:4]) + 1}-12-31", problem)


def _day_or_none(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return parse_day(value).isoformat()
    except ValueError:
        return None


# -- the address -------------------------------------------------------------------------------------------


def view(params: Mapping[str, str], today: str, b: Bounds) -> View:
    """The view an address asks for: `trip=FIRST/LAST`; else `zoom` (life, year, month, week, day) at
    `at` (or `year`), a year, a month or a day; a zoom not given follows what `at` names (a year, its
    year; a month, its month; a day, its week), or a window of days when `from` or `to` is given, else
    the year with today in view. `at` outside the bounds is shown at the nearer bound. `ValueError`
    for anything else, which the server answers with a 400."""
    asked_trip = params.get("trip") or ""
    if asked_trip:
        a, sep, z = asked_trip.partition("/")
        first, last = _day(a, "trip"), _day(z, "trip") if sep else ""
        if (
            not sep
            or last < first
            or (date.fromisoformat(last) - date.fromisoformat(first)).days >= TRIP_MOST
        ):
            raise ValueError(f"trip={asked_trip}: FIRST/LAST, two days, the first on or before the last")
        return View(TRIP, first, first, last, (first, last))
    zoom = params.get("zoom") or ""
    if zoom and zoom not in ZOOMS:
        raise ValueError(f"zoom={zoom!r} is not one of {', '.join(ZOOMS)}")
    asked = params.get("at") or params.get("year") or ""
    at, precision = _at(asked, today) if asked else (today, "")
    if not zoom:
        zoom = {YEAR: YEAR, MONTH: MONTH, DAY: WEEK}.get(precision) or (
            DAY if params.get("from") or params.get("to") else YEAR
        )
    at = min(max(at, b.first), b.last)
    d = date.fromisoformat(at)
    if zoom == LIFE:
        return View(LIFE, at, b.first, b.last)
    if zoom == YEAR:
        return View(YEAR, at, f"{d.year}-01-01", f"{d.year}-12-31")
    if zoom == MONTH:
        first_d = d.replace(day=1)
        return View(MONTH, at, first_d.isoformat(), d.replace(day=_month_days(d)).isoformat())
    if zoom == WEEK:
        monday = d - timedelta(days=d.weekday())
        return View(WEEK, at, monday.isoformat(), (monday + timedelta(days=6)).isoformat())
    given_from, given_to = params.get("from") or "", params.get("to") or ""
    if given_from or given_to:
        window = timedelta(days=DAY_WINDOW - 1)
        end = date.fromisoformat(_day(given_to, "to")) if given_to else None
        start = date.fromisoformat(_day(given_from, "from")) if given_from else None
        if start is None:
            assert end is not None
            start = end - window
        if end is None:
            end = start + window
        if end < start or (end - start).days >= DAY_MOST:
            raise ValueError(f"from {start} to {end}: a window of days runs forward, {DAY_MOST} days at most")
        return View(DAY, start.isoformat(), start.isoformat(), end.isoformat())
    sunday = d + timedelta(days=6 - d.weekday())
    return View(DAY, at, (sunday - timedelta(days=DAY_WINDOW - 1)).isoformat(), sunday.isoformat())


def _day(text: str, what: str) -> str:
    try:
        return parse_day(text).isoformat()
    except ValueError:
        raise ValueError(f"{what}={text!r} is not a day, YYYY-MM-DD") from None


def _at(text: str, today: str) -> tuple[str, str]:
    """`at` as the day in focus and what it named: a year (today when it is this year, else its first
    day), a month (likewise) or a day."""
    try:
        if len(text) == 4 and text.isdigit():
            return (today if today[:4] == text else f"{text}-01-01"), YEAR
        if len(text) == 7 and text[4] == "-":
            first = date(int(text[:4]), int(text[5:]), 1).isoformat()
            return (today if today[:7] == text else first), MONTH
        return parse_day(text).isoformat(), DAY
    except ValueError:
        raise ValueError(f"at={text!r} is not a year, a month or a day (YYYY, YYYY-MM, YYYY-MM-DD)") from None


def _month_days(d: date) -> int:
    return calendar.monthrange(d.year, d.month)[1]


def tabs(v: View) -> list[tuple[str, str]]:
    """(zoom, the address's query) for each zoom tab, keeping the moment in view."""
    return [
        (LIFE, "zoom=life"),
        (YEAR, f"zoom=year&at={v.at[:4]}"),
        (MONTH, f"zoom=month&at={v.at[:7]}"),
        (WEEK, f"zoom=week&at={v.at}"),
        (DAY, f"zoom=day&at={v.at}"),
    ]


def moves(v: View, b: Bounds) -> tuple[tuple[str, str] | None, tuple[str, str] | None]:
    """Earlier and later: (the address's query, what it names in words), or None at a bound and on the
    Life and a trip, which have no neighbour."""
    d = date.fromisoformat(v.at)
    first, last = date.fromisoformat(v.first), date.fromisoformat(v.last)
    lo, hi = b.first, b.last
    if v.zoom == YEAR:
        earlier = (f"zoom=year&at={d.year - 1}", str(d.year - 1)) if f"{d.year - 1}-12-31" >= lo else None
        later = (f"zoom=year&at={d.year + 1}", str(d.year + 1)) if f"{d.year + 1}-01-01" <= hi else None
        return earlier, later
    if v.zoom == MONTH:
        before = first - timedelta(days=1)
        after = last + timedelta(days=1)
        earlier = (
            (f"zoom=month&at={before.isoformat()[:7]}", f"{MONTHS[before.month - 1]} {before.year}")
            if before.isoformat() >= lo
            else None
        )
        later = (
            (f"zoom=month&at={after.isoformat()[:7]}", f"{MONTHS[after.month - 1]} {after.year}")
            if after.isoformat() <= hi
            else None
        )
        return earlier, later
    if v.zoom in (WEEK, DAY):
        span = (last - first).days + 1
        a, z = first - timedelta(days=span), last + timedelta(days=span)
        if v.zoom == WEEK:
            earlier = (
                (f"zoom=week&at={a.isoformat()}", "the week before")
                if (first - timedelta(days=1)).isoformat() >= lo
                else None
            )
            later = (
                (f"zoom=week&at={(last + timedelta(days=1)).isoformat()}", "the week after")
                if (last + timedelta(days=1)).isoformat() <= hi
                else None
            )
            return earlier, later
        before, after = first - timedelta(days=1), last + timedelta(days=1)
        earlier = (
            (f"zoom=day&from={a.isoformat()}&to={before.isoformat()}", "the days before")
            if before.isoformat() >= lo
            else None
        )
        later = (
            (f"zoom=day&from={after.isoformat()}&to={z.isoformat()}", "the days after")
            if after.isoformat() <= hi
            else None
        )
        return earlier, later
    return None, None


# -- the reading -------------------------------------------------------------------------------------------


def _reads(tiers: Sequence[int] | None, tier: int) -> bool:
    return tiers is None or tier in {int(t) for t in tiers}


def read(site: Site, today: str) -> Record:
    """What the door shows of the record through the page's gate, on `today`. Writes nothing."""
    lb, tiers = site.lb, site.tiers
    days = day_start.of(lb.meta)
    owner = str(lb.meta.get("owner_id") or "") or None
    words = _reads(tiers, goals.TIER)
    shelf = shelf_goals.read(lb, tiers, today) if words else None
    found = Record(today, None, words, shelf)
    with lb.index() as idx:
        retracted = retractions(idx.retractions())
        found.first_day = _first_day(idx, tiers)
        signatures = reading.crossing(idx.by_kind(signing.KIND), tiers)
        found.signed = sorted(signing.signatures(signatures, retracted, owner))
        if not words or shelf is None:
            return found
        found.undated = _undated(idx, tiers, retracted, shelf)
        signed = set(found.signed)
        marks = stars.standing(reading.crossing(idx.by_kind(stars.KIND), tiers), retracted)
        noted = [s.line for s in marks.values() if s.kind == notes.KIND]
        for line in reading.crossing(idx.by_ids(noted).values(), tiers):
            day = days.day_of(str(line["at"]))
            if notes.labelled(line, notes.REFLECTION) and day in signed and str(line["id"]) not in retracted:
                found.starred.append(Starred(day, str(line["id"]), stars.title(line)))
        found.starred.sort(key=lambda s: s.day)
        found.named = _named(reading.crossing(idx.by_kind(notes.KIND), tiers), frozenset(retracted))
        reviews = [g.review.line for g in shelf.goals if g.review is not None]
        for line in idx.by_ids(reviews).values():
            extra = (line.get("payload") or {}).get("extra")
            again = _day_or_none(extra.get("revisit")) if isinstance(extra, Mapping) else None
            if again is not None:
                found.revisits[str((line.get("payload") or {}).get("goal"))] = again
        if site.with_drafts and shelf.chapter is not None:
            found.draft = _chapter_draft(site, idx, retracted, shelf.chapter.line)
    found.revisits = {shelf.by_line.get(goal, goal): day for goal, day in found.revisits.items()}
    return found


def _first_day(idx: Index, tiers: Sequence[int] | None) -> str | None:
    """The first local day with a line that observes a day (`reading.record_span`'s rule), at the
    gate's tiers: the index's columns, nothing read from the files."""
    bookkeeping = sorted(reading.BOOKKEEPING)
    where = f"kind NOT IN ({','.join('?' * len(bookkeeping))})"
    params: list[object] = list(bookkeeping)
    if tiers is not None:
        where += f" AND tier IN ({','.join('?' * len(tiers)) or 'NULL'})"
        params += [int(t) for t in tiers]
    (first,) = idx.db.execute(f"SELECT min(day_local) FROM lines WHERE {where}", params).fetchone()
    return None if first is None else str(first)


def _undated(
    idx: Index, tiers: Sequence[int] | None, retracted: Collection[str], shelf: shelf_goals.Shelf
) -> list[str]:
    """The names of the chapter lines with no first day that no dated chapter has the name of since."""
    dated = {c.name for c in shelf.chapters}
    out: list[str] = []
    for line in reading.crossing(idx.by_kind(chapters.KIND), tiers):
        payload = line.get("payload") or {}
        name = payload.get("name")
        if not chapters.is_chapter(line) or str(line["id"]) in retracted or not isinstance(name, str):
            continue
        if (
            _day_or_none(payload.get("from")) is None
            and name.strip()
            and name not in dated
            and name not in out
        ):
            out.append(name.strip())
    return out


def _named(lines: Sequence[Any], retracted: frozenset[str]) -> list[Trip]:
    """The trips the owner named (`journeys.names_in`), each by its id's two days, the latest name."""
    found: dict[tuple[str, str], str] = {}
    for line in journeys.names_in(lines, retracted):
        payload = line.get("payload") or {}
        extra = payload.get("extra") or {}
        parts = str(extra.get("trip") or "").split(":")
        if len(parts) != 3 or _day_or_none(parts[1]) is None or _day_or_none(parts[2]) is None:
            continue
        found[(parts[1], parts[2])] = " ".join(str(payload.get("text") or "").split())
    out = []
    for (first, last), name in found.items():
        home = (date.fromisoformat(last) + timedelta(days=1)).isoformat()
        out.append(Trip(first, last, home, name))
    return sorted(out, key=lambda t: t.first)


def _chapter_draft(site: Site, idx: Index, retracted: Collection[str], line: str) -> tuple[str, str] | None:
    """The first supported sentence of the chapter's standing draft the `dream` entry allows, and the
    model that wrote it: the chapter's lines are its subject (`dream_chapter`), any line of its chain."""
    every = chapters.chapter_lines(reading.crossing(idx.by_kind(chapters.KIND), site.tiers), retracted)
    later = chapters.successors(every)

    def last_of(i: str) -> str:
        while i in later:
            i = later[i]
        return i

    chain = {str(c["id"]) for c in every if last_of(str(c["id"])) == line} | {line}
    by_subject = drafts.by_unit(idx.by_kind(drafts.KIND), retracted, drafts.UNIT_CHAPTER)
    found = sorted(
        {str(d["id"]): d for i in chain for d in by_subject.get(i, [])}.values(),
        key=lambda d: (str(d["at"]), int(d["seq"])),
    )
    shown, _withheld = drafts.through(found, site.tiers, drafts.allowed(site.lb.root))
    top = drafts.standing(shown)
    if top is None:
        return None
    for segment in (top.get("payload") or {}).get("segments") or []:
        if drafts.segment_shape(segment) == "supported":
            return str(segment["text"]).strip(), drafts.model_of(top.get("source"))
    return None


def held(site: Site, first: str, last: str, today: str) -> set[str]:
    """The local days of `[first, last]` up to today the record holds a line on, through the gate: the
    sources' days kept beside the index (`gaps.activity_of`, as `/gaps` reads it) when the page reads
    every tier, else the index's days at the gate's tiers. Nothing is read from the files."""
    end = min(last, today)
    if end < first:
        return set()
    if site.tiers is None:
        found = site.shared(("activity", "", today), lambda: gaps.activity_of(site.lb, "", today))
        return {d for a in found for d in a["days"] if first <= d <= end}
    tiers = [int(t) for t in site.tiers]
    with site.lb.index() as idx:
        rows = idx.db.execute(
            "SELECT DISTINCT day_local FROM lines WHERE day_local BETWEEN ? AND ? AND kind != 'retraction'"
            f" AND tier IN ({','.join('?' * len(tiers)) or 'NULL'})",
            [first, end, *tiers],
        ).fetchall()
    return {str(d) for (d,) in rows}


def silences(site: Site, rec: Record, first: str, last: str, at_least: int) -> list[tuple[str, str]]:
    """The runs of `at_least` days or more in `[first, last]`, between the record's first day and
    today, on which the record holds no line through the gate."""
    if rec.first_day is None:
        return []
    a, z = max(first, rec.first_day), min(last, rec.today)
    if z < a:
        return []
    days_held = held(site, a, z, rec.today)
    out: list[tuple[str, str]] = []
    run: list[str] = []
    for d in _days(a, z):
        if d in days_held:
            if len(run) >= at_least:
                out.append((run[0], run[-1]))
            run = []
        else:
            run.append(d)
    if len(run) >= at_least:
        out.append((run[0], run[-1]))
    return out


def trips_of(site: Site, rec: Record, v: View) -> list[Trip]:
    """The trips that touch the window, from the Journeys door's reading of each year it touches
    (`journeys.shelf`, kept for every page that asks, `Site.shared`); a year's trips are those that
    began in it, so a window early in January reads the year before too, but a Year reads its own."""
    first = date.fromisoformat(v.first)
    since = first.year if v.zoom == YEAR else (first - timedelta(days=MARGIN_DAYS)).year
    out: dict[str, Trip] = {}
    for year in range(since, int(v.last[:4]) + 1):
        if rec.first_day is None or f"{year}-12-31" < rec.first_day or f"{year}-01-01" > rec.today:
            continue
        shelf = site.shared(("journeys", str(year)), _journeys(site, str(year)))
        for j in shelf.journeys:
            t = j.trip
            if t.until < v.first or t.start > v.last:
                continue
            name = j.name.text if j.name is not None and rec.words else None
            places = tuple(trips.route_names(t.route)) or tuple(t.places)
            out[t.id] = Trip(t.start, t.end, t.until, name, places)
    return sorted(out.values(), key=lambda t: t.first)


def _journeys(site: Site, year: str) -> Callable[[], journeys.Shelf]:
    return lambda: journeys.shelf(site.lb, year, site.airports, site.tiers)


def _days(first: str, last: str) -> list[str]:
    a, z = date.fromisoformat(first), date.fromisoformat(last)
    return [(a + timedelta(days=n)).isoformat() for n in range((z - a).days + 1)]


# -- words ---------------------------------------------------------------------------------------------------


def words(day: str, today: str) -> str:
    """`3 May`, and the year when it is not this one: `3 May 2024`."""
    d = date.fromisoformat(day)
    out = f"{d.day} {MONTHS[d.month - 1]}"
    return out if day[:4] == today[:4] else f"{out} {d.year}"


def weekday(day: str) -> str:
    return WEEKDAYS[date.fromisoformat(day).weekday()]


def week_of(day: str) -> str:
    """The ISO week of `day`, as the week page's address names it: `2026-W25`."""
    iso = date.fromisoformat(day).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _range(first: str, last: str, today: str) -> str:
    """`15 June to 21 June`, a window's days in a label."""
    return words(first, today) if first == last else f"{words(first, today)} to {words(last, today)}"


def _chapter_words(c: shelf_goals.Chapter, today: str) -> str:
    """`from 1 August 2019 to 2 May`, or `since 3 May` while it is open."""
    return _span_words(c.start, c.to, today) if c.to else f"since {words(c.start, today)}"


def _span_words(first: str, last: str, today: str) -> str:
    """`from 15 June to 18 June`, or `on 15 June` for one day: after a name, always after a word."""
    if first == last:
        return f"on {words(first, today)}"
    return f"from {words(first, today)} to {words(last, today)}"


# -- the page ------------------------------------------------------------------------------------------------


def page(site: Site, params: Mapping[str, str]) -> str:
    """`/life`: the chapter, the goals, the timeline in the view the address asks for, the chapters not
    yet placed, and the Volumes. `ValueError` for an address no view reads (a 400)."""
    today = day_start.of(site.lb.meta).today(site.now()).isoformat()
    rec = read(site, today)
    b = bounds(site.lb.meta, rec.first_day, today)
    v = view(params, today, b)
    parts = [
        '<div class="door-life">\n<h1>Life</h1>\n<div class="top">\n',
        _chapter_html(site, rec),
        _goals_html(rec),
        "</div>\n",
        _timeline_html(site, rec, b, v),
        _unplaced_html(rec),
        _volumes_html(site, rec),
        "</div>\n",
    ]
    return site.document("Life", "".join(parts), style=STYLE)


def _a(site: Site, inner: str, path: str, cls: str = "", title: str = "", style: str = "") -> str:
    """`inner` (already escaped) as a link to `path`, or a span where the site has no page there (an
    exported site); `title` names it on hover and to a screen reader when it has no words of its own."""
    href = site.href(path)
    attrs = (f' class="{cls}"' if cls else "") + (f' style="{style}"' if style else "")
    if title:
        attrs += f' title="{escape(title)}"' + ("" if inner else f' aria-label="{escape(title)}"')
    if href is None:
        return f"<span{attrs}>{inner}</span>"
    return f'<a href="{escape(href)}"{attrs}>{inner}</a>'


def _life(query: str) -> str:
    return f"/life?{query}" if query else "/life"


def _tier_words(site: Site) -> str:
    tiers = ", ".join(str(t) for t in sorted(site.tiers or ())) or "none"
    return (
        f"Your chapters and goals are your own words, tier {goals.TIER}; this page reads tier {tiers} only."
    )


def _chapter_html(site: Site, rec: Record) -> str:
    out = ['<section class="card chapter">\n']
    if rec.shelf is None:
        out.append(f'<p class="label">This chapter</p>\n<p class="empty">{escape(_tier_words(site))}</p>\n')
        return "".join(out) + "</section>\n"
    c = rec.shelf.chapter
    if c is None:
        said = "No chapter yet." if not rec.shelf.chapters else "No chapter holds today."
        out.append(
            f'<p class="label">This chapter</p>\n<p class="empty">{said} Name one with'
            f" <code>{escape(CHAPTER_COMMAND)}</code> and it opens your Life.</p>\n"
        )
        return "".join(out) + "</section>\n"
    out.append(f'<p class="label">This chapter · since {escape(words(c.start, rec.today))}</p>\n')
    out.append(f'<h2 class="ink">{escape(c.name)}</h2>\n')
    if c.rules:
        out.append(f'<p class="ink rules">{escape(c.rules)}</p>\n')
    if rec.draft is not None:
        text, model = rec.draft
        out.append(
            f'<p class="pencil" title="{escape(f"A draft by {model}, not your words")}">{escape(text)}</p>\n'
        )
    return "".join(out) + "</section>\n"


def _goals_html(rec: Record) -> str:
    year = rec.today[:4]
    out = ['<section class="card goals">\n', f'<p class="label">Goals for {year}</p>\n']
    if rec.shelf is None:
        out.append(f'<p class="empty">Goals are your own words too, tier {goals.TIER}.</p>\n')
        return "".join(out) + "</section>\n"
    standing = [g for g in rec.shelf.goals if g.state != goals.SUPERSEDED]
    held_ = [
        g
        for g in standing
        if g.horizon in (goals.YEAR, goals.QUARTER)
        and g.start <= f"{year}-12-31"
        and (g.until is None or g.until >= f"{year}-01-01")
    ]
    life = [g for g in standing if g.horizon == goals.LIFE]
    if not held_ and not life:
        out.append(
            f'<p class="empty">No goals yet. Write one with <code>{escape(GOAL_COMMAND)}</code> and it is'
            " here, with its last review.</p>\n"
        )
        return "".join(out) + "</section>\n"
    out.append(_goal_list(held_, rec) if held_ else f'<p class="empty">None for {year} yet.</p>\n')
    if life:
        out.append('<p class="label">For life</p>\n')
        out.append(_goal_list(life, rec))
    shown = {g.line for g in [*held_, *life]}
    coming = sorted(d for g, d in rec.revisits.items() if g in shown and d >= rec.today)
    if coming:
        out.append(f'<p class="prov">Next look: {escape(words(coming[0], rec.today))}</p>\n')
    return "".join(out) + "</section>\n"


def _goal_list(found: Sequence[shelf_goals.Goal], rec: Record) -> str:
    ordered = [g for g in found if g.state == "open"] + [g for g in found if g.state != "open"]
    out = ['<ol class="goals">\n']
    for g in ordered:
        if g.review is not None:
            said = f"Reviewed {words(g.review.day, rec.today)}, {g.review.disposition}"
        elif g.state == "past" and g.until:
            said = f"Its time ended {words(g.until, rec.today)}"
        else:
            said = f"Since {words(g.start, rec.today)}, not reviewed yet"
        note = (
            f'<p class="ink goal-note">{escape(g.review.note)}</p>\n'
            if g.review is not None and g.review.note
            else ""
        )
        out.append(
            f'<li><p class="goal ink">{escape(g.text)}</p>\n<p class="prov">{escape(said)}</p>\n{note}</li>\n'
        )
    return "".join(out) + "</ol>\n"


def _timeline_html(site: Site, rec: Record, b: Bounds, v: View) -> str:
    out = [
        '<section class="timeline">\n',
        f"<h2>Your life, {b.first[:4]} to {b.last[:4]}</h2>\n",
    ]
    if b.problem:
        out.append(
            f'<p class="problem">{escape(b.problem)}; the line runs from the first day of the record to the'
            " end of next year.</p>\n"
        )
    out.append('<nav class="zoom" aria-label="Zoom">\n')
    for zoom, query in tabs(v):
        name = ZOOM_NAMES[zoom]
        if zoom == v.zoom:
            out.append(f'<span aria-current="page">{name}</span>\n')
        else:
            out.append(_a(site, name, _life(query)) + "\n")
    earlier, later = moves(v, b)
    out.append('<span class="moves">')
    for found, word, arrow in ((earlier, "Earlier", "← Earlier"), (later, "Later", "Later →")):
        if found is None:
            out.append(f'<span class="pill off" aria-disabled="true">{escape(arrow)}</span>')
        else:
            out.append(_a(site, escape(arrow), _life(found[0]), title=f"{word}: {found[1]}"))
    out.append("</span>\n</nav>\n")
    if rec.first_day is None:
        out.append(
            '<p class="empty">Nothing on the line yet. Days appear here once a source sends its first line:'
            " <code>logbook add</code> a file, or <code>logbook sync</code> a source.</p>\n"
        )
        return "".join(out) + "</section>\n"
    if v.zoom == LIFE:
        out.append(_life_html(site, rec, b))
    elif v.zoom == YEAR:
        out.append(_year_html(site, rec, v))
    elif v.zoom == MONTH:
        out.append(_month_html(site, rec, v))
    elif v.zoom == WEEK:
        out.append(_week_html(site, rec, v))
    elif v.zoom == TRIP:
        out.append(_trip_html(site, rec, v))
    else:
        out.append(_days_html(site, rec, v))
    return "".join(out) + "</section>\n"


class _Scale:
    """Where a day falls across a window, in per cent of its width."""

    def __init__(self, first: str, last: str):
        self.first = date.fromisoformat(first)
        self.days = (date.fromisoformat(last) - self.first).days + 1

    def x(self, day: str) -> float:
        return max(0.0, min(100.0, (date.fromisoformat(day) - self.first).days / self.days * 100))

    def width(self, first: str, last: str) -> float:
        """From the start of `first` to the end of `last`."""
        return max(0.0, min(100.0, self.x(last) + 100 / self.days) - self.x(first))


def _pos(left: float, top: float, width: float | None = None, height: float | None = None) -> str:
    style = f"left:{left:.3f}%;top:{top:g}px"
    if width is not None:
        style += f";width:{width:.3f}%"
    if height is not None:
        style += f";height:{height:g}px"
    return style


class _Lanes:
    """Rows of labels: a label takes the first row where it overlaps none already there."""

    def __init__(self, rows: int, canvas_px: int = CANVAS_PX):
        self.taken: list[list[tuple[float, float]]] = [[] for _ in range(rows)]
        self.canvas_px = canvas_px

    def width(self, text: str) -> float:
        return (len(text) * CHAR_PX + LABEL_PX) / self.canvas_px * 100

    def place(self, left: float, right: float) -> int | None:
        for row, taken in enumerate(self.taken):
            if all(right <= a or left >= z for a, z in taken):
                taken.append((left, right))
                return row
        return None


def _clip(text: str, most: int = 34) -> str:
    return text if len(text) <= most else text[: most - 1].rstrip() + "…"


def _record_line(
    site: Site, rec: Record, scale: _Scale, first: str, last: str, top: int, at_least: int
) -> str:
    """The record as one line across `[first, last]`: dotted before its first day, ink where it holds
    lines, a lighter gap where it is silent `at_least` days or more, lighter again ahead of today."""
    today = rec.today
    out: list[str] = []
    start = max(rec.first_day or today, first)
    end = min(today, last)
    if start > first:
        before = min(start, last)
        width = scale.x(before) - scale.x(first) if start <= last else 100.0
        out.append(
            f'<span class="seg before" title="Before the record" style="{_pos(0, top, width)}"></span>\n'
        )
    if start <= end:
        out.append(
            f'<span class="seg held" style="{_pos(scale.x(start), top, scale.width(start, end))}"></span>\n'
        )
        for a, z in silences(site, rec, start, end, at_least):
            title = f"Nothing in the record {_span_words(a, z, today)}"
            out.append(
                f'<span class="seg silence" title="{escape(title)}"'
                f' style="{_pos(scale.x(a), top, scale.width(a, z))}"></span>\n'
            )
    if today < last:
        left = scale.x(today) + 100 / scale.days if today >= first else 0.0
        out.append(f'<span class="seg ahead" style="{_pos(left, top, max(0.0, 100 - left))}"></span>\n')
    return "".join(out)


def _life_html(site: Site, rec: Record, b: Bounds) -> str:
    """One line across the bounds: before the record, the record with its silences, ahead; the year
    ticks; the chapters as bands, the named trips as spans, the starred reflections and the first
    signed day as ticks; NOW; and at most `LABELS_MOST` labels in `LANES` rows above."""
    scale = _Scale(b.first, b.last)
    today = rec.today
    lane_px, line_top = 44, LANES * 44 + 24
    out = [f'<div class="box"><div class="canvas life" style="height:{line_top + 96}px">\n']
    out.append(_record_line(site, rec, scale, b.first, b.last, line_top, SILENT_LIFE))
    first_year = int(b.first[:4])
    for year in range(first_year + (-first_year % TICK_YEARS), int(b.last[:4]) + 1, TICK_YEARS):
        day = f"{year}-01-01"
        if b.first <= day <= b.last:
            out.append(f'<span class="year-tick" style="{_pos(scale.x(day), line_top + 34)}">{year}</span>\n')
    labels: list[tuple[float, str, str, str]] = []  # left, text, path, title
    if rec.shelf is not None:
        for c in rec.shelf.chapters:
            a, z = max(c.start, b.first), min(c.to or today, b.last)
            if z < a:
                continue
            title = (
                f"{c.name}, {_span_words(c.start, c.to, today) if c.to else 'since ' + words(c.start, today)}"
            )
            path = _life(f"zoom=year&at={a[:4]}")
            cls = "band chapter" + (" current" if c == rec.shelf.chapter else "")
            out.append(
                _a(site, "", path, cls, title, _pos(scale.x(a), line_top - 7, scale.width(a, z), 16)) + "\n"
            )
            labels.append((scale.x(a), c.name, path, title))
    for t in rec.named:
        if t.home < b.first or t.first > b.last:
            continue
        title = f"{t.label}, {_span_words(t.first, t.home, today)}"
        path = _life(t.query)
        out.append(
            _a(
                site,
                "",
                path,
                "span trip",
                title,
                _pos(scale.x(t.first), line_top - 20, scale.width(t.first, t.home)),
            )
            + "\n"
        )
        labels.append((scale.x(t.first), t.label, path, title))
    for s in rec.starred:
        if not b.first <= s.day <= b.last:
            continue
        title = f"A reflection you starred, on a day you signed, {words(s.day, today)}"
        out.append(
            _a(site, "", f"/day/{s.day}", "tick reflection", title, _pos(scale.x(s.day), line_top + 2)) + "\n"
        )
        labels.append((scale.x(s.day), _clip(s.text), f"/day/{s.day}", title))
    if rec.signed and b.first <= rec.signed[0] <= b.last:
        day = rec.signed[0]
        title = f"First signed day, {weekday(day)} {words(day, today)}"
        out.append(_a(site, "", f"/day/{day}", "tick signed", title, _pos(scale.x(day), line_top + 2)) + "\n")
        labels.append((scale.x(day), "First signed day", f"/day/{day}", title))
    if today < b.last:
        after = scale.x(max(today, b.first))
        out.append(f'<span class="ahead" style="{_pos(after, 0, 100 - after, line_top + 40)}"></span>\n')
    if b.first <= today <= b.last:
        x = scale.x(today)
        out.append(f'<span class="now" style="{_pos(x, line_top - 30, None, 62)}"></span>\n')
        out.append(f'<span class="now-label" style="{_pos(x, line_top + 58)}">NOW</span>\n')
    if today < b.last:
        out.append(
            f'<span class="ahead-label" style="{_pos(scale.x(max(today, b.first)), line_top + 58)}">'
            "AHEAD</span>\n"
        )
    lanes = _Lanes(LANES)
    shown = 0
    for left, text, path, title in labels:
        if shown >= LABELS_MOST:
            break
        width = lanes.width(text)
        left = min(left, max(0.0, 100 - width))
        row = lanes.place(left, left + width)
        if row is None:
            continue
        shown += 1
        out.append(_a(site, escape(text), path, "label", title, _pos(left, row * lane_px)) + "\n")
    return "".join(out) + "</div></div>\n"


def _year_html(site: Site, rec: Record, v: View) -> str:
    """Twelve months: the chapters, the trips as spans with their names, the signed days as dots, the
    starred reflections as rings, the silences, NOW and what is ahead."""
    scale = _Scale(v.first, v.last)
    today, year = rec.today, int(v.first[:4])
    rows: list[str] = []
    for m in range(1, 13):
        first = date(year, m, 1).isoformat()
        last = date(year, m, _month_days(date(year, m, 1))).isoformat()
        rows.append(
            _a(
                site,
                escape(MONTHS[m - 1][:3]),
                _life(f"zoom=month&at={first[:7]}"),
                "month",
                f"{MONTHS[m - 1]} {year}",
                _pos(scale.x(first), 0, scale.width(first, last)),
            )
            + "\n"
        )
    top = 52
    body: list[str] = []
    if rec.shelf is not None:
        found = [c for c in rec.shelf.chapters if c.start <= v.last and (c.to or today) >= v.first]
        if found:
            lanes = _Lanes(1)
            for c in found:
                a, z = max(c.start, v.first), min(c.to or today, v.last)
                if z < a:
                    continue
                title = f"{c.name}, {_chapter_words(c, today)}"
                path = _life(f"zoom=month&at={a[:7]}")
                cls = "band chapter" + (" current" if c == rec.shelf.chapter else "")
                width = lanes.width(c.name)
                if lanes.place(scale.x(a), scale.x(a) + width) is not None:
                    body.append(_a(site, escape(c.name), path, "label", title, _pos(scale.x(a), top)) + "\n")
                body.append(
                    _a(site, "", path, cls, title, _pos(scale.x(a), top + 40, scale.width(a, z), 10)) + "\n"
                )
            top += 60
    found_trips = trips_of(site, rec, v)
    if found_trips:
        lanes = _Lanes(len(found_trips))
        rows_used = 0
        for t in found_trips:
            a, z = max(t.first, v.first), min(t.home, v.last)
            left, width = scale.x(a), scale.width(a, z)
            row = lanes.place(left, max(left + width, left + lanes.width(t.label)))
            row = row if row is not None else 0
            rows_used = max(rows_used, row + 1)
            title = f"{t.label}, {_span_words(t.first, t.home, today)}"
            path = _life(t.query)
            y = top + row * 56
            body.append(_a(site, escape(t.label), path, "label", title, _pos(left, y)) + "\n")
            body.append(_a(site, "", path, "span trip", title, _pos(left, y + 40, width)) + "\n")
        top += rows_used * 56 + 8
    signed = [d for d in rec.signed if v.first <= d <= v.last]
    starred = [s for s in rec.starred if v.first <= s.day <= v.last]
    if signed or starred:
        if rec.signed and v.first <= rec.signed[0] <= v.last:
            day = rec.signed[0]
            title = f"First signed day, {weekday(day)} {words(day, today)}"
            body.append(
                _a(site, "First signed day", f"/day/{day}", "label", title, _pos(scale.x(day), top)) + "\n"
            )
        for d in signed:
            title = f"Signed, {weekday(d)} {words(d, today)}"
            body.append(
                _a(site, "", f"/day/{d}", "dot signed", title, _pos(scale.x(d) + 50 / scale.days, top + 36))
                + "\n"
            )
        for s in starred:
            title = f"A reflection you starred, {weekday(s.day)} {words(s.day, today)}"
            body.append(
                _a(
                    site,
                    "",
                    f"/day/{s.day}",
                    "dot reflection",
                    title,
                    _pos(scale.x(s.day) + 50 / scale.days, top + 58),
                )
                + "\n"
            )
        top += 104
    body.append(_record_line(site, rec, scale, v.first, v.last, top + 12, SILENT_YEAR))
    top += 28
    height = top + 30
    if v.first <= today <= v.last:
        x = scale.x(today) + 50 / scale.days
        if today < v.last:
            after = scale.x(today) + 100 / scale.days
            body.append(f'<span class="ahead" style="{_pos(after, 44, 100 - after, height - 44)}"></span>\n')
            body.append(f'<span class="ahead-label" style="{_pos(x, top + 4)}">AHEAD</span>\n')
        body.append(f'<span class="now" style="{_pos(x, 44, None, top - 44)}"></span>\n')
        body.append(f'<span class="now-label" style="{_pos(x, top + 4)}">NOW</span>\n')
    elif v.first > today:
        body.append(f'<span class="ahead" style="{_pos(0, 44, 100, height - 44)}"></span>\n')
        body.append(f'<span class="ahead-label" style="{_pos(1, top + 4)}">AHEAD</span>\n')
    rules = "".join(
        f'<span class="rule" style="{_pos(scale.x(date(year, m, 1).isoformat()), 0, None, height)}"></span>\n'
        for m in range(2, 13)
    )
    return (
        f'<div class="box"><div class="canvas year" style="height:{height}px">\n'
        f"{rules}{''.join(rows)}{''.join(body)}</div></div>\n"
    )


@dataclass(frozen=True)
class _Day:
    """What a day of the Month, the Week and the Day zooms carries."""

    day: str
    signed: bool
    starred: Starred | None
    trips: tuple[Trip, ...]
    begins: tuple[str, ...]  # the chapters that begin on it
    silent: bool
    ahead: bool
    before: bool


def _marked(site: Site, rec: Record, first: str, last: str, found_trips: Sequence[Trip]) -> list[_Day]:
    signed = set(rec.signed)
    starred = {s.day: s for s in rec.starred}
    begins: dict[str, list[str]] = {}
    for c in rec.shelf.chapters if rec.shelf is not None else ():
        begins.setdefault(c.start, []).append(c.name)
    days_held = held(site, first, last, rec.today)
    out = []
    for d in _days(first, last):
        before = rec.first_day is None or d < rec.first_day
        ahead = d > rec.today
        out.append(
            _Day(
                d,
                d in signed,
                starred.get(d),
                tuple(t for t in found_trips if t.first <= d <= t.home),
                tuple(begins.get(d, ())),
                not before and not ahead and d not in days_held,
                ahead,
                before,
            )
        )
    return out


def _flags(d: _Day, today: str, month: str | None = None) -> str:
    flags = [
        name
        for name, on in (
            ("signed", d.signed),
            ("away", bool(d.trips)),
            ("silent", d.silent),
            ("ahead", d.ahead),
            ("before", d.before),
            ("today", d.day == today),
            ("out", month is not None and d.day[:7] != month),
        )
        if on
    ]
    return " ".join(flags)


def _state_words(d: _Day) -> list[str]:
    """The day's facts in words, for a title: never a name, never a count."""
    said = []
    if d.signed:
        said.append("signed")
    if d.starred is not None:
        said.append("a reflection you starred")
    if d.trips:
        said.append("away")
    if d.begins:
        said.append("a chapter begins")
    if d.silent:
        said.append("nothing in the record")
    if d.before:
        said.append("before the record")
    if d.ahead:
        said.append("ahead")
    return said


def _this_html(site: Site, rec: Record, marked: Sequence[_Day], found_trips: Sequence[Trip]) -> str:
    """What the window holds, one row each, every name after its kind and before its days."""
    today = rec.today

    def row(kind: str, link: str, said: str) -> str:
        return (
            f'<li><span class="k">{kind}</span><span class="v">{link}'
            f' <span class="prov">{escape(said)}</span></span></li>\n'
        )

    rows = [
        row(
            "Chapter",
            _a(site, escape(name), _life(f"zoom=year&at={d.day[:4]}")),
            f"from {words(d.day, today)}",
        )
        for d in marked
        for name in d.begins
    ]
    rows += [
        row("Trip", _a(site, escape(t.label), _life(t.query)), _span_words(t.first, t.home, today))
        for t in found_trips
    ]
    if rec.signed and any(d.day == rec.signed[0] for d in marked):
        day = rec.signed[0]
        rows.append(row("Signed", _a(site, "First signed day", f"/day/{day}"), f"on {words(day, today)}"))
    rows += [
        row(
            "Starred",
            _a(site, escape(_clip(d.starred.text, 60)), f"/day/{d.day}", "ink"),
            f"on {words(d.day, today)}",
        )
        for d in marked
        if d.starred is not None
    ]
    if not rows:
        return ""
    return f'<ul class="this">\n{"".join(rows)}</ul>\n'


def _named_here(t: Trip, d: _Day, first: str) -> bool:
    """A trip is named on its first day in the window, and is "away" on the rest."""
    return d.day == max(t.first, first)


def _month_html(site: Site, rec: Record, v: View) -> str:
    """The month's weeks, Monday first, each a link to its week page and each day to its Day."""
    first, last = date.fromisoformat(v.first), date.fromisoformat(v.last)
    monday = first - timedelta(days=first.weekday())
    sunday = last + timedelta(days=6 - last.weekday())
    found_trips = trips_of(site, rec, v)
    marked = _marked(site, rec, monday.isoformat(), sunday.isoformat(), found_trips)
    out = [
        f'<p class="label">{escape(MONTHS[first.month - 1])} {first.year}</p>\n',
        '<div class="box calendar"><div class="weeks">\n<span class="h week">Week</span>',
        "".join(f'<span class="h">{w[:3].upper()}</span>' for w in WEEKDAYS),
        "\n",
    ]
    for n in range(0, len(marked), 7):
        week = marked[n : n + 7]
        wk = week_of(week[0].day)
        out.append(_a(site, escape(f"Week {int(wk[-2:])}"), f"/week/{wk}", "wk", "The week page"))
        for d in week:
            said = _state_words(d)
            title = f"{weekday(d.day)} {words(d.day, rec.today)}" + (f": {', '.join(said)}" if said else "")
            marks = "".join(
                f'<i class="m {cls}"></i>'
                for cls, on in (
                    ("signed", d.signed),
                    ("reflection", d.starred is not None),
                    ("chapter", bool(d.begins)),
                )
                if on
            )
            inner = f'<span class="n">{date.fromisoformat(d.day).day}</span>' + (
                f'<span class="marks">{marks}</span>' if marks else ""
            )
            out.append(
                _a(site, inner, f"/day/{d.day}", f"cell {_flags(d, rec.today, v.first[:7])}".strip(), title)
            )
        out.append("\n")
    out.append("</div></div>\n")
    out.append(_this_html(site, rec, [d for d in marked if d.day[:7] == v.first[:7]], found_trips))
    return "".join(out)


def _marks_list(site: Site, d: _Day, first: str) -> str:
    items: list[str] = []
    if d.signed:
        items.append('<li class="ink">Signed</li>')
    for name in d.begins:
        items.append(f'<li>Chapter begins: <span class="ink">{escape(name)}</span></li>')
    for t in d.trips:
        if _named_here(t, d, first):
            items.append(f"<li>{_a(site, escape(t.label), _life(t.query))}</li>")
        else:
            items.append(f'<li class="quiet">{_a(site, "Away", _life(t.query))}</li>')
    if d.starred is not None:
        items.append(f"<li>{_a(site, 'A reflection you starred', f'/day/{d.day}')}</li>")
    if d.silent:
        items.append('<li class="quiet">Nothing in the record</li>')
    if d.before:
        items.append('<li class="quiet">Before the record</li>')
    if d.ahead:
        items.append('<li class="quiet">Ahead</li>')
    return f'<ul class="marks">{"".join(items)}</ul>' if items else ""


def _week_html(site: Site, rec: Record, v: View) -> str:
    """The week's seven days, each with what it holds and a link to its Day; above, its week page."""
    found_trips = trips_of(site, rec, v)
    marked = _marked(site, rec, v.first, v.last, found_trips)
    wk = week_of(v.first)
    out = [
        f'<p class="label">Week {int(wk[-2:])} · {escape(_range(v.first, v.last, rec.today))}</p>\n',
        f"<p>{_a(site, 'Open the week page', f'/week/{wk}', 'pill')}</p>\n",
        '<div class="box"><div class="sevens">\n',
    ]
    for d in marked:
        out.append(
            f'<div class="wday {_flags(d, rec.today)}"><p class="label">{weekday(d.day)[:3]}</p>'
            f"{_a(site, escape(words(d.day, rec.today)), f'/day/{d.day}', 'date')}"
            f"{_marks_list(site, d, v.first)}</div>\n"
        )
    out.append("</div></div>\n")
    return "".join(out)


def _days_html(site: Site, rec: Record, v: View, label: str | None = None) -> str:
    """One row a day, each a link to its Day with what it holds."""
    found_trips = trips_of(site, rec, v)
    marked = _marked(site, rec, v.first, v.last, found_trips)
    out = [] if label is None else [label]
    if label is None:
        out.append(f'<p class="label">{escape(_range(v.first, v.last, rec.today))}</p>\n')
    out.append('<div class="box"><ol class="days">\n')
    for d in marked:
        year = "" if d.day[:4] == rec.today[:4] else f'<span class="yr">{d.day[:4]}</span>'
        marks: list[str] = []
        if d.signed:
            marks.append('<span class="ink">Signed</span>')
        for name in d.begins:
            marks.append(f'Chapter begins: <span class="ink">{escape(name)}</span>')
        for t in d.trips:
            named = _named_here(t, d, v.first)
            marks.append(
                _a(site, escape(t.label) if named else "Away", _life(t.query), "ink" if named else "")
            )
        if d.starred is not None:
            marks.append(_a(site, "A reflection you starred", f"/day/{d.day}"))
        marks += [
            w.capitalize()
            for w, on in (
                ("nothing in the record", d.silent),
                ("before the record", d.before),
                ("ahead", d.ahead),
            )
            if on
        ]
        dated = (
            f"{weekday(d.day)} {date.fromisoformat(d.day).day} {MONTHS[date.fromisoformat(d.day).month - 1]}"
        )
        out.append(
            f'<li class="{_flags(d, rec.today)}">{year}{_a(site, escape(dated), f"/day/{d.day}", "date")}'
            f'<span class="marks">{" · ".join(marks)}</span></li>\n'
        )
    out.append("</ol></div>\n")
    return "".join(out)


def _trip_html(site: Site, rec: Record, v: View) -> str:
    assert v.trip is not None
    first, last = v.trip
    found = next(
        (
            t
            for t in trips_of(site, rec, View(DAY, first, first, last))
            if t.first == first and t.last == last
        ),
        None,
    )
    named = next((t for t in rec.named if t.first == first and t.last == last), None)
    home = found.home if found is not None else (date.fromisoformat(last) + timedelta(days=1)).isoformat()
    label = found.label if found is not None else named.label if named is not None else "These days"
    head = (
        f'<div class="trip-head"><p class="label">Trip</p><h3 class="ink">{escape(label)}</h3>'
        f'<p class="prov">{escape(_span_words(first, home, rec.today))}</p>'
        f"<p>{_a(site, 'Open the journey', f'/journeys/{first}/{last}', 'pill')}</p></div>\n"
    )
    return _days_html(site, rec, View(TRIP, first, first, home, v.trip), head)


def _unplaced_html(rec: Record) -> str:
    if not rec.undated:
        return ""
    return (
        '<section class="unplaced">\n<p class="label">Not yet placed</p>\n'
        f'<p class="names ink">{escape(", ".join(rec.undated))}</p>\n'
        '<p class="prov">A chapter with no first day. Date one with'
        f" <code>{escape(CHAPTER_COMMAND)}</code>.</p>\n"
        "</section>\n"
    )


def _volumes_html(site: Site, rec: Record) -> str:
    if rec.first_day is None:
        years: list[int] = []
    else:
        years = list(range(int(rec.first_day[:4]), int(rec.today[:4]) + 1))
    out = ['<section class="volumes">\n', f'<p class="lede">{escape(VOLUMES_LINE)}</p>\n']
    if not years:
        out.append('<p class="empty">The first volume begins with the record\'s first day.</p>\n')
        return "".join(out) + "</section>\n"
    out.append('<ol class="spines">\n')
    for year in years:
        current = str(year) == rec.today[:4]
        text = f"{year}, being written" if current else str(year)
        path = f"/days?from={year}-01-01&to={year}-12-31"
        out.append(f"<li>{_a(site, escape(text), path, 'spine current' if current else 'spine')}</li>\n")
    return "".join(out) + "</ol>\n</section>\n"
