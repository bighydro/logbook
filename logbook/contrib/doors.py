"""The Library's doors share one frame (RFC 0047 §6): the header, one stylesheet of the owner's tokens,
and three typefaces served by the Library itself. Today (`door_today`) is the first page in it; Life,
People and Places (`door_life`, `door_people`, `door_places`) render through `page` too, and every
other page keeps `serve.NAV` and `serve.STYLE` until its own pull request.

The header, from the left: the wordmark (a link to Today), the four doors, the Ask field and the gear.
A door not yet built links to the page that holds its moments today (`DOORS`: Life to `/days`, People
to `/people`, Places to `/places`). Ask is a GET form to the Library's search (`/search?q=`, Ask v1,
RFC 0047 §4.5); an exported site has no server to ask, and leaves it out. The gear is one icon, a link
to the index of the machinery pages (`GEAR`, the shelves listed) until `/gear` exists. On a phone the
doors are a bar at the foot of the screen and Ask is at the top.

The stylesheet (`STYLE`) holds the tokens as custom properties on `:root` (`TOKENS`, and `DARK` for a
browser that asks for a dark page) and the three families (`FAMILIES`) with their fallbacks. A door's
own rules come after it (`page(style=...)`) and read the tokens with a fallback, `var(--paper,
#F4F1EA)`, and never define `:root`: the tokens are defined here, once.

The typefaces are Instrument Serif, Inter and JetBrains Mono, as woff2 in `fonts/` beside this module,
each with its SIL Open Font License, Latin only (the fontsource cuts, 5.3.0; a glyph outside Latin
falls back to the system's face). The server answers `/font/NAME` from that folder and nothing else
(`font_bytes`): no font is ever fetched from anywhere, and a page's policy allows fonts from the server alone
(`CSP`). An exported site (`export site`) carries no font: its pages keep the families' fallbacks, as
its rule of one file a page and nothing beside it says."""

from __future__ import annotations

import functools
import hashlib
import re
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # the Site passes itself; serve imports this module, never the other way at import
    from .serve import Site

TODAY, LIFE, PEOPLE, PLACES = "Today", "Life", "People", "Places"
# the four doors and where each opens until its own page is on main (RFC 0047 §4, §5)
DOORS = ((TODAY, "/"), (LIFE, "/days"), (PEOPLE, "/people"), (PLACES, "/places"))
ASK = "/search"  # Ask v1 is the Library's search (#363)
GEAR = "/shelves"  # the index of the machinery pages, until `/gear` exists
GEAR_TITLE = "The gear: the sources, the agents, the Manifest, the assets and the gaps"
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
    " base-uri 'none'"
)  # a door's policy: its fonts and a memory's thumbnail from the server, its forms to it, nothing else

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


