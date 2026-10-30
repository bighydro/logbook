"""The Library's doors share one frame (RFC 0047 §6): the header, one stylesheet of the owner's tokens,
and three typefaces served by the Library itself. Today (`door_today`) is the first page in it; Life,
People and Places (`door_life`, `door_people`, `door_places`) render through `page` too. Every other
page of the Library carries the same header (`header`, with `header_style`: the tokens on the header
alone) above its own body, which keeps `serve.STYLE` and its look until its own pull request.

The header, from the left: the wordmark (a link to Today), the four doors, the Ask field and the gear.
A door not yet built links to the page that holds its moments today (`DOORS`: People to `/people`,
Places to `/places`); Life is its own page, `/life` (`door_life`). Ask is a GET form to `/ask?q=`
(`door_ask`, Ask v1, RFC 0047 §4.5), which answers with moments; the page of an answer keeps the words
asked in the field (`asked`). An exported site has no server to ask, and leaves it out.
The gear is one icon, a link to the machinery (`GEAR`, `door_gear`), marked on the gear's pages and the
shelves listed (`in_gear`). On a phone the doors are a bar at the foot of the screen and Ask is at the top.

The stylesheet (`STYLE`) holds the tokens as custom properties on `:root` (`TOKENS`, and `DARK` for a
browser that asks for a dark page) and the three families (`FAMILIES`) with their fallbacks. A door's
own rules come after it (`page(style=...)`) and read the tokens with a fallback, `var(--paper,
#F4F1EA)`, and never define `:root`: the tokens are defined here, once.

The typefaces are Instrument Serif, Inter and JetBrains Mono, as woff2 in `fonts/` beside this module,
each with its SIL Open Font License, Latin only (the fontsource cuts, 5.3.0; a glyph outside Latin
falls back to the system's face). The server answers `/font/NAME` from that folder and nothing else
(`font_bytes`): no font is ever fetched from anywhere, and a page's policy allows fonts from the server alone
(`CSP`). An exported site (`export site`) carries no font: its pages keep the families' fallbacks, as
its rule of one file a page and nothing beside it says.

Every address the Library answered before the doors is a row of `MOVED`, RFC 0047 §9's table in its
order: a row with a home is answered with `REDIRECT_STATUS` (302 for 1.1, 301 from 1.2, §15) to it, the
moment it named carried (`moved`); a row without one, and every POST, as it always was."""

from __future__ import annotations

import functools
import hashlib
import re
from dataclasses import dataclass
from datetime import date
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, quote, unquote, urlencode

if TYPE_CHECKING:  # the Site passes itself; serve imports this module, never the other way at import
    from .serve import Site

TODAY, LIFE, PEOPLE, PLACES = "Today", "Life", "People", "Places"
# the four doors and where each opens until its own page is on main (RFC 0047 §4, §5); the fifth,
# Holdings, goes between Places and Ask when it is built, and its place stays empty until then (§11)
DOORS = ((TODAY, "/"), (LIFE, "/life"), (PEOPLE, "/people"), (PLACES, "/places"))
REDIRECT_STATUS = 302  # RFC 0047 §15 (8): 302 for one release, 1.1; 301 from 1.2, this line alone


@dataclass(frozen=True)
class Moved:
    """One row of RFC 0047 §9: an address the Library answered before the doors (`old`, its parts
    `{DAY}`, `{FIRST}`, `{LAST}` and `{ID}`) and its new home (`home`; None: it stays, or its home is not
    built yet). `query` is what the old address's query carries to the new one, `(old name, new name,
    kind)`; `fixed` is what the new home's query adds, its parts named as `old`'s; `most` is the most
    days the row's two days may span (Life's own window), and `year` the home of a window that is one
    calendar year, `{YEAR}` its year, whatever `most` says. `waits` names what a row with a home waits
    for (its home not on main yet, or not yet holding what the old page held): until then it is
    answered as it always was. `post` marks a form's address."""

    old: str
    home: str | None = None
    query: tuple[tuple[str, str, str], ...] = ()
    fixed: tuple[tuple[str, str], ...] = ()
    most: int | None = None
    year: str | None = None
    waits: str = ""
    post: bool = False


