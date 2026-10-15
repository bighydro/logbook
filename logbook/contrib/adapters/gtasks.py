"""Google Tasks → task/v1 (RFC 0016), live: each task as it stands, mapped as the Takeout export maps it.

Google Tasks is the owner's quick-capture inbox: a task is an idea, or a promise to himself, and ticking
one off is worth knowing. `logbook sync gtasks` asks the Tasks API v1 (read-only scope `tasks.readonly`) as
the owner, through the service account `sync drive` uses (`service_account`: LOGBOOK_DRIVE_SA_KEY,
LOGBOOK_DRIVE_USER; one place to configure both).

**What is asked.** Every task list (`users/@me/lists`), then every task of each changed since `since`
(`updatedMin`; all of them without one), done, hidden (done and cleared from the list) and deleted
included, a page of `PAGE_SIZE` at a time, retried with backoff by the session. A page of tasks read is
a progress line.

**One mapping, two entrances (ADR 0017).** The API answers with the task objects Takeout writes into
`Tasks/Tasks.json`, so a line is the Takeout Tasks adapter's own (`takeout.tasks.draft`): kind `task`,
tier 2 (RFC 0016: MUST), source `google-takeout`, `raw_id` `<task id>@<updated>`. The record's dedupe on
`(source, raw_id)` then makes a task seen live and the same task in a Takeout export imported later one
line, and the other way round: a backfill writes nothing for what `sync` already saw.

**A snapshot (RFC 0016 rule 2).** One line per task as it stands: `at` its `updated` time (Google keeps no
creation time), `status` `open` or `done`, `completed_at` on a done one, `due` as a day (rule 4: Google
spells a due day as a midnight instant), `list` (its title), `parent` for a subtask, `modified_at`, and
under `extra` `hidden`, `deleted` and `links` as the export has them. A task changed since the record
last saw it — ticked off, renamed, reopened, deleted — is a new line; an unchanged one appends nothing,
and no line is ever rewritten. A deleted task is still a line (`extra.deleted`, rule 5, counted); a task
with no title or no time is skipped and counted.

**What the record adds.** Two things only the record knows, from `recorded`: the task lines of this
source it holds (every one, read once a pull). `supersedes` is the id of the task's newest earlier
snapshot there (rule 2: set when the adapter can find the earlier line). On a done snapshot,
`extra.open_for_s` is how long the task was open as far as the record saw: the seconds from the first of
the open snapshots since its last done one to `completed_at`; null when the record never saw it open.
The profile has no field for it, so it is kept under `extra`, as the profile keeps what it does not name.
A sealed snapshot is read when the identity is here; without it no earlier snapshot is found, and the
line has neither.

**The notes, never the words.** RFC 0016 keeps `notes` verbatim; this source keeps none: `extra.notes`
is `{sha256, words}`, the digest of the notes' text (CRLF as LF) and how many words it has. This is the
one way a live line differs from the export's, and the first to arrive is the line: an export imported
before `sync` keeps the words it carries.

**Watermark.** The task's `updated` time; a pull without `--since` starts `LOOKBACK_H` before it, and
the first `sync` after a Takeout backfill starts a day before the newest task the export holds."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

from . import service_account
from .service_account import Account
from .takeout import tasks as takeout_tasks

__all__ = [
    "ENV",
    "KIND",
    "NAME",
    "SCHEMA",
    "SCOPE",
    "SOURCE",
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
SOURCE = takeout_tasks.SOURCE  # the Takeout Tasks adapter's: the two dedupe on (source, raw_id)
KIND = takeout_tasks.KIND
TIER = takeout_tasks.TIER
SCHEMA = takeout_tasks.SCHEMA
UNIT = "tasks"  # what `sync` counts in its progress lines
SCOPE = service_account.SCOPES["gtasks"]
LISTS_URL = "https://tasks.googleapis.com/tasks/v1/users/@me/lists"
TASKS_URL = "https://tasks.googleapis.com/tasks/v1/lists/{list}/tasks"
PAGE_SIZE = 100
LOOKBACK_H = 24.0
OPEN, DONE = "open", "done"
UNTITLED_LIST = "untitled list"

Recorded = Callable[[str | None], Iterable[dict[str, Any]]]


@dataclass(frozen=True)
class Snapshot:
    """One task line the record holds, as far as this source needs it."""

    suffix: str  # the `raw_id` after its last `@`: the modification time, which orders snapshots
    seq: int
    id: str
    at: datetime
    status: str


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
    return str(draft["payload"].get("list") or UNTITLED_LIST)


def pull(
    config: Account,
    since: str | None = None,
    progress: Callable[[int, float], None] | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
    recorded: Recorded | None = None,
    wait_on_limits: bool = True,
) -> Iterator[dict[str, Any]]:
    """A task/v1 line draft for every task changed since `since` (RFC3339; None for all), oldest first.
    `recorded(None)` gives every task line of this source the record holds, for `supersedes` and how
    long a done task was open. Skips are tallied in `counts`; `progress(tasks_so_far, elapsed_seconds)`
    after each page. Raises service_account.GoogleError (an OSError) when Google cannot be read; nothing
    is yielded before every list is in."""
    counts = counts if counts is not None else {}
    session = service_account.Session(config, SCOPE, wait_on_limits)
    tasks = list(_read(session, since, progress, counts))
    history = _history(recorded(None)) if recorded is not None and tasks else {}
    tz = timezone or "UTC"
    drafts: list[dict[str, Any]] = []
    for task, task_list in tasks:
        draft = takeout_tasks.draft(task, " ".join(str(task_list.get("title") or "").split()), tz, counts)
        if draft is not None:
            drafts.append(_live(draft, history))
    yield from sorted(drafts, key=lambda d: (d["at"], d["payload"]["raw_id"]))


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _read(
    session: service_account.Session,
    since: str | None,
    progress: Callable[[int, float], None] | None,
    counts: dict[str, int],
) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    """(task, its list) for every task changed since `since`; one with no id is counted and left out,
    the rest are the mapping's to keep or skip."""
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
                if not task.get("id"):
                    _count(counts, "skipped_no_id")
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


