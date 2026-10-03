"""The typography of the paper edition, in one place.

`logbook year YYYY --html PATH --print` and `logbook trip ID --html PATH --print` write a document
designed for paper (`logbook.print_page`); every length, size, face and colour it is set in comes
from here and nowhere else, so a designer retheming the printed Logbook changes this file and
touches no logic. The renderer names classes; `stylesheet()` says what they look like. The poster
(`logbook year YYYY --poster`, `logbook.year_poster`) and the week's paper (`logbook digest --paper`,
`logbook.week_paper`) are set from the same constants: `poster_stylesheet()` and
`paper_stylesheet()` below, and the four night tokens every one of them colours a night by.

The page fits both A4 (210 × 297 mm) and US Letter (215.9 × 279.4 mm): the text block is laid out
for the narrower width and the shorter height, so one document prints on either paper without a
cut or a reflow, and the sheets differ only in their outer margins. `PAGE_SIZE` is `auto`, the
printer's own paper; set it to `A4` or `letter` to pin one. Lengths are millimetres and points,
never pixels: the print engine lays the page out at the paper's own resolution. The fonts are the
system's — a document that fetches nothing cannot carry a webfont — so the stacks name the faces
most machines have and end in the generic family."""

from __future__ import annotations

# -- the page -----------------------------------------------------------------------------------------------

PAGE_SIZE = "auto"  # the printer's paper: A4 or US Letter; `A4`, `letter`, or `A4 landscape` pins one
A4_MM = (210.0, 297.0)
LETTER_MM = (215.9, 279.4)
PAPER_WIDTH_MM = min(A4_MM[0], LETTER_MM[0])  # the narrower of the two
PAPER_HEIGHT_MM = min(A4_MM[1], LETTER_MM[1])  # the shorter of the two

MARGIN_TOP_MM = 16.0
MARGIN_BOTTOM_MM = 20.0  # the page number sits in it
MARGIN_INNER_MM = 20.0  # towards the spine, on a bound copy
MARGIN_OUTER_MM = 14.0

TEXT_WIDTH_MM = PAPER_WIDTH_MM - MARGIN_INNER_MM - MARGIN_OUTER_MM  # 176 mm
TEXT_HEIGHT_MM = PAPER_HEIGHT_MM - MARGIN_TOP_MM - MARGIN_BOTTOM_MM  # 243.4 mm

# -- the grid -----------------------------------------------------------------------------------------------

COLUMNS = 6  # the text block is six columns; the facts take two, the map and the photos the rest
GUTTER_MM = 5.0
COLUMN_MM = (TEXT_WIDTH_MM - GUTTER_MM * (COLUMNS - 1)) / COLUMNS
FACTS_COLUMNS = 2  # the facts column of a spread
FACTS_WIDTH_MM = FACTS_COLUMNS * COLUMN_MM + (FACTS_COLUMNS - 1) * GUTTER_MM

# -- the type -----------------------------------------------------------------------------------------------

BASE_PT = 10.0
LEADING = 1.4  # line height, as a multiple of the size
SCALE = 1.25  # a major third between the steps of the scale
SIZES_PT = {
    "small": BASE_PT / SCALE,  # captions, the page number, the scale bar
    "body": BASE_PT,
    "lead": BASE_PT * SCALE,  # the line under a heading
    "h3": BASE_PT * SCALE**2,
    "h2": BASE_PT * SCALE**4,  # a month, a day
    "h1": BASE_PT * SCALE**8,  # the cover: the year, the trip's dates
}

FONT_TEXT = 'Georgia, "Iowan Old Style", "Palatino Linotype", "Book Antiqua", "Times New Roman", serif'
FONT_LABEL = '-apple-system, "Segoe UI", "Helvetica Neue", Helvetica, Arial, sans-serif'
FONT_MONO = 'ui-monospace, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace'

# -- the ink ------------------------------------------------------------------------------------------------

INK = "#1b1b1b"
MUTED = "#6b6b6b"
RULE = "#c9c9c4"
PAPER = "#ffffff"
FRAME = "#ebebe7"  # the slot of a photo the record does not hold

# -- the nights ---------------------------------------------------------------------------------------------

