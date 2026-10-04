"""Copilot Money CopilotDB.sqlite → transaction/v1 (RFC 0021): one line per transaction, tier 3."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters
from logbook.adapters import copilot, ios_notes, whatsapp
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}

DDL = """
CREATE TABLE Transactions (
    id TEXT PRIMARY KEY, transaction_id TEXT, account_id TEXT, iso_currency_code TEXT, original_name TEXT,
    name TEXT, original_clean_name TEXT, name_override TEXT, amount DOUBLE, original_amount DOUBLE,
    pending BOOLEAN, recurring BOOLEAN, recurring_id TEXT, user_deleted BOOLEAN, plaid_deleted BOOLEAN,
    category_id TEXT, plaid_category_strings BLOB, date DATE, original_date DATE, type TEXT,
    user_note TEXT, parent_transaction_id TEXT, tag_ids BLOB
);
CREATE TABLE grdb_migrations (identifier TEXT);
"""

# -- the fixture: synthetic, no account in it exists ---------------------------------------

CAFE, SALARY, TRANSFER, PENDING, DELETED, NODATE, SPLIT = (
    "6f1c2a9e-0000-4000-8000-000000000001",
    "6f1c2a9e-0000-4000-8000-000000000002",
    "6f1c2a9e-0000-4000-8000-000000000003",
    "6f1c2a9e-0000-4000-8000-000000000004",
    "6f1c2a9e-0000-4000-8000-000000000005",
    "6f1c2a9e-0000-4000-8000-000000000006",
    "6f1c2a9e-0000-4000-8000-000000000007",
)
CARD, CHECKING = "acct_0000000000000001", "acct_0000000000000002"
# (id, account_id, currency, original_name, name, name_override, amount, pending, recurring, recurring_id,
#  user_deleted, category_id, plaid_category_strings, date, type, user_note, parent_transaction_id, tag_ids)
ROWS = [
    (CAFE, CARD, "USD", "HARBOUR CAFE OSLO", "Harbour Cafe", None, 42.5, 0, 0, None, 0, "restaurants", b"[]",
     "2026-03-01 23:00:00.000", "regular", None, None, None),
    (SALARY, CHECKING, "USD", "ACME PAYROLL", "Acme Payroll", "Salary", -3000, 0, 1, "rec_1", 0, "income",
     b'["Transfer","Payroll"]', "2026-03-02 22:00:00.000", "income", "March", None, b'["tag_a"]'),
    (TRANSFER, CHECKING, "USD", "ONLINE TRANSFER", "Online Transfer", None, 500, 0, 0, None, 0, "",
     b"[]", "2026-03-03 03:00:00.000", "internal_transfer", None, None, None),
    (PENDING, CARD, "USD", "MARINA FUEL", "Marina Fuel", None, 120.25, 1, 0, None, 0, None, b"[]",
     "2026-03-04 22:00:00.000", "regular", None, None, None),
    (DELETED, CARD, "USD", "DUPLICATE", "Duplicate", None, 9.99, 0, 0, None, 1, "shopping", b"[]",
     "2026-03-05 22:00:00.000", "regular", None, None, None),
    (NODATE, CARD, "USD", "NO DATE", "No Date", None, 1, 0, 0, None, 0, "shopping", b"[]",
     None, "regular", None, None, None),
    (SPLIT, CARD, "USD", "HARBOUR CAFE OSLO", "Harbour Cafe", None, 12.5, 0, 0, None, 0, "groceries", b"[]",
     "2026-03-01 23:00:00.000", "regular", None, CAFE, None),
]  # fmt: skip


def _store(folder: Path, name: str = "CopilotDB.sqlite") -> Path:
    p = folder / name
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    try:
        con.executescript(DDL)
        con.executemany(
            "INSERT INTO Transactions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (r[0], r[0], r[1], r[2], r[3], r[4], r[4], r[5], r[6], r[6], r[7], r[8], r[9], r[10], 0,
                 r[11], r[12], r[13], r[13], r[14], r[15], r[16], r[17])
                for r in ROWS
            ],
        )  # fmt: skip
        con.execute("INSERT INTO grdb_migrations VALUES ('createTransactionTable')")
        con.commit()
    finally:
        con.close()
    return p


def _by_id(lines: list[dict]) -> dict[str, dict]:
    return {line["payload"]["raw_id"]: line for line in lines}


# -- registry and sniff -------------------------------------------------------------------


def test_registry_lists_copilot_and_finds_the_store(tmp_path):
    assert "copilot" in [a.NAME for a in adapters.all_adapters()]
    found = adapters.find(_store(tmp_path))
    assert found is not None and found.NAME == "copilot"


def test_sniff_rejects_other_stores_and_junk(tmp_path):
    assert copilot.sniff(tmp_path) is False
    assert copilot.sniff(tmp_path / "nope.sqlite") is False
    p = tmp_path / "other.sqlite"
    con = sqlite3.connect(p)
    try:
        con.executescript("CREATE TABLE Transactions (id TEXT, amount DOUBLE);")  # not Copilot's columns
    finally:
        con.close()
    assert copilot.sniff(p) is False
    (tmp_path / "text.sqlite").write_text("SQLite format 3\0 but not really", encoding="utf-8")
    assert copilot.sniff(tmp_path / "text.sqlite") is False


def test_other_adapters_reject_the_copilot_store(tmp_path):
    p = _store(tmp_path)
    assert ios_notes.sniff(p) is False and whatsapp.sniff(p) is False


def test_sniff_and_run_never_touch_the_source(tmp_path):
    p = _store(tmp_path)
    before = p.read_bytes()
    assert copilot.sniff(p) is True
    list(copilot.run(p))
    assert p.read_bytes() == before
    assert [q.name for q in tmp_path.iterdir()] == [p.name]


# -- run: envelope ------------------------------------------------------------------------


def test_run_yields_tier_3_transaction_lines_at_the_stored_instant(tmp_path):
    lines = list(copilot.run(_store(tmp_path)))
    assert len(lines) == 6  # the undated row is skipped
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["end"] is None and line["tz"] is None
        assert line["source"] == "copilot" and line["kind"] == "transaction" and line["tier"] == 3
        assert line["payload"]["schema"] == "transaction/v1" and line["payload"]["provider"] == "copilot"
    assert _by_id(lines)[CAFE]["at"] == "2026-03-01T23:00:00Z"


def test_run_streams_in_date_order_and_honours_since(tmp_path):
    p = _store(tmp_path)
    assert list(_by_id(list(copilot.run(p)))) == [CAFE, SPLIT, SALARY, TRANSFER, PENDING, DELETED]
    assert list(_by_id(list(copilot.run(p, since="2026-03-03T03:00:00Z")))) == [TRANSFER, PENDING, DELETED]


# -- run: the transaction fields ----------------------------------------------------------


def test_run_a_purchase_is_negative_with_merchant_category_account_and_date(tmp_path):
    p = _by_id(list(copilot.run(_store(tmp_path), timezone="Europe/Oslo")))[CAFE]["payload"]
    assert p["amount"] == -42.5 and p["currency"] == "USD"
    assert p["merchant"] == "Harbour Cafe" and p["category"] == "restaurants"
    assert p["account"] == CARD and p["status"] == "posted"
    assert p["date"] == "2026-03-02"  # 23:00Z is local midnight of the 2nd in Oslo
    assert p["extra"] == {"type": "regular", "recurring": False, "original_name": "HARBOUR CAFE OSLO"}
    assert "note" not in p


def test_run_date_is_the_utc_day_without_a_record_zone(tmp_path):
    p = _by_id(list(copilot.run(_store(tmp_path))))[CAFE]["payload"]
    assert p["date"] == "2026-03-01"


def test_run_income_is_positive_and_keeps_the_override_note_tags_and_plaid_categories(tmp_path):
    p = _by_id(list(copilot.run(_store(tmp_path))))[SALARY]["payload"]
    assert p["amount"] == 3000 and p["merchant"] == "Salary" and p["category"] == "income"
    assert p["note"] == "March"
    assert p["extra"]["type"] == "income" and p["extra"]["recurring"] is True
    assert p["extra"]["recurring_id"] == "rec_1" and p["extra"]["name"] == "Acme Payroll"
    assert p["extra"]["original_name"] == "ACME PAYROLL"
    assert p["extra"]["plaid_categories"] == ["Transfer", "Payroll"] and p["extra"]["tags"] == ["tag_a"]


def test_run_an_empty_category_is_absent_and_a_transfer_keeps_its_type(tmp_path):
    p = _by_id(list(copilot.run(_store(tmp_path))))[TRANSFER]["payload"]
    assert "category" not in p and p["amount"] == -500 and p["extra"]["type"] == "internal_transfer"


def test_run_pending_and_deleted_are_lines_flagged_and_counted(tmp_path):
    counts: dict[str, int] = {}
    lines = _by_id(list(copilot.run(_store(tmp_path), counts=counts)))
    assert lines[PENDING]["payload"]["status"] == "pending"
    assert lines[DELETED]["payload"]["extra"]["deleted"] is True
    assert counts == {"deleted": 1, "pending": 1, "skipped_no_date": 1}


def test_run_a_split_child_names_its_parent(tmp_path):
    p = _by_id(list(copilot.run(_store(tmp_path))))[SPLIT]["payload"]
    assert p["extra"]["parent"] == CAFE and p["amount"] == -12.5


# -- through the logbook -------------------------------------------------------------------


def test_add_dedupes_on_a_second_import_and_validates(tmp_path, monkeypatch):
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    lb = Logbook.init(root, "Europe/Oslo")
    store = _store(tmp_path / "phone")
    assert lb.append_many(copilot.run(store)) == 6
    assert lb.append_many(copilot.run(store)) == 0
    assert lb.verify()[0] == 6
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)
        assert line["tier"] == 3
