"""`logbook export world --style chart`: the record on paper, the page `world.py` writes with this
module's script, style and legend. A logbook is a ship's instrument, and the record drawn on a chart is
what a logbook always looked like.

The paper is either **drawn** — Mercator's sea chart on the canvas, no image in it: sepia paper, the
coasts of the same land table as the globe hachured, a compass rose with its thirty-two rhumb lines,
the graticule engraved with a graduated border, names and dates in the system's serif (no font is
bundled: one would have to be fetched to be vendored, and nothing is) — or the **owner's own chart**, a
scanned PNG or JPEG they give with `--chart FILE`, its control points with `--control-points FILE`
(`chart_fit`), carried in the page under the cap (`chart_image`) and credited in the legend in the words
of `--chart-credit`, never in anything read from the file. Two rules hold on either: the chart is
paper, the track is evidence. The page's record JSON is the globe's, byte for byte (`world.build`
makes one bundle for both styles); the script (`world_chart.js`) draws every position where the paper
puts it, a track as straight segments between its own fixes, an asset at its last fix, and a day mark
at a recorded fix or a journey's own end, dated by the record's days, which this module writes into the
page (`days`) so a browser that does not know the record's zone still writes the record's dates.

The page fetches nothing: the image is in the page as base64 in a data block and the script makes a
picture of it with `createImageBitmap`, so the policy stays `default-src 'none'`, the one script allowed
by its hash. The paper is paper: dark mode leaves it light. The scrubber is the globe's, line for line
(`tests/test_world_chart.py` holds the script to it)."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from html import escape
from importlib import resources
from pathlib import Path
from typing import Any

from . import chart_fit, chart_image

MODERN, CHART = "modern", "chart"
STYLES = (MODERN, CHART)
FORMAT = "world-chart/1"  # the shape of the page's chart block
DRAWN, IMAGE = "drawn", "image"
DRAWN_CREDIT = "drawn from Natural Earth's 1:110m land, public domain"
NO_LAND = (
    '{"scale":100,"polygons":[]}'  # the owner's chart is the paper: the globe's coasts are not drawn on it
)
PAGE_BYTES = 7 * 1024 * 1024  # a chart page, whole: the record's JSON, the land table, the image, the rest
CREDIT_CHARS = 300
DOT = " \u00b7 "

SCRIPT = (resources.files("logbook") / "contrib" / "world_chart.js").read_text(encoding="utf-8")
SCRIPT_HASH = "sha256-" + base64.b64encode(hashlib.sha256(SCRIPT.encode("utf-8")).digest()).decode()
POLICY = (  # the chart page's own Content-Security-Policy: the one script by its hash, nothing fetched
    f"default-src 'none'; script-src '{SCRIPT_HASH}'; style-src 'unsafe-inline'; base-uri 'none';"
    " form-action 'none'"
)


class ChartError(ValueError):
    """A chart the export refuses: its image, its control points, its fit or its credit."""


@dataclass(frozen=True)
class Paper:
    """What the record is drawn on: the drawn chart (no image), or the owner's image, its fit and its
    credit."""

    image: chart_image.Image | None = None
    fit: chart_fit.Fit | None = None
    credit: str = DRAWN_CREDIT

    @property
    def kind(self) -> str:
        return DRAWN if self.image is None else IMAGE


def paper(chart: Path | None = None, points: Path | None = None, credit: str | None = None) -> Paper:
    """The paper `--chart`, `--control-points` and `--chart-credit` ask for: none of them, the drawn
    chart; all three, the owner's image fitted to its points. `ChartError` for one without the others,
    an image or points the export refuses, or a fit it refuses."""
    if chart is None:
        if points is not None or credit is not None:
            given = "--control-points" if points is not None else "--chart-credit"
            raise ChartError(f"{given} goes with --chart FILE, the owner's chart image")
        return Paper()
    if points is None:
        raise ChartError("--chart needs --control-points FILE: three or more pixels tied to positions")
    words = " ".join((credit or "").split())
    if not words:
        raise ChartError(
            '--chart needs --chart-credit "…": the chart\'s source, in your words, for the legend (nothing is'
            " read from the file)"
        )
    if len(words) > CREDIT_CHARS:
        raise ChartError(f"--chart-credit is {len(words)} characters; at most {CREDIT_CHARS}")
    try:
        image = chart_image.read(chart)
        found = chart_fit.fit(chart_fit.read_points(points), image.width, image.height)
    except (chart_image.ChartImageError, chart_fit.ChartFitError) as e:
        raise ChartError(str(e)) from e
    return Paper(image, found, words)


def chart_json(paper: Paper, first_day: str, marks: Mapping[str, Any], years: bool) -> str:
    """The page's chart block: the paper, its credit, the window's first day, the dates the chart
    writes (`marks`, as `world._Builder.day_marks` counts them from the record's instants: days from
    the first), and for the owner's chart its fit and its image's size."""
    block: dict[str, Any] = {
        "format": FORMAT,
        "paper": paper.kind,
        "credit": paper.credit,
        "days": {"first": first_day, "years": years},
        "marks": dict(marks),
    }
    if paper.image is not None and paper.fit is not None:
        width, height = paper.image.embedded_size
        block["fit"] = paper.fit.to_json()
        block["image"] = {
            "type": paper.image.mime,
            "width": width,
            "height": height,
            "factor": paper.image.factor,
        }
    text = json.dumps(block, ensure_ascii=False, separators=(",", ":"))
    return text.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


def image_text(paper: Paper) -> str | None:
    """The image as the page's data block holds it: base64, on one line."""
    return None if paper.image is None else base64.b64encode(paper.image.data).decode("ascii")


