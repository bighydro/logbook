"""Today, the Library's front door (RFC 0047 §4.1): `/`, what the owner reads at 07:00, on a phone first.

From the top:

1. **The date and where.** The day in words, a link to its Day; the place the night was spent (the
   night after yesterday, as the Day's header says it, `day.of_reading`); the weather when the record
   holds a weather line for the day there.
2. **What's open** (`OPEN_MOST` at most, the oldest first, each a link to its moment): the promises
   both ways that are still open, said in the fortnight before today and on it (`open_promises`, the
   Day's morning reading of them, `day_rhythm.promises_near`, so a promise years old never fills
   the list), in pencil, since the rules read them and the owner has not
   confirmed them; the
   plan's tasks for the day from the task tool, read and never run (`day_rhythm.plan_of`, RFC 0043
   §9), tier 1 alone; the replies the day owes (`day_rhythm.replies_owed`). Who it is with and since
   when are words, never a date or a count beside a name. What does not fit is one link to the
   Promises shelf.
3. **One memory**: this day a year ago when it holds something worth showing, else the nearest year
   back that does (`memory`): a starred photo, a signed reflection or a trip (a night away from home,
   or a flight). One, never a list, a link to that Day (Life's moment, until Life is built); its
   reflection's first sentence in ink, its starred photo's thumbnail when the store holds it.
4. **Reflect and sign**: the Day's own two forms (`Site._close_html`), posting to the Day's
   addresses, written by the Day's code.

Every part with nothing in it says what fills it, in one sentence (RFC 0047 §3.7).

Speed (RFC 0047 §3.6, §8): nothing here reads the whole record while the browser waits. The date reads
the day before (`reading.read`, one day), the memory a handful of days by the index and at most
`MEMORY_READS` of them in full, the promises the fortnight's (`day_rhythm.promises_near`); each is
kept for the record as it stands (`Site._day_reading`), the promises under the key today's Day keeps
them by. The plan and the replies owed read beyond the day, and are the same readings the Day's
morning reads, by the same keys (`Site._day_later`): on `logbook serve` they are read off the request,
and until they have arrived the page says so in one sentence and the next visit has them (its tag
names what has arrived). A test or a build reads them on the request.

An exported site (`export site`, `site.static`) has no clock: its Today is the record's last day (its
last day with a line it sends that observes one, `reading.record_span` through the site's tiers, so
the export's own crossing line does not move it, nor a line held back), with no form, no Ask and no
font."""

from __future__ import annotations

import calendar
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from html import escape
from typing import TYPE_CHECKING, Any

from ..core import day as day_reader
from ..core import day_start, keepers, notes, people, reading, signing, stars, weather
from ..core.store import retractions
from . import day_rhythm, doors, plan, promises, reflect, shelf_promises

if TYPE_CHECKING:  # the Site passes itself; serve imports this module, never the other way at import
    from ..core.chain import Line
    from ..core.flights import Airports
    from ..core.store import Logbook
    from .serve import Site