DAY_VALUE, YEAR_VALUE, SHARED_YEAR = "day", "year", "shared year"  # what a carried value must be
# Every Library address before the doors and where it lives now: RFC 0047 §9's rows, in order. The
# server answers a row with a home with `REDIRECT_STATUS` to it (`moved`); a row without one, a row that
# `waits`, and every POST, as it always did. A parameter an old address took that its new home does not
# is named in the row's comment and dropped, never passed on.
MOVED = (
    Moved("/"),  # Today
    Moved("/today"),  # already a 302 to today's Day, which Today is: left as it is (tests pin it)
    Moved("/day/{DAY}"),
    Moved("/day/{DAY}/reflect", post=True),
    Moved("/day/{DAY}/sign", post=True),
    Moved("/star", post=True),
    Moved("/with", post=True),
    # Life, the day zoom; Life's window of days is at most `door_life.DAY_MOST`, and a whole calendar
    # year (Life's own Volumes link one) is Life at that year
    Moved(
        "/days",
        "/life",
        (("from", "from", DAY_VALUE), ("to", "to", DAY_VALUE)),
        (("zoom", "day"),),
        most=92,
        year="/life?year={YEAR}&zoom=year",
    ),
    # Life at the year, the zoom that draws a year's trips: Life has no `zoom=trip` (§9's), so not that
    Moved("/trips", "/life", (("year", "year", YEAR_VALUE),), (("zoom", "year"),)),
    Moved("/journeys", "/life", (("year", "year", YEAR_VALUE),), (("zoom", "year"),)),
    # Life at that trip, at most `door_life.TRIP_MOST` days, once Life holds what the journey's page does:
    # its name form (`/journeys/name`), its promises and photos; Life's trip links here until then
    Moved(
        "/journeys/{FIRST}/{LAST}",
        "/life",
        fixed=(("trip", "{FIRST}/{LAST}"),),
        most=366,
        waits="Life's trip view: the journey's name form, promises and photos",
    ),
    Moved("/journeys/name", post=True),  # Life's form posts here
    Moved("/goals", "/life"),  # the year's goals at the top of Life (§15, 6)
    Moved("/goals/{ID}"),  # waits: Life takes no `goal=` yet, and a goal's thread is not dropped
    Moved("/ideas"),  # the Ideas shelf is kept in the gear (§15, 6), at its own address
    Moved("/idea/{ID}"),  # likewise: Life takes no `idea=` yet
    Moved("/ideas/review", post=True),
    Moved("/ideas/status", post=True),
    Moved("/gaps", "/gear/sources", waits="the gear, #418"),  # its `since` dropped: the sources take none
    Moved("/promises"),  # the full list of every promise stays in the gear (§15, 4), at its own address
    Moved("/promises/{ID}"),  # waits: People takes no `promise=` yet, and the person is the record's
    Moved("/people"),  # its `year` and `page` as they were
    Moved("/people/{ID}"),
    Moved("/people/review", post=True),
    Moved("/places"),
    Moved("/places/review", post=True),
    # Places at the year the window lies in: Places takes `at=YYYY`, no window, so `from` and `to` are
    # dropped and the year it opens in carried (`from`'s, else `to`'s); without either, Places' own year
    Moved("/world", "/places", (("from to", "at", SHARED_YEAR),)),
    Moved("/assets", "/gear/assets", waits="the gear, #418"),
    Moved("/manifest", "/gear/manifest", waits="the gear, #418"),  # its `page` and `portfolio`
    Moved("/manifest/people", "/gear/manifest/people", waits="the gear, #418"),
    Moved("/org/{ID}", "/gear/org/{ID}", waits="the gear, #418"),  # its `money`
    Moved("/manifest/review", post=True),
    Moved("/manifest/status", post=True),
    Moved("/agents", "/gear/agents", waits="the gear, #418"),  # its `page` and `day`
    Moved("/line/{ID}"),
    Moved("/photo/{ID}"),
)
_DAY = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"  # ASCII digits only: `\d` is any script's
_PARTS = {"DAY": _DAY, "FIRST": _DAY, "LAST": _DAY, "ID": r"[^/]+"}  # what each part of a row's address is
_YEAR = re.compile(r"[0-9]{4}")


@functools.cache
def pattern(old: str) -> re.Pattern[str]:
    """The paths a row's address names: its literal parts as they are, each `{PART}` as `_PARTS` says."""
    pieces = re.split(r"\{([A-Z]+)\}", old)
    return re.compile(
        "".join(f"(?P<{p}>{_PARTS[p]})" if n % 2 else re.escape(p) for n, p in enumerate(pieces))
    )


def _day(text: str, name: str) -> date:
    try:
        found = date.fromisoformat(text)
    except ValueError:
        found = None
    if found is None or found.isoformat() != text:
        raise ValueError(f"{name} is not a day, YYYY-MM-DD")
    return found


