"""One Mapbox Vector Tile (`vector_tile.proto` v2), decoded by hand from the protobuf wire format: no
protobuf library, no generated code. A tile is a list of layers; a layer has a name, an extent (4096 in
Protomaps' builds), its features and the keys and values their tags point into; a feature has an id, a
type (point, line, polygon), its properties and its geometry.

The wire format, as much as a tile uses: each field a varint key, `number << 3 | wire type`, then a
varint (type 0), eight bytes (1), a varint length and that many bytes (2) or four bytes (5). A packed
repeated field is one length-delimited run of varints. A field this reader does not know is skipped by
its wire type; a group (3, 4) or any other type is damage.

Geometry is a run of command integers: `id & 7` the command (1 MoveTo, 2 LineTo, 7 ClosePath),
`>> 3` how many times; MoveTo and LineTo take that many pairs of zigzag-encoded deltas from the cursor.
Decoded, a feature's geometry is a list of parts in tile coordinates (x right, y down): for points one
part holding every point; for a line one part per line; for a polygon one part per ring, not closed by
repeating its first point (exterior rings wind clockwise on screen, holes the other way; a renderer that
fills with the nonzero rule needs nothing more).

Every count is held to the bytes behind it, every index to the table it indexes: a damaged or hostile
tile is one `MapError`, never a hang."""

from __future__ import annotations

import struct
from collections.abc import Collection
from dataclasses import dataclass, field

from . import MapError

UNKNOWN, POINT, LINESTRING, POLYGON = 0, 1, 2, 3
MOVE_TO, LINE_TO, CLOSE_PATH = 1, 2, 7
DEFAULT_EXTENT = 4096
Value = str | int | float | bool
Point = tuple[int, int]


@dataclass(frozen=True)
class Feature:
    id: int | None
    type: int
    properties: dict[str, Value]
    geometry: list[list[Point]]


@dataclass(frozen=True)
class Layer:
    name: str
    extent: int
    version: int
    features: list[Feature] = field(default_factory=list)


def _damaged(what: str) -> MapError:
    return MapError(f"a tile of the map file is damaged: {what}")


def _varint(data: bytes, at: int, end: int) -> tuple[int, int]:
    value = shift = 0
    for i in range(10):
        if at + i >= end:
            raise _damaged("a number runs past its field")
        byte = data[at + i]
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, at + i + 1
        shift += 7
    raise _damaged("a number longer than ten bytes")


def _fields(data: bytes, start: int = 0, end: int | None = None) -> list[tuple[int, int, int | bytes]]:
    """(field number, wire type, the value: an int, or the bytes of a length-delimited or fixed field) of
    every field in `data[start:end]`."""
    end = len(data) if end is None else end
    out: list[tuple[int, int, int | bytes]] = []
    at = start
    while at < end:
        key, at = _varint(data, at, end)
        number, wire = key >> 3, key & 7
        value: int | bytes
        if wire == 0:
            value, at = _varint(data, at, end)
        elif wire == 2:
            length, at = _varint(data, at, end)
            if length > end - at:
                raise _damaged("a field longer than what holds it")
            value, at = data[at : at + length], at + length
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4
            if size > end - at:
                raise _damaged("a fixed-width number cut short")
            value, at = data[at : at + size], at + size
        else:
            raise _damaged(f"wire type {wire}, which no vector tile has")
        out.append((number, wire, value))
    return out


def _packed(data: bytes) -> list[int]:
    """A packed run of varints, in one pass over its bytes (a tile's geometry is most of its bytes)."""
    out: list[int] = []
    value = shift = 0
    for byte in data:
        value |= (byte & 0x7F) << shift
        if byte & 0x80:
            shift += 7
            if shift >= 70:
                raise _damaged("a number longer than ten bytes")
        else:
            out.append(value)
            value = shift = 0
    if shift:
        raise _damaged("a number runs past its field")
    return out


def _signed(value: int) -> int:
    return value - (1 << 64) if value >= 1 << 63 else value


def _zigzag(value: int) -> int:
    return (value >> 1) ^ -(value & 1)


