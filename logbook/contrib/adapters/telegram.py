"""Telegram Desktop's JSON export → message/v1 (RFC 0008): the owner's conversations with bots.

The owner talks to agents of their own on Telegram, bots they run, and those conversations are
part of the record: the owner's words at their tier, the bot's words marked as machine text
(`logbook.core.machine`), never as a person's. Telegram Desktop exports an account under
Settings → Advanced → Export Telegram data, as *Machine-readable JSON*: a folder holding
`result.json` and the media it downloaded beside it (`photos/`, `voice_messages/`, `files/`, …).
Ticking *Bot chats* alone keeps the file small; a whole account's export is read the same way, in
one piece. A chat's own export (⋮ → Export chat history) has the same shape for one chat.

`logbook add telegram-export <folder>` (or the folder, or its `result.json`, sniffed) reads every
chat of type `bot_chat` and nothing else: a personal chat, a group, a channel or the saved messages
are counted (`skipped_not_a_bot_chat`) and never read, so no person's words come in through here.
One line per message; a service message (a pin, a cleared history) is skipped and counted, and so
is a message with neither words nor media (a dice, a game: `skipped_empty`).

Kind `message`, tier 2 (RFC 0008, MUST), source `telegram`, `at` the message's `date_unixtime`
(an export older than that field gives only a local time without an offset, read in the record's
zone). The chat is `{id: <the bot's user id>, type: direct, name: <the bot's name>}`. A private
chat with a bot has two sides: a message from the bot (`from_id` `user<chat id>`, or the bare
number an older export wrote) has `from_me`
false, `sender` `{provider_id, telegram:<bot id>, name}` and `extra.machine` true; every other
message is the owner's (`from_me` true), unless the export names its owner
(`personal_information.user_id`) and the sender is someone else, which is counted
(`skipped_not_owner`). Every line carries `extra.counterpart`, the bot as an observed entity of kind
`agent`: `{kind: agent, ref: {provider_id, telegram:<bot id>}, name}`.

**The key both views share.** Telegram numbers the messages of a private chat per account: the
owner's export and the bot's own updates (`sync telegram`, `telegram_live`) give the same message
two different ids. So `raw_id` is not the export's id but what both sides see alike:
`<bot id>/<unix seconds>/<me|bot>/<digest>`, the digest the first twelve hex characters of the
SHA-256 of the text (or caption, whitespace collapsed, NFC) and whether there is media; the n-th
message of one chat with the same four parts is `~n` after them (an album sent in one second). The
export's own id stays under `extra.message_id` and `extra.view` is `export`. An edited message is
keyed by the text it has now, as both views give it after the edit (`edited`, `extra.edited_at`).

Text is the export's text with its formatting dropped (`text` is a string or a list of strings and
entities). A reply's `reply_to` is the key of the message it answers when the export holds it; the
export's id stays under `extra.reply_to_message_id`. A forwarded message keeps `extra.forwarded`
and `extra.forwarded_from`: forwarded words are the owner's to keep, not the owner's words.

Media is referenced, never copied (WhatsApp's convention): `media_kind` from the export's own
classification and `extra.media` `{local_path, sha256, bytes, media_type?, filename?}` for a file
the export holds, the path POSIX-relative to the export folder and resolved by its parts, never
leaving the folder; a file the export left out (or whose path leaves it) is `extra.media_missing`.
`payload.media` is never set. Pure: reads the folder, writes nothing, no network.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .. import stream

__all__ = [
    "KIND",
    "NAME",
    "SCHEMA",
    "TIER",
    "Bot",
    "Keys",
    "draft",
    "key",
    "run",
    "sniff",
]

NAME = "telegram"
KIND = "message"
TIER = 2  # RFC 0008: MUST
SCHEMA = "message/v1"
RESULT = "result.json"
BOT_CHAT = "bot_chat"
PROVIDER = "telegram"
DIGEST_CHARS = 12
HASH_CHUNK = 1 << 20
CHAT_TYPES = (
    "bot_chat",
    "personal_chat",
    "saved_messages",
    "replies",
    "verification_codes",
    "private_group",
    "private_supergroup",
    "public_supergroup",
    "private_channel",
    "public_channel",
)
SIGNATURE = re.compile(r'"type"\s*:\s*"(?:' + "|".join(CHAT_TYPES) + r')"')
MEDIA_TYPES = {  # the export's `media_type` → RFC 0008's `media_kind`
    "sticker": "sticker",
    "voice_message": "voice",
    "video_message": "video",
    "animation": "gif",
    "video_file": "video",
    "audio_file": "audio",
}


# -- what both views share ---------------------------------------------------------------------------


class Bot:
    """The counterpart: one bot, by its user id, with the name and username its side gives."""

    def __init__(self, bot_id: str, name: str | None = None, username: str | None = None):
        self.id = bot_id
        self.name = name
        self.username = username

    @property
    def ref(self) -> dict[str, str]:
        return {"kind": "provider_id", "value": f"{PROVIDER}:{self.id}"}

    def counterpart(self) -> dict[str, Any]:
        """The bot as an observed entity of kind `agent` (`logbook.core.machine`)."""
        found: dict[str, Any] = {"kind": "agent", "ref": self.ref}
        if self.name:
            found["name"] = self.name
        if self.username:
            found["username"] = self.username
        return found

    def sender(self) -> dict[str, str]:
        """RFC 0008's `sender` for a line the bot wrote: source-native, never resolved."""
        ref = dict(self.ref)
        if self.name:
            ref["name"] = self.name
        return ref


