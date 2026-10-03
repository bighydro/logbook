"""The poster: `logbook year YYYY --poster [--sheet A2|A3] [--html PATH]` writes one sheet — the
year as twelve columns of thirty-one squares, one a day, each in the ink of where the night was:
home, away, aboard, in transit, the four night tokens of `logbook.print_layout`; a day the record
has no night for shows the paper. Under the grid, one line: the countries of the year with their
days, as `rollup countries` counts them. Nothing else: no name of a person, a place or an asset,
no photo, no map, nothing fetched.

The sheet is drawn once as an inline SVG in millimetres of A2 (`print_layout.POSTER_VIEW_MM`) and
scaled by the stylesheet to the sheet chosen (`print_layout.poster_stylesheet`): A3 is A2 at 1/√2,
so the two sheets are the same drawing. Every length and colour comes from the layout module;
this module names classes and computes positions from its constants.

The year is read once (`reading.read` of the window `year.window` gives, as the Year's paper
edition reads it) and each night classified from the reading's nights (`token_of`): a night with
no stay reaching the minimum is in transit; a night aboard an asset is aboard before it is away; a
stay in a home region is home; any other stay is away. The countries are `rollup.countries` on
the same reading. Nothing is written (ADR 0013); the same record gives the same sheet."""

from __future__ import annotations

import calendar
from collections import Counter
from collections.abc import Mapping
from typing import Any

from . import print_layout as layout
from . import reading, rollup, stays
from . import year as year_reader
from .flights import Airports
from .store import Logbook
from .year import DOT, MONTHS, escape

POSTER = "poster"
SHEET = "A2"  # the sheet when none is asked for
MONTH_ABBREVIATIONS = tuple(m[:3] for m in MONTHS)
LEGEND_SLOT_MM = 46.0  # one token of the legend, on A2: its square and its words
FOOTER_RULE_MM = 10.0  # from the grid's foot to the rule; the countries sit under it


# -- the reading --------------------------------------------------------------------------------------------


def read(lb: Logbook, year: str, airports: Airports | None = None) -> dict[str, Any]:
    """The poster as one JSON-ready object: the year, the head, the window the record covers in
    it (None when none), every day of the year with its night token (None for a day with no
    night), the squares by token, the countries with their days. `ValueError` for a year that
    is not one; `stays.SettingsError` when the record's settings, places or assets file is not
    what it should be."""
    year = year_reader.parse_year(year)
    head = str(lb.meta.get("head") or "")
    days = grid_days(year)
    span = year_reader.window(lb, year)
    nights: dict[str, str] = {}
    countries: list[dict[str, Any]] = []
    in_transit = unknown = 0
    window = None
    if span is not None:
        first, last = span
        rd = reading.read(lb, first, last, airports or Airports.load())
        nights = {n.day: token_of(n) for n in rd.nights if n.day.startswith(year)}
        found = next((y for y in rollup.countries(rd)["years"] if y["year"] == year), None)
        if found is not None:
            countries = [{"country": c["country"], "days": c["days"]} for c in found["countries"]]
            in_transit, unknown = found["in_transit"]["days"], found["unknown"]["days"]
        window = {"since": first, "until": last, "days": len(rd.days)}
    for d in days:
        d["night"] = nights.get(str(d["day"]))
    counts = Counter(str(d["night"] or layout.NIGHT_NONE) for d in days)
    return {
        "kind": POSTER,
        "year": year,
        "head": head,
        "window": window,
        "days": days,
        "counts": {token: counts[token] for token in (*layout.NIGHTS, layout.NIGHT_NONE)},
        "countries": countries,
        "in_transit": in_transit,
        "unknown": unknown,
    }


def token_of(night: stays.Night) -> str:
    """Which of the four a night is: in transit with no stay, aboard before away, home by the
    home region, else away."""
    if night.stay is None:
        return layout.NIGHT_TRANSIT
    if night.aboard:
        return layout.NIGHT_ABOARD
    if night.home:
        return layout.NIGHT_HOME
    return layout.NIGHT_AWAY


def grid_days(year: str) -> list[dict[str, Any]]:
    """Every day of the year in order — 365, or 366 in a leap year — with its month and day of the
    month (the column and the row of its square) and no night yet."""
    out = []
    for month in range(1, 13):
        for dom in range(1, calendar.monthrange(int(year), month)[1] + 1):
            out.append({"day": f"{year}-{month:02d}-{dom:02d}", "month": month, "dom": dom, "night": None})
    return out


# -- the sheet ----------------------------------------------------------------------------------------------


def html(data: Mapping[str, Any], sheet: str = SHEET) -> str:
    """The poster as one HTML document: one inline stylesheet for the sheet, one inline SVG, no
    script, nothing fetched. `KeyError` for a sheet the layout does not know."""
    css = layout.poster_stylesheet(sheet)
    out = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{escape(data['year'])} · Logbook</title>",
        f"<style>{css}</style>",
        "</head>",
        "<body>",
        *svg(data),
        "</body>",
        "</html>",
    ]
    return "\n".join(out) + "\n"


