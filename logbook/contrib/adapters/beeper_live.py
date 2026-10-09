"""Beeper Desktop → message/v1 (RFC 0008), live: every chat the app bridges, read from its local API.

Beeper Desktop (Automattic) bridges WhatsApp, Signal, Telegram, Instagram, Messenger, LinkedIn, X and
more into one app and, while it runs, serves a local HTTP API: `http://localhost:23373` by default,
`Authorization: Bearer <token>`, a token made under Settings → Developers → Approved connections. The
token reads everything and can send as the owner, so it is a password: it lives in
`LOGBOOK_BEEPER_TOKEN` and never in the record. `LOGBOOK_BEEPER_URL` names another address; one that
is not this machine (localhost, 127.0.0.1, ::1) is refused unless `LOGBOOK_BEEPER_ALLOW_REMOTE=1`,
because the design is that only this machine reads Beeper and Remote Access stays off.

`logbook sync beeper` walks, with GET and nothing else: `GET /v1/accounts` (one per network), then
`GET /v1/chats?accountIDs=<id>&limit=200` per account, paged by `cursor` and `direction=before`,
then `GET /v1/chats/<chat>/messages` per chat, newest first by the same cursor, read back until the
chat's own watermark — its newest message seen, less a lookback of 24 h for a message a bridge
delivers late — or `since` for a chat with no mark yet. Each page carries `items`, `hasMore` and
`oldestCursor`, as Beeper's public SDK reads them. Nothing here sends, reacts, marks read, archives
or changes a thing; `check` is the one other call, `GET /v1/info`, which `doctor` makes to say
whether the app answers.

One message/v1 line per message: `at` the message's timestamp in UTC; `source`
`beeper-<network>` (`beeper-whatsapp`, `beeper-signal`; the envelope's source names allow letters,
digits and hyphens, so the network rides on a hyphen) and `extra.network` the same, so readers
tell the networks apart; `raw_id` `<account id>/<chat id>/<message id>`, which `append_many` dedupes
on; `from_me` when Beeper says the owner sent it (`isSender`, or the account's own user); `sender`
a source-native hint, never resolved — `{phone}` when the chat's participant list gives the number,
`{email}` when an address, else `{handle, <Beeper user id>}`, with the name the app shows; `chat`
the Beeper chat (`direct` for `single`, else `group`, with its title); `text`; `reply_to` the
raw_id of the message replied to; attachments referenced by Beeper asset id, size, media type and
file name under `extra.media` (the first; the rest under `extra.more_media`), never downloaded.
Reactions, hidden messages, and messages with neither text nor attachment (membership, calls, state)
are skipped and counted; a deleted message that still has text is a line with `extra.deleted`.

Known overlap, by design: a message another source already holds — an iMessage from this Mac's
own database (`sync imessage`), a WhatsApp message from a chat export or the phone's backup, a Beeper
cache from an iPhone backup (the `beeper` file adapter) — is a second line here, under another
source and raw_id. `--networks` chooses which networks to pull; the default is every one but
imessage, which the local source has.

`pull` takes `marks`, the watermark per chat `sync` keeps under `marks` in `state/beeper.json` and
hands back next run, and `networks`, the slugs `--networks` names. Network happens only inside
`pull` and `check`, which only `logbook sync beeper` and `logbook doctor` call.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

from . import phone

__all__ = [
    "ENV",
    "KIND",
    "NAME",
    "Config",
    "check",
    "configure",
    "group",
    "media_kind",
    "network_name",
    "networks",
    "pull",
    "watermark",
]

NAME = "beeper"
KIND = "message"
TIER = 2
SCHEMA = "message/v1"
TOKEN_ENV = "LOGBOOK_BEEPER_TOKEN"
URL_ENV = "LOGBOOK_BEEPER_URL"
ALLOW_REMOTE_ENV = "LOGBOOK_BEEPER_ALLOW_REMOTE"
ENV = (TOKEN_ENV,)  # the URL and the remote override are optional and read beside it
DEFAULT_URL = "http://localhost:23373"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
UNIT = "messages"  # what `sync` counts in its progress lines
GROUP_MARKS = True  # `sync` keeps the newest message time per network in the state file too
PROGRESS_EVERY = 1000
LOOKBACK_H = 24.0
CHAT_PAGE = 200  # the most Beeper serves per page of chats
TIMEOUT_S = 60
CHECK_TIMEOUT_S = 5
MAX_PAGES = 100_000  # a chat longer than this many pages is a cursor that stopped moving
EXCLUDED_BY_DEFAULT = ("imessage",)  # `sync imessage` reads this Mac's own database

DIRECT_CHAT = "direct_chat"
GROUP_CHAT = "group_chat"
NOT_RUNNING = "is Beeper Desktop running, with its Desktop API switched on under Settings → Developers?"
ATTACHMENT_KINDS = {"img": "image", "video": "video", "audio": "audio"}
MESSAGE_KINDS = {"LOCATION": "location", "STICKER": "sticker", "VOICE": "voice", "FILE": "document"}


@dataclass(frozen=True)
class Config:
    url: str
    token: str


def configure(env: Mapping[str, str]) -> Config | None:
    """Config from the environment: None without the token; ValueError, one sentence, for an
    address that is not an http(s) URL or that is not this machine without the override."""
    given = env.get(URL_ENV, "").strip()
    url = given.rstrip("/") if given else DEFAULT_URL
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"{URL_ENV} must be an http URL such as {DEFAULT_URL}, not {given!r}")
    if parts.hostname not in LOCAL_HOSTS and env.get(ALLOW_REMOTE_ENV, "").strip() != "1":
        raise ValueError(
            f"{URL_ENV} names {parts.hostname}, not this machine: Beeper is read only from the machine"
            f" that runs it, unless {ALLOW_REMOTE_ENV}=1 says otherwise"
        )
    token = env.get(TOKEN_ENV, "").strip()
    if not token:
        return None
    return Config(url=url, token=token)


def network_name(raw: object) -> str:
    """Beeper's display name of a network as a slug: `WhatsApp` → `whatsapp`, `Facebook Messenger` →
    `facebook-messenger`; `unknown` when it gave none."""
    text = raw.strip().lower() if isinstance(raw, str) else ""
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return slug or "unknown"


def networks(text: str) -> tuple[str, ...]:
    """`--networks whatsapp,signal` as slugs; ValueError when it names none."""
    names = tuple(dict.fromkeys(network_name(part) for part in text.split(",") if part.strip()))
    if not names:
        raise ValueError(f"--networks names no network, e.g. --networks whatsapp,signal, not {text!r}")
    return names


def watermark(draft: dict[str, Any]) -> str | None:
    """The message's own time: a chat is read back to it."""
    return str(draft["at"])


