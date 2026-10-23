"""A tiny synthetic map for the tests of `logbook.contrib.map`: a Mapbox Vector Tile encoder and a PMTiles v3
writer of our own, and the coast they draw — an invented fjord shore south-west of Oslo, with invented
names, at zooms 10 to 14. Nothing here is a real extract or a real place: the shore is a few straight
lines, the names belong to the Oslo persona (who does not exist) and the bay, the marina and the café
are made up. The writer follows github.com/protomaps/PMTiles `spec/v3/spec.md`; the encoder
`vector_tile.proto` v2. Layers and `kind` values follow Protomaps' basemap schema, as the renderer reads."""

from __future__ import annotations

import gzip
import math
import struct
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from logbook.contrib.map import pmtiles

EXTENT = 4096
BUFFER = 256  # tile units a feature may reach past the tile's edge, as real tiles carry

LonLat = tuple[float, float]
Value = str | int | float | bool

# -- the protobuf wire format, written -----------------------------------------------------------------------


def varint(n: int) -> bytes:
    out = bytearray()
    n &= (1 << 64) - 1
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def zigzag(n: int) -> int:
    return (n << 1) ^ (n >> 63)


def key(number: int, wire: int) -> bytes:
    return varint((number << 3) | wire)


def f_varint(number: int, value: int) -> bytes:
    return key(number, 0) + varint(value)


def f_bytes(number: int, value: bytes) -> bytes:
    return key(number, 2) + varint(len(value)) + value


def f_packed(number: int, values: Iterable[int]) -> bytes:
    return f_bytes(number, b"".join(varint(v) for v in values))


def value_message(value: Value) -> bytes:
    if isinstance(value, bool):
        return f_varint(7, int(value))
    if isinstance(value, str):
        return f_bytes(1, value.encode("utf-8"))
    if isinstance(value, int):
        return f_varint(5, value) if value >= 0 else f_varint(6, zigzag(value))
    return key(3, 1) + struct.pack("<d", value)


POINT, LINESTRING, POLYGON = 1, 2, 3


def geometry(kind: int, parts: Sequence[Sequence[tuple[int, int]]]) -> list[int]:
    """The command integers of one geometry: a point's parts are one MoveTo of every point; a line's,
    MoveTo then LineTo; a polygon's rings, MoveTo, LineTo, ClosePath (the ring not closed by repeating)."""
    out: list[int] = []
    cx = cy = 0

    def deltas(points: Sequence[tuple[int, int]]) -> list[int]:
        nonlocal cx, cy
        found = []
        for x, y in points:
            found += [zigzag(x - cx), zigzag(y - cy)]
            cx, cy = x, y
        return found

    if kind == POINT:
        points = [p for part in parts for p in part]
        return [(len(points) << 3) | 1, *deltas(points)]
    for part in parts:
        out += [(1 << 3) | 1, *deltas(part[:1])]
        out += [((len(part) - 1) << 3) | 2, *deltas(part[1:])]
        if kind == POLYGON:
            out.append((1 << 3) | 7)
    return out


@dataclass
class Feature:
    kind: int
    parts: list[list[tuple[int, int]]]
    properties: dict[str, Value] = field(default_factory=dict)
    id: int | None = None


def layer_message(name: str, features: Sequence[Feature], extent: int = EXTENT) -> bytes:
    keys: list[str] = []
    values: list[Value] = []
    body = f_varint(15, 2) + f_bytes(1, name.encode("utf-8"))
    for feature in features:
        tags: list[int] = []
        for k, v in feature.properties.items():
            if k not in keys:
                keys.append(k)
            if (type(v), v) not in [(type(w), w) for w in values]:
                values.append(v)
            tags += [keys.index(k), [(type(w), w) for w in values].index((type(v), v))]
        msg = b""
        if feature.id is not None:
            msg += f_varint(1, feature.id)
        msg += (
            f_packed(2, tags) + f_varint(3, feature.kind) + f_packed(4, geometry(feature.kind, feature.parts))
        )
        body += f_bytes(2, msg)
    body += b"".join(f_bytes(3, k.encode("utf-8")) for k in keys)
    body += b"".join(f_bytes(4, value_message(v)) for v in values)
    return body + f_varint(5, extent)


def tile_message(layers: Mapping[str, Sequence[Feature]]) -> bytes:
    return b"".join(
        f_bytes(3, layer_message(name, features)) for name, features in layers.items() if features
    )


# -- the archive, written ------------------------------------------------------------------------------------


def directory(entries: Sequence[pmtiles.Entry]) -> bytes:
    out = varint(len(entries))
    last = 0
    for e in entries:
        out += varint(e.tile_id - last)
        last = e.tile_id
    out += b"".join(varint(e.run_length) for e in entries)
    out += b"".join(varint(e.length) for e in entries)
    for i, e in enumerate(entries):
        contiguous = i > 0 and e.offset == entries[i - 1].offset + entries[i - 1].length
        out += varint(0 if contiguous else e.offset + 1)
    return out