def svg(data: Mapping[str, Any]) -> list[str]:
    """The drawing, in millimetres of A2: the kicker and the year, the legend, the month labels
    over the columns and the day numbers beside the rows, a square a day, a rule and the
    countries under the grid."""
    width, height = layout.POSTER_VIEW_MM
    grid_w, grid_h = layout.POSTER_GRID_MM
    square, gap = layout.POSTER_SQUARE_MM, layout.POSTER_GAP_MM
    block_w = width - 2 * layout.POSTER_MARGIN_MM
    left = layout.POSTER_MARGIN_MM + (block_w - grid_w - layout.POSTER_LABEL_MM) / 2
    right = left + layout.POSTER_LABEL_MM + grid_w
    x0 = left + layout.POSTER_LABEL_MM
    y0 = layout.POSTER_MARGIN_MM + layout.POSTER_HEAD_MM
    small, label = layout.POSTER_TYPE_MM["small"], layout.POSTER_TYPE_MM["label"]
    year = str(data["year"])
    caption = f"{year}: a square a day, in the ink of where the night was"
    out = [
        f'<svg class="poster" viewBox="0 0 {width:g} {height:g}" role="img" aria-label="{escape(caption)}">',
    ]
    kicker = "Logbook"
    if data["window"] is None:
        kicker += f"{DOT}the record has no days in this year"
    kicker_y = layout.POSTER_MARGIN_MM + small
    out.append(f'<text class="kicker" x="{_n(left)}" y="{_n(kicker_y)}">{escape(kicker)}</text>')
    year_y = layout.POSTER_MARGIN_MM + small + layout.POSTER_TYPE_MM["year"] + 2
    out.append(f'<text class="year" x="{_n(left)}" y="{_n(year_y)}">{escape(year)}</text>')
    # the legend, one slot a token, on the line above the month labels
    legend_y = y0 - label - 4 - small
    for n, token in enumerate(layout.NIGHTS):
        x = left + n * LEGEND_SLOT_MM
        out.append(
            f'<rect class="legend {token}" x="{_n(x)}" y="{_n(legend_y - small)}" width="{_n(small)}"'
            f' height="{_n(small)}" rx="{_n(layout.POSTER_RADIUS_MM / 2)}"/>'
        )
        words = f"{layout.NIGHT_LABEL[token]}{DOT}{_plural(int(data['counts'][token]), 'night')}"
        out.append(f'<text class="small" x="{_n(x + small + 1.5)}" y="{_n(legend_y)}">{escape(words)}</text>')
    for month in range(12):
        cx = x0 + month * (square + gap) + square / 2
        out.append(
            f'<text class="label" x="{_n(cx)}" y="{_n(y0 - 2)}" text-anchor="middle">'
            f"{escape(MONTH_ABBREVIATIONS[month])}</text>"
        )
    for row in range(layout.POSTER_ROWS):
        cy = y0 + row * (square + gap) + square / 2 + label / 3
        out.append(f'<text class="label" x="{_n(x0 - 2)}" y="{_n(cy)}" text-anchor="end">{row + 1}</text>')
    for d in data["days"]:
        x = x0 + (int(d["month"]) - 1) * (square + gap)
        y = y0 + (int(d["dom"]) - 1) * (square + gap)
        token = str(d["night"] or layout.NIGHT_NONE)
        out.append(
            f'<rect class="night {token}" data-day="{escape(d["day"])}" x="{_n(x)}" y="{_n(y)}"'
            f' width="{_n(square)}" height="{_n(square)}" rx="{_n(layout.POSTER_RADIUS_MM)}"/>'
        )
    rule_y = y0 + grid_h + FOOTER_RULE_MM
    out.append(f'<line class="rule" x1="{_n(left)}" y1="{_n(rule_y)}" x2="{_n(right)}" y2="{_n(rule_y)}"/>')
    out.append(
        f'<text class="countries" x="{_n(left)}" y="{_n(rule_y + label + 3)}">'
        f"{escape(countries_text(data))}</text>"
    )
    head = str(data.get("head") or "")
    note = "Read from the record" + (f" at head {head[:12]}…" if head else "") + ": derived, never written."
    out.append(
        f'<text class="small" x="{_n(left)}" y="{_n(rule_y + label + small + 6)}">{escape(note)}</text>'
    )
    out.append("</svg>")
    return out


def countries_text(data: Mapping[str, Any]) -> str:
    """`NO 25 days · CH 3 days · DK 2 days`, then the in-transit and unknown nights when there
    are any; `no nights in the record` when there are none."""
    parts = [f"{c['country']} {_plural(int(c['days']), 'day')}" for c in data["countries"]]
    if data["in_transit"]:
        parts.append(f"in transit {_plural(int(data['in_transit']), 'night')}")
    if data["unknown"]:
        parts.append(f"unknown {_plural(int(data['unknown']), 'night')}")
    return DOT.join(parts) if parts else "no nights in the record"


def _n(value: float) -> str:
    return f"{value:.2f}"


def _plural(n: int, noun: str) -> str:
    return f"{n:,} {noun}" if n == 1 else f"{n:,} {noun}s"
