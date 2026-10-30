"""Ask v1 (RFC 0047 §4.5): `/ask?q=…`, the one field at the top of every page, answered with moments.

The words are found by the Library's search (#363, `search_page`): the same two functions `logbook
search` calls (`search.query`, then `search.search` over the index's FTS5 table), the same literal
words, phrases and prefixes, the same bm25 ranking, a retracted line never a hit (the index leaves it
out). The search runs up to the page's tier gate and each hit is then let through the gate itself
(`search_page._gated`), so a page at tier 1 searches tier 1 alone. Nothing here searches a second way.

An answer is moments, not lines (RFC 0047 §2): the hits are grouped by their local day, one row per
day, newest first. A row is the day in words (a link to the Day), the place the night was spent (the
Day's own reading of its night after, `day.of_reading`; a link to that day on the World until Places
has a page for a place), the people with the owner that day (the Day's company, `day.company_of_day`:
names only, each a link to their page, in the day's order, never a number beside one), then the words
that matched: each hit's source (a message, a mail, a call, a note …) in the pencil colour and its
excerpt with every matching word marked (`search_page.marked`), a link to its row on the Day. A person
whose name rests on lines the gate does not read every tier of is left out (`day_rhythm.reads_up_to`,
as Today's replies owed are): a page at tier 1 never learns a name a tier-2 resolution gave.

A hit a later line of its kind supersedes is marked "corrected later", a link to the line that
corrected it when the gate lets it through (`search_page._superseded`, the search page's mark), never
dropped; `?standing=1` leaves such hits out (`search.Query.standing`), and a link takes it off again.

The answer is the `MOST` best matches by rank (the rank decides which, as on the search page), read as
days, newest first across every page: `DAYS` days a page, each day once with all its matches, the
owner's own words (a note, a voice memo) first, then the rest in time order. When there are more
matches than `MOST`, the answer says that more words narrow it. The pages are links:
`?q=&standing=&page=`. The search never reads the whole record (its cost is the matches of the words,
and the `MOST` lines it reads); a row reads its own day and the day before (`reading.read`, two folds
of the owner's stays), kept for the record as it stands beside the Day's own readings
(`Site._day_reading`), so a page reads at most `DAYS` days.

A GET only: nothing is written, no script, nothing fetched, every link the server's own; styled
through the doors' tokens (`doors.page`) under one class, `.door-ask`, phone width first, every row and
link a 44 px target. No model answers here: questions in natural language are Ask v2, a later slice.
An exported site (`export site`) has no server to ask: its Ask is one sentence."""

from __future__ import annotations

import functools
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from html import escape
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlencode

from ..core import day as day_reader
from ..core import figures, people, reading, search
from . import day_rhythm, doors, search_page

if TYPE_CHECKING:  # the Site passes itself; serve imports this module, never the other way at import
    from .serve import Site

