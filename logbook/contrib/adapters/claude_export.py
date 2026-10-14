"""The Claude apps' data export → transcript/v1 (RFC 0004): one line per conversation with the owner.

The owner talks to Claude in the apps (the web, the desktop and the phone), and those conversations
are part of the record in the shape Claude Code's sessions already are (`claude_code`, #279): the
owner's words at their tier, the assistant's beside them marked as machine text
(`logbook.core.machine`), never as a person's. The apps give the account's data on request
(Settings → Privacy → Export data): a zip holding `conversations.json`, a JSON array with one object
per conversation (`uuid`, `name`, `created_at`, `updated_at`, `chat_messages`), `projects.json`
when the account has projects (`uuid`, `name`, and a description, a prompt and documents of their
own) and `users.json` (the account: a name, an address, a number). A chat message has a `sender`
(`human` or `assistant`), `created_at`, `content` (blocks: `text`, `thinking`, `tool_use`,
`tool_result`, …), `text` (what the apps show, a placeholder for every block the export cannot
render), `attachments` (a file the owner gave, with the text extracted from it) and `files` or
`files_v2` (an image or a document uploaded, by name; the second with its kind, previews and links).

`logbook add claude-export <zip|folder|conversations.json>` reads the zip as it came (nothing is
unpacked to disk), the folder it unpacks to, or the file; each is sniffed, so a bare `add` finds
them too. A conversation that is not an object with a `uuid` and a list of messages (each an
object), or that has no time, is skipped and counted (`skipped_malformed`); one with no words in it
is counted (`skipped_empty`). When the export gives the conversation's leaf
(`current_leaf_message_uuid`) and every message its parent (`parent_message_uuid`), only the branch
the conversation stands on is read, and a message left on another (a prompt edited, an answer asked
for again) is counted (`skipped_branch`); else every message, in the export's order.

**The turns.** The owner's turns are the `text` blocks of the `human` messages, the assistant's the
`text` blocks of the `assistant` messages; a message without blocks (an export older than them)
gives `text` alone, read without its placeholders. Never kept, and never anyone's words: thinking;
a tool call's input (an artifact's content, a search's query), counted by the tool's name
(`tool_calls`, `tools`); a tool's result; the thinking and the artifacts an export from before
artifacts were tool calls writes inline (`<antThinking>`, `<antArtifact>`), each artifact counted
under `artifacts`; an attachment's extracted text and an uploaded file, named and counted
(`attachments`: name, type — the export's, else the name's suffix — and size; `files_v2` in place of
`files` when a message has both, never its previews or links); the conversation's own summary; a
message from neither side, counted (`skipped_unknown_sender`). A name (a file's, a tool's, a
project's, the conversation's) is cut at 255 characters. Of `projects.json` only a project's name is
read, and `users.json` never.

**The line.** As `claude_code` writes one: kind `transcript`, tier 2 (`--tier` sets another for a
run), source and provider `claude`, `participants` `[{"name": "owner"}, {"name": "assistant",
"machine": true}]`, `content` the turns as JSON stored once under their digest (SPEC §1.1), `at` and
`end` the first and last message (the conversation's own times when the messages have none),
`title` the conversation's name, else the first line of the owner's first turn, `raw_id`
`claude:<conversation uuid>`. Under `extra`: `conversation`, `project` (its name, when the
conversation names a project the export lists), `created_at` and `updated_at` (the conversation's),
`tool_calls`, `tools`, `attachments`, `words` (`{owner, machine}`), the counterpart (`{kind: agent,
ref: {provider_id, claude}, name: Claude}`), and the transcript counts every transcript has.

**A conversation that grew.** Run with the record's `existing` lines (`claude_code.versioned`), a
conversation whose text differs from the line standing for it is a new line, `raw_id` suffixed
`:v2` (`:v3` …), that supersedes the line before (`grown`); an unchanged one is the same line and
nothing is written (`conversations_unchanged`), nor for one older than the record's (a text a
version already holds, or a conversation that ends before the latest version: an earlier export
added after a later one, `conversations_older`). `conversations` counts every conversation of the
export and `conversations_new` those the record has no line for, so a dry run says them all; one
that ended before `since` is counted (`skipped_before_since`). Pure: reads the export, writes
nothing but through `store`, no network.
"""

from __future__ import annotations

import json
import re
import zipfile
import zlib
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from ...core.attachments import reference
from ...core.transcripts import Turn
from . import Unreadable
from .claude_code import (
    ASSISTANT,
    GROWN,
    MEDIA_TYPE,
    NEW,
    OLDER,
    OWNER,
    PARTICIPANTS,
    TIER,
    UNCHANGED,
    Existing,
    first_words,
    say,
    stamp,
    stored,
    versioned,
    words,
)
from .transcript import KIND, draft

