"""The Library's search (`logbook serve`): `/search?q=…`, the record's words in the browser.

The hits are what `logbook search` finds, through the same two functions (`search.query`, then
`search.search` over the index's FTS5 table): the same literal words, phrases and prefixes, the same
bm25 ranking, a retracted line never a hit. They are held to the page's tier gate as every other page
holds its lines (`reading.crossing` over `Site.tiers`): the search runs up to the gate's highest tier
and each hit is then let through the gate itself, so a gate of tiers 1 and 3 shows no tier 2 (and
searches further, `_gated`, until its page is full). `logbook
serve` reads every tier, as its Day and `/line/ID` do, since nothing leaves this machine; a gated
`Site` (`tiers`) reads only those.

Each hit is a row under its day (the date a link to the Day, the time a link to it too, to the hit's
own row there for the kinds the Day lists as rows, `ROWED`), with its kind, an excerpt of up to
sixteen words around the match with every matching word in `<mark>` (the snippet `search` prints in
brackets; a bracket the record itself holds stays as written, `marked`), and its line's id, a link
to `/line/ID`. The rank
decides which page a hit is on; on its page the hits are read by day, the latest first, as the
command prints them. A page holds `PAGE` hits; the pages, and the filters by kind and by year, are
links, never state in the browser: `?q=&kind=&year=&page=`. The filters are every kind with words
and every year the record runs over, never counted: a count would cost the matches of the words a
second time, and would say how many lines a gate holds back. An empty query is the form and nothing
else; a query, or a filter, that finds nothing says so in one sentence.

A GET form only: nothing is written, no script, nothing fetched, no reference but the server's own
paths; the page carries the Day's tokens and type (`TOKENS`, copied from `serve.STYLE`, which a test
holds equal) and the server's one stylesheet, phone width first, every link and control a 44 px
target. No person is a filter and no number stands beside a name: the page counts nothing but its pages.
A hit a later line of its kind supersedes is still a hit, marked as `logbook search` marks it,
`superseded by #N`, a link to that line, when the gate lets that line through (`_superseded`). An
exported site (`export site`) has no server to ask, and
its search is one sentence."""

from __future__ import annotations

import dataclasses
import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import datetime
from html import escape
from typing import TYPE_CHECKING
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from ..core import reading, search
from ..core.chain import Line
from ..core.index import Index

if TYPE_CHECKING:  # the Site passes itself; serve imports this module, never the other way at import
    from .serve import Site

