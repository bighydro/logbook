"""Instagram's "Export your information" archive (JSON) → message/v1, call/v1, photo/v1 and social/v1.

Instagram gives the account's data on request (the app: Accounts Center → Your information and
permissions → Export your information; docs/adapters/instagram.md): a zip, or the folder it unpacks
to, of JSON files. `logbook add instagram <zip|folder>` reads either as it came (nothing is unpacked
to disk); each is sniffed, so a bare `add` finds them too. The folders move between export versions —
`messages/inbox/…` in an older export, `your_instagram_activity/messages/inbox/…` in a newer one,
the followers under `followers_and_following/` or `connections/followers_and_following/` — so every
file is found by its name (`followers_1.json`, `message_3.json`, …), never by a fixed path, and the
same export in either layout, zipped or not, gives the same lines. An export asked for as HTML (the
same names ending `.html`, and no JSON) is one sentence saying to ask for JSON, and nothing is read.

**The encoding.** Meta writes every string as its UTF-8 bytes read as latin-1, so `Båten ⛵` arrives
as `B\\u00c3\\u00a5ten \\u00e2\\u009b\\u00b5`. `fix` reads each string back (encode latin-1, decode
UTF-8), and leaves alone one that is not such bytes; every string of every file read goes through it.

**Direct messages** (`message_<n>.json`, one or more per thread folder, under `inbox/`,
`message_requests/` or `archived_threads/`): one `message/v1` line per message (RFC 0008), tier 2 as
`whatsapp` writes messages, source `instagram`, `at` the message's `timestamp_ms` in UTC, `tz` the
record's own. `chat` is the thread: its `id` the thread's number (the digits after the folder name's
last `_`, else the folder name, which a later export keeps when the folder is renamed), `type`
`group` when more than two people take part, `name` the thread's title. `from_me` when the sender is
the owner (below). The export names people in a thread by their display name only, never by handle:
the sender is `{provider_id, instagram:<display name>, name}`, which `people review` keys by the name
and proposes against the people the record knows by that name (WhatsApp's, the address book's), never
merging on its own. `text` is the content; `media_kind` the first attachment's kind (`image`, `video`,
`voice`, `gif`, `sticker`, `document`, or `link` for a shared post or reel). Under `extra`: `thread`
(the folder), `box`, `participants` (a group's, sorted), `reactions` (`[{reaction, actor}]`), `share`
(`{link, text, owner}` — the post's owner as a handle ref), `media` (`[{path, kind, sha256?,
bytes?}]`: the file's path inside the archive, its digest and size, never copied out; the attach pass
does not read this source yet), `media_missing` when a file is not in the archive or its path would
leave it, and `unsent`. `LOGBOOK_INSTAGRAM_HASH_MEDIA=0` skips the hashing and records only the paths.
`raw_id` is `<thread>:<timestamp_ms>:<sha256 of the content, the shared link, the attachments' file
names and a call's duration>[:16]`, `:<n>` added to a second message identical to the first: the
export gives a message no id, and nothing in the key changes between layouts or when a person
renames themselves, so a newer export adds only what is new. Reactions are not in the key: a
reaction added later is not a new line. A message with nothing in it is skipped and counted
(`skipped_no_body`), as is one timed before Instagram existed (`skipped_bad_date`), and a thread file
that does not parse (`skipped_unreadable_file`).

**Calls.** A message with `call_duration` is a call: one `call/v1` line (RFC 0012), `direction` by
who placed it, `answered` when the duration is more than 0, `end` `at` plus the duration then,
`counterparty` the other person of a direct thread (none for a group), `service` `instagram`, and
under `extra` the `chat` and what the thread said (`Video chat ended`). Tier 2, as the messages it was
read among (`extra.tier_reason`), where RFC 0012 says 1: SPEC §4 lets a producer write higher for a
reason it states.

**The owner** is the `Name` and `Username` of the export's own profile
(`personal_information.json`), and the names and handles of `policy/owner.json` (`owner_aliases`).
When none of those takes part in any thread, the one person in every thread is the owner, and said
(`owner_in_every_chat`); when that is nobody or more than one, `run` raises `Unreadable` naming
`policy/owner.json`, and nothing is read: a message of the owner's is never written as somebody
else's. Nothing else of the profile is read.

**Connections and interactions** are one `social/v1` line each (RFC 0048, draft), tier 2: the act on
the network, its `action`, its `counterpart` as a handle ref `{handle, instagram:<handle>}` (lower
case), the `url` the export gives, a comment's `text`, and under `extra.list` the file it came from.
`at` is the export's timestamp of the act. From the connections: `followed_by` (followers), `follow`
(following), `close_friend`, `block`, `restrict`, `follow_request_sent` (pending and recent follow
requests), `follow_request_received` and `unfollow` (recently unfollowed). From the owner's activity:
`like` (liked posts), `comment` (comments on posts and reels, the media's owner as counterpart),
`story_like` and `search` (profile searches). `raw_id` is `<action>:<timestamp>:<sha256 of the
handle, the url and the text>[:16]`. An entry with no time is skipped and counted
(`skipped_no_timestamp`).

**Own content**: each image or video of the owner's posts, stories and reels is one `photo/v1` line
(RFC 0002), library `instagram`, `asset_id` `instagram:<file name>`, `at` its creation time, `lat` and
`lon` from the EXIF the export kept (0, 0 is no place), `content_hash` the file's digest when it is in
the archive; under `extra` the `post` (`{kind, id, caption?, items}`: one id for every item of one
post) and the `path`. Tier 2 where RFC 0002 says 1 (`extra.tier_reason`): a caption is the owner's
words, and the export does not say who could see the post. `raw_id` is `<kind>:<file name>`.

**Never read**: ads and the advertisers, logins, devices and security, the profile beyond the
owner's name, preferences, topics, and every other file: their names are not on the lists below.
Pure: reads the archive, writes nothing, no network.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
import zlib
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import IO, Any

from . import Unreadable

__all__ = ["NAME", "TIER", "fix", "run", "sniff"]

NAME = "instagram"
TIER = 2  # as `whatsapp` writes messages: someone else's words
MESSAGE, MESSAGE_SCHEMA = "message", "message/v1"
CALL, CALL_SCHEMA = "call", "call/v1"
PHOTO, PHOTO_SCHEMA = "photo", "photo/v1"
SOCIAL, SOCIAL_SCHEMA = "social", "social/v1"

HASH_MEDIA_ENV = "LOGBOOK_INSTAGRAM_HASH_MEDIA"
MARKERS = frozenset({"your_instagram_activity", "followers_and_following"})  # Facebook's export has neither
TOP = frozenset(  # the export's top folders, older and newer: where a media path starts
    {
        "your_instagram_activity",
        "connections",
        "followers_and_following",
        "messages",
        "media",
        "content",
        "likes",
        "comments",
        "story_sticker_interactions",
        "story_interactions",
        "recent_searches",
        "logged_information",
        "personal_information",
        "account_information",
        "ads_information",
        "security_and_login_information",
        "preferences",
        "apps_and_websites_off_of_instagram",
    }
)
BOXES = ("inbox", "message_requests", "archived_threads")
MESSAGE_FILE = re.compile(r"^message_\d+$")
NUMBERED = re.compile(r"_\d+$")  # `followers_1` is `followers`
THREAD_NUMBER = re.compile(r"_(\d+)$")
HANDLE = re.compile(r"^[a-z0-9._]{1,30}$")
PROFILE = "personal_information"
CONNECTIONS = {  # file name, its number dropped → action
    "followers": "followed_by",
    "following": "follow",
    "close_friends": "close_friend",
    "blocked_profiles": "block",
    "blocked_accounts": "block",
    "restricted_profiles": "restrict",
    "restricted_accounts": "restrict",
    "pending_follow_requests": "follow_request_sent",
    "recent_follow_requests": "follow_request_sent",
    "follow_requests_you've_received": "follow_request_received",
    "recently_unfollowed_profiles": "unfollow",
    "recently_unfollowed_accounts": "unfollow",
}
INTERACTIONS = {
    "liked_posts": "like",
    "post_comments": "comment",
    "reels_comments": "comment",
    "story_likes": "story_like",
    "profile_searches": "search",
    "account_searches": "search",
}
CONTENT = {"posts": "post", "stories": "story", "reels": "reel"}
ATTACHMENTS = (  # a message's attachment lists, in the order the first one names `media_kind`
    ("photos", "image"),
    ("videos", "video"),
    ("audio_files", "voice"),
    ("gifs", "gif"),
    ("files", "document"),
)
VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".m4v", ".webm"})
EARLIEST = 1_286_323_200  # 2010-10-06, the day Instagram opened: anything earlier is no time of its
HTML_ASK = (
    "this is an HTML export, which Logbook does not read; ask Instagram for JSON instead (Accounts Center"
    " → Your information and permissions → Export your information → Export to device, Format: JSON,"
    " Date range: All time); nothing read"
)
READ_ERRORS = (OSError, RuntimeError, EOFError, zipfile.BadZipFile, zlib.error)
CHUNK = 1 << 20


# -- the encoding ---------------------------------------------------------------------------------------


def fix(value: Any) -> Any:
    """Meta's strings read back: each one's latin-1 bytes decoded as UTF-8 (`Ã¥` is `å`), in lists
    and objects too; a string that is not such bytes (already right, or outside latin-1) as it is."""
    if isinstance(value, str):
        try:
            return value.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return value
    if isinstance(value, list):
        return [fix(v) for v in value]
    if isinstance(value, dict):
        return {fix(k): fix(v) for k, v in value.items()}
    return value


# -- the archive: a zip or a folder, by its paths' parts ------------------------------------------------


class _Archive:
    """The export's files by their POSIX path inside it: a zip's members, never extracted, or the files
    under a folder."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.zip: zipfile.ZipFile | None = None
        if path.is_dir():
            found = (f for f in path.rglob("*") if f.is_file())
            self.names = sorted(PurePosixPath(f.relative_to(path).as_posix()) for f in found)
        else:
            self.zip = zipfile.ZipFile(path)
            self.names = sorted(PurePosixPath(i.filename) for i in self.zip.infolist() if not i.is_dir())
        self.present = frozenset(self.names)

    def close(self) -> None:
        if self.zip is not None:
            self.zip.close()

    def read(self, name: PurePosixPath) -> bytes:
        if self.zip is not None:
            return self.zip.read(name.as_posix())
        return self.path.joinpath(*name.parts).read_bytes()

    def open(self, name: PurePosixPath) -> IO[bytes]:
        if self.zip is not None:
            return self.zip.open(name.as_posix())
        return self.path.joinpath(*name.parts).open("rb")


