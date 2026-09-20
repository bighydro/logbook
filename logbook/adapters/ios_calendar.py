"""iOS Calendar → event/v1 (RFC 0009).

Reads the Calendar.sqlitedb an iPhone keeps under Library/Calendar (in an unencrypted Finder/iTunes
backup it is the file named 2041457d5fe04d39d0ab481178355df6781e6858). Five tables matter:

    CalendarItem  (ROWID, unique_identifier, summary, description, start_date, end_date — seconds
                   since 2001-01-01 UTC — start_tz, all_day, calendar_id, location_id, status,
                   last_modified, has_recurrences, orig_item_id, orig_date)
    Calendar      (ROWID, title, type)
    Participant   (ROWID, owner_id → CalendarItem, email, name, status, role, type, entity_type)
    Location      (ROWID, title, address, latitude, longitude)
    Recurrence    (ROWID, owner_id → CalendarItem, frequency, interval, count, end_date, by_day,
                   by_month_day)

One line per CalendarItem row: kind `event`, tier 1, source `ios-calendar`, `at` the start and `end`
the end in UTC, `tz` the row's own zone when it names one the zone database knows (else the record's,
with the text kept under `extra.start_tz`). An all-day event is a date: `at` is that day's local
midnight in its zone — the record's zone, passed by `logbook add` as `timezone`, when the row is
floating — and `end` the next one (RFC 0009). Occurrences are never expanded: a master row carries its
rule as RRULE text, a detached occurrence (orig_item_id set) carries `recurrence_of`, the master's bare
uid (ADR 0011: log what the source has).

`raw_id` is `<unique_identifier>@<last_modified>`, so an entry edited after an export is a new line
next time (RFC 0009 rule 5); a row with no unique identifier is keyed by its ROWID and counted. A
detached occurrence that shares its master's uid is keyed `<uid>/<original date>` so the two never
collide. Rows whose start is a placeholder — the year 1601, or anything before 2010-07 — are the store's,
not the owner's, and are skipped and counted (rule 4); so is a row with no start at all.

Every column beyond ROWID and start_date is optional: an iOS version without it yields lines without
the field. Pure: opened `mode=ro`, `immutable=1` (no lock, no journal beside the source), one SELECT
streamed through the cursor, participants and rules fetched per row, no network.
"""

from __future__ import annotations

import re
import sqlite3
import zoneinfo
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

NAME = "ios-calendar"
KIND = "event"
TIER = 1
SCHEMA = "event/v1"

SQLITE_HEADER = b"SQLite format 3\x00"
REQUIRED_TABLES = frozenset({"CalendarItem", "Calendar"})
APPLE_EPOCH = 978_307_200  # 2001-01-01T00:00:00Z; every date column counts from it
EARLIEST_START = 300_000_000  # 2010-07-07; a start before this is a placeholder (RFC 0009 rule 4)
PLACEHOLDER_BEFORE_YEAR = 1990  # the store's 1601 rows, and anything else that is not a plan

ITEM_COLUMNS = (
    "unique_identifier",
    "summary",
    "description",
    "start_date",
    "end_date",
    "start_tz",
    "all_day",
    "calendar_id",
    "location_id",
    "status",
    "last_modified",
    "has_recurrences",
    "orig_item_id",
    "orig_date",
)
PARTICIPANT_COLUMNS = ("email", "name", "status", "role", "type", "entity_type")
LOCATION_COLUMNS = ("title", "address", "latitude", "longitude")
RECURRENCE_COLUMNS = ("frequency", "interval", "count", "end_date", "by_day", "by_month_day")

# EKEventStatus: 0 none, 1 confirmed, 2 tentative, 3 canceled
EVENT_STATUS = {1: "confirmed", 2: "tentative", 3: "cancelled"}
EVENT_STATUS_NONE = 0
# EKParticipantStatus: 0 unknown, 1 pending, 2 accepted, 3 declined, 4 tentative, 5 delegated, ...
PARTICIPANT_STATUS = {0: "none", 1: "none", 2: "accepted", 3: "declined", 4: "tentative"}
ORGANIZER_ROLE = 3  # EKParticipantRole chair
ORGANIZER_ENTITY_TYPE = 2  # the store's own participant kind for the organizer
FREQUENCIES = {1: "DAILY", 2: "WEEKLY", 3: "MONTHLY", 4: "YEARLY"}
WEEKDAYS = ("SU", "MO", "TU", "WE", "TH", "FR", "SA")  # the store counts from Sunday = 1
BYDAY_TOKEN = re.compile(r"^([+-]?[1-5])?(SU|MO|TU|WE|TH|FR|SA)$", re.IGNORECASE)
NUMBER = re.compile(r"^[+-]?\d+$")


