"""Beeper (iOS) → message/v1 (RFC 0008): what the phone's Matrix cache holds in clear.

Beeper bridges WhatsApp, Telegram, Instagram, Facebook and the rest into one Matrix account, and the
iPhone keeps a cache of it: BeeperStore.sqlite in the group.beeper.chat.ios container (in a
Finder/iTunes backup, the file `BeeperStore.sqlite` of the AppDomainGroup-group.beeper.chat.ios
domain). It is a Core Data store. Four tables matter:

    ZROOMITEMMO          one row per room: ZROOMID, ZDISPLAYNAME, ZNETWORK (whatsapp, telegram,
                         instagram, facebook, beeper), ZISONEONONE
    ZROOMMEMBERMO        one row per (room, user): ZUSERID, ZPROVIDEDDISPLAYNAME,
                         ZCONTACTPREFERREDNAME, ZPHONENUMBERIDENTIFIER, ZEMAILIDENTIFIER — the
                         bridge's hints at who a Matrix user is
    ZBSEVENT             the cached events, ZDATA an NSKeyedArchiver BSEvent: eventId, roomId,
                         userId, originServerTs (ms), content, and `clearEvent` — the decrypted
                         event — when the app had decrypted it; ZISREDACTED, ZISREDACTION
    ZBSROOMLASTMESSAGE   the last message of each room in clear: ZEVENTID, ZEVENTTYPE, ZSENDER,
                         ZSENDERDISPLAYNAME, ZMESSAGEBODY, ZORIGINSERVERTS (ms)

The cache is thin: most events are stored encrypted (Megolm, whose sessions this adapter does not
touch), a decrypted copy exists for some, and every room keeps its last message in clear. One
message/v1 line per message in clear: every event with a body — its `clearEvent` when there is
one, else an unencrypted `content` — then every last-message row whose event was not already
logged (`extra.from_last_message`, counted). Encrypted events without a decrypted copy, reactions,
redactions and redacted events, membership and bridge state are skipped and counted.

Kind `message`, tier 2, source `beeper`, `at` the event's origin server timestamp in UTC,
`raw_id` the Matrix event id (unique across rooms). `chat` is the room: `id` the room id, `type`
`direct` when the room is one-on-one, `name` the room's display name; `extra.network` says which
bridge. The owner is the user who is a member of the most rooms (the account itself, on every room
the bridges made); `from_me` is true for that user's events and for a bridged copy of the owner's
own message (`fi.mau.double_puppet_source` in the content). The sender is a contact resolution hint
from the member row (RFC 0006, never resolved here): `{phone}` when the bridge gave the member's
number, `{email}` when an address, else `{handle, <matrix user id>}`; `name` is the contact's
preferred name when the app matched one, else the name the network provided; the Matrix user id
stays under `extra.matrix_user`. Text messages (`m.text`, `m.notice`, `m.emote` with
`extra.emote`) carry `text`; media (`m.image`, `m.video`, `m.audio` — `voice` when flagged —,
`m.file`, `m.sticker`, `m.location`) carry `media_kind`, with the file name and media type under
`extra`; the bytes are not in the store. Pure: opened `mode=ro`, `immutable=1`, rooms and members
read once, events streamed, no network.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import keyed_archive, phone

NAME = "beeper"
KIND = "message"
TIER = 2
SCHEMA = "message/v1"

SQLITE_HEADER = b"SQLite format 3\x00"
REQUIRED_TABLES = frozenset({"ZBSEVENT", "ZBSROOMLASTMESSAGE", "ZROOMITEMMO", "ZROOMMEMBERMO"})
EARLIEST_MS = 1_262_304_000_000  # 2010-01-01: Matrix did not exist before; earlier is garbage
DOUBLE_PUPPET = "fi.mau.double_puppet_source"
VOICE_FLAG = "org.matrix.msc3245.voice"
TEXT_TYPES = {"m.text": None, "m.notice": None, "m.emote": None}
MEDIA_KINDS = {
    "m.image": "image",
    "m.video": "video",
    "m.audio": "audio",
    "m.file": "document",
    "m.sticker": "sticker",
    "m.location": "location",
}
MESSAGE_EVENT_TYPES = {"m.room.message", "m.sticker", ""}

EVENTS = "SELECT ZEVENTID, ZROOMID, ZISREDACTED, ZISREDACTION, ZDATA FROM ZBSEVENT ORDER BY Z_PK"
LAST = """
SELECT ZEVENTID, ZROOMID, ZSENDER, ZSENDERDISPLAYNAME, ZMESSAGEBODY, ZORIGINSERVERTS, ZEVENTTYPE, ZISREDACTED
FROM ZBSROOMLASTMESSAGE
WHERE ZEVENTID IS NOT NULL AND ZEVENTID <> ''
ORDER BY Z_PK
"""
ROOMS = "SELECT ZROOMID, ZDISPLAYNAME, ZNETWORK, ZISONEONONE FROM ZROOMITEMMO"
MEMBERS = """
SELECT ZROOMID, ZUSERID, ZPROVIDEDDISPLAYNAME, ZCONTACTPREFERREDNAME, ZEMAILIDENTIFIER, ZPHONENUMBERIDENTIFIER
FROM ZROOMMEMBERMO
WHERE ZUSERID IS NOT NULL AND ZUSERID <> ''
"""


@dataclass(frozen=True)
class Room:
    name: str | None
    network: str | None
    direct: bool


@dataclass(frozen=True)
class Member:
    name: str | None
    email: str | None
    phone: str | None

    def ref(self, user_id: str) -> dict[str, str]:
        """Source-native (RFC 0006): the number the bridge gave, else the address, else the handle."""
        if self.phone is not None:
            value, unnormalised = phone.normalise(self.phone, "")
            if value and not unnormalised:
                return {"kind": "phone", "value": value}
        if self.email is not None:
            return {"kind": "email", "value": self.email.lower()}
        return {"kind": "handle", "value": user_id}


@dataclass
class _Store:
    rooms: dict[str, Room]
    members: dict[tuple[str, str], Member]
    by_user: dict[str, Member]
    owner: str | None


def sniff(path: Path) -> bool:
    """A SQLite file with Beeper's event, last-message, room and member tables. Never raises."""
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
    """One message/v1 line per message in clear: the events in row order, then the last-message
    rows not already logged, streamed.

    `since` is RFC3339 UTC; messages before it are not yielded. `counts` tallies what was left out
    — `skipped_encrypted` (no decrypted copy), `skipped_reaction`, `skipped_redacted` (redacted,
    or a redaction), `skipped_system_event` (membership, bridge state, anything without a body),
    `skipped_bad_date` — and what was noted: `from_last_message`."""
    counts = counts if counts is not None else {}
    con = _open(Path(path))
    try:
        store = _load(con)
        logged: set[str] = set()
        for event_id, room_id, redacted, redaction, blob in con.execute(EVENTS):
            draft = _event_draft(event_id, room_id, redacted, redaction, blob, store, counts)
            if draft is None:
                continue
            logged.add(draft["payload"]["raw_id"])
            if not (since and draft["at"] < since):
                yield draft
        for row in con.execute(LAST):
            if row[0] in logged:
                continue
            draft = _last_draft(row, store, counts)
            if draft is not None and not (since and draft["at"] < since):
                yield draft
    finally:
        con.close()


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _load(con: sqlite3.Connection) -> _Store:
    rooms = {
        str(room_id): Room(_text(name), _text(network), bool(direct))
        for room_id, name, network, direct in con.execute(ROOMS)
        if isinstance(room_id, str)
    }
    members: dict[tuple[str, str], Member] = {}
    by_user: dict[str, Member] = {}
    room_count: dict[str, int] = {}
    for room_id, user_id, provided, preferred, email, number in con.execute(MEMBERS):
        member = Member(_text(preferred) or _text(provided), _text(email), _text(number))
        members[(str(room_id), str(user_id))] = member
        if user_id not in by_user or (by_user[user_id].phone is None and member.phone is not None):
            by_user[str(user_id)] = member
        room_count[str(user_id)] = room_count.get(str(user_id), 0) + 1
    owner = max(room_count, key=lambda u: (room_count[u], u)) if room_count else None
    return _Store(rooms, members, by_user, owner)


