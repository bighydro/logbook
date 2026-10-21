"""The map drawn: a bounding box and a width in pixels made into one inline `<svg>` from the map file, with
nothing fetched and no script. The Day page (RFC 0043 slice A) and the timeline (§11) call `render`;
`logbook lab map render` draws one to a file for checking by eye.

**Zoom and tiles.** The box's width in Web Mercator against the width asked gives the scale, and the
display zoom `log2(scale / 256)`; the tiles read are those of the whole zoom below it (a tile drawn
256 to 512 pixels wide), within the file's zooms: past its last zoom, its last is drawn larger. At most
`MAX_TILES` tiles of those within the file's bounds: a box that needs more is read a zoom further out,
and one that needs more at the file's first zoom is refused in one sentence, never drawn cut short.

**Drawing.** Each feature is projected (Web Mercator, in pixels of the output), clipped to its own tile
and to the map (so the buffers adjacent tiles share never draw twice), simplified to the output's pixel
(Douglas-Peucker, `TOLERANCE` px) and rounded to a tenth of a pixel. All the features of one style are
one `<path>`, filled with the nonzero rule (a hole winds the other way, so it stays a hole, and two
tiles' pieces of one lake overlap without a seam). In order: land under all, land use and parks, water,
piers, buildings when the display zoom is `BUILDINGS_FROM` or closer, roads by class (the widest last),
place labels (the most important first, one dropped when it would cover another, a pin or the
attribution), then on top the day's track and its numbered stops, and the attribution on every map.

**Styles** are CSS custom properties with their fallbacks in the `<style>` the map carries, light and
dark (`prefers-color-scheme`), so the map stands alone as a file and a page that sets `--map-water`
and the rest draws it in its own colours. Text is the system's sans-serif.

**Size.** A map is held under `BUDGET` bytes (300 KB): when the full drawing is larger, the buildings
go, then the paths and the minor roads with land use, each with a coarser tolerance, until it fits, and
last the bare map (land, names, the track); the track, the pins and the attribution are never dropped.
What a hostile file can cost is bounded too: past `MAX_VERTICES` points the classes go before anything
is simplified, and past `DP_WORK` Douglas-Peucker hands over to a one-pass corridor (`Work`).

**The track** is the Day page's (`_track_svg` in `logbook/contrib/serve.py`): the timeline's stays and
stops with a position, numbered in order, one pin for one place however often it was visited (stops
nearer than a pin's radius on the map one pin, as the Day page merges its dots by the pixel), and a
straight move between two of them, dashed across a flight, a gap or a stay with no position."""

from __future__ import annotations

import html
import itertools
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...core import stays
from ...core.day import FLIGHT, GAP
from . import MapError, mvt
from .pmtiles import PMTiles

BUDGET = 300_000  # bytes of SVG a map stays under
MIN_WIDTH, MAX_WIDTH, MAX_HEIGHT = 100, 4000, 4000
MAX_TILES = 36
TILE_PX = 256
MAX_LAT = 85.0511  # Web Mercator's edge
TOLERANCE = 0.5  # px: how far a simplified line may stray from the drawn one
BUILDINGS_FROM = 14.5  # display zoom
CHAR_EM = 0.6  # a label's width per character, in ems: an over-estimate for a system sans-serif
MAX_LABELS = 24
PIN_R = 9.0
ATTRIBUTION = "© OpenStreetMap contributors"
ATTRIBUTION_PX = 9.0
FONT = 'system-ui,-apple-system,"Segoe UI",Roboto,sans-serif'

Point = tuple[float, float]
Ring = list[Point]

