"""Apple Notes (iOS) → note/v1 (RFC 0010).

Reads the NoteStore.sqlite an iPhone keeps in the Notes app group (in an unencrypted Finder/iTunes
backup it is the file named 4f98687d8ab0d6d1a371110e6b7300f6e465bef2, under the
group.com.apple.notes domain). It is a Core Data store; two tables matter:

    ZICCLOUDSYNCINGOBJECT  one table for every synced object — notes, folders, attachments —
                           so most columns are null on most rows. Notes use Z_PK, ZIDENTIFIER,
                           ZTITLE1, ZSNIPPET, ZCREATIONDATE3 and ZMODIFICATIONDATE1 (seconds
                           since 2001-01-01 UTC), ZFOLDER → the folder row, whose name is
                           ZTITLE2, ZMARKEDFORDELETION, ZISPASSWORDPROTECTED
    ZICNOTEDATA            (Z_PK, ZNOTE → ZICCLOUDSYNCINGOBJECT.Z_PK, ZDATA BLOB)

A note is a ZICCLOUDSYNCINGOBJECT row with a ZICNOTEDATA record. One note/v1 line per note: kind
`note`, tier 2, source `ios-notes`, `at` the note's creation time in UTC, `modified_at` its last
modification. `raw_id` is `<ZIDENTIFIER>@<modified_at>` (RFC 0010 rule 2): the same note edited and
imported again is a new line, the same note unchanged appends nothing.

The body: ZDATA is a gzip stream holding a protobuf archive. A minimal decoder (varints; wire types
0, 1, 2 and 5; every length-delimited field read as a nested message where the path needs one and
as a string at the leaf) walks field 2 (Document) → 3 (Note) → 2 (note_text), which is the plain
text of the whole note, title line included. A body that will not decode falls back to ZSNIPPET
and is counted; when neither yields text the note is skipped and counted. A first line equal to
ZTITLE1 is stripped, so `title` and `text` do not repeat each other. Formatting, checklists and
attachments are not interpreted in v1 (RFC 0010 rule 3 is a follow-up): the text is emitted as is.

Password-protected notes are skipped and counted, their body being encrypted. Notes marked for
deletion (still in the store until the Recently Deleted folder is emptied) are lines with
`extra.deleted` true, and counted. Pure: opened `mode=ro`, `immutable=1` (no lock, no journal
beside the source), one SELECT streamed through the cursor, no network.
"""

from __future__ import annotations

import gzip
import sqlite3
import zlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

NAME = "ios-notes"
KIND = "note"
TIER = 2
SCHEMA = "note/v1"

SQLITE_HEADER = b"SQLite format 3\x00"
REQUIRED_TABLES = frozenset({"ZICCLOUDSYNCINGOBJECT", "ZICNOTEDATA"})
APPLE_EPOCH = 978_307_200  # 2001-01-01T00:00:00Z; ZCREATIONDATE3/ZMODIFICATIONDATE1 count from it
EARLIEST_DATE = 300_000_000  # 2010-07-07: anything earlier is a placeholder, not a creation time
TEXT_PATH = (2, 3, 2)  # Document → Note → note_text

WIRE_VARINT, WIRE_FIXED64, WIRE_LENGTH, WIRE_FIXED32 = 0, 1, 2, 5
FIXED_WIDTH = {WIRE_FIXED64: 8, WIRE_FIXED32: 4}

QUERY = """
SELECT n.Z_PK, n.ZIDENTIFIER, n.ZTITLE1, n.ZSNIPPET, n.ZCREATIONDATE3, n.ZMODIFICATIONDATE1,
       n.ZMARKEDFORDELETION, n.ZISPASSWORDPROTECTED, f.ZTITLE2, d.ZDATA
FROM ZICNOTEDATA AS d
JOIN ZICCLOUDSYNCINGOBJECT AS n ON n.Z_PK = d.ZNOTE
LEFT JOIN ZICCLOUDSYNCINGOBJECT AS f ON f.Z_PK = n.ZFOLDER
ORDER BY n.Z_PK, d.Z_PK
"""


def sniff(path: Path) -> bool:
    """A SQLite file with both ZICCLOUDSYNCINGOBJECT and ZICNOTEDATA tables. Never raises."""
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
        return _tables(con) >= REQUIRED_TABLES
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