def _event_draft(
    event_id: object,
    room_id: object,
    redacted: object,
    redaction: object,
    blob: object,
    store: _Store,
    counts: dict[str, int],
) -> dict[str, Any] | None:
    if redacted or redaction:
        _count(counts, "skipped_redacted")
        return None
    event = keyed_archive.decode(blob)
    if not isinstance(event, dict):
        _count(counts, "skipped_system_event")
        return None
    clear = event.get("clearEvent")
    content = clear.get("content") if isinstance(clear, dict) else event.get("content")
    if not isinstance(content, dict):
        content = {}
    matrix_type = _text(event.get("type")) or (_text(clear.get("type")) if isinstance(clear, dict) else None)
    relates = content.get("m.relates_to")
    annotation = isinstance(relates, dict) and relates.get("rel_type") == "m.annotation"
    if matrix_type == "m.reaction" or annotation:
        _count(counts, "skipped_reaction")
        return None
    if "ciphertext" in content and "body" not in content:
        _count(counts, "skipped_encrypted")
        return None
    msgtype = _text(content.get("msgtype"))
    if msgtype is None and matrix_type == "m.sticker":
        msgtype = "m.sticker"
    body = _text(content.get("body"))
    if body is None or (msgtype not in TEXT_TYPES and msgtype not in MEDIA_KINDS):
        _count(counts, "skipped_system_event")
        return None
    at = _rfc3339(event.get("originServerTs"))
    if at is None:
        _count(counts, "skipped_bad_date")
        return None
    sender = _text(event.get("userId"))
    from_me = sender == store.owner or DOUBLE_PUPPET in content
    room_key = _text(room_id) or _text(event.get("roomId")) or ""
    raw_id = _text(event_id) or _text(event.get("eventId")) or ""
    extra: dict[str, Any] = {}
    payload = _payload(raw_id, room_key, sender, from_me, store, extra)
    if msgtype in TEXT_TYPES:
        payload["text"] = body
        if msgtype == "m.emote":
            extra["emote"] = True
    else:
        kind = MEDIA_KINDS[msgtype]
        if kind == "audio" and VOICE_FLAG in content:
            kind = "voice"
        payload["media_kind"] = kind
        extra["filename"] = body
        info = content.get("info")
        if isinstance(info, dict) and _text(info.get("mimetype")) is not None:
            extra["media_type"] = info["mimetype"]
    if extra:
        payload["extra"] = extra
    return _line(at, payload)


