"""iOS Contacts → resolution/v1 (RFC 0006).

Reads the AddressBook.sqlitedb an iPhone keeps under Library/AddressBook (in an unencrypted
Finder/iTunes backup it is the file named 31bb7ba8914766d4ba40d6dfb6113c8b614be442). Two tables
matter: ABPerson (ROWID, First, Last, Organization, Nickname, CreationDate, ModificationDate) and
ABMultiValue (record_id, property, label, value) with property 3 = phone, 4 = email.

This is how a record gets its people (ADR 0013.2): the contact list is imported once, each
ABPerson row mints one Logbook UUIDv7 — a `person`, or a `company` when only Organization is set —
and every phone number and email address becomes one resolution line pointing at it. `raw_id` is the
normalised ref, not the row id, so a later backup of the same phone appends nothing for refs already
resolved and the entity ids already minted stand.

Pure: opens the database read-only (`mode=ro`, `immutable=1`, so not even a journal is written next
to the source), makes no network calls. `at` is the import time: a resolution is made when it is
read, not when the contact was created; the source's dates live under `extra`.
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..store import uuid7

NAME = "ios-contacts"
KIND = "resolution"
TIER = 2
SCHEMA = "resolution/v1"
METHOD = "owner"

DIAL_PREFIX_ENV = "LOGBOOK_DIAL_PREFIX"
SQLITE_HEADER = b"SQLite format 3\x00"
REQUIRED_TABLES = frozenset({"ABPerson", "ABMultiValue"})
LABEL_TABLE = "ABMultiValueLabel"
APPLE_EPOCH = 978_307_200  # 2001-01-01T00:00:00Z; CreationDate/ModificationDate count from it
PROPERTIES = {3: "phone", 4: "email"}

PHONE_PUNCTUATION = re.compile(r"[\s\-.()]+")
APPLE_LABEL = re.compile(r"^_\$!<(.+)>!\$_$")


def sniff(path: Path) -> bool:
    """A SQLite file with both ABPerson and ABMultiValue tables. Never raises."""
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


def run(
    path: Path, since: str | None = None, counts: dict[str, int] | None = None
) -> Iterator[dict[str, Any]]:
    """One resolution/v1 line per phone and per email, persons in ROWID order.

    `since` is accepted for the adapter contract and ignored: every line's `at` is now, and the
    log dedupes on `raw_id`. `counts` tallies `skipped_no_ref` (a person with neither phone nor
    email), `skipped_empty_ref` (a value with nothing in it) and `skipped_duplicate_ref` (a ref
    already emitted in this run; the first person to carry it wins)."""
    counts = counts if counts is not None else {}
    at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    prefix = os.environ.get(DIAL_PREFIX_ENV, "").strip()
    con = _open(Path(path))
    try:
        labels = _labels(con)
        values = _values(con)
        persons = con.execute(
            "SELECT ROWID, First, Last, Organization, Nickname, CreationDate, ModificationDate"
            " FROM ABPerson ORDER BY ROWID"
        ).fetchall()
    finally:
        con.close()
    seen: set[str] = set()
    for rowid, first, last, organization, nickname, created, modified in persons:
        rows = values.get(rowid, [])
        entity_type, label = _identity(first, last, organization, nickname)
        entity_id: str | None = None
        emitted = 0
        for uid, prop, raw_label, entered in rows:
            kind = PROPERTIES[prop]
            value, unnormalised = _normalise(kind, entered, prefix)
            if not value:
                counts["skipped_empty_ref"] = counts.get("skipped_empty_ref", 0) + 1
                continue
            raw_id = f"{kind}:{value}"
            if raw_id in seen:
                counts["skipped_duplicate_ref"] = counts.get("skipped_duplicate_ref", 0) + 1
                continue
            seen.add(raw_id)
            if entity_id is None:
                entity_id = uuid7()  # minted once per person, on the first ref that needs it
            emitted += 1
            extra: dict[str, Any] = {"record_id": rowid, "value_id": uid, "entered": entered}
            if entity_type == "person" and organization:
                extra["organization"] = organization
            if nickname and label != nickname:
                extra["nickname"] = nickname
            clean_label = _label(labels, raw_label)
            if clean_label:
                extra["label"] = clean_label
            for key, when in (("created", created), ("modified", modified)):
                stamp = _rfc3339(when)
                if stamp:
                    extra[key] = stamp
            if unnormalised:
                extra["unnormalised"] = True
            payload: dict[str, Any] = {
                "schema": SCHEMA,
                "ref": {"kind": kind, "value": value},
                "entity": {"type": entity_type, "id": entity_id, "registry": "logbook"},
            }
            if label:
                payload["label"] = label
            payload["method"] = METHOD
            payload["raw_id"] = raw_id
            payload["extra"] = extra
            yield {
                "at": at,
                "end": None,
                "tz": None,  # the logbook's own
                "source": NAME,
                "kind": KIND,
                "tier": TIER,
                "payload": payload,
            }
        if not emitted:  # nothing usable, or every ref already taken by an earlier row
            counts["skipped_no_ref"] = counts.get("skipped_no_ref", 0) + 1


def _labels(con: sqlite3.Connection) -> dict[int, str]:
    """iOS keeps labels in ABMultiValueLabel and stores their ROWID on the value; absent → {}."""
    if LABEL_TABLE not in _tables(con):
        return {}
    rows = con.execute(f"SELECT ROWID, value FROM {LABEL_TABLE}").fetchall()
    return {int(rowid): str(value) for rowid, value in rows if isinstance(value, str)}


def _values(con: sqlite3.Connection) -> dict[int, list[tuple[int, int, object, str]]]:
    """Phone and email rows per ABPerson ROWID, in property then UID order."""
    props = ", ".join(str(p) for p in PROPERTIES)
    rows = con.execute(
        "SELECT UID, record_id, property, label, value FROM ABMultiValue"
        f" WHERE property IN ({props}) ORDER BY record_id, property, UID"
    ).fetchall()
    out: dict[int, list[tuple[int, int, object, str]]] = {}
    for uid, record_id, prop, raw_label, value in rows:
        if not isinstance(record_id, int) or not isinstance(value, str):
            continue
        out.setdefault(record_id, []).append((int(uid), int(prop), raw_label, value))
    return out


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _identity(first: object, last: object, organization: object, nickname: object) -> tuple[str, str]:
    """(entity type, display name): "First Last", else Organization (a company), else Nickname."""
    name = " ".join(part for part in (_text(first), _text(last)) if part)
    if name:
        return "person", name
    if _text(organization):
        return "company", _text(organization)
    return "person", _text(nickname)


def _normalise(kind: str, entered: str, prefix: str) -> tuple[str, bool]:
    """(ref value, unnormalised). Empty when nothing usable is left.

    Phones lose spaces, dashes, dots and parentheses; a `00` prefix becomes `+`. A number with no
    country code gets `+<LOGBOOK_DIAL_PREFIX>` when that is set, after exactly one leading `0` (the
    national trunk prefix) is dropped: `079 654 31 17` with prefix 41 is `+41796543117`. A number
    that already starts with the prefix digits but no `+` is ambiguous (a trunk-less national number
    or a country code typed without `+`), so it is kept as entered and flagged. With no prefix set
    the number is kept as entered (punctuation stripped) and flagged. Anything that is not digits
    after that is flagged too. Emails are lower-cased and trimmed."""
    if kind == "email":
        return entered.strip().lower(), False
    number = PHONE_PUNCTUATION.sub("", entered)
    if number.startswith("00"):
        number = "+" + number[2:]
    digits = number[1:] if number.startswith("+") else number
    if not digits.isdigit() or not digits.isascii():
        return number, bool(number)
    if number.startswith("+"):
        return number, False
    if prefix and not number.startswith(prefix):
        national = number.removeprefix("0")
        if national:
            return f"+{prefix}{national}", False
    return number, True


def _label(labels: dict[int, str], raw: object) -> str:
    """`_$!<Mobile>!$_` → `mobile`; a custom label as typed; a label id through the label table."""
    text = labels.get(raw, "") if isinstance(raw, int) else _text(raw)
    m = APPLE_LABEL.match(text)
    return m.group(1).lower() if m else text


def _rfc3339(seconds_since_2001: object) -> str | None:
    if not isinstance(seconds_since_2001, int | float) or isinstance(seconds_since_2001, bool):
        return None
    try:
        return datetime.fromtimestamp(APPLE_EPOCH + int(seconds_since_2001), UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except (OverflowError, OSError, ValueError):
        return None
