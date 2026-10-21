"""A PMTiles v3 archive, read: the 127-byte header, the root directory, the leaf directories under it and
one tile by z/x/y, decompressed with zlib when the archive says gzip. The layout is the one
github.com/protomaps/PMTiles `spec/v3/spec.md` states:

    header (127 bytes, little-endian) | root directory | metadata (JSON) | leaf directories | tile data

A **tile id** numbers every tile of every zoom along a Hilbert curve: the tiles of the zooms above z
first, `(4**z - 1) // 3` of them, then the tile's place on the curve of its own zoom. A **directory** is
a varint count of entries, then four columns of varints: the tile ids as deltas, the run lengths, the
lengths and the offsets (an offset of 0 after the first entry is the previous entry's end; any other is
the offset plus one). An entry whose run length is 0 points at a leaf directory, in the leaf section;
any other covers `run_length` consecutive tile ids that share the bytes at `offset` in the tile data.

Everything read is checked against the file before it is trusted: an offset or a length past the end, a
varint longer than ten bytes, a count the bytes cannot hold, a directory or a tile that inflates past
`MAX_INFLATED`, leaves deeper than `MAX_DEPTH` are each one `MapError` naming the file. Nothing loops on
a count the file gives without the bytes to back it."""

from __future__ import annotations

import bisect
import json
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from . import MapError

MAGIC = b"PMTiles"
VERSION = 3
HEADER_SIZE = 127
HEADER = struct.Struct("<7sB11Q6B4iB2i")  # magic, version, 8 offsets and lengths, 3 counts, 6 bytes, …
# compressions (header bytes 97 and 98) and tile types (byte 99), as the spec numbers them
UNKNOWN, NONE, GZIP, BROTLI, ZSTD = 0, 1, 2, 3, 4
COMPRESSIONS = {UNKNOWN: "unknown", NONE: "none", GZIP: "gzip", BROTLI: "brotli", ZSTD: "zstd"}
MVT = 1
TILE_TYPES = {0: "unknown", 1: "vector tiles (MVT)", 2: "PNG", 3: "JPEG", 4: "WebP", 5: "AVIF"}
MAX_ZOOM = 31  # a tile id is a 64-bit number; z 31 is the deepest whose ids fit
MAX_DEPTH = 4  # root, then at most three levels of leaves (the spec's writers use one or two)
MAX_INFLATED = 64 << 20  # bytes one directory, the metadata or one tile may inflate to
MAX_READ = 64 << 20  # bytes one directory, the metadata or one tile may take in the file
MAX_ENTRIES = 1 << 20  # entries in one directory: Protomaps' builds hold thousands


@dataclass(frozen=True)
class Header:
    """The header's fields, as the spec names them; bounds and centre in degrees."""

    root_offset: int
    root_length: int
    metadata_offset: int
    metadata_length: int
    leaf_offset: int
    leaf_length: int
    data_offset: int
    data_length: int
    addressed_tiles: int
    tile_entries: int
    tile_contents: int
    clustered: bool
    internal_compression: int
    tile_compression: int
    tile_type: int
    min_zoom: int
    max_zoom: int
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float
    center_zoom: int
    center_lon: float
    center_lat: float

    def describe(self) -> str:
        """One line for the owner: what the file holds."""
        return (
            f"PMTiles v{VERSION}, {TILE_TYPES.get(self.tile_type, 'unknown')},"
            f" zoom {self.min_zoom} to {self.max_zoom},"
            f" bounds {self.min_lon:.4f},{self.min_lat:.4f},{self.max_lon:.4f},{self.max_lat:.4f},"
            f" {self.addressed_tiles:,} tiles"
        )


@dataclass(frozen=True)
class Entry:
    tile_id: int
    offset: int
    length: int
    run_length: int


def parse_header(data: bytes, name: str = "the map file") -> Header:
    """The header from the file's first 127 bytes; `MapError` for anything else, in one sentence."""
    if len(data) < HEADER_SIZE:
        raise MapError(f"{name} is not a PMTiles file: {len(data)} bytes, shorter than the header")
    fields = HEADER.unpack_from(data)
    if fields[0] != MAGIC:
        raise MapError(f"{name} is not a PMTiles file: it does not begin with {MAGIC.decode()}")
    if fields[1] != VERSION:
        raise MapError(f"{name} is PMTiles version {fields[1]}; this reader reads version {VERSION}")
    (ro, rl, mo, ml, lo, ll, do, dl, addressed, entries, contents) = fields[2:13]
    clustered, internal, tile_comp, tile_type, min_z, max_z = fields[13:19]
    min_lon, min_lat, max_lon, max_lat, center_z, center_lon, center_lat = fields[19:26]
    return Header(
        ro, rl, mo, ml, lo, ll, do, dl, addressed, entries, contents,
        bool(clustered), internal, tile_comp, tile_type, min_z, max_z,
        min_lon / 1e7, min_lat / 1e7, max_lon / 1e7, max_lat / 1e7,
        center_z, center_lon / 1e7, center_lat / 1e7,
    )  # fmt: skip