OPEN_MOST = 7  # what's open: this many rows at most, the oldest first
MEMORY_READS = 3  # the days back a memory reads in full looking for a night away, at most
MEMORY_YEARS = 120  # the years back a memory looks, at most (and never before the record's first day)
DOT = day_rhythm.DOT
WEEK = day_rhythm.WEEK
MONTHS, WORDS = day_rhythm.MONTHS, day_rhythm.WORDS
EMPTY_OPEN = (
    "Nothing open: a promise appears here once a message or a note makes one, a task once sync notion"
    " reads the plan, and a reply owed once someone writes and waits."
)
PENCIL_PROMISE = "read as a promise by the rules: yours to confirm when you sign its day"
STILL_READING = "Still reading {what} beside this page: open it again in a moment and they are here."
STYLE = """
section.date{margin:0 0 2rem}
section.date p.eyebrow{margin:0 0 .3rem;color:var(--pencil);font-size:.75rem;font-weight:600;
letter-spacing:.12em;text-transform:uppercase}
section.date h1{margin:0;font-weight:400;font-size:2.6rem;line-height:1.05;font-family:var(--serif)}
section.date h1 a{text-decoration:none}
section.date p.where{margin:.45rem 0 0;color:var(--pencil);font-size:1rem}
main.door h2{margin:0 0 .6rem;color:var(--pencil);font-size:.75rem;font-weight:600;
letter-spacing:.12em;text-transform:uppercase}
section.open,section.memory{margin:0 0 2.2rem}
ul.open{list-style:none;margin:0;padding:0;border-top:1px solid var(--line)}
ul.open li{display:flex;gap:.9rem;padding:.75rem 0;border-bottom:1px solid var(--line-soft)}
ul.open span.mark{flex:0 0 .45rem;height:.45rem;margin-top:.55rem;border-radius:50%;
background:var(--pencil-rule)}
ul.open li.task span.mark{background:var(--ink)}
ul.open div{min-width:0;overflow-wrap:anywhere}
ul.open a.what{display:block;font-weight:400;font-size:1.2rem;line-height:1.3;font-family:var(--serif);
text-decoration:none}
ul.open a.what.pencil{color:var(--pencil);text-decoration:underline dotted var(--pencil-rule);
text-underline-offset:.22em}
ul.open span.sub{display:block;margin-top:.15rem;color:var(--pencil);font-size:.85rem}
ul.open li.more{display:block;color:var(--pencil);font-size:.85rem}
p.said{margin:0;color:var(--pencil)}
span.person{white-space:nowrap}
a.memory{display:block;padding:1.1rem 1.2rem;border-radius:14px;background:var(--card-dark);
color:var(--card-dark-text);text-decoration:none;overflow-wrap:anywhere}
a.memory img{display:block;width:100%;max-width:100%;height:auto;max-height:16rem;object-fit:cover;
border-radius:8px;margin:0 0 .9rem}
a.memory span{display:block}
a.memory span.when{font-weight:400;font-size:1.5rem;line-height:1.2;font-family:var(--serif)}
a.memory span.where{margin-top:.2rem;color:var(--card-dark-muted);font-size:.9rem}
a.memory span.words{margin-top:.7rem;font-style:italic;font-weight:400;font-size:1.15rem;line-height:1.4;
font-family:var(--serif)}
a.memory span.open{margin-top:.8rem;font-size:.85rem;color:var(--card-dark-muted)}
a.memory:hover span.when{text-decoration:underline;text-decoration-color:var(--signal)}
section.close{margin:2.5rem 0 0;padding:1.5rem 0 0;border-top:1px solid var(--line)}
section.close h2{margin:0 0 .6rem}
section.close p,section.close ul{font-size:.9rem;color:var(--pencil)}
section.close ul.signed{padding-left:1.1rem}
section.close textarea{display:block;width:100%;min-height:8rem;margin:.4rem 0 .6rem;padding:.7rem .8rem;
border:1px solid var(--line);border-radius:10px;background:var(--surface);
color:var(--ink);font-size:1.05rem;line-height:1.5;font-family:var(--serif)}
section.close button{min-height:44px;padding:0 1.2rem;border-radius:22px;border:1px solid var(--ink);
background:var(--ink);color:var(--paper);font-weight:600;font-size:.9rem;font-family:var(--sans);cursor:pointer}
section.close button[type=button]{background:transparent;color:var(--ink)}
section.close form{margin:0 0 1rem}
section.close label{display:block;font-size:.9rem;overflow-wrap:anywhere}
section.close input[type=file]{max-width:100%}
section.close ol.proposals{list-style:none;padding:0;margin:.3rem 0}
section.close ol.proposals li{padding:.4rem 0;border-bottom:1px solid var(--line-soft)}
section.close ol.proposals label{display:flex;gap:.6rem;align-items:baseline;color:var(--ink)}
section.close ol.proposals input{flex:none;width:1.1rem;height:1.1rem}
section.close details{margin:.4rem 0;font-size:.9rem}
section.close code{font-family:var(--mono);font-size:.85em;overflow-wrap:anywhere}
@media (max-width:40rem){section.date h1{font-size:2.2rem}}
"""