# The four words a night can be, in the order a legend lists them, and the ink each prints in: the
# poster's squares, and any other place a night is coloured rather than named. A night aboard an asset
# is `aboard` before it is `away`; a night with no stay reaching the minimum is `transit`. `NIGHT_NONE`
# is a day the record has no night for: the paper shows through.
NIGHT_HOME, NIGHT_AWAY, NIGHT_ABOARD, NIGHT_TRANSIT = "home", "away", "aboard", "transit"
NIGHTS = (NIGHT_HOME, NIGHT_AWAY, NIGHT_ABOARD, NIGHT_TRANSIT)
NIGHT_INK = {
    NIGHT_HOME: "#d9d4c7",  # the quiet one: most nights
    NIGHT_AWAY: "#2f5d8a",
    NIGHT_ABOARD: "#2a8c7e",
    NIGHT_TRANSIT: "#e0a040",
}
NIGHT_LABEL = {NIGHT_HOME: "home", NIGHT_AWAY: "away", NIGHT_ABOARD: "aboard", NIGHT_TRANSIT: "in transit"}
NIGHT_NONE = "none"  # the class of a day without a night; it prints in `FRAME`

# -- the map ------------------------------------------------------------------------------------------------

MAP_VIEW_PX = (640, 420)  # the SVG's viewBox; the drawing scales to the figure's width on the page
MAP_WIDTH_MM = TEXT_WIDTH_MM - FACTS_COLUMNS * (COLUMN_MM + GUTTER_MM)  # beside the facts column
MAP_HEIGHT_MM = MAP_WIDTH_MM * MAP_VIEW_PX[1] / MAP_VIEW_PX[0]
ROUTE_MAP_WIDTH_MM = 140.0  # a trip's route, on its own page before the days, with the stays under it

# -- the photos ---------------------------------------------------------------------------------------------

PHOTOS_PER_PAGE = 6  # two columns by three rows; a month with more keepers takes more pages
CAPTION_MM = 7.0  # the line under a photo
PHOTO_ONE_MM = TEXT_HEIGHT_MM - CAPTION_MM  # one hero photo: the page
PHOTO_TWO_MM = (TEXT_HEIGHT_MM - 2 * (CAPTION_MM + GUTTER_MM)) / 2  # two: stacked
PHOTO_FOUR_MM = PHOTO_TWO_MM  # three or four: two by two
PHOTO_SIX_MM = (TEXT_HEIGHT_MM - 3 * (CAPTION_MM + GUTTER_MM)) / 3  # five or six: two by three


def mm(value: float) -> str:
    return f"{value:.2f}mm"


def pt(value: float) -> str:
    return f"{value:.2f}pt"