def _last_draft(row: tuple[Any, ...], store: _Store, counts: dict[str, int]) -> dict[str, Any] | None:
    event_id, room_id, sender, sender_name, body, ts, event_type, redacted = row
    kind = _text(event_type) or ""
    if redacted:
        _count(counts, "skipped_redacted")
        return None
    if kind == "m.reaction":
        _count(counts, "skipped_reaction")
        return None
    if kind == "m.room.encrypted":
        _count(counts, "skipped_encrypted")
        return None
    text = _text(body)
    if kind not in MESSAGE_EVENT_TYPES or text is None:
        _count(counts, "skipped_system_event")
        return None
    at = _rfc3339(ts)
    if at is None:
        _count(counts, "skipped_bad_date")
        return None
    sender = _text(sender)
    from_me = sender == store.owner
    extra: dict[str, Any] = {}
    payload = _payload(str(event_id), str(room_id), sender, from_me, store, extra, _text(sender_name))
    if kind == "m.sticker":
        payload["media_kind"] = "sticker"
    else:
        payload["text"] = text
    extra["from_last_message"] = True
    _count(counts, "from_last_message")
    payload["extra"] = extra
    return _line(at, payload)


def _payload(
    raw_id: str,
    room_id: str,
    sender: str | None,
    from_me: bool,
    store: _Store,
    extra: dict[str, Any],
    shown_name: str | None = None,
) -> dict[str, Any]:
    room = store.rooms.get(room_id)
    chat: dict[str, Any] = {"id": room_id, "type": "direct" if room is not None and room.direct else "group"}
    if room is not None and room.name is not None:
        chat["name"] = room.name
    payload: dict[str, Any] = {"schema": SCHEMA, "raw_id": raw_id, "chat": chat, "from_me": from_me}
    if room is not None and room.network is not None:
        extra["network"] = room.network
    if sender is not None:
        if not from_me:
            member = store.members.get((room_id, sender)) or store.by_user.get(sender)
            ref = member.ref(sender) if member is not None else {"kind": "handle", "value": sender}
            name = (member.name if member is not None else None) or shown_name
            if name is not None:
                ref["name"] = name
            payload["sender"] = ref
        extra["matrix_user"] = sender
    return payload


def _line(at: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "at": at,
        "end": None,
        "tz": None,  # the logbook's own
        "source": NAME,
        "kind": KIND,
        "tier": TIER,
        "payload": payload,
    }


def _text(value: object) -> str | None:
    """A non-blank string, stripped; anything else is None."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def _rfc3339(milliseconds: object) -> str | None:
    if not isinstance(milliseconds, int | float) or isinstance(milliseconds, bool):
        return None
    if milliseconds < EARLIEST_MS:
        return None
    try:
        return datetime.fromtimestamp(int(milliseconds) // 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return None