@dataclass(frozen=True)
class Row:
    """One row of what's open: the local day it is from (the order), its kind and its markup."""

    day: str
    rank: int  # the order on one day: a promise, then a reply owed, then a task
    kind: str
    html: str


def page_today(site: Site) -> str:
    """`/`: Today, in the doors' frame (`doors.page`)."""
    lb = site.lb
    if site.static:
        whole = reading.record_span(lb, site.tiers)  # the last day a line the site sends is on
        today = whole[1] if whole is not None else day_start.of(lb.meta).today(site.now()).isoformat()
    else:
        today = day_start.of(lb.meta).today(site.now()).isoformat()
    parts = [date_html(site, today), open_html(site, today), memory_html(site, today)]
    script = None
    if not site.static:
        closing, records = site._close_html(today, "Reflect and sign")
        parts.append(closing)
        from .serve import DAY_SCRIPT  # the Day's record button: serve imports this module at import

        script = DAY_SCRIPT if records else None
    site._day_later_start()  # what the page asked to read beside it, once it is rendered
    return doors.page(site, doors.TODAY, "Today", "".join(parts), style_=STYLE, script=script)


# -- the date and where ----------------------------------------------------------------------------------


def day_words(day: str, year: bool = False) -> str:
    """`Friday 19 June`, with the year when asked: the day in words."""
    d = date.fromisoformat(day)
    said = f"{day_reader.WEEKDAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"
    return f"{said} {d.year}" if year else said


def last_night(lb: Logbook, day: str, airports: Airports, tiers: Sequence[int] | None) -> dict[str, Any]:
    """The night before `day` as the Day's header says a night (`day.of_reading`'s `nights`): the night
    after the day before, from a reading of that one day."""
    before = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    rd = reading.read(lb, before, before, airports, tiers)
    night: dict[str, Any] = day_reader.of_reading(rd, before, None)["nights"]["after"]
    return night


def weather_of(lb: Logbook, day: str, night: Mapping[str, Any], tiers: Sequence[int] | None) -> str:
    """`14° · rain` for `day` at the place of the night, when the record holds a weather line for it."""
    before = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    with lb.index() as idx:
        lines = reading.crossing(idx.by_kind(weather.KIND, before, day), tiers)
    position = night.get("position")
    at = None if not position else (float(position["lat"]), float(position["lon"]))
    row = weather.day_row(weather.by_day(lines).get(day, []), at)
    return weather.short_text(row) if row is not None else ""


def date_html(site: Site, today: str) -> str:
    night = site._day_reading(
        ("today-night", today), lambda: last_night(site.lb, today, site.airports, site.tiers)
    )
    said = site._day_reading(("today-weather", today), lambda: weather_of(site.lb, today, night, site.tiers))
    if night["in_transit"]:
        where = "Last night in transit"
    elif night["where"] is None:
        where = "No place the record knows for last night"
    else:
        where = f"Last night at {night['where']}" + ("" if night["home"] else ", away from home")
    line = DOT.join(x for x in (where, said) if x)
    # an exported site's Today is its last day, which may be any year: the year is said there
    words = day_words(today, year=site.static)
    eyebrow = '<p class="eyebrow">The last day in the record</p>\n' if site.static else ""
    return (
        '<section class="date">\n'
        f"{eyebrow}<h1>{site.link(escape(words), f'/day/{today}')}</h1>\n"
        f'<p class="where">{escape(line)}</p>\n'
        "</section>\n"
    )


# -- what's open -------------------------------------------------------------------------------------------


