"""keeper/v1 (RFC 0024): the photos the captain marked keepers, in two lanes, `memory` (a day's
hero photo) and `art`.

`infer(lines)` is the producer `keeper-inference`: for every `photo/v1` line standing it drafts a
`memory` keeper when the library marked the photo a favourite (`favorite` at the payload's top,
as `apple-photos` writes it, or under `extra`, as `immich` does) and an `art` keeper when the
photo is in an album named Art (`albums` or `album`, at the top or under `extra`). The
draft's `raw_id` is `<photo line id>:<lane>`, so `append_many` writes each mark once, and a
retracted keeper (an unmarked favourite) is never written again because its `(source, raw_id)` is
still in the record. `standing(lines)` is the reader: the keeper lines not retracted, for
`logbook keepers` and for a day's hero photos. Nothing here opens a file or a socket."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from .chain import Line
from .store import RETRACTION, retractions

KIND = "keeper"
PHOTO = "photo"  # the kind of the lines the marks are read from
SCHEMA = "keeper/v1"
TIER = 1
LANES = ("memory", "art")
MEMORY, ART = LANES
PRODUCER = "keeper-inference"
ART_ALBUM = "art"
LIBRARY_SOURCE = {"apple-photos": "ios-photos"}  # a library whose mark is spelled under another name


def marks(photo: Line) -> list[str]:
    """The lanes a photo line's library marks put it in: `memory` for a favourite, `art` for
    the Art album; none, one or both."""
    payload = photo.get("payload") or {}
    found = payload.get("extra")
    extra: dict[str, Any] = found if isinstance(found, dict) else {}
    lanes = []
    if any(marks.get(key) is True for marks in (payload, extra) for key in ("favorite", "favourite")):
        lanes.append(MEMORY)
    albums: list[Any] = []
    for marks in (payload, extra):
        listed = marks.get("albums")
        if isinstance(listed, list):
            albums.extend(listed)
        if isinstance(marks.get("album"), str):
            albums.append(marks["album"])
    if any(isinstance(a, str) and a.strip().casefold() == ART_ALBUM for a in albums):
        lanes.append(ART)
    return lanes


def draft(photo: Line, lane: str) -> dict[str, Any]:
    """One keeper/v1 draft for a photo line and a lane."""
    payload = photo.get("payload") or {}
    library = str(payload.get("library") or photo.get("source") or "")
    ref: dict[str, Any] = {"line": str(photo["id"]), "asset_id": payload.get("asset_id"), "library": library}
    if payload.get("file_name"):
        ref["file_name"] = payload["file_name"]
    return {
        "at": photo["at"],
        "end": None,
        "source": PRODUCER,
        "kind": KIND,
        "tier": TIER,
        "payload": {
            "schema": SCHEMA,
            "raw_id": f"{photo['id']}:{lane}",
            "photo": ref,
            "at": photo["at"],
            "lane": lane,
            "source": LIBRARY_SOURCE.get(library, library),
        },
    }


def infer(photos: Iterable[Line], counts: dict[str, int] | None = None) -> Iterator[dict[str, Any]]:
    """Keeper drafts for every mark on the photo lines given (the caller leaves retracted photo
    lines out); `counts["photos"]` and `counts["marked"]` are tallied when a dict is given."""
    for photo in photos:
        if counts is not None:
            counts["photos"] = counts.get("photos", 0) + 1
        lanes = marks(photo)
        if lanes and counts is not None:
            counts["marked"] = counts.get("marked", 0) + 1
        for lane in lanes:
            yield draft(photo, lane)


def standing(lines: Iterable[Line]) -> list[Line]:
    """The keeper lines not retracted, in chain order, from keeper and retraction lines."""
    kept = sorted(lines, key=lambda line: int(line["seq"]))
    retracted = retractions(line for line in kept if line.get("kind") == RETRACTION)
    return [line for line in kept if line.get("kind") == KIND and str(line["id"]) not in retracted]


def summary(line: Line, day: str) -> dict[str, Any]:
    """One keeper as `logbook keepers --json` lists it."""
    payload = line.get("payload") or {}
    return {
        "line": str(line["id"]),
        "day": day,
        "at": line["at"],
        "lane": payload.get("lane"),
        "source": payload.get("source"),
        "photo": payload.get("photo"),
    }


def text(line: Line) -> str:
    """A keeper as `show` prints it: `hero photo (memory): IMG_0001.HEIC`."""
    payload = line.get("payload") or {}
    return f"hero photo ({payload.get('lane')}): {name_of(line)}"


def name_of(line: Line) -> str:
    photo = (line.get("payload") or {}).get("photo")
    if not isinstance(photo, dict):
        return "?"
    return str(photo.get("file_name") or photo.get("asset_id") or photo.get("line") or "?")


def _lane_order(line: Line) -> int:
    lane = (line.get("payload") or {}).get("lane")
    return LANES.index(lane) if lane in LANES else len(LANES)


def hero_row(lines: Iterable[Line]) -> str | None:
    """The one line `show` prints under the date: the day's keepers, memory first."""
    kept = sorted(standing(lines), key=lambda line: (_lane_order(line), str(line["at"])))
    if not kept:
        return None
    names = [
        f"{name_of(line)}" + ("" if line["payload"].get("lane") == MEMORY else " (art)") for line in kept
    ]
    return f"hero  {', '.join(names)}"
