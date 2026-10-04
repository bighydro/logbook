"""Splitwise database.sqlite → transaction/v1 (RFC 0021): the owner's share of every expense, tier 3."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook.contrib import adapters
from logbook.contrib.adapters import copilot, ios_notes, splitwise
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}

DDL = """
CREATE TABLE SWPerson (id INTEGER PRIMARY KEY, firstName TEXT, lastName TEXT, email TEXT, phone TEXT,
    personId INTEGER, registrationStatus TEXT);
CREATE TABLE SWGroup (id INTEGER PRIMARY KEY, groupId INTEGER, groupName TEXT, groupType TEXT);
CREATE TABLE SWCategory (id INTEGER PRIMARY KEY, categoryId INTEGER, parentCategoryId INTEGER,
    categoryName TEXT);
CREATE TABLE SWExpense (id INTEGER PRIMARY KEY, currencyCode TEXT, expenseId INTEGER, groupId INTEGER,
    description TEXT, isPayment INTEGER, cost REAL, date INTEGER, updatedAtDate INTEGER,
    createdAtDate INTEGER, category TEXT, categoryId INTEGER, creationMethod TEXT, deletedAtDate INTEGER,
    notes TEXT, createdById INTEGER);
CREATE TABLE SWExpenseMember (id INTEGER PRIMARY KEY, sWPersonId INTEGER, sWExpenseId INTEGER,
    owedShare REAL, paidShare REAL);