def group(draft: dict[str, Any]) -> str:
    """The network, as `sync` reports seen and new per network."""
    return str(draft["payload"]["extra"]["network"])


def check(config: Config) -> str:
    """`GET /v1/info`, the one call `doctor` makes: what answered, or OSError saying what did not."""
    info = _get(config, "/v1/info", timeout=CHECK_TIMEOUT_S)
    app = info.get("app") if isinstance(info, dict) else None
    server = info.get("server") if isinstance(info, dict) else None
    name = _text(app.get("name")) if isinstance(app, dict) else None
    version = _text(app.get("version")) if isinstance(app, dict) else None
    remote = bool(server.get("remote_access")) if isinstance(server, dict) else False
    who = " ".join(part for part in (name or "Beeper Desktop", version) if part)
    return f"the API answers: {who}, remote access {'ON: switch it off' if remote else 'off'}"


def pull(
    config: Config,
    since: str | None = None,
    progress: Callable[[int, float], None] | None = None,
    counts: dict[str, int] | None = None,
    networks: Iterable[str] | None = None,
    marks: dict[str, str] | None = None,
) -> Iterator[dict[str, Any]]:
    """Every message of every chat of every account on the networks asked for (`networks`; None
    means all but `EXCLUDED_BY_DEFAULT`), each chat oldest first, one message/v1 line draft each,
    streamed. A chat with a mark in `marks` (`<account>/<chat>` → RFC3339) is read from the lookback
    before it, any other from `since` (None means all), and its mark is raised to the newest message
    yielded. Skips and notes are tallied in `counts`; `progress(messages_so_far, elapsed_seconds)`
    is called every thousand lines and once at the end. Raises OSError when the app does not answer
    or refuses the token, ValueError on a page that is not what the API documents."""
    counts = counts if counts is not None else {}
    counts.setdefault(DIRECT_CHAT, 0)
    counts.setdefault(GROUP_CHAT, 0)
    marks = marks if marks is not None else {}
    wanted = set(networks) if networks is not None else None
    count, started = 0, time.monotonic()
    accounts = _get(config, "/v1/accounts")
    if not isinstance(accounts, list):
        raise ValueError("GET /v1/accounts did not answer with a list of accounts")
    for account in accounts:
        if not isinstance(account, dict):
            continue
        network = network_name(account.get("network"))
        if wanted is None and network in EXCLUDED_BY_DEFAULT:
            continue
        if wanted is not None and network not in wanted:
            continue
        account_id = _text(account.get("accountID"))
        if account_id is None:
            continue
        owner = account.get("user")
        owner_id = _text(owner.get("id")) if isinstance(owner, dict) else None
        for chat in _chats(config, account_id):
            chat_id = _text(chat.get("id"))
            if chat_id is None:
                continue
            if isinstance(chat.get("merge"), dict):  # a merged chat: its member chats carry the messages
                _count(counts, "skipped_merged_chat")
                continue
            key = f"{account_id}/{chat_id}"
            start = _start(marks.get(key), since)
            room = _Room(account_id, chat_id, network, owner_id, chat)
            for message in reversed(_messages(config, chat_id, start)):
                draft = _draft(message, room, counts)
                if draft is None or (start is not None and draft["at"] < start):
                    continue
                if key not in marks or draft["at"] > marks[key]:
                    marks[key] = draft["at"]
                counts[GROUP_CHAT if room.group else DIRECT_CHAT] += 1
                count += 1
                if progress is not None and count % PROGRESS_EVERY == 0:
                    progress(count, time.monotonic() - started)
                yield draft
    if progress is not None and count % PROGRESS_EVERY:
        progress(count, time.monotonic() - started)