def stylesheet() -> str:
    """The one stylesheet of the document, from the constants above: the page boxes (both faces
    and the cover), the type, the spreads, the map and the photos; a screen rule so the file
    reads in a browser before it is printed."""
    body_lh = f"{LEADING}"
    return f"""
@page {{
  size: {PAGE_SIZE};
  margin: {mm(MARGIN_TOP_MM)} {mm(MARGIN_OUTER_MM)} {mm(MARGIN_BOTTOM_MM)} {mm(MARGIN_INNER_MM)};
  @bottom-center {{ content: counter(page); font: {pt(SIZES_PT["small"])} {FONT_LABEL}; color: {MUTED}; }}
}}
@page :left {{ margin-left: {mm(MARGIN_OUTER_MM)}; margin-right: {mm(MARGIN_INNER_MM)}; }}
@page :right {{ margin-left: {mm(MARGIN_INNER_MM)}; margin-right: {mm(MARGIN_OUTER_MM)}; }}
@page cover {{ @bottom-center {{ content: none; }} }}
:root {{ color-scheme: light; }}
html {{ background: {PAPER}; }}
body {{ margin: 0; padding: 0; color: {INK}; background: {PAPER};
  font: {pt(SIZES_PT["body"])}/{body_lh} {FONT_TEXT}; }}
h1, h2, h3 {{ font-family: {FONT_LABEL}; font-weight: 600; letter-spacing: -.02em; margin: 0; }}
h1 {{ font-size: {pt(SIZES_PT["h1"])}; line-height: 1; }}
h2 {{ font-size: {pt(SIZES_PT["h2"])}; line-height: 1.1; }}
h3 {{ font-size: {pt(SIZES_PT["h3"])}; line-height: 1.2; margin: 0 0 {mm(GUTTER_MM / 2)}; }}
p {{ margin: 0 0 {mm(GUTTER_MM / 2)}; }}
.kicker {{ font: 600 {pt(SIZES_PT["small"])}/1.4 {FONT_LABEL}; text-transform: uppercase;
  letter-spacing: .12em; color: {MUTED}; margin: 0 0 {mm(GUTTER_MM / 2)}; }}
.lead {{ font-size: {pt(SIZES_PT["lead"])}; color: {MUTED}; }}
.muted {{ color: {MUTED}; }}
.n {{ font-family: {FONT_LABEL}; font-variant-numeric: tabular-nums; }}

section.cover {{ page: cover; break-after: page; min-height: {mm(TEXT_HEIGHT_MM * 0.9)};
  display: flex; flex-direction: column; justify-content: flex-end; }}
section.cover h1 {{ margin: 0 0 {mm(GUTTER_MM)}; }}
section.cover .name {{ font-size: {pt(SIZES_PT["h3"])}; margin: 0; }}
section.cover .dates {{ font-size: {pt(SIZES_PT["lead"])}; color: {MUTED}; }}
section.cover .rule {{ border: 0; border-top: 1px solid {INK}; margin: {mm(GUTTER_MM)} 0; }}

section.contents {{ break-after: page; }}
section.contents h2 {{ margin-bottom: {mm(GUTTER_MM)}; }}
ol.contents {{ list-style: none; margin: 0; padding: 0; }}
ol.contents li {{ display: grid; grid-template-columns: {mm(COLUMN_MM * 2 + GUTTER_MM)} 1fr;
  gap: 0 {mm(GUTTER_MM)}; padding: {mm(GUTTER_MM / 2)} 0; border-bottom: 1px solid {FRAME};
  break-inside: avoid; }}
ol.contents li .what {{ font-family: {FONT_LABEL}; font-weight: 600; }}
ol.contents li .about {{ color: {MUTED}; }}
section.route {{ break-before: page; break-after: page; }}
section.route h2 {{ margin-bottom: {mm(GUTTER_MM)}; }}
section.route figure.map {{ margin: 0 0 {mm(GUTTER_MM)}; }}
section.route figure.map svg {{ max-width: {mm(ROUTE_MAP_WIDTH_MM)}; }}
table {{ border-collapse: collapse; width: 100%; margin: 0 0 {mm(GUTTER_MM)}; }}
th, td {{ text-align: left; vertical-align: top; padding: {mm(1)} {mm(GUTTER_MM / 2)} {mm(1)} 0;
  border-bottom: 1px solid {FRAME}; }}
th {{ font: 600 {pt(SIZES_PT["small"])}/1.4 {FONT_LABEL}; color: {MUTED}; text-transform: uppercase;
  letter-spacing: .06em; }}
td.n, th.n {{ text-align: right; white-space: nowrap; }}
td.d {{ white-space: nowrap; font-variant-numeric: tabular-nums; }}

section.spread > article {{ break-before: page; }}
article.facts {{ display: grid; grid-template-columns: {mm(FACTS_WIDTH_MM)} 1fr;
  gap: 0 {mm(GUTTER_MM)}; }}
article.facts header {{ grid-column: 1 / -1; margin-bottom: {mm(GUTTER_MM)};
  padding-bottom: {mm(GUTTER_MM / 2)}; border-bottom: 1px solid {INK}; }}
article.facts header h2 {{ margin: 0; }}
article.facts header .lead {{ margin: {mm(1)} 0 0; }}
dl.facts {{ margin: 0; }}
dl.facts dt {{ font: 600 {pt(SIZES_PT["small"])}/1.4 {FONT_LABEL}; text-transform: uppercase;
  letter-spacing: .08em; color: {MUTED}; margin-top: {mm(GUTTER_MM / 2)}; }}
dl.facts dd {{ margin: 0; }}
dl.facts dd.empty {{ color: {MUTED}; }}
ol.places {{ margin: 0; padding-left: 1.4em; }}
ol.places li {{ padding-left: .2em; }}
ol.places .count {{ color: {MUTED}; }}
figure.map {{ margin: 0; align-self: start; }}
figure.map svg {{ display: block; width: 100%; height: auto; border: 1px solid {RULE}; }}
figure.map figcaption {{ font: {pt(SIZES_PT["small"])}/1.4 {FONT_LABEL}; color: {MUTED};
  margin-top: {mm(1.5)}; }}
figure.map.empty .none {{ display: flex; align-items: center; justify-content: center;
  height: {mm(MAP_HEIGHT_MM)}; border: 1px solid {RULE}; color: {MUTED}; }}
.track {{ fill: none; stroke: {INK}; stroke-width: 1.5; stroke-linejoin: round; stroke-linecap: round; }}
.leg {{ fill: none; stroke: {INK}; stroke-width: 2; stroke-linecap: round; }}
.leg.transit {{ stroke-dasharray: 6 5; }}
.stay {{ fill: {PAPER}; stroke: {INK}; stroke-width: 1.5; }}
.mark {{ font: 600 11px {FONT_LABEL}; fill: {INK}; }}
.scale {{ stroke: {INK}; stroke-width: 1.5; }}
.scale-text {{ font: 10px {FONT_LABEL}; fill: {MUTED}; }}

article.photos {{ display: grid; gap: {mm(GUTTER_MM)}; align-content: start; }}
article.photos.n1 {{ grid-template-columns: 1fr; }}
article.photos.n2 {{ grid-template-columns: 1fr; }}
article.photos.n4 {{ grid-template-columns: 1fr 1fr; }}
article.photos.n6 {{ grid-template-columns: 1fr 1fr; }}
figure.photo {{ margin: 0; break-inside: avoid; }}
figure.photo img, figure.photo .frame {{ display: block; width: 100%; object-fit: contain;
  object-position: left top; }}
figure.photo .frame {{ display: flex; align-items: center; justify-content: center; text-align: center;
  background: {FRAME}; color: {MUTED}; font: {pt(SIZES_PT["small"])}/1.4 {FONT_LABEL}; }}
.n1 figure.photo img, .n1 figure.photo .frame {{ height: {mm(PHOTO_ONE_MM)}; }}
.n2 figure.photo img, .n2 figure.photo .frame {{ height: {mm(PHOTO_TWO_MM)}; }}
.n4 figure.photo img, .n4 figure.photo .frame {{ height: {mm(PHOTO_FOUR_MM)}; }}
.n6 figure.photo img, .n6 figure.photo .frame {{ height: {mm(PHOTO_SIX_MM)}; }}
figure.photo figcaption {{ font: {pt(SIZES_PT["small"])}/1.4 {FONT_LABEL}; color: {MUTED};
  height: {mm(CAPTION_MM)}; overflow: hidden; margin-top: {mm(1)}; }}

footer.colophon {{ break-before: page; color: {MUTED}; font-size: {pt(SIZES_PT["small"])};
  border-top: 1px solid {RULE}; padding-top: {mm(GUTTER_MM / 2)}; }}

@media screen {{
  body {{ max-width: {mm(TEXT_WIDTH_MM)}; margin: {mm(MARGIN_TOP_MM)} auto;
    padding: 0 {mm(MARGIN_OUTER_MM)}; }}
  section.cover, section.contents, section.route, section.spread > article, footer.colophon {{
    padding-bottom: {mm(GUTTER_MM * 2)}; margin-bottom: {mm(GUTTER_MM * 2)};
    border-bottom: 1px dashed {RULE}; }}
}}
"""