# how the layers of Protomaps' basemap (v3 and v4) are drawn: the style class of a feature by its kind
PARKS = frozenset(
    {
        "park", "garden", "nature_reserve", "national_park", "protected_area", "playground", "golf_course",
        "forest", "wood", "grass", "grassland", "meadow", "scrub", "recreation_ground", "village_green",
        "cemetery", "allotments", "dog_park", "pitch",
    }
)  # fmt: skip
ROADS = {
    "highway": "road-highway",
    "major_road": "road-major",
    "medium_road": "road-medium",
    "minor_road": "road-minor",
    "other": "road-minor",
    "path": "road-path",
    "rail": "rail",
}
ROAD_WIDTH = {  # px at display zoom 15
    "road-path": 1.0,
    "road-minor": 1.8,
    "road-medium": 2.4,
    "road-major": 3.0,
    "road-highway": 4.0,
    "rail": 1.0,
    "waterway": 1.2,
}
# drawn in this order, the later on top; a level of detail (`LEVELS`) leaves some out
ORDER = (
    "landuse", "park", "water", "waterway", "pier", "building",
    "rail", "road-path", "road-minor", "road-medium", "road-major", "road-highway",
)  # fmt: skip
DRAWN = frozenset({"water", "landuse", "landcover", "natural", "roads", "transit", "places"})  # and buildings
FILLED = frozenset({"landuse", "park", "water", "pier", "building"})
PLACE_RANK = {"country": 0, "region": 1, "locality": 2, "macrohood": 3, "neighbourhood": 4}
PLACE_PX = {"country": 13.0, "region": 13.0, "locality": 12.0}


@dataclass(frozen=True)
class Level:
    """One level of detail: the classes left out and the simplification tolerance in pixels."""

    without: frozenset[str]
    tolerance: float


LEVELS = (
    Level(frozenset(), TOLERANCE),
    Level(frozenset({"building"}), 1.0),
    Level(frozenset({"building", "road-path", "road-minor", "landuse", "rail"}), 1.5),
    Level(
        frozenset({"building", "road-path", "road-minor", "road-medium", "landuse", "rail", "waterway"}), 2.5
    ),
)
BARE = len(LEVELS)  # the level past the last: land, names, the track and the attribution, nothing else
MAX_VERTICES = 150_000  # points drawn at most; past it the classes go in `DROPPED`'s order
DP_WORK = 3_000_000  # points Douglas-Peucker may look at for one map (`Work`)
DROPPED = (
    "building", "road-path", "road-minor", "landuse", "rail", "road-medium", "waterway",
    "park", "road-major", "road-highway", "pier", "water",
)  # fmt: skip

STYLE = (
    ".lbmap{display:block;max-width:100%;height:auto;overflow:hidden}"
    "{light}"
    "@media (prefers-color-scheme:dark){{dark}}"
    ".lbmap .waterway,.lbmap .road,.lbmap .rail,.lbmap .move"
    "{fill:none;stroke-linecap:round;stroke-linejoin:round}"
    ".lbmap .road-path{stroke-dasharray:2 2}.lbmap .rail{stroke-dasharray:3 3}"
    f".lbmap text{{font-family:{FONT}}}"
    ".lbmap .label{stroke-width:3px;paint-order:stroke;text-anchor:middle}"
    ".lbmap .move{stroke-width:2.5}.lbmap .gap{stroke-dasharray:5 4}"
    ".lbmap .track circle{stroke-width:1.5}"
    ".lbmap .pin{font-size:10px;font-weight:600;text-anchor:middle;fill:#fff}"
    f".lbmap .attribution text{{font-size:{ATTRIBUTION_PX:g}px;text-anchor:end}}"
    ".lbmap .attribution rect{fill-opacity:.8}"
)
# (selector, property, custom property, light fallback, dark fallback)
COLOURS = (
    (".land", "fill", "--map-land", "#f2efe9", "#1e2023"),
    (".pier", "fill", "--map-land", "#f2efe9", "#1e2023"),
    (".landuse", "fill", "--map-landuse", "#e9e5dc", "#25272a"),
    (".park", "fill", "--map-park", "#d3e5c1", "#1f3326"),
    (".water", "fill", "--map-water", "#b3d1e3", "#17324a"),
    (".waterway", "stroke", "--map-water", "#b3d1e3", "#17324a"),
    (".building", "fill", "--map-building", "#dcd5ca", "#33363a"),
    (".road", "stroke", "--map-road", "#ffffff", "#45484d"),
    (".road-major,.lbmap .road-highway", "stroke", "--map-road-major", "#f3d39b", "#6b5a3a"),
    (".road-path", "stroke", "--map-path", "#a99c8a", "#6e6a63"),
    (".rail", "stroke", "--map-rail", "#9e9e9e", "#6e6e6e"),
    (".label", "fill", "--map-label", "#45413b", "#d8d4cc"),
    (".label", "stroke", "--map-halo", "#f2efe9", "#1e2023"),
    (".move", "stroke", "--map-track", "#c2410c", "#fb923c"),
    (".track circle", "fill", "--map-track", "#c2410c", "#fb923c"),
    (".track circle", "stroke", "--map-halo", "#f2efe9", "#1e2023"),
    (".attribution rect", "fill", "--map-halo", "#f2efe9", "#1e2023"),
    (".attribution text", "fill", "--map-label", "#45413b", "#d8d4cc"),
)