FRAME = f"""
:root{{color-scheme:light dark;{_properties(TOKENS)};{_properties(FAMILIES)}}}
@media (prefers-color-scheme:dark){{:root{{{_properties(DARK)}}}}}
*,*::before,*::after{{box-sizing:border-box}}
body{{margin:0;background:var(--paper);color:var(--ink);font-size:16px;line-height:1.5;font-family:var(--sans);
-webkit-text-size-adjust:100%;text-size-adjust:100%}}
a{{color:inherit;text-decoration-color:var(--pencil-rule);text-underline-offset:.18em}}
a:hover{{text-decoration-color:var(--signal)}}
:focus-visible{{outline:2px solid var(--signal);outline-offset:2px}}
header.doors{{display:flex;align-items:center;gap:.5rem 1.6rem;max-width:72rem;margin:0 auto;
padding:.9rem 1.25rem;border-bottom:1px solid var(--line)}}
header.doors a.wordmark{{font-weight:400;font-size:1.6rem;line-height:1;font-family:var(--serif);
text-decoration:none;color:var(--ink);margin-right:.4rem}}
nav.doors{{display:flex;gap:.2rem}}
nav.doors a{{display:inline-flex;align-items:center;min-height:44px;padding:0 .7rem;border-radius:22px;
font-weight:500;font-size:.95rem;text-decoration:none;color:var(--pencil)}}
nav.doors a:hover{{color:var(--ink);background:var(--tint)}}
nav.doors a[aria-current=page]{{color:var(--ink);background:var(--surface);
box-shadow:inset 0 0 0 1px var(--line)}}
form.ask{{flex:1;display:flex;justify-content:flex-end;margin:0}}
form.ask input{{width:100%;max-width:22rem;min-height:44px;padding:0 1rem;border-radius:22px;
border:1px solid var(--line);background:var(--surface);color:var(--ink);font:inherit;font-size:.95rem}}
form.ask input::placeholder{{color:var(--pencil)}}
form.ask label,.hidden{{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);
white-space:nowrap}}
header.doors a.gear{{display:inline-flex;align-items:center;justify-content:center;min-width:44px;
min-height:44px;border-radius:22px;color:var(--pencil)}}
header.doors a.gear:hover{{color:var(--ink);background:var(--tint)}}
header.doors a.gear svg{{display:block;max-width:100%}}
main.door{{max-width:44rem;margin:0 auto;padding:1.5rem 1.25rem 3rem}}
footer.door{{max-width:44rem;margin:0 auto;padding:1rem 1.25rem 2rem;border-top:1px solid var(--line);
color:var(--pencil);font-size:.8rem;overflow-wrap:anywhere}}
footer.door code{{font-family:var(--mono);font-size:.95em}}
.pencil{{color:var(--pencil);text-decoration:underline dotted var(--pencil-rule);text-underline-offset:.2em}}
.ink{{font-family:var(--serif);color:var(--ink)}}
.fact{{color:var(--pencil);font-size:.8rem;font-variant-numeric:tabular-nums}}
@media (max-width:40rem){{
header.doors{{flex-wrap:wrap;gap:.6rem;padding:.7rem 1rem}}
header.doors a.wordmark{{font-size:1.4rem}}
form.ask{{order:3;flex:1 0 100%}}
form.ask input{{max-width:none}}
nav.doors{{position:fixed;left:0;right:0;bottom:0;z-index:10;justify-content:space-around;gap:0;
padding:.25rem .5rem .5rem;background:var(--surface);
border-top:1px solid var(--line)}}
nav.doors a{{flex:1;justify-content:center;font-size:.85rem;padding:0 .3rem}}
body{{padding-bottom:4.5rem}}
main.door,footer.door{{padding-left:1rem;padding-right:1rem}}
}}
"""


@functools.cache
def style(fonts: bool = True) -> str:
    """The doors' one stylesheet: the faces the server serves (`fonts`; none on an exported site), then
    the tokens and the frame. A door's own rules follow it."""
    return (_faces() if fonts else "") + FRAME


def header(site: Site, door: str) -> str:
    """The header of a door's page: the wordmark, the four doors (`door` the current one), Ask and the
    gear. On an exported site (`site.static`) every link goes through `site.href`, a door it has no
    page for is its name alone, and Ask and the gear are left out: there is no server to ask, and the
    machinery is the owner's."""
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
        parts.append(
            f'<form class="ask" method="get" action="{ASK}" role="search">'
            '<label for="ask">Ask</label>'
            '<input id="ask" type="search" name="q" placeholder="Ask the record" autocomplete="off">'
            "</form>"
        )
        title = escape(GEAR_TITLE)
        parts.append(f'<a class="gear" href="{GEAR}" title="{title}" aria-label="The gear">{GEAR_ICON}</a>')
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
) -> str:
    """One door's page: the head, the header (`header`), `body` in `<main class="door">`, then the
    footer the Library's every page carries (`footnote` under it). `style_` is the door's own rules,
    after the frame; `script` its one inline script, named by hash in its policy."""
    footer = site.footer_text(footnote)
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{escape(title)} · Logbook</title>\n"
        f"<style>{style(fonts=not site.static)}{style_}</style>\n</head>\n<body>\n"
        f"{header(site, door)}"
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
