"""Apple Books' annotation store → highlight/v1 (RFC 0022).

Reads `AEAnnotation_v10312011_1727_local.sqlite`, the store Books keeps under
`Documents/storeFiles/` on an iPhone (`AppDomain-com.apple.iBooks`; `logbook import-backup` copies it
out as `apple-books/`) and under `~/Library/Containers/com.apple.iBooksX/Data/Documents/AEAnnotation/`
on a Mac. One table matters:

    ZAEANNOTATION  (ZANNOTATIONUUID, ZANNOTATIONASSETID, ZANNOTATIONTYPE, ZANNOTATIONSTYLE,
                    ZANNOTATIONISUNDERLINE, ZANNOTATIONDELETED, ZANNOTATIONCREATIONDATE,
                    ZANNOTATIONMODIFICATIONDATE — seconds since 2001-01-01 UTC —, ZANNOTATIONLOCATION,
                    ZANNOTATIONSELECTEDTEXT, ZANNOTATIONNOTE)

A row with selected text is a highlight (`type` 2; `ZANNOTATIONISUNDERLINE` says whether it is drawn
as an underline, `ZANNOTATIONSTYLE` is its colour index); a row of type 3 without text is where the
owner last stopped reading, the app's own state, skipped and counted (RFC 0022 rule 2); any other row
without text is a bookmark. A row with `ZANNOTATIONDELETED` set is a tombstone, skipped and counted
(rule 3). The location is an EPUB CFI (or a page reference for a PDF), kept as text.

The book's title and author come from the library store, `BKLibrary-1-*.sqlite`
(`ZBKLIBRARYASSET`: ZASSETID, ZTITLE, ZAUTHOR), looked up by the mark's asset id. The adapter looks for
it beside the annotation store (where `import-backup` puts it) and in `../BKLibrary/` (Books' own
`Documents/` layout); a mark whose book the library does not list keeps its `asset_id` and no title,
counted `no_title` (rule 4). Nothing is ever guessed from the quote.

Every line is tier 2 (RFC 0022; `logbook add --tier` overrides); `tz` is the record's zone when `logbook
add` passes one, else None. `run` also takes the folder the store is in (`import-backup` runs a
glob-named source on its copies' folder). Pure: both stores are opened `mode=ro`, `immutable=1`, read
once in creation order; no network.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

NAME = "apple-books"
KIND = "highlight"
TIER = 2  # RFC 0022: what the owner read and wrote; `logbook add --tier` overrides
SCHEMA = "highlight/v1"

SQLITE_HEADER = b"SQLite format 3\x00"
APPLE_EPOCH_UTC = datetime(2001, 1, 1, tzinfo=UTC)
PLACEHOLDER_BEFORE_YEAR = 1900
ANNOTATIONS = "ZAEANNOTATION"
LIBRARY_TABLE = "ZBKLIBRARYASSET"
LIBRARY_GLOB = "BKLibrary*.sqlite"
LIBRARY_FOLDER = "BKLibrary"  # Books' Documents/ keeps the library here, beside storeFiles/
READING_POSITION = 3  # ZANNOTATIONTYPE of the row that marks where the owner last stopped

COLUMNS = (
    "Z_PK",
    "ZANNOTATIONUUID",
    "ZANNOTATIONASSETID",
    "ZANNOTATIONTYPE",
    "ZANNOTATIONSTYLE",
    "ZANNOTATIONISUNDERLINE",
    "ZANNOTATIONDELETED",
    "ZANNOTATIONCREATIONDATE",
    "ZANNOTATIONMODIFICATIONDATE",
    "ZANNOTATIONLOCATION",
    "ZANNOTATIONSELECTEDTEXT",
    "ZANNOTATIONNOTE",
)


def sniff(path: Path) -> bool:
    """A SQLite file with a `ZAEANNOTATION` table. Never raises."""
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
        return ANNOTATIONS in _tables(con)
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


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
    tier: int | None = None,
) -> Iterator[dict[str, Any]]:
    """One highlight/v1 line per highlight and bookmark, in creation order.

    `since` is RFC3339 UTC; lines with `at` before it are not yielded. `counts` tallies
    `skipped_reading_position`, `skipped_deleted`, `skipped_no_date`, `skipped_placeholder_date` and
    `no_title` (a line written without a book the library knows). `timezone` is the record's zone,
    the line's `tz`. `tier` overrides the default 2."""
    path = _store(Path(path))
    counts = counts if counts is not None else {}
    books = _library(path)
    con = _open(path)
    try:
        present = _columns(con, ANNOTATIONS)
        select = ", ".join(c if c in present else f"NULL AS {c}" for c in COLUMNS)
        order = "ZANNOTATIONCREATIONDATE, Z_PK" if "ZANNOTATIONCREATIONDATE" in present else "Z_PK"
        for row in con.execute(f"SELECT {select} FROM {ANNOTATIONS} ORDER BY {order}"):
            values = dict(zip(COLUMNS, row, strict=True))
            line = _line(values, books, counts, timezone, tier or TIER)
            if line is None or (since and line["at"] < since):
                continue
            yield line
    finally:
        con.close()