def _stem(name: PurePosixPath) -> str:
    return NUMBERED.sub("", name.stem)


def _root(name: PurePosixPath) -> tuple[str, ...]:
    """The parts above the export's first top folder: what a media path in the file is relative to."""
    for i, part in enumerate(name.parts):
        if part in TOP:
            return name.parts[:i]
    return name.parts[:-1]


# -- sniff ----------------------------------------------------------------------------------------------


def sniff(path: Path) -> bool:
    """A zip or a folder with one of Instagram's own folders (`your_instagram_activity`,
    `followers_and_following`): in a folder at its top or one below it, in a zip anywhere. Reads the zip's
    directory and nothing else; never raises."""
    try:
        path = Path(path)
        if path.is_dir():
            return any(_has_marker(child) for child in [path, *(c for c in path.iterdir() if c.is_dir())])
        if not path.is_file() or not zipfile.is_zipfile(path):
            return False
        with zipfile.ZipFile(path) as z:
            return any(MARKERS & set(PurePosixPath(n).parts[:-1]) for n in z.namelist())
    except (*READ_ERRORS, ValueError):
        return False


def _has_marker(folder: Path) -> bool:
    return any((folder / marker).is_dir() for marker in MARKERS) or (
        (folder / "connections" / "followers_and_following").is_dir()
    )


