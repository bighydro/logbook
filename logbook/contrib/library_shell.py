"""The shell every door of the Library shares (RFC 0047 §6): the header on every page, the tokens of the
owner's chosen look as custom properties, and the fonts the Library serves itself.

**The header** (`header_html`): the wordmark, *Logbook* in the serif, a link to `/`; the four doors as
text links (`DOORS`, one line a door, so each door's pull request changes its own line and no other);
**Ask**, one field, a GET form to `/search` (`name="q"`); and **the gear**, an icon button to
`/shelves`, the front page as it was, every shelf listed, so every page the old navigation reached is
one tap away. The door the page belongs to (`current`) is marked `aria-current="page"` and underlined
in ink. Under 40rem the wordmark, the gear and Ask stay at the top and the four doors are a bar fixed at
the foot of the screen, each at least 44px tall above the safe area, the page padded so the bar never
covers it.

**The tokens** (`STYLE`): the colours, the faces and their dark-mode values, on `:root` for the doors
that use them (Today; the other doors use them with fallbacks and never define `:root`), and again on
the header itself, so a page whose own stylesheet names a property the same (the Day's `--ink`) keeps
its look while its header keeps the shell's. Appended after the Library's stylesheet and before a page's
own, so every page that was there keeps its look in this build but for its borders, whose `--line` the
tokens now name.

**The fonts** (`FONTS`): Instrument Serif, Inter and JetBrains Mono, latin, woff2, bundled under
`fonts/` beside this module with each family's OFL licence, served at `/fonts/<file>` from this
package and nowhere else (`font`); the policy allows fonts from the server alone (`font-src 'self'`).
Nothing here reads the record, opens a socket or writes anything."""

from __future__ import annotations

from collections.abc import Callable
from html import escape
from pathlib import Path

# the four doors, in the order the header lists them: (name, the page it opens today). A door not yet
# built opens the page it grows from (RFC 0047 §9); each door's pull request changes its own line.
DOORS: tuple[tuple[str, str], ...] = (
    ("Today", "/"),
    ("Life", "/days"),
    ("People", "/people"),
    ("Places", "/places"),
)
GEAR = "/shelves"  # the record's machinery: every shelf, as the front page listed them before the doors
GEAR_LABEL = "The record's machinery"
ASK = "/search"
ASK_PLACEHOLDER = "Ask anything about your life"
WORDMARK = "Logbook"

FONT_DIR = Path(__file__).resolve().parent / "fonts"
FONT_PATH = "/fonts/"
FONT_TYPE = "font/woff2"
FONT_CACHE = "public, max-age=31536000, immutable"  # a file of this package: the same name, the same bytes
# family → (weight, style, file): latin only, woff2, as `@fontsource` publishes them (`npm pack`)
FONTS: tuple[tuple[str, int, str, str], ...] = (
    ("Instrument Serif", 400, "normal", "instrument-serif-latin-400-normal.woff2"),
    ("Instrument Serif", 400, "italic", "instrument-serif-latin-400-italic.woff2"),
    ("Inter", 400, "normal", "inter-latin-400-normal.woff2"),
    ("Inter", 500, "normal", "inter-latin-500-normal.woff2"),
    ("Inter", 600, "normal", "inter-latin-600-normal.woff2"),
    ("JetBrains Mono", 400, "normal", "jetbrains-mono-latin-400-normal.woff2"),
    ("JetBrains Mono", 500, "normal", "jetbrains-mono-latin-500-normal.woff2"),
)
LICENCES = ("instrument-serif-OFL.txt", "inter-OFL.txt", "jetbrains-mono-OFL.txt")

LIGHT = (
    "--paper:#F4F1EA;--surface:#FBFAF6;--line:#E3DED3;--line-soft:#ECE7DD;--tint:#EDE8DE;--ink:#16181D;"
    "--pencil:#62666D;--pencil-rule:#8C8F95;--signal:#C8401A;--signal-deep:#A93413;--card-dark:#16181D;"
    "--card-dark-text:#F4F1EA;--card-dark-muted:#C9C4B8"
)
DARK = (  # a dark paper; every text colour on its ground at 4.5:1 or more (`tests/test_door_today.py`)
    "--paper:#14161A;--surface:#1B1E23;--line:#2A2E35;--line-soft:#23272D;--tint:#20242A;--ink:#ECE8DF;"
    "--pencil:#A3A7AE;--pencil-rule:#7C8088;--signal:#C8401A;--signal-deep:#E0603A;--card-dark:#252930;"
    "--card-dark-text:#F4F1EA;--card-dark-muted:#C9C4B8"
)
FACES = (
    "--serif:'Instrument Serif',Georgia,serif;--sans:Inter,system-ui,sans-serif;"
    "--mono:'JetBrains Mono',ui-monospace,monospace"
)
GEAR_SVG = (
    '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.6"'
    ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'
    '<circle cx="12" cy="12" r="3.2"/>'
    '<path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3'
    " 1.7 1.7 0 0 0-1"
    " 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7"
    " 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1"
    "-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1"
    " 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2"
    ' 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>'
)


def _font_faces() -> str:
    return "".join(
        f"@font-face{{font-family:'{family}';font-style:{style};font-weight:{weight};font-display:swap;"
        f"src:url({FONT_PATH}{file}) format('woff2')}}\n"
        for family, weight, style, file in FONTS
    )


