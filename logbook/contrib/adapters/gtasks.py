"""Google Tasks → event/v1 (RFC 0009), live: a task created, a task done, as the events they are.

Google Tasks is the owner's quick-capture inbox: a task is an idea, or a promise to himself, and ticking
one off is a small event worth a line. `logbook sync gtasks` asks the Tasks API v1 (read-only scope
`tasks.readonly`) as the owner, through the service account `sync drive` uses (`service_account`:
LOGBOOK_DRIVE_SA_KEY, LOGBOOK_DRIVE_USER; one place to configure both).

**What is asked.** Every task list (`users/@me/lists`), then every task of each changed since `since`
(`updatedMin`; all of them without one), done, hidden (done and cleared from the list) and deleted
included, a page of `PAGE_SIZE` at a time, retried with backoff by the session. A page of tasks read is
a progress line.

**What is a line.** Two events, each at most once per task (`raw_id` `<task id>/created`,
`<task id>/completed`; the record's dedupe keeps the first):

- `created`, for a task the record sees open for the first time: `at` its `updated` time, which is when
  it was created for a task nobody touched since, and later for one edited before the record first saw
  it (Google Tasks keeps no creation time; RFC 0016 says as much). A task first seen already done has no
  `created` line: the record never saw it open and will not invent when it was. Nor has one reopened
  after the record saw it done.
- `completed`, for a task done: `at` its completion time; `extra.open_for_s` the seconds since its
  `created` line (read back from the record), null when the record has none.

A due day passing without the task done is no event: the record holds what happened. An edit is no
event either: a task changed after its `created` line appends nothing, and the line is never rewritten.
A deleted task writes nothing new (`skipped_deleted`); a task with no title is skipped and counted.

The line: kind `event`, `end` null, `tz` the record's zone; `title` the task's title, whitespace
collapsed; `calendar` `{google-tasks, Google Tasks}`, `all_day` false, `modified_at` the task's
`updated` (the watermark); under `extra` the `activity` (`created`, `completed`), the `list` (its
title), the `task` (`id`, `list_id`, and `url` when the API gives a link), `due` as a day (RFC 0016
rule 4: Google spells a due day as a midnight instant), `parent` for a subtask, `open_for_s` on a
completed line, and `notes` as `{sha256, words}`: the digest of the notes' text (CRLF as LF) and how
many words it has, never the words.

**Tier 2.** RFC 0009 makes a calendar entry tier 1, a SHOULD; SPEC §4 lets a producer write a higher
tier for a reason it states, and this is one: the line's title is a task's title, an idea or a promise
in the owner's words, the very text RFC 0016 puts at tier 2 when Takeout carries it as `task/v1`. The
tier is where a line may travel; the same words do not travel further because they arrive by another
road.

**Watermark.** The task's `updated` time; a pull without `--since` starts `LOOKBACK_H` before it."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

from . import service_account
from .service_account import Account

__all__ = [
    "ENV",
    "KIND",
    "NAME",
    "SCOPE",
    "TIER",
    "check",
    "configure",
    "group",
    "pull",
    "resume",
    "watermark",
]

NAME = "gtasks"
ENV = service_account.ENV
KIND = "event"
TIER = 2
SCHEMA = "event/v1"
UNIT = "tasks"  # what `sync` counts in its progress lines
SCOPE = service_account.SCOPES["gtasks"]
LISTS_URL = "https://tasks.googleapis.com/tasks/v1/users/@me/lists"
TASKS_URL = "https://tasks.googleapis.com/tasks/v1/lists/{list}/tasks"
PAGE_SIZE = 100
LOOKBACK_H = 24.0
CALENDAR = {"id": "google-tasks", "name": "Google Tasks"}
CREATED, COMPLETED = "created", "completed"

Held = Callable[[Iterable[tuple[str, str]]], Mapping[tuple[str, str], dict[str, Any]]]

configure = service_account.configure


def check(config: Account) -> str:
    """What `doctor` says after `configured`: the key read and loadable, no network asked."""
    return service_account.describe(config)


def resume(config: Account, mark: str) -> str:
    """Where a pull starts, given the watermark: a day before it."""
    return _z(_instant(mark) - timedelta(hours=LOOKBACK_H))


def watermark(draft: dict[str, Any]) -> str | None:
    """The task's last change, as Google stamped it."""
    modified = draft["payload"].get("modified_at")
    return str(modified) if modified else None


def group(draft: dict[str, Any]) -> str:
    """The list, so `sync` says seen and new per list."""
    return str(draft["payload"]["extra"].get("list") or draft["payload"]["extra"]["task"]["list_id"])


