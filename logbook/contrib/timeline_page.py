"""The Timeline of `logbook serve`: `/timeline`, the record's moments beside the map, at five zooms, each a
link and never a state the page keeps (RFC 0043 §11-12): `/timeline/day/YYYY-MM-DD`, `/week/YYYY-Www`,
`/month/YYYY-MM`, `/year/YYYY` and `/life`, all years. `/timeline` alone is the day the owner is in.
Read-only: no form, no act, no script.

The page reads `logbook.core.moments`, the reader `logbook show timeline --json` prints, so the page and
the command say the same thing. On a phone the map's place comes first and the list under it; on a
wider screen the list is on the left and the map on the right. The map is a placeholder until slice G
draws one: a box that says so, with the day's track drawn as the Day page draws it (`serve._track_svg`,
the same function, on the same rows).

- **day**: the moments and the moves between them, each moment a fold whose summary is one line
  (`Saltbu · 19:30-22:40 · Ola, Kari, Per? · 6 photos · 2 conversations`, a proposed person with a `?`)
  and whose body is its detail: who was there, the confirmed in ink and the proposed in pencil with
  their reasons; its photos; what passed during it; and, read at tier 3 only, what was paid;
- **week**: a line per day, its night and its moments as chips;
- **month**: a calendar, each day in its night's class colour, its photos, signed or open;
- **year**: the twelve months as a strip of their nights by class, and the journeys as bands;
- **life**: per place and per vessel, the visits, the years and who was there — names only.

A person is never shown with a number beside their name (VISION: no metrics near people). The month,
the year and all years are read once for the record as it stands (`Site.shared`, the lifetime every
shared reading has: the head, the settings beside the chain and the day), so a reload never scans the
record again; a day and a week read their own few days. All years is built once after the record moves,
in a thread of its own, by the first request that opens it; while a long build runs the page says so in
one line (`BUILDING`), and it is kept until the next move (`_Life`). The page says the highest tier it
read."""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Mapping, Sequence
from datetime import date, timedelta
from html import escape
from typing import TYPE_CHECKING, Any

from ..core import day as day_reader
from ..core import moments

if TYPE_CHECKING:  # the Site passes itself; serve imports this module, never the other way at import
    from .serve import Site