def legend(paper: Paper) -> str:
    """The legend: what each mark on the chart is, and the chart's source in the owner's words."""
    keys = (
        ("stay", "a stay, pricked; a night's written with its day"),
        ("journey", "a journey; a bar and its day at a recorded position"),
        ("track", "an asset's track, fix to fix; its name at its last fix"),
        ("place", "a named place"),
    )
    items = "".join(
        f'<li><span class="key {k}" aria-hidden="true"></span>{escape(text)}</li>' for k, text in keys
    )
    return (  # closed, it is one line, and covers as little of the record as it can; the credit always shows
        '<details id="legend"><summary>'
        f"the chart: {escape(paper.credit)}{DOT}nothing here is fetched{DOT}legend</summary>"
        f"<ul>{items}</ul></details>\n"
    )


def residuals(paper: Paper, beyond: int = 0) -> str:
    """The fit in a corner: its kind, each control point's residual, the limit it was held to, and how
    many of the page's positions lie beyond the points' spread, where the residuals vouch for nothing."""
    found = paper.fit
    if found is None:
        return ""
    n = len(found.points)
    if found.checked:
        how = (
            f"{found.kind}, {n} points; a residual is how far the other points put a point;"
            f" refused over {chart_fit.RESIDUAL_LIMIT:.0%} of the diagonal ({found.limit_px:,.1f} px)"
        )
    else:
        how = "affine through 3 points, which it fits exactly: unchecked; a fourth point would check them"
    spread = (
        f"<p>{beyond:,} {'position lies' if beyond == 1 else 'positions lie'} beyond the control points'"
        " spread, placed by extrapolation</p>"
        if beyond
        else ""
    )
    rows = "".join(
        f"<tr><td>{escape(r['name'])}</td><td>{escape(r['px'])}</td><td>{escape(r['share'])}</td></tr>"
        for r in chart_fit.residual_rows(found)
    )
    return (  # open, and folded with a click when it covers the record
        '<details id="residuals" open><summary>the fit of the chart</summary><p>'
        f"{escape(how)}</p><table><tr><th>point</th><th>residual</th><th>of the diagonal</th></tr>"
        f"{rows}</table>{spread}</details>\n"
    )


def outside(paper: Paper, bundle: Mapping[str, Any]) -> tuple[int, int]:
    """How many of the page's positions the owner's chart does not hold — off the image, or beyond the
    fit's horizon: drawn where the fit puts them, on no paper, or not at all — and how many it holds
    beyond the control points' spread (their hull), placed by extrapolation the residuals do not check."""
    if paper.fit is None:
        return 0, 0
    found = paper.fit
    positions: list[tuple[float, float]] = [(p["lat"], p["lon"]) for p in bundle["places"]]
    positions += [(s["lat"], s["lon"]) for s in bundle["stays"]]
    for a in bundle["assets"]:
        track = a["track"]
        positions += list(zip(track[1::3], track[2::3], strict=True))
    for j in bundle["journeys"]:
        path = j["path"]
        positions += list(zip(path[0::2], path[1::2], strict=True))
    off = beyond = 0
    for lat, lon in positions:
        at = found.to_pixel(lat, lon)
        if at is None or not (0 <= at[0] <= found.width and 0 <= at[1] <= found.height):
            off += 1
        elif not found.spans(at):
            beyond += 1
    return off, beyond