def _span(first: date | None, last: date | None, most: int | None, names: str) -> None:
    """Two days of a row run forward, and span fewer than `most` days when it says (Life's rule)."""
    if first is None or last is None:
        return
    if last < first or (most is not None and (last - first).days >= most):
        raise ValueError(f"{names}: two days, the first on or before the last, under {most} days apart")


def moved(path: str, query: str) -> str | None:
    """Where the old address `path?query` lives now (RFC 0047 §9, `MOVED`): its new home with the
    moment it named, built from the table and the values parsed from the request alone, each held to
    what its new home takes; None when the address stays, waits for its home, or no row names it.
    `ValueError` for a value the new home would refuse, which says what it is and never repeats it."""
    for row in MOVED:
        found = pattern(row.old).fullmatch(path)
        if found is None:
            continue
        if row.home is None or row.post or row.waits:
            return None
        parts = {
            name: (_day(value, name).isoformat() if name != "ID" else quote(unquote(value), safe=""))
            for name, value in found.groupdict().items()
        }
        if "FIRST" in parts:
            _span(date.fromisoformat(parts["FIRST"]), date.fromisoformat(parts["LAST"]), row.most, "the trip")
        asked = {k: v[-1] for k, v in parse_qs(query, keep_blank_values=True).items()}
        if row.year is not None and (year := _calendar_year(asked)) is not None:
            return row.year.format(YEAR=year)
        pairs: list[tuple[str, str]] = []
        for old, new, kind in row.query:
            value = _carried(old.split(), kind, asked, row.most)
            if value is not None:
                pairs.append((new, value))
        pairs.extend((new, template.format(**parts)) for new, template in row.fixed)
        return row.home + (f"?{urlencode(pairs, safe='/')}" if pairs else "")
    return None


def _calendar_year(asked: dict[str, str]) -> str | None:
    """The year `from` and `to` are, when they are its first and its last day; else None."""
    first, last = asked.get("from") or "", asked.get("to") or ""
    year = first[:4]
    if _YEAR.fullmatch(year) is None or (first, last) != (f"{year}-01-01", f"{year}-12-31"):
        return None
    return year


def _carried(names: list[str], kind: str, asked: dict[str, str], most: int | None) -> str | None:
    """The value the old query's `names` carry to the new home, as `kind` holds it; None when it
    names none."""
    given = {name: asked[name] for name in names if asked.get(name)}
    if kind == YEAR_VALUE:
        (name,) = names
        if name not in given:
            return None
        if _YEAR.fullmatch(given[name]) is None:
            raise ValueError(f"{name} is not a year, YYYY")
        return given[name]
    days = {name: _day(value, name) for name, value in given.items()}
    if kind == DAY_VALUE:
        (name,) = names
        if name == "from":
            _span(days.get("from"), _day(asked["to"], "to") if asked.get("to") else None, most, "from and to")
        return None if name not in days else days[name].isoformat()
    first, last = days.get(names[0]), days.get(names[1])  # SHARED_YEAR: a window, the year it lies in
    _span(first, last, most, " and ".join(names))
    opens = first or last
    return None if opens is None else f"{opens.year:04d}"


ASK = "/ask"  # Ask v1 (`door_ask`): the record's words as moments, through the search of #363
GEAR = "/gear"  # the machinery behind one icon (`door_gear`, RFC 0047 §4.6)
GEAR_TITLE = "The gear: the sources, the crossings, the agents, the Manifest, the assets and the build"
FONT_DIR = Path(__file__).resolve().parent / "fonts"
FONT_PATH = re.compile(r"^/font/([a-z-]+\.woff2)$")
FONT_TYPE = "font/woff2"
# file → (family, style, weight): every face this module serves, and nothing else
FACES = {
    "instrument-serif.woff2": ("Instrument Serif", "normal", "400"),
    "instrument-serif-italic.woff2": ("Instrument Serif", "italic", "400"),
    "inter.woff2": ("Inter", "normal", "100 900"),
    "jetbrains-mono.woff2": ("JetBrains Mono", "normal", "100 800"),
}
LICENCES = {  # each family's SIL Open Font License, beside its files
    "Instrument Serif": "OFL-instrument-serif.txt",
    "Inter": "OFL-inter.txt",
    "JetBrains Mono": "OFL-jetbrains-mono.txt",
}
LATIN = (  # the fontsource cuts' Latin range: a glyph outside it is the system face's
    "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,"
    "U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD"
)
CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; font-src 'self'; img-src 'self'; form-action 'self';"
    " base-uri 'none'; frame-ancestors 'none'"
)  # a door's policy: its fonts and a memory's thumbnail from the server, its forms to it, nothing else,
# and no frame around it