def normal_text(text: str | None) -> str:
    """Text as the key reads it: NFC, whitespace collapsed, stripped."""
    return unicodedata.normalize("NFC", " ".join((text or "").split()))


def key(bot_id: str, unix: int, from_me: bool, text: str | None, has_media: bool) -> str:
    """The raw_id both the export and the bot's updates give one message (module docstring)."""
    body = f"{normal_text(text)}\n{'media' if has_media else ''}"
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:DIGEST_CHARS]
    return f"{bot_id}/{unix}/{'me' if from_me else 'bot'}/{digest}"


class Keys:
    """The keys one view of one chat has minted: the n-th repeat of a key gets `~n`."""

    def __init__(self) -> None:
        self.seen: dict[str, int] = {}

    def mint(self, base: str) -> str:
        n = self.seen.get(base, 0) + 1
        self.seen[base] = n
        return base if n == 1 else f"{base}~{n}"


def draft(
    *,
    bot: Bot,
    at: str,
    raw_id: str,
    from_me: bool,
    text: str | None,
    view: str,
    message_id: int | str | None,
    media_kind: str | None = None,
    reply_to: str | None = None,
    edited_at: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One message/v1 line draft, the one mapping of the export and the bot's updates."""
    chat: dict[str, Any] = {"id": bot.id, "type": "direct"}
    if bot.name:
        chat["name"] = bot.name
    payload: dict[str, Any] = {"schema": SCHEMA, "raw_id": raw_id, "chat": chat, "from_me": from_me}
    if not from_me:
        payload["sender"] = bot.sender()
    if text:
        payload["text"] = text
    if media_kind is not None:
        payload["media_kind"] = media_kind
    if reply_to is not None:
        payload["reply_to"] = reply_to
    if edited_at is not None:
        payload["edited"] = True
    more: dict[str, Any] = {"counterpart": bot.counterpart()}
    if not from_me:
        more["machine"] = True
    more["view"] = view
    if message_id is not None:
        more["message_id"] = message_id
    if edited_at is not None:
        more["edited_at"] = edited_at
    more.update(extra or {})
    payload["extra"] = more
    return {
        "at": at,
        "end": None,
        "tz": None,  # the logbook's own
        "source": NAME,
        "kind": KIND,
        "tier": TIER,
        "payload": payload,
    }


def stamp(unix: int) -> str | None:
    try:
        return datetime.fromtimestamp(unix, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return None


# -- the export --------------------------------------------------------------------------------------


def _result(path: Path) -> Path:
    path = Path(path)
    return path / RESULT if path.is_dir() else path


def sniff(path: Path) -> bool:
    """A folder holding Telegram Desktop's `result.json`, or that file: its head names a chat type
    Telegram writes, or the account's personal information. Never raises."""
    try:
        file = _result(Path(path))
        if file.name != RESULT or not file.is_file():
            return False
    except OSError:
        return False
    head = stream.head(file)
    if not head.lstrip().startswith("{"):
        return False
    if '"personal_information"' in head and '"user_id"' in head:
        return True
    return '"messages"' in head and SIGNATURE.search(head) is not None


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
) -> Iterator[dict[str, Any]]:
    """One message/v1 line draft per message of every bot chat in the export, chat by chat, each in
    the export's order. `since` (RFC3339 UTC) leaves out what came before it; `timezone` reads the
    local time of an export without unix times (UTC when None). `counts` tallies
    `skipped_not_a_bot_chat`, `skipped_service`, `skipped_not_owner`, `skipped_bad_date`, and notes
    `media_hashed` and `media_missing`."""
    counts = counts if counts is not None else {}
    file = _result(Path(path))
    root = file.parent
    try:
        doc = json.loads(file.read_bytes().decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise ValueError(f"{file.name} is not a Telegram export that parses: {e}") from None
    if not isinstance(doc, dict):
        raise ValueError(f"{file.name} is not a Telegram export: not a JSON object")
    owner = _owner_id(doc)
    zone = _zone(timezone)
    for chat in _chats(doc):
        if chat.get("type") != BOT_CHAT:
            _count(counts, "skipped_not_a_bot_chat")
            continue
        yield from _chat(chat, root, owner, zone, since, counts)


def _chats(doc: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    """The chats of a whole account's export (`chats.list`), or the one chat of a chat's export."""
    chats = doc.get("chats")
    listed = chats.get("list") if isinstance(chats, dict) else None
    if isinstance(listed, list):
        yield from (c for c in listed if isinstance(c, dict))
    elif isinstance(doc.get("messages"), list):
        yield doc


def _owner_id(doc: Mapping[str, Any]) -> str | None:
    info = doc.get("personal_information")
    user = info.get("user_id") if isinstance(info, dict) else None
    return str(user) if isinstance(user, int | str) and str(user).strip() else None


def _zone(timezone: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(timezone) if timezone else ZoneInfo("UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _chat(
    chat: Mapping[str, Any],
    root: Path,
    owner: str | None,
    zone: ZoneInfo,
    since: str | None,
    counts: dict[str, int],
) -> Iterator[dict[str, Any]]:
    bot_id = str(chat.get("id") or "").strip()
    if not bot_id:
        _count(counts, "skipped_no_chat")
        return
    bot = Bot(bot_id, _text(chat.get("name")))
    keys = Keys()
    by_id: dict[Any, str] = {}  # the export's id → the key it was given, for replies
    messages = chat.get("messages")
    for message in messages if isinstance(messages, list) else []:
        if not isinstance(message, dict):
            continue
        if message.get("type") != "message":
            _count(counts, "skipped_service")
            continue
        unix = _unix(message, zone)
        at = stamp(unix) if unix is not None else None
        if unix is None or at is None:
            _count(counts, "skipped_bad_date")
            continue
        sender = _peer(message.get("from_id"))
        from_me = sender != f"user{bot_id}"
        if from_me and owner is not None and sender and sender != f"user{owner}":
            _count(counts, "skipped_not_owner")
            continue
        text = flatten(message.get("text"))
        kind = _media_kind(message)
        if not normal_text(text) and kind is None:
            _count(counts, "skipped_empty")  # a dice, a game: neither words nor media
            continue
        raw_id = keys.mint(key(bot_id, unix, from_me, text, kind is not None))
        by_id[message.get("id")] = raw_id
        if since and at < since:
            continue  # minted all the same: a key's repeat count is the chat's, not the window's
        extra: dict[str, Any] = {}
        if kind is not None:
            _media(message, root, extra, counts)
        replied = message.get("reply_to_message_id")
        if replied is not None:
            extra["reply_to_message_id"] = replied
        if "forwarded_from" in message:
            extra["forwarded"] = True
            if _text(message.get("forwarded_from")):
                extra["forwarded_from"] = _text(message.get("forwarded_from"))
        edited = _edited(message, zone)
        yield draft(
            bot=bot,
            at=at,
            raw_id=raw_id,
            from_me=from_me,
            text=text or None,
            view="export",
            message_id=message.get("id") if isinstance(message.get("id"), int | str) else None,
            media_kind=kind,
            reply_to=by_id.get(replied) if replied is not None else None,
            edited_at=edited,
            extra=extra,
        )


def _peer(value: object) -> str:
    """A sender as the export names it, `user<id>`: older exports wrote the bare number."""
    if isinstance(value, int) and not isinstance(value, bool):
        return f"user{value}"
    text = str(value or "").strip()
    return f"user{text}" if text.isdigit() else text


def flatten(text: object) -> str:
    """The words an export's `text` shows: a string, or a list of strings and entities `{type, text}`."""
    if isinstance(text, str):
        return text
    if isinstance(text, list):
        return "".join(
            part if isinstance(part, str) else str(part.get("text") or "") if isinstance(part, dict) else ""
            for part in text
        )
    return ""


def _unix(message: Mapping[str, Any], zone: ZoneInfo) -> int | None:
    raw = message.get("date_unixtime")
    if isinstance(raw, int | str) and str(raw).strip().isdigit():
        return int(str(raw).strip())
    return _local_unix(message.get("date"), zone)


def _local_unix(value: object, zone: ZoneInfo) -> int | None:
    """An export's local time without an offset, read in `zone`."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        when = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=zone)
    return int(when.timestamp())


def _edited(message: Mapping[str, Any], zone: ZoneInfo) -> str | None:
    raw = message.get("edited_unixtime")
    if isinstance(raw, int | str) and str(raw).strip().isdigit():
        return stamp(int(str(raw).strip()))
    if "edited" in message:
        unix = _local_unix(message.get("edited"), zone)
        return stamp(unix) if unix is not None else None
    return None


def _media_kind(message: Mapping[str, Any]) -> str | None:
    """RFC 0008's `media_kind` from the export's own fields; None for a message without media."""
    if "photo" in message:
        return "image"
    media_type = message.get("media_type")
    if isinstance(media_type, str) and media_type in MEDIA_TYPES:
        return MEDIA_TYPES[media_type]
    if "file" in message:
        return "document"
    if "location_information" in message or "place_name" in message:
        return "location"
    if "contact_information" in message:
        return "contact"
    if "poll" in message:
        return "other"
    return None


def _media(message: Mapping[str, Any], root: Path, extra: dict[str, Any], counts: dict[str, int]) -> None:
    """extra.media for the file the message names, hashed from the export; extra.media_missing when
    the export does not hold it (left out, too large, or a path that would leave the folder)."""
    media: dict[str, Any] = {}
    named = message.get("photo") if "photo" in message else message.get("file")
    local = _text(named) if isinstance(named, str) and not named.strip().startswith("(") else None
    if local is not None:
        media["local_path"] = local
    found = _inside(root, local) if local is not None else None
    if found is not None:
        media["sha256"], media["bytes"] = _digest(found)
        _count(counts, "media_hashed")
    else:
        extra["media_missing"] = True
        _count(counts, "media_missing")
    media_type = _text(message.get("mime_type"))
    if media_type is not None:
        media["media_type"] = media_type
    filename = _text(message.get("file_name"))
    if filename is not None:
        media["filename"] = filename
    if media:
        extra["media"] = media


def _inside(root: Path, local: str) -> Path | None:
    """The file a POSIX-relative path names inside `root`, by its parts; None when it is absolute,
    climbs out with `..`, or is not a file."""
    rel = PurePosixPath(local)
    if rel.is_absolute() or not rel.parts or ".." in rel.parts:
        return None
    file = root.joinpath(*rel.parts)
    try:
        return file if file.is_file() else None
    except OSError:
        return None


def _digest(file: Path) -> tuple[str, int]:
    h, size = hashlib.sha256(), 0
    with file.open("rb") as fh:
        while chunk := fh.read(HASH_CHUNK):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def _count(counts: dict[str, int], name: str) -> None:
    counts[name] = counts.get(name, 0) + 1


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
