"""The map file's two readers (`logbook.contrib.map.pmtiles`, `.mvt`): the archive against the PMTiles v3
spec's header and directory layout, the tile decoder against tiles built by hand from the vector tile
spec's own examples, and both against files cut short, bit-flipped or made hostile, which end in one
`MapError` and never a hang or a traceback. The archives are written here by `tests/oslo_map.py`."""

from __future__ import annotations

import contextlib
import gzip
import struct
import zlib
from pathlib import Path

import oslo_map
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from logbook.contrib.map import MapError, mvt, pmtiles

# -- the tile id ---------------------------------------------------------------------------------------------


def test_tile_ids_follow_the_spec_s_hilbert_numbering() -> None:
    """The spec's own values: zoom 0 is 0, zoom 1 runs 1 to 4 along the curve, zoom 2 begins at 5, 3 at 21."""
    assert pmtiles.tile_id(0, 0, 0) == 0
    assert [pmtiles.tile_id(1, x, y) for x, y in ((0, 0), (0, 1), (1, 1), (1, 0))] == [1, 2, 3, 4]
    assert pmtiles.tile_id(2, 0, 0) == 5
    assert pmtiles.tile_id(3, 0, 0) == 21
    ids = {pmtiles.tile_id(3, x, y) for x in range(8) for y in range(8)}
    assert ids == set(range(21, 21 + 64))  # every tile of a zoom once, and nothing of another zoom
    assert pmtiles.tile_id(12, 3423, 1763) == 19078479  # the spec's own example
    with pytest.raises(ValueError):
        pmtiles.tile_id(1, 2, 0)


# -- the header and the directories --------------------------------------------------------------------------


def test_the_header_is_read_at_the_spec_s_offsets() -> None:
    """127 bytes, little-endian, every field where the spec puts it (written here byte by byte, not by
    the reader's own struct)."""
    raw = bytearray(127)
    raw[0:7] = b"PMTiles"
    raw[7] = 3
    for at, value in ((8, 127), (16, 25), (24, 152), (32, 40), (40, 192), (48, 0), (56, 192), (64, 999)):
        raw[at : at + 8] = value.to_bytes(8, "little")
    for at, value in ((72, 100), (80, 90), (88, 80)):
        raw[at : at + 8] = value.to_bytes(8, "little")
    raw[96:102] = bytes([1, 2, 2, 1, 0, 14])
    for at, value in ((102, 106_600_000), (106, 598_800_000), (110, 107_700_000), (114, 599_350_000)):
        raw[at : at + 4] = struct.pack("<i", value)
    raw[118] = 12
    raw[119:123] = struct.pack("<i", 107_150_000)
    raw[123:127] = struct.pack("<i", -1)
    h = pmtiles.parse_header(bytes(raw))
    assert (h.root_offset, h.root_length, h.metadata_offset, h.metadata_length) == (127, 25, 152, 40)
    assert (h.leaf_offset, h.leaf_length, h.data_offset, h.data_length) == (192, 0, 192, 999)
    assert (h.addressed_tiles, h.tile_entries, h.tile_contents) == (100, 90, 80)
    assert (h.clustered, h.internal_compression, h.tile_compression, h.tile_type) == (True, 2, 2, 1)
    assert (h.min_zoom, h.max_zoom, h.center_zoom) == (0, 14, 12)
    assert (h.min_lon, h.min_lat, h.max_lon, h.max_lat) == (10.66, 59.88, 10.77, 59.935)
    assert (h.center_lon, h.center_lat) == (10.715, -1e-7)


def test_a_directory_reads_its_four_columns_and_the_contiguous_offset() -> None:
    """Count, tile id deltas, run lengths, lengths, offsets (0 after the first: the previous one's end;
    else offset + 1), each a varint, as the spec lays them out."""
    raw = bytes([3, 5, 1, 300 & 0x7F | 0x80, 300 >> 7, 1, 4, 0, 10, 20, 7, 1, 0, 101])
    assert pmtiles.parse_directory(raw) == [
        pmtiles.Entry(5, 0, 10, 1),
        pmtiles.Entry(6, 10, 20, 4),
        pmtiles.Entry(306, 100, 7, 0),  # a leaf
    ]


