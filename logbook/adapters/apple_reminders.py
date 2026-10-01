"""Apple Reminders (iOS) → task/v1 (RFC 0016).

Reads the Core Data stores an iPhone keeps in the Reminders app group: in a Finder/iTunes backup
they are the files under `Container_v1/Stores/Data-<UUID>.sqlite` of the
group.com.apple.reminders domain, one store per account (iCloud, local, each CalDAV account), so
`run` takes one store or a folder and reads every `Data-*.sqlite` below it. Two tables matter:

    ZREMCDREMINDER  (Z_PK, ZIDENTIFIER the reminder's UUID as 16 bytes, ZTITLE, ZNOTES,
                     ZCOMPLETED, ZCOMPLETIONDATE, ZCREATIONDATE, ZLASTMODIFIEDDATE, ZDUEDATE,
                     ZDISPLAYDATEDATE, ZALLDAY, ZTIMEZONE, ZPRIORITY, ZFLAGGED,
                     ZMARKEDFORDELETION, ZLIST → ZREMCDBASELIST, ZPARENTREMINDER → a reminder;
                     dates are seconds since 2001-01-01 UTC)
    ZREMCDBASELIST  (Z_PK, ZNAME, ZISGROUP, ZPARENTLIST → the group it sits in, ZMARKEDFORDELETION)

One task/v1 line per reminder: kind `task`, tier 2 (a reminder is the owner's own words, like a
note), source `apple-reminders`, `at` the reminder's creation time in UTC. `raw_id` is
`<uuid>@<last modified>`, so a reminder completed or edited after an import is a new line and one
unchanged appends nothing. `status` is `completed` when ZCOMPLETED is set, else `open`;
`completed_at` is ZCOMPLETIONDATE. `due`: an all-day reminder keeps its day as `YYYY-MM-DD` —
Apple stores it as midnight UTC of that day in ZDUEDATE; a timed one is the instant the phone
showed it at (ZDISPLAYDATEDATE: a reminder without a zone keeps its wall clock in ZDUEDATE as if it
were UTC, and the display date is the real instant), as RFC 3339 UTC. `list` is the list's name,
`notes` the notes text, `source` the app (`apple-reminders`). Priority, the flag, the zone, a
parent reminder (a subtask), the list's group and the store's file name go under `extra`.

A reminder without a title is skipped and counted (its title lives only in an opaque
ZTITLEDOCUMENT); one without a creation date too. A reminder marked for deletion (still in the
store until Recently Deleted is emptied) is a line with `extra.deleted` true, counted. Pure: each
store opened `mode=ro`, `immutable=1` (no lock, no journal beside the source), one SELECT streamed
through the cursor, no network.
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

NAME = "apple-reminders"
KIND = "task"
TIER = 2
SCHEMA = "task/v1"

SQLITE_HEADER = b"SQLite format 3\x00"
REQUIRED_TABLES = frozenset({"ZREMCDREMINDER", "ZREMCDBASELIST"})
STORE_GLOB = "Data-*.sqlite"
APPLE_EPOCH = 978_307_200  # 2001-01-01T00:00:00Z; every date column counts from it
EARLIEST_DATE = 300_000_000  # 2010-07-07: anything earlier is a placeholder, not a creation time

QUERY = """
SELECT r.Z_PK, r.ZIDENTIFIER, r.ZCKIDENTIFIER, r.ZTITLE, r.ZNOTES, r.ZCOMPLETED, r.ZCOMPLETIONDATE,
       r.ZCREATIONDATE, r.ZLASTMODIFIEDDATE, r.ZDUEDATE, r.ZDISPLAYDATEDATE, r.ZALLDAY, r.ZTIMEZONE,
       r.ZPRIORITY, r.ZFLAGGED, r.ZMARKEDFORDELETION, r.ZSTARTDATE,
       l.ZNAME, l.ZMARKEDFORDELETION, g.ZNAME, p.ZIDENTIFIER