PATH = doors.ASK  # `/ask`
TITLE = "Ask"
DAYS = 12  # days a page, each one reading (two folds of the stays: 24 a page, as every page)
MOST = 240  # the best matches an answer reads, by rank: twenty pages of a day each at most
MAX_PAGE = search_page.MAX_PAGE
DOT = " · "
MONTHS = day_rhythm.MONTHS
UNNAMED = "a place with no name yet"
# the Day's words for a place it has no name for (`trips.coordinates_label`): `lat,lon`, then the nearest
# named place (`near Office, 1.2 km`) or the city of the nearest airport (`(Hamburg)`), or nothing
COORDINATES = re.compile(r"^-?\d+\.\d+,-?\d+\.\d+(?: near (?P<near>[^,]+),.*| \((?P<city>[^)]+)\))?$")
STANDING = "1"  # `?standing=1`: the hits that still stand, the superseded left out
EMPTY = "Ask the record a word, a name or a place: the days that hold it come back here."
NOTHING = "Nothing in the record says that. Try fewer words, or a name."
PAST = "Page {page} is past the last day of the answer: it ends sooner."
NO_SERVER = "Ask answers in logbook serve, on this machine; an exported site has no server to ask."
NEWEST = "newest first"
CAPPED = "the closest matches; more words narrow it"
LEAVE_OUT = "Leave out what was corrected"
TAKE_IN = "Show what was corrected too"
CORRECTED = "corrected later"
LEFT_OUT = "what was corrected is left out"  # the facts while the filter is on
OWN = ("note", "voice-memo")  # the owner's own words: first in their day
HELD = "Its words are on its Day."  # an excerpt whose words set a number beside a person's name
ASKED = "Your question"  # the heading of an answer whose words set a number beside a person's name
# a hit's kind in the owner's words: what the source of the words was
SOURCES = {
    "transcript": "call",
    "event": "calendar",
    "voice-memo": "voice memo",
    "browse": "web page",
    "watch": "video",
    "listen": "music",
    "trip": "journey",
    "heard": "podcast",
}
EMAIL = re.compile(r"^\S+@\S+$")  # a field of an excerpt that is an address and nothing else
PHONE = re.compile(r"^\+?[\d\s().-]{6,}$")  # or a phone number and nothing else (a sender's ref)
MACHINE = re.compile(r"^[a-z][a-z0-9_-]*$")  # or one lowercase word alone: a type, an app (`shazam`)
EDGE = re.compile(r"^\W+|\W+$")  # what stands outside a field's first and last letter or digit
STYLE = """
.door-ask p.eyebrow{margin:0 0 .4rem;color:var(--pencil,#62666D);font-weight:500;font-size:12px;
line-height:1.4;font-family:var(--mono,'JetBrains Mono',ui-monospace,monospace);letter-spacing:.12em;
text-transform:uppercase}
.door-ask h1{margin:0;font-weight:400;font-size:72px;line-height:1.02;
font-family:var(--serif,'Instrument Serif',Georgia,serif);color:var(--ink,#16181D);
overflow-wrap:anywhere}
.door-ask p.facts{margin:.6rem 0 0;color:var(--pencil,#62666D);font-size:13px;line-height:1.5}
.door-ask p.filter{margin:.8rem 0 1.6rem}
.door-ask p.filter a,.door-ask form.asked button{display:inline-flex;align-items:center;min-height:46px;
padding:0 1.1rem;border-radius:23px;border:1px solid var(--line,#E3DED3);background:var(--surface,#FBFAF6);
color:var(--ink,#16181D);text-decoration:none;font-size:15px}
.door-ask form.asked{display:flex;gap:.6rem;margin:1.4rem 0 0;max-width:34rem}
.door-ask form.asked input{flex:1 1 auto;min-width:0;min-height:46px;padding:0 1.1rem;border-radius:23px;
border:1px solid var(--line,#E3DED3);background:var(--surface,#FBFAF6);color:var(--ink,#16181D);
font-size:15px}
.door-ask form.asked button{flex:none;font-family:inherit;cursor:pointer}
.door-ask p.filter a.on{background:var(--ink,#16181D);border-color:var(--ink,#16181D);
color:var(--paper,#F4F1EA)}
.door-ask p.foot{margin:1.2rem 0 0;color:var(--pencil,#62666D);font-size:13px}
.door-ask p.said{margin:1.2rem 0 0;font-size:15px;color:var(--ink,#16181D);max-width:34rem}
.door-ask ol.moments{list-style:none;margin:0;padding:0}
.door-ask li.moment{margin:0 0 1rem;padding:24px 28px;border:1px solid var(--line,#E3DED3);
border-radius:20px;
background:var(--surface,#FBFAF6);overflow-wrap:anywhere}
.door-ask a.when{display:block;min-height:44px;padding:4px 0;font-weight:400;font-size:26px;
line-height:1.25;font-family:var(--serif,'Instrument Serif',Georgia,serif);color:var(--ink,#16181D);
text-decoration:none}
.door-ask a.when:hover{text-decoration:underline;text-decoration-color:var(--pencil-rule,#8C8F95)}
.door-ask p.where{margin:0 0 .4rem;color:var(--pencil,#62666D);font-size:15px;line-height:1.5}
.door-ask p.where a,.door-ask p.where span.person{display:inline-block;min-height:44px;line-height:44px}
.door-ask p.where a{color:var(--ink,#16181D)}
.door-ask ol.said{list-style:none;margin:0;padding:0;border-top:1px solid var(--line-soft,#ECE7DD)}
.door-ask ol.said li{padding:0;border-bottom:1px solid var(--line-soft,#ECE7DD)}
.door-ask ol.said li:last-child{border-bottom:0}
.door-ask a.words{display:block;min-height:44px;padding:10px 0;color:var(--ink,#16181D);
text-decoration:none;
font-size:15px;line-height:1.5}
.door-ask a.words:hover q{text-decoration:underline;text-decoration-color:var(--pencil-rule,#8C8F95)}
.door-ask span.source{display:block;color:var(--pencil,#62666D);font-weight:500;font-size:12px;
line-height:1.6;font-family:var(--mono,'JetBrains Mono',ui-monospace,monospace);letter-spacing:.12em;
text-transform:uppercase}
.door-ask q{display:block;quotes:none}
.door-ask ol.parts{list-style:none;margin:0;padding:0}
.door-ask q.held{color:var(--pencil,#62666D);font-size:13px}
.door-ask mark{background:var(--tint,#EDE8DE);color:inherit;padding:0 .12em;border-radius:3px;
font-weight:600;box-shadow:inset 0 -2px 0 var(--pencil-rule,#8C8F95)}
.door-ask p.superseded{margin:0 0 .5rem;color:var(--pencil,#62666D);font-size:13px}
.door-ask p.superseded a{display:inline-block;min-height:44px;line-height:44px;color:var(--pencil,#62666D);
text-decoration:underline dotted var(--pencil-rule,#8C8F95);text-underline-offset:.2em}
.door-ask p.pager{margin:1.5rem 0 0;color:var(--pencil,#62666D);font-size:13px}
.door-ask p.pager a{display:inline-flex;align-items:center;min-height:46px;padding:0 1.2rem;
border-radius:23px;
border:1px solid var(--line,#E3DED3);background:var(--surface,#FBFAF6);color:var(--ink,#16181D);
text-decoration:none;font-size:15px}
@media (max-width:40rem){
.door-ask form.asked{display:none}
.door-ask h1{font-size:40px}
.door-ask li.moment{padding:20px}
.door-ask a.when{font-size:22px}
}
"""