def test_tiles_are_found_through_the_root_and_its_leaves(tmp_path: Path) -> None:
    """The written coast in leaves of eight: every tile read back as written, a run of equal tiles one
    entry, a tile outside the extract None, and the metadata as written."""
    tiles = oslo_map.coast_tiles()
    path = oslo_map.write_coast(tmp_path / "coast.pmtiles", leaf_size=8)
    with pmtiles.PMTiles(path) as archive:
        assert archive.header.leaf_length > 0 and all(e.run_length == 0 for e in archive.root)
        for (z, x, y), data in tiles.items():
            assert archive.tile(z, x, y) == data
        assert archive.tile(9, 0, 0) is None
        assert archive.tile(14, 0, 0) is None
        assert archive.tile(40, 0, 0) is None
        assert archive.metadata["attribution"] == oslo_map.ATTRIBUTION
    flat = oslo_map.write_coast(tmp_path / "flat.pmtiles", leaf_size=None)
    with pmtiles.PMTiles(flat) as archive:
        assert archive.header.leaf_length == 0
        assert all(archive.tile(*zxy) == data for zxy, data in tiles.items())


def test_a_run_of_equal_tiles_is_one_entry_and_each_reads(tmp_path: Path) -> None:
    same = oslo_map.tile_message({"water": [oslo_map.Feature(3, [[(0, 0), (0, 4096), (4096, 4096)]])]})
    tiles = {(1, x, y): same for x in range(2) for y in range(2)}
    path = oslo_map.write_pmtiles(tmp_path / "sea.pmtiles", tiles, compress=False)
    with pmtiles.PMTiles(path) as archive:
        assert archive.root == [pmtiles.Entry(1, 0, len(same), 4)]
        assert all(archive.tile(1, x, y) == same for x in range(2) for y in range(2))


def test_the_header_check_names_what_is_wrong(tmp_path: Path) -> None:
    path = oslo_map.write_coast(tmp_path / "coast.pmtiles")
    assert "zoom 10 to 14" in pmtiles.read_header(path).describe()
    raster = oslo_map.write_pmtiles(tmp_path / "raster.pmtiles", {(0, 0, 0): b"\x89PNG"}, tile_type=2)
    with pytest.raises(MapError, match="holds PNG, not vector tiles"):
        pmtiles.read_header(raster)
    text = tmp_path / "notes.txt"
    text.write_text("not a map\n", encoding="utf-8")
    with pytest.raises(MapError, match="not a PMTiles file"):
        pmtiles.read_header(text)
    v2 = bytearray(path.read_bytes())
    v2[7] = 2
    (tmp_path / "v2.pmtiles").write_bytes(bytes(v2))
    with pytest.raises(MapError, match="version 2"):
        pmtiles.read_header(tmp_path / "v2.pmtiles")
    brotli = bytearray(path.read_bytes())
    brotli[98] = pmtiles.BROTLI
    (tmp_path / "br.pmtiles").write_bytes(bytes(brotli))
    with pytest.raises(MapError, match="brotli"):
        pmtiles.read_header(tmp_path / "br.pmtiles")
    with pytest.raises(MapError, match="cut short"):
        (tmp_path / "cut.pmtiles").write_bytes(path.read_bytes()[:200])
        pmtiles.read_header(tmp_path / "cut.pmtiles")
    with pytest.raises(MapError, match="cannot be read"):
        pmtiles.read_header(tmp_path / "missing.pmtiles")


# -- the tile decoder ----------------------------------------------------------------------------------------


def _layer(*fields: bytes) -> bytes:
    body = b"".join(fields)
    return oslo_map.f_bytes(3, body)


def test_a_tile_built_by_hand_decodes_to_its_layers_features_and_values() -> None:
    """The vector tile spec's own geometry examples (§4.3.5: a point at 25,17; a line 2,2 2,10 10,10; a
    polygon 3,6 8,12 20,34), and a value of every type the spec has, written field by field."""
    f = oslo_map

    def feature(fid: int, tags: list[int], kind: int, geometry: list[int]) -> bytes:
        return f.f_bytes(
            2, f.f_varint(1, fid) + f.f_packed(2, tags) + f.f_varint(3, kind) + f.f_packed(4, geometry)
        )

    values = [
        f.f_bytes(1, "Kafé Kari".encode()),
        f.key(2, 5) + struct.pack("<f", 1.5),
        f.key(3, 1) + struct.pack("<d", -2.25),
        f.f_varint(4, (-3) & ((1 << 64) - 1)),  # int64, two's complement in ten bytes
        f.f_varint(5, 7),
        f.f_varint(6, f.zigzag(-9)),
        f.f_varint(7, 1),
    ]
    data = _layer(
        f.f_varint(15, 2),
        f.f_bytes(1, b"pois"),
        feature(1, [0, 0, 1, 1, 2, 2], 1, [9, 50, 34]),
        feature(2, [3, 3, 4, 4, 5, 5, 6, 6], 2, [9, 4, 4, 18, 0, 16, 16, 0]),
        feature(3, [], 3, [9, 6, 12, 18, 10, 12, 24, 44, 15]),
        *(f.f_bytes(3, k.encode()) for k in ("name", "f", "d", "i", "u", "s", "b")),
        *(f.f_bytes(4, v) for v in values),
        f.f_varint(5, 4096),
        f.key(9, 2) + f.varint(2) + b"??",  # a field this reader does not know: skipped
    )
    (layer,) = mvt.decode(data)
    assert (layer.name, layer.extent, layer.version) == ("pois", 4096, 2)
    point, line, polygon = layer.features
    assert (point.id, point.type, point.geometry) == (1, mvt.POINT, [[(25, 17)]])
    assert point.properties == {"name": "Kafé Kari", "f": 1.5, "d": -2.25}
    assert line.properties == {"i": -3, "u": 7, "s": -9, "b": True}
    assert line.geometry == [[(2, 2), (2, 10), (10, 10)]]
    assert (polygon.type, polygon.geometry) == (mvt.POLYGON, [[(3, 6), (8, 12), (20, 34)]])


