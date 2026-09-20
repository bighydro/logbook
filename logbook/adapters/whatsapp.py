"""WhatsApp (iOS) → message/v1 (RFC 0008).

Reads the ChatStorage.sqlite an iPhone keeps in the WhatsApp app group (in an unencrypted
Finder/iTunes backup it is the file named 7c7fba66680ef796b916b067077cc246adacf01d, under the
group.net.whatsapp.WhatsApp.shared domain). It is a Core Data store; four tables matter:

    ZWACHATSESSION  (Z_PK, ZCONTACTJID, ZPARTNERNAME, ZSESSIONTYPE: 0 one-to-one, 1 group,
                     2 broadcast list, 3 status)
    ZWAMESSAGE      (Z_PK, ZCHATSESSION → ZWACHATSESSION, ZISFROMME, ZMESSAGEDATE seconds since
                     2001-01-01 UTC, ZTEXT, ZMESSAGETYPE, ZFROMJID, ZGROUPMEMBER → ZWAGROUPMEMBER,
                     ZSTANZAID, ZMEDIAITEM → ZWAMEDIAITEM)
    ZWAMEDIAITEM    (Z_PK, ZMEDIALOCALPATH relative to the Message/ folder beside the database,
                     ZTITLE, ZFILESIZE)
    ZWAGROUPMEMBER  (Z_PK, ZMEMBERJID, ZCONTACTNAME)

One line per message: kind `message`, tier 2, source `whatsapp`, `at` the message's own timestamp
in UTC. `raw_id` is `<chat jid>:<ZSTANZAID>`, the source's stable id, so re-adding a later backup
appends nothing already logged; a row with no stanza id is keyed `<chat jid>:pk<Z_PK>` and counted.
The sender is source-native (RFC 0006 `ref`): a `digits@s.whatsapp.net` JID is `{phone, +digits}`
through the shared `phone` module, so it meets the address book on the same ref; anything else
(a `@lid`, an odd JID) is `{handle, <jid>}`. Names are never resolved here; `chat.name` is the
source's own display name.

Media, v1 rule: the file is never copied into the record — the §1.1 attachment store is not built
yet. When ZMEDIALOCALPATH names a file that exists under `<db folder>/Message/`, its SHA-256 and
size are recorded under `extra.media` so a later attach pass can find the bytes by digest; when it
does not, `extra.media_missing` is true. `payload.media` is never set. `LOGBOOK_WHATSAPP_HASH_MEDIA=0`
skips the hashing (a decade of media is many gigabytes) and records only the local path.

Built for the real store, about a million rows: one SELECT streamed through the cursor, chats and
group members joined by SQLite, nothing accumulated. Pure: opened `mode=ro`, `immutable=1` (no
lock, no journal beside the source), no network.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from . import phone

NAME = "whatsapp"
KIND = "message"
TIER = 2
SCHEMA = "message/v1"

HASH_MEDIA_ENV = "LOGBOOK_WHATSAPP_HASH_MEDIA"
SQLITE_HEADER = b"SQLite format 3\x00"
REQUIRED_TABLES = frozenset({"ZWACHATSESSION", "ZWAMESSAGE"})
MEDIA_FOLDER = "Message"
APPLE_EPOCH = 978_307_200  # 2001-01-01T00:00:00Z; ZMESSAGEDATE counts from it
EARLIEST_DATE = 300_000_000  # 2010-07-07: WhatsApp did not exist before; anything earlier is garbage
PHONE_DOMAIN = "s.whatsapp.net"
STATUS_JID = "status@broadcast"
SESSION_STATUS = 3
SESSION_BROADCAST = 2
SESSION_TYPES = {0: "direct", 1: "group", SESSION_BROADCAST: "group"}
TEXT_TYPE = 0
MEDIA_KINDS = {
    1: "image",
    2: "video",
    3: "voice",
    4: "contact",
    5: "location",
    7: "link",
    8: "document",
    11: "gif",
    15: "sticker",
}
CHUNK = 1 << 20

QUERY = """
SELECT m.Z_PK, m.ZISFROMME, m.ZMESSAGETYPE, m.ZMESSAGEDATE, m.ZTEXT, m.ZFROMJID, m.ZSTANZAID,
       c.Z_PK, c.ZCONTACTJID, c.ZPARTNERNAME, c.ZSESSIONTYPE,
       g.ZMEMBERJID,
       i.Z_PK, i.ZMEDIALOCALPATH, i.ZTITLE