@dataclass(frozen=True)
class Moment:
    """What a row says of its day besides the words: where the night was and who was there."""

    where: str | None  # the place of the night after, None when the record does not say
    people: tuple[tuple[str, str | None], ...]  # (name, person id or None), in the day's order


def page_ask(site: Site, params: Mapping[str, str]) -> str:
    """`/ask?q=&standing=&page=`: the answer to the words of `q`, a page (1 to `MAX_PAGE`) of moments
    held to the gate; the field alone, with one sentence, when `q` holds no word. `ValueError` (a 400)
    for a page that is not one and a `standing` that is not `1`."""
    if site.static:
        return doors.page(
            site,
            TITLE,
            TITLE,
            _section(f'<h1>{TITLE}</h1>\n<p class="said">{escape(NO_SERVER)}</p>\n'),
            style_=STYLE,
        )
    text = (params.get("q") or "").strip()
    standing = params.get("standing") or ""
    if standing not in ("", STANDING):
        raise ValueError(f"standing={standing}: 1 leaves out what no longer stands, nothing shows it")
    page = search_page._page_number(params.get("page") or "1")
    if search.expression(text) is None:  # the field, here beside its sentence, and a button
        body = f'<h1>{TITLE}</h1>\n<p class="said">{escape(EMPTY)}</p>\n{_form()}'
        return _document(site, "", body)
    q = search.query(text, max_tier=search_page._max_tier(site.tiers), standing=standing == STANDING)
    directory = site._day_reading(("directory",), lambda: people.directory(site.lb))
    names = known_names(directory)
    try:
        with site.lb.index() as idx:
            hits, more = search_page._gated(idx, q, site.tiers, MOST)
            days = search.Result(q, hits).days()  # the latest day first
            shown_days = days[DAYS * (page - 1) : DAYS * page]
            shown = [hit for _day, on_day in shown_days for hit in on_day]
            superseded = search_page._superseded(idx, shown, site.tiers)
    except RuntimeError as e:  # a SQLite without FTS5: the index holds no search table
        return _document(site, text, _head(text, names) + f'<p class="said">{escape(str(e))}.</p>\n', names)
    parts = [_head(text, names)]
    if not shown:
        said = NOTHING if not hits else PAST.format(page=page)
        parts.append(f'<p class="said">{escape(said)}</p>\n')
        if standing:  # what was corrected may say it: the way back is a link
            parts.append(f'<p class="filter">{_link(TAKE_IN, _href(text, "", 1))}</p>\n')
        return _document(site, text, "".join(parts), names)
    last = (len(days) + DAYS - 1) // DAYS
    parts.append(_facts(text, standing, page, last, more))
    terms = search_page._terms(text)
    rows = []
    for day, on_day in shown_days:
        moment = site._day_reading(("ask-moment", day), functools.partial(moment_of, site, day))
        rows.append(
            _moment_html(site, day, _owner_first(on_day), moment, directory, superseded, (names, terms))
        )
    parts.append('<ol class="moments">\n' + "".join(rows) + "</ol>\n")
    parts.append(_pager(text, standing, page, page < last))
    top = max(int(hit.line.get("tier") or 0) for hit in shown)
    parts.append(f'<p class="foot">{escape(f"Nothing read above tier {top}.")}</p>\n')
    return _document(site, text, "".join(parts), names)