PATH = re.compile(r"^/timeline(?:/(day|week|month|year)/([0-9W-]+)|/(life))?$")
MAP_LATER = "the map comes with slice G"
TAP = "tap"  # a link that is a 44 px target on its own, wherever it stands in a line
LIFE_WAIT_S = 10.0  # how long a request waits for all years to be built before saying it is being built
BUILDING = (
    "All years is being built from the record as it stands, once until the record moves; reload in a minute."
)
DOT = moments.DOT
EN_DASH = day_reader.EN_DASH
NO_MOMENT = '<span class="mute">no moment</span>'
ZOOM_WORDS = {"day": "day", "week": "week", "month": "month", "year": "year", "life": "all years"}
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
PROPOSED_BY = (
    "Pencil: proposed by the with module's rules, until you confirm who was there"  # the pencil's title
)
STYLE = """
main{--home:#2e8b57;--family:#b07d2b;--aboard:#1f7f9a;--away:#c0652a;--transit:#9b9b9b}
p.zooms{display:flex;flex-wrap:wrap;gap:.2rem .4rem;margin:.2rem 0 .6rem}
p.zooms a,p.zooms b,p.pager a{display:inline-block;min-height:2.75rem;min-width:2.75rem;box-sizing:border-box;
line-height:2.75rem;padding:0 .4rem;text-align:center}
p.zooms b{color:var(--ink)}
a.tap{display:inline-block;min-height:2.75rem;min-width:2.75rem;line-height:2.75rem;text-align:center}
p.pager{display:flex;flex-wrap:wrap;gap:.2rem .8rem;margin:0 0 .4rem}
p.pager span{display:inline-block;line-height:2.75rem;padding:0 .4rem;color:var(--pencil)}
div.timeline{display:flex;flex-direction:column;gap:1rem}
section.map{border:1px solid var(--line);border-radius:20px;padding:20px;background:var(--surface);
min-width:0}
section.map p{margin:0 0 .3rem;color:var(--pencil);font-size:.9rem}
section.list{min-width:0}
@media (min-width:48rem){div.timeline{display:grid;grid-template-columns:minmax(0,1fr) 20rem;
align-items:start}
section.map{grid-column:2;grid-row:1;position:sticky;top:.5rem}section.list{grid-column:1;grid-row:1}}
svg.track{display:block;width:100%;max-width:30rem;height:auto;margin:.5rem 0;
border:1px solid var(--line);border-radius:16px;background:var(--surface)}
svg.track circle{fill:var(--ink);fill-opacity:.85;stroke:var(--surface)}
svg.track line{stroke:var(--pencil);stroke-width:1.5}
svg.track line.gap{stroke-dasharray:4 3}
svg.track text{font:11px var(--sans);fill:var(--ink)}
ol.items{list-style:none;padding:0;margin:0}
ol.items>li{border-bottom:1px solid var(--line-soft);overflow-wrap:anywhere}
ol.items>li.move{color:var(--pencil);font-size:.9rem;padding:.3rem 0 .3rem 1rem}
ol.items details{margin:0}
ol.items summary{min-height:2.75rem;padding:.55rem 0;line-height:1.6;color:var(--ink)}
.class{display:inline-block;width:.7rem;height:.7rem;border-radius:50%;margin-right:.35rem;
background:var(--transit);vertical-align:baseline}
.home{--c:var(--home)}.family{--c:var(--family)}.aboard{--c:var(--aboard)}.away{--c:var(--away)}
.class{background:var(--c,var(--transit))}
dl.moment{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:.2rem .8rem;margin:.2rem 0 .8rem}
dl.moment dt{color:var(--pencil)}
dl.moment dd{margin:0;min-width:0}
blockquote.said{margin:.2rem 0;padding-left:.9rem;border-left:2px solid var(--line);white-space:pre-wrap;
font-family:var(--serif);font-size:17px}
blockquote.machine{color:var(--pencil);font-style:italic;font-family:var(--sans);font-size:15px}
ul.plain li{padding:.15rem 0}
ol.days{list-style:none;padding:0;margin:0}
ol.days>li{padding:.6rem 0;border-bottom:1px solid var(--line-soft);overflow-wrap:anywhere}
a.chip{display:inline-block;min-height:2.75rem;line-height:2.75rem;margin:.1rem .3rem .1rem 0;padding:0 .5rem;
border:1px solid var(--line);border-left:4px solid var(--c,var(--transit));border-radius:22px;
background:var(--surface);
text-decoration:none}
div.calendar{display:grid;grid-template-columns:repeat(7,1fr);gap:.2rem}
div.calendar span.head{color:var(--pencil);font-size:13px;font-family:var(--mono);letter-spacing:.12em;
text-transform:uppercase;text-align:center}
div.calendar a.cell,div.calendar span.cell{display:flex;flex-direction:column;min-height:3.4rem;min-width:0;
padding:.2rem;border:1px solid var(--line);border-top:4px solid var(--c,var(--line));border-radius:12px;
background:var(--surface);
text-decoration:none;font-size:13px;color:var(--pencil);overflow-wrap:anywhere}
div.calendar a.cell b{font-size:.95rem;color:var(--ink)}
ol.months{list-style:none;padding:0;margin:0}
ol.months>li{padding:.3rem 0;border-bottom:1px solid var(--line)}
ol.months a.month,ol.months span.month{display:block;min-height:2.75rem;text-decoration:none}
div.strip{display:flex;height:.8rem;border-radius:2px;overflow:hidden;background:var(--line);margin:.2rem 0}
div.strip span{display:block;background:var(--c,var(--transit))}
div.year{position:relative;height:1.2rem;background:var(--line);border-radius:2px;margin:.4rem 0}
div.year span{position:absolute;top:0;bottom:0;min-width:3px;background:var(--c,var(--away));
border-radius:2px}
ol.shelf>li a{overflow-wrap:anywhere}
p.legend{font-size:14px;color:var(--pencil)}
"""


def page(site: Site, path: str) -> str:
    """The page at `path` (`PATH`): a zoom and its key, or the day the owner is in."""
    m = PATH.match(path)
    if m is None:
        raise ValueError(f"no timeline at {path}")
    if m.group(3):
        return _life(site)
    zoom, key = m.group(1) or "day", m.group(2) or site._today_of()
    moments.window(zoom, key)  # a key that is not one is a 400, before anything is read
    if zoom == "day":
        return _day(site, key)
    if zoom == "week":
        return _week(site, key)
    if zoom == "month":
        return _month(site, key)
    return _year(site, key)


# -- what every zoom has --------------------------------------------------------------------------------