def gz(data: bytes) -> bytes:
    return gzip.compress(data, mtime=0)


def write_pmtiles(
    path: Path,
    tiles: Mapping[tuple[int, int, int], bytes],
    metadata: Mapping[str, Any] | None = None,
    *,
    leaf_size: int | None = None,
    compress: bool = True,
    tile_type: int = pmtiles.MVT,
    bounds: tuple[float, float, float, float] = (-180.0, -85.0, 180.0, 85.0),
) -> Path:
    """A PMTiles v3 file of `tiles` ({(z, x, y): the tile's bytes}): consecutive tile ids with the same
    bytes one entry with a run length; with `leaf_size`, the entries in leaf directories of that many
    under a root that points at them; gzip throughout unless `compress` is False."""
    pack = gz if compress else bytes
    ordered = sorted((pmtiles.tile_id(*zxy), data) for zxy, data in tiles.items())
    entries: list[pmtiles.Entry] = []
    blob = bytearray()
    for tid, data in ordered:
        stored = pack(data)
        last = entries[-1] if entries else None
        if last and last.tile_id + last.run_length == tid and bytes(blob[last.offset :]) == stored:
            entries[-1] = pmtiles.Entry(last.tile_id, last.offset, last.length, last.run_length + 1)
            continue
        entries.append(pmtiles.Entry(tid, len(blob), len(stored), 1))
        blob += stored
    leaves = b""
    if leaf_size and len(entries) > leaf_size:
        root_entries = []
        for i in range(0, len(entries), leaf_size):
            chunk = pack(directory(entries[i : i + leaf_size]))
            root_entries.append(pmtiles.Entry(entries[i].tile_id, len(leaves), len(chunk), 0))
            leaves += chunk
        root = pack(directory(root_entries))
    else:
        root = pack(directory(entries))
    meta = pack(json_bytes(metadata or {}))
    zooms = [z for z, _, _ in tiles] or [0]
    compression = pmtiles.GZIP if compress else pmtiles.NONE
    root_at = pmtiles.HEADER_SIZE
    meta_at = root_at + len(root)
    leaf_at = meta_at + len(meta)
    data_at = leaf_at + len(leaves)
    header = pmtiles.HEADER.pack(
        pmtiles.MAGIC, pmtiles.VERSION,
        root_at, len(root), meta_at, len(meta), leaf_at, len(leaves), data_at, len(blob),
        len(tiles), len(entries), len({d for _, d in ordered}),
        0, compression, compression, tile_type, min(zooms), max(zooms),
        *(round(v * 1e7) for v in bounds), min(zooms),
        round((bounds[0] + bounds[2]) / 2 * 1e7), round((bounds[1] + bounds[3]) / 2 * 1e7),
    )  # fmt: skip
    path.write_bytes(header + root + meta + leaves + bytes(blob))
    return path


def json_bytes(data: Mapping[str, Any]) -> bytes:
    import json

    return json.dumps(data, sort_keys=True).encode("utf-8")


# -- the coast -----------------------------------------------------------------------------------------------

#: the area the tiles cover: a few kilometres of an invented shore south-west of Oslo
WEST, SOUTH, EAST, NORTH = 10.66, 59.88, 10.77, 59.935
MIN_ZOOM, MAX_ZOOM = 10, 14
ATTRIBUTION = '<a href="https://example.org/basemaps">Example basemap</a> © <a href="https://example.org/osm">OpenStreetMap</a>'

#: the café, the marina and the pier the nearest-feature tests look for, and the stays beside them
CAFE = (10.7100, 59.9060)
MARINA = (10.7350, 59.9010)
PIER = [(10.7230, 59.9016), (10.7232, 59.9032), (10.7262, 59.9032), (10.7260, 59.9016)]  # out from the shore


@dataclass(frozen=True)
class Shape:
    layer: str
    kind: int
    parts: list[list[LonLat]]
    properties: dict[str, Value]
    min_zoom: int = MIN_ZOOM


def _square(lon: float, lat: float, half: float) -> list[LonLat]:
    k = math.cos(math.radians(lat))
    return [
        (lon - half / k, lat - half),
        (lon - half / k, lat + half),
        (lon + half / k, lat + half),
        (lon + half / k, lat - half),
    ]