__all__ = ["KIND", "NAME", "TIER", "run", "sniff"]

NAME = "claude"
COUNTERPART = {"kind": "agent", "ref": {"kind": "provider_id", "value": NAME}, "name": "Claude"}
CONVERSATIONS = "conversations.json"
PROJECTS = "projects.json"
SENDERS = {"human": OWNER, "assistant": ASSISTANT}
SNIFF_BYTES = 65536
SNIFF_KEY = b'"chat_messages"'
# what `text` holds in place of a block the export cannot render: never anyone's words
PLACEHOLDER = re.compile(
    r"```[^\n`]*\n\s*(?:This block is not supported on your current device yet\.|Viewing artifacts created"
    r" via the Analysis Tool web feature preview isn't yet supported on mobile\.)\s*\n```"
)
# what an export from before artifacts were tool calls writes in the text: the thinking and each
# artifact whole, never anyone's words (an artifact is counted as the tool call it later became)
THINKING = re.compile(r"<antThinking>[\s\S]*?(?:</antThinking>|\Z)")
ARTIFACT = re.compile(r"<antArtifact\b[^>]*>[\s\S]*?(?:</antArtifact>|\Z)")
ARTIFACTS = "artifacts"  # the tool's name for an artifact, as the export's tool_use blocks give it
NAME_CHARS = 255  # a file's, a tool's, a project's or a conversation's name, at most
NOTED = {
    NEW: "conversations_new",
    GROWN: "grown",
    UNCHANGED: "conversations_unchanged",
    OLDER: "conversations_older",
}
READ_ERRORS = (OSError, RuntimeError, EOFError, zipfile.BadZipFile, zlib.error)  # a damaged zip, a disk


# -- sniff -------------------------------------------------------------------------------------------


def sniff(path: Path) -> bool:
    """The export's zip, the folder it unpacks to, or its `conversations.json`: a JSON array whose
    head has `chat_messages` (another app's `conversations.json` has none). Reads the head of one
    file at most; never raises."""
    try:
        path = Path(path)
        if path.is_dir():
            return _looks(path / CONVERSATIONS)
        if not path.is_file():
            return False
        if path.name == CONVERSATIONS:
            return _looks(path)
        if not zipfile.is_zipfile(path):
            return False
        with zipfile.ZipFile(path) as z:
            member = _member(z, CONVERSATIONS)
            if member is None:
                return False
            with z.open(member) as fh:
                return _is_head(fh.read(SNIFF_BYTES))
    except (*READ_ERRORS, ValueError):
        return False


def _looks(file: Path) -> bool:
    if not file.is_file():
        return False
    with file.open("rb") as fh:
        return _is_head(fh.read(SNIFF_BYTES))


def _is_head(head: bytes) -> bool:
    return head.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"[") and SNIFF_KEY in head


def _member(z: zipfile.ZipFile, name: str, beside: PurePosixPath | None = None) -> str | None:
    """The zip's member called `name` nearest its root (in the folder `beside`, when given), by its
    path's parts; never extracted."""
    found = [
        info.filename
        for info in z.infolist()
        if not info.is_dir()
        and PurePosixPath(info.filename).name == name
        and (beside is None or PurePosixPath(info.filename).parent == beside)
    ]
    return min(found, key=lambda f: (len(PurePosixPath(f).parts), f)) if found else None


# -- run ---------------------------------------------------------------------------------------------


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    tier: int | None = None,
    store: Callable[[bytes], object] | None = None,
    existing: Existing | None = None,
) -> Iterator[dict[str, Any]]:
    """One transcript/v1 line draft per conversation of the export at `path` (its zip, its folder or
    its `conversations.json`), in the export's order. `since` (RFC3339 UTC) leaves out a
    conversation that ended before it; `tier` replaces 2 for the run; `store` is given the text's
    bytes just before its line; `existing` (the record's lines by (source, raw_id)) makes a grown
    conversation a correction and says which are new, unchanged or older than the record's line
    (an earlier export, never written back over a later one). Raises `Unreadable` for
    an input that holds no export, or one that does not parse."""
    counts = counts if counts is not None else {}
    data, projects_data = _read(Path(path))
    projects = _projects(projects_data)
    for conversation in _conversations(data):
        _count(counts, "conversations")
        found = _conversation(conversation, projects, counts, tier or TIER)
        if found is None:
            continue
        line, text = found
        if since and str(line["end"] or line["at"]) < since:
            _count(counts, "skipped_before_since")
            continue
        line, how = versioned(line, existing)
        if existing is not None:
            _count(counts, NOTED[how])
        if store is not None:
            store(text)
        yield line


