"""`logbook import pickup FOLDER`: a folder of call transcripts waiting outside the record, moved in.

The Purser, a separate program on the owner's Mac, collects the transcripts the receiving side holds
(the calls Granola, Fireflies and the rest recorded) into a folder of its own. This is the records
side of that hand-over. Every file under the folder, in path order (hidden files and folders, and an
`attachments/` folder an export keeps its referenced files in, are passed over), is read by the
`transcript` adapter (its one mapping, ADR 0017): a transcript/v1 JSON keeps its own source, its
provider, whatever `source` says; a WebVTT, SRT or Markdown file names none, and `source` names it
(`--source`), else it is left where it is (`NO_SOURCE`). A file the adapter does not read is
`NOT_TRANSCRIPT`; one with no start is `NO_START`.

A file **already taken** is skipped by its hash: the SHA-256 of its bytes, which every line this
command writes keeps under `payload.extra.picked_up` (`{"sha256", "file"}`, the file's path below the
folder), so the same file again, under any name, is `TAKEN`. A file whose line the record already
holds by (source, raw_id), the same call another road wrote, is `IN_RECORD`: nothing is written,
and the file is left for the owner. The rest is `TAKE`.

A dry run unless `write`: `survey` reads and decides, and nothing else happens. `take` stores each
file's content (SPEC §1.1, before the line that points at it, ADR 0015), appends the lines through
`Logbook.append_many` under the writer lock, then, unless `keep`, removes each file it took and each
file found already taken (a move a crash left half done). The folder must not be the record or a part
of it, told apart by the disk and not by the name. Nothing is fetched from anywhere: the files are on
this machine."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.store import Logbook
from .adapters import transcript

MARK = "picked_up"  # under a line's `payload.extra`: the hash and the path of the file it was taken from
TAKE, TAKEN, IN_RECORD = "take", "taken", "in_record"
NO_SOURCE, NO_START, NOT_TRANSCRIPT = "no_source", "no_start", "not_transcript"
SKIPPED_FOLDERS = frozenset({"attachments"})  # where an export keeps the files its JSON references


class PickupError(ValueError):
    """The folder cannot be picked up from; one sentence naming it."""


@dataclass
class Found:
    """One file of the folder: its path, its name below the folder (POSIX), its hash, what is to be
    done with it, and, when it is to be taken, its line and the bytes to store first."""

    path: Path
    name: str
    sha256: str
    status: str
    line: dict[str, Any] | None = None
    held: list[bytes] = field(default_factory=list)


@dataclass
class Taken:
    """What `take` did: the lines appended, the files removed (taken now, and taken before), and each
    file it could not remove."""

    appended: int = 0
    removed: int = 0
    removed_before: int = 0
    failed: list[str] = field(default_factory=list)


def files(folder: Path) -> list[Path]:
    """Every file below `folder`, by its path below it, hidden ones and `SKIPPED_FOLDERS` passed over."""
    found = []
    for path in folder.rglob("*"):
        parts = path.relative_to(folder).parts
        if any(p.startswith(".") for p in parts) or any(p in SKIPPED_FOLDERS for p in parts[:-1]):
            continue
        if path.is_file():
            found.append(path)
    return sorted(found, key=lambda p: p.relative_to(folder).parts)


def check_folder(lb: Logbook, folder: Path) -> Path:
    """The folder, resolved; PickupError when it is not a folder, or is the record or inside it."""
    if not folder.is_dir():
        raise PickupError(f"{folder} is not a folder")
    resolved = folder.resolve()
    for place in (resolved, *resolved.parents):
        try:
            if os.path.samefile(place, lb.root):
                raise PickupError(f"{folder} is inside the record; a pickup folder lies outside it")
        except OSError:
            continue
    return resolved


def taken_hashes(lb: Logbook) -> set[str]:
    """The hashes of the files the record's transcript lines were taken from (`MARK`)."""
    found: set[str] = set()
    with lb.index() as idx:
        for line in idx.stream(transcript.KIND):
            extra = (line.get("payload") or {}).get("extra")
            mark = extra.get(MARK) if isinstance(extra, dict) else None
            if isinstance(mark, dict) and isinstance(mark.get("sha256"), str):
                found.add(mark["sha256"])
    return found