def _document(site: Site, text: str, body: str, names: Sequence[str] = ()) -> str:
    """The page, its title the words asked unless they set a number beside a person's name (`beside`):
    the field keeps them, as typed, and the page's own words never repeat them."""
    title = f"{TITLE}: {text}" if text and not beside(text, names) else TITLE
    return doors.page(site, TITLE, title, _section(body), style_=STYLE, asked=text)


def _section(body: str) -> str:
    return f'<section class="door-ask">\n{body}</section>\n'


def _head(text: str, names: Sequence[str]) -> str:
    heading = ASKED if beside(text, names) else f"\u201c{text}\u201d"
    return f'<p class="eyebrow">{TITLE}</p>\n<h1>{escape(heading)}</h1>\n'


def _form() -> str:
    """The field on the page of nothing asked, beside the sentence that asks for it (the header's own is
    the same form, at the top of every page)."""
    return (
        f'<form class="asked" method="get" action="{PATH}" role="search">'
        '<label class="hidden" for="asked">Ask the record</label>'
        '<input id="asked" type="search" name="q" placeholder="a name, a place, a word" autocomplete="off">'
        "<button>Ask</button></form>\n"
    )


def _facts(text: str, standing: str, page: int, last: int, more: bool) -> str:
    """The answer's facts, small, in pencil (its page when it has more than one, newest first; that more
    words narrow it when it holds only the closest matches; that what was corrected is left out while
    the filter is on), then the filter, a pill of its own, filled while it is on: leave out what was
    corrected, or show it again."""
    said = [*([f"page {page}"] if last > 1 else []), NEWEST, *([CAPPED] if more else [])]
    if standing:
        said.append(LEFT_OUT)
        toggle = f'<a class="on" href="{escape(_href(text, "", 1))}">{escape(TAKE_IN)}</a>'
    else:
        toggle = _link(LEAVE_OUT, _href(text, STANDING, 1))
    return f'<p class="facts">{escape(DOT.join(said))}</p>\n<p class="filter">{toggle}</p>\n'


def _owner_first(hits: Sequence[search.Hit]) -> list[search.Hit]:
    """A day's hits, the owner's own words (`OWN`) first, each part in the day's time order."""
    return sorted(hits, key=lambda hit: str(hit.line["kind"]) not in OWN)


# -- a moment ---------------------------------------------------------------------------------------------


def moment_of(site: Site, day: str) -> Moment:
    """The place of `day`'s night and the people with the owner that day, as the Day reads them: one
    reading of the day and the day before through the gate (`reading.read`), the Day's own
    `of_reading`, then its company (`company_of_day`, with who the owner said was there)."""
    d = date.fromisoformat(day)
    rd = reading.read(site.lb, (d - timedelta(days=1)).isoformat(), day, site.airports, site.tiers)
    lines = day_reader.day_lines(rd, d)
    data: dict[str, Any] = day_reader.of_reading(rd, day, None, lines)
    stated = day_reader.stated_of(lines, rd.retracted)
    if stated:
        data["stated"] = stated
    night = data["nights"]["after"]
    where = night.get("where") if not night.get("in_transit") else None
    company = tuple(
        (str(c["name"]), str(c["person"]) if c.get("person") else None)
        for c in day_reader.company_of_day(data)
        if c.get("name")
    )
    return Moment(str(where) if where else None, company)


