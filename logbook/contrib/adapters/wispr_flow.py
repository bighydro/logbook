"""Wispr Flow's dictation history → transcript/v1 (RFC 0004), one line per dictation, tier 3.

Wispr Flow is a dictation keyboard: the owner speaks, the app transcribes, a model tidies the words,
and the text is typed into whatever app had the cursor. The iPhone app keeps every dictation in a
Core Data store, `Documents/database.sqlite` in its container (`AppDomain-com.wispr.flowapp`; the
recordings are `.wav` files beside it, one per dictation, not read here). `logbook import-backup`
copies the store out (source `wispr-flow`) and runs this adapter on the copy. One table matters:

    ZTRANSCRIPTION   ZID                 the dictation's UUID
                     ZSTARTDATE, ZENDDATE   seconds since 2001-01-01 UTC
                     ZASRTEXT            what the speech recogniser heard
                     ZLLMTEXT            the model's tidied text
                     ZTRANSCRIPTIONTEXT  what was typed: the tidied text when there is one
                     ZSTATUS             formatted, raw_transcript, or NULL for one that failed
                     ZTRANSCRIPTORIGIN, ZLANGUAGE, ZAPPBUNDLEID   where it came from, its language,
                                         and the app it was typed into

Each row with text is one `transcript/v1` line: a dictation is a spoken interaction with one speaker
(RFC 0004's notes), `provider` `wispr-flow`, `participants` empty, `language` the row's. The text —
the typed text, else the tidied text, else the recogniser's — is never in the line: it is stored
once as a SPEC §1.1 attachment (`text/plain`, through the `store` callback `logbook add` passes)
and `content` points at it; `extra.text` says which of the three it was (`formatted` or `asr`), and
`extra` keeps the app, the status and the origin. No title: the app gives none and a reader derives
one. `raw_id` is `wispr-flow:<ZID>`. Tier 3 by default (the owner's own words, often about other
people and typed into private chats); `logbook add --tier` overrides. Rows without any text or
without a start are skipped and counted; an end before its start is dropped and counted. Opened
`mode=ro`, `immutable=1`, read in start order; no network.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ...core.attachments import reference

NAME = "wispr-flow"
KIND = "transcript"
SCHEMA = "transcript/v1"
TIER = 3  # the owner's spoken words, typed into private chats; `logbook add --tier` overrides
MEDIA_TYPE = "text/plain"
TABLE = "ZTRANSCRIPTION"
SQLITE_HEADER = b"SQLite format 3\x00"
APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=UTC)
TEXT_COLUMNS = (("ZTRANSCRIPTIONTEXT", "formatted"), ("ZLLMTEXT", "formatted"), ("ZASRTEXT", "asr"))
OPTIONAL = (
    "ZENDDATE",
    "ZSTATUS",
    "ZTRANSCRIPTORIGIN",
    "ZLANGUAGE",
    "ZAPPBUNDLEID",
    "ZLLMTEXT",
    "ZASRTEXT",
    "ZTRANSCRIPTIONTEXT",
)


def sniff(path: Path) -> bool:
    """A SQLite file with a ZTRANSCRIPTION table. Never raises."""
    path = Path(path)
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
        return TABLE in _tables(con)
    except sqlite3.Error:
        return False
    finally:
        con.close()


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    tier: int | None = None,
    store: Callable[[bytes], object] | None = None,
) -> Iterator[dict[str, Any]]:
    """One transcript/v1 draft per dictation with text, in start order. `since` is RFC3339 UTC;
    drafts whose `at` is before it are not yielded. `counts` tallies `skipped_no_text` and
    `skipped_no_timestamp`, and notes `end_before_start`. `tier` overrides 3. `store` is called with
    the text's bytes just before each draft is yielded."""
    counts = counts if counts is not None else {}
    con = _open(Path(path))
    try:
        columns = _columns(con, TABLE)
        selected = ["ZID", "ZSTARTDATE", *(c for c in OPTIONAL if c in columns)]
        query = f"SELECT {', '.join(selected)} FROM {TABLE} ORDER BY ZSTARTDATE, Z_PK"
        for row in con.execute(query):
            values = dict(zip(selected, row, strict=True))
            result = _draft(values, counts, tier or TIER)
            if result is None:
                continue
            draft, data = result
            if since and draft["at"] < since:
                continue
            if store is not None:
                store(data)
            yield draft
    finally:
        con.close()


def _open(path: Path) -> sqlite3.Connection:
    """Read-only and immutable: SQLite neither locks the file nor writes a journal beside it."""
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)


def _tables(con: sqlite3.Connection) -> set[str]:
    return {str(name) for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _draft(values: dict[str, Any], counts: dict[str, int], tier: int) -> tuple[dict[str, Any], bytes] | None:
    text, which = None, None
    for column, label in TEXT_COLUMNS:
        candidate = values.get(column)
        if isinstance(candidate, str) and candidate.strip():
            text, which = candidate, label
            break
    if text is None:
        _count(counts, "skipped_no_text")
        return None
    start = _instant(values.get("ZSTARTDATE"))
    if start is None:
        _count(counts, "skipped_no_timestamp")
        return None
    end = _instant(values.get("ZENDDATE"))
    if end is not None and end < start:
        _count(counts, "end_before_start")
        end = None
    data = text.encode("utf-8")
    extra: dict[str, Any] = {}
    for key, column in (("app", "ZAPPBUNDLEID"), ("status", "ZSTATUS"), ("origin", "ZTRANSCRIPTORIGIN")):
        value = values.get(column)
        if isinstance(value, str) and value:
            extra[key] = value
    extra["text"] = which
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "provider": NAME,
        "raw_id": f"{NAME}:{values.get('ZID')}",
        "participants": [],
    }
    language = values.get("ZLANGUAGE")
    if isinstance(language, str) and language:
        payload["language"] = language
    payload["content"] = reference(data, MEDIA_TYPE)
    payload["extra"] = extra
    draft = {
        "at": _stamp(start),
        "end": _stamp(end) if end is not None else None,
        "tz": None,
        "source": NAME,
        "kind": KIND,
        "tier": tier,
        "payload": payload,
    }
    return draft, data


def _instant(seconds: object) -> datetime | None:
    if isinstance(seconds, bool) or not isinstance(seconds, int | float):
        return None
    return APPLE_EPOCH + timedelta(seconds=float(seconds))


def _stamp(when: datetime) -> str:
    return when.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
