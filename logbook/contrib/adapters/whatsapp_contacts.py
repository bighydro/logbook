"""WhatsApp (iOS) contacts → resolution/v1 alias lines (RFC 0006 `alias_of`).

Reads the ContactsV2.sqlite WhatsApp keeps in its app group beside ChatStorage.sqlite (in an
unencrypted Finder/iTunes backup it is the file under the group.net.whatsapp.WhatsApp.shared domain
with that name). One table matters:

    ZWAADDRESSBOOKCONTACT  (Z_PK, ZFULLNAME, ZGIVENNAME, ZLASTNAME, ZPHONENUMBER, ZWHATSAPPID,
                            ZLID, ZLIDHASH, ZINTEROPJID, ZUSERNAME, ZLASTUPDATED, ZSOURCE)

A message from a linked device carries a `@lid` JID, not the sender's phone JID, and the `whatsapp`
adapter logs it as `{handle, <lid>@lid}` — a ref no address book carries, so a resolution of the
person's phone number never matches it. This store knows which phone number each lid belongs to.
One alias line per row that has a lid and a phone number that normalises: `ref` is the lid spelled
exactly as the `whatsapp` adapter spells a sender (`<digits>@lid`), `alias_of` is the phone ref
through the shared `phone` module, `label` the name WhatsApp shows. Nothing is minted here: the
phone's entity comes from the owner's contacts import (`ios-contacts`), before or after this one.
`raw_id` is `alias:handle:<ref value>`, so a later backup appends nothing already aliased.

Rows without a lid, or with a phone that will not normalise (no country code and no
`LOGBOOK_DIAL_PREFIX`), are skipped and counted; the first row with a lid wins over a later one.

Pure: opens the database read-only (`mode=ro`, `immutable=1`, so not even a journal is written next
to the source), makes no network calls. `at` is the import time.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import phone

NAME = "whatsapp-contacts"
KIND = "resolution"
TIER = 2
SCHEMA = "resolution/v1"
METHOD = "exact"

DIAL_PREFIX_ENV = "LOGBOOK_DIAL_PREFIX"
SQLITE_HEADER = b"SQLite format 3\x00"
TABLE = "ZWAADDRESSBOOKCONTACT"
LID_COLUMN = "ZLID"
LID_DOMAIN = "lid"
APPLE_EPOCH = 978_307_200  # 2001-01-01T00:00:00Z; ZLASTUPDATED counts from it


def sniff(path: Path) -> bool:
    """A SQLite file with a ZWAADDRESSBOOKCONTACT table that has a ZLID column. Never raises."""
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
        return TABLE in _tables(con) and LID_COLUMN in _columns(con, TABLE)
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
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})").fetchall()}


def run(
    path: Path, since: str | None = None, counts: dict[str, int] | None = None
) -> Iterator[dict[str, Any]]:
    """One resolution/v1 alias line per contact with a lid and a usable phone, in Z_PK order.

    `since` is accepted for the adapter contract and ignored: every line's `at` is now, and the
    log dedupes on `raw_id`. `counts` tallies `skipped_no_lid`, `skipped_no_phone` (empty, or a
    number that will not normalise) and `skipped_duplicate_lid` (a lid already emitted in this
    run; the first row to carry it wins)."""
    counts = counts if counts is not None else {}
    at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    prefix = os.environ.get(DIAL_PREFIX_ENV, "").strip()
    con = _open(Path(path))
    try:
        rows = con.execute(
            "SELECT Z_PK, ZFULLNAME, ZGIVENNAME, ZLASTNAME, ZPHONENUMBER, ZWHATSAPPID, ZLID,"
            f" ZLASTUPDATED, ZSOURCE FROM {TABLE} ORDER BY Z_PK"
        ).fetchall()
    finally:
        con.close()
    seen: set[str] = set()
    for pk, full_name, given, last, entered, whatsapp_id, lid, updated, source in rows:
        handle = _handle(lid)
        if handle is None:
            counts["skipped_no_lid"] = counts.get("skipped_no_lid", 0) + 1
            continue
        number = _phone(entered, prefix)
        if number is None:
            counts["skipped_no_phone"] = counts.get("skipped_no_phone", 0) + 1
            continue
        if handle in seen:
            counts["skipped_duplicate_lid"] = counts.get("skipped_duplicate_lid", 0) + 1
            continue
        seen.add(handle)
        extra: dict[str, Any] = {"record_id": pk, "entered": entered}
        if _text(whatsapp_id):
            extra["whatsapp_id"] = _text(whatsapp_id)
        if isinstance(source, int) and not isinstance(source, bool):
            extra["contact_source"] = source
        stamp = _rfc3339(updated)
        if stamp:
            extra["last_updated"] = stamp
        payload: dict[str, Any] = {
            "schema": SCHEMA,
            "ref": {"kind": "handle", "value": handle},
            "alias_of": {"kind": "phone", "value": number},
        }
        label = _label(full_name, given, last)
        if label:
            payload["label"] = label
        payload["method"] = METHOD
        payload["raw_id"] = f"alias:handle:{handle}"
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


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _handle(lid: object) -> str | None:
    """`236000000000001` or `236000000000001@lid` → `236000000000001@lid`, the `whatsapp` adapter's
    spelling of a lid sender; None when there is nothing usable."""
    text = _text(lid)
    user, _, domain = text.partition("@")
    if not user or any(c.isspace() for c in text) or (domain and domain != LID_DOMAIN):
        return None
    return f"{user}@{LID_DOMAIN}"


def _phone(entered: object, prefix: str) -> str | None:
    """The normalised E.164 ref value, or None when the number will not normalise."""
    if not isinstance(entered, str):
        return None
    value, unnormalised = phone.normalise(entered, prefix)
    return value if value and not unnormalised else None


def _label(full_name: object, given: object, last: object) -> str:
    """ZFULLNAME, else "Given Last" from the parts, else nothing."""
    return _text(full_name) or " ".join(part for part in (_text(given), _text(last)) if part)


def _rfc3339(seconds_since_2001: object) -> str | None:
    if not isinstance(seconds_since_2001, int | float) or isinstance(seconds_since_2001, bool):
        return None
    try:
        return datetime.fromtimestamp(APPLE_EPOCH + int(seconds_since_2001), UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except (OverflowError, OSError, ValueError):
        return None