def _moment_html(
    site: Site,
    day: str,
    hits: Sequence[search.Hit],
    moment: Moment,
    directory: people.Report,
    superseded: search_page.Superseded,
    words: tuple[Sequence[str], search_page.Terms],
) -> str:
    """One day: the day in words (its Day), where and with whom, then each hit's source and words
    (`words`: the names no number may stand beside, and the terms to mark)."""
    when = site.link(escape(day_words(day)), f"/day/{day}", "when")
    where = []
    if moment.where is not None:
        said = place_words(moment.where)
        where.append(site.link(escape(said), f"/world?{urlencode([('from', day), ('to', day)])}"))
    names = [_person(site, name, person) for name, person in _held(moment.people, directory, site.tiers)]
    if names:
        where.append("with " + ", ".join(names))
    place = f'<p class="where">{DOT.join(where)}</p>\n' if where else ""
    said = "".join(_hit_html(site, day, hit, superseded.get(str(hit.line["id"])), *words) for hit in hits)
    return f'<li class="moment">\n{when}\n{place}<ol class="said">\n{said}</ol>\n</li>\n'


def _held(
    company: Sequence[tuple[str, str | None]], directory: people.Report, tiers: Sequence[int] | None
) -> list[tuple[str, str | None]]:
    """The company the gate may name: a person the record knows only when the gate reads every tier up
    to the lines that name them (`reads_up_to`); a name the day's own lines carry (a guest's, a voice
    the gate already held, `attribution.Voices`) as it is. The rest are left out, unsaid."""
    out = []
    for name, person in company:
        if person is not None:
            known = directory.known.get(person)
            if known is None or not day_rhythm.reads_up_to(known.tier, tiers):
                continue
        out.append((name, person))
    return out


def _person(site: Site, name: str, person: str | None) -> str:
    if person is None:
        return f'<span class="person">{escape(name)}</span>'
    return site.link(escape(name), "/people/" + quote(person, safe=""))


def _hit_html(
    site: Site,
    day: str,
    hit: search.Hit,
    superseded: tuple[str, str] | None,
    names: Sequence[str],
    terms: search_page.Terms,
) -> str:
    """One hit: its source in pencil, then its excerpt with the match marked (`excerpt_html`), a link to
    its row on the Day (for the kinds the Day gives a row of their own, `search_page.ROWED`), else to the
    Day; and, when a later line supersedes it, that mark, a link to the line that did."""
    line = hit.line
    kind = str(line["kind"])
    row = f"#{search_page._row_id(str(line['id']))}" if kind in search_page.ROWED else ""
    source = f'<span class="source">{escape(SOURCES.get(kind, kind))}</span>'
    words = f"{source}{excerpt_html(hit.snippet, names, terms)}"
    mark = ""
    if superseded is not None:
        said = site.link(escape(CORRECTED), f"/line/{superseded[1]}")
        mark = f'<p class="superseded">{said}</p>'
    return f"<li>{site.link(words, f'/day/{day}{row}', 'words')}{mark}</li>\n"


def excerpt_html(snippet: str, names: Sequence[str], terms: search_page.Terms) -> str:
    """The excerpt as the page shows it: its fields (`readable`) on one line, ` · ` between them, but
    where a field ends or begins with a digit, which then starts a line of its own (`parts`), so the
    page's own separator never sets a number beside a name the next field holds; and none of its words
    when they set a number beside a person's name (`beside`) all the same: the record's own words, they
    are on its Day (`HELD`), never on this page."""
    lines = parts(readable(snippet))
    if any(beside(_plain(line), names) for line in lines):
        return f'<q class="held">{escape(HELD)}</q>'
    if len(lines) == 1:
        return f"<q>{search_page.marked(lines[0], terms)}</q>"
    rows = "".join(f"<li><q>{search_page.marked(line, terms)}</q></li>\n" for line in lines)
    return f'<ol class="parts">\n{rows}</ol>'