# -- run ------------------------------------------------------------------------------------------------


@dataclass
class _Run:
    archive: _Archive
    counts: dict[str, int]
    hash_media: bool
    owner: frozenset[str] = frozenset()


@dataclass
class _Thread:
    folder: str
    box: str
    root: tuple[str, ...] = ()  # what the thread's media paths are relative to
    title: str | None = None
    participants: set[str] = field(default_factory=set)
    messages: list[Mapping[str, Any]] = field(default_factory=list)
    unreadable: bool = False


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    owner_aliases: Mapping[str, Iterable[str]] | None = None,
) -> Iterator[dict[str, Any]]:
    """The export's lines: messages and calls thread by thread, then the connections, the owner's posts,
    stories and reels, and the interactions. `since` (RFC3339 UTC) leaves out a line before it; `counts`
    tallies what was skipped and noted; `owner_aliases` (`policy/owner.json`) names the owner where the
    export does not. Raises `Unreadable` for an input that is no Instagram export, an HTML one, a zip that
    does not read, or messages with no owner to be found."""
    counts = counts if counts is not None else {}
    path = Path(path)
    if not sniff(path):
        raise Unreadable(f"{path.name}: not an Instagram export (its zip or its folder); nothing read")
    try:
        archive = _Archive(path)
    except READ_ERRORS as e:
        raise Unreadable(
            f"{path.name}: the export could not be read ({type(e).__name__}); nothing read"
        ) from None
    try:
        yield from _lines(path, archive, since, counts, owner_aliases)
    except READ_ERRORS as e:
        raise Unreadable(
            f"{path.name}: the export could not be read ({type(e).__name__}); nothing read"
        ) from None
    finally:
        archive.close()


