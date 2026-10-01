"""Apple Voice Memos' CloudRecordings.db → voice-memo/v1 (RFC 0023).

Reads the store the app keeps in its shared container (`AppDomainGroup-group.com.apple.VoiceMemos.shared`,
`Recordings/CloudRecordings.db`, with the audio files beside it in the same folder; on a Mac under
`~/Library/Group Containers/*.com.apple.VoiceMemos.shared/Recordings/`). `logbook import-backup` copies
the store out as `voice-memos/CloudRecordings.db` and the audio under `voice-memos/Recordings/`, so the
adapter looks for a recording's file first in `Recordings/` beside the store, then beside the store
itself. One table matters:

    ZCLOUDRECORDING  (ZUNIQUEID, ZDATE — seconds since 2001-01-01 UTC —, ZDURATION, ZCUSTOMLABEL,
                      ZPATH — the audio file's name —, ZFOLDER, ZFLAGS, ZEVICTIONDATE)

`ZCUSTOMLABEL` is the title the owner sees (their own words, or the place name the app chose);
`ZENCRYPTEDTITLE` is the same title as the app syncs it and is never read. `ZFOLDER` names a row of
`ZFOLDER`, whose `ZENCRYPTEDNAME` is not in the clear, so no `folder` is written. The file is `.m4a`
(ISO base media, `audio/mp4`) or, for a recording edited in the app, a `.qta` QuickTime composition
(`video/quicktime`); any other suffix is `application/octet-stream` with `file_name` carrying it.

The audio is hashed a chunk at a time and the line carries `{sha256, bytes, media_type}`; with
`attachments=True` (`logbook add --attachments`, `import-backup --attachments`) the file is also put in
the §1.1 store through the `store_file` callback `logbook add` hands in, and the reference carries its
`path` (RFC 0023 rule 2). A recording whose file is not there is a line without `media`, counted
`media_missing`. No transcription happens here (rule 3): that is a later, local step.

`at` is `ZDATE`; `end` is `at` plus `ZDURATION` when the store has one. Every line is tier 2 (RFC 0023;
`logbook add --tier` overrides); `tz` is the record's zone when given. Pure: opened `mode=ro`,
`immutable=1`, one SELECT in date order; the only writing is through `store_file`; no network.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .. import attachments

NAME = "voice-memos"
KIND = "voice-memo"
TIER = 2  # RFC 0023: the owner's own voice; `logbook add --tier` overrides
SCHEMA = "voice-memo/v1"

SQLITE_HEADER = b"SQLite format 3\x00"
APPLE_EPOCH_UTC = datetime(2001, 1, 1, tzinfo=UTC)
PLACEHOLDER_BEFORE_YEAR = 1900
RECORDINGS = "ZCLOUDRECORDING"
MEDIA_FOLDER = "Recordings"  # where `import-backup` puts the audio beside the store copy
MEDIA_TYPES = {".m4a": "audio/mp4", ".qta": "video/quicktime", ".caf": "audio/x-caf", ".wav": "audio/wav"}
FALLBACK_MEDIA_TYPE = "application/octet-stream"
COLUMNS = ("Z_PK", "ZUNIQUEID", "ZDATE", "ZDURATION", "ZCUSTOMLABEL", "ZPATH", "ZFLAGS", "ZEVICTIONDATE")


def sniff(path: Path) -> bool:
    """A SQLite file with a `ZCLOUDRECORDING` table. Never raises."""
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
        return RECORDINGS in _tables(con)
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
    attachments: bool | None = None,
    store_file: Callable[[Path], object] | None = None,
) -> Iterator[dict[str, Any]]:
    """One voice-memo/v1 line per recording, in date order.

    `since` is RFC3339 UTC; lines with `at` before it are not yielded. `counts` tallies
    `skipped_no_date`, `skipped_placeholder_date`, `media_missing`, and `attachments_stored` or
    `attachments_referenced`. `attachments=True` puts each file through `store_file` just before its
    line and gives the reference a `path`. `timezone` is the record's zone; `tier` overrides 2."""
    path = Path(path)
    counts = counts if counts is not None else {}
    keep = bool(attachments)
    con = _open(path)
    try:
        present = _columns(con, RECORDINGS)
        select = ", ".join(c if c in present else f"NULL AS {c}" for c in COLUMNS)
        order = "ZDATE, Z_PK" if "ZDATE" in present else "Z_PK"
        for row in con.execute(f"SELECT {select} FROM {RECORDINGS} ORDER BY {order}"):
            values = dict(zip(COLUMNS, row, strict=True))
            result = _line(values, path.parent, counts, timezone, tier or TIER, keep)
            if result is None:
                continue
            line, file = result
            if since and line["at"] < since:
                continue
            if keep and file is not None and store_file is not None:
                store_file(file)
            yield line
    finally:
        con.close()