def _style() -> str:
    def rules(which: int) -> str:
        return "".join(
            f".lbmap {selector}{{{prop}:var({var},{colour[which]})}}"
            for selector, prop, var, *colour in COLOURS
        )

    return STYLE.replace("{light}", rules(0)).replace("{dark}", rules(1))


# -- the box and the track -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Stop:
    """One pin: the timeline's numbers of the stays at this place, in order, and where it is."""

    numbers: tuple[int, ...]
    lat: float
    lon: float


@dataclass(frozen=True)
class Track:
    """The pins, and the moves between them: (from, to, dashed), indexes into `stops`."""

    stops: tuple[Stop, ...] = ()
    links: tuple[tuple[int, int, bool], ...] = ()


def track_of(timeline: Iterable[Mapping[str, Any]]) -> Track:
    """The Day's track from its timeline (`logbook.core.day.read(...)["timeline"]`), by the rule the Day
    page draws it with (`_track_svg`): every stay, stop or `aboard` entry with a position is numbered in
    order; a flight, a gap or a stay with no position breaks the move after it into a dashed one; one
    pin for one position, carrying every number it was."""
    located: list[tuple[float, float]] = []
    links: list[tuple[int, int, bool]] = []
    broken = False
    for entry in timeline:
        if entry.get("kind") in (FLIGHT, GAP) or entry.get("gap"):
            broken = True
            continue
        if entry.get("kind") == stays.MOVE:
            continue
        if entry.get("lat") is None or entry.get("lon") is None:
            broken = True
            continue
        located.append((float(entry["lat"]), float(entry["lon"])))
        if len(located) > 1:
            links.append((len(located) - 2, len(located) - 1, broken))
        broken = False
    pins: dict[tuple[float, float], list[int]] = {}
    for n, at in enumerate(located, 1):
        pins.setdefault(at, []).append(n)
    index = {at: i for i, at in enumerate(pins)}
    return Track(
        tuple(Stop(tuple(numbers), lat, lon) for (lat, lon), numbers in pins.items()),
        tuple((index[located[a]], index[located[b]], gap) for a, b, gap in links),
    )


@dataclass(frozen=True)
class Box:
    """A bounding box in degrees: west, south, east, north."""

    west: float
    south: float
    east: float
    north: float

    def __post_init__(self) -> None:
        values = (self.west, self.south, self.east, self.north)
        if not all(math.isfinite(v) for v in values):
            raise MapError("a map's box is four numbers: minlon,minlat,maxlon,maxlat")
        if not (-180 <= self.west < self.east <= 180):
            raise MapError("a map's box runs west to east between -180 and 180: minlon,minlat,maxlon,maxlat")
        if not (-MAX_LAT <= self.south < self.north <= MAX_LAT):
            raise MapError(
                f"a map's box runs south to north between -{MAX_LAT} and {MAX_LAT}, Mercator's edge"
            )

    @classmethod
    def parse(cls, text: str) -> Box:
        """`minlon,minlat,maxlon,maxlat`, as `--bbox` takes it."""
        parts = [p.strip() for p in text.split(",")]
        try:
            values = [float(p) for p in parts]
        except ValueError:
            values = []
        if len(values) != 4:
            raise MapError(f"{text!r} is not a box: four numbers, minlon,minlat,maxlon,maxlat")
        return cls(*values)

    @classmethod
    def around(cls, track: Track, pad: float = 0.15, min_m: float = 400.0) -> Box:
        """The box round a track's pins, a margin of `pad` each side and `min_m` metres across at least."""
        if not track.stops:
            raise MapError("the track has no stay with a position to draw")
        lats = [s.lat for s in track.stops]
        lons = [s.lon for s in track.stops]
        mid = (min(lats) + max(lats)) / 2
        half_lat = max((max(lats) - min(lats)) * (0.5 + pad), min_m / 2 / 111_320)
        half_lon = max(
            (max(lons) - min(lons)) * (0.5 + pad),
            min_m / 2 / (111_320 * max(math.cos(math.radians(mid)), 0.01)),
        )
        clon = (min(lons) + max(lons)) / 2
        return cls(
            max(-180.0, clon - half_lon),
            max(-MAX_LAT, mid - half_lat),
            min(180.0, clon + half_lon),
            min(MAX_LAT, mid + half_lat),
        )