def check_header(header: Header, size: int, name: str = "the map file") -> None:
    """What the renderer needs of a file, before it is named or read: vector tiles, a compression zlib
    reads, zooms in order and every section inside the file's `size` bytes."""
    if header.tile_type != MVT:
        kind = TILE_TYPES.get(header.tile_type, f"type {header.tile_type}")
        raise MapError(
            f"{name} holds {kind}, not vector tiles: the map draws an OpenStreetMap vector extract"
        )
    for which, value in (("directories", header.internal_compression), ("tiles", header.tile_compression)):
        if value not in (UNKNOWN, NONE, GZIP):
            raise MapError(
                f"{name}'s {which} are compressed with {COMPRESSIONS.get(value, f'method {value}')},"
                " which this reader does not read; Protomaps' builds are gzip"
            )
    if not header.min_zoom <= header.max_zoom <= MAX_ZOOM:
        raise MapError(f"{name}'s zooms run {header.min_zoom} to {header.max_zoom}, which no archive holds")
    for which, offset, length in (
        ("root directory", header.root_offset, header.root_length),
        ("metadata", header.metadata_offset, header.metadata_length),
        ("leaf directories", header.leaf_offset, header.leaf_length),
        ("tile data", header.data_offset, header.data_length),
    ):
        if offset + length > size:
            raise MapError(f"{name} is cut short: its {which} runs past the end of the file")
    if header.root_length == 0:
        raise MapError(f"{name} has no root directory")


def tile_id(z: int, x: int, y: int) -> int:
    """The tile id of z/x/y (the spec's `ZxyToTileId`): the tiles of every zoom above, then the place of
    (x, y) on the Hilbert curve of zoom z."""
    if not 0 <= z <= MAX_ZOOM:
        raise ValueError(f"zoom {z} is outside 0 to {MAX_ZOOM}")
    n = 1 << z
    if not (0 <= x < n and 0 <= y < n):
        raise ValueError(f"tile {z}/{x}/{y} is outside zoom {z}")
    d = 0
    s = n >> 1
    while s:
        rx = 1 if x & s else 0
        ry = 1 if y & s else 0
        d += s * s * ((3 * rx) ^ ry)
        if ry == 0:
            if rx == 1:
                x, y = n - 1 - x, n - 1 - y
            x, y = y, x
        s >>= 1
    return ((1 << (2 * z)) - 1) // 3 + d


def read_varint(data: bytes, at: int, name: str = "the map file") -> tuple[int, int]:
    """(the unsigned varint at `at`, the position after it); ten bytes at most."""
    value = shift = 0
    for i in range(10):
        if at + i >= len(data):
            raise MapError(f"{name} is damaged: a number runs past the end of its section")
        byte = data[at + i]
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, at + i + 1
        shift += 7
    raise MapError(f"{name} is damaged: a number longer than ten bytes")


def parse_directory(data: bytes, name: str = "the map file") -> list[Entry]:
    """The entries of one directory, decompressed; in tile id order, as the spec requires."""
    count, at = read_varint(data, 0, name)
    if 4 * count > len(data) or count > MAX_ENTRIES:  # each entry takes four varints of a byte at least
        raise MapError(f"{name} is damaged: a directory counts {count:,} entries in {len(data):,} bytes")
    ids: list[int] = []
    last = 0
    for _ in range(count):
        delta, at = read_varint(data, at, name)
        last += delta
        ids.append(last)
    runs: list[int] = []
    lengths: list[int] = []
    offsets: list[int] = []
    for column in (runs, lengths):
        for _ in range(count):
            value, at = read_varint(data, at, name)
            column.append(value)
    for i in range(count):
        value, at = read_varint(data, at, name)
        if value == 0 and i > 0:
            offsets.append(offsets[i - 1] + lengths[i - 1])
        elif value == 0:
            raise MapError(f"{name} is damaged: a directory's first offset is missing")
        else:
            offsets.append(value - 1)
    return [Entry(ids[i], offsets[i], lengths[i], runs[i]) for i in range(count)]


def inflate(data: bytes, compression: int, name: str = "the map file") -> bytes:
    """`data` as stored, decompressed: gzip by zlib, bounded by `MAX_INFLATED`."""
    if compression in (NONE, UNKNOWN) and not data.startswith(b"\x1f\x8b"):
        return data
    if compression not in (NONE, UNKNOWN, GZIP):
        raise MapError(f"{name} uses {COMPRESSIONS.get(compression, f'compression {compression}')}, not gzip")
    try:
        inflater = zlib.decompressobj(wbits=31)  # gzip only
        out = inflater.decompress(data, MAX_INFLATED)
    except zlib.error as e:
        raise MapError(f"{name} is damaged: a section does not inflate ({e})") from None
    if inflater.unconsumed_tail:
        raise MapError(f"{name} holds a section that inflates past {MAX_INFLATED >> 20} MB")
    if not inflater.eof:
        raise MapError(f"{name} is damaged: a compressed section is cut short")
    return out