def _head(
    site: Site, zoom: str, key: str | None, title: str, facts: str | None, tier: int | None
) -> list[str]:
    """The heading, the zoom links (the one shown in bold) and the previous and next of this zoom; the
    other zooms open on the day this one starts on (all years: the day the owner is in). With no
    `facts` (all years while it is built), the heading says nothing of what was read."""
    day = site._today_of() if key is None else moments.window(zoom, key)[0]
    targets = {
        "day": f"/timeline/day/{day}",
        "week": f"/timeline/week/{moments.week_of(day)}",
        "month": f"/timeline/month/{day[:7]}",
        "year": f"/timeline/year/{day[:4]}",
        "life": "/timeline/life",
    }
    zooms = "".join(  # each its own 44 px target, set apart by the row's gap
        f"<b>{ZOOM_WORDS[z]}</b>" if z == zoom else site.link(ZOOM_WORDS[z], target)
        for z, target in targets.items()
    )
    out = [
        f"<h1>Timeline <small>{escape(title)}</small>"
        + ("" if facts is None else f" {site.tier_small(facts, tier)}")
        + "</h1>\n",
        f'<p class="zooms">{zooms}</p>\n',
    ]
    if key is not None:
        before, after = _beside(zoom, key)
        span = _span(site)
        out.append(
            f'<p class="pager">{_pager_link(site, f"← {before}", zoom, before, span)}'
            f"{_pager_link(site, f'{after} →', zoom, after, span)}</p>\n"
        )
    return out


def _span(site: Site) -> tuple[str, str] | None:
    """The days the pager may reach: the record's first to its last (`Site._record_days`), or today when
    that is later; None for an empty record, where no neighbour is linked. The week page's rule."""
    whole = site._record_days()
    return None if whole is None else (whole[0], max(whole[1], site._today_of()))


def _reaches(span: tuple[str, str] | None, zoom: str, key: str) -> bool:
    """Whether a day, week, month or year holds a day of `span` (`_span`): the timeline links only those,
    so a crawl that follows its links (the golden crawl, the open-ends walk) ends at the record's edges
    instead of walking every day of the calendar."""
    first, last = moments.window(zoom, key)
    return span is not None and last >= span[0] and first <= span[1]


def _pager_link(site: Site, text: str, zoom: str, key: str, span: tuple[str, str] | None) -> str:
    """`text` as a link to the neighbouring day, week, month or year while it holds a day of `span`,
    else as plain words."""
    if not _reaches(span, zoom, key):
        return f"<span>{escape(text)}</span>"
    return site.link(escape(text), f"/timeline/{zoom}/{key}")


def _beside(zoom: str, key: str) -> tuple[str, str]:
    first, last = moments.window(zoom, key)
    if zoom == "day":
        d = date.fromisoformat(first)
        return (d - timedelta(days=1)).isoformat(), (d + timedelta(days=1)).isoformat()
    if zoom == "week":
        d = date.fromisoformat(first)
        return moments.week_of((d - timedelta(days=7)).isoformat()), moments.week_of(
            (d + timedelta(days=7)).isoformat()
        )
    if zoom == "month":
        before = date.fromisoformat(first) - timedelta(days=1)
        after = date.fromisoformat(last) + timedelta(days=1)
        return before.isoformat()[:7], after.isoformat()[:7]
    return str(int(key) - 1), str(int(key) + 1)


def _shared(site: Site, zoom: str, key: str | None) -> dict[str, Any]:
    """A zoom read once for the record as it stands (`Site.shared`): the month and the year."""
    tiers = None if site.tiers is None else tuple(site.tiers)
    return site.shared(
        ("timeline", zoom, key, tiers), lambda: moments.read(site.lb, zoom, key, site.airports, site.tiers)
    )


def _class(cls: str | None) -> str:
    return "transit" if cls in (None, moments.IN_TRANSIT) else str(cls)


def _legend(found: Mapping[str, int]) -> str:
    return f'<p class="legend">{escape(moments.counts_text(found))}</p>\n'


# -- day --------------------------------------------------------------------------------------------------