def _read(path: Path) -> tuple[bytes, bytes | None]:
    """The bytes of `conversations.json` and of the `projects.json` beside it (None when absent)."""
    try:
        if path.is_dir():
            return _file(path / CONVERSATIONS, path), _optional(path / PROJECTS)
        if path.is_file() and path.name == CONVERSATIONS:
            return path.read_bytes(), _optional(path.parent / PROJECTS)
        if path.is_file() and zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                member = _member(z, CONVERSATIONS)
                if member is None:
                    raise Unreadable(
                        f"{path.name}: no {CONVERSATIONS} in the zip, so no Claude export; nothing read"
                    )
                projects = _member(z, PROJECTS, beside=PurePosixPath(member).parent)
                return z.read(member), z.read(projects) if projects is not None else None
    except READ_ERRORS as e:
        raise Unreadable(
            f"{path.name}: the Claude export could not be read ({type(e).__name__}); nothing read"
        ) from None
    raise Unreadable(
        f"{path.name}: not a Claude export (its zip, its folder or {CONVERSATIONS}); nothing read"
    )


def _file(file: Path, folder: Path) -> bytes:
    if not file.is_file():
        raise Unreadable(f"{folder.name}: no {CONVERSATIONS}, so no Claude export; nothing read")
    return file.read_bytes()


def _optional(file: Path) -> bytes | None:
    return file.read_bytes() if file.is_file() else None


def _conversations(data: bytes) -> list[Any]:
    try:
        found = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError, RecursionError) as e:
        raise Unreadable(
            f"{CONVERSATIONS} does not parse as JSON ({type(e).__name__}); nothing read"
        ) from None
    if not isinstance(found, list):
        raise Unreadable(f"{CONVERSATIONS} is not a list of conversations; nothing read")
    return found


def _projects(data: bytes | None) -> dict[str, str]:
    """Each project's name by its uuid; nothing else of a project is read. A `projects.json` that
    does not parse names no project."""
    if data is None:
        return {}
    try:
        found = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return {}
    names = {}
    for project in found if isinstance(found, list) else []:
        if not isinstance(project, Mapping):
            continue
        uuid, name = _text(project.get("uuid")), _name(project.get("name"))
        if uuid and name:
            names[uuid] = name
    return names


class _Conversation:
    """What one conversation holds, read message by message."""

    def __init__(self) -> None:
        self.turns: list[Turn] = []
        self.stamps: list[str] = []
        self.tools: Counter[str] = Counter()
        self.attachments: list[dict[str, Any]] = []


def _conversation(
    conversation: object, projects: Mapping[str, str], counts: dict[str, int], tier: int
) -> tuple[dict[str, Any], bytes] | None:
    if not isinstance(conversation, Mapping):
        _count(counts, "skipped_malformed")
        return None
    uuid = _text(conversation.get("uuid"))
    messages = conversation.get("chat_messages")
    if uuid is None or not isinstance(messages, list) or not all(isinstance(m, Mapping) for m in messages):
        _count(counts, "skipped_malformed")
        return None
    held = _Conversation()
    for message in _branch(conversation, messages, counts):
        _message(message, held, counts)
    created, updated = stamp(conversation.get("created_at")), stamp(conversation.get("updated_at"))
    stamps = sorted(held.stamps)
    first = stamps[0] if stamps else created
    last = stamps[-1] if stamps else updated or created
    if first is None:
        _count(counts, "skipped_malformed")
        return None
    if not held.turns:
        _count(counts, "skipped_empty")
        return None
    data = stored(held.turns)
    extra: dict[str, Any] = {"conversation": uuid}
    project = _project(conversation, projects)
    if project:
        extra["project"] = project
    if created:
        extra["created_at"] = created
    if updated:
        extra["updated_at"] = updated
    extra["tool_calls"] = sum(held.tools.values())
    extra["tools"] = dict(sorted(held.tools.items()))
    if held.attachments:
        extra["attachments"] = held.attachments
    extra["words"] = words(held.turns)
    extra["counterpart"] = dict(COUNTERPART)
    line = draft(
        source=NAME,
        at=first,
        end=last,
        raw_id=f"{NAME}:{uuid}",
        content=reference(data, MEDIA_TYPE),
        turns=held.turns,
        tier=tier,
        title=_name(conversation.get("name")) or first_words(held.turns),
        participants=[dict(p) for p in PARTICIPANTS],
        extra=extra,
    )
    return line, data