def _history(lines: Iterable[dict[str, Any]]) -> dict[str, list[Snapshot]]:
    """The record's snapshots per task id (the `raw_id` before its last `@`), oldest first; a line whose
    payload does not say (sealed with no identity here, or not a task) is left out."""
    found: dict[str, list[Snapshot]] = {}
    for line in lines:
        payload = line.get("payload")
        if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
            continue
        raw_id, at = payload.get("raw_id"), _instant_or_none(line.get("at"))
        if not isinstance(raw_id, str) or at is None:
            continue
        key, sep, suffix = raw_id.rpartition("@")
        if not sep:
            continue
        snapshot = Snapshot(
            suffix, int(line.get("seq") or 0), str(line.get("id") or ""), at, str(payload.get("status"))
        )
        found.setdefault(key, []).append(snapshot)
    for snapshots in found.values():
        snapshots.sort(key=lambda s: (s.suffix, s.seq))
    return found


def _live(draft: dict[str, Any], history: dict[str, list[Snapshot]]) -> dict[str, Any]:
    """The mapping's draft as this source writes it: the notes as a digest, and what the record adds —
    `supersedes`, and on a done snapshot how long the task was open."""
    payload = draft["payload"]
    extra = dict(payload.pop("extra", None) or {})
    notes = payload.pop("notes", None)
    if isinstance(notes, str) and notes.strip():
        extra["notes"] = {
            "sha256": hashlib.sha256(notes.encode("utf-8")).hexdigest(),
            "words": len(notes.split()),
        }
    key, _sep, suffix = str(payload["raw_id"]).rpartition("@")
    earlier = [s for s in history.get(key, []) if s.suffix < suffix]
    if earlier and earlier[-1].id:
        payload["supersedes"] = earlier[-1].id
    if payload.get("status") == DONE:
        extra["open_for_s"] = _open_for(earlier, _instant_or_none(payload.get("completed_at")))
    if extra:
        payload["extra"] = extra
    return draft


def _open_for(earlier: list[Snapshot], completed: datetime | None) -> int | None:
    """Seconds from the first of the open snapshots since the task was last done to `completed`; None
    when the record saw it open in none, or the time would be negative."""
    opened: datetime | None = None
    for snapshot in reversed(earlier):
        if snapshot.status != OPEN:
            break
        opened = snapshot.at
    if opened is None or completed is None or completed < opened:
        return None
    return int((completed - opened).total_seconds())


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
