"""Claude Code's session transcripts → transcript/v1 (RFC 0004): one line per session with the owner.

The owner talks to a coding assistant in Claude Code, and those sessions are part of the record:
the owner's words at their tier, the assistant's beside them marked as machine text
(`logbook.core.machine`), never as a person's. Claude Code keeps every session on the machine it
ran on, under `~/.claude/projects/`: one folder per project, named from its working directory
(`/Users/ines/code/solvind-log` is `-Users-ines-code-solvind-log`), one `<session id>.jsonl` per
session, one JSON object per line (`type` `user`, `assistant`, `summary`, `system`, …, with
`sessionId`, `cwd`, `gitBranch`, `timestamp`, and the API's `message` for a turn).

`logbook add claude-sessions <folder>` reads the projects folder, one project's folder or one
session's file (each sniffed, so a bare `add` finds them). A file named `agent-*.jsonl` is a
subagent's own conversation, whose "user" is the main agent: it is skipped and counted
(`skipped_subagent`), as is every entry marked `isSidechain` (`skipped_sidechain`) and a line that
is not JSON (`skipped_unreadable_row`).

**The turns.** The owner's turns are the text of the `user` entries: a string, or the `text`
blocks of a list. Never the owner's: a tool's result (`tool_result` blocks, `toolUseResult`),
which is the machine's output; an entry marked `isMeta` (a caveat Claude Code adds) or
`isCompactSummary` (the model's summary of the conversation, in the user's role); a slash command
or its output (`<command-…>`, `<local-command-…>`); the interrupt marker. The assistant's turns are
the `text` blocks of the `assistant` entries; its thinking is never kept, an API error
(`isApiErrorMessage`) is not a turn, and a `tool_use` block is counted, never kept: `tool_calls`,
and `tools` by name. Consecutive text of one side is one turn. An image the owner pasted is
counted (`images`) and never stored.

**The line.** Kind `transcript`, source and provider `claude-code`, tier 2 (RFC 0004's; `--tier`
sets another for a run). `at` and `end` are the session's first and last entry. `participants` are
`[{"name": "owner"}, {"name": "assistant", "machine": true}]`: `owner` is a word every reader
takes for the owner (as `me`), and the participant marked machine is the assistant, whose turns no
reader counts as a person's (RFC 0004 lets a participant carry a field a consumer does not know).
`content` is the turns as JSON, `{"turns": [{"speaker", "text"}, …]}`, stored once under its
digest (SPEC §1.1), the digest the reference's `sha256`. `title` is Claude Code's own title of the
session (its `summary` entry), else the first line of the owner's first turn. `raw_id` is
`claude-code:<session id>` (the file's name). Under `extra`: `session`, `project` (the working
directory's last part), `cwd`, `git_branch`, `version` (Claude Code's), `models`, `tool_calls`,
`tools`, `images`, `words` (`{owner, machine}`), the counterpart (`{kind: agent, ref:
{provider_id, claude-code}, name: Claude Code}`), and the transcript counts every transcript has.

**A session that grew.** A session goes on after an import (or is resumed): run with the record's
`existing` lines, a session whose stored text differs from the line standing for it is written as
a new line, `raw_id` suffixed `:v2` (`:v3` …) and `supersedes` the line before, counted
(`grown`); an unchanged session is the same line and is not written twice. A sealed line this
machine cannot open is taken as unchanged: a session grows on the record's home, which has the
key. Pure: reads the files, writes nothing but through `store`, no network.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import Any

from ...core.attachments import reference
from ...core.transcripts import Turn
from .transcript import KIND, draft

__all__ = ["ASSISTANT", "KIND", "NAME", "OWNER", "TIER", "run", "sniff"]

NAME = "claude-code"
TIER = 2  # RFC 0004's SHOULD: the owner's words and the assistant's, no third party's
MEDIA_TYPE = "application/json"
OWNER = "owner"  # the owner's speaker label: a word every reader takes for the owner
ASSISTANT = "assistant"  # the assistant's, a participant marked machine
PARTICIPANTS = ({"name": OWNER}, {"name": ASSISTANT, "machine": True})
COUNTERPART = {"kind": "agent", "ref": {"kind": "provider_id", "value": NAME}, "name": "Claude Code"}
SUFFIX = ".jsonl"
SUBAGENT_PREFIX = "agent-"
ENTRY_TYPES = frozenset({"user", "assistant", "summary", "system", "file-history-snapshot"})
NOT_WORDS = ("<command-", "<local-command-", "[Request interrupted")  # a command, its output, a marker
SNIFF_LINES = 8
SNIFF_BYTES = 65536
SNIFF_FOLDERS = 50  # a projects folder: at most this many project folders looked into
TITLE_CHARS = 80
SYNTHETIC_MODEL = "<synthetic>"
SEALED = "sealed/v1"  # a line this machine cannot open (RFC 0029)

Existing = Callable[[Iterable[tuple[str, str]]], Mapping[tuple[str, str], Mapping[str, Any]]]


# -- sniff -------------------------------------------------------------------------------------------


def sniff(path: Path) -> bool:
    """A Claude Code session file, a project's folder holding one, or the projects folder holding
    such folders. Reads a few lines of a few files at most; never raises."""
    path = Path(path)
    try:
        if path.is_file():
            return _is_session(path)
        if not path.is_dir():
            return False
        if any(_is_session(f) for f in _session_files(path)):
            return True
        folders = sorted(p for p in path.iterdir() if p.is_dir() and not p.name.startswith("."))
        return any(any(_is_session(f) for f in _session_files(d)) for d in folders[:SNIFF_FOLDERS])
    except OSError:
        return False


def _session_files(folder: Path) -> list[Path]:
    return sorted(
        f for f in folder.iterdir() if f.is_file() and f.suffix == SUFFIX and not f.name.startswith(".")
    )


def _is_session(file: Path) -> bool:
    if file.suffix != SUFFIX:
        return False
    try:
        with file.open("rb") as fh:
            head = fh.read(SNIFF_BYTES)
    except OSError:
        return False
    for raw in head.splitlines()[:SNIFF_LINES]:
        try:
            entry = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            continue
        if not isinstance(entry, dict) or entry.get("type") not in ENTRY_TYPES:
            continue
        if isinstance(entry.get("sessionId"), str) or (
            entry.get("type") == "summary" and "leafUuid" in entry
        ):
            return True
    return False


# -- run ---------------------------------------------------------------------------------------------


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    tier: int | None = None,
    store: Callable[[bytes], object] | None = None,
    existing: Existing | None = None,
) -> Iterator[dict[str, Any]]:
    """One transcript/v1 line draft per session under `path` (the projects folder, a project's
    folder or a session file), in path order. `since` (RFC3339 UTC) leaves out a session that ended
    before it; `tier` replaces 2 for the run; `store` is given the text's bytes just before its
    line; `existing` (the record's lines by (source, raw_id)) makes a grown session a correction."""
    counts = counts if counts is not None else {}
    for file in _files(Path(path), counts):
        found = _session(file, counts, tier or TIER)
        if found is None:
            continue
        line, data = found
        if since and str(line["end"] or line["at"]) < since:
            continue
        line = _versioned(line, existing, counts)
        if store is not None:
            store(data)
        yield line


def _files(path: Path, counts: dict[str, int]) -> Iterator[Path]:
    """The session files: the file given, a folder's own, or each project folder's; a subagent's
    file is counted and passed over."""
    if path.is_file():
        candidates = [path]
    else:
        candidates = _session_files(path)
        if not any(_is_session(f) for f in candidates):  # the projects folder: a stray file hides nothing
            candidates = []
            for folder in sorted(p for p in path.iterdir() if p.is_dir() and not p.name.startswith(".")):
                candidates.extend(_session_files(folder))
    for file in candidates:
        if file.name.startswith(SUBAGENT_PREFIX):
            _count(counts, "skipped_subagent")
            continue
        yield file


class _Session:
    """What one session file holds, read line by line."""

    def __init__(self) -> None:
        self.turns: list[Turn] = []
        self.stamps: list[str] = []
        self.cwd: str | None = None
        self.branch: str | None = None
        self.version: str | None = None
        self.summary: str | None = None
        self.models: list[str] = []
        self.tools: Counter[str] = Counter()
        self.images = 0

    def say(self, speaker: str, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if self.turns and self.turns[-1].speaker == speaker:
            self.turns[-1] = Turn(speaker, f"{self.turns[-1].text}\n\n{text}")
        else:
            self.turns.append(Turn(speaker, text))


def _session(file: Path, counts: dict[str, int], tier: int) -> tuple[dict[str, Any], bytes] | None:
    held = _Session()
    with file.open("rb") as fh:
        for raw in fh:
            if not raw.strip():
                continue
            try:
                entry = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                _count(counts, "skipped_unreadable_row")
                continue
            if isinstance(entry, dict):
                _entry(entry, held, counts)
    if not held.turns or not held.stamps:
        _count(counts, "skipped_empty")
        return None
    session = _session_id(file)
    data = json.dumps(
        {"turns": [{"speaker": t.speaker, "text": t.text} for t in held.turns]},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    words = {
        "owner": sum(len(t.text.split()) for t in held.turns if t.speaker == OWNER),
        "machine": sum(len(t.text.split()) for t in held.turns if t.speaker == ASSISTANT),
    }
    extra: dict[str, Any] = {"session": session}
    if held.cwd:
        extra["project"] = PureWindowsPath(held.cwd).name or held.cwd  # either separator, by parts
        extra["cwd"] = held.cwd
    if held.branch:
        extra["git_branch"] = held.branch
    if held.version:
        extra["version"] = held.version
    if held.models:
        extra["models"] = held.models
    extra["tool_calls"] = sum(held.tools.values())
    extra["tools"] = dict(sorted(held.tools.items()))
    if held.images:
        extra["images"] = held.images
    extra["words"] = words
    extra["counterpart"] = dict(COUNTERPART)
    stamps = sorted(held.stamps)
    line = draft(
        source=NAME,
        at=stamps[0],
        end=stamps[-1],
        raw_id=f"{NAME}:{session}",
        content=reference(data, MEDIA_TYPE),
        turns=held.turns,
        tier=tier,
        title=held.summary or _first_words(held.turns),
        participants=[dict(p) for p in PARTICIPANTS],
        extra=extra,
    )
    return line, data


def _entry(entry: Mapping[str, Any], held: _Session, counts: dict[str, int]) -> None:
    kind = entry.get("type")
    if kind == "summary":
        if held.summary is None and _text(entry.get("summary")):
            held.summary = _text(entry.get("summary"))
        return
    if kind not in ("user", "assistant"):
        return
    if entry.get("isSidechain") is True:
        _count(counts, "skipped_sidechain")
        return
    stamp = _stamp(entry.get("timestamp"))
    if stamp is not None:
        held.stamps.append(stamp)
    held.cwd = held.cwd or _text(entry.get("cwd"))
    held.branch = held.branch or _text(entry.get("gitBranch"))
    held.version = held.version or _text(entry.get("version"))
    message = entry.get("message")
    if not isinstance(message, Mapping):
        return
    if kind == "user":
        _user(entry, message, held)
    else:
        _assistant(entry, message, held)


def _user(entry: Mapping[str, Any], message: Mapping[str, Any], held: _Session) -> None:
    if entry.get("isMeta") is True or entry.get("isCompactSummary") is True or "toolUseResult" in entry:
        return
    content = message.get("content")
    if isinstance(content, str):
        if _words(content):
            held.say(OWNER, content)
        return
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, Mapping):
            continue
        if block.get("type") == "text" and isinstance(block.get("text"), str) and _words(block["text"]):
            held.say(OWNER, block["text"])
        elif block.get("type") == "image":
            held.images += 1
        # a tool_result block is the machine's output, never the owner's words: nothing kept


def _assistant(entry: Mapping[str, Any], message: Mapping[str, Any], held: _Session) -> None:
    if entry.get("isApiErrorMessage") is True:
        return
    model = _text(message.get("model"))
    if model and model != SYNTHETIC_MODEL and model not in held.models:
        held.models.append(model)
    content = message.get("content")
    if isinstance(content, str):
        held.say(ASSISTANT, content)
        return
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, Mapping):
            continue
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            held.say(ASSISTANT, block["text"])
        elif block.get("type") == "tool_use":
            held.tools[_text(block.get("name")) or "unnamed"] += 1
        # thinking is never kept


def _words(text: str) -> bool:
    """Whether a user entry's text is the owner's words: not a slash command, its output or a marker."""
    stripped = text.strip()
    return bool(stripped) and not stripped.startswith(NOT_WORDS)


def _session_id(file: Path) -> str:
    """The file's own name, which Claude Code names after the session."""
    return file.stem


def _first_words(turns: list[Turn]) -> str | None:
    first = next((t.text for t in turns if t.speaker == OWNER), None)
    if first is None:
        return None
    line = first.strip().splitlines()[0].strip()
    return line if len(line) <= TITLE_CHARS else line[: TITLE_CHARS - 1].rstrip() + "…"


def _versioned(line: dict[str, Any], existing: Existing | None, counts: dict[str, int]) -> dict[str, Any]:
    """The line as it goes to the record: as it is when the record has no line for its session, or
    one whose text is the same (the record's dedupe then writes nothing); a correction `:v<n>` that
    supersedes the latest version when the session's text changed. One batched lookup per version."""
    if existing is None:
        return line
    raw_id = str(line["payload"]["raw_id"])
    latest: Mapping[str, Any] | None = None
    version = 1
    while True:
        wanted = (NAME, raw_id if version == 1 else f"{raw_id}:v{version}")
        found = existing([wanted]).get(wanted)
        if found is None:
            break
        latest, version = found, version + 1
    if latest is None:
        return line
    if (latest.get("payload") or {}).get("schema") == SEALED:
        return line  # sealed and no identity here to open it: nothing to compare, nothing re-written
    stored = (latest.get("payload") or {}).get("content")
    if isinstance(stored, Mapping) and stored.get("sha256") == line["payload"]["content"]["sha256"]:
        return line  # the same session: deduped by its raw_id
    payload = dict(line["payload"])
    payload["raw_id"] = f"{raw_id}:v{version}"
    payload["supersedes"] = str(latest["id"])
    _count(counts, "grown")
    return {**line, "payload": payload}


def _stamp(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        when = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _count(counts: dict[str, int], name: str) -> None:
    counts[name] = counts.get(name, 0) + 1


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