def world(lon: float, lat: float) -> Point:
    """Web Mercator, 0 to 1 both ways from the north-west corner."""
    lat = max(-MAX_LAT, min(MAX_LAT, lat))
    s = math.sin(math.radians(lat))
    return (lon + 180.0) / 360.0, 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)


# -- geometry ------------------------------------------------------------------------------------------------


Rect = tuple[float, float, float, float]  # x0, y0, x1, y1


def clip_ring(ring: Ring, rect: Rect) -> Ring:
    """Sutherland-Hodgman: the part of a ring inside `rect`, its winding kept."""
    x0, y0, x1, y1 = rect
    out = ring
    for axis, bound, keep_above in ((0, x0, True), (0, x1, False), (1, y0, True), (1, y1, False)):
        if not out:
            return []
        points, out = out, []

        def inside(p: Point) -> bool:
            return p[axis] >= bound if keep_above else p[axis] <= bound  # noqa: B023

        prev = points[-1]
        for cur in points:
            if inside(cur):
                if not inside(prev):
                    out.append(_cross(prev, cur, axis, bound))
                out.append(cur)
            elif inside(prev):
                out.append(_cross(prev, cur, axis, bound))
            prev = cur
    return out


def _cross(a: Point, b: Point, axis: int, bound: float) -> Point:
    t = (bound - a[axis]) / (b[axis] - a[axis])
    x, y = a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
    return (bound, y) if axis == 0 else (x, bound)


def clip_line(line: Ring, rect: Rect) -> list[Ring]:
    """The runs of a line inside `rect` (Liang-Barsky, segment by segment)."""
    x0, y0, x1, y1 = rect
    runs: list[Ring] = []
    current: Ring = []
    for (ax, ay), (bx, by) in itertools.pairwise(line):
        dx, dy = bx - ax, by - ay
        t0, t1 = 0.0, 1.0
        visible = True
        for p, q in ((-dx, ax - x0), (dx, x1 - ax), (-dy, ay - y0), (dy, y1 - ay)):
            if p == 0:
                if q < 0:
                    visible = False
                    break
                continue
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 > t1:
                visible = False
                break
        if not visible:
            if current:
                runs.append(current)
                current = []
            continue
        start = (ax + t0 * dx, ay + t0 * dy)
        end = (ax + t1 * dx, ay + t1 * dy)
        if not current:
            current = [start]
        current.append(end)
        if t1 < 1.0:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs


class Work:
    """What one map may spend on Douglas-Peucker (`DP_WORK` points looked at): an honest map spends a
    fraction of it; a hostile line, whose every point Douglas-Peucker would look at again and again, is
    simplified past it by the corridor (`corridor`), which looks at each point once."""

    def __init__(self, budget: int = 0) -> None:
        self.left = budget or DP_WORK