# -- the poster ---------------------------------------------------------------------------------------------

# `logbook year YYYY --poster`: one sheet, A2 or A3, the year as twelve columns of thirty-one squares,
# one a day, each in the ink of its night. The A series keeps its proportions from one size to the
# next (A3 is A2 at 1/√2), so the sheet is drawn once, in millimetres of A2 (`POSTER_VIEW_MM`, the
# SVG's viewBox), and scaled to the sheet chosen; every length below is on A2.
POSTER_SHEETS = {"A2": (420.0, 594.0), "A3": (297.0, 420.0)}
POSTER_VIEW_MM = POSTER_SHEETS["A2"]
POSTER_MARGIN_MM = 30.0
POSTER_COLUMNS = 12  # a month a column
POSTER_ROWS = 31  # a day a row
POSTER_GAP_MM = 2.0  # between two squares
POSTER_HEAD_MM = 70.0  # above the grid: the year and the legend
POSTER_FOOT_MM = 30.0  # under it: the countries
POSTER_SQUARE_MM = (
    POSTER_VIEW_MM[1]
    - 2 * POSTER_MARGIN_MM
    - POSTER_HEAD_MM
    - POSTER_FOOT_MM
    - (POSTER_ROWS - 1) * POSTER_GAP_MM
) / POSTER_ROWS
POSTER_GRID_MM = (
    POSTER_COLUMNS * POSTER_SQUARE_MM + (POSTER_COLUMNS - 1) * POSTER_GAP_MM,
    POSTER_ROWS * POSTER_SQUARE_MM + (POSTER_ROWS - 1) * POSTER_GAP_MM,
)
POSTER_LABEL_MM = 12.0  # left of the grid: the day numbers; above it: the months
POSTER_RADIUS_MM = 0.8  # the corner of a square
POSTER_TYPE_MM = {"year": 36.0, "label": 4.2, "small": 3.4}  # the year; the months and days; the rest