def test_multipart_geometries_and_the_written_coast_decode() -> None:
    f = oslo_map
    ring = [(0, 0), (0, 10), (10, 10), (10, 0)]
    hole = [(2, 2), (8, 2), (8, 8), (2, 8)]
    data = f.tile_message(
        {
            "water": [f.Feature(3, [ring, hole], {"kind": "ocean"})],
            "roads": [f.Feature(2, [[(0, 0), (5, 5)], [(9, 9), (1, 1), (4, 4)]], {"kind": "path"})],
            "pois": [f.Feature(1, [[(1, 2), (3, 4)]], {"name": "Solvind marina"})],
        }
    )
    water, roads, pois = mvt.decode(data)
    assert water.features[0].geometry == [ring, hole]
    assert roads.features[0].geometry == [[(0, 0), (5, 5)], [(9, 9), (1, 1), (4, 4)]]
    assert pois.features[0].geometry == [[(1, 2), (3, 4)]]
    for data in oslo_map.coast_tiles().values():
        assert {layer.name for layer in mvt.decode(data)} <= {
            "water",
            "landuse",
            "roads",
            "places",
            "pois",
            "buildings",
        }


@pytest.mark.parametrize(
    "data",
    [
        b"\x1a\x05\x0a\x03ab",  # a layer cut inside its name
        b"\x1a\xff\xff\xff\xff\x0f",  # a layer longer than the tile
        b"\x1b",  # a group, which no tile has
        b"\x1a\x04\x12\x02\x22\x08",  # a feature whose geometry runs past its end
        b"\x1a\x0b\x12\x09\x12\x02\x05\x00\x22\x03\x09\x02\x02",  # a tag naming no key
        b"\x1a\x05\x12\x03\x22\x01\x09",  # a MoveTo of one point and none of its numbers
        b"\x1a\x06\x12\x04\x22\x02\x0b\x00",  # a command this format has not
        b"\x1a\x0c" + b"\x82" * 11 + b"\x01",  # a varint of twelve bytes
    ],
)
def test_a_damaged_tile_is_one_map_error(data: bytes) -> None:
    with pytest.raises(MapError):
        mvt.decode(data)


# -- hostile and damaged files -------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def coast(tmp_path_factory: pytest.TempPathFactory) -> bytes:
    path = oslo_map.write_coast(tmp_path_factory.mktemp("coast") / "coast.pmtiles", leaf_size=8)
    return path.read_bytes()


def _read_all(path: Path) -> None:
    """Everything a caller can ask of a file: header, metadata, every tile of the coast decoded."""
    with pmtiles.PMTiles(path) as archive:
        _ = archive.metadata
        for z in range(oslo_map.MIN_ZOOM, oslo_map.MAX_ZOOM + 1):
            xs, ys = oslo_map.tile_range(z)
            for x in xs:
                for y in ys:
                    data = archive.tile(z, x, y)
                    if data is not None:
                        mvt.decode(data)


def test_a_file_cut_anywhere_is_one_map_error(coast: bytes, tmp_path: Path) -> None:
    path = tmp_path / "cut.pmtiles"
    for cut in sorted({*range(0, 400, 7), *range(len(coast) - 200, len(coast), 13)}):
        path.write_bytes(coast[:cut])
        with pytest.raises(MapError):
            _read_all(path)