def since(then: str, today: str) -> str:
    """When something began: `today`, `since yesterday`, `since Tuesday` within the week, else the date,
    `since Mon 8 June`, with its year when it is not this one, `since Wed 3 June 2026`. A row says it
    last, after the person and the words (*Kari Nordmann promised you · since Sun 8 June 2025*), so a
    date never stands beside a name."""
    a, b = date.fromisoformat(then), date.fromisoformat(today)
    gap = (b - a).days
    weekday = day_reader.WEEKDAYS[a.weekday()]
    if gap <= 0:
        return "today"
    if gap == 1:
        return "since yesterday"
    if gap < WEEK:
        return f"since {weekday}"
    said = f"since {weekday[:3]} {a.day} {MONTHS[a.month - 1]}"
    return said if a.year == b.year else f"{said} {a.year}"


def _person(name: str) -> str:
    return f'<span class="person">{escape(name)}</span>'


def open_promises(found: Sequence[promises.Proposal]) -> list[promises.Proposal]:
    """The promises both ways still open among `found`, the Day's morning reading of them
    (`day_rhythm.promises_near`: said in the `PROMISE_DAYS` before today and on it, through the gate), so
    a promise years old never fills Today; every one, whatever its age, is on the Promises shelf."""
    return [p for p in found if p.status == "open"]


def _with(p: promises.Proposal) -> str | None:
    """Whom a promise is with, as the record names them: its counterpart, else the one who spoke it when
    it was not the owner; None when the reader names nobody (a note's promise to someone it names)."""
    if p.counterpart:
        return p.counterpart
    if p.speaker is not None and not p.speaker.owner and p.speaker.label:
        return str(p.speaker.label)
    return None


def _promise_row(site: Site, p: promises.Proposal, today: str) -> Row:
    name = _with(p)
    named = name is not None
    who = _person(name) if name is not None else ""
    if p.direction == promises.OWED_TO_OWNER:
        said = f"{who} promised you" if named else "you were promised"
    elif p.role == promises.ASKED:
        said = f"{who} asked you" if named else "you were asked"
    else:
        said = f"you promised {who}" if named else "you promised"
    if p.kind == promises.NOTE and not named:
        said += ", in a note"
    href = site.href(shelf_promises.day_line(p.day, p.line))
    quote = f"“{escape(p.match.quote)}”"
    what = (
        f'<a class="what pencil" href="{escape(href)}" title="{escape(PENCIL_PROMISE)}">{quote}</a>'
        if href is not None
        else f'<span class="what pencil" title="{escape(PENCIL_PROMISE)}">{quote}</span>'
    )
    when = since(p.day, today)
    sub = f"{said}{DOT}{escape(when)}"
    return Row(p.day, 0, "promise", _li("promise", what, sub))


def _owed_row(site: Site, owed: Mapping[str, Any], today: str) -> Row:
    day = str(owed["day"])
    what = site.link("A reply owed", f"/day/{day}", "what")
    when = since(day, today)
    sub = f"{_person(str(owed.get('name') or ''))} wrote{DOT}{escape(when)}"
    return Row(day, 1, "owed", _li("owed", what, sub))


def _task_rows(site: Site, found: object, today: str) -> list[Row]:
    if not isinstance(found, plan.Plan) or not found.mapped or not found.tasks:
        return []
    out = []
    for t in found.tasks["rows"]:
        name = escape(str(t.get("title") or plan.UNTITLED))
        what = (
            site.link(name, f"/line/{t['line']}", "what")
            if t.get("line")
            else f'<span class="what">{name}</span>'
        )
        start = str((t.get("date") or {}).get("start") or "")[:10]
        day = start if t.get("overdue") and start else today
        said = ["from the plan", "carried from an earlier day" if t.get("overdue") else "for today"]
        if t.get("status"):
            said.insert(1, escape(str(t["status"])))
        out.append(Row(day, 2, "task", _li("task", what, DOT.join(said))))
    return out