@dataclass(frozen=True)
class _Room:
    account_id: str
    chat_id: str
    network: str
    owner_id: str | None
    chat: dict[str, Any]

    @property
    def group(self) -> bool:
        return self.chat.get("type") != "single"

    def participants(self) -> dict[str, dict[str, Any]]:
        people = self.chat.get("participants")
        items = people.get("items") if isinstance(people, dict) else None
        found: dict[str, dict[str, Any]] = {}
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and _text(item.get("id")) is not None:
                found[str(item["id"]).strip()] = item
        return found


def _start(mark: str | None, since: str | None) -> str | None:
    """Where a chat is read back to: the lookback before its mark; `since` for a chat with none."""
    if mark is None:
        return since
    start = datetime.fromisoformat(mark.replace("Z", "+00:00")).astimezone(UTC) - timedelta(hours=LOOKBACK_H)
    return start.strftime("%Y-%m-%dT%H:%M:%SZ")


def _chats(config: Config, account_id: str) -> Iterator[dict[str, Any]]:
    """Every chat of the account, as Beeper lists them (newest activity first), page by page."""
    query: dict[str, str] = {"accountIDs": account_id, "limit": str(CHAT_PAGE)}
    for page in _pages(config, "/v1/chats", query):
        for item in page:
            if isinstance(item, dict):
                yield item


