"""Splitwise (iOS) → transaction/v1 (RFC 0021): the owner's share of every expense.

Reads the database.sqlite an iPhone keeps for Splitwise (in a Finder/iTunes backup it is
`Library/Application Support/database.sqlite` under the AppDomain-com.Splitwise.SplitwiseMobile
domain). Five tables matter:

    SWExpense        (id, expenseId — the server's id, groupId, description, isPayment, cost,
                      currencyCode, date — Unix seconds, category — the name as shown, categoryId,
                      creationMethod, deletedAtDate, notes, createdById — a server person id)
    SWExpenseMember  (sWExpenseId → SWExpense.id, sWPersonId → SWPerson.id, paidShare, owedShare)
    SWPerson         (id, personId — the server's id, firstName, lastName, email, phone)
    SWGroup          (groupId, groupName)
    SWCategory       (categoryId, categoryName, parentCategoryId)

One transaction/v1 line per expense: kind `transaction`, tier 3 (RFC 0021: money, always), source
and `provider` `splitwise`, `at` the expense's date in UTC, `raw_id` the server's `expenseId`.
`amount` is the owner's side (RFC 0021 rule 2): for an expense the owner's owed share, negative;
for a payment between members what the owner paid, negative, or received, positive. `merchant` is
the description, `category` the category name as the app shows it, `account` the group's name when
the expense is in a group, `note` the notes. The total cost, the owner's paid and owed shares,
every member's shares with a source-native ref (`{email}` when the app has one, else `{phone}`,
else `{provider_id}` — never resolved here, RFC 0006) and the name the app shows, who created it,
the creation method and a deleted flag go under `extra`.

Who the owner is: the person whose email is one of `owner_emails` (`logbook.json`, passed by
`logbook add`); without a match, the person on the most expenses — the store does not say which
person is the phone's — and that guess is counted (`owner_guessed`). An expense the owner is not a
member of is skipped and counted; one without a date too. An expense the app marks deleted is a
line with `extra.deleted`, counted. Pure: opened `mode=ro`, `immutable=1`, the people, groups and
categories read once (a few dozen rows), the expenses streamed, no network.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import phone

NAME = "splitwise"
KIND = "transaction"
TIER = 3
SCHEMA = "transaction/v1"

SQLITE_HEADER = b"SQLite format 3\x00"
REQUIRED_TABLES = frozenset({"SWExpense", "SWExpenseMember", "SWPerson"})
EARLIEST_DATE = 1_293_840_000  # 2011-01-01: Splitwise did not exist before; earlier is garbage

QUERY = """
SELECT e.id, e.expenseId, e.currencyCode, e.description, e.isPayment, e.cost, e.date, e.category,
       e.categoryId, e.creationMethod, e.deletedAtDate, e.notes, e.createdById, g.groupName
FROM SWExpense AS e
LEFT JOIN SWGroup AS g ON g.groupId = e.groupId
ORDER BY e.date, e.expenseId
"""
MEMBERS = "SELECT sWPersonId, owedShare, paidShare FROM SWExpenseMember WHERE sWExpenseId = ? ORDER BY id"


@dataclass(frozen=True)
class Person:
    pk: int
    person_id: int | None
    name: str | None
    email: str | None
    phone: str | None

    @property
    def ref(self) -> dict[str, str]:
        """Source-native (RFC 0006): the email, else the phone, else the server's id."""
        if self.email is not None:
            return {"kind": "email", "value": self.email}
        if self.phone is not None:
            value, unnormalised = phone.normalise(self.phone, "")
            if value and not unnormalised:
                return {"kind": "phone", "value": value}
        return {
            "kind": "provider_id",
            "value": str(self.person_id if self.person_id is not None else self.pk),
        }