def survey(lb: Logbook, folder: Path, source: str | None = None, tier: int | None = None) -> list[Found]:
    """Every file below `folder` and what is to be done with it; reads, writes nothing."""
    folder = check_folder(lb, folder)
    taken = taken_hashes(lb)
    zone = str(lb.meta["timezone"])
    found: list[Found] = []
    for path in files(folder):
        data = path.read_bytes()
        item = Found(path, path.relative_to(folder).as_posix(), hashlib.sha256(data).hexdigest(), TAKE)
        found.append(item)
        if item.sha256 in taken:
            item.status = TAKEN
            continue
        counts: dict[str, int] = {}
        held: list[bytes] = []
        named = own_source(data)  # a file's own source wins: `source` names only the files that name none
        given = None if named is not None else source
        lines = list(
            transcript.run(path, counts=counts, timezone=zone, source=given, tier=tier, store=held.append)
        )
        if not lines:
            item.status = NO_START if counts.get(transcript.NO_START) else NOT_TRANSCRIPT
            continue
        if named is None and source is None:
            item.status = NO_SOURCE
            continue
        line = lines[0]
        payload = line["payload"]
        payload["extra"] = {**(payload.get("extra") or {}), MARK: {"sha256": item.sha256, "file": item.name}}
        item.line, item.held = line, held
        taken.add(item.sha256)  # the same bytes twice in one folder are one call
    _in_record(lb, [f for f in found if f.status == TAKE])
    return found


def own_source(data: bytes) -> str | None:
    """The source a transcript/v1 JSON names for itself (its `source`, else its payload's
    `provider`), or None: a file in any other format names none."""
    try:
        obj = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    payload = obj.get("payload")
    for value in (obj.get("source"), payload.get("provider") if isinstance(payload, dict) else None):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _in_record(lb: Logbook, items: list[Found]) -> None:
    """Mark `IN_RECORD` each item whose line the record holds by (source, raw_id), one SELECT."""
    keys = {
        (str(f.line["source"]), str(f.line["payload"]["raw_id"])): f
        for f in items
        if f.line is not None and f.line["payload"].get("raw_id")
    }
    if not keys:
        return
    with lb.index() as idx:
        held = idx.lines_of(keys)
    for key in held:
        keys[key].status = IN_RECORD


def take(lb: Logbook, found: list[Found], keep: bool = False) -> Taken:
    """Store the content of every file to take and of every file whose call is in the record, then
    append the lines to take, then (unless `keep`) remove the files taken now and before."""
    done = Taken()
    with lb.writer("import pickup"):
        for f in found:
            if f.status in (TAKE, IN_RECORD):
                tier = int(f.line["tier"]) if f.line is not None else None
                for data in f.held:
                    lb.attach(data, tier)
        done.appended = lb.append_many(f.line for f in found if f.status == TAKE and f.line is not None)
    if keep:
        return done
    for f in found:
        if f.status not in (TAKE, TAKEN):
            continue
        try:
            f.path.unlink()
        except OSError as e:
            done.failed.append(f"{f.name}: {e.strerror or e}")
            continue
        if f.status == TAKE:
            done.removed += 1
        else:
            done.removed_before += 1
    return done


def by_source(found: list[Found], status: str = TAKE) -> Iterator[tuple[str, int]]:
    """(source, files) of the files with `status`, the most first."""
    counts: dict[str, int] = {}
    for f in found:
        if f.status == status and f.line is not None:
            counts[str(f.line["source"])] = counts.get(str(f.line["source"]), 0) + 1
    yield from sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
