"""LINE (iOS) → message/v1 (RFC 0008).

Reads the Line.sqlite an iPhone keeps for LINE's messages: in a Finder/iTunes backup it is
`Library/Application Support/PrivateStore/P_<account>/Messages/Line.sqlite` under the
AppDomainGroup-group.com.linecorp.line domain. It is a Core Data store; four tables matter:

    ZMESSAGE    (Z_PK, ZID the server's message id, ZCHAT → ZCHAT, ZSENDER → ZUSER or NULL for the
                 owner's own, ZTIMESTAMP milliseconds since 1970 UTC, ZCONTENTTYPE, ZTEXT,
                 ZSENDSTATUS 0 while unsent)
    ZCHAT       (Z_PK, ZMID the chat's id: `u…` a user for a one-to-one chat, `c…` a group, ZTYPE)
    ZUSER       (Z_PK, ZMID, ZNAME the profile name, ZCUSTOMNAME the owner's own name for them,
                 ZADDRESSBOOKNAME the address book's)
    Z_1MEMBERS  (chat → user)

Two companion stores give what Line.sqlite does not, when they are beside it (or anywhere below
the folder `run` was given — `import-backup` copies them next to the store):

    Contacts.sqlite       ZMANAGEDCNCONTACT (ZMID, ZPHONENUMBER, ZNAME): the address-book
                          contacts LINE matched to a user, the phone number in E.164 digits without
                          its `+` (from `.../P_<account>/Contacts Syncing/` in the app's own domain)
    UnifiedGroup.sqlite   ZUNIFIEDGROUP (ZID, ZNAME): the groups' names

One message/v1 line per ZMESSAGE row: kind `message`, tier 2, source `line`, `at` the message's own
timestamp in UTC, `raw_id` the server's id, else `pk<Z_PK>` for a message never sent (counted,
`extra.unsent`). `chat` is the ZCHAT: `direct` for a `u…` id with the user's name as the owner
spells it (custom name, else the profile name), `group` for the rest with the group's name when
UnifiedGroup.sqlite has it. A row without a sender is the owner's (`from_me`). The sender is a
contact resolution hint, never resolved (RFC 0006): `{phone}` when Contacts.sqlite pairs the
user's mid with a number, else `{handle, <mid>}`; `name` the custom name, else the profile name;
the mid and the address-book name under `extra`. Text (content type 0, and any type this version
does not know that carries text, with `extra.content_type`) carries `text`; images, video, audio
(`voice`), files, stickers, locations, contacts and links carry `media_kind`. Calls (content type
6) are not messages and are skipped and counted; a row with neither text nor a known media type,
or without a usable timestamp, too. Pure: each store opened `mode=ro`, `immutable=1`, users and
chats read once, messages streamed through one cursor, no network.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import phone

NAME = "line"
KIND = "message"
TIER = 2
SCHEMA = "message/v1"

SQLITE_HEADER = b"SQLite format 3\x00"
STORE_NAME = "Line.sqlite"
CONTACTS_NAME = "Contacts.sqlite"
GROUPS_NAME = "UnifiedGroup.sqlite"
REQUIRED_TABLES = frozenset({"ZMESSAGE", "ZCHAT", "ZUSER"})
EARLIEST_MS = 1_293_840_000_000  # 2011-01-01: LINE did not exist before; earlier is garbage
TEXT_TYPE = 0
CALL_TYPE = 6
MEDIA_KINDS = {
    1: "image",
    2: "video",
    3: "voice",
    5: "document",
    7: "sticker",
    12: "link",
    13: "contact",
    14: "document",
    15: "location",
    21: "image",
}

QUERY = """
SELECT m.Z_PK, m.ZID, m.ZCHAT, m.ZSENDER, m.ZTIMESTAMP, m.ZCONTENTTYPE, m.ZTEXT, m.ZSENDSTATUS
FROM ZMESSAGE AS m
ORDER BY m.Z_PK
"""


@dataclass(frozen=True)
class User:
    mid: str | None
    name: str | None  # the profile name
    custom_name: str | None
    address_book_name: str | None

    @property
    def shown(self) -> str | None:
        return self.custom_name or self.name


@dataclass
class _Store:
    users: dict[int, User]
    chats: dict[int, str]  # pk → mid
    phones: dict[str, str]  # mid → number as the contacts store keeps it
    groups: dict[str, str]  # mid → name


def sniff(path: Path) -> bool:
    """A LINE message store (ZMESSAGE, ZCHAT and ZUSER tables), or a folder with one below it.
    Never raises."""
    path = Path(path)
    try:
        if path.is_dir():
            return any(_is_store(p) for p in stores(path))
        return _is_store(path)
    except OSError:
        return False


def stores(path: Path) -> list[Path]:
    """The stores `run` would read: `path` itself when it is a file, else every Line.sqlite below it."""
    path = Path(path)
    if path.is_file():
        return [path]
    return sorted(p for p in path.rglob(STORE_NAME) if p.is_file())


def _is_store(path: Path) -> bool:
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
    """One message/v1 line per message, store by store, in row order, streamed.

    `since` is RFC3339 UTC; messages before it are not yielded. `counts` tallies what was left out
    — `skipped_call`, `skipped_system_event` (neither text nor a known media type),
    `skipped_bad_date` — and what was noted: `no_unique_id` (never sent, keyed by row id)."""
    counts = counts if counts is not None else {}
    root = Path(path)
    for store in stores(root):
        if not _is_store(store):
            continue
        con = _open(store)
        try:
            data = _load(con, _companion(root, store, CONTACTS_NAME), _companion(root, store, GROUPS_NAME))
            for row in con.execute(QUERY):  # the cursor streams; nothing is accumulated
                draft = _draft(row, data, counts)
                if draft is not None and not (since and draft["at"] < since):
                    yield draft
        finally:
            con.close()


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _companion(root: Path, store: Path, name: str) -> Path | None:
    """The companion store beside `store`, else the first one below `root` when that is a folder."""
    beside = store.parent / name
    if beside.is_file():
        return beside
    if root.is_dir():
        return next((p for p in sorted(root.rglob(name)) if p.is_file()), None)
    return None


def _load(con: sqlite3.Connection, contacts: Path | None, groups: Path | None) -> _Store:
    users = {
        int(pk): User(_text(mid), _text(name), _text(custom), _text(book))
        for pk, mid, name, custom, book in con.execute(
            "SELECT Z_PK, ZMID, ZNAME, ZCUSTOMNAME, ZADDRESSBOOKNAME FROM ZUSER"
        )
    }
    chats = {
        int(pk): str(mid) for pk, mid in con.execute("SELECT Z_PK, ZMID FROM ZCHAT") if isinstance(mid, str)
    }
    phones = _table(contacts, "SELECT ZMID, ZPHONENUMBER FROM ZMANAGEDCNCONTACT")
    names = _table(groups, "SELECT ZID, ZNAME FROM ZUNIFIEDGROUP")
    return _Store(users, chats, phones, names)


def _table(path: Path | None, query: str) -> dict[str, str]:
    """`{key: value}` from a companion store's two-column query; {} when the store is not there or
    not what it should be (a companion is a bonus, never a failure)."""
    if path is None:
        return {}
    try:
        con = _open(path)
    except (OSError, ValueError, sqlite3.Error):
        return {}
    try:
        return {
            key: value
            for key, value in con.execute(query)
            if isinstance(key, str) and key and isinstance(value, str) and value.strip()
        }
    except sqlite3.Error:
        return {}
    finally:
        con.close()


def _draft(row: tuple[Any, ...], store: _Store, counts: dict[str, int]) -> dict[str, Any] | None:
    pk, message_id, chat_pk, sender_pk, timestamp, content_type, text, send_status = row
    if content_type == CALL_TYPE:
        _count(counts, "skipped_call")
        return None
    body = _text(text)
    media_kind = MEDIA_KINDS.get(content_type) if isinstance(content_type, int) else None
    if body is None and media_kind is None:
        _count(counts, "skipped_system_event")
        return None
    at = _rfc3339(timestamp)
    if at is None:
        _count(counts, "skipped_bad_date")
        return None
    chat_mid = store.chats.get(chat_pk) if isinstance(chat_pk, int) else None
    chat_mid = chat_mid or f"pk{chat_pk}"
    direct = chat_mid.startswith("u")
    chat: dict[str, Any] = {"id": chat_mid, "type": "direct" if direct else "group"}
    name = _chat_name(chat_mid, direct, store)
    if name is not None:
        chat["name"] = name
    extra: dict[str, Any] = {"pk": pk}
    raw_id = _text(message_id)
    if raw_id is None:
        raw_id = f"pk{pk}"
        _count(counts, "no_unique_id")
    if send_status == 0:
        extra["unsent"] = True
    payload: dict[str, Any] = {"schema": SCHEMA, "raw_id": raw_id, "chat": chat, "from_me": sender_pk is None}
    if sender_pk is not None:
        user = store.users.get(sender_pk) if isinstance(sender_pk, int) else None
        payload["sender"] = _sender(user, sender_pk, store, extra)
    if media_kind is not None:
        payload["media_kind"] = media_kind
        if body is not None:
            extra["caption"] = body
    else:
        payload["text"] = body
    if content_type != TEXT_TYPE and isinstance(content_type, int):
        extra["content_type"] = content_type
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


def _chat_name(mid: str, direct: bool, store: _Store) -> str | None:
    if direct:
        user = next((u for u in store.users.values() if u.mid == mid), None)
        return user.shown if user is not None else None
    return store.groups.get(mid)


def _sender(user: User | None, sender_pk: object, store: _Store, extra: dict[str, Any]) -> dict[str, str]:
    """A phone ref when the contacts store pairs the user's mid with a number, else the mid as a handle."""
    mid = user.mid if user is not None else None
    if mid is None:
        return {"kind": "handle", "value": f"pk{sender_pk}"}
    ref = _phone_ref(store.phones.get(mid)) or {"kind": "handle", "value": mid}
    if user is not None and user.shown is not None:
        ref["name"] = user.shown
    extra["line_mid"] = mid
    if user is not None and user.address_book_name is not None:
        extra["address_book_name"] = user.address_book_name
    return ref


def _phone_ref(number: str | None) -> dict[str, str] | None:
    """LINE keeps a matched contact's number as E.164 digits without the `+`; with it, it is one."""
    if number is None:
        return None
    entered = number if number.startswith("+") else "+" + number
    value, unnormalised = phone.normalise(entered, "")
    if value and not unnormalised:
        return {"kind": "phone", "value": value}
    return None


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