def sniff(path: Path) -> bool:
    """A SQLite file with SWExpense, SWExpenseMember and SWPerson tables. Never raises."""
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
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    owner_emails: Iterable[str] | None = None,
) -> Iterator[dict[str, Any]]:
    """One transaction/v1 line per expense the owner is part of, in date order, streamed.

    `since` is RFC3339 UTC; expenses dated before it are not yielded. `owner_emails` names the
    owner (any case). `counts` tallies what was left out — `skipped_no_date`, `skipped_not_involved`
    (the owner is not a member), `skipped_no_owner` (nobody to be the owner) — and what was noted:
    `deleted`, `owner_guessed` (no email matched; the person on most expenses was taken)."""
    counts = counts if counts is not None else {}
    con = _open(Path(path))
    try:
        people = _people(con)
        owner = _owner(con, people, owner_emails or (), counts)
        if owner is None:
            for _ in con.execute("SELECT 1 FROM SWExpense"):
                _count(counts, "skipped_no_owner")
            return
        categories = {
            cid: str(name)
            for cid, name in con.execute("SELECT categoryId, categoryName FROM SWCategory")
            if isinstance(name, str)
        }
        for row in con.execute(QUERY):  # the cursor streams; members are one small query each
            members = con.execute(MEMBERS, (row[0],)).fetchall()
            draft = _draft(row, members, people, owner, categories, counts)
            if draft is not None and not (since and draft["at"] < since):
                yield draft
    finally:
        con.close()


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _people(con: sqlite3.Connection) -> dict[int, Person]:
    people: dict[int, Person] = {}
    for pk, first, last, email, number, person_id in con.execute(
        "SELECT id, firstName, lastName, email, phone, personId FROM SWPerson"
    ):
        name = " ".join(part for part in (_text(first), _text(last)) if part is not None) or None
        address = _text(email)
        people[pk] = Person(
            pk,
            person_id if isinstance(person_id, int) else None,
            name,
            address.lower() if address is not None else None,
            _text(number),
        )
    return people


def _owner(
    con: sqlite3.Connection, people: dict[int, Person], owner_emails: Iterable[str], counts: dict[str, int]
) -> Person | None:
    """The person whose email is the owner's; else the person on the most expenses, counted."""
    wanted = {e.strip().lower() for e in owner_emails if isinstance(e, str) and e.strip()}
    for person in people.values():
        if person.email is not None and person.email in wanted:
            return person
    rows = con.execute(
        "SELECT sWPersonId, count(*) AS n FROM SWExpenseMember GROUP BY sWPersonId"
        " ORDER BY n DESC, sWPersonId"
    ).fetchall()
    for pk, _n in rows:
        if pk in people:
            _count(counts, "owner_guessed")
            return people[pk]
    return None


def _draft(
    row: tuple[Any, ...],
    members: list[tuple[Any, ...]],
    people: dict[int, Person],
    owner: Person,
    categories: dict[int, str],
    counts: dict[str, int],
) -> dict[str, Any] | None:
    (
        _pk,
        expense_id,
        currency,
        description,
        is_payment,
        cost,
        date,
        category_text,
        category_id,
        creation_method,
        deleted_at,
        notes,
        created_by,
        group_name,
    ) = row
    at = _rfc3339(date)
    if at is None:
        _count(counts, "skipped_no_date")
        return None
    shares: list[dict[str, Any]] = []
    owed = paid = None
    for person_pk, owed_share, paid_share in members:
        person = people.get(person_pk)
        entry: dict[str, Any] = {
            "ref": person.ref if person is not None else {"kind": "provider_id", "value": str(person_pk)},
            "paid": _number(paid_share),
            "owed": _number(owed_share),
        }
        if person is not None and person.name is not None:
            entry["name"] = person.name
        shares.append(entry)
        if person_pk == owner.pk:
            owed, paid = _number(owed_share), _number(paid_share)
    if owed is None or paid is None:
        _count(counts, "skipped_not_involved")
        return None
    amount = round(owed - paid, 2) if is_payment else -owed
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": str(expense_id),
        "amount": amount,
        "currency": str(currency).upper() if _text(currency) else "XXX",
    }
    merchant = _text(description)
    if merchant is not None:
        payload["merchant"] = merchant
    category = categories.get(category_id) if isinstance(category_id, int) else None
    category = category or _text(category_text)
    if category is not None:
        payload["category"] = category
    group = _text(group_name)
    if group is not None:
        payload["account"] = group
    payload["provider"] = NAME
    note = _text(notes)
    if note is not None:
        payload["note"] = note
    extra: dict[str, Any] = {
        "cost": _number(cost),
        "paid_share": paid,
        "owed_share": owed,
        "payment": bool(is_payment),
        "members": shares,
    }
    creator = next((p for p in people.values() if p.person_id == created_by), None)
    if creator is not None:
        extra["created_by"] = creator.ref
    method = _text(creation_method)
    if method is not None:
        extra["creation_method"] = method
    if isinstance(deleted_at, int | float) and deleted_at:
        extra["deleted"] = True
        _count(counts, "deleted")
    payload["extra"] = extra
    return {
        "at": at,
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


def _number(value: object) -> float | int:
    """A share or cost as the store keeps it; 0 when it is missing."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return value
    return 0


def _rfc3339(unix_seconds: object) -> str | None:
    if not isinstance(unix_seconds, int | float) or isinstance(unix_seconds, bool):
        return None
    if unix_seconds < EARLIEST_DATE:
        return None
    try:
        return datetime.fromtimestamp(int(unix_seconds), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return None
