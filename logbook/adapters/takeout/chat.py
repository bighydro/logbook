"""Google Takeout Google Chat/ → message/v1 (RFC 0008).

Takeout writes `Takeout/Google Chat/Groups/<DM xxxx | Space xxxx>/messages.json`, one folder per
conversation, with `group_info.json` (`{name?, members: [{name, email, user_type}]}`) beside it and
the attached files in the same folder under their `export_name`; and `Takeout/Google Chat/Users/<User
xxxx>/user_info.json` (`{user: {name, email, user_type}}`), the owner. `messages.json` is
`{"messages": [{creator: {name, email, user_type}, created_date: "Wednesday, June 10, 2026 at
11:30:05 AM UTC", text?, topic_id?, message_id?, attached_files?: [{original_name, export_name}],
reactions?: [{emoji: {unicode}, reactor_emails}], annotations?: [{url_metadata: {url: {…}, title}}]}]}`.
The input is the `Google Chat/` folder, its `Groups/`, one conversation's folder, or a `messages.json`.

One line per message: kind `message`, tier 2 (RFC 0008, MUST), source `google-takeout`, `at` the
`created_date` in UTC, `tz` the record's zone. `chat` is `{id: the folder's name, type, name}`: a
folder named `DM …` or with two members is `direct`, named for the other member, anything else
`group`, named by `group_info.json`. `from_me` is whether the creator's email is the owner's: the
owner is `owner_emails` (`logbook.json`, passed by `logbook add`) when set, else the one user under
`Users/`; with neither, nobody is the owner, every message reads as received and that is counted
(`no_owner`). `sender` is the creator as `{kind: email, value, name}` when not from me; never
resolved here (RFC 0006). `raw_id` is `chat:<message_id>`; a message without one is keyed
`chat:<created_date as spelled>:<sha256(text)[:16]>` and counted. A message with no text and no file
is skipped and counted; one with no date too.

An attached file beside the message is hashed and the line carries `media` `{sha256, bytes,
media_type}` (the first file; every name under `extra.attached_files`); with `attachments=True`
(`--attachments`) the bytes go to the SPEC §1.1 store and `media` gains `path`. A file the export
does not hold leaves `media` out, `media_kind` says what it was, counted. Reactions are kept as
`extra.reactions` `[{emoji, count}]`, link annotations as `extra.links`, the topic as
`extra.topic_id`. Pure: no network, never writes the source.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from ...core.attachments import DIR as ATTACHMENTS_DIR
from . import SOURCE, times

NAME = "google-takeout-chat"
KIND = "message"
TIER = 2
SCHEMA = "message/v1"
FOLDER = "Google Chat"
GROUPS = "Groups"
USERS = "Users"
MESSAGES = "messages.json"
GROUP_INFO = "group_info.json"
USER_INFO = "user_info.json"

SNIFF_BYTES = 4096
MEDIA_KINDS = {"image": "image", "video": "video", "audio": "audio"}
Draft = dict[str, Any]


def sniff(path: Path) -> bool:
    """A conversation's `messages.json`, its folder, a `Groups/` of them, or the `Google Chat/`
    folder above. Never raises."""
    path = Path(path)
    try:
        return bool(_conversations(path)) if path.is_dir() else _is_messages(path)
    except OSError:
        return False


def _is_messages(path: Path) -> bool:
    if not path.is_file() or path.name != MESSAGES:
        return False
    with path.open("rb") as fh:
        head = fh.read(SNIFF_BYTES)
    return head.lstrip().startswith(b"{") and b'"messages"' in head and b'"creator"' in head


def _conversations(folder: Path) -> list[Path]:
    """The conversation folders under `folder`: itself, its children, or the children of its
    `Groups/`, whichever hold a `messages.json`."""
    if _is_messages(folder / MESSAGES):
        return [folder]
    groups = folder / GROUPS if (folder / GROUPS).is_dir() else folder
    return sorted(d for d in groups.iterdir() if d.is_dir() and _is_messages(d / MESSAGES))


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
    owner_emails: list[str] | None = None,
    attachments: bool | None = None,
    store: Callable[[bytes], object] | None = None,
) -> Iterator[Draft]:
    """One message/v1 line draft per message under `path`, oldest first. `since` is RFC3339 UTC;
    `timezone` is the record's zone; `owner_emails` names the owner (else `Users/` does)."""
    counts = counts if counts is not None else {}
    path = Path(path)
    folders = [path.parent] if path.is_file() else _conversations(path)
    owner = {e.strip().lower() for e in owner_emails or [] if e.strip()} or _owner(path)
    if not owner:
        _count(counts, "no_owner")
    tz = timezone or "UTC"
    drafts: list[Draft] = []
    for folder in folders:
        drafts.extend(_messages(folder, owner, tz, bool(attachments), counts))
    for draft in sorted(drafts, key=lambda d: (d["at"], d["payload"]["raw_id"])):
        blobs: list[bytes] = draft.pop("_blobs")
        if since is not None and draft["at"] < since:
            continue
        if store is not None:
            for blob in blobs:
                store(blob)
        yield draft


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _owner(path: Path) -> set[str]:
    """The owner's email from `Users/*/user_info.json`, looked for beside `Groups/` from wherever
    the input is: the product folder, `Groups/`, a conversation, or its `messages.json`."""
    for candidate in (path, *path.parents[:3]):
        users = candidate / USERS
        if not users.is_dir():
            continue
        found: set[str] = set()
        for info in sorted(users.glob(f"*/{USER_INFO}")):
            data = _json(info)
            user = data.get("user") if isinstance(data, dict) else None
            email = str(user.get("email") or "").strip().lower() if isinstance(user, dict) else ""
            if email:
                found.add(email)
        return found
    return set()


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _messages(
    folder: Path, owner: set[str], tz: str, keep_files: bool, counts: dict[str, int]
) -> Iterator[Draft]:
    data = _json(folder / MESSAGES)
    entries = data.get("messages") if isinstance(data, dict) else None
    chat = _chat(folder, owner)
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        at, spelled = times.parse(entry.get("created_date"))
        text: str = entry["text"] if isinstance(entry.get("text"), str) else ""
        files = [f for f in entry.get("attached_files") or [] if isinstance(f, dict) and f.get("export_name")]
        if not text.strip() and not files:
            _count(counts, "skipped_no_body")
            continue
        if at is None:
            _count(counts, "skipped_no_timestamp")
            continue
        creator: dict[str, Any] = entry["creator"] if isinstance(entry.get("creator"), dict) else {}
        email = str(creator.get("email") or "").strip().lower()
        message_id = str(entry.get("message_id") or "").strip()
        if message_id:
            raw_id = f"chat:{message_id}"
        else:
            raw_id = f"chat:{spelled}:{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}"
            _count(counts, "no_chat_message_id")
        payload: dict[str, Any] = {"schema": SCHEMA, "raw_id": raw_id, "chat": chat}
        payload["from_me"] = bool(email) and email in owner
        if not payload["from_me"] and email:
            sender: dict[str, str] = {"kind": "email", "value": email}
            name = " ".join(str(creator.get("name") or "").split())
            if name:
                sender["name"] = name
            payload["sender"] = sender
        if text.strip():
            payload["text"] = text.replace("\r\n", "\n")
        blobs: list[bytes] = []
        extra: dict[str, Any] = {}
        if files:
            media, kind, blob = _media(folder, str(files[0]["export_name"]), keep_files, counts)
            if media is not None:
                payload["media"] = media
            payload["media_kind"] = kind
            if blob is not None:
                blobs.append(blob)
            extra["attached_files"] = [str(f["export_name"]) for f in files]
        topic = str(entry.get("topic_id") or "").strip()
        if topic:
            extra["topic_id"] = topic
        reactions = [
            {"emoji": str(r["emoji"].get("unicode") or ""), "count": len(r.get("reactor_emails") or [])}
            for r in entry.get("reactions") or []
            if isinstance(r, dict) and isinstance(r.get("emoji"), dict)
        ]
        if reactions:
            extra["reactions"] = reactions
        links = _links(entry.get("annotations"))
        if links:
            extra["links"] = links
        if extra:
            payload["extra"] = extra
        yield {
            "at": at,
            "end": None,
            "tz": tz,
            "source": SOURCE,
            "kind": KIND,
            "tier": TIER,
            "payload": payload,
            "_blobs": blobs,
        }


