"""iOS/macOS Messages → message/v1 (RFC 0008).

Reads the sms.db that iOS keeps in /var/mobile/Library/SMS (in an unencrypted Finder/iTunes backup
it is the file named 3d0d7e5fb2ce288813306e4d4636395e047a3d28) and macOS keeps as
~/Library/Messages/chat.db. Seven tables matter:

    message                 (ROWID, guid, text, attributedBody, handle_id → handle, date, is_from_me,
                             service, associated_message_type, reply_to_guid, item_type,
                             cache_has_attachments)
    handle                  (ROWID, id: a phone number or an email address, service)
    chat                    (ROWID, guid, chat_identifier, display_name, style: 43 group, 45 direct)
    chat_message_join       (chat_id, message_id)
    chat_handle_join        (chat_id, handle_id)
    attachment              (ROWID, guid, filename, mime_type, total_bytes)
    message_attachment_join (message_id, attachment_id)

One line per message: kind `message`, tier 2, source `imessage`, `at` the message's own timestamp in
UTC. `raw_id` is the message `guid`, the source's stable id, so re-adding a later backup appends
nothing already logged; a row with no guid is keyed `row<ROWID>` and counted. The sender is
source-native (RFC 0006 `ref`): a handle that is a number is `{phone, +digits}` through the shared
`phone` module, so it meets the address book on the same ref; one with an `@` is `{email,
lower-cased}`; anything else (an alphanumeric SMS sender id) is `{handle, <id>}`. Names are never
resolved here; `chat.name` is the source's own display name. Apple's handle table carries no name,
so `sender.name` is normally absent; a store whose handle table has a `display_name` column (none
of Apple's do today) fills it from there.

Three traps the store sets. (1) Since iOS 16 `text` is often NULL and the body lives in
`attributedBody`, an NSArchiver typedstream: the plain string is the one NSString in it, its
length one byte or 0x81 followed by a little-endian uint16. `text` wins when present. (2) Tapbacks
(`associated_message_type` 2000 to 2005 adds one, 3000 to 3005 removes it) are reactions, not messages
(RFC 0008 rule 1), and `item_type != 0` marks a group event (rename, join, leave); both are skipped
and counted. (3) `date` is nanoseconds since 2001-01-01 on a modern store and seconds on an old
one; a value below 1e11 is seconds. Anything before 300000000 seconds (2010) is garbage.

Media, v1 rule: the file is never copied into the record — the §1.1 attachment store is not built
yet. The `filename` column is a path like `~/Library/SMS/Attachments/ab/12/<guid>/<name>`; the part
after `Attachments` is looked up under `<db folder>/Attachments/`, with pathlib parts, and must stay
inside that folder. When the file exists its SHA-256 and size are recorded under `extra.media` so
a later attach pass can find the bytes by digest; when it does not, `extra.media_missing` is true.
`payload.media` is never set. A message with several attachments puts the first under `extra.media`
(and its kind in `media_kind`) and the rest under `extra.more_media`. `LOGBOOK_IMESSAGE_HASH_MEDIA=0`
skips the hashing and records only the stored path.

Built for the real store, hundreds of thousands of rows: one SELECT streamed through the cursor,
chat, handle and attachments joined by SQLite, rows grouped by message as they arrive. Pure:
opened `mode=ro`, `immutable=1` (no lock, no journal beside the source), no network.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from itertools import groupby
from pathlib import Path, PurePosixPath
from typing import Any

from . import phone

NAME = "imessage"
KIND = "message"
TIER = 2
SCHEMA = "message/v1"

HASH_MEDIA_ENV = "LOGBOOK_IMESSAGE_HASH_MEDIA"
SQLITE_HEADER = b"SQLite format 3\x00"
REQUIRED_TABLES = frozenset({"message", "handle", "chat", "chat_message_join"})
MEDIA_FOLDER = "Attachments"
APPLE_EPOCH = 978_307_200  # 2001-01-01T00:00:00Z; message.date counts from it
NANOSECONDS_FROM = 100_000_000_000  # 1e11: a date this large is nanoseconds, below it seconds
EARLIEST_DATE = 300_000_000  # 2010-07-07 in seconds since 2001; anything earlier is garbage
GROUP_STYLE = 43
TAPBACK_ADD = range(2000, 2006)
TAPBACK_REMOVE = range(3000, 3006)
OBJECT_REPLACEMENT = "\ufffc"  # what `text` holds when the message is only an attachment
NSSTRING = b"NSString"
STRING_TAG = b"+"
TWO_BYTE_LENGTH = 0x81
MEDIA_KINDS = {"image": "image", "video": "video", "audio": "voice"}
MEDIA_TYPES = {"text/vcard": "contact", "application/pdf": "document"}
CHUNK = 1 << 20

HANDLE_NAME_COLUMN = "display_name"  # not in Apple's handle table; honoured when a store has it
QUERY = """
SELECT m.ROWID, m.guid, m.text, m.attributedBody, m.date, m.is_from_me, m.service,
       m.associated_message_type, m.reply_to_guid, m.item_type,
       h.id,
       c.ROWID, c.chat_identifier, c.display_name, c.style,
       a.ROWID, a.filename, a.mime_type,
       {handle_name}
