"""The Library's search (`logbook serve`): `/search?q=…`, the record's words in the browser.

The hits are what `logbook search` finds, through the same two functions (`search.query`, then
`search.search` over the index's FTS5 table): the same literal words, phrases and prefixes, the same
bm25 ranking, a retracted line never a hit. They are held to the page's tier gate as every other page
holds its lines (`reading.crossing` over `Site.tiers`): the search runs up to the gate's highest tier
and each hit is then let through the gate itself, so a gate of tiers 1 and 3 shows no tier 2. `logbook
serve` reads every tier, as its Day and `/line/ID` do, since nothing leaves this machine; a gated
`Site` (`tiers`) reads only those.

Each hit is a row under its day (the date a link to the Day, the time a link to the hit's own row on
it), with its kind, an excerpt of up to sixteen words around the match with every matching word in
`<mark>` (the snippet `search` prints in brackets), and its line's id, a link to `/line/ID`. The rank
decides which page a hit is on; on its page the hits are read by day, the latest first, as the
command prints them. A page holds `PAGE` hits; the pages, and the filters by kind and by year, are
links, never state in the browser: `?q=&kind=&year=&page=`. The filters count the hits the gate lets
through (one grouped query over the same table, `_facets`), and a kind or a year with none is not
offered. An empty query is the form and nothing else; a query that finds nothing says so in one
sentence.

A GET form only: nothing is written, no script, nothing fetched, no reference but the server's own
paths; the page carries the Day's tokens and type (`TOKENS`, copied from `serve.STYLE`, which a test
holds equal) and the server's one stylesheet, phone width first, every link and control a 44 px
target. No person is a filter and no number stands beside a name: the page counts kinds, years and
hits. Superseded lines are hits as `show` prints both (`docs/search.md`); their mark is not on main
yet, and `_superseded` is where it goes. An exported site (`export site`) has no server to ask, and
its search is one sentence."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from html import escape
from typing import TYPE_CHECKING
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from ..core import reading, search
from ..core.chain import Line
from ..core.index import RETRACTED, SEARCH, Index

if TYPE_CHECKING:  # the Site passes itself; serve imports this module, never the other way at import
    from .serve import Site

PAGE = 50  # hits a page
MAX_PAGE = 20  # the last page asked for: a search reads every hit up to its page, so 1,000 at most
YEAR = re.compile(r"^\d{4}$")
DOT = " · "
MARKED = re.compile(re.escape(search.MARK[0]) + r"([^\[\]]+?)" + re.escape(search.MARK[1]))
# the Day page's tokens, copied from `serve.STYLE` (tests/test_search_page.py holds them equal)
TOKENS = """
:root{color-scheme:light dark;--fg:#1c1c1c;--bg:#fff;--mute:#6a6a6a;--line:#ddd;--accent:#2f5d7c}
@media (prefers-color-scheme:dark){
:root{--fg:#e8e8e8;--bg:#141414;--mute:#9b9b9b;--line:#333;--accent:#8fb8d6}}
"""
SEARCH_STYLE = (
    TOKENS
    + """form.search{display:flex;gap:.5rem;margin:0 0 1rem}
form.search input{flex:1 1 auto;min-width:0;min-height:2.75rem;box-sizing:border-box;padding:0 .6rem}
form.search button{flex:none;min-height:2.75rem;min-width:2.75rem;padding:0 1rem}
p.facets{margin:0;color:var(--mute);font-size:.9rem}
p.facets a,p.pager a{display:inline-block;min-height:2.75rem;line-height:2.75rem;padding:0 .4rem;
min-width:2.75rem;box-sizing:border-box}
p.facets b{display:inline-block;padding:0 .4rem;color:var(--fg)}
p.facets span.n{font-variant-numeric:tabular-nums}
section.day h2 a{display:inline-block;min-height:2.75rem;line-height:2.75rem}
ol.hits{list-style:none;padding:0;margin:0}
li.hit{padding:.4rem 0;border-bottom:1px solid var(--line);overflow-wrap:anywhere}
li.hit a.at{display:inline-block;min-height:2.75rem;line-height:2.75rem;min-width:2.75rem;
font-variant-numeric:tabular-nums}
li.hit q.excerpt{display:block;quotes:none;margin:.1rem 0}
li.hit mark{background:color-mix(in srgb,var(--accent) 25%,var(--bg));color:inherit;padding:0 .1rem}
li.hit a.id{display:inline-block;min-height:2.75rem;line-height:2.75rem;
font:.78rem/2.75rem ui-monospace,monospace;color:var(--mute);overflow-wrap:anywhere}
li.hit .superseded{color:var(--mute);font-size:.85rem}
@media (max-width:40rem){form.search button{padding:0 .6rem}li.hit .kind{min-width:0;margin-right:.4rem}}
"""
)
NOTHING = "Nothing in the record matches {text}."  # a query with no hit: one sentence
PAST = "Page {page} is past the last hit."  # a page asked for beyond them
NO_SERVER = "Search answers in logbook serve, on this machine; an exported site has no server to ask."


def page_search(site: Site, params: Mapping[str, str]) -> str:
    """`/search?q=&kind=&year=&page=`: the form, then the hits of page `page` (1 to `MAX_PAGE`) held
    to the gate, the filters by kind and year as links with their counts, and the pages as links.
    `ValueError` (a 400) for a kind with no words, a year that is not one, a page that is not one."""
    if site.static:
        return site.document("search", f"<h1>Search</h1>\n<p>{escape(NO_SERVER)}</p>\n")
    text = params.get("q") or ""
    kind = params.get("kind") or None
    year = params.get("year") or None
    page = _page_number(params.get("page") or "1")
    if year is not None and YEAR.match(year) is None:
        raise ValueError(f"year {year}: four digits, such as 2026")
    parts = ["<h1>Search</h1>\n", _form(text)]
    if search.expression(text) is None:
        return _document(site, parts)
    q = search.query(
        text,
        since=None if year is None else f"{year}-01-01",
        until=None if year is None else f"{year}-12-31",
        kinds=None if kind is None else [kind],
        max_tier=_max_tier(site.tiers),
        limit=PAGE * page,
    )
    try:
        with site.lb.index() as idx:
            result = search.search(idx, q)
            facets = site.shared(
                ("search", q.expression, _gate(site.tiers)), lambda: _facets(idx, q, site.tiers)
            )
    except RuntimeError as e:  # a SQLite without FTS5: the index holds no search table
        parts.append(f"<p>{escape(str(e))}.</p>\n")
        return _document(site, parts)
    held = reading.crossing([hit.line for hit in result.hits], site.tiers)
    kept = {id(line) for line in held}
    hits = [hit for hit in result.hits if id(hit.line) in kept]
    shown = hits[PAGE * (page - 1) : PAGE * page]
    total = _total(facets, kind, year)
    if not shown:
        said = NOTHING.format(text=text) if not hits else PAST.format(page=page)
        parts.append(f"<p>{escape(said)}</p>\n")
        return _document(site, parts)
    top = max(int(hit.line.get("tier") or 0) for hit in hits)
    parts[0] = f"<h1>Search {site.tier_small(_plural(total, 'hit'), top)}</h1>\n"
    parts.append(_facets_html(text, kind, year, facets))
    superseded = _superseded(shown)
    tz = ZoneInfo(str(site.lb.meta["timezone"]))
    for day, on_day in search.Result(q, shown).days():
        parts.append(_day_html(site, day, on_day, superseded, tz))
    parts.append(_pager(text, kind, year, page, more=total > PAGE * page))
    return _document(site, parts)


def _document(site: Site, parts: Sequence[str]) -> str:
    return site.document("search", "".join(parts), style=SEARCH_STYLE)


def _page_number(asked: str) -> int:
    if not asked.isdigit() or not 1 <= int(asked) <= MAX_PAGE:
        raise ValueError(
            f"page {asked}: the pages run from 1 to {MAX_PAGE}; a kind or a year narrows the search"
        )
    return int(asked)


def _max_tier(tiers: Sequence[int] | None) -> int:
    """The highest tier the gate lets through: what the search runs up to (3 when it reads every one)."""
    return 3 if tiers is None else max((int(t) for t in tiers), default=0) or 1


def _gate(tiers: Sequence[int] | None) -> tuple[int, ...]:
    return (1, 2, 3) if tiers is None else tuple(sorted({int(t) for t in tiers}))


def _form(text: str) -> str:
    return (
        '<form class="search" method="get" action="/search">'
        f'<input type="search" name="q" value="{escape(text)}" aria-label="words to search the record for"'
        ' placeholder="words, &quot;a phrase&quot;, kar*">'
        "<button>Search</button></form>\n"
    )


# -- the filters -----------------------------------------------------------------------------------------


Facets = dict[tuple[str, str], int]  # (kind, year) → the hits the gate lets through


def _facets(idx: Index, q: search.Query, tiers: Sequence[int] | None) -> Facets:
    """The hits of `q`'s words in the whole record by kind and year, through the gate: one grouped
    query over the search table, no rank and no snippet, a retracted line left out as `Index.search`
    leaves it out. A kind of two spellings is counted under its newer one (`_folded`)."""
    gate = _gate(tiers)
    found = idx.db.execute(
        f"SELECT {SEARCH}.kind, substr({SEARCH}.day, 1, 4), count(*) FROM {SEARCH}"
        f" JOIN lines l ON l.seq = {SEARCH}.rowid"
        f" WHERE {SEARCH} MATCH ? AND {SEARCH}.tier IN ({', '.join('?' * len(gate))})"
        f" AND l.id NOT IN ({RETRACTED}) GROUP BY 1, 2",
        (q.expression, *gate),
    ).fetchall()
    counted: Facets = {}
    for kind, year, n in found:
        key = (_folded(str(kind)), str(year))
        counted[key] = counted.get(key, 0) + int(n)
    return counted


def _total(facets: Facets, kind: str | None, year: str | None) -> int:
    """The hits the gate lets through for the filters in force: what the header counts and the pager
    reads."""
    asked = None if kind is None else _folded(kind)
    return sum(
        n for (k, y), n in facets.items() if (asked is None or k == asked) and (year is None or y == year)
    )


def _href(text: str, kind: str | None, year: str | None, page: int = 1) -> str:
    params = [("q", text)]
    if kind is not None:
        params.append(("kind", kind))
    if year is not None:
        params.append(("year", year))
    if page > 1:
        params.append(("page", str(page)))
    return "/search?" + urlencode(params)


def _facets_html(text: str, kind: str | None, year: str | None, facets: Facets) -> str:
    """The filters as links: each kind the words are found in (the most hits first), counted in the
    year asked for, and each year (the latest first), counted in the kind asked for; the filter in
    force in bold, and `every` a link that takes it off."""
    asked = None if kind is None else _folded(kind)
    by_kind: dict[str, int] = {}
    by_year: dict[str, int] = {}
    for (k, y), n in facets.items():
        if year is None or y == year:
            by_kind[k] = by_kind.get(k, 0) + n
        if asked is None or k == asked:
            by_year[y] = by_year.get(y, 0) + n
    kinds = [(k, by_kind[k], _href(text, k, year)) for k in sorted(by_kind, key=lambda k: (-by_kind[k], k))]
    years = [(y, by_year[y], _href(text, kind, y)) for y in sorted(by_year, reverse=True)]
    return (
        f'<p class="facets">kind: {_choices(asked, kinds, _href(text, None, year))}</p>\n'
        f'<p class="facets">year: {_choices(year, years, _href(text, kind, None))}</p>\n'
    )


def _choices(asked: str | None, choices: Sequence[tuple[str, int, str]], every: str) -> str:
    out = ["<b>every</b>" if asked is None else _link("every", every)]
    for value, n, href in choices:
        label = f'{escape(value)} <span class="n">{n:,}</span>'
        out.append(f"<b>{label}</b>" if value == asked else _link(label, href))
    return " ".join(out)


def _folded(kind: str) -> str:
    """A kind of two spellings (RFC 0031) under its newer one: `trip` is counted as `journey`."""
    return search.ALIASES.get(kind, (kind,))[-1]


def _link(label: str, href: str) -> str:
    return f'<a href="{escape(href)}">{label}</a>'


# -- the hits --------------------------------------------------------------------------------------------


def _superseded(hits: Sequence[search.Hit]) -> dict[str, str]:
    """The mark of each shown hit that a later line supersedes, by line id: what the hit's row says
    beside its kind. Empty until `search` marks superseded hits (fix/search-marks-superseded, built
    beside this page): this is the one place that mark is read, and `_hit_html` already shows it."""
    return {}


def _day_html(
    site: Site, day: str, hits: Sequence[search.Hit], superseded: Mapping[str, str], tz: ZoneInfo
) -> str:
    head = site.link(f"{escape(day)} {escape(search.weekday(day))}", f"/day/{day}")
    rows = "".join(_hit_html(site, day, hit, superseded.get(str(hit.line["id"])), tz) for hit in hits)
    return f'<section class="day">\n<h2>{head}</h2>\n<ol class="hits">\n{rows}</ol>\n</section>\n'


def _hit_html(site: Site, day: str, hit: search.Hit, superseded: str | None, tz: ZoneInfo) -> str:
    """One hit: its time, a link to its row on its Day; its kind; the excerpt, the match marked; its
    line's id, a link to the line as written; and, when a later line supersedes it, that mark."""
    line = hit.line
    line_id = str(line["id"])
    at = site.link(escape(f"{day} {_clock(line, tz)}"), f"/day/{day}#{_row_id(line_id)}", "at")
    kind = f'<span class="kind">{escape(str(line["kind"]))}</span>'
    mark = "" if superseded is None else f' <span class="superseded">{escape(superseded)}</span>'
    return (
        f'<li class="hit" id="{_row_id(line_id)}">{at} {kind}{mark}'
        f'<q class="excerpt">{marked(hit.snippet)}</q>'
        f"{site.link(escape(line_id), f'/line/{line_id}', 'id')}</li>\n"
    )


def marked(snippet: str) -> str:
    """The snippet as HTML: escaped, each word `search` bracketed (`search.MARK`) in `<mark>`."""
    return MARKED.sub(r"<mark>\1</mark>", escape(snippet, quote=False))


def _clock(line: Line, tz: ZoneInfo) -> str:
    """The line's local time, in its own zone when it carries one."""
    try:
        at = datetime.fromisoformat(str(line["at"]).replace("Z", "+00:00"))
        zone = ZoneInfo(str(line["tz"])) if line.get("tz") else tz
    except (ValueError, KeyError):
        return ""
    return at.astimezone(zone).strftime("%H:%M")


def _row_id(line_id: str) -> str:
    """The anchor of a line's row on the Day (`serve._row_id`, the same rule)."""
    return "l-" + re.sub(r"[^A-Za-z0-9-]", "", line_id)


def _pager(text: str, kind: str | None, year: str | None, page: int, more: bool) -> str:
    """The pages as links, the one before and the one after; nothing when every hit is on this one."""
    if page == 1 and not more:
        return ""
    links = []
    if page > 1:
        links.append(_link(f"← page {page - 1}", _href(text, kind, year, page - 1)))
    links.append(f"page {page}")
    if more and page < MAX_PAGE:
        links.append(_link(f"page {page + 1} →", _href(text, kind, year, page + 1)))
    return f'<p class="pager">{DOT.join(links)}</p>\n'


def _plural(n: int, noun: str) -> str:
    return f"{n:,} {noun}" if n == 1 else f"{n:,} {noun}s"