def simplify(points: Ring, tolerance: float, work: Work | None = None) -> Ring:
    """The points a line keeps when nothing it drops strays more than `tolerance` from it, the first and
    the last always: first the points within the tolerance of the last kept go (one pass), then
    Douglas-Peucker without recursion, or the corridor once `work` is spent."""
    if len(points) < 3:
        return list(points)
    near = [points[0]]
    t2 = tolerance * tolerance
    for p in points[1:-1]:
        if (p[0] - near[-1][0]) ** 2 + (p[1] - near[-1][1]) ** 2 > t2:
            near.append(p)
    near.append(points[-1])
    points = near
    if len(points) < 3:
        return points
    work = work or Work()
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        work.left -= last - first
        if work.left < 0:
            return corridor(points, tolerance)
        (ax, ay), (bx, by) = points[first], points[last]
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        worst, at = -1.0, -1
        for i in range(first + 1, last):
            px, py = points[i]
            if length2 == 0:
                d2 = (px - ax) ** 2 + (py - ay) ** 2
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
                d2 = (px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2
            if d2 > worst:
                worst, at = d2, i
        if worst > t2:
            keep[at] = True
            stack += [(first, at), (at, last)]
    return [p for p, k in zip(points, keep, strict=True) if k]


def corridor(points: Ring, tolerance: float) -> Ring:
    """Reumann-Witkam, in one pass: from the last point kept, along the line to the next, every point
    within `tolerance` of that line goes; the last one inside is kept and the next corridor starts there."""
    out = [points[0]]
    n = len(points)
    j = 1
    while j < n - 1:
        (ax, ay), (bx, by) = out[-1], points[j]
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        k = j + 1
        if length > 0:
            while (
                k < n - 1 and abs((points[k][0] - ax) * dy - (points[k][1] - ay) * dx) <= tolerance * length
            ):
                k += 1
        out.append(points[k - 1])
        j = k
    out.append(points[-1])
    return out


def _tenths(points: Ring) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for x, y in points:
        p = (round(x * 10), round(y * 10))
        if not out or p != out[-1]:
            out.append(p)
    return out


def _n(v: int) -> str:
    return str(v // 10) if v % 10 == 0 else f"{v / 10:.1f}"


def _path(points: list[tuple[int, int]], close: bool) -> str:
    (x, y), rest = points[0], points[1:]
    steps = []
    for px, py in rest:
        steps.append(f"{_n(px - x)} {_n(py - y)}")
        x, y = px, py
    return f"M{_n(points[0][0])} {_n(points[0][1])}l{' '.join(steps)}{'z' if close else ''}"


def _area(points: list[tuple[int, int]]) -> float:
    return (
        abs(
            sum(ax * by - bx * ay for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1], strict=True))
        )
        / 200
    )


# -- reading the tiles ---------------------------------------------------------------------------------------


@dataclass
class Label:
    name: str
    x: float
    y: float
    rank: tuple[int, float, float, str]
    size: float


@dataclass
class Drawing:
    """What the tiles hold, in output pixels, before simplification: per class its rings (filled) or
    lines (stroked), and the labels."""

    shapes: dict[str, list[Ring]]
    labels: list[Label]
    tiles: int  # how many of the tiles asked for the file holds


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _kind(properties: Mapping[str, Any]) -> str:
    return _text(properties.get("kind")) or _text(properties.get("pmap:kind"))


def _class_of(layer: str, feature: mvt.Feature) -> str | None:
    kind = _kind(feature.properties)
    if layer == "water":
        return (
            "waterway" if feature.type == mvt.LINESTRING else "water" if feature.type == mvt.POLYGON else None
        )
    if layer in ("landuse", "landcover", "natural") and feature.type == mvt.POLYGON:
        if kind == "pier":
            return "pier"
        if kind in PARKS:
            return "park"
        return "landuse" if layer == "landuse" else None
    if layer == "roads" and feature.type == mvt.LINESTRING:
        return ROADS.get(kind, "road-minor") if kind != "ferry" else None
    if layer == "transit" and feature.type == mvt.LINESTRING and kind == "rail":
        return "rail"
    if layer == "buildings" and feature.type == mvt.POLYGON:
        return "building"
    return None