def sniff(path: Path) -> bool:
    """A SQLite file with both CalendarItem and Calendar tables. Never raises."""
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


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}


def _select(present: set[str], wanted: tuple[str, ...], alias: str) -> str:
    """The wanted columns, NULL for each the table lacks, so an absent column is an absent field."""
    return ", ".join(f"{alias}.{c}" if c in present else f"NULL AS {c}" for c in wanted)


class _Store:
    """The open database and its per-row lookups, built once per run."""

    def __init__(self, con: sqlite3.Connection) -> None:
        self.con = con
        tables = _tables(con)
        self.item_columns = _columns(con, "CalendarItem")
        self.calendar_columns = _columns(con, "Calendar")
        self.participant = _columns(con, "Participant") if "Participant" in tables else None
        self.location = _columns(con, "Location") if "Location" in tables else None
        self.recurrence = _columns(con, "Recurrence") if "Recurrence" in tables else None

    def items(self) -> Iterator[tuple[Any, ...]]:
        joined = "calendar_id" in self.item_columns
        name = "c.title" if joined and "title" in self.calendar_columns else "NULL"
        query = (
            f"SELECT i.ROWID, {_select(self.item_columns, ITEM_COLUMNS, 'i')}, {name} AS calendar_name"
            " FROM CalendarItem AS i"
        )
        if joined:
            query += " LEFT JOIN Calendar AS c ON c.ROWID = i.calendar_id"
        return iter(self.con.execute(query + " ORDER BY i.ROWID"))

    def master_uid(self, rowid: object) -> str | None:
        """The bare id of the row a detached occurrence points at: its uid, else its ROWID as text."""
        if not isinstance(rowid, int):
            return None
        uid = "unique_identifier" if "unique_identifier" in self.item_columns else "NULL"
        row = self.con.execute(f"SELECT {uid} FROM CalendarItem WHERE ROWID = ?", (rowid,)).fetchone()
        if row is None:
            return str(rowid)
        return _text(row[0]) or str(rowid)

    def participants(self, rowid: int) -> list[tuple[Any, ...]]:
        if self.participant is None or "owner_id" not in self.participant:
            return []
        query = f"SELECT {_select(self.participant, PARTICIPANT_COLUMNS, 'p')} FROM Participant AS p"
        return self.con.execute(query + " WHERE p.owner_id = ? ORDER BY p.ROWID", (rowid,)).fetchall()

    def location_row(self, location_id: object) -> tuple[Any, ...] | None:
        if self.location is None or not isinstance(location_id, int):
            return None
        query = f"SELECT {_select(self.location, LOCATION_COLUMNS, 'l')} FROM Location AS l WHERE l.ROWID = ?"
        return _one(self.con.execute(query, (location_id,)))

    def rule(self, rowid: int) -> tuple[Any, ...] | None:
        if self.recurrence is None or "owner_id" not in self.recurrence:
            return None
        query = f"SELECT {_select(self.recurrence, RECURRENCE_COLUMNS, 'r')} FROM Recurrence AS r"
        return _one(self.con.execute(query + " WHERE r.owner_id = ? ORDER BY r.ROWID LIMIT 1", (rowid,)))