def shapes() -> list[Shape]:
    """The coast: the fjord south of a shore of five bends with an island in it (a ring with a hole),
    a park, a residential area, the pier, roads of four classes, a few buildings close in, three places
    and four points of interest, one unnamed."""
    shore = [(10.60, 59.915), (10.68, 59.912), (10.71, 59.905), (10.74, 59.900), (10.80, 59.895)]
    fjord = [(10.60, 59.80), *shore, (10.80, 59.80)]
    island = [
        (10.695, 59.893),
        (10.705, 59.893),
        (10.705, 59.897),
        (10.695, 59.897),
    ]  # wound the other way: a hole
    out = [
        Shape("water", POLYGON, [fjord[::-1], island[::-1]], {"kind": "ocean", "name": "Solvindfjorden"}),
        Shape(
            "water", LINESTRING, [[(10.745, 59.935), (10.742, 59.915), (10.738, 59.901)]], {"kind": "stream"}
        ),
        Shape(
            "landuse", POLYGON, [_square(10.722, 59.916, 0.003)[::-1]], {"kind": "park", "name": "Kariparken"}
        ),
        Shape("landuse", POLYGON, [_square(10.695, 59.922, 0.004)[::-1]], {"kind": "residential"}),
        Shape("landuse", POLYGON, [PIER[::-1]], {"kind": "pier", "name": "Hansenbrygga"}),
        Shape(
            "roads",
            LINESTRING,
            [[(10.60, 59.928), (10.80, 59.926)]],
            {"kind": "highway", "kind_detail": "motorway"},
        ),
        Shape(
            "roads",
            LINESTRING,
            [[(10.66, 59.918), (10.77, 59.910)]],
            {"kind": "major_road", "name": "Fjordveien"},
        ),
        Shape("roads", LINESTRING, [[(10.715, 59.904), (10.715, 59.926)]], {"kind": "minor_road"}),
        Shape("roads", LINESTRING, [[(10.73, 59.902), (10.732, 59.912)]], {"kind": "path"}),
        Shape(
            "places",
            POINT,
            [[(10.7200, 59.9140)]],
            {"kind": "locality", "name": "Solvindbukta", "min_zoom": 10},
        ),
        Shape(
            "places",
            POINT,
            [[(10.6900, 59.9200)]],
            {"kind": "neighbourhood", "name": "Hansenbyen", "min_zoom": 12},
        ),
        Shape(
            "places",
            POINT,
            [[(10.7480, 59.9110)]],
            {"kind": "neighbourhood", "name": "Nordmannsvik", "min_zoom": 12},
        ),
        Shape("pois", POINT, [[CAFE]], {"kind": "restaurant", "name": "Kafé Kari"}, 14),
        Shape("pois", POINT, [[MARINA]], {"kind": "marina", "name": "Solvind marina"}, 13),
        Shape("pois", POINT, [[(10.7400, 59.9200)]], {"kind": "bench"}, 14),  # unnamed: never a proposal
        Shape("pois", POINT, [[(10.7560, 59.9150)]], {"kind": "cafe", "name": "Per's kiosk"}, 14),
    ]
    for i in range(6):
        for j in range(4):
            lon, lat = 10.712 + i * 0.0012, 59.9075 + j * 0.0008
            out.append(
                Shape("buildings", POLYGON, [_square(lon, lat, 0.0002)[::-1]], {"kind": "building"}, 13)
            )
    return out


def world(lon: float, lat: float) -> tuple[float, float]:
    """Web Mercator, 0 to 1 both ways, y down."""
    s = math.sin(math.radians(lat))
    return (lon + 180.0) / 360.0, 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)


def tile_range(z: int) -> tuple[range, range]:
    n = 1 << z
    (x0, y0), (x1, y1) = world(WEST, NORTH), world(EAST, SOUTH)
    return range(int(x0 * n), int(x1 * n) + 1), range(int(y0 * n), int(y1 * n) + 1)


def encode_tile(z: int, x: int, y: int, found: Sequence[Shape]) -> bytes:
    n = 1 << z
    layers: dict[str, list[Feature]] = {}
    for shape in found:
        if z < shape.min_zoom:
            continue
        parts = []
        for part in shape.parts:
            points = []
            for lon, lat in part:
                wx, wy = world(lon, lat)
                points.append((round((wx * n - x) * EXTENT), round((wy * n - y) * EXTENT)))
            parts.append(points)
        xs = [p[0] for part in parts for p in part]
        ys = [p[1] for part in parts for p in part]
        if max(xs) < -BUFFER or min(xs) > EXTENT + BUFFER or max(ys) < -BUFFER or min(ys) > EXTENT + BUFFER:
            continue
        layers.setdefault(shape.layer, []).append(Feature(shape.kind, parts, dict(shape.properties)))
    return tile_message(layers)


def coast_tiles() -> dict[tuple[int, int, int], bytes]:
    found = shapes()
    tiles = {}
    for z in range(MIN_ZOOM, MAX_ZOOM + 1):
        xs, ys = tile_range(z)
        for x in xs:
            for y in ys:
                tiles[(z, x, y)] = encode_tile(z, x, y, found)
    return tiles


def write_coast(path: Path, *, leaf_size: int | None = 8) -> Path:
    """The coast as one PMTiles file at `path`, its directory in leaves of `leaf_size` entries."""
    return write_pmtiles(
        path,
        coast_tiles(),
        {"name": "the invented coast", "attribution": ATTRIBUTION, "vector_layers": []},
        leaf_size=leaf_size,
        bounds=(WEST, SOUTH, EAST, NORTH),
    )