def _read(
    archive: PMTiles,
    z: int,
    tiles: Sequence[tuple[int, int]],
    origin: Point,
    scale: float,
    size: tuple[int, int],
    dz: float,
) -> Drawing:
    width, height = size
    shapes: dict[str, list[Ring]] = {}
    labels: dict[tuple[str, int, int], Label] = {}
    found_tiles = 0
    n = 1 << z
    tile_px = scale / n
    view = (-2.0, -2.0, width + 2.0, height + 2.0)
    wanted = DRAWN | ({"buildings"} if dz >= BUILDINGS_FROM else set())
    for tx, ty in tiles:
        data = archive.tile(z, tx, ty)
        if data is None:
            continue
        found_tiles += 1
        left, top = (tx / n - origin[0]) * scale, (ty / n - origin[1]) * scale
        square = (
            max(view[0], left),
            max(view[1], top),
            min(view[2], left + tile_px),
            min(view[3], top + tile_px),
        )
        overlap = (square[0] - 0.5, square[1] - 0.5, square[2] + 0.5, square[3] + 0.5)
        for layer in mvt.decode(data, wanted):
            k = tile_px / layer.extent
            for feature in layer.features:
                parts = [[(left + gx * k, top + gy * k) for gx, gy in part] for part in feature.geometry]
                if layer.name == "places" and feature.type == mvt.POINT:
                    _place(labels, feature, parts, square, dz)
                    continue
                style = _class_of(layer.name, feature)
                if style is None or (style == "building" and dz < BUILDINGS_FROM):
                    continue
                found = shapes.setdefault(style, [])
                rect = overlap if style in FILLED else square
                for part in parts:
                    xs, ys = [p[0] for p in part], [p[1] for p in part]
                    if max(xs) < rect[0] or min(xs) > rect[2] or max(ys) < rect[1] or min(ys) > rect[3]:
                        continue  # wholly outside
                    within = (
                        min(xs) >= rect[0]
                        and max(xs) <= rect[2]
                        and min(ys) >= rect[1]
                        and max(ys) <= rect[3]
                    )
                    if style in FILLED:
                        ring = part if within else clip_ring(part, rect)
                        if len(ring) >= 3:
                            found.append(ring)
                    else:
                        found += [part] if within and len(part) > 1 else clip_line(part, rect)
    return Drawing(shapes, list(labels.values()), found_tiles)


def _place(
    labels: dict[tuple[str, int, int], Label],
    feature: mvt.Feature,
    parts: list[Ring],
    square: Rect,
    dz: float,
) -> None:
    name = _clean(_text(feature.properties.get("name")))
    if not name:
        return
    kind = _kind(feature.properties)
    min_zoom = feature.properties.get("min_zoom")
    min_zoom = (
        float(min_zoom) if isinstance(min_zoom, int | float) and not isinstance(min_zoom, bool) else 0.0
    )
    if min_zoom > dz + 1:
        return
    population = feature.properties.get("population_rank")
    population = float(population) if isinstance(population, int | float) else 0.0
    for x, y in (p for part in parts for p in part):
        if square[0] <= x < square[2] and square[1] <= y < square[3]:
            key = (name, round(x), round(y))
            labels[key] = Label(
                name, x, y, (PLACE_RANK.get(kind, 5), min_zoom, -population, name), PLACE_PX.get(kind, 11.0)
            )


INVALID_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def _clean(text: str) -> str:
    return " ".join(INVALID_XML.sub("", text).split())[:80]


def attribution(metadata: Mapping[str, Any]) -> str:
    """ "© OpenStreetMap contributors", and what the file's own `attribution` adds to it (Protomaps'
    builds name themselves there), its links dropped and its OpenStreetMap notice not said twice."""
    found = metadata.get("attribution")
    extra = html.unescape(re.sub(r"<[^>]*>", "", found)) if isinstance(found, str) else ""
    extra = re.sub(r"(©|\(c\))?\s*OpenStreetMap( contributors)?", "", extra, flags=re.IGNORECASE)
    extra = _clean(extra).strip(" ·,;|-©")[:60]
    return f"{ATTRIBUTION} · {extra}" if extra else ATTRIBUTION


# -- the map -------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Drawn:
    """One map: the SVG, its size in pixels, the zoom of its tiles, how many it read and the level of
    detail it was drawn at (0 is everything)."""

    svg: str
    width: int
    height: int
    zoom: int
    tiles: int
    level: int