STYLE = """
:root{color-scheme:light;--fg:#2b1d10;--bg:#f1e4c4;--mute:#6a5640;--line:#c9b07c;--accent:#7a2a1c;
--panel:#f8efd8;--ink:#2e2012;--journey:#9a2c1d;--place:#1f3a56}
html,body{height:100%}
body{margin:0;font:15px/1.4 'Iowan Old Style','Palatino Linotype',Palatino,'Book Antiqua',Georgia,serif;
color:var(--fg);background:var(--bg);display:flex;flex-direction:column}
header{padding:.4rem 1rem;border-bottom:1px solid var(--line);display:flex;flex-wrap:wrap;gap:.2rem 1rem;
align-items:baseline}
header nav a{margin-right:.8rem;color:var(--accent);text-decoration:none}
h1{font-size:1.15rem;margin:0;font-style:italic;font-weight:400}
h1 small{color:var(--mute);font-size:.8em}
#readout{margin:0;color:var(--mute);flex:1 1 20rem;font-style:italic}
main{flex:1;position:relative;min-height:18rem;overflow:hidden}
#globe{position:absolute;inset:0;width:100%;height:100%;touch-action:none;cursor:grab}
#globe:active{cursor:grabbing}
#tools{position:absolute;top:2.6rem;right:2.6rem;display:flex;gap:.3rem}
#list{position:absolute;top:2.6rem;left:2.6rem;max-height:calc(100% - 12rem);overflow:auto;list-style:none;
margin:0;padding:0;display:flex;flex-direction:column;gap:.2rem;align-items:flex-start}
#panel{position:absolute;top:4.6rem;right:2.6rem;width:17rem;max-height:calc(100% - 7rem);overflow:auto;
background:var(--panel);border:1px solid var(--line);border-radius:2px;padding:.5rem .7rem}
#panel h2{font-size:1rem;margin:0 0 .4rem;font-style:italic;font-weight:400}
#panel dl{display:grid;grid-template-columns:max-content 1fr;gap:.15rem .7rem;margin:0}
#panel dt{color:var(--mute)}
#panel dd{margin:0;font-variant-numeric:tabular-nums}
#panel .close{float:right}
#legend{position:absolute;bottom:.35rem;left:2.6rem;max-width:min(30rem,calc(100% - 5.2rem));
background:var(--panel);border:1px solid var(--line);border-radius:2px;padding:.1rem .5rem;font-size:.78rem}
#legend summary{cursor:pointer;color:var(--mute);font-style:italic}
#legend ul{list-style:none;margin:.25rem 0;padding:0}
#legend li{display:flex;align-items:center;gap:.5rem}
.key{display:inline-block;flex:none;width:1.6rem;height:.7rem;position:relative}
.key.stay{width:.6rem;height:.6rem;margin:0 .5rem;border:1px solid var(--ink);border-radius:50%}
.key.journey{border-top:2px dashed var(--journey);height:0}
.key.track{border-top:1.5px solid var(--ink);height:0}
.key.place{width:.6rem;height:.6rem;margin:0 .5rem;border:1.5px solid var(--place);border-radius:50%}
#residuals{position:absolute;bottom:.6rem;right:.6rem;max-width:22rem;background:var(--panel);
border:1px solid var(--line);border-radius:2px;padding:.35rem .6rem;font-size:.78rem}
#residuals summary{cursor:pointer;font-style:italic}
#residuals p{margin:.25rem 0;color:var(--mute)}
#residuals table{border-collapse:collapse;font-variant-numeric:tabular-nums}
#residuals th,#residuals td{text-align:left;padding:.05rem .5rem .05rem 0}
footer{border-top:1px solid var(--line);padding:.4rem 1rem;display:flex;gap:.7rem;align-items:center}
.scrub{flex:1;min-width:0}
#bands{display:block;width:100%;height:34px;cursor:pointer}
#time{display:block;width:100%;margin:0;accent-color:var(--accent)}
#clock{font-variant-numeric:tabular-nums;white-space:nowrap;color:var(--mute);min-width:11rem;text-align:right}
button{font:inherit;padding:.1rem .55rem;background:var(--panel);color:var(--fg);border:1px solid var(--line);
border-radius:2px;cursor:pointer}
noscript table{border-collapse:collapse;margin:1rem}
noscript th,noscript td{text-align:left;padding:.2rem .6rem;border-bottom:1px solid var(--line)}
@media (max-width:40rem){#list{display:none}#clock{min-width:0}}
"""