# the owner's tokens (RFC 0047, the brief of 24 October 2026), as custom properties on :root
TOKENS = (
    ("--paper", "#F4F1EA"),
    ("--surface", "#FBFAF6"),
    ("--line", "#E3DED3"),
    ("--line-soft", "#ECE7DD"),
    ("--tint", "#EDE8DE"),
    ("--ink", "#16181D"),
    ("--pencil", "#62666D"),
    ("--pencil-rule", "#8C8F95"),
    ("--signal", "#C8401A"),
    ("--signal-deep", "#A93413"),
    ("--card-dark", "#16181D"),
    ("--card-dark-text", "#F4F1EA"),
    ("--card-dark-muted", "#C9C4B8"),
)
# the same tokens for a browser that asks for a dark page: the paper is the ink's, and every text keeps
# 4.5:1 on the paper and on the surface, as the light ones do
DARK = (
    ("--paper", "#16181D"),
    ("--surface", "#1D2026"),
    ("--line", "#33363D"),
    ("--line-soft", "#2A2D33"),
    ("--tint", "#24272D"),
    ("--ink", "#F4F1EA"),
    ("--pencil", "#A8ACB3"),
    ("--pencil-rule", "#7A7E85"),
    ("--signal", "#EE7A55"),
    ("--signal-deep", "#F49A7C"),
    ("--card-dark", "#262930"),
    ("--card-dark-text", "#F4F1EA"),
    ("--card-dark-muted", "#C9C4B8"),
)
FAMILIES = (
    ("--serif", '"Instrument Serif","Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif'),
    ("--sans", 'Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif'),
    ("--mono", '"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace'),
)
GEAR_ICON = (  # drawn here, inline: no image is fetched
    '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" focusable="false">'
    '<path fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" d="M10.3 2.8h3.4l.5'
    " 2.5 1.7.9 2.3-1.1 2.4 2.4-1.1 2.3.9 1.7 2.5.5v3.4l-2.5.5-.9 1.7 1.1 2.3-2.4 2.4-2.3-1.1-1.7.9-.5"
    " 2.5h-3.4l-.5-2.5-1.7-.9-2.3 1.1-2.4-2.4 1.1-2.3-.9-1.7-2.5-.5v-3.4l2.5-.5.9-1.7-1.1-2.3 2.4-2.4"
    ' 2.3 1.1 1.7-.9z"/><circle cx="12" cy="12" r="3.2" fill="none" stroke="currentColor"'
    ' stroke-width="1.6"/></svg>'
)


def _properties(pairs: tuple[tuple[str, str], ...]) -> str:
    return ";".join(f"{name}:{value}" for name, value in pairs)


def _faces() -> str:
    return "".join(
        f'@font-face{{font-family:"{family}";src:url(/font/{name}) format("woff2");font-style:{style};'
        f"font-weight:{weight};font-display:swap;unicode-range:{LATIN}}}\n"
        for name, (family, style, weight) in FACES.items()
    )


