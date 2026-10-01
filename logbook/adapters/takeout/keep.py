"""Google Takeout Keep/ → note/v1 (RFC 0010).

Takeout writes `Takeout/Keep/<title or timestamp>.json`, one file per note, with an `.html` twin
beside it (not read: the JSON has everything) and the attachments as files in the same folder.
A note is an object with `title`, `textContent` or `listContent` (`[{text, isChecked}]`),
`createdTimestampUsec` and `userEditedTimestampUsec` (microseconds since the epoch), `labels`
(`[{name}]`), `isPinned`, `isArchived`, `isTrashed`, `color`, `attachments` (`[{filePath,
mimetype}]`) and `annotations` (web links: `[{title, url, description, source}]`).

One line per note: kind `note`, tier 2, source `google-takeout`, `at` the creation time in UTC,
`modified_at` the last edit, `tz` the record's zone (Keep keeps no zone). `raw_id` is
`keep:<createdTimestampUsec>@<modified_at>` (RFC 0010 rule 2): Keep's export carries no note id,
and the creation instant is the one thing about a note that never changes; the edit time on the
end makes an edited note a new line and a re-import of an unchanged one nothing. `supersedes` is
not set (as `ios-notes`): the earlier line of the same note is the one whose `raw_id` has the same
prefix, and a reader can find it.

A list note's text is one line per item, `[x] ` or `[ ] ` first (rule 3). An empty title is no
title. `labels` are the label names in export order. `extra` carries only what is true: `pinned`,
`archived`, `trashed` when set, `color` when not `DEFAULT`, `links` for the web-link annotations.
Attachments are `{filename, media_type, sha256, bytes}` from the file beside the note and `path`
with the bytes in the SPEC §1.1 store only with `attachments=True` (`--attachments`); a file the
export does not hold is `{filename, media_type}` and counted (`attachments_missing`). A note with
neither text nor items is skipped and counted; a trashed note is a line, marked and counted.
Pure: no network, never writes the source.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ...attachments import DIR as ATTACHMENTS_DIR
from . import SOURCE

NAME = "google-takeout-keep"
KIND = "note"
TIER = 2
SCHEMA = "note/v1"
FOLDER = "Keep"

SUFFIX = ".json"
SNIFF_BYTES = 1 << 20  # a note is a few kilobytes; nothing bigger is one
SHAPE = ("createdTimestampUsec", "userEditedTimestampUsec")
NO_TEXT = "skipped_no_text"
NOTE_FLAGS = ("pinned", "archived", "trashed")


def sniff(path: Path) -> bool:
    """A Keep note (a `.json` object with Keep's timestamps and a title, text or list), or a folder
    holding at least one — Takeout's `Keep/`. Never raises."""
    path = Path(path)
    try:
        if path.is_dir():
            return any(_is_note(f) for f in sorted(path.iterdir()))
        return _is_note(path)
    except OSError:
        return False


def _is_note(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() != SUFFIX or path.stat().st_size > SNIFF_BYTES:
        return False
    return _read(path) is not None


def _read(path: Path) -> dict[str, Any] | None:
    """The note in `path`, or None when it is not a Keep note."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not all(isinstance(data.get(k), int) for k in SHAPE):
        return None
    if not any(k in data for k in ("title", "textContent", "listContent")):
        return None
    return data


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
    attachments: bool | None = None,
    store: Callable[[bytes], object] | None = None,
) -> Iterator[dict[str, Any]]:
    """One note/v1 line draft per note in `path` (a note, or the folder of them, in name order),
    oldest first. `since` is RFC3339 UTC; notes created before it are not yielded. `timezone`
    is the record's zone (the line's `tz`)."""
    counts = counts if counts is not None else {}
    path = Path(path)
    files = [path] if path.is_file() else sorted(f for f in path.iterdir() if _is_note(f))
    drafts: list[dict[str, Any]] = []
    for file in files:
        note = _read(file)
        if note is None:
            continue
        draft = _draft(note, file.parent, timezone or "UTC", bool(attachments), counts)
        if draft is None or (since is not None and draft["at"] < since):
            continue
        drafts.append(draft)
    for draft in sorted(drafts, key=lambda d: (d["at"], d["payload"]["raw_id"])):
        blobs: list[bytes] = draft.pop("_blobs")
        if store is not None:
            for blob in blobs:
                store(blob)
        yield draft


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _draft(
    note: dict[str, Any], folder: Path, tz: str, keep_files: bool, counts: dict[str, int]
) -> dict[str, Any] | None:
    text = _text(note)
    if not text:
        _count(counts, NO_TEXT)
        return None
    created, edited = note["createdTimestampUsec"], note["userEditedTimestampUsec"]
    at, modified_at = _rfc3339(created), _rfc3339(edited)
    payload: dict[str, Any] = {"schema": SCHEMA, "raw_id": f"keep:{created}@{modified_at}"}
    title = " ".join(str(note.get("title") or "").split())
    if title:
        payload["title"] = title
    payload["text"] = text
    payload["modified_at"] = modified_at
    labels = [str(label.get("name")) for label in note.get("labels") or [] if isinstance(label, dict)]
    labels = [name for name in labels if name]
    if labels:
        payload["labels"] = labels
    found, blobs = _attachments(note, folder, keep_files, counts)
    if found:
        payload["attachments"] = found
    extra: dict[str, Any] = {}
    for flag in NOTE_FLAGS:
        if note.get(f"is{flag.capitalize()}") is True:
            extra[flag] = True
    if extra.get("trashed"):
        _count(counts, "trashed")
    color = str(note.get("color") or "")
    if color and color != "DEFAULT":
        extra["color"] = color
    links = [
        {k: str(a[k]) for k in ("title", "url", "description") if a.get(k)}
        for a in note.get("annotations") or []
        if isinstance(a, dict) and a.get("url")
    ]
    if links:
        extra["links"] = links
    if extra:
        payload["extra"] = extra
    return {
        "at": at,
        "end": None,
        "tz": tz,
        "source": SOURCE,
        "kind": KIND,
        "tier": TIER,
        "payload": payload,
        "_blobs": blobs,
    }


def _text(note: dict[str, Any]) -> str:
    """`textContent` as written, else the list as `[x] item` lines (RFC 0010 rule 3)."""
    body = note.get("textContent")
    if isinstance(body, str) and body.strip():
        return body.replace("\r\n", "\n")
    items = note.get("listContent")
    if not isinstance(items, list):
        return ""
    lines = [
        f"[{'x' if item.get('isChecked') else ' '}] {str(item.get('text') or '').strip()}"
        for item in items
        if isinstance(item, dict) and str(item.get("text") or "").strip()
    ]
    return "\n".join(lines)


def _attachments(
    note: dict[str, Any], folder: Path, keep_files: bool, counts: dict[str, int]
) -> tuple[list[dict[str, Any]], list[bytes]]:
    """Every attachment as `{filename, media_type, sha256, bytes}` (+ `path` when `keep_files`) from
    the file beside the note; one the export does not hold as `{filename, media_type}`."""
    found: list[dict[str, Any]] = []
    blobs: list[bytes] = []
    for entry in note.get("attachments") or []:
        if not isinstance(entry, dict) or not entry.get("filePath"):
            continue
        name = Path(str(entry["filePath"])).name  # never a path into the folder
        item: dict[str, Any] = {"filename": name, "media_type": str(entry.get("mimetype") or "")}
        file = folder / name
        if not file.is_file():
            _count(counts, "attachments_missing")
            found.append(item)
            continue
        data = file.read_bytes()
        sha256 = hashlib.sha256(data).hexdigest()
        item.update(sha256=sha256, bytes=len(data))
        if keep_files:
            item["path"] = f"{ATTACHMENTS_DIR}/{sha256}"
            blobs.append(data)
            _count(counts, "attachments_stored")
        else:
            _count(counts, "attachments_referenced")
        found.append(item)
    return found, blobs


def _rfc3339(usec: int) -> str:
    return datetime.fromtimestamp(usec / 1_000_000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