def _one(cursor: sqlite3.Cursor) -> tuple[Any, ...] | None:
    row = cursor.fetchone()
    return tuple(row) if row is not None else None


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
) -> Iterator[dict[str, Any]]:
    """One event/v1 line per CalendarItem row, in ROWID order, streamed.

    `since` is RFC3339 UTC; rows with `at` before it are not yielded. `timezone` is the record's
    IANA zone (`logbook add` passes it): a floating all-day event is placed at local midnight in it;
    without it the stored UTC midnight stands. `counts` tallies `skipped_no_start` and
    `skipped_placeholder_date` (RFC 0009 rule 4), and notes `no_unique_identifier` (keyed by row id)."""
    counts = counts if counts is not None else {}
    record_zone = _zone(timezone)
    con = _open(Path(path))
    try:
        store = _Store(con)
        for row in store.items():  # the cursor streams; the per-row lookups run on the same connection
            draft = _draft(row, store, record_zone, counts)
            if draft is not None and not (since and draft["at"] < since):
                yield draft
    finally:
        con.close()


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _draft(
    row: tuple[Any, ...], store: _Store, record_zone: zoneinfo.ZoneInfo | None, counts: dict[str, int]
) -> dict[str, Any] | None:
    (
        rowid,
        uid,
        summary,
        description,
        start_date,
        end_date,
        start_tz,
        all_day,
        calendar_id,
        location_id,
        status,
        last_modified,
        _has_recurrences,
        orig_item_id,
        orig_date,
        calendar_name,
    ) = row
    start = _datetime(start_date)
    if start is None:
        _count(counts, "skipped_no_start" if not _is_number(start_date) else "skipped_placeholder_date")
        return None
    if (_is_number(start_date) and start_date < EARLIEST_START) or start.year < PLACEHOLDER_BEFORE_YEAR:
        _count(counts, "skipped_placeholder_date")
        return None
    end = _datetime(end_date)
    extra: dict[str, Any] = {}
    zone = _zone(start_tz)
    if zone is None and _text(start_tz):
        extra["start_tz"] = _text(start_tz)
    is_all_day = bool(all_day)
    if is_all_day:
        start, end = _all_day_span(start, zone or record_zone, zone is not None)
    bare = _text(uid)
    if not bare:
        bare = str(rowid)
        _count(counts, "no_unique_identifier")
    modified = _rfc3339(last_modified)
    payload: dict[str, Any] = {"schema": SCHEMA, "raw_id": bare}
    if modified:
        payload["modified_at"] = modified
    if _text(summary):
        payload["title"] = _text(summary)
    if calendar_id is not None:
        calendar: dict[str, Any] = {"id": str(calendar_id)}
        if _text(calendar_name):
            calendar["name"] = _text(calendar_name)
        payload["calendar"] = calendar
    payload["all_day"] = is_all_day
    _place(payload, extra, store.location_row(location_id))
    _people(payload, store.participants(rowid))
    if status is not None and status != EVENT_STATUS_NONE:
        if status in EVENT_STATUS:
            payload["status"] = EVENT_STATUS[status]
        elif _is_number(status):
            extra["status_code"] = status
    if orig_item_id is not None:
        master = store.master_uid(orig_item_id)
        if master is not None:
            payload["recurrence_of"] = master
            original = _rfc3339(orig_date)
            if original:
                extra["original_date"] = original
            if master == bare:  # the store gives a detached occurrence its master's uid
                bare = f"{bare}/{original or f'row{rowid}'}"
    else:
        _rule(payload, extra, store.rule(rowid))
    if _text(description):
        payload["notes"] = _text(description)
    if extra:
        payload["extra"] = extra
    payload["raw_id"] = f"{bare}@{modified}" if modified else bare
    return {
        "at": _stamp(start),
        "end": _stamp(end) if end is not None else None,
        "tz": zone.key if zone is not None else None,  # None: the logbook's own
        "source": NAME,
        "kind": KIND,
        "tier": TIER,
        "payload": payload,
    }


def _all_day_span(
    start: datetime, zone: zoneinfo.ZoneInfo | None, own_zone: bool
) -> tuple[datetime, datetime]:
    """Local midnight of the event's day and the next one, in UTC. The day is the stored instant's date in
    the row's own zone; a floating row (no zone of its own) keeps the day at UTC midnight, so its date is
    the UTC date, then placed at midnight in the record's zone when that is known."""
    day = start.astimezone(zone).date() if own_zone and zone is not None else start.date()
    if zone is None:
        first = datetime(day.year, day.month, day.day, tzinfo=UTC)
        return first, first + timedelta(days=1)
    first = datetime(day.year, day.month, day.day, tzinfo=zone)
    return first.astimezone(UTC), (first + timedelta(days=1)).astimezone(UTC)


def _place(payload: dict[str, Any], extra: dict[str, Any], row: tuple[Any, ...] | None) -> None:
    """`location` is the title, else the address; coordinates (and the address, when the title won) under
    `extra.location`. Resolving the place is a resolution/v1 line, never done here."""
    if row is None:
        return
    title, address, latitude, longitude = (_text(row[0]), _text(row[1]), row[2], row[3])
    detail: dict[str, Any] = {}
    if title:
        payload["location"] = title
        if address:
            detail["address"] = address
    elif address:
        payload["location"] = address
    if _is_number(latitude) and _is_number(longitude) and -90 <= latitude <= 90 and -180 <= longitude <= 180:
        detail["latitude"] = latitude
        detail["longitude"] = longitude
    if detail:
        extra["location"] = detail