class PMTiles:
    """One archive, open for reading: `tile(z, x, y)` the tile's bytes decompressed, or None when the
    archive holds no such tile; `metadata` the JSON object it carries. Directories read are kept, so
    many tiles of one map cost one read of each leaf. Close it, or use it in a `with`."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.name = str(self.path)
        try:
            self._file: BinaryIO = self.path.open("rb")
        except OSError as e:
            raise MapError(f"the map file {self.name} cannot be opened: {e.strerror or e}") from None
        try:
            self.size = self.path.stat().st_size
            self.header = parse_header(self._read(0, HEADER_SIZE), self.name)
            check_header(self.header, self.size, self.name)
            self._leaves: dict[tuple[int, int], tuple[list[int], list[Entry]]] = {}
            self.root = self._directory(self.header.root_offset, self.header.root_length)
            self._root_ids = [e.tile_id for e in self.root]
            self._metadata: dict[str, Any] | None = None
        except BaseException:
            self._file.close()
            raise

    def __enter__(self) -> PMTiles:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._file.close()

    def _read(self, offset: int, length: int) -> bytes:
        if length > MAX_READ:
            raise MapError(f"{self.name} asks for a section of {length:,} bytes, more than this reader reads")
        if offset < 0 or offset + length > getattr(self, "size", offset + length):
            raise MapError(f"{self.name} is damaged: a section runs past the end of the file")
        self._file.seek(offset)
        data = self._file.read(length)
        if len(data) != length:
            raise MapError(f"{self.name} is cut short: a section runs past the end of the file")
        return data

    def _directory(self, offset: int, length: int) -> list[Entry]:
        raw = self._read(offset, length)
        return parse_directory(inflate(raw, self.header.internal_compression, self.name), self.name)

    @property
    def metadata(self) -> dict[str, Any]:
        """The archive's JSON metadata (`vector_layers`, `attribution`, …); {} when it carries none or
        none that reads as an object."""
        if self._metadata is None:
            h = self.header
            found: Any = {}
            if h.metadata_length:
                raw = inflate(
                    self._read(h.metadata_offset, h.metadata_length), h.internal_compression, self.name
                )
                try:
                    found = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, ValueError, RecursionError):
                    found = {}
            self._metadata = found if isinstance(found, dict) else {}
        return self._metadata

    def entry(self, tid: int) -> Entry | None:
        """The entry that holds tile id `tid`, through the leaves; None when no entry does."""
        ids, entries = self._root_ids, self.root
        for _ in range(MAX_DEPTH):
            i = bisect.bisect_right(ids, tid) - 1
            if i < 0:
                return None
            found = entries[i]
            if found.run_length > 0:
                return found if tid < found.tile_id + found.run_length else None
            key = (found.offset, found.length)
            if key not in self._leaves:
                if found.offset + found.length > self.header.leaf_length:
                    raise MapError(f"{self.name} is damaged: a leaf directory lies outside the leaf section")
                leaf = self._directory(self.header.leaf_offset + found.offset, found.length)
                self._leaves[key] = ([e.tile_id for e in leaf], leaf)
            ids, entries = self._leaves[key]
        raise MapError(f"{self.name} is damaged: its leaf directories nest deeper than {MAX_DEPTH}")

    def tile(self, z: int, x: int, y: int) -> bytes | None:
        """The tile z/x/y decompressed; None when the archive holds none there (outside the extract)."""
        if not 0 <= z <= MAX_ZOOM or not (0 <= x < 1 << z and 0 <= y < 1 << z):
            return None
        found = self.entry(tile_id(z, x, y))
        if found is None or found.length == 0:
            return None
        if found.offset + found.length > self.header.data_length:
            raise MapError(f"{self.name} is damaged: a tile lies outside the tile data")
        raw = self._read(self.header.data_offset + found.offset, found.length)
        return inflate(raw, self.header.tile_compression, self.name)


def read_header(path: Path) -> Header:
    """The header of the file at `path`, checked as `check_header` checks it: what `setup map` reads
    before it names a file."""
    try:
        with Path(path).open("rb") as f:
            data = f.read(HEADER_SIZE)
        size = Path(path).stat().st_size
    except OSError as e:
        raise MapError(f"{path} cannot be read: {e.strerror or e}") from None
    header = parse_header(data, str(path))
    check_header(header, size, str(path))
    return header