def parts(excerpt: str) -> list[str]:
    """An excerpt's fields as lines: one line while the fields meet in letters, a new line wherever a
    field ends or begins with a digit (the marks and an ellipsis aside)."""
    lines: list[str] = []
    for field in excerpt.split(search.FIELD_BREAK):
        if lines and (_edge(lines[-1], -1).isdigit() or _edge(field, 0).isdigit()):
            lines.append(field)
        elif lines:
            lines[-1] += search.FIELD_BREAK + field
        else:
            lines.append(field)
    return lines


def _edge(text: str, end: int) -> str:
    """The first (`end` 0) or last (`end` -1) letter or digit of `text`, the marks, an ellipsis, a space
    and any other sign aside: what touches the next field."""
    bare = EDGE.sub("", _plain(text))
    return bare[end] if bare else ""


def _machine(field: str, first: bool, last: bool) -> bool:
    """Whether an excerpt's field is no one's words: an address or a phone number alone; else, when it
    holds no match, one lowercase word alone or a piece the excerpt cut at its first or last edge."""
    bare = _plain(field).strip(search.ELLIPSIS + " ")
    if EMAIL.match(bare) is not None or PHONE.match(bare) is not None:
        return True
    if search.MARK[0] in field:
        return False
    if (first and field.startswith(search.ELLIPSIS)) or (last and field.endswith(search.ELLIPSIS)):
        return True
    return MACHINE.match(bare) is not None


def _plain(text: str) -> str:
    """An excerpt's words without the search's marks (`search.MARK`)."""
    return text.replace(search.MARK[0], "").replace(search.MARK[1], "")


def known_names(directory: people.Report) -> tuple[str, ...]:
    """Every name of a person the record knows, whole and given, at any tier: only what no number may
    stand beside, never printed (a name above the page's gate is held here too, the stricter way)."""
    found = {part for p in directory.known.values() if p.name for part in (p.name, p.name.split()[0])}
    return tuple(sorted(found, key=len, reverse=True))


def beside(text: str, names: Sequence[str]) -> bool:
    """Whether `text` sets a number, a date or a clock beside one of `names` (`figures.adjacent`)."""
    return any(figures.adjacent(text, name) for name in names)


def readable(snippet: str) -> str:
    """An excerpt as words: the fields of a line's body (`search.FIELD_BREAK` between them) but those
    that are no one's words (`_machine`: an address or a phone number alone, a guest's, a sender's; one
    lowercase word alone, a type or an app, `track`, `shazam`; a name cut at the excerpt's edge,
    `…Nordmann`), when another field holds the match; else the excerpt as the search gives it."""
    fields = snippet.split(search.FIELD_BREAK)
    last = len(fields) - 1
    words = [f for n, f in enumerate(fields) if not _machine(f, n == 0, n == last)]
    if words and any(search.MARK[0] in f for f in words):
        return search.FIELD_BREAK.join(words)
    return snippet


def place_words(where: str) -> str:
    """The place of a night in words: its name as the Day gives it; for a place with no name, never its
    coordinates, but the named place or the city it is near (`near Zurich`), else `UNNAMED`."""
    found = COORDINATES.match(where)
    if found is None:
        return where
    near = found.group("near") or found.group("city")
    return f"near {near}" if near else UNNAMED


def day_words(day: str) -> str:
    """`Wednesday 10 June 2026`: a day in words, with its year (an answer runs over years)."""
    d = date.fromisoformat(day)
    return f"{day_reader.WEEKDAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]} {d.year}"


# -- the links --------------------------------------------------------------------------------------------


def _href(text: str, standing: str, page: int) -> str:
    params = [("q", text)]
    if standing:
        params.append(("standing", standing))
    if page > 1:
        params.append(("page", str(page)))
    return f"{PATH}?{urlencode(params)}"


def _link(label: str, href: str) -> str:
    return f'<a href="{escape(href)}">{escape(label)}</a>'


def _pager(text: str, standing: str, page: int, more: bool) -> str:
    """The pages as links, the one before and the one after; nothing when the answer is one page."""
    if page == 1 and not more:
        return ""
    links = []
    if page > 1:
        links.append(_link(f"← page {page - 1}", _href(text, standing, page - 1)))
    if more:
        links.append(_link(f"page {page + 1} →", _href(text, standing, page + 1)))
    return f'<p class="pager">{" ".join(links)}</p>\n' if links else ""