def run(
    path: Path, since: str | None = None, counts: dict[str, int] | None = None
) -> Iterator[dict[str, Any]]:
    """One note/v1 line per note, in Z_PK order, streamed.

    `since` is RFC3339 UTC; notes created before it are not yielded. `counts` tallies what was
    left out — `skipped_password_protected`, `skipped_bad_date` (no creation date, or one before
    2010), `skipped_no_text` (neither the archive nor the snippet had any) — and what was noted:
    `deleted` (marked for deletion, still a line), `body_from_snippet` (the archive would not
    decode), `no_identifier` (keyed by row id instead)."""
    counts = counts if counts is not None else {}
    con = _open(Path(path))
    try:
        for row in con.execute(QUERY):  # the cursor streams; nothing is accumulated
            draft = _draft(row, counts)
            if draft is not None and not (since and draft["at"] < since):
                yield draft
    finally:
        con.close()


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _draft(row: tuple[Any, ...], counts: dict[str, int]) -> dict[str, Any] | None:
    pk, identifier, title, snippet, created, modified, deleted, locked, folder, data = row
    at = _rfc3339(created)
    if at is None:
        _count(counts, "skipped_bad_date")
        return None
    if locked:
        _count(counts, "skipped_password_protected")
        return None
    extra: dict[str, Any] = {"pk": pk}
    body = _note_text(data)
    if body is None:
        body = snippet if isinstance(snippet, str) else ""
        extra["body_from_snippet"] = True
        _count(counts, "body_from_snippet")
    title = title.strip() if isinstance(title, str) else ""
    text = _strip_title(body, title)
    if not text.strip():
        _count(counts, "skipped_no_text")
        return None
    modified_at = _rfc3339(modified)
    if isinstance(identifier, str) and identifier:
        key = identifier
    else:
        key = f"pk{pk}"
        _count(counts, "no_identifier")
    payload: dict[str, Any] = {"schema": SCHEMA, "raw_id": f"{key}@{modified_at or at}"}
    if title and title != text:
        payload["title"] = title
    payload["text"] = text
    if modified_at is not None:
        payload["modified_at"] = modified_at
    if isinstance(folder, str) and folder.strip():
        payload["folder"] = folder
    if deleted:
        extra["deleted"] = True
        _count(counts, "deleted")
    payload["extra"] = extra
    return {
        "at": at,
        "end": None,
        "tz": None,  # the logbook's own
        "source": NAME,
        "kind": KIND,
        "tier": TIER,
        "payload": payload,
    }


def _strip_title(body: str, title: str) -> str:
    """Apple writes the title as the body's first line; drop it when it is exactly the title.

    A body that is nothing but the title keeps it: the note's text is the title then."""
    if not title:
        return body
    first, sep, rest = body.partition("\n")
    if sep and first.strip() == title and rest.strip():
        return rest
    return body


# -- the archive: gzip around a protobuf message --------------------------------------------


def _note_text(data: object) -> str | None:
    """The string at field path 2 → 3 → 2 of the gunzipped archive, or None when anything fails."""
    if not isinstance(data, bytes | memoryview):
        return None
    try:
        message = gzip.decompress(bytes(data))
        for field in TEXT_PATH[:-1]:
            message = _first(message, field)
        return _first(message, TEXT_PATH[-1]).decode("utf-8")
    except (OSError, EOFError, zlib.error, ValueError, LookupError):
        return None


def _first(message: bytes, wanted: int) -> bytes:
    """The bytes of the first length-delimited field numbered `wanted`; ValueError when absent."""
    for field, wire_type, value in _fields(message):
        if field == wanted and wire_type == WIRE_LENGTH:
            assert isinstance(value, bytes)
            return value
    raise ValueError(f"no length-delimited field {wanted}")


def _fields(message: bytes) -> Iterator[tuple[int, int, int | bytes]]:
    """(field number, wire type, value) for each field; ValueError on a malformed message."""
    i, n = 0, len(message)
    while i < n:
        key, i = _varint(message, i)
        field, wire_type = key >> 3, key & 0x7
        if field == 0:
            raise ValueError("field number 0")
        if wire_type == WIRE_VARINT:
            value, i = _varint(message, i)
        elif wire_type in FIXED_WIDTH:
            width = FIXED_WIDTH[wire_type]
            if i + width > n:
                raise ValueError("truncated fixed-width field")
            value = int.from_bytes(message[i : i + width], "little")
            i += width
        elif wire_type == WIRE_LENGTH:
            length, i = _varint(message, i)
            if i + length > n:
                raise ValueError("truncated length-delimited field")
            yield field, wire_type, message[i : i + length]
            i += length
            continue
        else:
            raise ValueError(f"wire type {wire_type}")  # 3 and 4 (groups) are long gone
        yield field, wire_type, value


def _varint(message: bytes, i: int) -> tuple[int, int]:
    value, shift = 0, 0
    while True:
        if i >= len(message):
            raise ValueError("truncated varint")
        byte = message[i]
        i += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, i
        shift += 7
        if shift > 63:
            raise ValueError("varint too long")


def _rfc3339(seconds_since_2001: object) -> str | None:
    if not isinstance(seconds_since_2001, int | float) or isinstance(seconds_since_2001, bool):
        return None
    if seconds_since_2001 < EARLIEST_DATE:
        return None
    try:
        return datetime.fromtimestamp(APPLE_EPOCH + int(seconds_since_2001), UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except (OverflowError, OSError, ValueError):
        return None