def _day(site: Site, day: str) -> str:
    from . import serve  # the Day page's own drawing of the track, never a copy of it

    data = moments.read(site.lb, "day", day, site.airports, site.tiers)
    found = [i for i in data["items"] if i["kind"] == "moment"]
    night = data["night"]
    facts = f"{len(found)} moment{'' if len(found) == 1 else 's'}"
    parts = _head(site, "day", day, f"{day} {data['weekday']}", facts, data["tier"])
    where = f" ({night['where']})" if night.get("where") else ""
    parts.append(
        f'<p class="{_class(night["class"])}"><span class="class"></span>night after: '
        f"{escape(night['class'] + where)}{DOT}{site.link('the Day', f'/day/{day}', TAP)}</p>\n"
    )
    money = data.get("money")
    if money is not None and not money["covered"]:
        parts.append(f'<p class="mute">{escape(moments.money_gap_text(money))}</p>\n')
    parts.append('<div class="timeline">\n<section class="map" aria-label="map">\n')
    parts.append(f"<p>{escape(MAP_LATER)}</p>\n{serve._track_svg(data['track'])}</section>\n")
    parts.append('<section class="list">\n')
    if data["items"]:
        parts.append('<ol class="items">\n')
        parts.extend(_item(site, item, day) for item in data["items"])
        parts.append("</ol>\n")
    else:
        parts.append('<p class="mute">no moment: no stay on this day</p>\n')
    if money is not None and money["elsewhere"]:
        paid = ", ".join(_paid(t) for t in money["elsewhere"])
        parts.append(f'<p class="mute">paid outside any moment: {paid}</p>\n')
    parts.append("</section>\n</div>\n")
    return site.document(f"Timeline {day}", "".join(parts), style=STYLE)


def _item(site: Site, item: Mapping[str, Any], day: str) -> str:
    if item["kind"] != "moment":
        return f'<li class="move">{escape(moments.item_text(item))}</li>\n'
    summary = escape(moments.item_text(item))
    cls = _class(item["class"])
    return (
        f'<li class="{cls}"><details><summary><span class="class"></span>{summary}</summary>\n'
        f'<dl class="moment">\n{_detail(site, item, day)}</dl>\n</details></li>\n'
    )


def _detail(site: Site, item: Mapping[str, Any], day: str) -> str:
    """A moment open: its place and class, who was there, its photos, what passed during it, paid."""
    rows = [_dt("where", f"{escape(item['place'])}{DOT}{escape(item['class'])}{DOT}{escape(item['span'])}")]
    people = item["people"]
    if people["confirmed"]:
        rows.append(_dt("with", escape(", ".join(p["name"] for p in people["confirmed"]))))
    if people["proposed"]:
        proposed = ", ".join(
            f"{escape(p['name'])}? ({escape(', '.join(p['because']))})" for p in people["proposed"]
        )
        rows.append(_dt("proposed", f'<span class="pencil" title="{PROPOSED_BY}">{proposed}</span>'))
    if item["photos"]:
        photos = ", ".join(
            site.link(f"photo {n}", f"/line/{i}", TAP) for n, i in enumerate(item["photos"], 1)
        )
        rows.append(_dt("photos", photos))
    during = item["during"]
    for c in during["messages"]:  # the name and the channel, never a count beside the name
        rows.append(_dt("messages", escape(moments.conversation_text(c))))
    for c in during["calls"]:  # the name and which way, never how long
        rows.append(_dt("call", escape(moments.call_text(c))))
    for s in during["agents"]:
        said = "".join(f'<blockquote class="said">{escape(t)}</blockquote>' for t in s["owner"])
        machine = "".join(
            f'<blockquote class="said machine" title="machine text">{escape(t)}</blockquote>'
            for t in s["machine"]
        )
        head = f"{escape(s['agent'])}: {escape(s['title'])}"
        tail = f'<p class="mute">machine text, {escape(s["agent"])}:</p>{machine}' if machine else ""
        rows.append(_dt("agent", f"{head}{said}{tail}"))
    for r in during["recordings"]:
        rows.append(_dt("recording", site.link(escape(r["title"]), f"/line/{r['line']}", TAP)))
    for t in during["mail"]:
        rows.append(
            _dt(
                "mail", f"{escape(t['subject'])} ({t['messages']} message{'' if t['messages'] == 1 else 's'})"
            )
        )
    for n in during["notes"]:
        rows.append(_dt("note", escape(n["text"])))
    for e in during["events"]:
        rows.append(_dt("event", escape(e["title"])))
    money = item.get("money")
    if money is not None:
        said = money.get("said")
        paid = ", ".join(_paid(t) for t in money["paid"]) or escape(said or "nothing")
        rows.append(_dt("paid", paid))
    rows.append(_dt("record", site.link("the Day", f"/day/{day}", TAP)))
    return "".join(rows)


def _paid(t: Mapping[str, Any]) -> str:
    amount = t.get("amount")
    money = f" {amount:.2f} {t['currency']}" if isinstance(amount, int | float) else ""
    return escape(f"{t['merchant']}{money}")