def _line(
    values: dict[str, Any],
    folder: Path,
    counts: dict[str, int],
    timezone: str | None,
    tier: int,
    keep: bool,
) -> tuple[dict[str, Any], Path | None] | None:
    started = _datetime(values.get("ZDATE"))
    if started is None:
        _count(counts, "skipped_no_date")
        return None
    if started.year < PLACEHOLDER_BEFORE_YEAR:
        _count(counts, "skipped_placeholder_date")
        return None
    uid = _text(values.get("ZUNIQUEID"))
    payload: dict[str, Any] = {"schema": SCHEMA, "raw_id": uid or f"row:{values['Z_PK']}"}
    title = _text(values.get("ZCUSTOMLABEL"))
    if title:
        payload["title"] = title
    duration = _number(values.get("ZDURATION"))
    end: datetime | None = None
    if duration is not None and duration >= 0:
        payload["duration_s"] = _round(duration)
        end = started + timedelta(seconds=duration)
    file_name = _text(values.get("ZPATH"))
    file: Path | None = None
    if file_name:
        payload["file_name"] = file_name
        file = _find(folder, file_name)
        if file is None:
            _count(counts, "media_missing")
        else:
            media_type = MEDIA_TYPES.get(Path(file_name).suffix.lower(), FALLBACK_MEDIA_TYPE)
            reference = attachments.reference_path(file, media_type)
            if keep:
                _count(counts, "attachments_stored")
            else:
                del reference["path"]
                _count(counts, "attachments_referenced")
            payload["media"] = reference
    else:
        _count(counts, "media_missing")
    extra: dict[str, Any] = {}
    flags = values.get("ZFLAGS")
    if isinstance(flags, int) and not isinstance(flags, bool):
        extra["flags"] = flags
    if values.get("ZEVICTIONDATE") is not None:
        extra["evicted"] = True
    if extra:
        payload["extra"] = extra
    line = {
        "at": _stamp(started),
        "end": _stamp(end) if end is not None else None,
        "tz": timezone,
        "source": NAME,
        "kind": KIND,
        "tier": tier,
        "payload": payload,
    }
    return line, (file if keep else None)


def _find(folder: Path, file_name: str) -> Path | None:
    """The audio file: under `Recordings/` beside the store (an `import-backup` copy), else beside
    the store (the phone's and the Mac's own layout). A name that would leave the folder is not
    looked for."""
    parts = Path(file_name).parts
    if len(parts) != 1 or file_name in ("..", "."):
        return None
    for candidate in (folder / MEDIA_FOLDER / file_name, folder / file_name):
        if candidate.is_file():
            return candidate
    return None


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _text(value: object) -> str:
    if isinstance(value, bytes | bytearray | memoryview):
        try:
            return bytes(value).decode("utf-8").strip()
        except UnicodeDecodeError:
            return ""
    return value.strip() if isinstance(value, str) else ""


def _number(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def _round(value: int | float) -> int | float:
    rounded = round(float(value), 3)
    return int(rounded) if rounded == int(rounded) else rounded


def _datetime(seconds_since_2001: object) -> datetime | None:
    """Arithmetic from the epoch, not `fromtimestamp`: Windows refuses instants before 1970."""
    number = _number(seconds_since_2001)
    if number is None:
        return None
    try:
        return APPLE_EPOCH_UTC + timedelta(seconds=int(number))
    except (OverflowError, ValueError):
        return None


def _stamp(when: datetime) -> str:
    return when.astimezone(UTC).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"