FROM message AS m
LEFT JOIN handle AS h ON h.ROWID = m.handle_id
LEFT JOIN chat_message_join AS cm ON cm.message_id = m.ROWID
LEFT JOIN chat AS c ON c.ROWID = cm.chat_id
LEFT JOIN message_attachment_join AS ma ON ma.message_id = m.ROWID
LEFT JOIN attachment AS a ON a.ROWID = ma.attachment_id
ORDER BY m.ROWID, c.ROWID, a.ROWID
"""


def sniff(path: Path) -> bool:
    """A SQLite file with the message, handle, chat and chat_message_join tables. Never raises."""
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


def _query(con: sqlite3.Connection) -> str:
    """QUERY with the handle's name column when the store has one, NULL in its place when not."""
    columns = {str(row[1]) for row in con.execute("PRAGMA table_info(handle)")}
    handle_name = f"h.{HANDLE_NAME_COLUMN}" if HANDLE_NAME_COLUMN in columns else "NULL"
    return QUERY.format(handle_name=handle_name)


def run(
    path: Path, since: str | None = None, counts: dict[str, int] | None = None
) -> Iterator[dict[str, Any]]:
    """One message/v1 line per message row, in ROWID order, streamed.

    `since` is RFC3339 UTC; rows with `at` before it are not yielded. `counts` tallies what was
    left out — `skipped_reaction` (tapbacks), `skipped_system_event` (group renames, joins),
    `skipped_bad_date` (no date, or one before 2010), `skipped_no_chat` (no chat_message_join row),
    `skipped_no_body` (no text and no attachment) — and what was noted: `no_guid` (keyed by row id
    instead), `media_hashed`, `media_missing`."""
    counts = counts if counts is not None else {}
    path = Path(path)
    media_root = path.resolve().parent / MEDIA_FOLDER
    hash_media = os.environ.get(HASH_MEDIA_ENV, "1").strip() != "0"
    con = _open(path)
    try:
        cursor = con.execute(_query(con))  # the cursor streams; only one message's rows sit in memory
        for _rowid, rows in groupby(cursor, key=lambda row: row[0]):
            draft = _draft(list(rows), media_root, hash_media, counts)
            if draft is not None and not (since and draft["at"] < since):
                yield draft
    finally:
        con.close()


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _draft(
    rows: list[tuple[Any, ...]], media_root: Path, hash_media: bool, counts: dict[str, int]
) -> dict[str, Any] | None:
    """One message from its joined rows (one per attachment, times one per chat; the first chat wins)."""
    (
        rowid,
        guid,
        text,
        attributed_body,
        date,
        from_me,
        service,
        associated_type,
        reply_to_guid,
        item_type,
        handle,
        chat_pk,
        chat_id,
        chat_name,
        style,
    ) = rows[0][:15]
    if isinstance(associated_type, int) and (
        associated_type in TAPBACK_ADD or associated_type in TAPBACK_REMOVE
    ):
        _count(counts, "skipped_reaction")
        return None
    if isinstance(item_type, int) and item_type != 0:
        _count(counts, "skipped_system_event")
        return None
    at = _rfc3339(date)
    if at is None:
        _count(counts, "skipped_bad_date")
        return None
    if chat_pk is None or not isinstance(chat_id, str) or not chat_id:
        _count(counts, "skipped_no_chat")
        return None
    body = _body(text, attributed_body)
    attachments: list[tuple[Any, ...]] = []
    seen: set[int] = set()
    for row in rows:
        if row[15] is not None and row[15] not in seen and row[11] == chat_pk:
            seen.add(row[15])
            attachments.append(row[15:18])
    if body is None and not attachments:
        _count(counts, "skipped_no_body")
        return None
    chat: dict[str, Any] = {"id": chat_id, "type": "group" if style == GROUP_STYLE else "direct"}
    if isinstance(chat_name, str) and chat_name.strip():
        chat["name"] = chat_name
    if isinstance(guid, str) and guid:
        raw_id = guid
    else:
        raw_id = f"row{rowid}"
        _count(counts, "no_guid")
    payload: dict[str, Any] = {"schema": SCHEMA, "raw_id": raw_id, "chat": chat, "from_me": bool(from_me)}
    if not from_me and isinstance(handle, str) and handle.strip():
        payload["sender"] = _ref(handle)
        handle_name = rows[0][18]
        if isinstance(handle_name, str) and handle_name.strip():
            payload["sender"]["name"] = handle_name.strip()
    if body is not None:
        payload["text"] = body
    if isinstance(reply_to_guid, str) and reply_to_guid:
        payload["reply_to"] = reply_to_guid
    extra: dict[str, Any] = {}
    if isinstance(service, str) and service:
        extra["service"] = service
    if isinstance(associated_type, int) and associated_type != 0:
        extra["associated_message_type"] = associated_type
    for index, (_pk, filename, mime_type) in enumerate(attachments):
        item = _media(filename, mime_type, media_root, hash_media, counts)
        if index == 0:
            payload["media_kind"] = item.pop("media_kind")
            extra.update(item)
        else:
            extra.setdefault("more_media", []).append(item)
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