ROOT = f"""
:root{{color-scheme:light dark;{_properties(TOKENS)};{_properties(FAMILIES)}}}
@media (prefers-color-scheme:dark){{:root{{{_properties(DARK)}}}}}
*,*::before,*::after{{box-sizing:border-box}}
body{{margin:0;background:var(--paper);color:var(--ink);font-size:16px;line-height:1.5;font-family:var(--sans);
-webkit-text-size-adjust:100%;text-size-adjust:100%}}
a{{color:inherit;text-decoration-color:var(--pencil-rule);text-underline-offset:.18em}}
a:hover{{text-decoration-color:var(--signal)}}
:focus-visible{{outline:2px solid var(--signal);outline-offset:2px}}
"""  # the tokens on :root and the page's own ground: a door's pages only
HEADER = """header.doors{display:flex;align-items:center;gap:.5rem 1.6rem;max-width:72rem;margin:0 auto;
padding:.9rem 1.25rem;border-bottom:1px solid var(--line)}
header.doors a.wordmark{font-weight:400;font-size:1.6rem;line-height:1;font-family:var(--serif);
text-decoration:none;color:var(--ink);margin-right:.4rem}
nav.doors{display:flex;gap:.2rem}
nav.doors a{display:inline-flex;align-items:center;min-height:44px;padding:0 .7rem;border-radius:22px;
font-weight:500;font-size:.95rem;text-decoration:none;color:var(--pencil)}
nav.doors a:hover{color:var(--ink);background:var(--tint)}
nav.doors a[aria-current=page]{color:var(--ink);background:var(--surface);
box-shadow:inset 0 0 0 1px var(--line);text-decoration:underline 2px var(--ink);text-underline-offset:.4em}
form.ask{flex:1;display:flex;justify-content:flex-end;margin:0}
form.ask input{width:100%;max-width:22rem;min-height:44px;padding:0 1rem;border-radius:22px;
border:1px solid var(--line);background:var(--surface);color:var(--ink);font:inherit;font-size:.95rem}
form.ask input::placeholder{color:var(--pencil)}
form.ask label,.hidden{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);
white-space:nowrap}
header.doors a.gear{display:inline-flex;align-items:center;justify-content:center;min-width:44px;
min-height:44px;border-radius:22px;color:var(--pencil)}
header.doors a.gear:hover{color:var(--ink);background:var(--tint)}
header.doors a.gear[aria-current=page]{color:var(--ink);background:var(--surface);
box-shadow:inset 0 0 0 1px var(--line)}
header.doors a.gear svg{display:block;max-width:100%}
"""  # the header's rules: every page's
REST = """main.door{max-width:44rem;margin:0 auto;padding:1.5rem 1.25rem 3rem}
footer.door{max-width:44rem;margin:0 auto;padding:1rem 1.25rem 2rem;border-top:1px solid var(--line);
color:var(--pencil);font-size:.8rem;overflow-wrap:anywhere}
footer.door code{font-family:var(--mono);font-size:.95em}
.pencil{color:var(--pencil);text-decoration:underline dotted var(--pencil-rule);text-underline-offset:.2em}
.ink{font-family:var(--serif);color:var(--ink)}
.fact{color:var(--pencil);font-size:.8rem;font-variant-numeric:tabular-nums}
"""  # a door's main, footer, ink and pencil
PHONE_HEADER = """header.doors{flex-wrap:wrap;gap:.6rem;padding:.7rem 1rem}
header.doors a.wordmark{font-size:1.4rem;margin-right:auto}
form.ask{order:3;flex:1 0 100%}
form.ask input{max-width:none}
nav.doors{position:fixed;left:0;right:0;bottom:0;z-index:10;justify-content:space-around;gap:0;
padding:.25rem .5rem .5rem;background:var(--surface);
border-top:1px solid var(--line)}
nav.doors a{flex:1;justify-content:center;font-size:.85rem;padding:0 .3rem}
nav.doors a[aria-current=page]{background:var(--ink);color:var(--paper);box-shadow:none;text-decoration:none}
body{padding-bottom:4.5rem}
"""  # the header on a phone, the doors a bar at the foot: every page's
PHONE_REST = """main.door,footer.door{padding-left:1rem;padding-right:1rem}
}
"""
FRAME = f"{ROOT}{HEADER}{REST}@media (max-width:40rem){{\n{PHONE_HEADER}{PHONE_REST}"
# every other page's header (`header_style`): the tokens on the header alone, so a page whose own sheet
# names a property the same (the Day's `--ink`, the old pages' `--line`) keeps its look and the header the
# doors'; its paper and its rule the page's whole width (a border image drawn past the box, which neither
# scrolls nor clips the phone's door bar, fixed inside the header); and what the page's own sheet sets on
# any `nav`, `a` or `input` undone inside it
SCOPED = f"""
header.doors{{color-scheme:light dark;{_properties(TOKENS)};{_properties(FAMILIES)};color:var(--ink);
font-size:16px;line-height:1.5;font-family:var(--sans);background:var(--paper);
border-image:linear-gradient(to top,var(--line) 1px,var(--paper) 1px) 0 fill/0/0 100vmax}}
@media (prefers-color-scheme:dark){{header.doors{{{_properties(DARK)}}}}}
header.doors,header.doors *,header.doors *::before,header.doors *::after{{box-sizing:border-box}}
header.doors :focus-visible{{outline:2px solid var(--signal);outline-offset:2px}}
nav.doors{{flex-wrap:nowrap}}
nav.doors a{{margin:0}}
"""
BAND = "header.doors{border-bottom-color:transparent}\n"  # after `HEADER`: the band's own rule, edge to edge