def _li(kind: str, what: str, sub: str) -> str:
    return (
        f'<li class="{kind}"><span class="mark"></span><div>{what}<span class="sub">{sub}</span></div></li>\n'
    )


def open_html(site: Site, today: str) -> str:
    """What's open: the promises both ways, the replies owed and the plan's tasks, `OPEN_MOST` at most,
    the oldest first; what does not fit, one link to the Promises shelf."""
    lb, tiers = site.lb, site.tiers
    head = str(lb.meta.get("head"))
    waiting = []
    # the fortnight's promises, the reading today's Day keeps under the same key: one day's span of
    # lines, read on the request
    near = site._day_reading(("promises", today), lambda: day_rhythm.promises_near(lb, today, tiers))
    found_promises = open_promises(near)
    directory = site._day_reading(("directory",), lambda: people.directory(lb))
    owed = site._day_later(
        ("owed", today, head), lambda: day_rhythm.replies_owed(lb, today, directory, tiers)
    )
    if owed is None:
        waiting.append("the replies owed")
    found: object = None
    if tiers is None or 1 in tiers:
        found = site._day_later(("plan", today, head), lambda: day_rhythm.plan_of(lb, today))
        if found is None:
            waiting.append("the plan")
    rows: list[Row] = []
    rows += [_promise_row(site, p, today) for p in found_promises or () if p.day <= today]
    rows += [_owed_row(site, o, today) for o in owed or () if str(o["day"]) <= today]
    rows += _task_rows(site, found, today)
    rows.sort(key=lambda r: (r.day, r.rank))
    out = ['<section class="open">\n<h2>What\u2019s open</h2>\n']
    if rows:
        out.append('<ul class="open">\n')
        out += [r.html for r in rows[:OPEN_MOST]]
        rest = len(rows) - OPEN_MOST
        if rest > 0:
            shelf_link = site.link("the Promises shelf", "/promises")
            more = WORDS[rest] if rest < len(WORDS) else "many"
            out.append(
                f'<li class="more">{more.capitalize()} more, newer than these: every promise is on'
                f" {shelf_link}.</li>\n"
            )
        out.append("</ul>\n")
    elif not waiting:
        out.append(f'<p class="said">{escape(EMPTY_OPEN)}</p>\n')
    if waiting:
        what = ", ".join(waiting[:-1]) + (" and " if len(waiting) > 1 else "") + waiting[-1]
        out.append(f'<p class="said">{escape(STILL_READING.format(what=what))}</p>\n')
    out.append("</section>\n")
    return "".join(out)


# -- one memory ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Memory:
    """The one day back the morning shows, and why: what it holds worth showing."""

    years: int
    day: str
    where: str | None
    away: bool
    people: tuple[str, ...]
    starred: tuple[str, ...]  # the starred photos' line ids, the first the thumbnail
    said: str | None  # the first sentence of the day's reflection, when it has one
    signed: bool
    flight: bool


def same_day(day: str, years: int) -> str:
    """`day` so many years before; 29 February is the 28th in a year that has none."""
    d = date.fromisoformat(day)
    dom = 28 if (d.month, d.day) == (2, 29) and not calendar.isleap(d.year - years) else d.day
    return date(d.year - years, d.month, dom).isoformat()


