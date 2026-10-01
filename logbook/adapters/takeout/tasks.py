"""Google Takeout Tasks/ → task/v1 (RFC 0016).

Takeout writes `Takeout/Tasks/Tasks.json`: `{"kind": "tasks#taskLists", "items": [<list>]}`, each
list `{id, title, updated, items: [<task>]}` and each task `{id, title, updated, status
("needsAction" | "completed"), due?, completed?, notes?, parent?, position, links?, hidden?,
deleted?}` with every time as RFC 3339 UTC with milliseconds and `due` always a midnight instant
standing for a day.

One line per task, subtasks their own lines: kind `task`, tier 2, source `google-takeout`, `at`
the task's `updated` (the export keeps no creation time; RFC 0016), `tz` the record's zone.
`raw_id` is `<task id>@<updated>` (rule 2): a task ticked off and exported again is a new line, an
unchanged one appends nothing. `status` is `done` for `completed`, else `open`; `due` is the day
(`YYYY-MM-DD`, rule 4); `completed_at`, `list` (the list's title), `notes`, `parent` (the parent's
task id), `modified_at`; `extra` carries `hidden`, `deleted` (counted) and `links` as
`{type, description, url}`. A task with no title is skipped and counted. Pure: no network, never
writes the source.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import SOURCE

NAME = "google-takeout-tasks"
KIND = "task"
TIER = 2
SCHEMA = "task/v1"
FOLDER = "Tasks"

SUFFIX = ".json"
SNIFF_BYTES = 4096
LISTS_KIND = "tasks#taskLists"
LIST_KIND = "tasks#taskList"
STATUS = {"completed": "done", "needsAction": "open"}
NO_TITLE = "skipped_no_title"


def sniff(path: Path) -> bool:
    """A Tasks export (`tasks#taskLists` with lists), or a folder holding one. Never raises."""
    path = Path(path)
    try:
        if path.is_dir():
            return any(_is_export(f) for f in sorted(path.iterdir()))
        return _is_export(path)
    except OSError:
        return False


def _is_export(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() != SUFFIX:
        return False
    with path.open("rb") as fh:
        head = fh.read(SNIFF_BYTES)
    if LISTS_KIND.encode() not in head:
        return False
    return bool(_lists(path))


def _lists(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict) or data.get("kind") != LISTS_KIND:
        return []
    return [x for x in data.get("items") or [] if isinstance(x, dict) and x.get("kind") == LIST_KIND]


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
) -> Iterator[dict[str, Any]]:
    """One task/v1 line draft per task in the export at `path` (or every export in the folder),
    oldest `at` first. `since` is RFC3339 UTC; `timezone` is the record's zone."""
    counts = counts if counts is not None else {}
    path = Path(path)
    files = [path] if path.is_file() else sorted(f for f in path.iterdir() if _is_export(f))
    drafts: list[dict[str, Any]] = []
    for file in files:
        for task_list in _lists(file):
            name = " ".join(str(task_list.get("title") or "").split())
            for task in task_list.get("items") or []:
                if not isinstance(task, dict):
                    continue
                draft = _draft(task, name, timezone or "UTC", counts)
                if draft is not None and (since is None or draft["at"] >= since):
                    drafts.append(draft)
    yield from sorted(drafts, key=lambda d: (d["at"], d["payload"]["raw_id"]))


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _draft(task: dict[str, Any], list_name: str, tz: str, counts: dict[str, int]) -> dict[str, Any] | None:
    title = " ".join(str(task.get("title") or "").split())
    if not title:
        _count(counts, NO_TITLE)
        return None
    updated = _instant(task.get("updated"))
    if updated is None:
        _count(counts, "skipped_no_date")
        return None
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": f"{task.get('id')}@{updated}",
        "title": title,
        "status": STATUS.get(str(task.get("status")), "open"),
    }
    due = _instant(task.get("due"))
    if due is not None:
        payload["due"] = due[:10]  # a day, never the midnight instant the export spells (rule 4)
    completed = _instant(task.get("completed"))
    if completed is not None and payload["status"] == "done":
        payload["completed_at"] = completed
    if list_name:
        payload["list"] = list_name
    notes = str(task.get("notes") or "").replace("\r\n", "\n")
    if notes.strip():
        payload["notes"] = notes
    if task.get("parent"):
        payload["parent"] = str(task["parent"])
    payload["modified_at"] = updated
    extra: dict[str, Any] = {}
    for flag in ("hidden", "deleted"):
        if task.get(flag) is True:
            extra[flag] = True
    if extra.get("deleted"):
        _count(counts, "deleted")
    links = [_link(link) for link in task.get("links") or [] if isinstance(link, dict) and link.get("link")]
    if links:
        extra["links"] = links
    if extra:
        payload["extra"] = extra
    return {
        "at": updated,
        "end": None,
        "tz": tz,
        "source": SOURCE,
        "kind": KIND,
        "tier": TIER,
        "payload": payload,
    }


def _link(link: dict[str, Any]) -> dict[str, str]:
    """`{type, description, link}` as `{type, description, url}`, empty members left out."""
    keys = (("type", "type"), ("description", "description"), ("url", "link"))
    return {name: str(link[key]) for name, key in keys if link.get(key)}


def _instant(value: object) -> str | None:
    """An RFC 3339 time of the export as `YYYY-MM-DDTHH:MM:SSZ`, or None when it is not one."""
    if not isinstance(value, str) or not value:
        return None
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
