"""Apple Photos' Photos.sqlite → photo/v1 (RFC 0002).

Reads the library store an iPhone keeps at `Media/PhotoData/Photos.sqlite` (`CameraRollDomain`;
`logbook import-backup` copies it out as `apple-photos/Photos.sqlite` with its -wal) and a Mac at
`~/Pictures/Photos Library.photoslibrary/database/Photos.sqlite`. The tables that matter:

    ZASSET                       (ZUUID, ZDATECREATED — seconds since 2001-01-01 UTC —, ZKIND 0 image
                                  1 video, ZKINDSUBTYPE 2 live photo 10 screenshot 1 panorama 100-103
                                  video kinds, ZFAVORITE, ZHIDDEN, ZTRASHEDSTATE, ZWIDTH, ZHEIGHT,
                                  ZDURATION, ZLATITUDE, ZLONGITUDE (-180 when none), ZFILENAME,
                                  ZUNIFORMTYPEIDENTIFIER)
    ZADDITIONALASSETATTRIBUTES   (ZASSET → ZASSET.Z_PK, ZORIGINALFILENAME, ZTIMEZONENAME, ZIMPORTEDBY,
                                  ZIMPORTEDBYBUNDLEIDENTIFIER)
    ZGENERICALBUM                (ZKIND 2 the owner's own albums, ZTITLE, ZTRASHEDSTATE)
    Z_<n>ASSETS                  the album ↔ asset join; `n` is the Album entity's number in
                                 Z_PRIMARYKEY and changes with iOS, so the table is found by its shape
    ZDETECTEDFACE                (ZASSETFORFACE, ZPERSONFORFACE)
    ZPERSON                      (ZPERSONUUID, ZFULLNAME, ZDISPLAYNAME, ZMERGETARGETPERSON)

One line per asset not in the trash: `asset_id` and `raw_id` the asset's UUID, `library` `apple-photos`,
`file_name` the original file name the camera or sender gave it (`ZORIGINALFILENAME`, else the
library's own `ZFILENAME`), `media`, `lat`/`lon` when the store has them, `width`/`height`,
`duration_s` for a video, `live_photo` when it has a motion half, `faces` the number of faces the
library found, `people` the UUIDs of the people among them **that the owner has named** (a merged
person counts under its merge target; ids, never names — RFC 0002), `favorite` and `hidden` when set,
`albums` the titles of the owner's own albums (kind 2, not trashed) it is in, sorted; the automatic
groupings (smart albums, memories, shared streams, folders) are not albums. `extra` keeps the UTI,
`imported_by`, the importing app's bundle id and `faces`, the names the owner gave those people in
the People album (the full name, else the display name; a merged person under its target's), sorted.
A name there is the library's guess at who is in the picture and the owner's spelling of it: a
reader proposes it as company and never confirms it (`present.from_photos`), and resolves it to a
person only when it is exactly a label a resolution line carries.

Favourites and the Art album are keepers (RFC 0024): `KEEPERS` tells `logbook add` to write one
`keeper/v1` line per mark through `keepers.draft` once the photo lines are in the record, keyed by
the photo line's id and lane so a re-import, and `infer keepers` after it, write nothing twice.

Provenance follows the store's own record of how the asset arrived (RFC 0002): `screenshot` when the
subtype says so; `camera` for a live photo, a camera video kind, or an import by the back or front
camera (`ZIMPORTEDBY` 1 or 2, or the camera's bundle id); `received` for an import by another app
(3), by AirDrop or sharing (8), or shared with the owner (13); else `other`.

`at` is `ZDATECREATED`, the capture time, to the second. `tz` is the asset's `ZTIMEZONENAME` when it is
an IANA name (`Europe/Oslo`; the store also writes `GMT+0200`, which is not one), else the record's zone.
**Merge key** (RFC 0002, "Several libraries, one asset"): the pair `(file_name, at)` is what the Immich
line for the same asset carries too, so a reader folds the two by equal name (ignoring case) and
instants within a second; this adapter writes its own line and never looks the other up.

Trashed assets and assets without a capture date are skipped and counted. Every line is tier 1
(metadata; `logbook add --tier` overrides). Pure: opened `mode=ro`, `immutable=1`; albums, faces and
people are read once into memory (a library of a few hundred thousand assets fits), then one SELECT
over the assets streams in capture order; no network.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

NAME = "apple-photos"
KIND = "photo"
TIER = 1  # RFC 0002: metadata; `logbook add --tier` overrides
SCHEMA = "photo/v1"
KEEPERS = True  # `logbook add` writes the keeper/v1 lines for the marks on these photos (RFC 0024)

SQLITE_HEADER = b"SQLite format 3\x00"
APPLE_EPOCH_UTC = datetime(2001, 1, 1, tzinfo=UTC)
PLACEHOLDER_BEFORE_YEAR = 1900
NO_LOCATION = -180.0  # what the store writes for an asset without coordinates
REQUIRED_TABLES = ("ZASSET", "ZADDITIONALASSETATTRIBUTES")
USER_ALBUM = 2  # ZGENERICALBUM.ZKIND of an album the owner made
LIVE_PHOTO = 2
SCREENSHOT = 10
VIDEO_KINDS = frozenset({100, 101, 102, 103})  # slo-mo, time-lapse, cinematic, … : the camera's video
CAMERA_IMPORTS = frozenset({1, 2})  # ZIMPORTEDBY: back camera, front camera
RECEIVED_IMPORTS = frozenset({3, 8, 13})  # another app, AirDrop or sharing, shared with you
CAMERA_BUNDLE = "com.apple.camera"
JOIN_TABLE = re.compile(r"^Z_\d+ASSETS$")

ASSET_COLUMNS = (
    "Z_PK",
    "ZUUID",
    "ZDATECREATED",
    "ZKIND",
    "ZKINDSUBTYPE",
    "ZFAVORITE",
    "ZHIDDEN",
    "ZTRASHEDSTATE",
    "ZWIDTH",
    "ZHEIGHT",
    "ZDURATION",
    "ZLATITUDE",
    "ZLONGITUDE",
    "ZFILENAME",
    "ZUNIFORMTYPEIDENTIFIER",
)
ATTRIBUTE_COLUMNS = ("ZORIGINALFILENAME", "ZTIMEZONENAME", "ZIMPORTEDBY", "ZIMPORTEDBYBUNDLEIDENTIFIER")


def sniff(path: Path) -> bool:
    """A SQLite file with `ZASSET` and `ZADDITIONALASSETATTRIBUTES` tables. Never raises."""
    path = Path(path)
    try:
        if not path.is_file():
            return False
        with path.open("rb") as fh:
            if fh.read(len(SQLITE_HEADER)) != SQLITE_HEADER:
                return False
        con = _open(path)
    except (OSError, ValueError, sqlite3.Error):
        return False
    try:
        return all(t in _tables(con) for t in REQUIRED_TABLES)
    except sqlite3.Error:
        return False
    finally:
        con.close()


def _open(path: Path) -> sqlite3.Connection:
    """Read-only and immutable: SQLite neither locks the file nor writes a journal beside it."""
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)


def _tables(con: sqlite3.Connection) -> set[str]:
    rows = con.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(name) for (name,) in rows}


def _columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")]


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
    tier: int | None = None,
) -> Iterator[dict[str, Any]]:
    """One photo/v1 line per asset, in capture order.

    `since` is RFC3339 UTC; lines with `at` before it are not yielded. `counts` tallies
    `skipped_trashed`, `skipped_no_timestamp` and `skipped_placeholder_date`. `timezone` is the
    record's zone, the line's `tz` when the asset has no IANA zone of its own. `tier` overrides 1."""
    path = Path(path)
    counts = counts if counts is not None else {}
    con = _open(path)
    try:
        tables = _tables(con)
        albums = _albums(con, tables)
        faces, people, names = _faces(con, tables)
        asset_columns = _columns(con, "ZASSET")
        attribute_columns = _columns(con, "ZADDITIONALASSETATTRIBUTES")
        select = [f"a.{c}" if c in asset_columns else f"NULL AS {c}" for c in ASSET_COLUMNS]
        select += [f"b.{c}" if c in attribute_columns else f"NULL AS {c}" for c in ATTRIBUTE_COLUMNS]
        order = "a.ZDATECREATED, a.Z_PK" if "ZDATECREATED" in asset_columns else "a.Z_PK"
        join = (
            "LEFT JOIN ZADDITIONALASSETATTRIBUTES b ON b.ZASSET = a.Z_PK"
            if "ZASSET" in attribute_columns
            else ""
        )
        columns = ASSET_COLUMNS + ATTRIBUTE_COLUMNS
        for row in con.execute(f"SELECT {', '.join(select)} FROM ZASSET a {join} ORDER BY {order}"):
            values = dict(zip(columns, row, strict=True))
            line = _line(values, albums, faces, people, names, counts, timezone, tier or TIER)
            if line is None or (since and line["at"] < since):
                continue
            yield line
    finally:
        con.close()


def _albums(con: sqlite3.Connection, tables: set[str]) -> dict[int, list[str]]:
    """`asset Z_PK → sorted titles` of the owner's own albums, through the join table found by its
    shape (one column ending in ALBUMS, one in ASSETS, neither an ordering key)."""
    if "ZGENERICALBUM" not in tables:
        return {}
    columns = _columns(con, "ZGENERICALBUM")
    if not {"ZKIND", "ZTITLE"} <= set(columns):
        return {}
    trashed = "ZTRASHEDSTATE" in columns
    titles: dict[int, str] = {}
    sql = f"SELECT Z_PK, ZTITLE{', ZTRASHEDSTATE' if trashed else ''} FROM ZGENERICALBUM WHERE ZKIND = ?"
    for row in con.execute(sql, (USER_ALBUM,)):
        if trashed and row[2]:
            continue
        title = _text(row[1])
        if title:
            titles[int(row[0])] = title
    join = _join_table(con, tables)
    if join is None or not titles:
        return {}
    table, album_column, asset_column = join
    found: dict[int, set[str]] = {}
    for album_pk, asset_pk in con.execute(f"SELECT {album_column}, {asset_column} FROM {table}"):
        found_title = titles.get(album_pk) if isinstance(album_pk, int) else None
        if found_title is not None and isinstance(asset_pk, int):
            found.setdefault(asset_pk, set()).add(found_title)
    return {pk: sorted(names) for pk, names in found.items()}


def _join_table(con: sqlite3.Connection, tables: set[str]) -> tuple[str, str, str] | None:
    for table in sorted(t for t in tables if JOIN_TABLE.match(t)):
        columns = [c for c in _columns(con, table) if not c.startswith("Z_FOK_")]
        albums = [c for c in columns if c.endswith("ALBUMS")]
        assets = [c for c in columns if c.endswith("ASSETS")]
        if len(albums) == 1 and len(assets) == 1:
            return table, albums[0], assets[0]
    return None


Faces = tuple[dict[int, int], dict[int, list[str]], dict[int, list[str]]]


def _faces(con: sqlite3.Connection, tables: set[str]) -> Faces:
    """(`asset Z_PK → number of faces`, `asset Z_PK → sorted UUIDs of the named people among them`,
    `asset Z_PK → their names, sorted`). A name is the person's full name, else the display name,
    as the People album shows it. A person merged into another counts under the merge target's
    name and UUID."""
    if "ZDETECTEDFACE" not in tables:
        return {}, {}, {}
    face_columns = set(_columns(con, "ZDETECTEDFACE"))
    if "ZASSETFORFACE" not in face_columns:
        return {}, {}, {}
    named: dict[int, tuple[str, str]] = {}  # person Z_PK → (UUID, name) of the person it stands for
    if "ZPERSON" in tables:
        person_columns = set(_columns(con, "ZPERSON"))
        if "ZPERSONUUID" in person_columns:
            select = ["Z_PK", "ZPERSONUUID"]
            select.append("ZFULLNAME" if "ZFULLNAME" in person_columns else "NULL")
            select.append("ZDISPLAYNAME" if "ZDISPLAYNAME" in person_columns else "NULL")
            select.append("ZMERGETARGETPERSON" if "ZMERGETARGETPERSON" in person_columns else "NULL")
            persons = {
                int(pk): (_text(uuid), _text(full) or _text(display), target)
                for pk, uuid, full, display, target in con.execute(f"SELECT {', '.join(select)} FROM ZPERSON")
                if isinstance(pk, int)
            }
            for pk, (uuid, name, target) in persons.items():
                resolved = persons.get(target) if isinstance(target, int) and target != pk else None
                if resolved is not None and resolved[1] and resolved[0]:
                    named[pk] = (resolved[0], resolved[1])
                elif name and uuid:
                    named[pk] = (uuid, name)
    counts: dict[int, int] = {}
    people: dict[int, set[str]] = {}
    names: dict[int, set[str]] = {}
    person_column = "ZPERSONFORFACE" if "ZPERSONFORFACE" in face_columns else "NULL"
    for asset_pk, person_pk in con.execute(f"SELECT ZASSETFORFACE, {person_column} FROM ZDETECTEDFACE"):
        if not isinstance(asset_pk, int):
            continue
        counts[asset_pk] = counts.get(asset_pk, 0) + 1
        person = named.get(person_pk) if isinstance(person_pk, int) else None
        if person is not None:
            people.setdefault(asset_pk, set()).add(person[0])
            names.setdefault(asset_pk, set()).add(person[1])
    return (
        counts,
        {pk: sorted(ids) for pk, ids in people.items()},
        {pk: sorted(found) for pk, found in names.items()},
    )


def _line(
    values: dict[str, Any],
    albums: dict[int, list[str]],
    faces: dict[int, int],
    people: dict[int, list[str]],
    names: dict[int, list[str]],
    counts: dict[str, int],
    timezone: str | None,
    tier: int,
) -> dict[str, Any] | None:
    if values.get("ZTRASHEDSTATE"):
        _count(counts, "skipped_trashed")
        return None
    taken = _datetime(values.get("ZDATECREATED"))
    if taken is None:
        _count(counts, "skipped_no_timestamp")
        return None
    if taken.year < PLACEHOLDER_BEFORE_YEAR:
        _count(counts, "skipped_placeholder_date")
        return None
    pk = int(values["Z_PK"])
    uuid = _text(values.get("ZUUID")) or f"row:{pk}"
    file_name = _text(values.get("ZORIGINALFILENAME")) or _text(values.get("ZFILENAME"))
    kind = values.get("ZKIND")
    subtype = values.get("ZKINDSUBTYPE")
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": uuid,
        "asset_id": uuid,
        "library": NAME,
    }
    if file_name:
        payload["file_name"] = file_name
    payload["media"] = "video" if kind == 1 else "image"
    lat, lon = _number(values.get("ZLATITUDE")), _number(values.get("ZLONGITUDE"))
    if lat is not None and lon is not None and lat != NO_LOCATION and -90 <= lat <= 90 and -180 <= lon <= 180:
        payload["lat"], payload["lon"] = lat, lon
    width, height = _number(values.get("ZWIDTH")), _number(values.get("ZHEIGHT"))
    if width and height and width > 0 and height > 0:
        payload["width"], payload["height"] = int(width), int(height)
    duration = _number(values.get("ZDURATION"))
    if kind == 1 and duration is not None and duration > 0:
        payload["duration_s"] = _round(duration)
    if subtype == LIVE_PHOTO:
        payload["live_photo"] = True
    imported_by = values.get("ZIMPORTEDBY")
    bundle = _text(values.get("ZIMPORTEDBYBUNDLEIDENTIFIER"))
    payload["provenance"] = _provenance(subtype, imported_by, bundle)
    payload["faces"] = faces.get(pk, 0)
    if pk in people:
        payload["people"] = people[pk]
    if values.get("ZFAVORITE"):
        payload["favorite"] = True
    if values.get("ZHIDDEN"):
        payload["hidden"] = True
    if pk in albums:
        payload["albums"] = albums[pk]
    extra: dict[str, Any] = {}
    uti = _text(values.get("ZUNIFORMTYPEIDENTIFIER"))
    if uti:
        extra["uti"] = uti
    if isinstance(imported_by, int) and not isinstance(imported_by, bool):
        extra["imported_by"] = imported_by
    if bundle:
        extra["imported_by_bundle"] = bundle
    if pk in names:
        extra["faces"] = names[pk]
    if extra:
        payload["extra"] = extra
    return {
        "at": _stamp(taken),
        "end": None,
        "tz": _zone(values.get("ZTIMEZONENAME")) or timezone,
        "source": NAME,
        "kind": KIND,
        "tier": tier,
        "payload": payload,
    }


def _provenance(subtype: object, imported_by: object, bundle: str) -> str:
    if subtype == SCREENSHOT:
        return "screenshot"
    if subtype == LIVE_PHOTO or subtype in VIDEO_KINDS or bundle == CAMERA_BUNDLE:
        return "camera"
    if imported_by in CAMERA_IMPORTS:
        return "camera"
    if imported_by in RECEIVED_IMPORTS:
        return "received"
    return "other"


def _zone(value: object) -> str | None:
    """An IANA zone name (`Europe/Oslo`, `UTC`); the store's `GMT+0200` is an offset, not a zone."""
    name = _text(value)
    if not name or " " in name:
        return None
    return name if "/" in name or name in ("UTC", "Etc/UTC") else None


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _text(value: object) -> str:
    if isinstance(value, bytes | bytearray | memoryview):
        try:
            return bytes(value).decode("utf-8").strip()
        except UnicodeDecodeError:
            return ""
    return value.strip() if isinstance(value, str) else ""


def _number(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def _round(value: int | float) -> int | float:
    rounded = round(float(value), 3)
    return int(rounded) if rounded == int(rounded) else rounded


def _datetime(seconds_since_2001: object) -> datetime | None:
    """Arithmetic from the epoch, not `fromtimestamp`: Windows refuses instants before 1970."""
    number = _number(seconds_since_2001)
    if number is None:
        return None
    try:
        return APPLE_EPOCH_UTC + timedelta(seconds=int(number))
    except (OverflowError, ValueError):
        return None


def _stamp(when: datetime) -> str:
    return when.astimezone(UTC).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"