def _branch(
    conversation: Mapping[str, Any], messages: list[Mapping[str, Any]], counts: dict[str, int]
) -> list[Mapping[str, Any]]:
    """The messages of the branch the conversation stands on, oldest first: walked from its
    `current_leaf_message_uuid` up the `parent_message_uuid` links when the export gives the leaf
    and every message its parent, a message left on another branch (a prompt edited, an answer
    asked for again) counted (`skipped_branch`); else every message, in the export's order."""
    leaf = _text(conversation.get("current_leaf_message_uuid"))
    by_uuid = {uuid: m for m in messages if (uuid := _text(m.get("uuid"))) is not None}
    if leaf not in by_uuid or not all(isinstance(m.get("parent_message_uuid"), str) for m in messages):
        return messages
    chain: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    at: str | None = leaf
    while at is not None and at in by_uuid and at not in seen:  # the root's parent is no message; a loop ends
        seen.add(at)
        chain.append(by_uuid[at])
        at = _text(by_uuid[at].get("parent_message_uuid"))
    if len(messages) > len(chain):
        counts["skipped_branch"] = counts.get("skipped_branch", 0) + len(messages) - len(chain)
    return chain[::-1]


def _message(message: Mapping[str, Any], held: _Conversation, counts: dict[str, int]) -> None:
    speaker = SENDERS.get(str(message.get("sender")))
    if speaker is None:
        _count(counts, "skipped_unknown_sender")  # never the owner's words, nor the assistant's
        return
    when = stamp(message.get("created_at"))
    if when is not None:
        held.stamps.append(when)
    files = _list(message.get("files_v2")) or _list(message.get("files"))  # two views of one upload
    for given in [*_list(message.get("attachments")), *files]:
        if isinstance(given, Mapping):
            held.attachments.append(_attachment(given))
    content = message.get("content")
    if not isinstance(content, list) or not content:  # an export older than the blocks: the text
        if isinstance(message.get("text"), str):
            _say(held, speaker, message["text"])
        return
    for block in content:
        if not isinstance(block, Mapping):
            continue
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            _say(held, speaker, block["text"])
        elif block.get("type") == "tool_use":
            held.tools[_name(block.get("name")) or "unnamed"] += 1
        # thinking, a tool's result and every other block: never kept


def _say(held: _Conversation, speaker: str, text: str) -> None:
    """`text` as `speaker`'s, without what is never anyone's words: the export's placeholders, and
    the thinking and the artifacts an older export writes inline (each artifact counted)."""
    text, placeholders = PLACEHOLDER.subn("", text)
    text, thoughts = THINKING.subn("", text)
    text, artifacts = ARTIFACT.subn("", text)
    if artifacts:
        held.tools[ARTIFACTS] += artifacts
    if placeholders or thoughts or artifacts:
        text = re.sub(r"\n[ \t]*(?:\n[ \t]*)+\n", "\n\n", text)  # the blank lines a block left behind
    say(held.turns, speaker, text)


def _attachment(given: Mapping[str, Any]) -> dict[str, Any]:
    """A file by its name, type and size as the export gives them (the type, when it gives none, the
    name's suffix); its extracted text, its previews and its links never."""
    name = _name(given.get("file_name"))
    named: dict[str, Any] = {"name": name or "unnamed"}
    suffix = PurePosixPath(name).suffix.lstrip(".").casefold() if name else ""
    kind = _name(given.get("file_type")) or _name(given.get("file_kind")) or _name(suffix)
    if kind:
        named["type"] = kind
    size = given.get("file_size")
    if isinstance(size, int) and not isinstance(size, bool) and size >= 0:
        named["bytes"] = size
    return named


def _project(conversation: Mapping[str, Any], projects: Mapping[str, str]) -> str | None:
    """The name of the project the conversation is in, when the export links one it lists: a
    `project_uuid`, or a `project` naming one by uuid."""
    project = conversation.get("project")
    uuid = _text(project.get("uuid")) if isinstance(project, Mapping) else None
    uuid = uuid or _text(conversation.get("project_uuid"))
    return projects.get(uuid) if uuid else None


def _name(value: object) -> str | None:
    """A name as `_text` reads it, cut at NAME_CHARS: a name is never a way in for a document."""
    name = _text(value)
    if name is None or len(name) <= NAME_CHARS:
        return name
    return name[: NAME_CHARS - 1].rstrip() + "…"


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _count(counts: dict[str, int], name: str) -> None:
    counts[name] = counts.get(name, 0) + 1


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
