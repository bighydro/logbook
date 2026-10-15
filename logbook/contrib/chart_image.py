"""The owner's chart image as `logbook export world --chart FILE` embeds it: a PNG or a JPEG, read from
disk and never fetched, carried into the page under `IMAGE_BYTES` and `IMAGE_PIXELS`.

**Only the picture crosses.** An image file carries more than its pixels: a phone's photograph of a
paper chart says where it was taken and on what (EXIF, XMP), a scan may name its maker, an editor its
history. None of it goes into the page. A PNG keeps the chunks that draw it (`IHDR`, `PLTE`, `tRNS`,
`gAMA`, `cHRM`, `sRGB`, `IDAT`, `IEND`), a JPEG the segments that decode it (the frame, the tables,
the scans, Adobe's colour marker); a colour profile, the text chunks and every application segment
are left out, and so is anything after the image's end (a second picture, a gain map). An image stored
rotated (an EXIF orientation other than 1) is refused, since its control points were measured on the
picture as a viewer turns it, which the page, without its EXIF, would not: save it upright first.

**The cap.** A PNG over the cap is downscaled here, by a whole factor (2, 3, …) and box-averaged, and
written again as a PNG, lossless; the control points stay in the pixels of the file as given and the
page draws each pixel of the smaller picture as that many of the original (`Image.scale`). A PNG of
tens of megapixels takes a while: this is the standard library, no image library. A JPEG is never
decoded — the standard library carries no JPEG codec — so one over the cap is refused, saying how
wide to save it. Nothing here writes a file."""

from __future__ import annotations

import math
import struct
import zlib
from dataclasses import dataclass
from itertools import accumulate
from operator import add, sub
from pathlib import Path

IMAGE_BYTES = 4 * 1024 * 1024  # the chart as the page carries it, at most (base64 in the page: a third more)
IMAGE_PIXELS = 40_000_000  # and at most this many pixels, which a browser holds as four bytes each
PNG, JPEG = "image/png", "image/jpeg"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_KEEP = frozenset({b"IHDR", b"PLTE", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"IDAT", b"IEND"})
JPEG_SOF = frozenset({0xC0, 0xC1, 0xC2})  # baseline, extended and progressive Huffman: what a browser draws
JPEG_KEEP = frozenset({0xC4, 0xCC, 0xDB, 0xDD, 0xDC, 0xEE})  # tables, restart interval, lines, Adobe
SOS, EOI, SOI = 0xDA, 0xD9, 0xD8
ORIENTATION_TAG = 0x0112
BYTE = (255).__and__  # an int to a byte's value, modulo 256 (a negative one too)


class ChartImageError(ValueError):
    """An image the export refuses; the message says why and what to do."""


@dataclass(frozen=True)
class Image:
    """The chart as the page embeds it."""

    mime: str
    data: bytes  # what the page carries: the picture, nothing else
    width: int  # the file as given: the pixels the control points count
    height: int
    factor: int  # each pixel of `data` is factor × factor of the file as given (1: not downscaled)
    given_bytes: int
    dropped: tuple[str, ...]  # what was left out, by name: chunks or segments

    @property
    def scale(self) -> float:
        return 1 / self.factor

    @property
    def embedded_size(self) -> tuple[int, int]:
        return math.ceil(self.width / self.factor), math.ceil(self.height / self.factor)


def read(path: Path) -> Image:
    """The image at `path` as the page will carry it; `ChartImageError` for one it will not."""
    try:
        raw = Path(path).read_bytes()
    except OSError as e:
        raise ChartImageError(f"--chart {path}: {e}") from e
    if raw.startswith(PNG_SIGNATURE):
        return _png(raw, str(path))
    if raw.startswith(b"\xff\xd8\xff"):
        return _jpeg(raw, str(path))
    raise ChartImageError(f"--chart {path}: not a PNG or a JPEG")


# -- PNG ----------------------------------------------------------------------------------------------------