STYLE = (
    _font_faces()
    + f"""
:root,header.shell{{{LIGHT};{FACES}}}
@media (prefers-color-scheme:dark){{:root,header.shell{{{DARK}}}}}
header.shell{{display:flex;align-items:center;gap:1.4rem;padding:.7rem 1.5rem;margin:0;
background:var(--paper);color:var(--ink);border-bottom:1px solid var(--line);font:15px/1.4 var(--sans)}}
header.shell a.wordmark{{font:28px/1 var(--serif);font-weight:400;color:var(--ink);text-decoration:none;
margin:0;
padding:.2rem 0;white-space:nowrap}}
header.shell nav.doors{{display:flex;gap:1.4rem;flex-wrap:nowrap;row-gap:0}}
header.shell nav.doors a{{display:inline-flex;align-items:center;min-height:44px;margin:0;padding:0 .1rem;
color:var(--pencil);text-decoration:none;font-weight:500;font-size:15px;border-bottom:2px solid transparent;
box-sizing:border-box}}
header.shell nav.doors a:first-child{{font-weight:500}}
header.shell nav.doors a:hover{{color:var(--ink)}}
header.shell nav.doors a[aria-current=page]{{color:var(--ink);border-bottom-color:var(--ink)}}
header.shell form.ask{{flex:1 1 16rem;display:flex;justify-content:flex-end;margin:0;min-width:0}}
header.shell form.ask input{{width:100%;max-width:26rem;height:44px;box-sizing:border-box;border-radius:22px;
border:1px solid var(--line);background:var(--surface);color:var(--ink);padding:0 1.1rem;
font:15px var(--sans)}}
header.shell form.ask input::placeholder{{color:var(--pencil);opacity:1}}
header.shell a.gear{{display:inline-flex;align-items:center;justify-content:center;width:44px;height:44px;
flex:none;border-radius:22px;color:var(--pencil);border:1px solid transparent;box-sizing:border-box}}
header.shell a.gear:hover,header.shell a.gear[aria-current=page]{{color:var(--ink);border-color:var(--line)}}
header.shell svg{{max-width:100%}}
header.shell :focus-visible{{outline:2px solid var(--ink);outline-offset:2px}}
@media (max-width:40rem){{
header.shell{{flex-wrap:wrap;gap:.5rem .8rem;padding:.6rem 16px .7rem}}
header.shell a.wordmark{{order:1;flex:1 1 auto;font-size:26px}}
header.shell a.gear{{order:2}}
header.shell form.ask{{order:3;flex:1 1 100%}}
header.shell form.ask input{{max-width:none}}
header.shell nav.doors{{position:fixed;left:0;right:0;bottom:0;z-index:10;justify-content:space-around;gap:0;
background:var(--surface);border-top:1px solid var(--line);
padding-bottom:env(safe-area-inset-bottom)}}
header.shell nav.doors a{{flex:1 1 0;justify-content:center;min-height:52px;font-size:14px;
border-bottom:0;border-top:2px solid transparent}}
header.shell nav.doors a[aria-current=page]{{border-top-color:var(--ink)}}
body{{padding-bottom:calc(56px + env(safe-area-inset-bottom))}}
}}
"""
)


def current(path: str) -> str | None:
    """The door `path` belongs to: the door whose page it is or is under; the gear for `/shelves`; None
    for a page of no door."""
    if path == GEAR:
        return GEAR
    for name, target in DOORS:
        if path == target or (target != "/" and path.startswith(target + "/")):
            return name
    return None


def header_html(path: str, href: Callable[[str], str | None], ask: bool = True) -> str:
    """The header of the page at `path`, every link written through `href` (a server path → the link to
    write, or None for a page that has no link: the static site's); `ask` False for a page with nothing
    to submit to (a static one), which carries no form."""
    here = current(path)

    def a(text: str, target: str, cls: str = "", label: str = "", inner: str = "") -> str:
        link = href(target)
        attrs = f' class="{cls}"' if cls else ""
        attrs += f' aria-label="{escape(label)}"' if label else ""
        marked = here in (text, target) and cls != "wordmark"
        attrs += ' aria-current="page"' if marked else ""
        if link is None:
            return f"<span{attrs}>{inner or escape(text)}</span>"
        return f'<a href="{escape(link)}"{attrs}>{inner or escape(text)}</a>'

    doors = "".join(a(name, target) for name, target in DOORS)
    target = href(ASK) if ask else None
    form = (
        ""
        if target is None
        else f'<form class="ask" role="search" method="get" action="{escape(target)}">'
        f'<input type="search" name="q" placeholder="{escape(ASK_PLACEHOLDER)}" aria-label="Ask"></form>'
    )
    gear = a(GEAR_LABEL, GEAR, "gear", GEAR_LABEL, GEAR_SVG)
    return (
        '<header class="shell">'
        f"{a(WORDMARK, '/', 'wordmark')}"
        f'<nav class="doors" aria-label="The doors">{doors}</nav>'
        f"{form}{gear}</header>\n"
    )


def font(path: str) -> bytes | None:
    """The bytes of a font the Library serves at `path` (`/fonts/<file>`), or None for any other path:
    only the files `FONTS` names, read from this package and never from a path the request makes."""
    name = path.removeprefix(FONT_PATH)
    if not path.startswith(FONT_PATH) or name not in {f for *_rest, f in FONTS}:
        return None
    return (FONT_DIR / name).read_bytes()