@settings(max_examples=150, deadline=2000, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(flips=st.lists(st.tuples(st.integers(min_value=0), st.integers(1, 255)), min_size=1, max_size=8))
def test_a_flipped_byte_reads_or_is_one_map_error(
    coast: bytes, tmp_path: Path, flips: list[tuple[int, int]]
) -> None:
    data = bytearray(coast)
    for at, mask in flips:
        data[at % len(data)] ^= mask
    path = tmp_path / "flipped.pmtiles"
    path.write_bytes(bytes(data))
    with contextlib.suppress(MapError):
        _read_all(path)


@settings(max_examples=200, deadline=2000)
@given(data=st.binary(max_size=300))
def test_any_bytes_are_a_tile_or_one_map_error(data: bytes) -> None:
    with contextlib.suppress(MapError):
        mvt.decode(data)


@settings(max_examples=100, deadline=2000)
@given(data=st.binary(max_size=200))
def test_any_bytes_are_a_directory_or_one_map_error(data: bytes) -> None:
    with contextlib.suppress(MapError):
        pmtiles.parse_directory(data)


def test_a_hostile_archive_ends_in_one_map_error(coast: bytes, tmp_path: Path) -> None:
    """A gzip bomb as a tile, a leaf that points at itself for ever, a directory counting more entries
    than its bytes hold, an entry past the tile data: each one sentence, none a hang."""
    bomb = gzip.compress(b"\0" * (pmtiles.MAX_INFLATED + 1), compresslevel=9, mtime=0)
    path = oslo_map.write_pmtiles(tmp_path / "bomb.pmtiles", {(0, 0, 0): b""})
    raw = bytearray(path.read_bytes())
    h = pmtiles.parse_header(bytes(raw))
    root = gzip.compress(oslo_map.directory([pmtiles.Entry(0, 0, len(bomb), 1)]), mtime=0)
    rebuilt = _rebuild(raw, h, root=root, data=bomb)
    (tmp_path / "bomb.pmtiles").write_bytes(rebuilt)
    with (
        pytest.raises(MapError, match="inflates past"),
        pmtiles.PMTiles(tmp_path / "bomb.pmtiles") as archive,
    ):
        archive.tile(0, 0, 0)
    leaf = oslo_map.directory([pmtiles.Entry(0, 0, 5, 0)])  # five bytes: a leaf that is itself
    assert len(leaf) == 5
    (tmp_path / "loop.pmtiles").write_bytes(_rebuild(raw, h, root=leaf, leaves=leaf, data=b"", gzip=False))
    with pytest.raises(MapError, match="deeper than"), pmtiles.PMTiles(tmp_path / "loop.pmtiles") as archive:
        archive.tile(0, 0, 0)
    counted = gzip.compress(oslo_map.varint(10**9) + b"\0\0", mtime=0)
    (tmp_path / "count.pmtiles").write_bytes(_rebuild(raw, h, root=counted, data=b""))
    with pytest.raises(MapError, match="counts"):
        pmtiles.PMTiles(tmp_path / "count.pmtiles")
    past = gzip.compress(oslo_map.directory([pmtiles.Entry(0, 50, 10, 1)]), mtime=0)
    (tmp_path / "past.pmtiles").write_bytes(_rebuild(raw, h, root=past, data=b"x" * 20))
    with (
        pytest.raises(MapError, match="outside the tile data"),
        pmtiles.PMTiles(tmp_path / "past.pmtiles") as a,
    ):
        a.tile(0, 0, 0)
    deflated = bytearray(coast)
    deflated[pmtiles.HEADER_SIZE : pmtiles.HEADER_SIZE + 2] = zlib.compress(b"x")[:2]
    (tmp_path / "root.pmtiles").write_bytes(bytes(deflated))
    with pytest.raises(MapError, match="does not inflate"):
        pmtiles.PMTiles(tmp_path / "root.pmtiles")


def _rebuild(
    raw: bytearray, h: pmtiles.Header, *, root: bytes, data: bytes, leaves: bytes = b"", gzip: bool = True
) -> bytes:
    """`raw`'s header with the root, the leaves and the tile data replaced, and no metadata; with
    `gzip` False, the directories stored as they are."""
    at = pmtiles.HEADER_SIZE
    head = bytearray(raw[:at])
    if not gzip:
        head[97] = pmtiles.NONE
    for offset, value in (
        (8, at), (16, len(root)), (24, at + len(root)), (32, 0),
        (40, at + len(root)), (48, len(leaves)), (56, at + len(root) + len(leaves)), (64, len(data)),
    ):  # fmt: skip
        head[offset : offset + 8] = value.to_bytes(8, "little")
    return bytes(head) + root + leaves + data


def test_a_directory_counting_more_entries_than_four_bytes_each_is_refused_at_once() -> None:
    import time

    started = time.monotonic()
    with pytest.raises(MapError, match="counts"):
        pmtiles.parse_directory(oslo_map.varint(15_000_000) + b"\x01" * 15_000_000)
    with pytest.raises(MapError, match="counts"):
        pmtiles.parse_directory(oslo_map.varint(10) + b"\x01" * 30)
    assert time.monotonic() - started < 1
