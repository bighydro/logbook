"""The Library's doors share one frame (RFC 0047 §6): the header, one stylesheet of the owner's tokens,
and three typefaces served by the Library itself. Today (`door_today`) is the first page in it; Life,
People and Places (`door_life`, `door_people`, `door_places`) render through `page` too. Every other
page of the Library carries the same header (`header`) and reads the same sheet with the pages' rules
after it (`library_style`, `PAGES`): the doors' look, its content, order and address as they were.

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
# the four doors and where each opens until its own page is on main (RFC 0047 §4, §5); the fifth,
# Holdings, goes between Places and Ask when it is built, and its place stays empty until then (§11)
DOORS = ((TODAY, "/"), (LIFE, "/life"), (PEOPLE, "/people"), (PLACES, "/places"))
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
# the Library's every other page in the doors' look (`library_style`): its main and footer in the header's
# column; the serif for page titles, section titles and names, Inter for the body, the mono for labels;
# lists of things and tables on cards; the page's actions as pills; every control 44px; the chart colours
# (`--stay`, `--move`, ...) on `main` alone, for graphics and never for text. No `:root` here: the tokens
# are `ROOT`'s, and the dark face is `DARK`'s. Text keeps the Library's floor at a phone's width
# (tests/test_phone_targets.py): 14 px, the mono labels 13 px.
PAGES = """main{max-width:72rem;margin:0 auto;padding:2.5rem 1.25rem 4rem;font-size:15px;
--stay:#2e7d4f;--move:#3a62b0;--aboard:#1f6f88;--call:#a35a16;--plan:#868b93;--star:#9a760f}
body>footer{max-width:72rem;margin:0 auto;padding:1rem 1.25rem 2rem;border-top:1px solid var(--line);
color:var(--pencil);font-size:14px;overflow-wrap:anywhere}
body>footer code{font-family:var(--mono);font-size:.95em}
main h1{margin:0 0 1.2rem;font-weight:400;font-size:72px;line-height:1.02;font-family:var(--serif);
overflow-wrap:anywhere}
main h1 small{font-weight:400;font-size:15px;line-height:1.5;font-family:var(--sans);color:var(--pencil);
letter-spacing:0}
main h2{margin:2.6rem 0 .9rem;font-weight:400;font-size:36px;line-height:1.1;font-family:var(--serif)}
main h2 small{font-weight:400;font-size:14px;font-family:var(--sans);color:var(--pencil)}
main h3{margin:1.4rem 0 .5rem;font-weight:500;font-size:13px;line-height:1.4;font-family:var(--mono);
letter-spacing:.13em;text-transform:uppercase;color:var(--pencil)}
main code{font-family:var(--mono);font-size:.9em;overflow-wrap:anywhere}
main table{width:100%;border-collapse:separate;border-spacing:0;margin:.6rem 0 1.4rem;
background:var(--surface);border:1px solid var(--line);border-radius:20px}
main th,main td{text-align:left;padding:.75rem .9rem;border-bottom:1px solid var(--line-soft);
vertical-align:top}
main th{font-weight:500;font-size:13px;font-family:var(--mono);letter-spacing:.12em;text-transform:uppercase;
color:var(--pencil);border-bottom-color:var(--line)}
main td.num,main th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
main td.day,main td.at,main span.run{white-space:nowrap}
main td.day a{display:inline-flex;align-items:center;min-height:44px}
dl.header{display:grid;grid-template-columns:max-content 1fr;gap:.45rem 1.4rem;margin:0 0 1.4rem;
align-items:baseline}
dl.header dt{font-weight:500;font-size:13px;font-family:var(--mono);letter-spacing:.12em;
text-transform:uppercase;color:var(--pencil)}
dl.header dd{margin:0;min-width:0}
ol.timeline,ol.inside,ul.attached,ul.unplaced,ul.plain,ul.proposals{list-style:none;padding:0;margin:0}
li.proposal{padding:.4rem 0}
li.proposal>p.head{color:var(--pencil);text-decoration:underline dotted var(--pencil-rule);
text-underline-offset:.2em}
main textarea.pencil{color:var(--pencil);border-style:dotted}
.row{padding:.7rem 0;border-bottom:1px solid var(--line-soft)}
.clock{display:inline-block;min-width:7.5rem;font-variant-numeric:tabular-nums;color:var(--pencil);
font-size:14px;font-family:var(--mono)}
.kind{display:inline-block;min-width:5.5rem;font-weight:500;font-size:14px;font-family:var(--mono);
text-transform:uppercase;letter-spacing:.12em;color:var(--pencil)}
ol.inside{margin:.3rem 0 0 2rem}
ol.inside .row{border:0;padding:.15rem 0}
details{margin:.3rem 0 0 7.5rem}
summary{cursor:pointer;color:var(--pencil);min-height:44px;padding:.6rem 0}
ul.attached{margin:.3rem 0 0 1rem}
details.synthesis,p.synthesis{margin:.2rem 0 .3rem 1.5rem;font-size:14px}
details.synthesis p.segment{margin:.15rem 0}
ul.attached li,ul.unplaced li{padding:.3rem 0}
p.with{margin:.3rem 0 0 1rem;color:var(--pencil)}
form.window{display:flex;gap:.6rem;align-items:center;flex-wrap:wrap;margin:0 0 1.2rem}
main input,main select{min-height:44px;padding:0 .9rem;border:1px solid var(--line);border-radius:12px;
background:var(--surface);color:var(--ink);font:inherit;font-size:15px}
main input[type=checkbox],main input[type=radio]{min-height:0;width:1.2rem;height:1.2rem;padding:0;
accent-color:var(--ink)}
main input[type=file]{padding:.5rem .9rem;max-width:100%}
main textarea{display:block;width:100%;min-height:8rem;padding:.8rem 1rem;border:1px solid var(--line);
border-radius:14px;background:var(--surface);color:var(--ink);font-size:17px;line-height:1.5;font-family:var(--serif)}
main button,a.skip{display:inline-flex;align-items:center;justify-content:center;min-height:44px;
padding:0 1.2rem;border-radius:23px;border:1px solid var(--ink);background:var(--ink);color:var(--paper);
font-weight:600;font-size:14px;font-family:var(--sans);text-decoration:none;cursor:pointer}
main a.skip,main form.act button,main form.window button,main button[value=reject]{border-color:var(--line);
background:var(--surface);color:var(--ink)}
main form.act button[value=name]{border-color:var(--ink);background:var(--ink);color:var(--paper)}
main button:hover,a.skip:hover{border-color:var(--signal)}
p.pager,p.mute,.mute{color:var(--pencil)}
p.pager a,p.zooms a,p.facets a{display:inline-flex;align-items:center;min-height:44px}
a.name{display:inline-flex;align-items:center;min-height:44px;font-size:14px;margin-left:.5rem;color:var(--pencil)}
main form.star{display:inline;margin:0 0 0 .3rem}
main form.star button{min-width:44px;padding:0;border:0;background:none;color:var(--pencil-rule);
font-weight:400;font-size:1.05rem;line-height:1}
main form.star button[aria-pressed=true],.star.on{color:var(--star)}
form.with{display:inline-flex;gap:.4rem;align-items:center;flex-wrap:wrap;margin-left:.6rem}
form.with input[type=text]{width:12rem;min-width:0;max-width:100%}
ul.starred{list-style:none;padding:0;margin:0}
ul.starred li{padding:.3rem 0}
ol.timeline li:target,ul.attached li:target,ul.attached span:target,ul.unplaced li:target,
dt#with:target,li.cluster:target,ol.shelf>li:target{background:var(--tint)}
ol.queue,ol.shelf{list-style:none;margin:.6rem 0 1.4rem;padding:.4rem 28px;background:var(--surface);
border:1px solid var(--line);border-radius:20px}
li.cluster{display:grid;grid-template-columns:10rem 1fr;gap:.4rem 1.4rem;padding:1.4rem 0;
border-bottom:1px solid var(--line-soft)}
ol.queue>li:last-child,ol.shelf>li:last-child{border-bottom:0}
li.cluster svg{grid-row:1/4;width:10rem;height:6.5rem;border:1px solid var(--line);border-radius:12px;
background:var(--paper)}
li.cluster svg text{font:12px var(--sans);fill:var(--pencil)}
li.cluster svg circle.spot{fill:var(--ink)}
li.cluster svg circle.ring,li.cluster svg circle.near{fill:none;stroke:var(--pencil);stroke-dasharray:3 2}
li.cluster svg line{stroke:var(--pencil-rule)}
li.cluster p.facts{margin:0}
li.cluster p.facts b{font-weight:500;font-variant-numeric:tabular-nums}
ul.evidence{list-style:none;padding:0;margin:0;color:var(--pencil);font-size:14px}
li.cluster details{margin:0;font-size:14px}
form.name{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap;margin:.5rem 0 0}
form.name input[type=text]{min-width:16rem;flex:1}
section.close{margin:2.6rem 0 0;padding:28px 32px;background:var(--surface);border:1px solid var(--line);
border-radius:20px}
section.close h2{margin-top:0}
section.part.close{margin:0;padding:0;background:none;border:0;border-radius:0}
section.close form{margin:.6rem 0 1rem}
section.close button{margin:.6rem .4rem 0 0}
section.close details{margin:.4rem 0}
section.close label{overflow-wrap:anywhere}
ol.proposals,ol.sentences{padding:0;margin:.3rem 0}
ol.proposals{list-style:none}
ol.sentences{padding-left:2rem}
ol.proposals li{padding:.5rem 0;border-bottom:1px solid var(--line-soft)}
ol.proposals label{display:flex;gap:.6rem;align-items:baseline;min-height:44px;cursor:pointer}
ol.proposals input{flex:none}
ul.signed{color:var(--pencil);margin:.4rem 0}
code.sha{overflow-wrap:anywhere}
footer .footnote{display:inline-block;margin-top:.3rem}
ol.shelf>li{padding:1.1rem 0;border-bottom:1px solid var(--line-soft);overflow-wrap:anywhere}
ol.shelf p{margin:.15rem 0}
p.head{display:flex;flex-wrap:wrap;gap:.1rem .8rem;align-items:baseline}
p.head>a{font-weight:400;font-size:24px;line-height:1.25;font-family:var(--serif);
text-decoration:none}
p.head>a:hover{text-decoration:underline;text-decoration-color:var(--signal)}
p.head .mute{font-size:14px;font-variant-numeric:tabular-nums}
p.facts{color:var(--pencil);font-size:14px;overflow-wrap:anywhere}
details.evidence,details.draft{margin:.25rem 0 0}
details.evidence>summary{font-size:14px}
details.evidence ul.evidence{margin:.2rem 0 0 .8rem}
details.evidence details{margin:0 0 0 .8rem}
span.id{font-size:14px;font-family:var(--mono);color:var(--pencil)}
details.draft>summary{font-size:14px}
div.draft p.segment{margin:.3rem 0}
p.segment.unsupported{border-left:2px solid var(--line);padding-left:.6rem}
.dates{white-space:nowrap}
svg.stays,svg.track{display:block;width:100%;max-width:30rem;height:auto;margin:.6rem 0;
border:1px solid var(--line);border-radius:16px;background:var(--surface)}
svg.stays circle,svg.track circle{fill:var(--ink);fill-opacity:.8;stroke:var(--surface)}
svg.stays text,svg.track text{font:12px var(--sans);fill:var(--ink)}
svg.stays line,svg.track line{stroke:var(--pencil-rule)}
svg.track line{stroke-width:1.5}
svg.track line.gap{stroke-dasharray:4 3}
li.proposal form{display:flex;flex-wrap:wrap;gap:.5rem;margin:.4rem 0 0}
.badge{display:inline-flex;align-items:center;min-height:22px;padding:0 .6rem;border:1px solid var(--line);
border-radius:11px;font-weight:500;font-size:13px;font-family:var(--mono);text-transform:uppercase;
letter-spacing:.12em;color:var(--pencil);background:var(--paper)}
.badge.open,.badge.passed,.badge.stalled,.badge.past{color:var(--signal-deep);border-color:var(--signal-deep)}
.badge.hold,.badge.add,.badge.sell,.badge.kept,.badge.advancing{color:var(--ink)}
.badge.exited,.badge.let-go{color:var(--pencil)}
.stale-flag{color:var(--signal-deep)}
ol.shelf>li.stale{border-left:3px solid var(--signal);padding-left:.8rem}
p.reason{margin:.2rem 0 0;font-style:italic;font-family:var(--serif);font-size:17px}
form.act{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;margin:.5rem 0}
form.act input[type=text]{flex:1 1 10rem;min-width:0}
form.act select,form.act input[type=date]{max-width:100%}
section.acts{margin:1rem 0;padding:20px 28px;background:var(--surface);border:1px solid var(--line);
border-radius:20px}
s.retracted{color:var(--pencil)}
blockquote.said{margin:.4rem 0;padding-left:.9rem;border-left:2px solid var(--line);overflow-wrap:anywhere;
font-size:17px;font-family:var(--serif);color:var(--ink)}
blockquote.machine{font-family:var(--sans);font-size:15px;color:var(--pencil);font-style:italic}
q.said{overflow-wrap:anywhere;font-family:var(--serif);font-size:19px;color:var(--pencil);
text-decoration:underline dotted var(--pencil-rule);text-underline-offset:.22em}
main h1 q.said{font-size:inherit}
ol.shelf p.pencil{font-family:var(--serif);font-size:19px}
p.head>a b,blockquote.said b,main h1 b,main h2 b{font-weight:400}
main h1 a,main h2 a{text-decoration:none}
main h1 a:hover,main h2 a:hover{text-decoration:underline;text-decoration-color:var(--signal)}
main input::placeholder,main textarea::placeholder{color:var(--pencil)}
ol.shelf details{margin-left:0}
main>ul.plain{margin:.6rem 0 1.4rem;padding:.4rem 28px;background:var(--surface);border:1px solid var(--line);
border-radius:20px}
main>ul.plain>li{padding:.8rem 0;border-bottom:1px solid var(--line-soft)}
main>ul.plain>li:last-child{border-bottom:0}
p.people{display:flex;flex-wrap:wrap;gap:.2rem .8rem;overflow-wrap:anywhere}
p.note{margin:.2rem 0 0;font-style:italic;font-family:var(--serif);font-size:17px;overflow-wrap:anywhere}
p.summary{margin:.2rem 0;overflow-wrap:anywhere}
p.refs{overflow-wrap:anywhere}
pre.file{white-space:pre-wrap;overflow-wrap:anywhere;max-width:100%;font-family:var(--mono);font-size:14px}
pre.line{max-width:100%;overflow-x:auto;white-space:pre;
font:14px/1.5 var(--mono);padding:20px 24px;background:var(--surface);border:1px solid var(--line);
border-radius:20px}
dl.header dd{overflow-wrap:anywhere}
@media (max-width:40rem){
main{padding:1.5rem 1rem 3rem}
p.head>a,main h2>a,p.people>a,p.ids>a,p.gear-crumb>a,a.person,p.facts>a,dd>a{display:inline-flex;
align-items:center;min-height:44px}
body>footer{padding-left:1rem;padding-right:1rem}
main h1{font-size:40px;line-height:1.05}
main h2{font-size:28px}
details{margin-left:1rem}
.clock{min-width:0;margin-right:.5rem}
main table{display:block;overflow-x:auto}
main th,main td{white-space:nowrap}
li.cluster{grid-template-columns:1fr}
li.cluster svg{grid-row:auto;max-width:100%}
ol.queue,ol.shelf{padding:.2rem 20px}
section.close,section.acts{padding:20px}
pre.line{font-size:14px;padding:16px}
}
@media (prefers-color-scheme:dark){main{--stay:#6cc08a;--move:#88a8ea;--aboard:#6fc2da;--call:#e39a55;
--plan:#8d9299;--star:#e2bf52}}
"""


@functools.cache
def style(fonts: bool = True) -> str:
    """The doors' one stylesheet: the faces the server serves (`fonts`; none on an exported site), then
    the tokens and the frame. A door's own rules follow it."""
    return (_faces() if fonts else "") + FRAME


@functools.cache
def library_style(fonts: bool = True) -> str:
    """The stylesheet of every page of the Library that is not a door's: the doors' one stylesheet
    (`style`), then the pages' rules in its tokens (`PAGES`). A page's own rules follow it."""
    return style(fonts) + PAGES


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