FROM ZWAMESSAGE AS m
LEFT JOIN ZWACHATSESSION AS c ON c.Z_PK = m.ZCHATSESSION
LEFT JOIN ZWAGROUPMEMBER AS g ON g.Z_PK = m.ZGROUPMEMBER
LEFT JOIN ZWAMEDIAITEM AS i ON i.Z_PK = m.ZMEDIAITEM
ORDER BY m.Z_PK
"""


def sniff(path: Path) -> bool:
    """A SQLite file with both ZWACHATSESSION and ZWAMESSAGE tables. Never raises."""
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
    """One message/v1 line per ZWAMESSAGE row, in Z_PK order, streamed.

    `since` is RFC3339 UTC; rows with `at` before it are not yielded. `counts` tallies what was
    left out — `skipped_status` (status chats), `skipped_bad_date` (no date, or one before
    2010), `skipped_no_chat` (no session row), `skipped_system_event` (neither text nor a known
    type: group joins, calls, …) — and what was noted: `no_stanza_id` (keyed by row id instead),
    `media_hashed`, `media_missing`."""
    counts = counts if counts is not None else {}
    path = Path(path)
    media_root = path.resolve().parent / MEDIA_FOLDER
    hash_media = os.environ.get(HASH_MEDIA_ENV, "1").strip() != "0"
    con = _open(path)
    try:
        for row in con.execute(QUERY):  # the cursor streams; a million rows never sit in memory
            draft = _draft(row, media_root, hash_media, counts)
            if draft is not None and not (since and draft["at"] < since):
                yield draft
    finally:
        con.close()


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _draft(
    row: tuple[Any, ...], media_root: Path, hash_media: bool, counts: dict[str, int]
) -> dict[str, Any] | None:
    (
        pk,
        from_me,
        message_type,
        date,
        text,
        from_jid,
        stanza_id,
        chat_pk,
        chat_jid,
        chat_name,
        session_type,
        member_jid,
        media_pk,
        local_path,
        title,
    ) = row
    if chat_pk is None or not isinstance(chat_jid, str) or not chat_jid:
        _count(counts, "skipped_no_chat")
        return None
    if session_type == SESSION_STATUS or chat_jid == STATUS_JID:
        _count(counts, "skipped_status")
        return None
    at = _rfc3339(date)
    if at is None:
        _count(counts, "skipped_bad_date")
        return None
    body = text if isinstance(text, str) and text.strip() else None
    media_kind = MEDIA_KINDS.get(message_type) if isinstance(message_type, int) else None
    known = message_type == TEXT_TYPE or media_kind is not None
    if body is None and not known:
        _count(counts, "skipped_system_event")
        return None
    chat_type = SESSION_TYPES.get(session_type) if isinstance(session_type, int) else None
    if chat_type is None:
        chat_type = "group" if chat_jid.endswith("@g.us") else "direct"
    chat: dict[str, Any] = {"id": chat_jid, "type": chat_type}
    if isinstance(chat_name, str) and chat_name.strip():
        chat["name"] = chat_name
    if isinstance(stanza_id, str) and stanza_id:
        raw_id = f"{chat_jid}:{stanza_id}"
    else:
        raw_id = f"{chat_jid}:pk{pk}"
        _count(counts, "no_stanza_id")
    payload: dict[str, Any] = {"schema": SCHEMA, "raw_id": raw_id, "chat": chat, "from_me": bool(from_me)}
    if not from_me:
        sender_jid = chat_jid if chat_type == "direct" else None
        for candidate in (member_jid, from_jid):
            if sender_jid is None and isinstance(candidate, str) and candidate:
                sender_jid = candidate
        if sender_jid is not None:
            payload["sender"] = _ref(sender_jid)
    if body is not None:
        payload["text"] = body
    if media_kind is not None:
        payload["media_kind"] = media_kind
    extra: dict[str, Any] = {}
    if not known and isinstance(message_type, int):
        extra["message_type"] = message_type
    if session_type == SESSION_BROADCAST:
        extra["broadcast_list"] = True
    if media_pk is not None:
        _media(extra, local_path, title, media_root, hash_media, counts)
    if extra:
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


def _ref(jid: str) -> dict[str, str]:
    """`4790000001@s.whatsapp.net` → phone `+4790000001`; anything else is a handle, as is."""
    user, _, domain = jid.partition("@")
    if domain == PHONE_DOMAIN and user.isdigit() and user.isascii():
        value, unnormalised = phone.normalise("+" + user, "")
        if not unnormalised:
            return {"kind": "phone", "value": value}
    return {"kind": "handle", "value": jid}


def _media(
    extra: dict[str, Any],
    local_path: object,
    title: object,
    media_root: Path,
    hash_media: bool,
    counts: dict[str, int],
) -> None:
    """extra.media = {local_path, title?, sha256?, bytes?}; extra.media_missing when the file is not there.

    The stored path is POSIX-relative to `Message/`; it is resolved with pathlib parts and must stay
    inside that folder (no `..`, no absolute path), else it counts as missing."""
    media: dict[str, Any] = {}
    if isinstance(local_path, str) and local_path:
        media["local_path"] = local_path
    if isinstance(title, str) and title:
        media["title"] = title
    file = _inside(media_root, local_path) if "local_path" in media else None
    if file is None or not file.is_file():
        extra["media_missing"] = True
        _count(counts, "media_missing")
    elif hash_media:
        digest, size = _sha256(file)
        media["sha256"] = digest
        media["bytes"] = size
        _count(counts, "media_hashed")
    if media:
        extra["media"] = media


def _inside(root: Path, local_path: object) -> Path | None:
    parts = PurePosixPath(str(local_path)).parts
    if not parts or parts[0] == "/" or any(part in ("..", "") for part in parts):
        return None
    candidate = root.joinpath(*parts)
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