@functools.cache
def style(fonts: bool = True) -> str:
    """The doors' one stylesheet: the faces the server serves (`fonts`; none on an exported site), then
    the tokens and the frame. A door's own rules follow it."""
    return (_faces() if fonts else "") + FRAME


@functools.cache
def header_style(fonts: bool = True) -> str:
    """The header's stylesheet on a page that is not a door's (every page of the Library but Today, until
    its own door): the faces (`fonts`), the tokens on the header alone and the header's rules, on a
    phone the doors a bar at the foot; nothing else of the page changes."""
    phone = f"@media (max-width:40rem){{\n{PHONE_HEADER}}}\n"
    return (_faces() if fonts else "") + SCOPED + HEADER + BAND + phone


def in_gear(path: str) -> bool:
    """Whether the page at `path` is the gear's: `/gear`, its parts, and the shelves listed it links."""
    return path in (GEAR, "/shelves") or path.startswith(f"{GEAR}/")


def door_of(path: str) -> str | None:
    """The door the page at `path` is in: the door whose page it is or is under; None for a page of
    none yet (a Day, the gear's shelves)."""
    for name, target in DOORS:
        if path == target or (target != "/" and path.startswith(target + "/")):
            return name
    return None


def header(site: Site, door: str, asked: str = "") -> str:
    """The header of a door's page: the wordmark, the four doors (`door` the current one), Ask (the
    words `asked` in its field, on the page of an answer) and the gear. On an exported site
    (`site.static`) every link goes through `site.href`, a door it has no page for is its name alone,
    and Ask and the gear are left out: there is no server to ask, and the machinery is the owner's."""
    doors = []
    for name, path in DOORS:
        current = ' aria-current="page"' if name == door else ""
        href = site.href(path)
        doors.append(
            f'<a href="{escape(href)}"{current}>{escape(name)}</a>'
            if href is not None
            else f"<span{current}>{escape(name)}</span>"
        )
    home = site.href("/")
    wordmark = (
        f'<a class="wordmark" href="{escape(home)}">Logbook</a>'
        if home is not None
        else '<span class="wordmark">Logbook</span>'
    )
    parts = [wordmark, f'<nav class="doors" aria-label="Doors">{"".join(doors)}</nav>']
    if not site.static:
        value = f' value="{escape(asked)}"' if asked else ""
        parts.append(
            f'<form class="ask" method="get" action="{ASK}" role="search">'
            '<label for="ask">Ask</label>'
            '<input id="ask" type="search" name="q" placeholder="Ask: a name, a place, a word"'
            f'{value} autocomplete="off">'
            "</form>"
        )
        title = escape(GEAR_TITLE)
        here = ' aria-current="page"' if door == GEAR else ""  # the gear's pages, the shelves listed
        parts.append(
            f'<a class="gear" href="{GEAR}" title="{title}" aria-label="The gear"{here}>{GEAR_ICON}</a>'
        )
    return '<header class="doors">' + "".join(parts) + "</header>\n"


def page(
    site: Site,
    door: str,
    title: str,
    body: str,
    *,
    style_: str = "",
    script: str | None = None,
    footnote: str | None = None,
    asked: str = "",
) -> str:
    """One door's page: the head, the header (`header`, the words `asked` in its Ask field), `body` in
    `<main class="door">`, then the footer the Library's every page carries (`footnote` under it).
    `style_` is the door's own rules, after the frame; `script` its one inline script, named by hash in
    its policy."""
    footer = site.footer_text(footnote, door=True)
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{escape(title)} · Logbook</title>\n"
        f"<style>{style(fonts=not site.static)}{style_}</style>\n</head>\n<body>\n"
        f"{header(site, door, asked)}"
        f'<main class="door">\n{body}</main>\n'
        f'<footer class="door">{footer}</footer>\n'
        f"{'' if script is None else f'<script>{script}</script>' + chr(10)}"
        "</body>\n</html>\n"
    )


@functools.cache
def font_bytes(name: str) -> bytes | None:
    """The bytes of the face `name` in `fonts/` (`FACES`), read once a process; None for a name this
    module does not serve, whatever the folder holds."""
    if name not in FACES:
        return None
    try:
        return (FONT_DIR / name).read_bytes()
    except OSError:
        return None


def font_tag(data: bytes) -> str:
    """A face's tag: the digest of its bytes, so a browser keeps it and a reload is a 304."""
    return f'"font-{hashlib.sha256(data).hexdigest()[:32]}"'