def _lines(
    path: Path,
    archive: _Archive,
    since: str | None,
    counts: dict[str, int],
    owner_aliases: Mapping[str, Iterable[str]] | None,
) -> Iterator[dict[str, Any]]:
    hash_media = os.environ.get(HASH_MEDIA_ENV, "1").strip() != "0"
    state = _Run(archive, counts, hash_media)
    threads = _threads(state)
    connections = [n for n in archive.names if n.suffix == ".json" and _stem(n) in CONNECTIONS]
    content = [
        n for n in archive.names if n.suffix == ".json" and _stem(n) in CONTENT and not _in_messages(n)
    ]
    interactions = [n for n in archive.names if n.suffix == ".json" and _stem(n) in INTERACTIONS]
    if not (threads or connections or content or interactions):
        if any(_is_html(n) for n in archive.names):
            raise Unreadable(f"{path.name}: {HTML_ASK}")
        raise Unreadable(f"{path.name}: no messages, connections or content in the export; nothing read")
    if threads:
        state.owner = _owner(state, threads, owner_aliases)
    found: Iterator[dict[str, Any]] = _chain(
        (draft for thread in threads for draft in _thread(state, thread)),
        (draft for name in connections for draft in _social(state, name, CONNECTIONS[_stem(name)])),
        (draft for name in content for draft in _content(state, name, CONTENT[_stem(name)])),
        (draft for name in interactions for draft in _social(state, name, INTERACTIONS[_stem(name)])),
    )
    for draft in found:
        if not (since and draft["at"] < since):
            yield draft


