"""Copilot Money (iOS) → transaction/v1 (RFC 0021).

Reads the CopilotDB.sqlite an iPhone keeps in the Copilot app group (in a Finder/iTunes backup it
is `database/CopilotDB.sqlite` under the group.com.copilot.production domain). It is a GRDB store
with one table that matters:

    Transactions  (transaction_id, account_id, iso_currency_code, name — the cleaned merchant,
                   original_name as the bank spelled it, name_override — the owner's own name for
                   it, amount, pending, recurring, recurring_id, user_deleted, plaid_deleted,
                   category_id — Copilot's own category slug, plaid_category_strings — a JSON
                   array, date — "YYYY-MM-DD HH:MM:SS.SSS" in UTC, type — regular, income or
                   internal_transfer, user_note, parent_transaction_id — the transaction this is a
                   split of, tag_ids — a JSON array)

One transaction/v1 line per row: kind `transaction`, tier 3 (RFC 0021: money, always), source and
`provider` `copilot`. `raw_id` is `transaction_id`. `amount` is the row's amount negated: Copilot
keeps Plaid's convention, debits positive and income negative, and the profile is signed from the
owner's side. `merchant` is `name_override` when the owner set one, else `name`; `category` is
`category_id` when it is not empty; `account` is the account id (the store keeps no account
names); `status` is `pending` or `posted`; `note` is `user_note`. The row's `type`, the recurring
flag and id, the original and cleaned names when they differ from `merchant`, the Plaid category
strings and tags when there are any, the parent of a split, and a deleted flag go under `extra`.

`at` is the stored instant as UTC, verbatim (RFC 0021 rule 5): Copilot stores local midnight of
the transaction's day as a UTC instant, so `date` is the day of `at` in the record's zone
(`timezone`, passed by `logbook add`), the UTC day without one. A row with no date is skipped and
counted; a row the owner or the bank deleted is a line with `extra.deleted`, counted. Pure: opened
`mode=ro`, `immutable=1`, one SELECT streamed through the cursor, no network.
"""

from __future__ import annotations

import json
import sqlite3
import zoneinfo
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

NAME = "copilot"
KIND = "transaction"
TIER = 3
SCHEMA = "transaction/v1"

SQLITE_HEADER = b"SQLite format 3\x00"
TABLE = "Transactions"
REQUIRED_COLUMNS = frozenset({"transaction_id", "amount", "iso_currency_code", "date", "name"})
DATE_FORMATS = ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d")

QUERY = """
SELECT transaction_id, account_id, iso_currency_code, original_name, name, name_override, amount,
       pending, recurring, recurring_id, user_deleted, plaid_deleted, category_id,
       plaid_category_strings, date, type, user_note, parent_transaction_id, tag_ids
FROM Transactions
ORDER BY date, transaction_id
"""


def sniff(path: Path) -> bool:
    """A SQLite file with Copilot's Transactions table (its columns, not just the name). Never raises."""
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
        columns = {str(row[1]) for row in con.execute(f"PRAGMA table_info({TABLE})")}
        return columns >= REQUIRED_COLUMNS
    except sqlite3.Error:
        return False
    finally:
        con.close()


def _open(path: Path) -> sqlite3.Connection:
    """Read-only and immutable: SQLite neither locks the file nor writes a journal beside it."""
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
) -> Iterator[dict[str, Any]]:
    """One transaction/v1 line per row, in date order, streamed.

    `since` is RFC3339 UTC; rows with `at` before it are not yielded. `timezone` is the record's
    zone, for `date`. `counts` tallies what was left out — `skipped_no_date` — and what was
    noted: `pending`, `deleted`."""
    counts = counts if counts is not None else {}
    zone = _zone(timezone)
    con = _open(Path(path))
    try:
        for row in con.execute(QUERY):  # the cursor streams; nothing is accumulated
            draft = _draft(row, zone, counts)
            if draft is not None and not (since and draft["at"] < since):
                yield draft
    finally:
        con.close()


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _draft(
    row: tuple[Any, ...], zone: zoneinfo.ZoneInfo | None, counts: dict[str, int]
) -> dict[str, Any] | None:
    (
        transaction_id,
        account_id,
        currency,
        original_name,
        name,
        name_override,
        amount,
        pending,
        recurring,
        recurring_id,
        user_deleted,
        plaid_deleted,
        category_id,
        plaid_categories,
        date,
        kind,
        note,
        parent,
        tags,
    ) = row
    when = _datetime(date)
    if when is None:
        _count(counts, "skipped_no_date")
        return None
    if not isinstance(amount, int | float) or isinstance(amount, bool):
        _count(counts, "skipped_no_amount")
        return None
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": str(transaction_id),
        "amount": -amount,  # Plaid keeps debits positive; the profile is signed from the owner's side
        "currency": str(currency).upper() if _text(currency) else "XXX",
    }
    merchant = _text(name_override) or _text(name)
    if merchant is not None:
        payload["merchant"] = merchant
    category = _text(category_id)
    if category is not None:
        payload["category"] = category
    payload["date"] = (when.astimezone(zone) if zone is not None else when).strftime("%Y-%m-%d")
    account = _text(account_id)
    if account is not None:
        payload["account"] = account
    payload["provider"] = NAME
    payload["status"] = "pending" if pending else "posted"
    if pending:
        _count(counts, "pending")
    note = _text(note)
    if note is not None:
        payload["note"] = note
    extra: dict[str, Any] = {"type": _text(kind) or "unknown", "recurring": bool(recurring)}
    if _text(recurring_id) is not None:
        extra["recurring_id"] = recurring_id
    if _text(name) is not None and name != merchant:
        extra["name"] = name
    if _text(original_name) is not None and original_name != merchant:
        extra["original_name"] = original_name
    plaid = _strings(plaid_categories)
    if plaid:
        extra["plaid_categories"] = plaid
    tag_list = _strings(tags)
    if tag_list:
        extra["tags"] = tag_list
    if _text(parent) is not None:
        extra["parent"] = parent
    if user_deleted or plaid_deleted:
        extra["deleted"] = True
        _count(counts, "deleted")
    payload["extra"] = extra
    return {
        "at": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": None,
        "tz": None,  # the logbook's own
        "source": NAME,
        "kind": KIND,
        "tier": TIER,
        "payload": payload,
    }


def _text(value: object) -> str | None:
    """A non-blank string, stripped; anything else is None."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def _strings(value: object) -> list[str]:
    """The strings of a JSON array stored as a blob or text; [] for anything else."""
    if isinstance(value, bytes | memoryview):
        value = bytes(value).decode("utf-8", errors="replace")
    if not isinstance(value, str):
        return []
    try:
        data = json.loads(value)
    except ValueError:
        return []
    return [item for item in data if isinstance(item, str)] if isinstance(data, list) else []


def _datetime(value: object) -> datetime | None:
    """The stored date-time read as UTC; None when it will not parse."""
    text = _text(value)
    if text is None:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _zone(name: object) -> zoneinfo.ZoneInfo | None:
    text = _text(name)
    if text is None:
        return None
    try:
        return zoneinfo.ZoneInfo(text)
    except (KeyError, ValueError, OSError):  # ZoneInfoNotFoundError is a KeyError
        return None
