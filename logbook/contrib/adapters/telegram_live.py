"""The owner's own Telegram bots → message/v1 (RFC 0008), live: what the Bot API still holds for each.

The owner runs bots of their own and talks to them; `LOGBOOK_TELEGRAM_BOT_TOKENS` names them, the
tokens comma-separated (BotFather's `<bot id>:<secret>`; each is a password: it can read and send
as the bot, so it is never printed, never in a line, never in a URL this module shows), and
`LOGBOOK_TELEGRAM_OWNER_ID` is the owner's numeric Telegram user id. A bot's updates are meant to be
only its chat with the owner; the owner id makes that a rule rather than a hope: a message from
anyone else is counted (`skipped_not_owner`) and never written, so a stranger who finds a bot never
speaks in the owner's name. A message outside a private chat is counted too (`skipped_not_private`).

`logbook sync telegram` asks each bot, with GET and nothing else, three read-only methods:
`getMe` (who the bot is), `getWebhookInfo` (whether updates go to a webhook, and how many are
pending) and, only when updates are pending and no webhook is set, `getUpdates?timeout=0&limit=100`.
It never passes `offset`, so it never confirms an update: the bot's own program still receives
every one. It never passes `allowed_updates`, which would change what the bot is sent. It never
calls `deleteWebhook`, `getFile` or a method that sends. What that leaves is narrow, and the
docs say so (docs/adapters/agents.md): the Bot API holds an update until the bot confirms it, and
for 24 hours at most; at most the first 100 pending; never the bot's own messages, which Telegram
does not send back to it. A bot that delivers to a webhook is one line in `failed` and is not read.
A bot that long-polls while sync asks may see one `409 Conflict` and retry; a bot with nothing
pending is never asked. The complete conversation, both sides, comes from the owner's export
(`logbook add telegram-export`, the `telegram` file adapter); this source catches what arrived since.

One line per message the owner sent the bot, by the file adapter's mapping (`telegram.draft`), so
the export and this source write the same line: `from_me` true, the chat the bot, `extra.counterpart`
the bot as an observed entity of kind `agent` (with its username from `getMe`), `extra.view` `bot`
and `extra.message_id` the bot's own id for the message. Telegram numbers a private chat's
messages per account, so `raw_id` is the key both views share (`telegram.key`: the bot, the second,
the side, the text's digest), and a message already in the record from the export is not written
again. An `edited_message` is keyed by its new text, as the export has it; the version first sent,
when this source saw it, is a line of its own. A reply's `reply_to` is the key of the message it
answers, which the update carries whole (the bot's message included). A forward keeps
`extra.forwarded` and `extra.forwarded_from`. Media is referenced by the API's `file_unique_id`,
size and media type under `extra.media`, never fetched.

There is no watermark: what the API holds is small and the record's dedupe by (source, raw_id) is
the mark, so `watermark` is None and each run reads everything pending; `--since` still leaves out
what came before it. `LOGBOOK_TELEGRAM_API` points the client elsewhere (a test's fake): https, or
http on this machine only, since the token travels in the path. Network happens only inside
`pull`, which only `logbook sync telegram` calls.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from .telegram import KIND, Bot, Keys, draft, key, stamp

__all__ = ["ENV", "KIND", "NAME", "Config", "configure", "group", "pull", "watermark"]

NAME = "telegram"
HISTORY = False  # the Bot API keeps a day at most: a first scheduled run has nothing to bound
TOKENS_ENV = "LOGBOOK_TELEGRAM_BOT_TOKENS"
OWNER_ENV = "LOGBOOK_TELEGRAM_OWNER_ID"
API_ENV = "LOGBOOK_TELEGRAM_API"
ENV = (TOKENS_ENV, OWNER_ENV)  # the API's address is optional and read beside them
DEFAULT_API = "https://api.telegram.org"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
UNIT = "messages"
LIMIT = 100  # the most getUpdates gives at once; more would need an offset, which confirms
TIMEOUT_S = 30
TOKEN = re.compile(r"^(\d{1,20}):[A-Za-z0-9_-]{1,200}$")
OWNER = re.compile(r"^\d{1,20}$")
MEDIA = (  # the Bot API's message fields, in the order that decides RFC 0008's `media_kind`
    ("photo", "image"),
    ("voice", "voice"),
    ("video_note", "video"),
    ("animation", "gif"),  # before `document`: an animation carries both
    ("video", "video"),
    ("audio", "audio"),
    ("sticker", "sticker"),
    ("document", "document"),
    ("location", "location"),
    ("venue", "location"),
    ("contact", "contact"),
    ("poll", "other"),
)


@dataclass(frozen=True)
class Config:
    tokens: tuple[str, ...] = field(repr=False)
    owner: str
    api: str = DEFAULT_API


def configure(env: Mapping[str, str]) -> Config | None:
    """Config from the environment: None without the tokens or the owner; ValueError, one sentence
    that never repeats a token, for a token that is not BotFather's shape, an owner id that is not a
    number, or an API address that is neither https nor on this machine."""
    raw = env.get(TOKENS_ENV, "")
    tokens = tuple(t.strip() for t in raw.split(",") if t.strip())
    owner = env.get(OWNER_ENV, "").strip()
    api = env.get(API_ENV, "").strip().rstrip("/") or DEFAULT_API
    parts = urlsplit(api)
    secure = parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in LOCAL_HOSTS)
    if not parts.hostname or not secure:
        raise ValueError(f"{API_ENV} must be https, or http on this machine (the token travels in the path)")
    for n, token in enumerate(tokens, 1):
        if TOKEN.match(token) is None:
            raise ValueError(
                f"{TOKENS_ENV}: token {n} of {len(tokens)} is not <bot id>:<secret> as BotFather gives it"
            )
    if owner and OWNER.match(owner) is None:
        raise ValueError(f"{OWNER_ENV} must be the owner's numeric Telegram user id, not a username")
    if not tokens or not owner:
        return None
    return Config(tokens=tokens, owner=owner, api=api)


def watermark(draft: dict[str, Any]) -> str | None:
    """None: what the API holds is read whole every run and the dedupe keeps it once."""
    return None


def group(draft: dict[str, Any]) -> str:
    """The bot, as `sync` reports seen and new per bot."""
    chat = draft["payload"]["chat"]
    return str(chat.get("name") or chat["id"])


def pull(
    config: Config,
    since: str | None = None,
    progress: Callable[[int, float], None] | None = None,
    counts: dict[str, int] | None = None,
    failed: list[str] | None = None,
) -> Iterator[dict[str, Any]]:
    """The owner's messages each bot's updates hold, bot by bot in the order configured, each bot's
    in the order Telegram numbered the updates; every bot is asked before the first line is
    yielded. A bot that cannot be read (a refused token, a webhook, the API not answering) is one
    line in `failed`, naming the bot and never its token; without a list, OSError carries those
    lines after the other bots' messages. `since` (RFC3339 UTC) leaves out what came before it.
    `counts` tallies `skipped_not_owner`, `skipped_not_private`, `skipped_other_update`,
    `skipped_empty` and `skipped_bad_date`; `progress(messages, elapsed)` after each bot."""
    counts = counts if counts is not None else {}
    problems: list[str] = []
    started = time.monotonic()
    read: list[dict[str, Any]] = []
    for token in config.tokens:
        try:
            read.extend(_bot(config, token, since, counts))
        except _BotError as e:
            problems.append(str(e))
        if progress is not None:
            progress(len(read), time.monotonic() - started)
    yield from read
    if problems:
        if failed is None:
            raise OSError("; ".join(problems))
        failed.extend(problems)


class _BotError(Exception):
    """One bot that could not be read; the message names the bot, never the token."""


def _bot(config: Config, token: str, since: str | None, counts: dict[str, int]) -> list[dict[str, Any]]:
    bot_id = token.partition(":")[0]
    me = _call(config, token, bot_id, "getMe")
    if not isinstance(me, dict):
        raise _BotError(f"bot {bot_id}: getMe did not answer with the bot")
    username = _text(me.get("username"))
    bot = Bot(str(me.get("id") or bot_id), _text(me.get("first_name")), username)
    shown = f"@{username}" if username else f"bot {bot.id}"
    hook = _call(config, token, bot_id, "getWebhookInfo")
    if isinstance(hook, dict) and _text(hook.get("url")):
        raise _BotError(
            f"{shown} delivers its updates to a webhook, which sync never changes; nothing read from it"
            " (its conversation comes in through `add telegram-export`)"
        )
    pending = hook.get("pending_update_count") if isinstance(hook, dict) else None
    if pending == 0:
        return []  # nothing to read, and a bot that long-polls is never interrupted
    updates = _call(config, token, bot_id, "getUpdates", {"timeout": "0", "limit": str(LIMIT)})
    if not isinstance(updates, list):
        raise _BotError(f"{shown}: getUpdates did not answer with a list of updates")
    return list(_lines(bot, config.owner, updates, since, counts))


def _lines(
    bot: Bot, owner: str, updates: list[Any], since: str | None, counts: dict[str, int]
) -> Iterator[dict[str, Any]]:
    keys = Keys()
    minted: dict[tuple[Any, str], str] = {}  # (message id, key) → raw_id: an update seen twice is one key
    ordered = sorted(
        (u for u in updates if isinstance(u, dict)),
        key=_update_id,
    )
    for update in ordered:
        message, edited = update.get("message"), False
        if not isinstance(message, dict):
            message, edited = update.get("edited_message"), True
        if not isinstance(message, dict):
            _count(counts, "skipped_other_update")
            continue
        chat = message.get("chat")
        if not isinstance(chat, dict) or chat.get("type") != "private":
            _count(counts, "skipped_not_private")
            continue
        sender = message.get("from")
        if not isinstance(sender, dict) or str(sender.get("id")) != owner:
            _count(counts, "skipped_not_owner")
            continue
        date = message.get("date")
        at = stamp(date) if isinstance(date, int) and not isinstance(date, bool) else None
        if at is None or not isinstance(date, int):
            _count(counts, "skipped_bad_date")
            continue
        text = _text(message.get("text")) or _text(message.get("caption"))
        kind, media = _media(message)
        if text is None and kind is None:
            _count(counts, "skipped_empty")  # a dice, a game: neither words nor media, as the export
            continue
        base = key(bot.id, date, True, text, kind is not None)
        mid = message.get("message_id")
        raw_id = minted.get((mid, base)) or keys.mint(base)
        minted[(mid, base)] = raw_id
        if since and at < since:
            continue
        extra: dict[str, Any] = {}
        if media:
            extra["media"] = media
        replied = message.get("reply_to_message")
        reply_to = _key_of(bot, replied) if isinstance(replied, dict) else None
        if isinstance(replied, dict) and replied.get("message_id") is not None:
            extra["reply_to_message_id"] = replied["message_id"]
        forwarded = _forwarded(message)
        if forwarded is not None:
            extra["forwarded"] = True
            if forwarded:
                extra["forwarded_from"] = forwarded
        edit_date = message.get("edit_date")
        edited_at = stamp(edit_date) if edited and isinstance(edit_date, int) else None
        yield draft(
            bot=bot,
            at=at,
            raw_id=raw_id,
            from_me=True,
            text=text,
            view="bot",
            message_id=mid if isinstance(mid, int | str) else None,
            media_kind=kind,
            reply_to=reply_to,
            edited_at=edited_at,
            extra=extra,
        )


def _update_id(update: Mapping[str, Any]) -> int:
    number = update.get("update_id")
    return number if isinstance(number, int) and not isinstance(number, bool) else 0


def _key_of(bot: Bot, message: Mapping[str, Any]) -> str | None:
    """The key of a message an update carries whole (the one replied to): the bot's or the owner's."""
    date = message.get("date")
    if not isinstance(date, int) or isinstance(date, bool):
        return None
    sender = message.get("from")
    by_bot = isinstance(sender, dict) and (sender.get("is_bot") is True or str(sender.get("id")) == bot.id)
    text = _text(message.get("text")) or _text(message.get("caption"))
    kind, _media_ref = _media(message)
    return key(bot.id, date, not by_bot, text, kind is not None)


def _media(message: Mapping[str, Any]) -> tuple[str | None, dict[str, Any]]:
    """(RFC 0008's media_kind, the reference under extra.media) for the message's media; the largest
    size of a photo; never the file itself."""
    for field_name, kind in MEDIA:
        value = message.get(field_name)
        if value is None:
            continue
        if isinstance(value, list):  # a photo: its sizes, smallest first
            sized = [v for v in value if isinstance(v, dict)]
            value = max(sized, key=lambda v: v.get("file_size") or 0) if sized else {}
        ref: dict[str, Any] = {}
        if isinstance(value, dict):
            unique = _text(value.get("file_unique_id"))
            if unique is not None:
                ref["file_unique_id"] = unique
            size = value.get("file_size")
            if isinstance(size, int) and not isinstance(size, bool) and size >= 0:
                ref["bytes"] = size
            media_type = _text(value.get("mime_type"))
            if media_type is not None:
                ref["media_type"] = media_type
            filename = _text(value.get("file_name"))
            if filename is not None:
                ref["filename"] = filename
        return kind, ref
    return None, {}


def _forwarded(message: Mapping[str, Any]) -> str | None:
    """Who a forwarded message came from, as the API names them ('' when it hides the name); None
    when the message is not a forward. `forward_origin` (Bot API 7.0) first, then the older fields."""
    origin = message.get("forward_origin")
    if isinstance(origin, dict):
        user = origin.get("sender_user")
        if isinstance(user, dict):
            return _name(user)
        chat = origin.get("sender_chat") or origin.get("chat")
        if isinstance(chat, dict):
            return _text(chat.get("title")) or ""
        return _text(origin.get("sender_user_name")) or ""
    if isinstance(message.get("forward_from"), dict):
        return _name(message["forward_from"])
    if isinstance(message.get("forward_from_chat"), dict):
        return _text(message["forward_from_chat"].get("title")) or ""
    if _text(message.get("forward_sender_name")):
        return _text(message.get("forward_sender_name"))
    if message.get("forward_date") is not None:
        return ""
    return None


def _name(user: Mapping[str, Any]) -> str:
    return " ".join(part for part in (_text(user.get("first_name")), _text(user.get("last_name"))) if part)


def _call(
    config: Config, token: str, bot_id: str, method: str, query: Mapping[str, str] | None = None
) -> Any:
    """One GET of one Bot API method; the `result` it answered. The only network call in this
    module. A refusal or a silence is a _BotError naming the bot and the method, never the token
    and never the URL, which holds it."""
    url = f"{config.api}/bot{token}/{method}" + (f"?{urlencode(query)}" if query else "")
    req = Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urlopen(req, timeout=TIMEOUT_S) as response:
            body = response.read()
    except HTTPError as e:
        said = _description(e)
        hint = f": check {TOKENS_ENV}" if e.code in (401, 404) else ""
        raise _BotError(f"bot {bot_id}: the Bot API answered {e.code} to {method}{said}{hint}") from None
    except URLError as e:
        raise _BotError(f"bot {bot_id}: the Bot API did not answer {method} ({_reason(e.reason)})") from None
    except TimeoutError:
        raise _BotError(f"bot {bot_id}: the Bot API did not answer {method} in {TIMEOUT_S}s") from None
    try:
        doc = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise _BotError(f"bot {bot_id}: {method} did not answer with JSON") from None
    if not isinstance(doc, dict) or doc.get("ok") is not True:
        refused = _text(doc.get("description")) if isinstance(doc, dict) else None
        raise _BotError(f"bot {bot_id}: {method} was refused" + (f" ({refused})" if refused else ""))
    return doc.get("result")


def _description(e: HTTPError) -> str:
    """The API's own words for a refusal, ` (…)`, when it gave any; never anything from the URL."""
    try:
        doc = json.loads(e.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return ""
    said = _text(doc.get("description")) if isinstance(doc, dict) else None
    return f" ({said})" if said else ""


def _reason(reason: object) -> str:
    text = str(reason)
    return text if "/bot" not in text else "the connection failed"


def _count(counts: dict[str, int], name: str) -> None:
    counts[name] = counts.get(name, 0) + 1


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