def _chain(*parts: Iterable[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for part in parts:
        yield from part


def _is_html(name: PurePosixPath) -> bool:
    stem = _stem(name)
    return name.suffix == ".html" and (
        MESSAGE_FILE.match(name.stem) is not None
        or stem in CONNECTIONS
        or stem in CONTENT
        or stem in INTERACTIONS
    )


def _in_messages(name: PurePosixPath) -> bool:
    return "messages" in name.parts[:-1]


def _count(counts: dict[str, int], key: str, n: int = 1) -> None:
    counts[key] = counts.get(key, 0) + n


def _load(state: _Run, name: PurePosixPath) -> Any:
    """The file's JSON with its strings fixed, or None (counted) when it does not parse."""
    try:
        return fix(json.loads(state.archive.read(name).decode("utf-8-sig")))
    except (UnicodeDecodeError, ValueError, RecursionError):
        _count(state.counts, "skipped_unreadable_file")
        return None


def _entries(data: Any) -> list[Any]:
    """A file's entries: the list it is, or the first list among its object's values
    (`{"relationships_following": [...]}`)."""
    if isinstance(data, list):
        return data
    if isinstance(data, Mapping):
        for value in data.values():
            if isinstance(value, list):
                return value
    return []


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _rfc3339(seconds: object) -> str | None:
    if not isinstance(seconds, int | float) or isinstance(seconds, bool) or seconds < EARLIEST:
        return None
    try:
        return datetime.fromtimestamp(int(seconds), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return None


def _digest(*parts: object) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def _handle(value: object) -> dict[str, str] | None:
    """`{handle, instagram:<handle>}`, lower case; None for what is no handle (a 👍, a blank)."""
    text = _text(value)
    if text is None:
        return None
    text = text.removeprefix("@").casefold()
    return {"kind": "handle", "value": f"{NAME}:{text}"} if HANDLE.match(text) else None


def _draft(at: str, kind: str, payload: dict[str, Any], end: str | None = None) -> dict[str, Any]:
    return {"at": at, "end": end, "tz": None, "source": NAME, "kind": kind, "tier": TIER, "payload": payload}


# -- media ----------------------------------------------------------------------------------------------


def _member(state: _Run, root: tuple[str, ...], uri: object) -> PurePosixPath | None:
    """The archive's file a media path names, relative to the export's root; None when the path would
    leave the archive or names no file in it."""
    text = _text(uri)
    if text is None or text.startswith("/") or "://" in text:
        return None
    parts = PurePosixPath(text).parts
    if not parts or any(part in ("..", "") for part in parts):
        return None
    name = PurePosixPath(*root, *parts)
    return name if name in state.archive.present else None


def _media(
    state: _Run, root: tuple[str, ...], uri: object, kind: str | None = None
) -> tuple[dict[str, Any], bool]:
    """(`{path, kind?, sha256?, bytes?}`, found): the file by its path in the archive, hashed unless
    hashing is off; counted as hashed or missing."""
    given = _text(uri) or ""
    media: dict[str, Any] = {"path": given}
    if kind is not None:
        media["kind"] = kind
    member = _member(state, root, uri)
    if member is None:
        _count(state.counts, "media_missing")
        return media, False
    if state.hash_media:
        h, size = hashlib.sha256(), 0
        with state.archive.open(member) as fh:
            while chunk := fh.read(CHUNK):
                h.update(chunk)
                size += len(chunk)
        media["sha256"], media["bytes"] = h.hexdigest(), size
        _count(state.counts, "media_hashed")
    return media, True


# -- messages and calls ---------------------------------------------------------------------------------


def _threads(state: _Run) -> list[_Thread]:
    """Every thread, its `message_<n>.json` files read together, in the order of their folders."""
    by_folder: dict[tuple[str, ...], _Thread] = {}
    for name in state.archive.names:
        if name.suffix != ".json" or not MESSAGE_FILE.match(name.stem) or len(name.parts) < 3:
            continue
        box = name.parts[-3]
        if box not in BOXES or not _in_messages(name):
            continue
        folder = name.parts[:-1]
        thread = by_folder.setdefault(folder, _Thread(folder=name.parts[-2], box=box))
        thread.root = _root(name)
        data = _load(state, name)
        if not isinstance(data, Mapping):
            thread.unreadable = True
            continue
        thread.title = thread.title or _text(data.get("title"))
        for person in data.get("participants") or []:
            who = _text(person.get("name")) if isinstance(person, Mapping) else None
            if who is not None:
                thread.participants.add(who)
        thread.messages.extend(m for m in data.get("messages") or [] if isinstance(m, Mapping))
    return [t for t in by_folder.values() if t.messages or not t.unreadable]


def _owner(
    state: _Run, threads: list[_Thread], owner_aliases: Mapping[str, Iterable[str]] | None
) -> frozenset[str]:
    """The owner's names, folded: the profile's and policy/owner.json's when one of them takes part in a
    thread; else the one person in every thread (counted as a guess). Raises `Unreadable` when neither
    names the owner."""
    named = set(_profile(state))
    for key in ("names", "handles"):
        for value in (owner_aliases or {}).get(key) or []:
            if isinstance(value, str) and value.strip():
                named.add(_fold(value.removeprefix("@").removeprefix(f"{NAME}:")))
    seen = {_fold(p) for t in threads for p in t.participants}
    seen |= {_fold(str(m.get("sender_name"))) for t in threads for m in t.messages if m.get("sender_name")}
    if named & seen:
        return frozenset(named)
    every = [{_fold(p) for p in t.participants} for t in threads if t.participants]
    common = set.intersection(*every) if every else set()
    if len(common) == 1:
        _count(state.counts, "owner_in_every_chat")
        return frozenset(common)
    raise Unreadable(
        "the export does not say which person in the messages is you (no profile, and no one name in every"
        ' thread): add your name as Instagram shows it to policy/owner.json ({"names": ["…"]}); nothing read'
    )


def _profile(state: _Run) -> list[str]:
    """The `Name` and `Username` of the export's own profile, folded; nothing else of it is read."""
    found: list[str] = []
    for name in state.archive.names:
        if name.name != f"{PROFILE}.json":
            continue
        data = _load(state, name)
        for entry in _entries(data):
            values = entry.get("string_map_data") if isinstance(entry, Mapping) else None
            for key in ("Name", "Username"):
                item = values.get(key) if isinstance(values, Mapping) else None
                text = _text(item.get("value")) if isinstance(item, Mapping) else None
                if text is not None:
                    found.append(_fold(text))
    return found


def _fold(name: str) -> str:
    return " ".join(name.split()).casefold()


def _thread(state: _Run, thread: _Thread) -> Iterator[dict[str, Any]]:
    number = THREAD_NUMBER.search(thread.folder)
    key = number.group(1) if number else thread.folder
    group = len(thread.participants) > 2
    chat: dict[str, Any] = {"id": key, "type": "group" if group else "direct"}
    if thread.title is not None:
        chat["name"] = thread.title
    others = sorted(p for p in thread.participants if _fold(p) not in state.owner)
    used: dict[str, int] = {}
    ordered = sorted(thread.messages, key=lambda m: _number(m.get("timestamp_ms")) or 0.0)
    for message in ordered:
        ms = _number(message.get("timestamp_ms"))
        at = _rfc3339(ms / 1000) if ms is not None else None
        if ms is None or at is None:
            _count(state.counts, "skipped_bad_date")
            continue
        draft = _message(state, thread, chat, others, thread.root, message, at, int(ms), used, key)
        if draft is not None:
            yield draft


def _number(value: object) -> float | None:
    """A number as JSON gave it (never a boolean), else None."""
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _message(
    state: _Run,
    thread: _Thread,
    chat: dict[str, Any],
    others: list[str],
    root: tuple[str, ...],
    message: Mapping[str, Any],
    at: str,
    ms: int,
    used: dict[str, int],
    key: str,
) -> dict[str, Any] | None:
    sender = _text(message.get("sender_name"))
    from_me = sender is not None and _fold(sender) in state.owner
    body = _text(message.get("content"))
    share = message.get("share") if isinstance(message.get("share"), Mapping) else None
    files: list[tuple[str, object]] = []
    for field_name, kind in ATTACHMENTS:
        for item in message.get(field_name) or []:
            if isinstance(item, Mapping):
                files.append((kind, item.get("uri")))
    sticker = message.get("sticker")
    if isinstance(sticker, Mapping):
        files.append(("sticker", sticker.get("uri")))
    duration = message.get("call_duration")
    link = _text(share.get("link")) if share is not None else None
    names = [PurePosixPath(str(uri)).name for _kind, uri in files]
    seconds = _number(duration)
    raw_id = f"{key}:{ms}:{_digest(body, link, names, duration if seconds is not None else None)}"
    used[raw_id] = used.get(raw_id, 0) + 1
    if used[raw_id] > 1:
        raw_id = f"{raw_id}:{used[raw_id]}"
    if seconds is not None:
        return _call(thread, chat, others, at, raw_id, from_me, int(seconds), body)
    if body is None and not files and share is None:
        _count(state.counts, "skipped_no_body")
        return None
    payload: dict[str, Any] = {
        "schema": MESSAGE_SCHEMA,
        "raw_id": raw_id,
        "chat": dict(chat),
        "from_me": from_me,
    }
    if not from_me and sender is not None:
        payload["sender"] = {"kind": "provider_id", "value": f"{NAME}:{sender}", "name": sender}
    if body is not None:
        payload["text"] = body
    if files:
        payload["media_kind"] = files[0][0]
    elif share is not None:
        payload["media_kind"] = "link"
    extra: dict[str, Any] = {"thread": thread.folder, "box": thread.box}
    if chat["type"] == "group":
        extra["participants"] = sorted(thread.participants)
    reactions = [
        {"reaction": r["reaction"], "actor": r["actor"]}
        for r in message.get("reactions") or []
        if isinstance(r, Mapping) and _text(r.get("reaction")) and _text(r.get("actor"))
    ]
    if reactions:
        extra["reactions"] = reactions
    if share is not None:
        shared: dict[str, Any] = {}
        if link is not None:
            shared["link"] = link
        if _text(share.get("share_text")) is not None:
            shared["text"] = share["share_text"]
        owner = _handle(share.get("original_content_owner"))
        if owner is not None:
            shared["owner"] = owner
        extra["share"] = shared
    if files:
        media = [_media(state, root, uri, kind) for kind, uri in files]
        extra["media"] = [m for m, _found in media]
        if not all(found for _m, found in media):
            extra["media_missing"] = True
    if message.get("is_unsent") is True:
        extra["unsent"] = True
    payload["extra"] = extra
    return _draft(at, MESSAGE, payload)


def _call(
    thread: _Thread,
    chat: dict[str, Any],
    others: list[str],
    at: str,
    raw_id: str,
    from_me: bool,
    duration: int,
    text: str | None,
) -> dict[str, Any]:
    answered = duration > 0
    payload: dict[str, Any] = {
        "schema": CALL_SCHEMA,
        "raw_id": raw_id,
        "direction": "outgoing" if from_me else "incoming",
        "answered": answered,
        "duration_s": max(duration, 0),
        "service": NAME,
    }
    if chat["type"] == "direct" and len(others) == 1:
        payload["counterparty"] = {"kind": "provider_id", "value": f"{NAME}:{others[0]}"}
    extra: dict[str, Any] = {
        "chat": dict(chat),
        "box": thread.box,
        "tier_reason": "read from direct messages",
    }
    if text is not None:
        extra["text"] = text
    payload["extra"] = extra
    end = None
    if answered:
        end = datetime.fromtimestamp(_seconds(at) + duration, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return _draft(at, CALL, payload, end)


def _seconds(at: str) -> int:
    return int(datetime.strptime(at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp())


# -- connections and interactions -----------------------------------------------------------------------


def _social(state: _Run, name: PurePosixPath, action: str) -> Iterator[dict[str, Any]]:
    """One social/v1 line per act a list file holds: `string_list_data` items (a follower, a like),
    or one `string_map_data` (a comment, a search)."""
    for entry in _entries(_load(state, name)):
        if not isinstance(entry, Mapping):
            continue
        title = entry.get("title")
        values = entry.get("string_map_data")
        if isinstance(values, Mapping):
            yield from _one(state, name, action, *_from_map(values, title))
        for item in entry.get("string_list_data") or []:
            if isinstance(item, Mapping):
                ref = _handle(title) or _handle(item.get("value"))
                yield from _one(
                    state, name, action, ref, _text(item.get("href")), None, item.get("timestamp")
                )


def _from_map(
    values: Mapping[str, Any], title: object
) -> tuple[dict[str, str] | None, str | None, str | None, object]:
    """(counterpart, url, text, time) from a `string_map_data`: a comment's `Media Owner` and `Comment`, a
    search's `Search`, the act's `Time`."""

    def value(key: str, part: str = "value") -> object:
        item = values.get(key)
        return item.get(part) if isinstance(item, Mapping) else None

    ref = _handle(value("Media Owner")) or _handle(value("Search")) or _handle(title)
    url = _text(value("Search", "href"))
    return ref, url, _text(value("Comment")), value("Time", "timestamp")


def _one(
    state: _Run,
    name: PurePosixPath,
    action: str,
    ref: dict[str, str] | None,
    url: str | None,
    text: str | None,
    seconds: object,
) -> Iterator[dict[str, Any]]:
    when = _number(seconds)
    if not when:  # absent, or the 0 the export writes for no time
        _count(state.counts, "skipped_no_timestamp")
        return
    at = _rfc3339(when)
    if at is None:
        _count(state.counts, "skipped_bad_date")
        return
    if ref is None and url is None and text is None:
        _count(state.counts, "skipped_no_counterpart")
        return
    payload: dict[str, Any] = {
        "schema": SOCIAL_SCHEMA,
        "raw_id": f"{action}:{int(when)}:{_digest(ref['value'] if ref else None, url, text)}",
        "network": NAME,
        "action": action,
    }
    if ref is not None:
        payload["counterpart"] = ref
    if url is not None:
        payload["url"] = url
    if text is not None:
        payload["text"] = text
    payload["extra"] = {"list": _stem(name)}
    yield _draft(at, SOCIAL, payload)


# -- the owner's posts, stories and reels ---------------------------------------------------------------


def _content(state: _Run, name: PurePosixPath, kind: str) -> Iterator[dict[str, Any]]:
    root = _root(name)
    for entry in _entries(_load(state, name)):
        if not isinstance(entry, Mapping):
            continue
        given = entry.get("media")
        items = [
            i
            for i in (given if isinstance(given, list) else [entry])
            if isinstance(i, Mapping) and _text(i.get("uri"))
        ]
        if not items:
            continue
        caption = _text(entry.get("title")) or next((t for i in items if (t := _text(i.get("title")))), None)
        post: dict[str, Any] = {"kind": kind, "id": f"{kind}:{PurePosixPath(str(items[0]['uri'])).name}"}
        if caption is not None:
            post["caption"] = caption
        post["items"] = len(items)
        for item in items:
            at = _rfc3339(item.get("creation_timestamp")) or _rfc3339(entry.get("creation_timestamp"))
            if at is None:
                _count(state.counts, "skipped_bad_date")
                continue
            yield _photo(state, root, kind, item, at, post)


def _photo(
    state: _Run, root: tuple[str, ...], kind: str, item: Mapping[str, Any], at: str, post: dict[str, Any]
) -> dict[str, Any]:
    uri = str(item["uri"]).strip()
    file_name = PurePosixPath(uri).name
    payload: dict[str, Any] = {
        "schema": PHOTO_SCHEMA,
        "raw_id": f"{kind}:{file_name}",
        "asset_id": f"{NAME}:{file_name}",
        "library": NAME,
        "file_name": file_name,
        "media": "video" if PurePosixPath(file_name).suffix.casefold() in VIDEO_SUFFIXES else "image",
        "provenance": "other",
    }
    place = _place(item.get("media_metadata"))
    if place is not None:
        payload["lat"], payload["lon"] = place
    media, found = _media(state, root, uri)
    if "sha256" in media:
        payload["content_hash"] = media["sha256"]
    extra: dict[str, Any] = {"post": dict(post), "path": uri}
    if not found:
        extra["media_missing"] = True
    extra["tier_reason"] = "a caption is the owner's words, and the export does not say who could see it"
    payload["extra"] = extra
    return _draft(at, PHOTO, payload)


def _place(metadata: object) -> tuple[float, float] | None:
    """The first latitude and longitude the media's EXIF gives, when it is a place (0, 0 is none)."""
    if not isinstance(metadata, Mapping):
        return None
    for kind in metadata.values():
        exif = kind.get("exif_data") if isinstance(kind, Mapping) else None
        for row in exif if isinstance(exif, list) else []:
            if not isinstance(row, Mapping):
                continue
            lat, lon = _number(row.get("latitude")), _number(row.get("longitude"))
            if lat is None or lon is None or (lat, lon) == (0, 0):
                continue
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return lat, lon
    return None