def _store(path: Path) -> Path:
    """The annotation store: `path` itself, or the first `AEAnnotation*.sqlite` in the folder `path`
    (`import-backup` runs a pattern source on the folder it copied the store to)."""
    if path.is_dir():
        found = sorted(p for p in path.glob("AEAnnotation*.sqlite") if p.is_file())
        if found:
            return found[0]
    return path


def _library(store: Path) -> dict[str, tuple[str | None, str | None]]:
    """`asset id → (title, author)` from the first BKLibrary store beside the annotation store or in
    Books' `../BKLibrary/` folder; nothing when there is none or it cannot be read."""
    candidates = sorted(store.parent.glob(LIBRARY_GLOB)) + sorted(
        (store.parent.parent / LIBRARY_FOLDER).glob(LIBRARY_GLOB)
    )
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            con = _open(candidate)
        except (OSError, ValueError, sqlite3.Error):
            continue
        try:
            if LIBRARY_TABLE not in _tables(con):
                continue
            columns = _columns(con, LIBRARY_TABLE)
            if "ZASSETID" not in columns:
                continue
            title = "ZTITLE" if "ZTITLE" in columns else "NULL"
            author = "ZAUTHOR" if "ZAUTHOR" in columns else "NULL"
            books: dict[str, tuple[str | None, str | None]] = {}
            for asset_id, title_text, author_text in con.execute(
                f"SELECT ZASSETID, {title}, {author} FROM {LIBRARY_TABLE}"
            ):
                if isinstance(asset_id, str) and asset_id and asset_id not in books:
                    books[asset_id] = (_text(title_text) or None, _text(author_text) or None)
            return books
        except sqlite3.Error:
            continue
        finally:
            con.close()
    return {}


def _line(
    values: dict[str, Any],
    books: dict[str, tuple[str | None, str | None]],
    counts: dict[str, int],
    timezone: str | None,
    tier: int,
) -> dict[str, Any] | None:
    if values.get("ZANNOTATIONDELETED"):
        _count(counts, "skipped_deleted")
        return None
    quote = _text(values.get("ZANNOTATIONSELECTEDTEXT"))
    if not quote and values.get("ZANNOTATIONTYPE") == READING_POSITION:
        _count(counts, "skipped_reading_position")
        return None
    created = _datetime(values.get("ZANNOTATIONCREATIONDATE"))
    if created is None:
        _count(counts, "skipped_no_date")
        return None
    if created.year < PLACEHOLDER_BEFORE_YEAR:
        _count(counts, "skipped_placeholder_date")
        return None
    uuid = _text(values.get("ZANNOTATIONUUID"))
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": uuid or f"row:{values['Z_PK']}",
        "type": "highlight" if quote else "bookmark",
    }
    asset_id = _text(values.get("ZANNOTATIONASSETID"))
    title, author = books.get(asset_id, (None, None)) if asset_id else (None, None)
    if title:
        payload["title"] = title
    else:
        _count(counts, "no_title")
    if author:
        payload["author"] = author
    if asset_id:
        payload["asset_id"] = asset_id
    if quote:
        payload["quote"] = quote
    note = _text(values.get("ZANNOTATIONNOTE"))
    if note:
        payload["note"] = note
    location = _text(values.get("ZANNOTATIONLOCATION"))
    if location:
        payload["location"] = location
    modified = _datetime(values.get("ZANNOTATIONMODIFICATIONDATE"))
    if modified is not None and modified > created:
        payload["modified_at"] = _stamp(modified)
    extra: dict[str, Any] = {}
    style = values.get("ZANNOTATIONSTYLE")
    if isinstance(style, int) and not isinstance(style, bool):
        extra["style"] = style
    underline = values.get("ZANNOTATIONISUNDERLINE")
    if underline is not None:
        extra["underline"] = bool(underline)
    if extra:
        payload["extra"] = extra
    return {
        "at": _stamp(created),
        "end": None,
        "tz": timezone,
        "source": NAME,
        "kind": KIND,
        "tier": tier,
        "payload": payload,
    }


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _text(value: object) -> str:
    if isinstance(value, bytes | bytearray | memoryview):
        try:
            return bytes(value).decode("utf-8").strip()
        except UnicodeDecodeError:
            return ""
    return value.strip() if isinstance(value, str) else ""


def _datetime(seconds_since_2001: object) -> datetime | None:
    """Arithmetic from the epoch, not `fromtimestamp`: Windows refuses instants before 1970."""
    if isinstance(seconds_since_2001, bool) or not isinstance(seconds_since_2001, int | float):
        return None
    if seconds_since_2001 != seconds_since_2001:  # NaN
        return None
    try:
        return APPLE_EPOCH_UTC + timedelta(seconds=int(seconds_since_2001))
    except (OverflowError, ValueError):
        return None


def _stamp(when: datetime) -> str:
    return when.astimezone(UTC).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"