def _messages(config: Config, chat_id: str, start: str | None) -> list[dict[str, Any]]:
    """The chat's messages newest first, as many pages as reach back to `start` (all when None)."""
    out: list[dict[str, Any]] = []
    for page in _pages(config, f"/v1/chats/{quote(chat_id, safe='')}/messages", {}):
        reached = False
        for item in page:
            if not isinstance(item, dict):
                continue
            out.append(item)
            at = _rfc3339(item.get("timestamp"))
            if start is not None and at is not None and at < start:
                reached = True
        if reached:
            break
    return out


def _pages(config: Config, path: str, query: dict[str, str]) -> Iterator[list[Any]]:
    """One list of items per page, following `oldestCursor` with `direction=before` while the page
    says `hasMore` and names a cursor; a cursor that does not move is one clear error."""
    cursor: str | None = None
    for _ in range(MAX_PAGES):
        asked = dict(query) if cursor is None else {**query, "cursor": cursor, "direction": "before"}
        page = _get(config, path, asked)
        if not isinstance(page, dict) or not isinstance(page.get("items"), list):
            raise ValueError(f"GET {path} did not answer with a page of items")
        items: list[Any] = page["items"]
        yield items
        following = _text(page.get("oldestCursor"))
        if page.get("hasMore") is False or following is None or not items:
            return
        if following == cursor:
            raise ValueError(f"GET {path}: the page cursor {following!r} does not move; stopped")
        cursor = following
    raise ValueError(f"GET {path}: more than {MAX_PAGES:,} pages; stopped")