def _people(payload: dict[str, Any], rows: list[tuple[Any, ...]]) -> None:
    """Attendees as source-native email refs (RFC 0006), never resolved; the first row marked as the
    organizer — chair role, or the store's organizer entity type — becomes `organizer`."""
    attendees: list[dict[str, Any]] = []
    for email, name, status, role, _type, entity_type in rows:
        value = _text(email).lower()
        if not value:
            continue
        ref = {"kind": "email", "value": value}
        if "organizer" not in payload and (role == ORGANIZER_ROLE or entity_type == ORGANIZER_ENTITY_TYPE):
            payload["organizer"] = ref
            continue
        attendee: dict[str, Any] = {"ref": ref}
        if _text(name):
            attendee["name"] = _text(name)
        if status is not None:
            attendee["response"] = PARTICIPANT_STATUS.get(status, "none") if _is_number(status) else "none"
            if status not in PARTICIPANT_STATUS and _is_number(status):
                attendee["extra"] = {"status_code": status}
        attendees.append(attendee)
    if attendees:
        payload["attendees"] = attendees


def _rule(payload: dict[str, Any], extra: dict[str, Any], row: tuple[Any, ...] | None) -> None:
    """RRULE text from the Recurrence row: FREQ, INTERVAL, COUNT or UNTIL, BYDAY, BYMONTHDAY. A frequency
    we cannot name gives no rule; whatever could not be rendered is kept raw under `extra.recurrence`."""
    if row is None:
        return
    frequency, interval, count, end_date, by_day, by_month_day = row
    raw = dict(zip(RECURRENCE_COLUMNS, row, strict=True))
    freq = FREQUENCIES.get(frequency) if _is_number(frequency) else None
    if freq is None:
        kept = {k: v for k, v in raw.items() if v is not None}
        if kept:
            extra["recurrence"] = kept
        return
    parts = [f"FREQ={freq}"]
    unrendered: dict[str, Any] = {}
    if _is_number(interval) and interval >= 2:
        parts.append(f"INTERVAL={int(interval)}")
    if _is_number(count) and count >= 1:
        parts.append(f"COUNT={int(count)}")
    else:
        until = _datetime(end_date)
        if until is not None:
            parts.append(f"UNTIL={until:%Y%m%dT%H%M%SZ}")
    for key, value, render in (("by_day", by_day, _by_day), ("by_month_day", by_month_day, _by_month_day)):
        if not _text(value):
            continue
        rendered = render(_text(value))
        if rendered is None:
            unrendered[key] = value
        else:
            parts.append(rendered)
    payload["recurrence"] = ";".join(parts)
    if unrendered:
        extra["recurrence"] = unrendered


def _by_day(text: str) -> str | None:
    """`3,5` (the store's Sunday = 1) or `MO,WE` → `BYDAY=TU,TH`; anything else is unrendered."""
    days: list[str] = []
    for token in text.split(","):
        token = token.strip()
        if NUMBER.match(token) and 1 <= int(token) <= 7:
            days.append(WEEKDAYS[int(token) - 1])
        elif m := BYDAY_TOKEN.match(token):
            days.append((m.group(1) or "") + m.group(2).upper())
        else:
            return None
    return "BYDAY=" + ",".join(days) if days else None


def _by_month_day(text: str) -> str | None:
    days: list[str] = []
    for token in text.split(","):
        token = token.strip()
        if not NUMBER.match(token) or not 1 <= abs(int(token)) <= 31:
            return None
        days.append(str(int(token)))
    return "BYMONTHDAY=" + ",".join(days) if days else None


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _zone(name: object) -> zoneinfo.ZoneInfo | None:
    """The zone the database knows by that name, else None (a floating `_float`, garbage, or absent)."""
    text = _text(name)
    if not text:
        return None
    try:
        return zoneinfo.ZoneInfo(text)
    except (KeyError, ValueError, OSError):  # ZoneInfoNotFoundError is a KeyError
        return None


def _datetime(seconds_since_2001: object) -> datetime | None:
    if not isinstance(seconds_since_2001, int | float) or isinstance(seconds_since_2001, bool):
        return None
    try:
        return datetime.fromtimestamp(APPLE_EPOCH + int(seconds_since_2001), UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _stamp(when: datetime) -> str:
    return when.astimezone(UTC).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


def _rfc3339(seconds_since_2001: object) -> str | None:
    when = _datetime(seconds_since_2001)
    return _stamp(when) if when is not None else None
