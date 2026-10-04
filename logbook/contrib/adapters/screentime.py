"""Screen Time → `app-use` lines: which app was in use, from when to when, on which device.

Two stores, one mapping. On a Mac, CoreDuet's knowledge store `knowledgeC.db` (per user under
`~/Library/Application Support/Knowledge/`, the system's under `/private/var/db/CoreDuet/Knowledge/`;
both need Full Disk Access for the terminal) keeps one `ZOBJECT` row per app session in the
`/app/usage` stream:

    ZOBJECT   (ZSTREAMNAME, ZVALUESTRING — the bundle id —, ZSTARTDATE, ZENDDATE — seconds since
               2001-01-01 UTC —, ZSOURCE → ZSOURCE.Z_PK)
    ZSOURCE   (ZDEVICEID: NULL for this Mac, another device's identifier for a synced row)

Only `/app/usage` is read. The other streams are never queried: `/app/activity` carries window titles
and content URLs under `ZSTRUCTUREDMETADATA`, and neither reaches a line, ever. An iPhone backs
Screen Time's own store up as HomeDomain `Library/Application Support/com.apple.remotemanagementd/
RMAdminStore-Local.sqlite` (`import-backup --only screentime` and `add screentime --backup DIR` copy
it out); it keeps hourly totals, not sessions:

    ZUSAGEBLOCK      (ZSTARTDATE — the top of the hour —, ZDURATIONINMINUTES, ZUSAGE → ZUSAGE)
    ZUSAGECATEGORY   (ZBLOCK → ZUSAGEBLOCK, ZIDENTIFIER — Apple's own category name —)
    ZUSAGETIMEDITEM  (ZCATEGORY → ZUSAGECATEGORY, ZBUNDLEIDENTIFIER, ZDOMAIN, ZTOTALTIMEINSECONDS)
    ZUSAGE → ZCOREDEVICE (ZIDENTIFIER, ZNAME)        ZINSTALLEDAPP (ZBUNDLEIDENTIFIER, ZDISPLAYNAME)

One line per app per hour, laid from the top of the hour for the hour's total (`extra.observed`
`hourly_total`), where a Mac session is a span (`extra.observed` `session`). A timed item with a web
domain and no bundle id is Safari's per-site time: skipped and counted, the domain never kept.

Every line: kind `app-use`, tier 2, payload `event/v1` (RFC 0009's shape — `title` the app's name
when the built-in table (`apps.BUILT_IN`) or the phone's own app table names it, else the bundle id;
`calendar` Screen Time; `all_day` false) with the app under `extra`: `bundle_id`, `app` (when
named), `device` (`mac` for this Mac, the device identifier for a synced row or the phone,
`iphone` when the phone's store has no device table), `device_name` (the phone's), `duration_s`,
`observed`, `stream`, `block_s`, `apple_category`. `raw_id` is `<device>:<bundle id>:<start>`: one
line per app per start per device, so a re-import appends nothing (ADR 0017). Each table's columns
are confirmed with `PRAGMA table_info` before a read: a column not needed may be gone and the rows
still read; a table or column needed that is not there is one error naming the store. Pure: opened
`mode=ro`, `immutable=1`, read once; no network."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ...core import apps

NAME = "screentime"
KIND = apps.KIND
TIER = 2  # what the owner did with their time; `logbook add --tier` overrides
SCHEMA = apps.SCHEMA
CALENDAR = {"id": "screen-time", "name": "Screen Time"}
MAC_DEVICE = "mac"  # the local device of a knowledgeC.db, which has no identifier of its own
IOS_DEVICE = "iphone"  # a phone store without a device table
USAGE_STREAM = "/app/usage"
SESSION, HOURLY = "session", "hourly_total"
MAC_STORE = "knowledgeC.db"
PHONE_STORE = "RMAdminStore-Local.sqlite"
MAC_DEFAULT = Path("~/Library/Application Support/Knowledge") / MAC_STORE  # expanded by the CLI

SQLITE_HEADER = b"SQLite format 3\x00"
APPLE_EPOCH_UTC = datetime(2001, 1, 1, tzinfo=UTC)
PLACEHOLDER_BEFORE_YEAR = 2000  # Screen Time did not exist; a date before this is the store's placeholder

OBJECTS, SOURCES = "ZOBJECT", "ZSOURCE"
OBJECT_COLUMNS = ("ZSTREAMNAME", "ZVALUESTRING", "ZSTARTDATE", "ZENDDATE")
BLOCKS, CATEGORIES, ITEMS, USAGE, DEVICES, INSTALLED = (
    "ZUSAGEBLOCK",
    "ZUSAGECATEGORY",
    "ZUSAGETIMEDITEM",
    "ZUSAGE",
    "ZCOREDEVICE",
    "ZINSTALLEDAPP",
)


def sniff(path: Path) -> bool:
    """A SQLite file with knowledgeC's `ZOBJECT` stream column, or Screen Time's usage tables. Never
    raises."""
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
        return _shape(con) is not None
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


def _shape(con: sqlite3.Connection) -> str | None:
    """`mac` for a knowledge store, `phone` for a Screen Time store, None for neither."""
    tables = _tables(con)
    if OBJECTS in tables and all(c in _columns(con, OBJECTS) for c in OBJECT_COLUMNS):
        return "mac"
    if BLOCKS in tables and ITEMS in tables and CATEGORIES in tables:
        return "phone"
    return None


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
    tier: int | None = None,
) -> Iterator[dict[str, Any]]:
    """One app-use line per session (a Mac's knowledgeC.db) or per app per hour (a phone's
    RMAdminStore-Local.sqlite), in start order. `since` is RFC3339 UTC; lines with `at` before it
    are not yielded. `counts` tallies `skipped_empty` (nothing in the span), `skipped_no_start`,
    `skipped_no_bundle`, `skipped_duplicate` (the same device, app and start twice),
    `skipped_web_domain` (Safari's per-site time, the domain never kept), `skipped_placeholder_date`
    and `no_name` (a line whose app nothing names). `timezone` is the record's zone, the line's `tz`;
    `tier` overrides the default 2."""
    path = _store(Path(path))
    counts = counts if counts is not None else {}
    con = _open(path)
    try:
        shape = _shape(con)
        if shape is None:
            raise ValueError(
                f"{path} is neither a knowledgeC.db with {OBJECTS}({', '.join(OBJECT_COLUMNS)})"
                f" nor an {PHONE_STORE} with {BLOCKS}, {CATEGORIES} and {ITEMS}"
            )
        drafts = _mac(con, counts) if shape == "mac" else _phone(con, counts)
        seen: set[str] = set()
        for start, end, payload in drafts:
            if payload["raw_id"] in seen:
                _count(counts, "skipped_duplicate")
                continue
            seen.add(payload["raw_id"])
            at = _stamp(start)
            if since and at < since:
                continue
            if "app" not in payload["extra"]:
                _count(counts, "no_name")
            yield {
                "at": at,
                "end": _stamp(end),
                "tz": timezone,
                "source": NAME,
                "kind": KIND,
                "tier": tier or TIER,
                "payload": payload,
            }
    finally:
        con.close()


def _store(path: Path) -> Path:
    """The store: `path` itself, or the one store in the folder `path` (`import-backup` runs a source
    on the folder it copied the store to)."""
    if path.is_dir():
        for name in (PHONE_STORE, MAC_STORE):
            if (path / name).is_file():
                return path / name
    return path


Draft = tuple[datetime, datetime, dict[str, Any]]  # start, end, payload


def _mac(con: sqlite3.Connection, counts: dict[str, int]) -> Iterator[Draft]:
    """The `/app/usage` sessions of a knowledge store, each with the device of its source row."""
    columns = _columns(con, OBJECTS)
    devices = _devices(con) if "ZSOURCE" in columns else {}
    source = "ZSOURCE" if "ZSOURCE" in columns else "NULL"
    rows = con.execute(
        f"SELECT ZVALUESTRING, ZSTARTDATE, ZENDDATE, {source} FROM {OBJECTS} WHERE ZSTREAMNAME = ?"
        " ORDER BY ZSTARTDATE, Z_PK",
        (USAGE_STREAM,),
    )
    for bundle_id, start_s, end_s, source_pk in rows:
        span = _span(bundle_id, start_s, end_s, counts)
        if span is None:
            continue
        start, end = span
        device = devices.get(source_pk) or MAC_DEVICE
        extra: dict[str, Any] = {
            "bundle_id": bundle_id,
            **_named(bundle_id, None),
            "device": device,
            "duration_s": int((end - start).total_seconds()),
            "observed": SESSION,
            "stream": USAGE_STREAM,
        }
        yield start, end, _payload(device, bundle_id, start, extra)


def _devices(con: sqlite3.Connection) -> dict[int, str]:
    """`ZSOURCE.Z_PK → device identifier` for the source rows that carry one (a synced device); a
    store without the table, or without the column, has every row local."""
    if SOURCES not in _tables(con):
        return {}
    columns = _columns(con, SOURCES)
    if "Z_PK" not in columns or "ZDEVICEID" not in columns:
        return {}
    return {
        int(pk): device.strip()
        for pk, device in con.execute(f"SELECT Z_PK, ZDEVICEID FROM {SOURCES}")
        if isinstance(pk, int) and isinstance(device, str) and device.strip()
    }


def _phone(con: sqlite3.Connection, counts: dict[str, int]) -> Iterator[Draft]:
    """The hourly totals of a Screen Time store: one per timed item with a bundle id, from the top of
    its block's hour for its seconds."""
    blocks, categories, items = (_columns(con, t) for t in (BLOCKS, CATEGORIES, ITEMS))
    needed = {
        BLOCKS: ("Z_PK", "ZSTARTDATE"),
        CATEGORIES: ("Z_PK", "ZBLOCK"),
        ITEMS: ("ZCATEGORY", "ZBUNDLEIDENTIFIER", "ZTOTALTIMEINSECONDS"),
    }
    for table, have in ((BLOCKS, blocks), (CATEGORIES, categories), (ITEMS, items)):
        missing = [c for c in needed[table] if c not in have]
        if missing:
            raise ValueError(f"{PHONE_STORE}: {table} has no {', '.join(missing)} column; nothing read")
    device, device_name = _phone_device(con, blocks)
    names = _installed(con)
    minutes = "b.ZDURATIONINMINUTES" if "ZDURATIONINMINUTES" in blocks else "NULL"
    domain = "i.ZDOMAIN" if "ZDOMAIN" in items else "NULL"
    apple_category = "c.ZIDENTIFIER" if "ZIDENTIFIER" in categories else "NULL"
    rows = con.execute(
        f"SELECT b.ZSTARTDATE, {minutes}, {apple_category}, i.ZBUNDLEIDENTIFIER, {domain},"
        f" i.ZTOTALTIMEINSECONDS FROM {ITEMS} AS i JOIN {CATEGORIES} AS c ON c.Z_PK = i.ZCATEGORY"
        f" JOIN {BLOCKS} AS b ON b.Z_PK = c.ZBLOCK ORDER BY b.ZSTARTDATE, i.ZBUNDLEIDENTIFIER, i.Z_PK"
    )
    for start_s, block_min, category, bundle_id, web_domain, seconds in rows:
        if not _text(bundle_id):
            _count(counts, "skipped_web_domain" if _text(web_domain) else "skipped_no_bundle")
            continue
        start = _datetime(start_s)
        if start is None:
            _count(counts, "skipped_no_start")
            continue
        if start.year < PLACEHOLDER_BEFORE_YEAR:
            _count(counts, "skipped_placeholder_date")
            continue
        total = int(seconds) if isinstance(seconds, int | float) and not isinstance(seconds, bool) else 0
        if total <= 0:
            _count(counts, "skipped_empty")
            continue
        bundle_id = _text(bundle_id)
        end = start + timedelta(seconds=total)
        extra: dict[str, Any] = {
            "bundle_id": bundle_id,
            **_named(bundle_id, names.get(bundle_id)),
            "device": device,
        }
        if device_name:
            extra["device_name"] = device_name
        extra["duration_s"] = total
        extra["observed"] = HOURLY
        if isinstance(block_min, int | float) and not isinstance(block_min, bool) and block_min > 0:
            extra["block_s"] = int(block_min) * 60
        if _text(category):
            extra["apple_category"] = _text(category)
        yield start, end, _payload(device, bundle_id, start, extra)


def _phone_device(con: sqlite3.Connection, blocks: set[str]) -> tuple[str, str | None]:
    """The phone's identifier and name from `ZUSAGE → ZCOREDEVICE`, the first device when the store
    has several; `iphone` and no name when the tables or their columns are not there."""
    tables = _tables(con)
    if USAGE not in tables or DEVICES not in tables or "ZUSAGE" not in blocks:
        return IOS_DEVICE, None
    usage, devices = _columns(con, USAGE), _columns(con, DEVICES)
    if "ZDEVICE" not in usage or "Z_PK" not in devices or "ZIDENTIFIER" not in devices:
        return IOS_DEVICE, None
    name = "d.ZNAME" if "ZNAME" in devices else "NULL"
    row = con.execute(
        f"SELECT d.ZIDENTIFIER, {name} FROM {USAGE} AS u JOIN {DEVICES} AS d ON d.Z_PK = u.ZDEVICE"
        " ORDER BY u.Z_PK LIMIT 1"
    ).fetchone()
    if row is None or not _text(row[0]):
        return IOS_DEVICE, None
    return _text(row[0]), _text(row[1]) or None


def _installed(con: sqlite3.Connection) -> dict[str, str]:
    """`bundle id → display name` from the phone's own app table, when the store has one."""
    if INSTALLED not in _tables(con):
        return {}
    columns = _columns(con, INSTALLED)
    if "ZBUNDLEIDENTIFIER" not in columns or "ZDISPLAYNAME" not in columns:
        return {}
    found: dict[str, str] = {}
    for bundle_id, name in con.execute(f"SELECT ZBUNDLEIDENTIFIER, ZDISPLAYNAME FROM {INSTALLED}"):
        if _text(bundle_id) and _text(name) and _text(bundle_id) not in found:
            found[_text(bundle_id)] = _text(name)
    return found


def _span(
    bundle_id: object, start_s: object, end_s: object, counts: dict[str, int]
) -> tuple[datetime, datetime] | None:
    if not _text(bundle_id):
        _count(counts, "skipped_no_bundle")
        return None
    start, end = _datetime(start_s), _datetime(end_s)
    if start is None:
        _count(counts, "skipped_no_start")
        return None
    if start.year < PLACEHOLDER_BEFORE_YEAR:
        _count(counts, "skipped_placeholder_date")
        return None
    if end is None or end <= start:
        _count(counts, "skipped_empty")
        return None
    return start, end


def _named(bundle_id: str, store_name: str | None) -> dict[str, str]:
    """`{"app": name}` when the store or the built-in table names the app, else nothing."""
    name = store_name or apps.built_in_name(bundle_id)
    return {"app": name} if name else {}


def _payload(device: str, bundle_id: str, start: datetime, extra: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "raw_id": f"{device}:{bundle_id}:{_stamp(start)}",
        "title": extra.get("app") or bundle_id,
        "calendar": dict(CALENDAR),
        "all_day": False,
        "extra": extra,
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