def _dt(term: str, html: str) -> str:
    return f"<dt>{escape(term)}</dt><dd>{html}</dd>\n"


# -- week -------------------------------------------------------------------------------------------------


def _week(site: Site, key: str) -> str:
    data = moments.read(site.lb, "week", key, site.airports, site.tiers)
    parts = _head(
        site, "week", key, f"{key} {data['first']} {EN_DASH} {data['last']}", "7 days", data["tier"]
    )
    parts.append('<ol class="days">\n')
    span = _span(site)
    for d in data["days"]:
        night = d["night"]
        where = f" ({night['where']})" if night.get("where") else ""
        chips = "".join(
            f'<a class="chip {_class(c["class"])}" href="{escape(_href(site, f"/timeline/day/{d['day']}"))}">'
            f"{escape(c['place'])} {escape(c['span'])}</a>"
            for c in d["moments"]
        )
        name = escape(f"{d['weekday'][:3]} {d['day']}")
        day_link = (
            site.link(name, f"/timeline/day/{d['day']}", TAP) if _reaches(span, "day", d["day"]) else name
        )
        parts.append(
            f'<li><p class="{_class(night["class"])}"><span class="class"></span>{day_link}{DOT}night '
            f"{escape(night['class'] + where)}</p>\n<p>{chips or NO_MOMENT}</p></li>\n"
        )
    parts.append("</ol>\n")
    return site.document(f"Timeline {key}", "".join(parts), style=STYLE)


def _href(site: Site, path: str) -> str:
    return site.href(path) or path


# -- month ------------------------------------------------------------------------------------------------


def _month(site: Site, key: str) -> str:
    data = _shared(site, "month", key)
    facts = f"{data['signed']} signed"
    parts = _head(site, "month", key, key, facts, data["tier"])
    parts.append(_legend(data["nights"]))
    parts.append('<div class="calendar">\n')
    parts.extend(f'<span class="head">{w}</span>' for w in WEEKDAYS)
    first = date.fromisoformat(data["first"])
    parts.extend('<span class="cell" aria-hidden="true"></span>' for _ in range(first.weekday()))
    span = _span(site)
    for d in data["days"]:
        cls = _class(d["night"]["class"]) if d["night"] else ""
        night = d["night"]["class"] if d["night"] else "no track"
        photos = f"{d['photos']} photo{'' if d['photos'] == 1 else 's'}" if d["photos"] else ""
        title = DOT.join(p for p in (night, photos, "signed" if d["signed"] else "open") if p)
        inside = (
            f"<b>{int(d['day'][8:])}</b><span>{escape(photos)}</span>"
            f"<span>{'signed' if d['signed'] else 'open'}</span>"
        )
        if _reaches(span, "day", d["day"]):
            parts.append(
                f'<a class="cell {cls}" href="{escape(_href(site, f"/timeline/day/{d['day']}"))}"'
                f' title="{escape(title)}">{inside}</a>\n'
            )
        else:  # a day outside the record: shown, not linked
            parts.append(f'<span class="cell {cls}" title="{escape(title)}">{inside}</span>\n')
    parts.append("</div>\n")
    return site.document(f"Timeline {key}", "".join(parts), style=STYLE)


# -- year -------------------------------------------------------------------------------------------------


def _year(site: Site, key: str) -> str:
    data = _shared(site, "year", key)
    bands = data["journeys"]
    parts = _head(
        site, "year", key, key, f"{len(bands)} journey{'' if len(bands) == 1 else 's'}", data["tier"]
    )
    parts.append(_legend(data["nights"]))
    parts.append('<ol class="months">\n')
    span = _span(site)
    for m in data["months"]:
        strip = "".join(
            f'<span class="{_class(c)}" style="flex:{n}"'
            f' title="{escape(moments.counts_text({c: n}))}"></span>'
            for c, n in m["nights"].items()
        )
        text = f"{m['month']}{DOT}{moments.counts_text(m['nights'])}{DOT}{moments.tally_text(m)}"
        inside = f'{escape(text)}<div class="strip">{strip}</div>'
        if _reaches(span, "month", m["month"]):
            parts.append(
                f'<li><a class="month" href="{escape(_href(site, f"/timeline/month/{m['month']}"))}">'
                f"{inside}</a></li>\n"
            )
        else:  # a month outside the record: shown, not linked
            parts.append(f'<li><span class="month">{inside}</span></li>\n')
    parts.append("</ol>\n<h2>Journeys</h2>\n")
    if bands:
        days = 366 if date(int(key), 12, 31).timetuple().tm_yday == 366 else 365
        start = date(int(key), 1, 1)
        spans = "".join(
            f'<span class="{_class(j["class"])}"'
            f' style="left:{(date.fromisoformat(j["first"]) - start).days / days * 100:.1f}%;'
            f'width:{j["nights"] / days * 100:.1f}%"></span>'
            for j in bands
        )
        parts.append(f'<div class="year" aria-hidden="true">{spans}</div>\n<ul class="plain">\n')
        for j in bands:
            nights = f"{j['nights']} night{'' if j['nights'] == 1 else 's'}"
            text = f"{j['first']} {EN_DASH} {j['last']}{DOT}{j['where'] or 'away'}{DOT}{nights}"
            journey = f"/timeline/day/{j['first']}"  # its first day: always a page, whatever the trips say
            parts.append(
                f'<li class="{_class(j["class"])}"><span class="class"></span>'
                f"{site.link(escape(text), journey, TAP)}</li>\n"
            )
        parts.append("</ul>\n")
    else:
        parts.append('<p class="mute">no journey: no run of nights away from home</p>\n')
    return site.document(f"Timeline {key}", "".join(parts), style=STYLE)