"""

# -- the fixture: synthetic, nobody in it exists ------------------------------------------

OWNER = "kari.nordmann@example.org"
KARI, OLA, PER = 1, 2, 3  # SWPerson.id; personId is the server's number, 10 + id
TRIP, HOME = 100, 101
DINING, GENERAL = 13, 1
T0 = 1_772_000_000  # 2026-02-25T06:13:20Z
DINNER, PAID_OLA, OLA_PAID, DELETED, ALONE, NOTED, UNDATED = 1, 2, 3, 4, 5, 6, 7

PERSONS = [
    (KARI, "Kari", "Nordmann", OWNER, None, 11, "confirmed"),
    (OLA, "Ola", "Nordmann", "ola@example.org", None, 12, "confirmed"),
    (PER, "Per", None, None, "+44 7700 900123", 13, None),
]
GROUPS = [(1, TRIP, "Sailing trip", "trip"), (2, HOME, "Home", "home")]
CATEGORIES = [(1, GENERAL, None, "General"), (2, DINING, GENERAL, "Dining out")]
# (id, currency, expenseId, groupId, description, isPayment, cost, date, category, categoryId,
#  creationMethod, deletedAtDate, notes, createdById)
EXPENSES = [
    (DINNER, "NOK", 1000000001, TRIP, "Dinner at the marina", 0, 90, T0, "Dining out", DINING,
     "equal", None, None, 11),
    (PAID_OLA, "NOK", 1000000002, TRIP, "Payment", 1, 30, T0 + 100, "General", GENERAL,
     "payment", None, None, 11),
    (OLA_PAID, "NOK", 1000000003, TRIP, "Payment", 1, 12.5, T0 + 200, "General", GENERAL,
     "payment", None, None, 12),
    (DELETED, "EUR", 1000000004, None, "Duplicate taxi", 0, 20, T0 + 300, "General", GENERAL,
     None, T0 + 400, None, 12),
    (ALONE, "NOK", 1000000005, HOME, "Ola and Per only", 0, 40, T0 + 500, "General", GENERAL,
     "equal", None, None, 12),
    (NOTED, "NOK", 1000000006, None, "Fuel", 0, 60, T0 + 600, "General", 999,
     "percent", None, "Marina pump, card", 13),
    (UNDATED, "NOK", 1000000007, TRIP, "No date", 0, 1, None, "General", GENERAL,
     "equal", None, None, 11),
]  # fmt: skip
# (sWPersonId, sWExpenseId, owedShare, paidShare)
MEMBERS = [
    (KARI, DINNER, 30, 90), (OLA, DINNER, 30, 0), (PER, DINNER, 30, 0),
    (KARI, PAID_OLA, 0, 30), (OLA, PAID_OLA, 30, 0),
    (OLA, OLA_PAID, 0, 12.5), (KARI, OLA_PAID, 12.5, 0),
    (KARI, DELETED, 10, 20), (OLA, DELETED, 10, 0),
    (OLA, ALONE, 20, 40), (PER, ALONE, 20, 0),
    (KARI, NOTED, 45, 0), (PER, NOTED, 15, 60),
    (KARI, UNDATED, 1, 1),
]  # fmt: skip


def _store(folder: Path, name: str = "database.sqlite") -> Path:
    p = folder / name
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    try:
        con.executescript(DDL)
        con.executemany("INSERT INTO SWPerson VALUES (?,?,?,?,?,?,?)", PERSONS)
        con.executemany("INSERT INTO SWGroup VALUES (?,?,?,?)", GROUPS)
        con.executemany("INSERT INTO SWCategory VALUES (?,?,?,?)", CATEGORIES)
        con.executemany(
            "INSERT INTO SWExpense VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[7], r[7], *r[8:]) for r in EXPENSES],
        )
        con.executemany("INSERT INTO SWExpenseMember VALUES (NULL,?,?,?,?)", MEMBERS)
        con.commit()
    finally:
        con.close()
    return p


def _lines(p: Path, **options: object) -> dict[int, dict]:
    return {int(line["payload"]["raw_id"]) - 1000000000: line for line in splitwise.run(p, **options)}  # type: ignore[arg-type]


# -- registry and sniff -------------------------------------------------------------------


def test_registry_lists_splitwise_and_finds_the_store(tmp_path):
    assert "splitwise" in [a.NAME for a in adapters.all_adapters()]
    found = adapters.find(_store(tmp_path))
    assert found is not None and found.NAME == "splitwise"


def test_sniff_rejects_other_stores_and_junk(tmp_path):
    assert splitwise.sniff(tmp_path) is False
    assert splitwise.sniff(tmp_path / "nope.sqlite") is False
    p = tmp_path / "other.sqlite"
    con = sqlite3.connect(p)
    try:
        con.executescript("CREATE TABLE SWExpense (id INTEGER);")  # half of it
    finally:
        con.close()
    assert splitwise.sniff(p) is False
    (tmp_path / "text.sqlite").write_text("SQLite format 3\0 but not really", encoding="utf-8")
    assert splitwise.sniff(tmp_path / "text.sqlite") is False


def test_other_adapters_reject_the_splitwise_store(tmp_path):
    p = _store(tmp_path)
    assert ios_notes.sniff(p) is False and copilot.sniff(p) is False


def test_sniff_and_run_never_touch_the_source(tmp_path):
    p = _store(tmp_path)
    before = p.read_bytes()
    assert splitwise.sniff(p) is True
    list(splitwise.run(p, owner_emails=[OWNER]))
    assert p.read_bytes() == before
    assert [q.name for q in tmp_path.iterdir()] == [p.name]


# -- run: envelope ------------------------------------------------------------------------


def test_run_yields_tier_3_transaction_lines_at_the_expense_date(tmp_path):
    lines = list(splitwise.run(_store(tmp_path), owner_emails=[OWNER]))
    assert len(lines) == 5  # dinner, both payments, the deleted one, the noted one
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["end"] is None and line["tz"] is None
        assert line["source"] == "splitwise" and line["kind"] == "transaction" and line["tier"] == 3
        assert line["payload"]["schema"] == "transaction/v1" and line["payload"]["provider"] == "splitwise"
    assert lines[0]["at"] == "2026-02-25T06:13:20Z"


def test_run_streams_in_date_order_and_honours_since(tmp_path):
    p = _store(tmp_path)
    assert list(_lines(p, owner_emails=[OWNER])) == [DINNER, PAID_OLA, OLA_PAID, DELETED, NOTED]
    assert list(_lines(p, owner_emails=[OWNER], since="2026-02-25T06:18:20Z")) == [DELETED, NOTED]


# -- run: the owner's share ---------------------------------------------------------------


def test_run_an_expense_is_the_owners_owed_share_negative_with_the_whole_split_in_extra(tmp_path):
    p = _lines(_store(tmp_path), owner_emails=[OWNER])[DINNER]["payload"]
    assert p["amount"] == -30 and p["currency"] == "NOK"
    assert p["merchant"] == "Dinner at the marina" and p["category"] == "Dining out"
    assert p["account"] == "Sailing trip" and "note" not in p and "status" not in p
    assert p["extra"]["cost"] == 90 and p["extra"]["paid_share"] == 90 and p["extra"]["owed_share"] == 30
    assert p["extra"]["payment"] is False and p["extra"]["creation_method"] == "equal"
    assert p["extra"]["created_by"] == {"kind": "email", "value": OWNER}
    assert p["extra"]["members"] == [
        {"ref": {"kind": "email", "value": OWNER}, "name": "Kari Nordmann", "paid": 90, "owed": 30},
        {"ref": {"kind": "email", "value": "ola@example.org"}, "name": "Ola Nordmann", "paid": 0, "owed": 30},
        {"ref": {"kind": "phone", "value": "+447700900123"}, "name": "Per", "paid": 0, "owed": 30},
    ]
    assert "deleted" not in p["extra"]


def test_run_a_payment_is_negative_when_the_owner_paid_and_positive_when_paid(tmp_path):
    lines = _lines(_store(tmp_path), owner_emails=[OWNER])
    assert (
        lines[PAID_OLA]["payload"]["amount"] == -30 and lines[PAID_OLA]["payload"]["extra"]["payment"] is True
    )
    assert lines[OLA_PAID]["payload"]["amount"] == 12.5
    assert lines[OLA_PAID]["payload"]["extra"]["created_by"] == {"kind": "email", "value": "ola@example.org"}


def test_run_deleted_expense_is_a_line_flagged_and_counted_without_a_group(tmp_path):
    counts: dict[str, int] = {}
    p = _lines(_store(tmp_path), owner_emails=[OWNER], counts=counts)[DELETED]["payload"]
    assert p["amount"] == -10 and p["currency"] == "EUR" and "account" not in p
    assert p["extra"]["deleted"] is True
    assert counts["deleted"] == 1


def test_run_an_expense_without_the_owner_is_skipped_and_counted(tmp_path):
    counts: dict[str, int] = {}
    lines = _lines(_store(tmp_path), owner_emails=[OWNER], counts=counts)
    assert ALONE not in lines and UNDATED not in lines
    assert counts["skipped_not_involved"] == 1 and counts["skipped_no_date"] == 1


def test_run_keeps_the_note_and_the_source_category_text_when_the_id_is_unknown(tmp_path):
    p = _lines(_store(tmp_path), owner_emails=[OWNER])[NOTED]["payload"]
    assert p["amount"] == -45 and p["note"] == "Marina pump, card" and p["category"] == "General"
    assert p["extra"]["created_by"] == {"kind": "phone", "value": "+447700900123"}


# -- run: who the owner is -----------------------------------------------------------------


def test_run_matches_the_owner_by_email_case_insensitively(tmp_path):
    assert (
        _lines(_store(tmp_path), owner_emails=["Kari.Nordmann@Example.org"])[DINNER]["payload"]["amount"]
        == -30
    )


def test_run_without_owner_emails_takes_the_person_on_most_expenses_and_says_so(tmp_path):
    counts: dict[str, int] = {}
    lines = _lines(_store(tmp_path), counts=counts)
    assert lines[DINNER]["payload"]["amount"] == -30  # Kari is on five expenses, Ola on four
    assert counts["owner_guessed"] == 1


def test_run_an_owner_email_nobody_has_falls_back_to_the_guess(tmp_path):
    counts: dict[str, int] = {}
    lines = _lines(_store(tmp_path), owner_emails=["nobody@example.org"], counts=counts)
    assert lines[DINNER]["payload"]["amount"] == -30 and counts["owner_guessed"] == 1


# -- through the logbook -------------------------------------------------------------------


def test_add_dedupes_on_a_second_import_and_validates(tmp_path, monkeypatch):
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    lb = Logbook.init(root, "Europe/Oslo")
    store = _store(tmp_path / "phone")
    assert lb.append_many(splitwise.run(store, owner_emails=[OWNER])) == 5
    assert lb.append_many(splitwise.run(store, owner_emails=[OWNER])) == 0
    assert lb.verify()[0] == 5
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)
        assert line["tier"] == 3
