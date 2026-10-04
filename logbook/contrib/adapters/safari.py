"""Safari's History.db → browse/v1 (RFC 0017).

The store an iPhone backs up as HomeDomain `Library/Safari/History.db` (`import-backup` copies it
to `inbox/<backup>/safari/` and runs this adapter on the copy) and the Mac keeps at
`~/Library/Safari/History.db`. Two tables matter:

    history_items   (id, url, visit_count, …)            one row per page
    history_visits  (id, history_item → history_items.id, visit_time, title?, load_successful?,
                     redirect_source?, redirect_destination?, …)   one row per visit

`visit_time` is seconds since 2001-01-01 UTC (a REAL). The columns are discovered with
`PRAGMA table_info`: only `history_items.id`, `history_items.url`, `history_visits.history_item`
and `history_visits.visit_time` are required; `title` and `load_successful` are read when present
and the rest of the row is left alone, so a Safari that adds or drops a column still reads.

One line per visit: kind `browse`, tier 2, source `safari`, `browser` `safari`, `at` the visit
time in UTC (to the second), `raw_id` `safari:<visit_time as stored>:<sha256(url)[:16]>` — the
same on the phone's copy and the Mac's, so the two dedupe (RFC 0017 rule 4). `extra.load_successful`
is false, and counted, for a visit the page did not load on. Pure: opened `mode=ro`,
`immutable=1` (no lock, no journal beside the source), one SELECT streamed, no network.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

NAME = "safari"
KIND = "browse"
TIER = 2
SCHEMA = "browse/v1"
BROWSER = "safari"

SQLITE_HEADER = b"SQLite format 3\x00"
APPLE_EPOCH = 978_307_200  # 2001-01-01T00:00:00Z
REQUIRED = {"history_items": ("id", "url"), "history_visits": ("history_item", "visit_time")}
OPTIONAL = ("title", "load_successful")


def sniff(path: Path) -> bool:
    """A SQLite file with Safari's `history_items` and `history_visits` tables. Never raises."""
    path = Path(path)
    try:
        if not path.is_file():
            return False
        with path.open("rb") as fh:
            if fh.read(len(SQLITE_HEADER)) != SQLITE_HEADER:
                return False
        con = _open(path)
        try:
            return _columns(con) is not None
        finally:
            con.close()
    except (OSError, sqlite3.Error):
        return False


def _open(path: Path) -> sqlite3.Connection:
    """Read-only and immutable: SQLite neither locks the file nor writes a journal beside it."""
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)


def _columns(con: sqlite3.Connection) -> dict[str, set[str]] | None:
    """The columns of the two tables, or None when a required one is missing."""
    found: dict[str, set[str]] = {}
    for table, needed in REQUIRED.items():
        columns = {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}
        if not all(c in columns for c in needed):
            return None
        found[table] = columns
    return found


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
) -> Iterator[dict[str, Any]]:
    """One browse/v1 line draft per visit in the store at `path`, oldest first. `since` is
    RFC3339 UTC; `timezone` is the record's zone."""
    counts = counts if counts is not None else {}
    tz = timezone or "UTC"
    con = _open(Path(path))
    try:
        columns = _columns(con)
        if columns is None:
            raise ValueError(f"{path} is not a Safari History.db (no history_items/history_visits)")
        have = columns["history_visits"]
        selected = ["i.url", "v.visit_time"] + [f"v.{c}" if c in have else "NULL" for c in OPTIONAL]
        query = (
            f"SELECT {', '.join(selected)} FROM history_visits AS v"
            " JOIN history_items AS i ON i.id = v.history_item ORDER BY v.visit_time, v.history_item"
        )
        for url, visit_time, title, loaded in con.execute(query):
            if not url or not isinstance(visit_time, int | float):
                _count(counts, "skipped_no_timestamp" if url else "skipped_no_url")
                continue
            at = datetime.fromtimestamp(APPLE_EPOCH + float(visit_time), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            if since is not None and at < since:
                continue
            payload: dict[str, Any] = {
                "schema": SCHEMA,
                "raw_id": f"{BROWSER}:{visit_time!r}:{hashlib.sha256(str(url).encode()).hexdigest()[:16]}",
                "url": str(url),
            }
            name = " ".join(str(title or "").split())
            if name:
                payload["title"] = name
            payload["action"] = "visit"
            payload["browser"] = BROWSER
            if loaded is not None and not loaded:
                payload["extra"] = {"load_successful": False}
                _count(counts, "load_failed")
            yield {
                "at": at,
                "end": None,
                "tz": tz,
                "source": NAME,
                "kind": KIND,
                "tier": TIER,
                "payload": payload,
            }
    finally:
        con.close()


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1
