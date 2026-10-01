"""Twitter / X direct messages (iOS) → message/v1 (RFC 0008).

Reads the DM store the X app keeps per signed-in account: in a Finder/iTunes backup it is
`com.atebits.tweetie.databases/v1/<account id>/<account id>-dmv2.db` under the
AppDomainGroup-group.com.atebits.Tweetie2 domain, one per account, so `run` takes one store or a
folder and reads every `*-dmv2.db` below it. Three tables matter:

    dm_entry         (entry_id, conversation_id, timestamp ms since 1970 UTC, entry_type — message
                      or informational, sender_id, sender_is_owner, plain_text, has_attachment,
                      attachment_types, message_status; `contents` is a MessagePack blob of the
                      same, not read)
    dm_conversation  (conversation_id — `<id>:<id>` or `<id>-<id>` for a one-to-one chat, a plain
                      number for a group — custom_title)
    dm_user          (id, screen_name, nickname — the owner's own name for them)

One message/v1 line per `message` entry: kind `message`, tier 2, source `twitter`, `at` the entry's
timestamp in UTC, `raw_id` the entry id (a UUID, unique across accounts). `chat` is the
conversation: `direct` when its id is two account ids, named after the other account (the nickname,
else the screen name); `group` otherwise, named by its custom title. `from_me` is the store's own
flag. The sender is source-native, never resolved (RFC 0006): `{handle, <screen name>}` with the
nickname as `name` when the store knows the user, else `{provider_id, <account id>}`; the numeric
id stays under `extra.twitter_user_id`. `text` is the plain text; an attachment gives `media_kind`
(`link`, `image` for a photo, `video`, `gif`, `other`) with the store's own type string under
`extra.attachment_types`. The account the store belongs to goes under `extra.account`: the id of
the sender of any entry flagged as the owner's, else the id in the file's name. Informational
entries (joins, name changes), entries with neither text nor an attachment, and entries without a
usable timestamp are skipped and counted. Pure: each store opened `mode=ro`, `immutable=1`, users
and conversations read once, entries streamed, no network.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

NAME = "twitter"
KIND = "message"
TIER = 2
SCHEMA = "message/v1"

SQLITE_HEADER = b"SQLite format 3\x00"
STORE_GLOB = "*-dmv2.db"
STORE_SUFFIX = "-dmv2.db"
REQUIRED_TABLES = frozenset({"dm_entry", "dm_conversation", "dm_user"})
EARLIEST_MS = 1_136_073_600_000  # 2006-01-01: Twitter did not exist before; earlier is garbage
MESSAGE_ENTRY = "message"
SENT = "Sent"
MEDIA_KINDS = {
    "link": "link",
    "card": "link",
    "photo": "image",
    "image": "image",
    "video": "video",
    "animated_gif": "gif",
}

QUERY = """
SELECT entry_id, conversation_id, timestamp, entry_type, sender_id, sender_is_owner, plain_text,
       has_attachment, attachment_types, message_status