def render(path: Path, box: Box, width: int, track: Track | None = None) -> Drawn:
    """The map of `box`, `width` pixels wide and as tall as Mercator makes it, from the PMTiles file at
    `path`, with `track` on top; `MapError` for a file it cannot read or a size it will not draw."""
    if not MIN_WIDTH <= width <= MAX_WIDTH:
        raise MapError(f"a map's width is {MIN_WIDTH} to {MAX_WIDTH} pixels, not {width}")
    (x0, y0), (x1, y1) = world(box.west, box.north), world(box.east, box.south)
    if x1 - x0 < 1e-12 or y1 - y0 < 1e-12:
        raise MapError("the box is too small to draw: its sides are less than a millimetre apart")
    scale = width / (x1 - x0)
    height = max(1, round((y1 - y0) * scale))
    if height > MAX_HEIGHT:
        raise MapError(f"the box would draw {height} pixels tall at {width} wide; {MAX_HEIGHT} at most")
    dz = math.log2(scale / TILE_PX)
    with PMTiles(path) as archive:
        h = archive.header
        z = max(h.min_zoom, min(h.max_zoom, math.floor(dz)))
        # the tiles of the box that lie within the file's bounds: outside them it holds none
        (bx0, by0), (bx1, by1) = world(h.min_lon, h.max_lat), world(h.max_lon, h.min_lat)
        if bx1 <= bx0 or by1 <= by0:  # a file that states no bounds
            bx0, by0, bx1, by1 = 0.0, 0.0, 1.0, 1.0
        wx0, wy0, wx1, wy1 = max(x0, bx0), max(y0, by0), min(x1, bx1), min(y1, by1)
        while True:
            n = 1 << z
            xs = range(max(0, int(wx0 * n)), min(n - 1, int(wx1 * n * (1 - 1e-12))) + 1)
            ys = range(max(0, int(wy0 * n)), min(n - 1, int(wy1 * n * (1 - 1e-12))) + 1)
            if len(xs) * len(ys) <= MAX_TILES:
                break
            if z <= h.min_zoom:
                raise MapError(
                    f"the box needs {len(xs) * len(ys):,} tiles at zoom {z}, the file's widest; a map reads"
                    f" {MAX_TILES} at most: draw a smaller box, or cut the file from zoom 0"
                )
            z -= 1
        drawing = _read(archive, z, [(x, y) for x in xs for y in ys], (x0, y0), scale, (width, height), dz)
        credit = attribution(archive.metadata)
    project = _projector((x0, y0), scale)
    shapes = _capped(drawing.shapes)
    work = Work()
    for level, detail in enumerate((*LEVELS, Level(frozenset(ORDER), 0.0))):
        shapes = {
            style: [_simplified(ring, style in FILLED, detail.tolerance, work) for ring in rings]
            for style, rings in shapes.items()
            if style not in detail.without
        }
        text = _svg(shapes, drawing.labels, detail, dz, (width, height), track or Track(), project, credit)
        if len(text.encode("utf-8")) <= BUDGET or level == BARE:
            return Drawn(text, width, height, z, drawing.tiles, level)
    raise AssertionError("unreachable")


def _capped(shapes: dict[str, list[Ring]]) -> dict[str, list[Ring]]:
    """`shapes` with whole classes left out, the finest first, until `MAX_VERTICES` points are left:
    what keeps a hostile tile from taking minutes, and an honest one is never near."""
    count = {style: sum(len(r) for r in rings) for style, rings in shapes.items()}
    total = sum(count.values())
    kept = dict(shapes)
    for style in DROPPED:
        if total <= MAX_VERTICES:
            break
        total -= count.get(style, 0)
        kept.pop(style, None)
    return kept


def _simplified(ring: Ring, filled: bool, tolerance: float, work: Work) -> Ring:
    """A ring simplified as a closed line (its first point kept as its last, then dropped) or a line."""
    if tolerance <= 0:
        return ring
    if not filled:
        return simplify(ring, tolerance, work)
    found = simplify([*ring, ring[0]], tolerance, work)
    return found[:-1] if len(found) > 1 and found[-1] == found[0] else found


def _projector(origin: Point, scale: float) -> Any:
    def project(lat: float, lon: float) -> Point:
        x, y = world(lon, lat)
        return (x - origin[0]) * scale, (y - origin[1]) * scale

    return project