def pull(
    config: Account,
    since: str | None = None,
    progress: Callable[[int, float], None] | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
    held: Held | None = None,
) -> Iterator[dict[str, Any]]:
    """The created and completed events of every task changed since `since` (RFC3339; None for all),
    as event/v1 line drafts, oldest first. `held(keys)` gives the lines the record holds under these
    (source, raw_id) keys: a completed task's `created` line, for how long it was open, and whether a
    task now open was seen done before. Skips are tallied in `counts`; `progress(tasks_so_far,
    elapsed_seconds)` after each page. Raises service_account.GoogleError (an OSError) when Google
    cannot be read; nothing is yielded before every list is in."""
    counts = counts if counts is not None else {}
    session = service_account.Session(config, SCOPE)
    tasks = list(_read(session, since, progress, counts))
    keys = [(NAME, f"{task['id']}/{event}") for task, _list in tasks for event in (CREATED, COMPLETED)]
    record = dict(held(keys)) if held is not None and keys else {}
    tz = timezone or "UTC"
    drafts: list[dict[str, Any]] = []
    for task, task_list in tasks:
        draft = _event(task, task_list, record, tz)
        if draft is not None:
            drafts.append(draft)
    yield from sorted(drafts, key=lambda d: (d["at"], d["payload"]["raw_id"]))


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _read(
    session: service_account.Session,
    since: str | None,
    progress: Callable[[int, float], None] | None,
    counts: dict[str, int],
) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    """(task, its list) for every task changed since `since` that can be a line: deleted ones and those
    with no title are counted and left out."""
    started = time.monotonic()
    seen = 0
    for task_list in _pages(session, LISTS_URL, {"maxResults": str(PAGE_SIZE)}):
        if not task_list.get("id"):
            continue
        params = {
            "maxResults": str(PAGE_SIZE),
            "showCompleted": "true",
            "showHidden": "true",
            "showDeleted": "true",
        }
        if since:
            params["updatedMin"] = _z(_instant(since))
        url = TASKS_URL.format(list=quote(str(task_list["id"]), safe=""))
        for page in _pages_of(session, url, params):
            for task in page:
                seen += 1
                if not task.get("id") or not _instant_or_none(task.get("updated")):
                    _count(counts, "skipped_no_date")
                elif task.get("deleted") is True:
                    _count(counts, "skipped_deleted")
                elif not _title(task):
                    _count(counts, "skipped_no_title")
                else:
                    yield task, task_list
            if progress is not None:
                progress(seen, time.monotonic() - started)


def _pages(session: service_account.Session, url: str, params: dict[str, str]) -> Iterator[dict[str, Any]]:
    for page in _pages_of(session, url, params):
        yield from page


def _pages_of(
    session: service_account.Session, url: str, params: dict[str, str]
) -> Iterator[list[dict[str, Any]]]:
    """Each page's items, following `nextPageToken` to the last page."""
    asked = dict(params)
    while True:
        page = session.get_json(url, asked)
        yield [x for x in page.get("items") or [] if isinstance(x, dict)]
        token = page.get("nextPageToken")
        if not isinstance(token, str) or not token:
            return
        asked = {**params, "pageToken": token}


def _event(
    task: dict[str, Any], task_list: dict[str, Any], record: Mapping[tuple[str, str], dict[str, Any]], tz: str
) -> dict[str, Any] | None:
    """The one event this snapshot of the task can still add: `completed` for a done task, `created`
    for an open one the record has not seen done."""
    task_id = str(task["id"])
    completed = _instant_or_none(task.get("completed"))
    if task.get("status") == "completed" and completed is not None:
        created = record.get((NAME, f"{task_id}/{CREATED}"))
        opened = _instant_or_none(created.get("at")) if created is not None else None
        open_for = int((completed - opened).total_seconds()) if opened is not None else None
        return _draft(
            task, task_list, COMPLETED, completed, tz, open_for if open_for is None or open_for >= 0 else None
        )
    if task.get("status") == "completed" or (NAME, f"{task_id}/{COMPLETED}") in record:
        return None  # done with no time, or reopened after the record saw it done: no creation to tell
    updated = _instant_or_none(task.get("updated"))
    return None if updated is None else _draft(task, task_list, CREATED, updated, tz)


def _draft(
    task: dict[str, Any],
    task_list: dict[str, Any],
    event: str,
    at: datetime,
    tz: str,
    open_for_s: int | None = None,
) -> dict[str, Any]:
    """One event's line draft; `open_for_s` is a completed line's, seconds since its created line."""
    task_id = str(task["id"])
    ref: dict[str, Any] = {"id": task_id, "list_id": str(task_list["id"])}
    if isinstance(task.get("webViewLink"), str) and task["webViewLink"]:
        ref["url"] = task["webViewLink"]
    extra: dict[str, Any] = {"activity": event}
    list_title = " ".join(str(task_list.get("title") or "").split())
    if list_title:
        extra["list"] = list_title
    extra["task"] = ref
    due = _instant_or_none(task.get("due"))
    if due is not None:
        extra["due"] = due.date().isoformat()  # a day, never the midnight instant Google spells (RFC 0016)
    if task.get("parent"):
        extra["parent"] = str(task["parent"])
    notes = str(task.get("notes") or "").replace("\r\n", "\n")
    if notes.strip():
        extra["notes"] = {
            "sha256": hashlib.sha256(notes.encode("utf-8")).hexdigest(),
            "words": len(notes.split()),
        }
    if event == COMPLETED:
        extra["open_for_s"] = open_for_s
    updated = _instant_or_none(task.get("updated"))
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": f"{task_id}/{event}",
        "title": _title(task),
        "calendar": dict(CALENDAR),
        "all_day": False,
        "modified_at": _z(updated if updated is not None else at),
        "extra": extra,
    }
    return {
        "at": _z(at),
        "end": None,
        "tz": tz,
        "source": NAME,
        "kind": KIND,
        "tier": TIER,
        "payload": payload,
    }


def _title(task: dict[str, Any]) -> str:
    return " ".join(str(task.get("title") or "").split())


def _instant(text: str) -> datetime:
    when = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(UTC)


def _instant_or_none(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _instant(value)
    except ValueError:
        return None


def _z(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