def png_chunks(raw: bytes, where: str = "the PNG") -> list[tuple[bytes, bytes]]:
    """The chunks of a PNG, each `(type, data)`, their CRCs checked, up to `IEND`."""
    chunks: list[tuple[bytes, bytes]] = []
    at = len(PNG_SIGNATURE)
    while at + 12 <= len(raw):
        (length,) = struct.unpack(">I", raw[at : at + 4])
        kind = raw[at + 4 : at + 8]
        data = raw[at + 8 : at + 8 + length]
        if len(data) != length or at + 12 + length > len(raw):
            raise ChartImageError(f"{where}: cut short in its {kind.decode('latin-1')!r} chunk")
        (crc,) = struct.unpack(">I", raw[at + 8 + length : at + 12 + length])
        if zlib.crc32(kind + data) != crc:
            raise ChartImageError(f"{where}: the {kind.decode('latin-1')!r} chunk is damaged (its CRC)")
        chunks.append((kind, data))
        at += 12 + length
        if kind == b"IEND":
            return chunks
    raise ChartImageError(f"{where}: no IEND; the file is cut short")


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def _png(raw: bytes, where: str) -> Image:
    chunks = png_chunks(raw, where)
    if not chunks or chunks[0][0] != b"IHDR" or len(chunks[0][1]) != 13:
        raise ChartImageError(f"{where}: a PNG starts with IHDR")
    width, height = struct.unpack(">II", chunks[0][1][:8])
    if not width or not height:
        raise ChartImageError(f"{where}: an image of {width} × {height} pixels")
    for kind, data in chunks:
        if kind == b"eXIf":
            _upright(data, where)
    kept = [(kind, data) for kind, data in chunks if kind in PNG_KEEP]
    dropped = tuple(sorted({kind.decode("latin-1") for kind, _data in chunks if kind not in PNG_KEEP}))
    stripped = PNG_SIGNATURE + b"".join(_chunk(kind, data) for kind, data in kept)
    if len(stripped) <= IMAGE_BYTES and width * height <= IMAGE_PIXELS:
        return Image(PNG, stripped, width, height, 1, len(raw), dropped)
    pixels = decode_png(kept, where)
    factor = max(2, math.ceil(math.sqrt(width * height / IMAGE_PIXELS)))
    factor = max(factor, math.floor(math.sqrt(len(stripped) / IMAGE_BYTES)))
    while True:
        data = encode_png(downscale(pixels, factor))
        if len(data) <= IMAGE_BYTES:
            return Image(PNG, data, width, height, factor, len(raw), dropped)
        factor += 1


@dataclass(frozen=True)
class Pixels:
    """A raster of 8-bit samples, `channels` per pixel (1 grey, 2 grey and alpha, 3 RGB, 4 RGBA), one
    `bytes` per row."""

    width: int
    height: int
    channels: int
    rows: list[bytes]