# -- all years --------------------------------------------------------------------------------------------


class _Life:
    """All years for one state of the record: built once, in a thread of its own, by the first request
    that asks for it; every request after it is answered from what was built, until the record moves
    and `Site.shared` hands out a new one."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._thread: threading.Thread | None = None
        self.data: dict[str, Any] | None = None
        self.error: BaseException | None = None

    def get(self, build: Callable[[], dict[str, Any]], wait: float) -> dict[str, Any] | None:
        """What was built, waiting `wait` seconds for a build that runs; None while it still runs. The
        first call starts the build; a build that failed raises its error until the record moves."""
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, args=(build,), name="timeline-life", daemon=True
                )
                self._thread.start()
        if not self._done.wait(wait):
            return None
        if self.error is not None:
            raise self.error
        return self.data

    def _run(self, build: Callable[[], dict[str, Any]]) -> None:
        try:
            self.data = build()
        except BaseException as e:  # handed to the request that reads it, as a page's own error
            self.error = e
        finally:
            self._done.set()


def _life(site: Site) -> str:
    """All years, built once for the record as it stands (`_Life`, kept by `Site.shared` until the head,
    the settings beside it or the day move): a request waits `LIFE_WAIT_S` for the build, so a record
    of a few years answers at once; a longer build is said in one line (`BUILDING`), and a reload shows
    it once it is done."""
    tiers = None if site.tiers is None else tuple(site.tiers)
    held = site.shared(("timeline", "life", tiers), _Life)
    data = held.get(lambda: moments.read(site.lb, "life", None, site.airports, site.tiers), LIFE_WAIT_S)
    if data is None:
        parts = _head(site, "life", None, "all years", None, None)
        parts.append(f'<p class="mute">{escape(BUILDING)}</p>\n')
        return site.document("Timeline, all years", "".join(parts), style=STYLE)
    span = f"{data['first']} {EN_DASH} {data['last']}" if data["first"] else "no days"
    facts = f"{len(data['places'])} places{DOT}{len(data['vessels'])} vessels"
    parts = _head(site, "life", None, f"all years, {span}", facts, data["tier"])
    parts.append(_legend(data["nights"]))
    parts.append("<h2>Places</h2>\n")
    parts.append(_shelf(site, [(moments.place_text(p), p) for p in data["places"]]))
    parts.append("<h2>Vessels</h2>\n")
    parts.append(_shelf(site, [(moments.vessel_text(v), v) for v in data["vessels"]]))
    return site.document("Timeline, all years", "".join(parts), style=STYLE)


def _shelf(site: Site, rows: Sequence[tuple[str, Mapping[str, Any]]]) -> str:
    """A place or a vessel a row: what it was, its years (each a link to the year), who was there."""
    if not rows:
        return '<p class="mute">none</p>\n'
    out = ['<ol class="shelf">\n']
    for text, row in rows:
        years = ", ".join(site.link(y, f"/timeline/year/{y}", TAP) for y in row["years"])
        who = f"<p>with {escape(', '.join(row['people']))}</p>" if row["people"] else ""
        cls = _class(row.get("class") or "aboard")
        out.append(
            f'<li><p class="{cls}"><span class="class"></span>{escape(text)}</p>'
            f'<p class="mute">{years}</p>{who}</li>\n'
        )
    out.append("</ol>\n")
    return "".join(out)