def memory(lb: Logbook, today: str, airports: Airports, tiers: Sequence[int] | None) -> Memory | None:
    """The one memory (RFC 0047 §14.2, the owner's answer): exactly a year back first, whatever it
    holds; else the same date in the nearest earlier year that holds a signed reflection, a starred
    photo or a trip (a flight, or a night away); else None, and Today shows no card. The index says
    which years hold a line at all and what each holds of the first two and of flights; an earlier year
    that holds none of them is read in full for its night, `MEMORY_READS` of them at most."""
    whole = reading.record_span(lb, tiers)
    first = whole[0] if whole is not None else today
    owner = str(lb.meta.get("owner_id"))
    held: list[tuple[int, str, list[Line]]] = []
    with lb.index() as idx:
        retracted = retractions(idx.retractions())
        for years in range(1, MEMORY_YEARS + 1):
            then = same_day(today, years)
            if then < first:
                break
            if idx.source_days(then, then, tiers)[0] == 0:
                continue
            held.append((years, then, reading.crossing(idx.day(then), tiers)))
        reflected_on = any(notes.standing(on_day, notes.REFLECTION, retracted) for _y, _t, on_day in held)
        signed = signing.standing(idx, owner) if reflected_on else {}  # the signatures, when it matters
    if not held:
        return None
    reads = 0
    for years, then, on_day in held:
        by_id = {str(line["id"]): line for line in on_day}
        marks = [line for line in on_day if line.get("kind") in (stars.KIND, keepers.KIND)]
        shown = stars.shown(stars.standing(marks, retracted), by_id)
        starred = tuple(i for i in shown if (by_id.get(i) or {}).get("kind") == stars.PHOTO)
        reflected = notes.standing(on_day, notes.REFLECTION, retracted)
        is_signed = bool(reflected) and then in signed
        flight = any(line.get("kind") == "flight" and str(line["id"]) not in retracted for line in on_day)
        a_year_back = years == 1
        if not (a_year_back or starred or is_signed or flight) and reads >= MEMORY_READS:
            continue
        rd = reading.read(lb, then, then, airports, tiers)
        reads += 1
        data = day_reader.of_reading(rd, then, None)
        data["stated"] = day_reader.stated_of(on_day, retracted)
        night = data["nights"]["after"]
        away = not night["in_transit"] and night["where"] is not None and not night["home"]
        if not (a_year_back or starred or is_signed or flight or away):
            continue
        said = None
        if reflected:
            sentences = reflect.sentences(str((reflected[-1].get("payload") or {}).get("text") or ""))
            said = sentences[0] if sentences else None
        return Memory(
            years,
            then,
            None if night["in_transit"] else night["where"],
            away,
            tuple(str(c.get("name") or "") for c in day_reader.company_of_day(data) if c.get("name")),
            starred,
            said,
            is_signed,
            flight,
        )
    return None


def ago(years: int) -> str:
    """`A year ago today`, `Two years ago today`, `Thirteen years ago today` in words up to twelve."""
    if years == 1:
        return "A year ago today"
    said = WORDS[years].capitalize() if years < len(WORDS) else str(years)
    return f"{said} years ago today"


def memory_html(site: Site, today: str) -> str:
    found = site._day_reading(
        ("today-memory", today), lambda: memory(site.lb, today, site.airports, site.tiers)
    )
    if found is None:
        return ""
    bits = []
    if found.where:
        bits.append(f"the night at {found.where}" + (", away from home" if found.away else ""))
    if found.starred:
        bits.append("a starred photo" if len(found.starred) == 1 else "starred photos")
    if found.flight:
        bits.append("a flight")
    if found.people:
        bits.append("with " + ", ".join(found.people))
    thumbnail = ""
    if found.starred:
        marks = site._day_marks(found.day)
        thumbnail = site._thumbnail(found.starred[0], marks) or ""
    words = f'<span class="words ink">“{escape(found.said)}”</span>' if found.said else ""
    line = DOT.join(bits)
    where = f'<span class="where">{escape(line[:1].upper() + line[1:])}</span>' if bits else ""
    cue = '<span class="open">Open the day</span>' if site.href(f"/day/{found.day}") is not None else ""
    when = escape(day_words(found.day, year=True))
    inner = f'{thumbnail}<span class="when">{when}</span>{where}{words}{cue}'
    href = site.href(f"/day/{found.day}")
    card = (
        f'<a class="memory" href="{escape(href)}">{inner}</a>'
        if href is not None
        else f'<div class="memory">{inner}</div>'
    )
    return f'<section class="memory">\n<h2>{escape(ago(found.years))}</h2>\n{card}\n</section>\n'
