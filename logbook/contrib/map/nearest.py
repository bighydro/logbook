"""The named thing the map holds nearest a point: for an unnamed stay's centroid, the restaurant, the pier or
the marina within `RADIUS_M` of it, as a **proposal** for places review and the timeline (RFC 0043 §11:
*the map file's nearest named thing, proposed in grey*). Nothing is written: no place, no line, no
note. Places review and the timeline read it and the owner confirms, or not.

Read from the file's last zoom, where every point of interest is: the tile holding the point and, when
the radius reaches past its edge, its neighbours. Counted are the named features of the layers a stay
can be at (`LAYERS`: points of interest, land use such as a pier or a park, named buildings), never a
road, a town's point or a stretch of water. The distance is to the feature itself: to a point, to the
nearest piece of a line, and nought inside a polygon. Metres from tile units at the point's latitude
(Web Mercator is conformal, so a few tens of metres are measured true)."""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from pathlib import Path

from . import mvt
from .pmtiles import PMTiles
from .svg import MAX_LAT, world

RADIUS_M = 50.0
LAYERS = ("pois", "landuse", "buildings")  # in this order when two are as near
EARTH_M = 40_075_016.686  # the equator in metres, as Web Mercator measures it


@dataclass(frozen=True)
class Proposal:
    """The named thing nearest the point: its name and kind as the map has them, the layer it is in,
    how far it is in metres, and its point nearest the one asked about."""

    name: str
    kind: str
    layer: str
    distance_m: float
    lat: float
    lon: float


def nearest_named(path: Path, lat: float, lon: float, radius_m: float = RADIUS_M) -> Proposal | None:
    """The named feature nearest (`lat`, `lon`) within `radius_m`, from the map file at `path`; None when
    nothing named is that near, or the point is outside the file. For many stays, one `Namer`."""
    with Namer(path) as namer:
        return namer.nearest(lat, lon, radius_m)


class Namer:
    """One map file open for many questions (places review over every unnamed stay): the archive's
    directories and the tiles already decoded are kept. Close it, or use it in a `with`."""

    def __init__(self, path: Path) -> None:
        self.archive = PMTiles(path)
        self._tiles: dict[tuple[int, int], list[mvt.Layer]] = {}

    def __enter__(self) -> Namer:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.archive.close()

    def _layers(self, z: int, tx: int, ty: int) -> list[mvt.Layer]:
        if (tx, ty) not in self._tiles:
            if len(self._tiles) >= 64:
                self._tiles.clear()
            data = self.archive.tile(z, tx, ty)
            self._tiles[(tx, ty)] = [] if data is None else mvt.decode(data, LAYERS)
        return self._tiles[(tx, ty)]

    def nearest(self, lat: float, lon: float, radius_m: float = RADIUS_M) -> Proposal | None:
        """As `nearest_named`, from the open file."""
        if not (math.isfinite(lat) and math.isfinite(lon)) or abs(lat) > MAX_LAT or abs(lon) > 180:
            return None
        z = self.archive.header.max_zoom
        n = 1 << z
        wx, wy = world(lon, lat)
        units_per_m = n / (EARTH_M * math.cos(math.radians(lat)))  # tiles per metre, here
        reach = radius_m * units_per_m
        best: tuple[float, int, Proposal] | None = None
        xs = range(max(0, int((wx * n) - reach)), min(n - 1, int(wx * n + reach)) + 1)
        ys = range(max(0, int((wy * n) - reach)), min(n - 1, int(wy * n + reach)) + 1)
        for tx in xs:
            for ty in ys:
                for layer in self._layers(z, tx, ty):
                    rank = LAYERS.index(layer.name)
                    e = layer.extent
                    here = ((wx * n - tx) * e, (wy * n - ty) * e)
                    for feature in layer.features:
                        name = feature.properties.get("name")
                        if not isinstance(name, str) or not name.strip():
                            continue
                        found = _distance(here, feature)
                        if found is None:
                            continue
                        d_units, (px, py) = found
                        metres = d_units / e / units_per_m
                        if metres > radius_m or (best is not None and (metres, rank) >= best[:2]):
                            continue
                        plon, plat = _lonlat((tx + px / e) / n, (ty + py / e) / n)
                        kind = feature.properties.get("kind") or feature.properties.get("pmap:kind")
                        best = (
                            metres,
                            rank,
                            Proposal(
                                " ".join(name.split()),
                                kind if isinstance(kind, str) else "",
                                layer.name,
                                round(metres, 1),
                                round(plat, 7),
                                round(plon, 7),
                            ),
                        )
        return best[2] if best else None


def _lonlat(x: float, y: float) -> tuple[float, float]:
    return x * 360.0 - 180.0, math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y))))


Point = tuple[float, float]


def _distance(here: Point, feature: mvt.Feature) -> tuple[float, Point] | None:
    """(how far, in tile units, the feature's point nearest `here`); None for a feature with no geometry."""
    parts = [[(float(x), float(y)) for x, y in part] for part in feature.geometry if part]
    if not parts:
        return None
    if feature.type == mvt.POLYGON and _inside(here, parts):
        return 0.0, here
    best: tuple[float, Point] | None = None
    for part in parts:
        if feature.type == mvt.POINT or len(part) == 1:
            segments = [(p, p) for p in part]
        else:
            segments = list(itertools.pairwise(part))
            if feature.type == mvt.POLYGON:
                segments.append((part[-1], part[0]))
        for a, b in segments:
            d, at = _to_segment(here, a, b)
            if best is None or d < best[0]:
                best = (d, at)
    return best


def _to_segment(p: Point, a: Point, b: Point) -> tuple[float, Point]:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
    at = (a[0] + t * dx, a[1] + t * dy)
    return math.hypot(p[0] - at[0], p[1] - at[1]), at


def _inside(p: Point, rings: list[list[Point]]) -> bool:
    """Even-odd over every ring: inside an exterior and outside its holes."""
    x, y = p
    inside = False
    for ring in rings:
        for (ax, ay), (bx, by) in zip(ring, ring[1:] + ring[:1], strict=True):
            if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
                inside = not inside
    return inside