def _value(data: bytes) -> Value:
    """One `Value` message: the last of its fields that is a value (a well-formed one has one)."""
    found: Value | None = None
    for number, wire, raw in _fields(data):
        if number == 1 and wire == 2 and isinstance(raw, bytes):
            found = raw.decode("utf-8", "replace")
        elif number == 2 and wire == 5 and isinstance(raw, bytes):
            found = struct.unpack("<f", raw)[0]
        elif number == 3 and wire == 1 and isinstance(raw, bytes):
            found = struct.unpack("<d", raw)[0]
        elif number == 4 and wire == 0 and isinstance(raw, int):
            found = _signed(raw)
        elif number == 5 and wire == 0 and isinstance(raw, int):
            found = raw
        elif number == 6 and wire == 0 and isinstance(raw, int):
            found = _zigzag(raw)
        elif number == 7 and wire == 0 and isinstance(raw, int):
            found = bool(raw)
    if found is None:
        raise _damaged("a value of no type")
    return found


def geometry(commands: list[int], kind: int) -> list[list[Point]]:
    """The parts of one feature's geometry from its command integers (module docstring)."""
    parts: list[list[Point]] = []
    x = y = 0
    i = 0
    while i < len(commands):
        command, count = commands[i] & 7, commands[i] >> 3
        i += 1
        if command == CLOSE_PATH:
            if not parts:
                raise _damaged("a ClosePath before any MoveTo")
            continue
        if command not in (MOVE_TO, LINE_TO):
            raise _damaged(f"geometry command {command}, which the format has not")
        if count == 0 or 2 * count > len(commands) - i:
            raise _damaged("a geometry command with fewer numbers than it counts")
        if command == LINE_TO and not parts:
            raise _damaged("a LineTo before any MoveTo")
        for _ in range(count):
            x += _zigzag(commands[i])
            y += _zigzag(commands[i + 1])
            i += 2
            if command == MOVE_TO and (kind != POINT or not parts):
                parts.append([(x, y)])
            else:
                parts[-1].append((x, y))
    return parts


def _feature(data: bytes, keys: list[str], values: list[Value]) -> Feature:
    fid: int | None = None
    kind = UNKNOWN
    tags: list[int] = []
    commands: list[int] = []
    for number, wire, raw in _fields(data):
        if number == 1 and wire == 0 and isinstance(raw, int):
            fid = raw
        elif number == 2 and wire == 2 and isinstance(raw, bytes):
            tags += _packed(raw)
        elif number == 3 and wire == 0 and isinstance(raw, int):
            kind = raw
        elif number == 4 and wire == 2 and isinstance(raw, bytes):
            commands += _packed(raw)
    if len(tags) % 2:
        raise _damaged("a feature's tags are not in pairs")
    properties: dict[str, Value] = {}
    for k, v in zip(tags[::2], tags[1::2], strict=True):
        if k >= len(keys) or v >= len(values):
            raise _damaged("a tag names a key or a value the layer has not")
        properties[keys[k]] = values[v]
    return Feature(fid, kind, properties, geometry(commands, kind))


def _layer(data: bytes, only: Collection[str] | None = None) -> Layer | None:
    name = ""
    extent, version = DEFAULT_EXTENT, 1
    keys: list[str] = []
    raw_values: list[bytes] = []
    features: list[bytes] = []
    for number, wire, raw in _fields(data):
        if number == 1 and wire == 2 and isinstance(raw, bytes):
            name = raw.decode("utf-8", "replace")
        elif number == 2 and wire == 2 and isinstance(raw, bytes):
            features.append(raw)  # read once the keys and values are known: they may come after
        elif number == 3 and wire == 2 and isinstance(raw, bytes):
            keys.append(raw.decode("utf-8", "replace"))
        elif number == 4 and wire == 2 and isinstance(raw, bytes):
            raw_values.append(raw)  # read once the layer is known to be wanted
        elif number == 5 and wire == 0 and isinstance(raw, int):
            extent = raw
        elif number == 15 and wire == 0 and isinstance(raw, int):
            version = raw
    if only is not None and name not in only:
        return None
    if extent <= 0:
        raise _damaged(f"layer {name!r} has an extent of {extent}")
    values = [_value(raw) for raw in raw_values]
    return Layer(name, extent, version, [_feature(f, keys, values) for f in features])


def decode(data: bytes, only: Collection[str] | None = None) -> list[Layer]:
    """The layers of one tile, decompressed (`PMTiles.tile` inflates it), in the tile's order; with
    `only`, the layers of those names and no other is decoded past its name."""
    found = (
        _layer(raw, only)
        for number, wire, raw in _fields(data)
        if number == 3 and wire == 2 and isinstance(raw, bytes)
    )
    return [layer for layer in found if layer is not None]