FROM ZREMCDREMINDER AS r
LEFT JOIN ZREMCDBASELIST AS l ON l.Z_PK = r.ZLIST
LEFT JOIN ZREMCDBASELIST AS g ON g.Z_PK = l.ZPARENTLIST
LEFT JOIN ZREMCDREMINDER AS p ON p.Z_PK = r.ZPARENTREMINDER
ORDER BY r.Z_PK
"""


def sniff(path: Path) -> bool:
    """A Reminders store (a SQLite file with ZREMCDREMINDER and ZREMCDBASELIST), or a folder with
    one anywhere below it. Never raises."""
    path = Path(path)
    try:
        if path.is_dir():
            return any(_is_store(p) for p in stores(path))
        return _is_store(path)
    except OSError:
        return False


def stores(path: Path) -> list[Path]:
    """The stores `run` would read: `path` itself when it is a file, else every `Data-*.sqlite`
    below it, in path order."""
    path = Path(path)
    if path.is_file():
        return [path]
    return sorted(p for p in path.rglob(STORE_GLOB) if p.is_file())


def _is_store(path: Path) -> bool:
    try:
        if not path.is_file():
            return False
        with path.open("rb") as fh:
            if fh.read(len(SQLITE_HEADER)) != SQLITE_HEADER:
                return False
        con = _open(path)
    except (OSError, ValueError, sqlite3.Error):
        return False
    try:
        return _tables(con) >= REQUIRED_TABLES
    except sqlite3.Error:
        return False
    finally:
        con.close()


def _open(path: Path) -> sqlite3.Connection:
    """Read-only and immutable: SQLite neither locks the file nor writes a journal beside it."""
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)


def _tables(con: sqlite3.Connection) -> set[str]:
    rows = con.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(name) for (name,) in rows}


def run(
    path: Path, since: str | None = None, counts: dict[str, int] | None = None
) -> Iterator[dict[str, Any]]:
    """One task/v1 line per reminder, store by store, each in Z_PK order, streamed.

    `since` is RFC3339 UTC; reminders created before it are not yielded. `counts` tallies what was
    left out — `skipped_no_title`, `skipped_bad_date` (no creation date, or one before 2010) — and
    what was noted: `deleted` (marked for deletion, still a line), `no_identifier` (keyed by row
    id instead)."""
    counts = counts if counts is not None else {}
    for store in stores(Path(path)):
        if not _is_store(store):
            continue
        con = _open(store)
        try:
            for row in con.execute(QUERY):  # the cursor streams; nothing is accumulated
                draft = _draft(row, store.name, counts)
                if draft is not None and not (since and draft["at"] < since):
                    yield draft
        finally:
            con.close()


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _draft(row: tuple[Any, ...], store_name: str, counts: dict[str, int]) -> dict[str, Any] | None:
    (
        pk,
        identifier,
        ck_identifier,
        title,
        notes,
        completed,
        completion_date,
        creation_date,
        modified_date,
        due_date,
        display_date,
        all_day,
        timezone,
        priority,
        flagged,
        deleted,
        start_date,
        list_name,
        list_deleted,
        group_name,
        parent_identifier,
    ) = row
    at = _rfc3339(creation_date)
    if at is None:
        _count(counts, "skipped_bad_date")
        return None
    title = _text(title)
    if title is None:
        _count(counts, "skipped_no_title")
        return None
    key = _uuid(identifier) or _text(ck_identifier)
    if key is None:
        key = f"pk{pk}"
        _count(counts, "no_identifier")
    modified_at = _rfc3339(modified_date) or at
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": f"{key}@{modified_at}",
        "title": title,
        "status": "completed" if completed else "open",
    }
    due = _due(due_date, display_date, bool(all_day))
    if due is not None:
        payload["due"] = due
    completed_at = _rfc3339(completion_date) if completed else None
    if completed_at is not None:
        payload["completed_at"] = completed_at
    list_name = _text(list_name)
    if list_name is not None:
        payload["list"] = list_name
    payload["source"] = NAME
    notes = _text(notes)
    if notes is not None:
        payload["notes"] = notes
    extra: dict[str, Any] = {"pk": pk, "store": store_name, "identifier": key, "modified_at": modified_at}
    if isinstance(priority, int) and priority:
        extra["priority"] = priority
    if flagged:
        extra["flagged"] = True
    if all_day:
        extra["all_day"] = True
    zone = _text(timezone)
    if zone is not None:
        extra["timezone"] = zone
    start = _rfc3339(start_date)
    if start is not None:
        extra["start"] = start
    group_name = _text(group_name)
    if group_name is not None:
        extra["list_group"] = group_name
    if list_deleted:
        extra["list_deleted"] = True
    parent = _uuid(parent_identifier)
    if parent is not None:
        extra["parent"] = parent
    if deleted:
        extra["deleted"] = True
        _count(counts, "deleted")
    payload["extra"] = extra
    return {
        "at": at,
        "end": None,
        "tz": None,  # the logbook's own
        "source": NAME,
        "kind": KIND,
        "tier": TIER,
        "payload": payload,
    }


def _due(due_date: object, display_date: object, all_day: bool) -> str | None:
    """An all-day reminder's day, else the instant the phone showed the reminder at."""
    if all_day:
        when = _datetime(due_date) or _datetime(display_date)
        return when.strftime("%Y-%m-%d") if when is not None else None
    return _rfc3339(display_date) or _rfc3339(due_date)


def _text(value: object) -> str | None:
    """A non-blank string, stripped; anything else is None."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def _uuid(value: object) -> str | None:
    """The lowercase UUID a 16-byte ZIDENTIFIER holds; None for anything else."""
    if isinstance(value, bytes | memoryview) and len(value) == 16:
        return str(uuid.UUID(bytes=bytes(value)))
    return None


def _datetime(seconds_since_2001: object) -> datetime | None:
    if not isinstance(seconds_since_2001, int | float) or isinstance(seconds_since_2001, bool):
        return None
    if seconds_since_2001 < EARLIEST_DATE:
        return None
    try:
        return datetime.fromtimestamp(APPLE_EPOCH + int(seconds_since_2001), UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _rfc3339(seconds_since_2001: object) -> str | None:
    when = _datetime(seconds_since_2001)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ") if when is not None else None
