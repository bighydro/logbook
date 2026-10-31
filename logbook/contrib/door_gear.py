"""The gear (RFC 0047 §4.6, §5): the machinery behind one icon at the end of the header, at `/gear`, in
the machine's own words (RFC 0047 §3.5 allows them here, and nowhere else).

`/gear` is one card per part, each with one line of state, then the old shelves a link away (`/shelves`,
"Every shelf, as before"; the full list of promises and the Ideas shelf stay there, the captain's answers
of 25 October 2026):

- **Sources** (`/gear/sources`): one row per source, what it sent and the day of its last line (a link to
  that Day), a source quiet for `QUIET_DAYS` or more marked, and the command that brings it back when the
  docs name one (`command`: `logbook sync NAME` for a live adapter, `logbook add NAME <file>` for a file
  adapter); a source `policy/import.json` turns off says so. The machine side of `/gaps`, and `doctor
  sources`' list; `?quiet=1` the quiet ones alone. `/gaps` stays, its table a link away.
- **Crossings** (`/gear/crossings`): every standing `crossing/v1` line, the newest first, each with its
  destination, the tiers that crossed, the kinds and the lines it counted, the policy entry it crossed
  under, and a link to the line itself (`/line/ID`); `?to=DESTINATION` one destination's, `?page=N`
  `PAGE` at a time.
- **Agents**, **the Manifest** and **Assets** (`/gear/agents`, `/gear/manifest`, `/gear/manifest/people`,
  `/gear/org/ID`, `/gear/assets`): the old page at the old address, its contents exactly (the Site renders
  it, `Site._page`), with one line at the top that leads back to the gear (`crumbed`). Its links and its
  forms are the old page's: the forms post to the routes they always posted to.
- **The build** (`/gear/build`): when the pages were last built, how long it took, the doors and shelves
  each with when it was built and, for the slowest, the seconds it took, and the command that builds them
  again, from `pages.json` (`library_build.Library.built`) and the serve service `serve --status` names;
  on a machine that never built them, one sentence that the Library renders every page live and how to
  try the build lab.

What a page shows is held to the Library's gate (`Site.tiers`, as `reading.crossing` reads it): a source
whose every line is above it is no row and no count, and a crossing that carried a tier above it counts
only its lines at the tiers the page reads, and names no kind. The owner's own server reads every tier.

Speed (RFC 0047 §8): every reading is one the Library keeps for the record as it stands (`Site.shared`):
the sources the kept activity of `/gaps` (`gaps.activity_of`, brought forward by the lines added since),
the crossings the index's few lines of one kind, the agents' sessions and the orgs the readings `/agents`
and `/manifest` read, under the same keys, so a visit to the gear and then to one of its parts reads
once. Under a gate, the sources are one aggregate over the index's columns, nothing read from the files.
The sub-pages are built with the rest (`library_build.DOORS`); `/gear` and `/gear/build` say how the build
stands now, and are always rendered (`library_build.LIVE_PAGES`).

Nothing here writes, and nothing is fetched: no script, no font but the Library's own, no address but
the server's. The gear is not in an exported site (`export site`): its header leaves the icon out."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..core import assets, crossing, day_start, policy, reading, stays
from ..core.store import retractions
from . import day_rhythm, door_today, doors, gaps, library_build, shelf_agents

if TYPE_CHECKING:  # the Site passes itself; serve imports this module, never the other way at import
    from ..core.chain import Line
    from .serve import Site

GEAR = doors.GEAR
SOURCES, CROSSINGS, BUILD = f"{GEAR}/sources", f"{GEAR}/crossings", f"{GEAR}/build"
AGENTS, MANIFEST, MANIFEST_PEOPLE, ASSETS = (
    f"{GEAR}/agents",
    f"{GEAR}/manifest",
    f"{GEAR}/manifest/people",
    f"{GEAR}/assets",
)
ORG_PATH = re.compile(r"^/gear(/org/[^/]+)$")  # an org's page, in the gear: the old `/org/ID`
OLD = {AGENTS: "/agents", MANIFEST: "/manifest", MANIFEST_PEOPLE: "/manifest/people", ASSETS: "/assets"}
FRAMED = frozenset({GEAR, SOURCES, CROSSINGS, BUILD})  # the gear's own pages, in the doors' frame
RECORD_PAGES = frozenset({SOURCES, CROSSINGS, AGENTS, MANIFEST, MANIFEST_PEOPLE})  # tagged by the record
CLOCK_PAGES = (SOURCES, MANIFEST, f"{GEAR}/org/")  # and by the record's today
QUIET_DAYS = 7  # a source whose last line is this many days before today is quiet
PAGE = 50  # crossings a page
# the product's own destinations, said by name; any other is a member of the owner's circle (`share day`,
# `export crossing --to`), a person, never named on the gear
OWN = frozenset(policy.RESERVED)  # the names the policy keeps for its own readers and doors (#438)
MEMBER = "a member of your circle"
CIRCLE, CIRCLE_PILL = "circle", "Your circle"  # the filter of every member's crossing, and its pill
DOT = day_rhythm.DOT
PARTS = (  # the cards of `/gear`, in order: address, name, what it is
    (SOURCES, "Sources", "What each source sent, and when it last spoke."),
    (CROSSINGS, "Crossings", "What left this machine, when, to where, under which policy entry."),
    (AGENTS, "Agents", "Your sessions with your own agents, by day."),
    (MANIFEST, "The Manifest", "The orgs you named, and who appears with more than one org."),
    (ASSETS, "Assets", "The boats, cars and aircraft the record tracks, and their last fix."),
    (BUILD, "The build", "When the pages were last built, how long it took, and how to build them again."),
)
NAMES = {address: name for address, name, _what in PARTS}
SHELVES = (  # the old shelves, a link away
    ("/shelves", "Every shelf, as before"),
    ("/promises", "Every promise"),
    ("/ideas", "The Ideas shelf"),
    ("/gaps", "Where each source went quiet, as a table"),
)
NEVER_BUILT = (
    "Nothing is built ahead on this machine: the Library renders every page live, as it is asked for, and"
    " <code>logbook serve --built</code> tries the build lab, which builds every door and shelf ahead and"
    " answers from them (docs/serve.md, Built ahead)."
)
STYLE = """
.door-gear{font-size:.9375rem;color:var(--ink,#16181D)}
.door-gear p{margin:0 0 1rem}
.door-gear .eyebrow,.door-gear .label{margin:0 0 .5rem;color:var(--pencil,#62666D);font-weight:500;
font-size:.75rem;line-height:1.4;letter-spacing:.13em;text-transform:uppercase;
font-family:var(--mono,'JetBrains Mono',ui-monospace,monospace)}
.door-gear .eyebrow a{text-decoration:none}
.door-gear h1{margin:0 0 .9rem;font-weight:400;font-size:4.5rem;line-height:1;
font-family:var(--serif,'Instrument Serif',Georgia,serif)}
.door-gear h2{margin:2.4rem 0 .8rem;font-weight:400;font-size:2.25rem;line-height:1.1;
font-family:var(--serif,'Instrument Serif',Georgia,serif)}
.door-gear p.lede{max-width:34rem;color:var(--pencil,#62666D);font-size:1rem}
.door-gear p.empty{padding:1.75rem;border:1px solid var(--line,#E3DED3);border-radius:20px;
background:var(--surface,#FBFAF6);color:var(--pencil,#62666D)}
.door-gear code{font-size:.8125rem;font-family:var(--mono,'JetBrains Mono',ui-monospace,monospace);
white-space:nowrap;overflow-wrap:anywhere}
.door-gear p.pills{display:flex;flex-wrap:wrap;gap:.5rem;margin:0 0 1.8rem}
.door-gear p.pills a,.door-gear p.pills b{display:inline-flex;align-items:center;
min-height:44px;padding:0 1.1rem;border-radius:23px;border:1px solid var(--line,#E3DED3);
background:var(--surface,#FBFAF6);font-weight:500;font-size:.875rem;text-decoration:none;
color:var(--pencil,#62666D)}
.door-gear p.pills a:hover{color:var(--ink,#16181D);
background:var(--tint,#EDE8DE)}
.door-gear p.pills b{background:var(--ink,#16181D);
border-color:var(--ink,#16181D);color:var(--paper,#F4F1EA)}
.door-gear div.cards{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin:1.6rem 0 2rem}
.door-gear a.card{display:flex;flex-direction:column;min-height:44px;padding:1.9rem;border-radius:20px;
border:1px solid var(--line,#E3DED3);background:var(--surface,#FBFAF6);text-decoration:none;
overflow-wrap:anywhere}
.door-gear a.card:hover{border-color:var(--pencil-rule,#8C8F95)}
.door-gear a.card span{display:block}
.door-gear a.card span.title{margin:0 0 .35rem;font-weight:400;font-size:1.5rem;line-height:1.15;
font-family:var(--serif,'Instrument Serif',Georgia,serif)}
.door-gear a.card span.what{margin:0 0 1rem;color:var(--pencil,#62666D);font-size:.8125rem}
.door-gear a.card span.state{margin-top:auto;padding-top:.8rem;border-top:1px solid var(--line-soft,#ECE7DD);
color:var(--pencil,#62666D);font-size:.8125rem;font-variant-numeric:tabular-nums}
.door-gear a.card em.owed{font-style:normal;color:var(--signal-deep,#A93413)}
.door-gear ul.more{list-style:none;margin:0;padding:0;border-top:1px solid var(--line,#E3DED3)}
.door-gear ul.more li{border-bottom:1px solid var(--line-soft,#ECE7DD)}
.door-gear ul.more a{display:flex;align-items:center;min-height:44px;padding:.5rem 0;text-decoration:none}
.door-gear ul.more a:hover{text-decoration:underline}
.door-gear ul.rows{list-style:none;margin:0 0 1.5rem;padding:0;border-top:1px solid var(--line,#E3DED3)}
.door-gear li.row{padding:1rem 0;border-bottom:1px solid var(--line-soft,#ECE7DD);overflow-wrap:anywhere}
.door-gear li.row span{display:block}
.door-gear li.row span.name{font-weight:400;font-size:1.375rem;line-height:1.25;
font-family:var(--serif,'Instrument Serif',Georgia,serif)}
.door-gear li.row span.sub{margin-top:.2rem;color:var(--pencil,#62666D);font-size:.8125rem;
font-variant-numeric:tabular-nums}
.door-gear li.row span.cmd{margin-top:.35rem;color:var(--pencil,#62666D);font-size:.8125rem}
.door-gear li.row a{text-decoration-color:var(--pencil-rule,#8C8F95)}
.door-gear li.row span.name a,.door-gear li.row span.cmd a{display:inline-flex;align-items:center;
min-height:44px}
.door-gear li.row span.badge{display:inline-block;margin-left:.5rem;padding:.05rem .55rem;border-radius:23px;
border:1px solid var(--signal,#C8401A);color:var(--signal-deep,#A93413);font-weight:500;font-size:.6875rem;
letter-spacing:.12em;text-transform:uppercase;vertical-align:.3em;
font-family:var(--mono,'JetBrains Mono',ui-monospace,monospace)}
.door-gear li.row span.badge.off{border-color:var(--pencil-rule,#8C8F95);color:var(--pencil,#62666D)}
.door-gear li.row.quiet span.name{color:var(--ink,#16181D)}
.door-gear div.dark{margin:0 0 1.8rem;padding:1.9rem;border-radius:20px;background:var(--card-dark,#16181D);
color:var(--card-dark-text,#F4F1EA)}
.door-gear div.dark p{margin:0 0 .6rem}
.door-gear div.dark p.label{color:var(--card-dark-muted,#C9C4B8)}
.door-gear div.dark p.when{font-weight:400;font-size:1.75rem;line-height:1.15;
font-family:var(--serif,'Instrument Serif',Georgia,serif)}
.door-gear div.dark p.facts,.door-gear div.dark p.again{color:var(--card-dark-muted,#C9C4B8);
font-size:.8125rem}
.door-gear div.dark code{color:var(--card-dark-text,#F4F1EA)}
.door-gear p.pager{display:flex;flex-wrap:wrap;gap:1rem}
.door-gear p.pager a{display:inline-flex;align-items:center;min-height:44px}
@media (max-width:40rem){
.door-gear h1{font-size:2.5rem}
.door-gear h2{font-size:1.75rem}
.door-gear div.cards{grid-template-columns:1fr}
.door-gear a.card,.door-gear div.dark,.door-gear p.empty{padding:1.25rem}
}
"""


@dataclass(frozen=True)
class Source:
    """One source as the gear shows it: its lines (through the gate) and the local days of its first and
    last, how many days it has been quiet to today, what kind of adapter reads it, the command that
    brings it back, and the reason `policy/import.json` turns it off (None when it does not)."""

    name: str
    lines: int
    first: str
    last: str
    quiet: int
    adapter: str
    command: str | None
    off: str | None


def page(site: Site, path: str, params: Mapping[str, str]) -> str:
    """The gear's page at `path`; `NotFound` for an address under `/gear` that is none of them."""
    from .serve import NotFound

    if path == GEAR:
        return page_gear(site)
    if path == SOURCES:
        return page_sources(site, quiet=params.get("quiet") == "1")
    if path == CROSSINGS:
        return page_crossings(site, params.get("to") or None, params.get("page") or "1")
    if path == BUILD:
        return page_build(site)
    if path == MANIFEST_PEOPLE:
        trail = [site.link(escape(NAMES[MANIFEST]), MANIFEST), "people across orgs"]
        return crumbed(site, site._page(OLD[path], params), trail)
    if path == MANIFEST:
        trail = [escape(NAMES[MANIFEST]), site.link("people across orgs", MANIFEST_PEOPLE)]
        return crumbed(site, site._page(OLD[path], params), trail)
    if path in OLD:
        return crumbed(site, site._page(OLD[path], params), [escape(NAMES[path])])
    if (org := ORG_PATH.match(path)) is not None:
        return crumbed(site, site._page(org.group(1), params), [site.link(escape(NAMES[MANIFEST]), MANIFEST)])
    raise NotFound(f"no page at {path}")


def crumbed(site: Site, document: str, trail: Sequence[str]) -> str:
    """An old page in the gear: its document exactly, with one line at the top of its `<main>` that leads
    back to the gear, then `trail` (escaped already: the part it is in, a page beside it)."""
    said = DOT.join([site.link("The gear", GEAR), *trail])
    return document.replace("<main>\n", f'<main>\n<p class="mute gear-crumb">{said}</p>\n', 1)


# -- /gear ---------------------------------------------------------------------------------------------------


def page_gear(site: Site) -> str:
    """One card per part, each with one line of state, then the old shelves a link away."""
    found, today = sources_of(site)
    quiet = sum(1 for s in found if s.quiet >= QUIET_DAYS)
    if not found:
        said = escape(
            "No source yet: one appears here once logbook add or logbook sync brings its first line."
        )
    elif quiet:  # the quiet ones are owed: they alone in the accent, the count beside them in pencil
        said = f'{_plural(len(found), "source")}, <em class="owed">{quiet:,} quiet for a week or more</em>.'
    else:
        said = f"{_plural(len(found), 'source')}, none quiet for a week."
    states = {
        SOURCES: said,
        CROSSINGS: escape(_last_crossing(site, today)),
        AGENTS: escape(_last_session(site, today)),
        MANIFEST: escape(_orgs_named(site)),
        ASSETS: escape(_assets_registered(site)),
        BUILD: escape(_build_state(site, today)),
    }
    cards = []
    for address, name, what in PARTS:
        href = site.href(address)
        if href is None:
            continue
        cards.append(
            f'<a class="card" href="{escape(href)}"><span class="title">{escape(name)}</span>'
            f'<span class="what">{escape(what)}</span><span class="state">{states[address]}</span></a>\n'
        )
    more = "".join(f"<li>{site.link(escape(text), path)}</li>\n" for path, text in SHELVES)
    body = (
        '<div class="door-gear">\n<p class="eyebrow">The machinery</p>\n<h1>The gear</h1>\n'
        '<p class="lede">The machinery behind the record, in its own words: what each source sent, what'
        " left this machine, the agents, the Manifest, the assets and the build.</p>\n"
        f'<div class="cards">\n{"".join(cards)}</div>\n'
        f'<p class="label">The old shelves</p>\n<ul class="more">\n{more}</ul>\n</div>\n'
    )
    return doors.page(site, doors.GEAR, "the gear", body, style_=STYLE)


def _frame(site: Site, here: str, title: str, lede: str, body: str) -> str:
    """A part's page: the way back to the gear, its title, one sentence of what it is, the parts as pills
    (`here` the current one), then `body`."""
    pills = []
    for address, name, _what in PARTS:
        href = site.href(address)
        if href is None:
            continue
        here_ = address == here  # the part shown is no link, as a filter's chosen pill is not
        pills.append(f"<b>{escape(name)}</b>" if here_ else f'<a href="{escape(href)}">{escape(name)}</a>')
    html = (
        f'<div class="door-gear">\n<p class="eyebrow">{site.link("The gear", GEAR)}</p>\n'
        f"<h1>{escape(title)}</h1>\n"
        f'<p class="lede">{lede}</p>\n'
        f'<p class="pills parts">{"".join(pills)}</p>\n'
        f"{body}</div>\n"
    )
    return doors.page(site, doors.GEAR, f"{title.lower()} · the gear", html, style_=STYLE)


# -- /gear/sources -------------------------------------------------------------------------------------------


def sources_of(site: Site) -> tuple[list[Source], str]:
    """Every source with a line through the gate, the quiet ones first (the longest quiet first), then
    the rest, the latest to speak first; and the record's today. Ungated, from the kept activity `/gaps`
    reads (`gaps.report`, through `Site._activity`); under a gate, one aggregate over the index."""
    days = day_start.of(site.lb.meta)
    today = days.today(site.now()).isoformat()
    found = site.shared(("gear sources", _gate(site.tiers), today), lambda: _activity(site, today))
    off = _disabled(site.lb.root)
    from . import adapters  # the adapters' registry, loaded by the gear's pages, never by `--help`

    rows = []
    for name, lines, first, last in found:
        first_day, last_day = days.day_of(first), days.day_of(last)
        quiet = (date.fromisoformat(today) - date.fromisoformat(last_day)).days
        kind, command = adapter_of(name)
        reason = off.get(adapters.ALIASES.get(name, name))
        rows.append(
            Source(name, lines, first_day, last_day, quiet, kind, None if reason else command, reason)
        )
    rows.sort(
        key=lambda s: (s.quiet < QUIET_DAYS, -s.quiet if s.quiet >= QUIET_DAYS else 0, -_ord(s.last), s.name)
    )
    return rows, today


def _ord(day: str) -> int:
    return date.fromisoformat(day).toordinal()


def _gate(tiers: Sequence[int] | None) -> tuple[int, ...] | None:
    return None if tiers is None else tuple(sorted({int(t) for t in tiers}))


def _activity(site: Site, today: str) -> list[tuple[str, int, str, str]]:
    """(source, lines, first `at`, last `at`) of every source to `today`, through the gate."""
    gate = _gate(site.tiers)
    if gate is None:
        data = gaps.report(site.lb, activity=site._activity, instant=site.now())
        return [
            (str(s["source"]), int(s["lines"]), str(s["first"]), str(s["last"]))
            for s in data["sources"]
            if s["lines"]
        ]
    if not gate:
        return []
    marks = ", ".join("?" * len(gate))
    with site.lb.index() as idx:
        found = idx.db.execute(
            f"SELECT source, count(*), min(at), max(at) FROM lines WHERE tier IN ({marks}) AND day_local <= ?"
            " GROUP BY source ORDER BY count(*) DESC, source",
            (*gate, today),
        ).fetchall()
    return [(str(source), int(n), str(first), str(last)) for source, n, first, last in found]


def _disabled(root: Path) -> dict[str, str]:
    """The sources `policy/import.json` turns off, aliases resolved, with their reasons; none without the
    file or when it is not the shape (`doctor sources` names that). Never writes the file."""
    from . import adapters

    if not policy.import_path(root).exists():
        return {}
    try:
        listed = policy.read_disabled(root)
    except policy.PolicyError:
        return {}
    return {adapters.ALIASES.get(name, name): str(reason) for name, reason in listed.items()}


def adapter_of(source: str) -> tuple[str, str | None]:
    """What reads `source` (`live`, `file`, `live and file`, or empty for the record's own lines) and the
    command the docs name to bring it back: `logbook sync NAME` for a live adapter (a Beeper network's
    source, `beeper-whatsapp`, is the `beeper` adapter's), `logbook add NAME <file>` for a file adapter."""
    from . import adapters

    name = adapters.ALIASES.get(source, source)
    live = adapters.live(name)
    if live is None and "-" in name:
        live = adapters.live(name.split("-", 1)[0])
    file = adapters.named(name)
    kind = " and ".join(k for k, there in (("live", live), ("file", file)) if there is not None)
    if live is not None:
        return kind, f"logbook sync {live.NAME}"
    if file is not None:
        return kind, f"logbook add {file.NAME} <file>"
    return kind, None


def page_sources(site: Site, quiet: bool = False) -> str:
    """One row per source: what it sent, its last line's day, a quiet one marked, and the command that
    brings it back; `quiet` the quiet ones alone."""
    found, today = sources_of(site)
    shown = [s for s in found if s.quiet >= QUIET_DAYS] if quiet else found
    filters = [
        ("Every source", SOURCES, not quiet),
        ("Quiet for a week or more", f"{SOURCES}?quiet=1", quiet),
    ]
    pills = "".join(
        f"<b>{escape(text)}</b>" if here else site.link(escape(text), address)
        for text, address, here in filters
    )
    parts = [f'<p class="pills">{pills}</p>\n'] if found else []
    if not found:
        parts.append(
            '<p class="empty">No source has sent a line yet: a source appears here once'
            " <code>logbook add</code> or <code>logbook sync</code> brings its first line in.</p>\n"
        )
    elif not shown:
        parts.append(
            f'<p class="empty">Every source has spoken in the last {QUIET_DAYS} days, so none is quiet.</p>\n'
        )
    else:
        parts.append('<ul class="rows">\n')
        parts.extend(_source_row(site, s, today) for s in shown)
        parts.append("</ul>\n")
    gaps_link = site.link("the longest silences and the days each source missed", "/gaps")
    parts.append(f'<p class="lede">The table of {gaps_link} is where it always was.</p>\n')
    lede = (
        "What each source sent, and when it last spoke: a source quiet for a week or more is marked, with"
        " the command that brings it back when there is one."
    )
    return _frame(site, SOURCES, "Sources", lede, "".join(parts))


def _own_source(name: str) -> bool:
    """A source the record writes itself: the owner's own words (`manual`), Logbook's lines (`logbook`) and
    what its derivations infer (`keeper-inference`, `flight-inference`)."""
    return name in ("manual", "logbook") or name.endswith("-inference")


def _nb(text: str) -> str:
    """`text`, escaped, its spaces no place to break a line: a date stays whole on a phone."""
    return escape(text).replace(" ", "&nbsp;")


def _source_row(site: Site, s: Source, today: str) -> str:
    quiet = s.quiet >= QUIET_DAYS
    badge = '<span class="badge">quiet</span>' if quiet else ""
    if s.off is not None:
        badge += '<span class="badge off">off</span>'
    last = site.link(_nb(_day(s.last, today)), f"/day/{s.last}")
    spoke = f"last spoke {last}"
    if quiet:
        spoke += f", {s.quiet:,} days ago"
    sent = f"{_plural(s.lines, 'line')} since {_nb(_day(s.first, today))}"
    sub = DOT.join([spoke, sent] + ([escape(f"read by its {s.adapter} adapter")] if s.adapter else []))
    if s.off is not None:
        cmd = f"turned off in {escape(policy.IMPORT_FILE.as_posix())}: {escape(s.off)}"
    elif s.command is not None:
        cmd = f"<code>{escape(s.command)}</code> {'brings it back' if quiet else 'brings what is new'}"
    elif _own_source(s.name):
        cmd = "written on this machine, by you or by Logbook's own readings: no sync brings it back"
    else:
        cmd = "no adapter here reads it, so no command brings it back; the docs name none"
    return (
        f'<li class="row{" quiet" if quiet else ""}" data-source="{escape(s.name)}">'
        f'<span class="name">{escape(s.name)}{badge}</span><span class="sub">{sub}</span>'
        f'<span class="cmd">{cmd}</span></li>\n'
    )


# -- /gear/crossings -----------------------------------------------------------------------------------------


def crossings_of(site: Site) -> list[Line]:
    """Every standing crossing line through the gate, the newest first."""

    def read() -> list[Line]:
        with site.lb.index() as idx:
            retracted = retractions(idx.retractions())
            lines = [
                line
                for line in reading.crossing(idx.by_kind(crossing.KIND), site.tiers)
                if str(line["id"]) not in retracted
            ]
        return sorted(lines, key=lambda line: (str(line["at"]), int(line["seq"])), reverse=True)

    return site.shared(("gear crossings", _gate(site.tiers)), read)


def _payload(line: Line) -> dict[str, Any]:
    return _mapping(line.get("payload"))


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _destination(line: Line) -> str:
    """Where a crossing went, as the gear may say it: the product's own destination by its name (`OWN`),
    and every other, a member of the circle the owner shared a day or a package with, never by name
    (`MEMBER`): a person is named only from the resolutions at a page's tiers, and a crossing line is
    not one."""
    raw = str(_payload(line).get("destination") or "")
    return raw if raw in OWN else MEMBER


def _destination_key(line: Line) -> str:
    """The filter a crossing is under (`?to=`): its own destination's name, or `CIRCLE` for a member's."""
    raw = str(_payload(line).get("destination") or "")
    return raw if raw in OWN else CIRCLE


def page_crossings(site: Site, to: str | None = None, page_: str = "1") -> str:
    """The crossings, the newest first, `PAGE` a page; `to` one destination's."""
    if not page_.isdigit() or int(page_) < 1:
        raise ValueError(f"page must be a number from 1, not {page_!r}")
    n = int(page_)
    every = crossings_of(site)
    keys = sorted({_destination_key(line) for line in every}, key=lambda k: (k == CIRCLE, k))
    shown = [line for line in every if to is None or _destination_key(line) == to]
    parts = []
    if keys:
        pills = ["<b>Every destination</b>" if to is None else site.link("Every destination", CROSSINGS)]
        for key in keys:
            said = escape(CIRCLE_PILL if key == CIRCLE else key)
            pills.append(f"<b>{said}</b>" if key == to else site.link(said, f"{CROSSINGS}?to={_query(key)}"))
        parts.append(f'<p class="pills">{"".join(pills)}</p>\n')
    if not every:
        parts.append(
            '<p class="empty">Nothing has left this machine yet: a crossing appears here each time an export'
            " sends lines out, as <code>logbook export site</code>, <code>vault</code> and"
            " <code>crossing</code> do.</p>\n"
        )
    elif not shown:
        parts.append(
            '<p class="empty">Nothing has crossed there: every crossing is under Every destination.</p>\n'
        )
    else:
        tz = site.tz
        today = day_start.of(site.lb.meta).today(site.now()).isoformat()
        parts.append('<ul class="rows">\n')
        parts.extend(_crossing_row(site, line, tz, today) for line in shown[(n - 1) * PAGE : n * PAGE])
        parts.append("</ul>\n")
        pager = []
        base = f"{CROSSINGS}?" + (f"to={_query(to)}&" if to is not None else "")
        if n > 1:
            pager.append(site.link("← later", f"{base}page={n - 1}"))
        if n * PAGE < len(shown):
            pager.append(site.link("earlier →", f"{base}page={n + 1}"))
        if pager:
            parts.append(f'<p class="pager">{"".join(pager)}</p>\n')
    lede = (
        "What left this machine, when, to where, under which entry of"
        f" <code>{escape(policy.POLICY_FILE.as_posix())}</code>: every export writes one line, and here it"
        " is."
    )
    return _frame(site, CROSSINGS, "Crossings", lede, "".join(parts))


def _query(text: str) -> str:
    from urllib.parse import quote

    return quote(text, safe="")


def _crossing_row(site: Site, line: Line, tz: Any, today: str) -> str:
    """One crossing: its destination and when, the tiers, the lines and the kinds, the entry, the line."""
    payload = _payload(line)
    tiers = sorted({int(t) for t in payload.get("tiers") or [] if isinstance(t, int)})
    counts = _mapping(payload.get("counts"))
    gate = _gate(site.tiers)
    whole = gate is None or set(tiers) <= set(gate)  # the page reads every tier that crossed
    if gate is not None:  # a tier the page does not read is not said, not even that it crossed
        tiers = [t for t in tiers if t in gate]
    facts = [("tier " if len(tiers) == 1 else "tiers ") + ", ".join(str(t) for t in tiers)] if tiers else []
    lines = _lines(counts, gate, whole)
    if lines is not None:
        facts.append(_plural(lines, "line"))
    kinds = counts.get("by_kind")
    if whole and isinstance(kinds, dict) and kinds:
        facts.append(", ".join(sorted(str(k) for k in kinds)))
    at = stays.instant(line.get("at"))
    when = "" if at is None else _moment(at, tz, today)
    entry = _mapping(payload.get("policy"))
    under = escape(str(entry.get("file") or policy.POLICY_FILE.as_posix()))
    ceiling = entry.get("max_tier")
    entry_of = (
        "the entry for that member" if _destination(line) == MEMBER else f"the {_destination(line)} entry"
    )
    said = f"under <code>{under}</code>, {escape(entry_of)}"
    if isinstance(ceiling, int) and (gate is None or ceiling <= max(gate, default=0)):
        said += f", ceiling {ceiling}"
    the_line = site.link("the crossing line", f"/line/{line['id']}")
    return (
        f'<li class="row"><span class="name">{escape(_destination(line))}</span>'
        f'<span class="sub">{escape(when)}{DOT if when and facts else ""}{escape(DOT.join(facts))}</span>'
        f'<span class="cmd">{said}</span><span class="cmd">{the_line}</span></li>\n'
    )


def _lines(counts: Mapping[str, Any], gate: tuple[int, ...] | None, whole: bool) -> int | None:
    """The lines a crossing carried, as the page may count them: all of them when it reads every tier that
    crossed, else those of the tiers it reads (`by_tier`); None when the line does not count them."""
    if whole:
        crossed = counts.get("crossed")
        return int(crossed) if isinstance(crossed, int) else None
    by_tier = counts.get("by_tier")
    if not isinstance(by_tier, dict) or gate is None:
        return None
    return sum(
        int(n) for t, n in by_tier.items() if str(t).isdigit() and int(t) in gate and isinstance(n, int)
    )


def _last_crossing(site: Site, today: str) -> str:
    every = crossings_of(site)
    if not every:
        return "Nothing has left this machine yet."
    at = stays.instant(every[0].get("at"))
    when = "" if at is None else f", {_moment(at, site.tz, today)}"
    return f"last crossing: {_destination(every[0])}{when}."


# -- the agents, the Manifest, the assets: their one line ----------------------------------------------------


def _last_session(site: Site, today: str) -> str:
    standing = site.shared(("agents",), lambda: shelf_agents.standing(site.lb, site.tiers))
    ats = [str(line["at"]) for line in [*standing.transcripts, *standing.messages]]
    if not ats:
        return "No session with an agent yet."
    day = day_start.of(site.lb.meta).day_of(max(ats))
    return f"last session: {_day(day, today)}."


def _orgs_named(site: Site) -> str:
    named = len(site._org_record().orgs)
    return f"{_plural(named, 'org')} named." if named else "No org named yet."


def _assets_registered(site: Site) -> str:
    try:
        registry = assets.read(site.lb.root)
    except assets.AssetError as e:
        return f"{e}."
    if not registry:
        return "None registered yet."
    return f"{_plural(len(registry), 'asset')} registered."


# -- /gear/build ---------------------------------------------------------------------------------------------


def _library(site: Site) -> library_build.Library:
    return site.library if site.library is not None else library_build.Library(site.lb)


def _build_state(site: Site, today: str) -> str:
    if not library_build.allowed(site.lb):
        return "A sealed record builds nothing: every page renders live."
    built = _library(site).built()
    if not built.get("when"):
        return "Every page renders live; nothing is built ahead."
    when = stays.instant(str(built["when"]))
    at = "" if when is None else f" {_moment(when, site.tz, today)}"
    pages = _plural(int(built.get("pages") or 0), "page")
    return f"last built{at}, {pages} in {built.get('seconds', 0)}\u00a0s."


def page_build(site: Site) -> str:
    """When the pages were last built and how long it took, each door and shelf with when it was built,
    the command that builds them again; the serve service `serve --status` names."""
    today = day_start.of(site.lb.meta).today(site.now()).isoformat()
    tz = site.tz
    parts = []
    if not library_build.allowed(site.lb):
        parts.append(
            f'<p class="empty">{escape(library_build.SEALED[0].upper() + library_build.SEALED[1:])}.</p>\n'
        )
    else:
        library = _library(site)
        built = library.built()
        if not built.get("when"):
            parts.append(f'<p class="empty">{NEVER_BUILT}</p>\n')
        else:
            parts.append(_built_card(built, tz, today))
            parts.append(_built_pages(site, library.pages(), built, tz, today))
    parts.append(_service(site))
    lede = (
        "The Library's pages built ahead of time: when, how long it took, and the command that builds"
        " them again."
    )
    return _frame(site, BUILD, "The build", lede, "".join(parts))


def _built_card(built: Mapping[str, Any], tz: Any, today: str) -> str:
    when = stays.instant(str(built["when"]))
    said = "last built" + ("" if when is None else f" {_moment(when, tz, today)}")
    pages, written = int(built.get("pages") or 0), int(built.get("written") or 0)
    how = "every page" if built.get("full") else "what changed since the build before"
    workers = int(built.get("workers") or 1)
    facts = (
        f"{_plural(pages, 'page')} in {built.get('seconds', 0)}\u00a0s{DOT}{written:,} written{DOT}{how}"
        + (f"{DOT}{workers} processes" if workers > 1 else "")
    )
    return (
        '<div class="dark">\n<p class="label">The last build</p>\n'
        f'<p class="when">{escape(said[0].upper() + said[1:])}</p>\n'
        f'<p class="facts">{escape(facts)}</p>\n'
        '<p class="again"><code>logbook serve --build</code> builds them again now, what changed;'
        " <code>logbook serve --build --full</code> every page. The 06:00 close builds them each"
        " morning.</p>\n"
        "</div>\n"
    )


def _built_pages(
    site: Site, pages: Mapping[str, library_build.Page], built: Mapping[str, Any], tz: Any, today: str
) -> str:
    """The doors and shelves, each with when it was built and, for the slowest, how long it took; then
    the slowest of the other pages by their section (`_section`) and how many the build holds of each,
    on a page that reads every tier; a gated page says the doors and shelves alone."""
    took = {str(t): s for t, s in built.get("slowest") or [] if isinstance(s, (int, float))}
    rows = []
    for target in library_build.DOORS:
        page = pages.get(target)
        when = stays.instant(page.at) if page is not None else None
        said = "not built yet" if when is None else f"built {_moment(when, tz, today)}"
        if target in took:
            said += f"{DOT}{took[target]:g} s, among the slowest"
        rows.append(
            f'<li class="row"><span class="name">{site.link(escape(_address(target)), target)}</span>'
            f'<span class="sub">{escape(said)}</span></li>\n'
        )
    others: dict[str, int] = {}
    for target in pages:
        if target not in library_build.DOORS:
            section = target.partition("?")[0].split("/")[1] or "/"
            others[section] = others.get(section, 0) + 1
    slow = [
        f'<li class="row"><span class="name">{escape(_section(t))}</span>'
        f'<span class="sub">{s:g} s</span></li>\n'
        for t, s in took.items()
        if t not in library_build.DOORS
    ]
    live = ", ".join(
        f"<code>{escape(p)}</code>" + (" (a redirect to today's Day)" if p == "/today" else "")
        for p in library_build.LIVE_PAGES
    )
    parts = [
        '<h2>The doors and shelves</h2>\n<ul class="rows">\n',
        *rows,
        "</ul>\n",
        f'<p class="lede">Never built, always rendered as they are asked for: {live}, today\'s Day and a'
        " photo's pixels.</p>\n",
    ]
    if site.tiers is not None:  # a gated page: the doors and shelves alone, no page of a person or a day
        return "".join(parts)
    if slow:
        parts += ["<h2>The slowest of the rest</h2>\n", '<ul class="rows">\n', *slow, "</ul>\n"]
    if others:
        listed = "; ".join(f"{n:,} under /{name}" for name, n in sorted(others.items()))
        parts.append(f'<p class="lede">And the pages they lead to: {escape(listed)}.</p>\n')
    return "".join(parts)


SECTIONS = {  # a section of the Library in words: what one of its pages is
    "day": "a Day",
    "days": "a window of days",
    "journeys": "a journey",
    "trips": "a year's trips",
    "people": "a person's page",
    "org": "an org's page",
    "idea": "an idea's page",
    "goals": "a goal",
    "promises": "a promise",
    "week": "a week",
    "line": "a line as written",
    "timeline": "a stretch of the timeline",
    "gear": "a part of the gear",
}


def _section(target: str) -> str:
    """A page beyond the doors and shelves named by its section alone, in words and by its path's first
    part (`a person's page, /people/…`): never a person's id or a day's date beside the seconds it took."""
    path, _mark, query = target.partition("?")
    first = path.split("/")[1] if path.count("/") >= 1 else ""
    tail = "/…" if path.count("/") > 1 else ("?…" if query else "")
    return f"{SECTIONS.get(first, 'a page')}, /{first}{tail}"


def _address(target: str) -> str:
    """A built page's address as the row names it: `/` is Today."""
    return "/ (Today)" if target == "/" else target


def _service(site: Site) -> str:
    """The serve service `logbook serve --status` names, from this machine's files alone: nothing is
    asked of a port here."""
    from . import service

    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    found = service.find(service.system(), Path.home(), Path(xdg).expanduser() if xdg else None)
    if not found:
        said = (
            "No serve service is installed: <code>logbook serve --install-service</code> keeps the Library"
            " running, and <code>logbook serve --status</code> says whether it answers."
        )
    else:
        each = "; ".join(f"a {escape(item.kind)}, port {item.port}" for item in found)
        said = f"Installed: {each}. <code>logbook serve --status</code> says whether it answers."
    return f'<h2>The server</h2>\n<p class="lede">{said}</p>\n'


# -- words ---------------------------------------------------------------------------------------------------


def _day(day: str, today: str) -> str:
    """A day in words: `today`, `yesterday`, `Tuesday` within the week, else `Tue 9 June` (and its year
    when it is not this one); a day after `today` is its date, `26 October 2026`."""
    if day > today:  # a day after the record's today (a clock behind the record's): the date itself
        then = date.fromisoformat(day)
        return f"{then.day} {day_rhythm.MONTHS[then.month - 1]} {then.year}"
    return door_today.since(day, today).removeprefix("since ")


def _moment(at: datetime, tz: Any, today: str) -> str:
    """An instant in words, in the record's zone: `yesterday 06:10`."""
    local = at.astimezone(tz if tz is not None else UTC)
    return f"{_day(local.date().isoformat(), today)} {local.strftime('%H:%M')}"


def _plural(n: int, noun: str) -> str:
    return f"{n:,} {noun}" if n == 1 else f"{n:,} {noun}s"