PAGE = 50  # hits a page
WIDEN = 16  # how far past a page `_gated` searches for hits a gate of some tiers lets through
MAX_PAGE = 20  # the last page asked for: a search reads every hit up to its page, so 1,000 at most
YEAR = re.compile(r"^\d{4}$")
DOT = " · "
ROWED = frozenset({"note", "mail", "event"})  # the kinds whose line the Day lists as a row of its own, `l-ID`
STROKES = str.maketrans({"ø": "o", "đ": "d", "ł": "l", "ħ": "h"})  # letters `unicode61` folds, NFKD not
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
li.hit .superseded a{display:inline-block;min-height:2.75rem;line-height:2.75rem}
@media (max-width:40rem){form.search button{padding:0 .6rem}li.hit .kind{min-width:0;margin-right:.4rem}}
"""
)
PAST = "Page {page} is past the last hit."  # a page asked for beyond them
NO_SERVER = "Search answers in logbook serve, on this machine; an exported site has no server to ask."


def page_search(site: Site, params: Mapping[str, str]) -> str:
    """`/search?q=&kind=&year=&page=`: the form, then the hits of page `page` (1 to `MAX_PAGE`) held
    to the gate, the filters by kind and year as links, and the pages as links. `ValueError` (a 400)
    for a kind with no words, a year that is not one, a page that is not one."""
    if site.static:
        return site.document("search", f"<h1>Search</h1>\n<p>{escape(NO_SERVER)}</p>\n")
    text = params.get("q") or ""
    kind = params.get("kind") or None
    year = params.get("year") or None
    page = _page_number(params.get("page") or "1")
    if year is not None and YEAR.fullmatch(year) is None:
        raise ValueError(f"year {year}: four digits, such as 2026")
    if kind is not None and kind not in search.KINDS:
        raise search.QueryError(
            f"{kind}: not a kind with words; the kinds searched are {', '.join(search.KINDS)}"
        )
    parts = ["<h1>Search</h1>\n", _form(text)]
    if search.expression(text) is None:
        return _document(site, parts)
    q = search.query(
        text,
        since=None if year is None else f"{year}-01-01",
        until=None if year is None else f"{year}-12-31",
        kinds=None if kind is None else [kind],
        max_tier=_max_tier(site.tiers),
    )
    try:
        with site.lb.index() as idx:
            hits, more = _gated(idx, q, site.tiers, PAGE * page)
            years = _years(idx)
            superseded = _superseded(idx, hits[PAGE * (page - 1) : PAGE * page], site.tiers)
    except RuntimeError as e:  # a SQLite without FTS5: the index holds no search table
        parts.append(f"<p>{escape(str(e))}.</p>\n")
        return _document(site, parts)
    shown = hits[PAGE * (page - 1) : PAGE * page]
    if shown or kind is not None or year is not None:  # a filter that found nothing can be taken off
        parts.append(_filters(text, kind, year, years))
    if not shown:
        said = _nothing(text, kind, year) if not hits else PAST.format(page=page)
        parts.append(f"<p>{escape(said)}</p>\n")
        return _document(site, parts)
    top = max(int(hit.line.get("tier") or 0) for hit in shown)
    parts[0] = f"<h1>Search {site.tier_small(f'page {page}{DOT}the best by rank', top)}</h1>\n"
    tz = ZoneInfo(str(site.lb.meta["timezone"]))
    for day, on_day in search.Result(q, shown).days():
        parts.append(_day_html(site, day, on_day, superseded, tz, text))
    parts.append(_pager(text, kind, year, page, more))
    return _document(site, parts)


def _gated(
    idx: Index, q: search.Query, tiers: Sequence[int] | None, wanted: int
) -> tuple[list[search.Hit], bool]:
    """The best `wanted` hits of `q` the gate lets through (`reading.crossing`), and whether there
    are more. The search runs up to the gate's highest tier, so a gate that is not every tier from 1
    up (tiers 1 and 3) leaves some of the hits out after the search's own limit: the limit is then
    widened, up to `WIDEN` times what the page needs, until the page is full or the matches end."""
    limit = wanted + 1  # one more than the page shows: whether there is a next page
    while True:
        result = search.search(idx, dataclasses.replace(q, limit=limit))
        held = {id(line) for line in reading.crossing([hit.line for hit in result.hits], tiers)}
        hits = [hit for hit in result.hits if id(hit.line) in held]
        if len(hits) > wanted or not result.full or limit >= wanted * WIDEN:
            return hits[:wanted], len(hits) > wanted or result.full
        limit *= 4


def _nothing(text: str, kind: str | None, year: str | None) -> str:
    """The one sentence of a search that finds nothing; the year first, never beside the words."""
    said = f"othing in the record matches {text}" + ("" if kind is None else f" as a {kind}") + "."
    return ("N" if year is None else f"In {year}, n") + said


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


def _form(text: str) -> str:
    return (
        '<form class="search" method="get" action="/search">'
        f'<input type="search" name="q" value="{escape(text)}" aria-label="words to search the record for"'
        ' placeholder="words, &quot;a phrase&quot;, kar*">'
        "<button>Search</button></form>\n"
    )


# -- the filters -----------------------------------------------------------------------------------------


def _years(idx: Index) -> list[str]:
    """The years the record's local days run over, the latest first: the first and the last
    `day_local`, each one lookup in its index (a single min or max; `Index.span`, both in one
    statement, reads every row, half a second on five million lines)."""
    first = idx.db.execute("SELECT min(day_local) FROM lines").fetchone()[0]
    last = idx.db.execute("SELECT max(day_local) FROM lines").fetchone()[0]
    if first is None or last is None:
        return []
    return [str(y) for y in range(int(str(last)[:4]), int(str(first)[:4]) - 1, -1)]


def _href(text: str, kind: str | None, year: str | None, page: int = 1) -> str:
    params = [("q", text)]
    if kind is not None:
        params.append(("kind", kind))
    if year is not None:
        params.append(("year", year))
    if page > 1:
        params.append(("page", str(page)))
    return "/search?" + urlencode(params)


def _filters(text: str, kind: str | None, year: str | None, years: Sequence[str]) -> str:
    """The filters as links, never counted: every kind with words (`search.KINDS`, a kind of two
    spellings under its newer one) and every year the record runs over; the filter in force in
    bold, and `every` a link that takes it off. A count would cost the matches of the words a second
    time (the search table's kind and day are read per match), and a filter that finds nothing says
    so in its sentence."""
    asked = None if kind is None else _folded(kind)
    kinds = [k for k in search.KINDS if _folded(k) == k]
    by_kind = _choices(asked, [(k, _href(text, k, year)) for k in kinds], _href(text, None, year))
    by_year = _choices(year, [(y, _href(text, kind, y)) for y in years], _href(text, kind, None))
    return f'<p class="facets">kind: {by_kind}</p>\n<p class="facets">year: {by_year}</p>\n'


def _choices(asked: str | None, choices: Sequence[tuple[str, str]], every: str) -> str:
    out = ["<b>every</b>" if asked is None else _link("every", every)]
    out += [
        f"<b>{escape(value)}</b>" if value == asked else _link(escape(value), href) for value, href in choices
    ]
    return " ".join(out)


def _folded(kind: str) -> str:
    """A kind of two spellings (RFC 0031) under its newer one: `trip` is offered as `journey`."""
    return search.ALIASES.get(kind, (kind,))[-1]


def _link(label: str, href: str) -> str:
    return f'<a href="{escape(href)}">{label}</a>'


# -- the hits --------------------------------------------------------------------------------------------


Superseded = Mapping[str, tuple[str, str]]  # a hit's line id → the words of its mark, the superseder's id


def _superseded(idx: Index, hits: Sequence[search.Hit], tiers: Sequence[int] | None) -> Superseded:
    """The mark of each shown hit that a later line of its kind supersedes (`Hit.superseded_by`,
    which `search.search` asks of the index): the words `logbook search` marks it with
    (`search.mark`) and the superseding line's id, which the mark links to. Only when the gate lets
    the superseding line through, as `/line/ID` would show it: a correction above the gate is no
    mark, and the hit reads as the page would read it without that line."""
    by = {str(hit.line["id"]): hit.superseded_by for hit in hits if hit.superseded_by is not None}
    if not by:
        return {}
    found = idx.by_seqs(seq for seq, _id in by.values())
    held = {str(line["id"]) for line in reading.crossing(found.values(), tiers)}
    words = {str(hit.line["id"]): search.mark(hit).removeprefix(search.FIELD_BREAK) for hit in hits}
    return {line_id: (words[line_id], later) for line_id, (_seq, later) in by.items() if later in held}


def _day_html(
    site: Site, day: str, hits: Sequence[search.Hit], superseded: Superseded, tz: ZoneInfo, text: str
) -> str:
    head = site.link(f"{escape(day)} {escape(search.weekday(day))}", f"/day/{day}")
    terms = _terms(text)
    rows = "".join(_hit_html(site, day, hit, superseded.get(str(hit.line["id"])), tz, terms) for hit in hits)
    return f'<section class="day">\n<h2>{head}</h2>\n<ol class="hits">\n{rows}</ol>\n</section>\n'


def _hit_html(
    site: Site, day: str, hit: search.Hit, superseded: tuple[str, str] | None, tz: ZoneInfo, terms: Terms
) -> str:
    """One hit: its time, a link to its Day (to its row there, for the kinds the Day gives a row,
    `ROWED`); its kind; the excerpt, the match marked; its line's id, a link to the line as written;
    and, when a later line supersedes it, that mark."""
    line = hit.line
    line_id = str(line["id"])
    row = f"#{_row_id(line_id)}" if line.get("kind") in ROWED else ""
    at = site.link(escape(f"{day} {_clock(line, tz)}"), f"/day/{day}{row}", "at")
    kind = f'<span class="kind">{escape(str(line["kind"]))}</span>'
    mark = (
        ""
        if superseded is None
        else f' <span class="superseded">{site.link(escape(superseded[0]), f"/line/{superseded[1]}")}</span>'
    )
    return (
        f'<li class="hit" id="{_row_id(line_id)}">{at} {kind}{mark}'
        f'<q class="excerpt">{marked(hit.snippet, terms)}</q>'
        f"{site.link(escape(line_id), f'/line/{line_id}', 'id')}</li>\n"
    )


# -- the mark ---------------------------------------------------------------------------------------------


Terms = tuple[frozenset[str], tuple[str, ...]]  # the query's words, folded; and its prefixes


def marked(snippet: str, terms: Terms) -> str:
    """The snippet as HTML, escaped, each run `search` bracketed (`search.MARK`) in `<mark>` when its
    words are the query's (`_terms`): a bracket the record itself holds (`[urgent]` in a note) stays
    as written, since the snippet's marks and the text's own brackets are the same characters."""
    out: list[str] = []
    at = 0
    for m in MARKED.finditer(snippet):
        out.append(escape(snippet[at : m.start()], quote=False))
        words = _tokens(m.group(1))
        ours = bool(words) and all(w in terms[0] or w.startswith(terms[1]) for w in words)
        out.append(
            f"<mark>{escape(m.group(1), quote=False)}</mark>" if ours else escape(m.group(0), quote=False)
        )
        at = m.end()
    out.append(escape(snippet[at:], quote=False))
    return "".join(out)


def _terms(text: str) -> Terms:
    """The words of a query as the index's tokeniser reads them (`_tokens`), and the prefixes (a
    term's last word before a `*`), as `search.expression` parses the query."""
    words: set[str] = set()
    prefixes: list[str] = []
    for phrase, word in search.TERM.findall(text):
        term = phrase or word
        found = _tokens(term.rstrip("*"))
        if term.endswith("*") and found:
            prefixes.append(found.pop())
        words.update(found)
    return frozenset(words), tuple(prefixes)


def _tokens(text: str) -> list[str]:
    """The words of `text` as `unicode61` folds them: case, then diacritics (ø and å to o and a)."""
    plain = unicodedata.normalize("NFKD", text.casefold().translate(STROKES))
    return re.findall(r"[^\W_]+", "".join(ch for ch in plain if not unicodedata.combining(ch)))


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