def vu(value: float) -> str:
    """A length inside the poster's drawing: a user unit of its viewBox, which is one millimetre
    of A2 and scales with the sheet. CSS writes a user unit as `px`; it is not a pixel."""
    return f"{value:.2f}px"


def poster_stylesheet(sheet: str) -> str:
    """The poster's stylesheet for one sheet (`A2` or `A3`): the page is the sheet with no margin,
    the drawing fills it, the type in the drawing's own units (`vu`), the four night tokens and
    the empty day its fills; a screen rule so the file reads in a browser before it is printed.
    `KeyError` for a sheet that is not one."""
    width, height = POSTER_SHEETS[sheet]
    fills = "\n".join(f".night.{name} {{ fill: {ink}; }}" for name, ink in NIGHT_INK.items())
    return f"""
@page {{ size: {sheet}; margin: 0; }}
:root {{ color-scheme: light; }}
html {{ background: {PAPER}; }}
body {{ margin: 0; padding: 0; color: {INK}; background: {PAPER}; font-family: {FONT_LABEL}; }}
svg.poster {{ display: block; width: {mm(width)}; height: {mm(height)}; }}
.year {{ font: 600 {vu(POSTER_TYPE_MM["year"])} {FONT_LABEL}; fill: {INK}; letter-spacing: -.02em; }}
.label {{ font: {vu(POSTER_TYPE_MM["label"])} {FONT_LABEL}; fill: {MUTED}; }}
.countries {{ font: 600 {vu(POSTER_TYPE_MM["label"])} {FONT_LABEL}; fill: {INK}; }}
.small {{ font: {vu(POSTER_TYPE_MM["small"])} {FONT_LABEL}; fill: {MUTED}; }}
.kicker {{ font: 600 {vu(POSTER_TYPE_MM["small"])} {FONT_LABEL}; fill: {MUTED}; letter-spacing: .12em;
  text-transform: uppercase; }}
.night {{ stroke: none; }}
{fills}
.night.{NIGHT_NONE} {{ fill: {FRAME}; }}
.rule {{ stroke: {INK}; stroke-width: 0.3; }}
@media screen {{
  body {{ padding: {mm(GUTTER_MM * 2)}; }}
  svg.poster {{ max-width: 100%; height: auto; box-shadow: 0 0 0 {mm(0.25)} {RULE}; }}
}}
"""


# -- the week's paper ---------------------------------------------------------------------------------------

# `logbook digest --paper --week YYYY-Www`: the week as four pages of A4, set with the same text block,
# grid, type and ink as the Year (`stylesheet()`); only the sheet is pinned, so one paper is one paper.
PAPER_SHEET = "A4"
PAPER_PAGES = 4
PAPER_DAY_MM = COLUMN_MM * 1 + GUTTER_MM  # the day column of the week's list: one column of the grid


def paper_stylesheet() -> str:
    """The week's stylesheet: the Year's (`stylesheet()`), then the sheet pinned to A4 and the
    rules of the paper's own classes — a page a section, the week's days as a two-column list,
    the people, the keepers, the promises and the titles read."""
    return (
        stylesheet()
        + f"""
@page {{ size: {PAPER_SHEET}; }}
section.page {{ break-after: page; }}
section.page:last-of-type {{ break-after: auto; }}
section.page > header {{ margin-bottom: {mm(GUTTER_MM)}; padding-bottom: {mm(GUTTER_MM / 2)};
  border-bottom: 1px solid {INK}; }}
section.page > header h2 {{ margin: 0; }}
section.page > header .lead {{ margin: {mm(1)} 0 0; }}
ol.contents.days li {{ grid-template-columns: {mm(PAPER_DAY_MM)} 1fr; }}
ol.contents.days li .about {{ color: {INK}; }}
ol.contents.days li .night {{ color: {MUTED}; }}
ul.titles {{ margin: 0 0 {mm(GUTTER_MM / 2)}; padding-left: 1.2em; }}
ul.titles li {{ padding-left: .2em; break-inside: avoid; }}
blockquote {{ margin: 0; font-style: italic; }}
footer.note {{ color: {MUTED}; font-size: {pt(SIZES_PT["small"])}; margin-top: {mm(GUTTER_MM * 2)};
  border-top: 1px solid {RULE}; padding-top: {mm(GUTTER_MM / 2)}; }}
@media screen {{
  section.page {{ padding-bottom: {mm(GUTTER_MM * 2)}; margin-bottom: {mm(GUTTER_MM * 2)};
    border-bottom: 1px dashed {RULE}; }}
}}
"""
    )