def _svg(
    shapes: Mapping[str, list[Ring]],
    labels: list[Label],
    detail: Level,
    dz: float,
    size: tuple[int, int],
    track: Track,
    project: Any,
    credit: str,
) -> str:
    width, height = size
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" class="lbmap" viewBox="0 0 {width} {height}"'
        f' width="{width}" height="{height}" role="img" aria-label="map">',
        f"<style>{_style()}</style>",
        f'<rect class="land" width="{width}" height="{height}"/>',
    ]
    factor = max(0.35, min(2.0, 2 ** ((dz - 15) * 0.6)))
    for style in ORDER:
        if style in detail.without or (style == "building" and dz < BUILDINGS_FROM):
            continue
        filled = style in FILLED
        pieces = []
        for ring in shapes.get(style, []):
            points = _tenths(ring)
            if filled:
                if points and points[-1] == points[0]:
                    points = points[:-1]
                if len(points) < 3 or _area(points) < detail.tolerance:
                    continue
            elif len(points) < 2:
                continue
            pieces.append(_path(points, filled))
        if not pieces:
            continue
        css = style if filled or style in ("waterway", "rail") else f"road {style}"
        stroke = "" if filled else f' stroke-width="{ROAD_WIDTH[style] * factor:.1f}"'
        out.append(f'<path class="{css}"{stroke} d="{"".join(pieces)}"/>')
    pins, links = _pins(track, project)
    radii = [max(PIN_R, 3.2 * len(label) + 2) for _, label in pins]
    credit_w = len(credit) * ATTRIBUTION_PX * 0.55 + 8
    if credit_w > width - 4:
        credit, credit_w = ATTRIBUTION, len(ATTRIBUTION) * ATTRIBUTION_PX * 0.55 + 8
    credit_h = ATTRIBUTION_PX + 5
    taken = [(width - credit_w, height - credit_h, float(width), float(height))]
    taken += [
        (x - r - 1, y - r - 1, x + r + 1, y + r + 1) for ((x, y), _), r in zip(pins, radii, strict=True)
    ]
    out.append(_labels(labels, taken, width, height))
    out.append('<g class="track">')
    view = (0.0, 0.0, float(width), float(height))
    for a, b, gap in links:
        if a == b:
            continue
        for run in clip_line([pins[a][0], pins[b][0]], view):  # a stop outside the box: the move to its edge
            points = _tenths(run)
            if len(points) > 1:
                out.append(f'<path class="move{" gap" if gap else ""}" d="{_path(points, False)}"/>')
    for ((x, y), label), r in zip(pins, radii, strict=True):
        if not (0 <= x <= width and 0 <= y <= height):
            continue
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:g}"/>')
        out.append(f'<text class="pin" x="{x:.1f}" y="{y + 3.5:.1f}">{label}</text>')
    out.append("</g>")
    out.append(
        f'<g class="attribution"><rect x="{width - credit_w:.1f}" y="{height - credit_h:.1f}"'
        f' width="{credit_w:.1f}" height="{credit_h:.1f}"/><text x="{width - 4}" y="{height - 4}">'
        f"{html.escape(credit)}</text></g>"
    )
    out.append("</svg>\n")
    return "".join(out)


def _pins(track: Track, project: Any) -> tuple[list[tuple[Point, str]], list[tuple[int, int, bool]]]:
    """The pins in pixels with their numbers, the stops nearer than a pin's radius one pin (as the Day
    page merges its dots by the pixel), and the moves between them by pin."""
    at: list[Point] = []
    numbers: list[list[int]] = []
    pin_of: list[int] = []
    for stop in track.stops:
        x, y = project(stop.lat, stop.lon)
        near = next((i for i, (px, py) in enumerate(at) if (px - x) ** 2 + (py - y) ** 2 < PIN_R**2), None)
        if near is None:
            at.append((x, y))
            numbers.append([])
            near = len(at) - 1
        numbers[near] += stop.numbers
        pin_of.append(near)
    pins = [(p, ", ".join(str(n) for n in sorted(ns))) for p, ns in zip(at, numbers, strict=True)]
    return pins, [(pin_of[a], pin_of[b], gap) for a, b, gap in track.links]


def _labels(labels: list[Label], taken: list[Rect], width: int, height: int) -> str:
    """The place names, the most important first, each where it does not cover one already placed,
    a pin or the attribution, nor leave the map."""
    placed: list[str] = []
    for label in sorted(labels, key=lambda lb: lb.rank):
        if len(placed) >= MAX_LABELS:
            break
        w = len(label.name) * label.size * CHAR_EM
        box = (
            label.x - w / 2 - 2,
            label.y - label.size - 2,
            label.x + w / 2 + 2,
            label.y + label.size * 0.3 + 2,
        )
        if box[0] < 0 or box[1] < 0 or box[2] > width or box[3] > height:
            continue
        if any(box[0] < t[2] and t[0] < box[2] and box[1] < t[3] and t[1] < box[3] for t in taken):
            continue
        taken.append(box)
        placed.append(
            f'<text class="label" x="{label.x:.1f}" y="{label.y:.1f}" font-size="{label.size:g}">'
            f"{html.escape(label.name)}</text>"
        )
    return f'<g class="labels">{"".join(placed)}</g>' if placed else ""
