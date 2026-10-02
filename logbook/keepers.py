"""keeper/v1 (RFC 0024): the photos the captain marked keepers, in two lanes, `memory` (a day's
hero photo) and `art`.

`infer(lines)` is the producer `keeper-inference`: for every `photo/v1` line standing it drafts a
`memory` keeper when the library marked the photo a favourite (`favorite` at the payload's top,
as `apple-photos` writes it, or under `extra`, as `immich` does) and an `art` keeper when the
photo is in an album named Art (`albums` or `album`, at the top or under `extra`). The
draft's `raw_id` is `<photo line id>:<lane>`, so `append_many` writes each mark once, and a
retracted keeper (an unmarked favourite) is never written again because its `(source, raw_id)` is
still in the record. `standing(lines)` is the reader: the keeper lines not retracted, for
`logbook keepers` and for a day's hero photos. `people_by_month` is `logbook keepers --people`:
who appears on the keepers, per month, from the faces the library named on each keeper's photo
line (`extra.faces`) and the people it tagged by id (`people`), every one a proposal — a face
never confirms (the with module's rule, `present.from_photos`). Nothing here opens a file or a
socket."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from typing import Any

from .chain import Line
from .index import local_date
from .resolve import Identity, Ref
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


def people_by_month(
    kept: Iterable[Line], photos: Mapping[str, Line], identities: Mapping[Ref, Identity], tz: str
) -> list[dict[str, Any]]:
    """Who appears on the keepers, per local month: one row per month and person — a person the
    record resolves (by the library's id through `provider_id`, or by a face's name that is exactly
    a label, `present.by_label`), else the name as the library wrote it — with how many keepers
    they are on, by lane, and the keeper lines. `photos` is the keepers' photo lines by id; a
    keeper whose photo is not there names nobody. Months in order; within a month the most keepers
    first, then the name. Every row is `proposed`: a face is the library's guess."""

    rows: dict[tuple[str, str | None, str], dict[str, Any]] = {}
    for keeper in kept:
        payload = keeper.get("payload") or {}
        ref = payload.get("photo")
        photo = photos.get(str(ref.get("line"))) if isinstance(ref, dict) else None
        if photo is None:
            continue
        month = local_date(str(keeper["at"]), tz)[:7]
        lane = str(payload.get("lane") or "")
        for person, name in _on_photo(photo, identities):
            key = (month, person, "" if person else name.casefold())
            row = rows.setdefault(
                key,
                {
                    "month": month,
                    "name": name,
                    "person": person,
                    "status": "proposed",
                    "keepers": 0,
                    "lanes": dict.fromkeys(LANES, 0),
                    "lines": [],
                },
            )
            if str(keeper["id"]) in row["lines"]:
                continue
            row["keepers"] += 1
            if lane in LANES:
                row["lanes"][lane] += 1
            row["lines"].append(str(keeper["id"]))
    return sorted(rows.values(), key=lambda r: (r["month"], -r["keepers"], r["name"].casefold()))


def _on_photo(photo: Line, identities: Mapping[Ref, Identity]) -> list[tuple[str | None, str]]:
    """(person, name) for everyone a photo line names, each once: the ids under `people`, through
    the library's `provider_id`, then the names under `extra.faces`; a name that resolves to a
    person an id already named adds nothing, one that resolves to nobody is itself."""
    from .present import by_label, resolve_ref

    payload = photo.get("payload") or {}
    library = str(payload.get("library") or photo.get("source") or "")
    found: list[tuple[str | None, str]] = []
    people = payload.get("people")
    for person_id in people if isinstance(people, list) else []:
        if isinstance(person_id, str) and person_id:
            person, label = resolve_ref(("provider_id", f"{library}:{person_id}"), identities)
            found.append((person, label or f"{library}:{person_id}"))
    extra = payload.get("extra")
    faces = extra.get("faces") if isinstance(extra, dict) else None
    for name in faces if isinstance(faces, list) else []:
        if isinstance(name, str) and name.strip():
            name = " ".join(name.split())
            person, label = by_label(name, identities)
            found.append((person, label or name))
    seen: set[tuple[str | None, str]] = set()
    unique = []
    for person, name in found:
        key = (person, "" if person else name.casefold())
        if key not in seen:
            seen.add(key)
            unique.append((person, name))
    return unique


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
