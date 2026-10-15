"""A synthetic chart for `logbook export world --chart`: an image made here, pixel by pixel, of a grid
of the Oslo fjord laid on Mercator's plane by a known transform — a scan turned a few degrees, and,
when asked, photographed at an angle — with the places of `tests/world_record.py` marked on it, so a
test knows where every position of the record belongs on the paper. Nothing in it is real: the grid is
a grid, the marks are the synthetic persona's places, and the PNG is written with `zlib` alone."""

from __future__ import annotations

import json
import math
import struct
import zlib
from collections.abc import Callable
from pathlib import Path

from world_record import HOME, HYTTA, MARINA

WIDTH, HEIGHT = 640, 900
LON0, LAT0 = 10.65, 59.80  # the middle of the paper
SCALE = 1400.0  # pixels per degree of Mercator's plane
TURN = 4.0  # degrees the scan is turned
PAPER, INK, MARK = (235, 222, 190), (70, 50, 30), (30, 60, 110)
CORNERS = [(59.70, 10.55), (59.70, 10.75), (59.90, 10.75), (59.90, 10.55)]  # grid crossings, (lat, lon)
MIDDLE = (59.80, 10.65)

Transform = Callable[[float, float], tuple[float, float]]


def north(lat: float) -> float:
    return math.log(math.tan(math.pi / 4 + lat * math.pi / 360)) * 180 / math.pi


def known(tilt: float = 0.0) -> Transform:
    """The paper's own transform, a position to its pixel: Mercator's plane, turned by `TURN`, scaled,
    centred; `tilt` > 0 photographs it at an angle (a homography whose horizon is far off the paper)."""
    c, s = math.cos(math.radians(TURN)), math.sin(math.radians(TURN))

    def to_pixel(lat: float, lon: float) -> tuple[float, float]:
        e, n = lon - LON0, north(lat) - north(LAT0)
        x, y = SCALE * (c * e - s * n), -SCALE * (s * e + c * n)
        w = 1 + tilt * (x + 0.5 * y) / WIDTH
        return WIDTH / 2 + x / w, HEIGHT / 2 + y / w

    return to_pixel


def png(path: Path, to_pixel: Transform, extra_chunks: bytes = b"") -> bytes:
    """The paper as a PNG at `path`: the grid every 0.05° engraved, the places marked by rings.
    `extra_chunks` (whole chunks) go in after IHDR: what a scanner or a phone would add."""
    pixels = [bytearray(bytes(PAPER) * WIDTH) for _ in range(HEIGHT)]

    def ink(x: float, y: float, colour: tuple[int, int, int]) -> None:
        i, j = round(x), round(y)
        if 0 <= i < WIDTH and 0 <= j < HEIGHT:
            pixels[j][i * 3 : i * 3 + 3] = bytes(colour)

    for k in range(9):
        lat = 59.60 + 0.05 * k
        for t in range(2001):
            ink(*to_pixel(lat, 10.40 + 0.5 * t / 2000), INK)
    for k in range(11):
        lon = 10.40 + 0.05 * k
        for t in range(2001):
            ink(*to_pixel(59.60 + 0.4 * t / 2000, lon), INK)
    for lat, lon in (HOME, MARINA, HYTTA):
        x, y = to_pixel(lat, lon)
        for t in range(120):
            a = 2 * math.pi * t / 120
            ink(x + 6 * math.cos(a), y + 6 * math.sin(a), MARK)
    raw = b"".join(b"\x00" + bytes(row) for row in pixels)
    data = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0))
        + extra_chunks
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(data)
    return data


def chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def points(
    to_pixel: Transform, where: list[tuple[float, float]] | None = None
) -> list[dict[str, float | str]]:
    """Control points at grid crossings, their pixels as the paper's transform puts them."""
    out: list[dict[str, float | str]] = []
    for n, (lat, lon) in enumerate(where or CORNERS, 1):
        x, y = to_pixel(lat, lon)
        out.append({"name": f"crossing {n}", "x": round(x, 3), "y": round(y, 3), "lat": lat, "lon": lon})
    return out


def write_points(path: Path, found: list[dict[str, float | str]]) -> Path:
    path.write_text(json.dumps({"points": found}, indent=2), encoding="utf-8")
    return path