def _body(text: object, attributed_body: object) -> str | None:
    """The `text` column when it says something, else the string inside `attributedBody`."""
    if isinstance(text, str) and text.replace(OBJECT_REPLACEMENT, "").strip():
        return text
    if isinstance(attributed_body, bytes):
        extracted = _typedstream_string(attributed_body)
        if extracted is not None and extracted.replace(OBJECT_REPLACEMENT, "").strip():
            return extracted
    return None


def _typedstream_string(blob: bytes) -> str | None:
    """The NSString inside an NSArchiver typedstream: after the `NSString` class name comes a short
    header ending in `+` (the raw-bytes tag), then the length — one byte, or 0x81 and a little-endian
    uint16 — then that many UTF-8 bytes."""
    marker = blob.find(NSSTRING)
    if marker < 0:
        return None
    tag = blob.find(STRING_TAG, marker + len(NSSTRING), marker + len(NSSTRING) + 8)
    if tag < 0:
        return None
    at = tag + 1
    if at >= len(blob):
        return None
    if blob[at] == TWO_BYTE_LENGTH:
        length = int.from_bytes(blob[at + 1 : at + 3], "little")
        at += 3
    else:
        length = blob[at]
        at += 1
    data = blob[at : at + length]
    if len(data) != length:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _ref(handle: str) -> dict[str, str]:
    """`+4790000001` → phone; `ola@example.org` → email, lower-cased; `Telenor` → handle, as is."""
    value, unnormalised = phone.normalise(handle, "")
    if not unnormalised:
        return {"kind": "phone", "value": value}
    if "@" in handle:
        return {"kind": "email", "value": handle.strip().lower()}
    return {"kind": "handle", "value": handle}


def _media(
    filename: object, mime_type: object, media_root: Path, hash_media: bool, counts: dict[str, int]
) -> dict[str, Any]:
    """{media_kind, media: {local_path, media_type?, sha256?, bytes?}, media_missing?}.

    The stored path is looked up by the part after its `Attachments` folder, resolved with pathlib
    parts under `<db folder>/Attachments/`; it must stay inside (no `..`), else it counts as
    missing."""
    media: dict[str, Any] = {}
    if isinstance(filename, str) and filename:
        media["local_path"] = filename
    if isinstance(mime_type, str) and mime_type:
        media["media_type"] = mime_type
    item: dict[str, Any] = {"media_kind": _media_kind(mime_type)}
    file = _inside(media_root, filename) if "local_path" in media else None
    if file is None or not file.is_file():
        item["media_missing"] = True
        _count(counts, "media_missing")
    elif hash_media:
        digest, size = _sha256(file)
        media["sha256"] = digest
        media["bytes"] = size
        _count(counts, "media_hashed")
    if media:
        item["media"] = media
    return item


def _media_kind(mime_type: object) -> str:
    if not isinstance(mime_type, str):
        return "other"
    kind = MEDIA_TYPES.get(mime_type.lower())
    if kind is None:
        kind = MEDIA_KINDS.get(mime_type.lower().partition("/")[0], "other")
    return kind


def _inside(root: Path, filename: object) -> Path | None:
    parts = PurePosixPath(str(filename)).parts
    if MEDIA_FOLDER not in parts:
        return None
    below = parts[parts.index(MEDIA_FOLDER) + 1 :]
    if not below or any(part in ("..", "", "/") for part in below):
        return None
    candidate = root.joinpath(*below)
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _sha256(file: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with file.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def _rfc3339(date: object) -> str | None:
    """Nanoseconds since 2001 on a modern store, seconds on an old one; below 2010 is garbage."""
    if not isinstance(date, int | float) or isinstance(date, bool):
        return None
    seconds = date / 1_000_000_000 if date >= NANOSECONDS_FROM else date
    if seconds < EARLIEST_DATE:
        return None
    try:
        return datetime.fromtimestamp(APPLE_EPOCH + int(seconds), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return None