def _chat(folder: Path, owner: set[str]) -> dict[str, str]:
    """`{id, type, name}`: the folder's name is the id; a `DM …` folder or a two-member group is
    direct and named for the other member, anything else a group named by `group_info.json`."""
    info = _json(folder / GROUP_INFO)
    info = info if isinstance(info, dict) else {}
    members = [m for m in info.get("members") or [] if isinstance(m, dict)]
    chat: dict[str, str] = {"id": folder.name}
    direct = folder.name.startswith("DM ") or (len(members) == 2 and not info.get("name"))
    chat["type"] = "direct" if direct else "group"
    name = " ".join(str(info.get("name") or "").split())
    if not name and direct:
        others = [m for m in members if str(m.get("email") or "").strip().lower() not in owner]
        name = " ".join(str((others or members or [{}])[0].get("name") or "").split())
    if name:
        chat["name"] = name
    return chat


def _media(
    folder: Path, name: str, keep_files: bool, counts: dict[str, int]
) -> tuple[dict[str, Any] | None, str, bytes | None]:
    """(`media` reference or None, `media_kind`, the bytes to store or None) for the file `name`
    beside the messages."""
    media_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    kind = MEDIA_KINDS.get(media_type.split("/")[0], "document")
    file = folder / Path(name).name  # never a path out of the folder
    if not file.is_file():
        _count(counts, "media_missing")
        return None, kind, None
    data = file.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    media: dict[str, Any] = {"sha256": sha256, "bytes": len(data), "media_type": media_type}
    if keep_files:
        media["path"] = f"{ATTACHMENTS_DIR}/{sha256}"
        _count(counts, "media_stored")
        return media, kind, data
    _count(counts, "media_hashed")
    return media, kind, None


def _links(annotations: object) -> list[dict[str, str]]:
    """`[{url, title?}]` from the url annotations; Takeout wraps the url in one long-named key."""
    found: list[dict[str, str]] = []
    for note in annotations if isinstance(annotations, list) else []:
        meta = note.get("url_metadata") if isinstance(note, dict) else None
        if not isinstance(meta, dict):
            continue
        url_field = meta.get("url")
        url = ""
        if isinstance(url_field, dict):
            url = next((str(v) for v in url_field.values() if isinstance(v, str) and v), "")
        elif isinstance(url_field, str):
            url = url_field
        if not url:
            continue
        link = {"url": url}
        title = " ".join(str(meta.get("title") or "").split())
        if title:
            link["title"] = title
        found.append(link)
    return found