def _get(config: Config, path: str, query: dict[str, str] | None = None, timeout: float = TIMEOUT_S) -> Any:
    """One GET, the only method this module knows, with the bearer token; the JSON it answered."""
    url = config.url + path + (f"?{urlencode(query)}" if query else "")
    req = Request(
        url,
        headers={"Authorization": f"Bearer {config.token}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(req, timeout=timeout) as response:
            body = response.read()
    except HTTPError as e:
        if e.code in (401, 403):
            raise OSError(
                f"Beeper Desktop refused the token ({e.code}): make a new one under Settings → Developers"
                " → Approved connections"
            ) from None
        raise OSError(f"Beeper Desktop answered {e.code} to GET {path}") from None
    except URLError as e:
        raise OSError(
            f"Beeper Desktop is not answering at {config.url} ({e.reason}): {NOT_RUNNING}"
        ) from None
    except TimeoutError:
        raise OSError(
            f"Beeper Desktop did not answer at {config.url} in {timeout:g}s: {NOT_RUNNING}"
        ) from None
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ValueError(f"GET {path} did not answer with JSON") from None


def _draft(message: dict[str, Any], room: _Room, counts: dict[str, int]) -> dict[str, Any] | None:
    if message.get("type") == "REACTION":
        _count(counts, "skipped_reaction")
        return None
    if message.get("isHidden"):
        _count(counts, "skipped_hidden")
        return None
    text = _text(message.get("text"))
    raw_attachments = message.get("attachments")
    attachments = (
        [a for a in raw_attachments if isinstance(a, dict)] if isinstance(raw_attachments, list) else []
    )
    if text is None and not attachments:
        _count(counts, "skipped_system_event")
        return None
    at = _rfc3339(message.get("timestamp"))
    if at is None:
        _count(counts, "skipped_bad_date")
        return None
    message_id = _text(message.get("id"))
    if message_id is None:
        _count(counts, "skipped_no_id")
        return None
    people = room.participants()
    sender_id = _text(message.get("senderID"))
    participant = people.get(sender_id) if sender_id is not None else None
    from_me = bool(message.get("isSender")) or (sender_id is not None and sender_id == room.owner_id)
    if participant is not None and participant.get("isSelf"):
        from_me = True
    chat: dict[str, Any] = {"id": room.chat_id, "type": "group" if room.group else "direct"}
    title = _text(room.chat.get("title"))
    if title is not None:
        chat["name"] = title
    prefix = f"{room.account_id}/{room.chat_id}/"
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": prefix + message_id,
        "chat": chat,
        "from_me": from_me,
    }
    if not from_me and sender_id is not None:
        payload["sender"] = _sender(sender_id, participant, _text(message.get("senderName")))
    if text is not None:
        payload["text"] = text
    linked = _text(message.get("linkedMessageID"))
    if linked is not None:
        payload["reply_to"] = prefix + linked
    extra: dict[str, Any] = {"network": room.network, "account": room.account_id}
    if sender_id is not None:
        extra["sender_id"] = sender_id
    if message.get("isDeleted"):
        extra["deleted"] = True
    edited = _rfc3339(message.get("editedTimestamp"))
    if edited is not None:
        extra["edited_at"] = edited
    kind = _text(message.get("type"))
    for index, attachment in enumerate(attachments):
        item = _media(attachment, kind)
        if index == 0:
            payload["media_kind"] = item.pop("media_kind")
            extra["media"] = item["media"]
        else:
            extra.setdefault("more_media", []).append(item)
    if attachments:
        _count(counts, "media_referenced")
    payload["extra"] = extra
    return {
        "at": at,
        "end": None,
        "tz": None,  # the logbook's own
        "source": f"{NAME}-{room.network}",
        "kind": KIND,
        "tier": TIER,
        "payload": payload,
    }


def _sender(sender_id: str, participant: dict[str, Any] | None, shown: str | None) -> dict[str, str]:
    """Source-native (RFC 0006): the number the participant list gives, else the address, else the
    Beeper user id as a handle; the name the app shows beside it."""
    ref: dict[str, str] = {"kind": "handle", "value": sender_id}
    name = shown
    if participant is not None:
        number = _text(participant.get("phoneNumber"))
        email = _text(participant.get("email"))
        if number is not None:
            value, unnormalised = phone.normalise(number, "")
            if value and not unnormalised:
                ref = {"kind": "phone", "value": value}
        if ref["kind"] == "handle" and email is not None:
            ref = {"kind": "email", "value": email.lower()}
        name = _text(participant.get("fullName")) or name
    if name is not None:
        ref["name"] = name
    return ref


def media_kind(attachment: dict[str, Any], message_kind: str | None) -> str:
    """RFC 0008's classification from the attachment's flags, then its type, then its media type,
    then the message's own kind; `other` when nothing says."""
    if attachment.get("isVoiceNote"):
        return "voice"
    if attachment.get("isSticker"):
        return "sticker"
    if attachment.get("isGif"):
        return "gif"
    kind = ATTACHMENT_KINDS.get(str(attachment.get("type") or ""))
    if kind is not None:
        return kind
    media_type = _text(attachment.get("mimeType"))
    if media_type is not None:
        head = media_type.lower().partition("/")[0]
        if head in ("image", "video", "audio"):
            return head
        return "document"
    if message_kind in MESSAGE_KINDS:
        return MESSAGE_KINDS[message_kind]
    return "other"


def _media(attachment: dict[str, Any], message_kind: str | None) -> dict[str, Any]:
    """{media_kind, media: {asset_id?, bytes?, media_type?, filename?}}: a reference, never the bytes."""
    media: dict[str, Any] = {}
    asset = _text(attachment.get("id"))
    if asset is not None:
        media["asset_id"] = asset
    size = attachment.get("fileSize")
    if isinstance(size, int | float) and not isinstance(size, bool) and size >= 0:
        media["bytes"] = int(size)
    media_type = _text(attachment.get("mimeType"))
    if media_type is not None:
        media["media_type"] = media_type
    filename = _text(attachment.get("fileName"))
    if filename is not None:
        media["filename"] = filename
    return {"media_kind": media_kind(attachment, message_kind), "media": media}


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _text(value: object) -> str | None:
    """A non-blank string, stripped; anything else is None."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def _rfc3339(value: object) -> str | None:
    """Beeper's timestamp (RFC3339, with or without milliseconds or an offset) in the record's
    spelling, UTC to the second; None for anything else."""
    if isinstance(value, int | float) and not isinstance(value, bool):  # milliseconds since the epoch
        try:
            return datetime.fromtimestamp(int(value) // 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (OverflowError, OSError, ValueError):
            return None
    text = _text(value)
    if text is None:
        return None
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