def decode_png(chunks: list[tuple[bytes, bytes]], where: str = "the PNG") -> Pixels:
    """The pixels of a PNG's chunks, as 8-bit samples (16-bit ones rounded, a palette expanded).
    Interlaced PNGs are refused."""
    header = dict(chunks).get(b"IHDR", b"")
    width, height, depth, colour, _compression, _filter, interlace = struct.unpack(">IIBBBBB", header)
    if interlace:
        raise ChartImageError(f"{where}: interlaced and over the cap; save it without interlacing")
    samples = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(colour)
    if samples is None or depth not in {1, 2, 4, 8, 16} or (colour in {2, 4, 6} and depth < 8):
        raise ChartImageError(f"{where}: colour type {colour} at {depth} bits is not a PNG")
    bits = samples * depth
    stride = max(1, bits // 8)
    row_bytes = (width * bits + 7) // 8
    try:
        flat = zlib.decompress(b"".join(data for kind, data in chunks if kind == b"IDAT"))
    except zlib.error as e:
        raise ChartImageError(f"{where}: its image data does not inflate ({e})") from e
    if len(flat) < height * (row_bytes + 1):
        raise ChartImageError(f"{where}: its image data is cut short")
    palette = dict(chunks).get(b"PLTE", b"")
    alpha = dict(chunks).get(b"tRNS", b"") if colour == 3 else b""
    rows: list[bytes] = []
    prior = bytes(row_bytes)
    for y in range(height):
        start = y * (row_bytes + 1)
        line = _unfilter(flat[start], flat[start + 1 : start + 1 + row_bytes], prior, stride, where)
        prior = line
        rows.append(_samples(line, width, depth, colour, palette, alpha))
    channels = {0: 1, 2: 3, 3: 4 if alpha else 3, 4: 2, 6: 4}[colour]
    return Pixels(width, height, channels, rows)


def _unfilter(kind: int, line: bytes, prior: bytes, stride: int, where: str) -> bytes:
    if kind == 0:
        return bytes(line)
    if kind == 2:
        return bytes(map(BYTE, map(add, line, prior)))
    out = bytearray(line)
    n = len(out)
    if kind == 1:
        for c in range(min(stride, n)):
            out[c::stride] = bytes(map(BYTE, accumulate(out[c::stride])))
        return bytes(out)
    if kind == 3:
        for i in range(n):
            left = out[i - stride] if i >= stride else 0
            out[i] = (out[i] + ((left + prior[i]) >> 1)) & 255
        return bytes(out)
    if kind == 4:
        for i in range(n):
            a = out[i - stride] if i >= stride else 0
            b = prior[i]
            c = prior[i - stride] if i >= stride else 0
            p = a + b - c
            pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
            out[i] = (out[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        return bytes(out)
    raise ChartImageError(f"{where}: an unknown row filter {kind}")


def _samples(line: bytes, width: int, depth: int, colour: int, palette: bytes, alpha: bytes) -> bytes:
    """One row at 8 bits a sample: 16-bit samples rounded to 8, fewer bits unpacked (grey scaled
    to 0 to 255), a palette's indices expanded to its colours (and its alpha, when it has one)."""
    if depth == 16:
        line = bytes(
            ((hi << 8 | lo) * 255 + 32767) // 65535 for hi, lo in zip(line[0::2], line[1::2], strict=True)
        )
    elif depth < 8:
        per = 8 // depth
        mask = (1 << depth) - 1
        values = [(byte >> (8 - depth * (k + 1))) & mask for byte in line for k in range(per)][:width]
        line = bytes(v * 255 // mask for v in values) if colour == 0 else bytes(values)
    if colour != 3:
        return bytes(line)
    out = bytearray()
    for index in line[:width]:
        rgb = palette[index * 3 : index * 3 + 3] or b"\x00\x00\x00"
        out += rgb
        if alpha:
            out.append(alpha[index] if index < len(alpha) else 255)
    return bytes(out)


def downscale(pixels: Pixels, factor: int) -> Pixels:
    """Every `factor` × `factor` block of pixels averaged into one; the blocks at the right and the
    bottom edge average the pixels they have."""
    ch, k = pixels.channels, factor
    width = math.ceil(pixels.width / k)
    rows: list[bytes] = []
    for y0 in range(0, pixels.height, k):
        block = pixels.rows[y0 : y0 + k]
        acc = list(block[0])
        for row in block[1:]:
            acc = list(map(add, acc, row))
        out = bytearray(width * ch)
        for x in range(width):
            x0, x1 = x * k, min(pixels.width, (x + 1) * k)
            count = (x1 - x0) * len(block)
            for c in range(ch):
                out[x * ch + c] = (sum(acc[x0 * ch + c : x1 * ch : ch]) + count // 2) // count
        rows.append(bytes(out))
    return Pixels(width, len(rows), ch, rows)


def encode_png(pixels: Pixels) -> bytes:
    """A PNG of 8-bit samples, every row filtered by Up (the first by None), deflated at level 9."""
    colour = {1: 0, 2: 4, 3: 2, 4: 6}[pixels.channels]
    header = struct.pack(">IIBBBBB", pixels.width, pixels.height, 8, colour, 0, 0, 0)
    body = bytearray()
    prior: bytes | None = None
    for row in pixels.rows:
        if prior is None:
            body += b"\x00" + row
        else:
            body += b"\x02" + bytes(map(BYTE, map(sub, row, prior)))
        prior = row
    return (
        PNG_SIGNATURE
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(body), 9))
        + _chunk(b"IEND", b"")
    )


# -- JPEG ---------------------------------------------------------------------------------------------------


def jpeg_segments(raw: bytes, where: str = "the JPEG") -> list[tuple[int, bytes]]:
    """The segments of a JPEG up to its first end of image, each `(marker, bytes as in the file)`: a
    scan carries its entropy-coded data with it."""
    out: list[tuple[int, bytes]] = [(SOI, raw[:2])]
    at = 2
    while at < len(raw):
        if raw[at] != 0xFF:
            raise ChartImageError(f"{where}: no marker where one should be (byte {at})")
        while at < len(raw) and raw[at] == 0xFF:  # a marker may be preceded by fill bytes
            at += 1
        if at >= len(raw):
            break
        marker = raw[at]
        at += 1
        if marker == EOI:
            out.append((EOI, b"\xff\xd9"))
            return out
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:
            out.append((marker, bytes((0xFF, marker))))
            continue
        if at + 2 > len(raw):
            break
        (length,) = struct.unpack(">H", raw[at : at + 2])
        end = at + length
        if length < 2 or end > len(raw):
            raise ChartImageError(f"{where}: a segment runs past the end of the file")
        if marker == SOS:
            end = _scan_end(raw, end)
        out.append((marker, bytes((0xFF, marker)) + raw[at:end]))
        at = end
    raise ChartImageError(f"{where}: no end of image; the file is cut short")


def _scan_end(raw: bytes, at: int) -> int:
    """Where a scan's entropy-coded data ends: at the first marker that is not a stuffed byte or a
    restart."""
    while True:
        at = raw.find(b"\xff", at)
        if at < 0 or at + 1 >= len(raw):
            return len(raw)
        following = raw[at + 1]
        if following == 0x00 or 0xD0 <= following <= 0xD7 or following == 0xFF:
            at += 1
            continue
        return at


def _jpeg(raw: bytes, where: str) -> Image:
    segments = jpeg_segments(raw, where)
    width = height = 0
    frame = None
    for marker, data in segments:
        if marker == 0xE1 and data[4:10] == b"Exif\x00\x00":
            _upright(data[10:], where)
        if 0xC0 <= marker <= 0xCF and marker not in {0xC4, 0xC8, 0xCC}:
            frame = marker
            height, width = struct.unpack(">HH", data[5:9])
    if frame is None:
        raise ChartImageError(f"{where}: a JPEG with no frame")
    if frame not in JPEG_SOF:
        raise ChartImageError(
            f"{where}: a JPEG coded in a way a browser does not draw (marker {frame:#04x}); save it as a"
            " baseline or progressive JPEG"
        )
    if not width or not height:
        raise ChartImageError(f"{where}: a JPEG of {width} × {height} pixels")
    keep = {SOI, EOI, SOS, frame} | JPEG_KEEP
    kept = [data for marker, data in segments if marker in keep or 0xD0 <= marker <= 0xD7]
    dropped = tuple(sorted({_segment_name(marker) for marker, _data in segments if marker not in keep}))
    data = b"".join(kept)
    over_bytes, over_pixels = len(data) > IMAGE_BYTES, width * height > IMAGE_PIXELS
    if over_bytes or over_pixels:
        share = min(math.sqrt(IMAGE_BYTES / len(data)), math.sqrt(IMAGE_PIXELS / (width * height)))
        wide = max(1, math.floor(width * share * 0.95))
        raise ChartImageError(
            f"{where}: {len(data):,} bytes and {width:,} × {height:,} pixels, over the cap of {IMAGE_BYTES:,}"
            f" bytes and {IMAGE_PIXELS:,} pixels; a JPEG is never re-encoded here (the standard library has"
            f" no JPEG codec), so save it smaller — about {wide:,} pixels wide — and measure the control"
            " points on that file, or save it as a PNG, which the export downscales itself"
        )
    return Image(JPEG, data, width, height, 1, len(raw), dropped)


def _segment_name(marker: int) -> str:
    if 0xE0 <= marker <= 0xEF:
        return f"APP{marker - 0xE0}"
    return {0xFE: "COM"}.get(marker, f"{marker:#04x}")


# -- EXIF ---------------------------------------------------------------------------------------------------


def orientation(tiff: bytes) -> int | None:
    """The EXIF orientation of a TIFF structure (an `eXIf` chunk, a JPEG's `Exif` segment less its
    header), or None when it names none."""
    if len(tiff) < 8 or tiff[:2] not in {b"II", b"MM"}:
        return None
    order = "<" if tiff[:2] == b"II" else ">"
    (first,) = struct.unpack(order + "I", tiff[4:8])
    if first + 2 > len(tiff):
        return None
    (count,) = struct.unpack(order + "H", tiff[first : first + 2])
    for n in range(count):
        at = first + 2 + 12 * n
        if at + 12 > len(tiff):
            return None
        tag, kind = struct.unpack(order + "HH", tiff[at : at + 4])
        if tag == ORIENTATION_TAG and kind == 3:
            (value,) = struct.unpack(order + "H", tiff[at + 8 : at + 10])
            return int(value)
    return None


def _upright(tiff: bytes, where: str) -> None:
    found = orientation(tiff)
    if found not in {None, 1}:
        raise ChartImageError(
            f"{where}: stored turned or mirrored (EXIF orientation {found}), which the page would not"
            " undo once the EXIF is left out; save it upright, then measure the control points on it"
        )