FROM dm_entry
ORDER BY timestamp, sequence_number, entry_id
"""


@dataclass(frozen=True)
class User:
    screen_name: str | None
    nickname: str | None

    @property
    def shown(self) -> str | None:
        return self.nickname or self.screen_name


@dataclass
class _Store:
    users: dict[str, User]  # account id (as text) → user
    titles: dict[str, str]  # conversation id → custom title
    account: str | None


def sniff(path: Path) -> bool:
    """A DM store (dm_entry, dm_conversation and dm_user tables), or a folder with one below it.
    Never raises."""
    path = Path(path)
    try:
        if path.is_dir():
            return any(_is_store(p) for p in stores(path))
        return _is_store(path)
    except OSError:
        return False


def stores(path: Path) -> list[Path]:
    """The stores `run` would read: `path` itself when it is a file, else every `*-dmv2.db` below it."""
    path = Path(path)
    if path.is_file():
        return [path]
    return sorted(p for p in path.rglob(STORE_GLOB) if p.is_file())


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
    """One message/v1 line per message entry, store by store, in timestamp order, streamed.

    `since` is RFC3339 UTC; messages before it are not yielded. `counts` tallies what was left out:
    `skipped_system_event` (informational entries), `skipped_no_body` (neither text nor an
    attachment), `skipped_bad_date`."""
    counts = counts if counts is not None else {}
    for store in stores(Path(path)):
        if not _is_store(store):
            continue
        con = _open(store)
        try:
            data = _load(con, store)
            for row in con.execute(QUERY):  # the cursor streams; nothing is accumulated
                draft = _draft(row, data, counts)
                if draft is not None and not (since and draft["at"] < since):
                    yield draft
        finally:
            con.close()


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _load(con: sqlite3.Connection, store: Path) -> _Store:
    users = {
        str(uid): User(_text(screen_name), _text(nickname))
        for uid, screen_name, nickname in con.execute("SELECT id, screen_name, nickname FROM dm_user")
        if uid is not None
    }
    titles = {
        str(cid): title.strip()
        for cid, title in con.execute("SELECT conversation_id, custom_title FROM dm_conversation")
        if isinstance(cid, str) and isinstance(title, str) and title.strip()
    }
    owner = con.execute(
        "SELECT sender_id FROM dm_entry WHERE sender_is_owner = 1 AND sender_id IS NOT NULL LIMIT 1"
    ).fetchone()
    account = str(owner[0]) if owner is not None else _account_from_name(store)
    return _Store(users, titles, account)


def _account_from_name(store: Path) -> str | None:
    """`<account id>-dmv2.db` → the id; None for any other name."""
    name = store.name
    if name.endswith(STORE_SUFFIX) and name[: -len(STORE_SUFFIX)].isdigit():
        return name[: -len(STORE_SUFFIX)]
    return None


def _draft(row: tuple[Any, ...], store: _Store, counts: dict[str, int]) -> dict[str, Any] | None:
    (
        entry_id,
        conversation_id,
        timestamp,
        entry_type,
        sender_id,
        is_owner,
        text,
        has_attachment,
        kinds,
        status,
    ) = row
    if entry_type != MESSAGE_ENTRY:
        _count(counts, "skipped_system_event")
        return None
    body = _text(text)
    media_kind = _media_kind(kinds) if has_attachment else None
    if body is None and media_kind is None:
        _count(counts, "skipped_no_body")
        return None
    at = _rfc3339(timestamp)
    if at is None:
        _count(counts, "skipped_bad_date")
        return None
    conversation = str(conversation_id)
    chat = _chat(conversation, store)
    from_me = bool(is_owner)
    payload: dict[str, Any] = {"schema": SCHEMA, "raw_id": str(entry_id), "chat": chat, "from_me": from_me}
    extra: dict[str, Any] = {}
    if store.account is not None:
        extra["account"] = store.account
    if not from_me and sender_id is not None:
        sender = str(sender_id)
        user = store.users.get(sender)
        if user is not None and user.screen_name is not None:
            ref: dict[str, str] = {"kind": "handle", "value": user.screen_name}
            if user.nickname is not None:
                ref["name"] = user.nickname
            extra["twitter_user_id"] = sender
        else:
            ref = {"kind": "provider_id", "value": sender}
        payload["sender"] = ref
    if body is not None:
        payload["text"] = body
    if media_kind is not None:
        payload["media_kind"] = media_kind
        if _text(kinds) is not None:
            extra["attachment_types"] = kinds
    if _text(status) is not None and status != SENT:
        extra["status"] = status
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


def _chat(conversation: str, store: _Store) -> dict[str, Any]:
    """A one-to-one conversation's id is two account ids; it is named after the other one."""
    parts = conversation.replace("-", ":").split(":")
    direct = len(parts) == 2 and all(p.isdigit() for p in parts)
    chat: dict[str, Any] = {"id": conversation, "type": "direct" if direct else "group"}
    name = store.titles.get(conversation)
    if name is None and direct:
        others = [p for p in parts if p != store.account] or parts
        user = store.users.get(others[0])
        name = user.shown if user is not None else None
    if name is not None:
        chat["name"] = name
    return chat


def _media_kind(kinds: object) -> str:
    """The profile's word for the store's attachment type string (`photo`, `link`, …)."""
    text = _text(kinds)
    if text is None:
        return "other"
    first = text.split(",")[0].strip().lower()
    return MEDIA_KINDS.get(first, "other")


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
