"""iOS call history → call/v1 (RFC 0012).

Reads the CallHistory.storedata an iPhone keeps under Library/CallHistoryDB. Only an encrypted
backup carries it (`logbook import-backup` copies it out as `ios-calls/CallHistory.storedata` and
runs this adapter on the copy). It is a Core Data store: one SQLite table matters,

    ZCALLRECORD  (Z_PK, ZUNIQUE_ID, ZADDRESS, ZDATE — seconds since 2001-01-01 UTC — ZDURATION,
                  ZORIGINATED, ZANSWERED, ZCALLTYPE, ZSERVICE_PROVIDER, and whatever else the iOS
                  version added: ZREAD, ZNAME, ZLOCATION, ZISO_COUNTRY_CODE, ZDISCONNECTED_CAUSE, …)

One line per row: kind `call`, tier 1, source `ios-calls`, `at` the start in UTC, `end` the start
plus the duration when the call was answered and lasted, else null; `tz` is never the row's (a call
log has no zone), so the record's applies. `direction` is `outgoing` when ZORIGINATED is set, else
`incoming`; `answered` is ZANSWERED as the phone flagged it (RFC 0012 rule 3), `duration_s` the
duration rounded to whole seconds.

`counterparty` is ZADDRESS as a source-native ref (RFC 0006), never resolved: a number through the
shared `phone.normalise` with `LOGBOOK_DIAL_PREFIX` as `ios-contacts` uses it, so the address book,
the chats and the calls meet on one resolution (a national spelling that could not be completed is
kept as entered and flagged `extra.unnormalised`); an address with `@` is an email, lower-cased;
anything else a handle. A row with no address (a withheld number) has no counterparty and is
counted, not skipped: the phone rang. The store sometimes keeps the address as a blob of UTF-8;
it is decoded.

`service` is what the phone says, as one token: the provider `com.apple.Telephony` is `cellular`,
`com.apple.FaceTime` is `facetime` or `facetime-audio` by ZCALLTYPE (8 video, 16 audio), and a
third-party CallKit provider is named by the last part of its bundle id (`net.whatsapp.WhatsApp` →
`whatsapp`). Without a provider ZCALLTYPE alone decides (1 cellular, 8 facetime, 16 facetime-audio);
a type we cannot name gives no service and keeps the code under `extra.call_type`. The raw provider
string is always kept under `extra.service_provider`.

`raw_id` is ZUNIQUE_ID; a row without one is keyed by its Z_PK and counted. Every other column of
the table that is not mapped, not Core Data bookkeeping (Z_PK, Z_ENT, Z_OPT) and not null or a blob
is kept under `extra` with its name lower-cased and the Z prefix dropped (`ZNAME` → `name`: the
caller-id text the phone showed, never an identity). Rows whose date is a placeholder — before 1900 —
or absent are skipped and counted (RFC 0012 rule 4).

Every column beyond Z_PK and ZDATE is optional: PRAGMA says what the table has, and an iOS version
without a column yields lines without the field. Pure: opened `mode=ro`, `immutable=1`, one SELECT
streamed through the cursor, no network.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import phone
from .ios_contacts import DIAL_PREFIX_ENV

NAME = "ios-calls"
KIND = "call"
TIER = 1
SCHEMA = "call/v1"

SQLITE_HEADER = b"SQLite format 3\x00"
TABLE = "ZCALLRECORD"
APPLE_EPOCH_UTC = datetime(2001, 1, 1, tzinfo=UTC)
PLACEHOLDER_BEFORE_YEAR = 1900  # a 1601 row is the store's placeholder, not a call (RFC 0012 rule 4)

ROW_ID = "Z_PK"
DATE = "ZDATE"
MAPPED = ("ZUNIQUE_ID", "ZADDRESS", "ZDURATION", "ZORIGINATED", "ZANSWERED", "ZCALLTYPE", "ZSERVICE_PROVIDER")
BOOKKEEPING = frozenset({"Z_PK", "Z_ENT", "Z_OPT"})

TELEPHONY = "com.apple.telephony"
FACETIME = "com.apple.facetime"
CALL_TYPES = {1: "cellular", 8: "facetime", 16: "facetime-audio"}  # ZCALLTYPE as the phone spells it
FACETIME_TYPES = {8: "facetime", 16: "facetime-audio"}


def sniff(path: Path) -> bool:
    """A SQLite file with a ZCALLRECORD table. Never raises."""
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


def _open(path: Path) -> sqlite3.Connection:
    """Read-only and immutable: SQLite neither locks the file nor writes a journal beside it."""
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)


def _tables(con: sqlite3.Connection) -> set[str]:
    rows = con.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(name) for (name,) in rows}


def _columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")]


def run(
    path: Path, since: str | None = None, counts: dict[str, int] | None = None
) -> Iterator[dict[str, Any]]:
    """One call/v1 line per ZCALLRECORD row, in Z_PK order, streamed.

    `since` is RFC3339 UTC; rows with `at` before it are not yielded. `counts` tallies
    `skipped_no_date` and `skipped_placeholder_date` (RFC 0012 rule 4), and notes `no_unique_id`
    (keyed by row id) and `no_counterparty` (a withheld number)."""
    counts = counts if counts is not None else {}
    prefix = os.environ.get(DIAL_PREFIX_ENV, "").strip()
    con = _open(Path(path))
    try:
        columns = _columns(con, TABLE)
        present = set(columns)
        wanted = [c for c in (ROW_ID, DATE, *MAPPED) if c in present]
        extras = [c for c in columns if c not in BOOKKEEPING and c != DATE and c not in MAPPED]
        query = f"SELECT {', '.join(wanted + extras)} FROM {TABLE} ORDER BY {ROW_ID}"
        for row in con.execute(query):
            values = dict(zip(wanted + extras, row, strict=True))
            draft = _draft(values, extras, prefix, counts)
            if draft is not None and not (since and draft["at"] < since):
                yield draft
    finally:
        con.close()


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _draft(
    values: dict[str, Any], extras: list[str], prefix: str, counts: dict[str, int]
) -> dict[str, Any] | None:
    date = values.get(DATE)
    start = _datetime(date)
    if start is None:
        _count(counts, "skipped_placeholder_date" if _is_number(date) else "skipped_no_date")
        return None
    if start.year < PLACEHOLDER_BEFORE_YEAR:
        _count(counts, "skipped_placeholder_date")
        return None
    extra: dict[str, Any] = {}
    raw_id = _text(values.get("ZUNIQUE_ID"))
    if not raw_id:
        raw_id = str(values[ROW_ID])
        _count(counts, "no_unique_id")
    answered = _flag(values.get("ZANSWERED"))
    duration = _seconds(values.get("ZDURATION"))
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": raw_id,
        "direction": "outgoing" if _flag(values.get("ZORIGINATED")) else "incoming",
        "answered": answered,
        "duration_s": duration,
    }
    address = _text(values.get("ZADDRESS"))
    if address:
        payload["counterparty"] = _ref(address, prefix, extra)
    else:
        _count(counts, "no_counterparty")
    _service(payload, extra, values.get("ZSERVICE_PROVIDER"), values.get("ZCALLTYPE"))
    for column in extras:
        value = values.get(column)
        if value is None or isinstance(value, bytes | bytearray | memoryview):
            continue
        if isinstance(value, str) and not value.strip():
            continue
        extra[column.removeprefix("Z").lower()] = value
    if extra:
        payload["extra"] = extra
    end = start + timedelta(seconds=duration) if answered and duration > 0 else None
    return {
        "at": _stamp(start),
        "end": _stamp(end) if end is not None else None,
        "tz": None,  # a call log has no zone of its own; the record's applies
        "source": NAME,
        "kind": KIND,
        "tier": TIER,
        "payload": payload,
    }


def _ref(address: str, prefix: str, extra: dict[str, Any]) -> dict[str, str]:
    """`+4790000001` → phone; `90000005` → phone through the dial prefix, else kept and flagged;
    `ola@example.org` → email, lower-cased; `Telenor` → handle, as is. Never resolved."""
    if "@" in address:
        return {"kind": "email", "value": address.lower()}
    value, unnormalised = phone.normalise(address, prefix)
    digits = value[1:] if value.startswith("+") else value
    if value and digits.isdigit() and digits.isascii():
        if unnormalised:
            extra["unnormalised"] = True
        return {"kind": "phone", "value": value}
    return {"kind": "handle", "value": address}


def _service(payload: dict[str, Any], extra: dict[str, Any], provider: object, call_type: object) -> None:
    """One token for the service, from the provider's bundle id first, else the call type; the raw
    provider always under `extra.service_provider`, an unnamed type under `extra.call_type`."""
    name = _text(provider)
    kind = _number(call_type)
    if name:
        extra["service_provider"] = name
        lowered = name.lower()
        if lowered == TELEPHONY:
            payload["service"] = "cellular"
            return
        if lowered == FACETIME:
            payload["service"] = FACETIME_TYPES.get(int(kind), "facetime") if kind is not None else "facetime"
            return
        last = lowered.rsplit(".", 1)[-1].strip()
        if last:
            payload["service"] = last
            return
    if kind is not None and int(kind) in CALL_TYPES:
        payload["service"] = CALL_TYPES[int(kind)]
    elif kind is not None:
        extra["call_type"] = kind


def _text(value: object) -> str:
    if isinstance(value, bytes | bytearray | memoryview):
        try:
            return bytes(value).decode("utf-8").strip()
        except UnicodeDecodeError:
            return ""
    return value.strip() if isinstance(value, str) else ""


def _flag(value: object) -> bool:
    number = _number(value)
    return number is not None and number != 0


def _is_number(value: object) -> bool:
    return _number(value) is not None


def _number(value: object) -> int | float | None:
    """The value when it is a number (a bool is not one), else None."""
    return value if isinstance(value, int | float) and not isinstance(value, bool) else None


def _seconds(value: object) -> int:
    number = _number(value)
    if number is None:
        return 0
    try:
        return max(0, round(number))
    except (OverflowError, ValueError):
        return 0


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
