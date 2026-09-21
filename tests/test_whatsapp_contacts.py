"""WhatsApp ContactsV2.sqlite → resolution/v1 alias lines (RFC 0006 `alias_of`): a linked-device id
paired with the phone number WhatsApp knows it by, so a `@lid` sender meets the address book."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters
from logbook.adapters import dawarich, ios_contacts, whatsapp, whatsapp_contacts
from logbook.adapters.takeout import location
from logbook.export import write_day_package
from logbook.resolve import labels
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
DAWARICH = ROOT / "tests" / "fixtures" / "dawarich" / "export.json"
TAKEOUT = ROOT / "tests" / "fixtures" / "takeout" / "Records.json"
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
APPLE_EPOCH = 978_307_200  # 2001-01-01T00:00:00Z, the zero of ZLASTUPDATED

DDL = """
CREATE TABLE ZWAADDRESSBOOKCONTACT (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER,
    ZSOURCE INTEGER, ZLASTUPDATED TIMESTAMP,
    ZFULLNAME VARCHAR, ZGIVENNAME VARCHAR, ZLASTNAME VARCHAR, ZPHONENUMBER VARCHAR,
    ZWHATSAPPID VARCHAR, ZLID VARCHAR, ZLIDHASH VARCHAR, ZINTEROPJID VARCHAR, ZUSERNAME VARCHAR
);
"""

OLA_LID = "236000000000001"
INES_LID = "236000000000002@lid"  # a store that spells the lid with its domain
KALLE_LID = "236000000000004"
COMPANY_LID = "236000000000005"
PER_LID = "236000000000006"

# (Z_PK, ZSOURCE, ZLASTUPDATED, ZFULLNAME, ZGIVENNAME, ZLASTNAME, ZPHONENUMBER, ZWHATSAPPID, ZLID,
#  ZLIDHASH, ZINTEROPJID, ZUSERNAME) — synthetic; nobody here exists
CONTACTS = [
    (
        1,
        0,
        780_000_000,
        "Ola Nordmann",
        "Ola",
        "Nordmann",
        "+47 900 00 001",
        "4790000001@s.whatsapp.net",
        OLA_LID,
        "h1",
        None,
        None,
    ),
    (
        2,
        0,
        780_000_100,
        "Ines Nordmann",
        "Ines",
        "Nordmann",
        "+47 900 00 002",
        "4790000002@s.whatsapp.net",
        INES_LID,
        "h2",
        None,
        "ines",
    ),
    (
        3,
        0,
        780_000_200,
        "Kari Nordmann",
        "Kari",
        "Nordmann",
        "+47 900 00 003",
        "4790000003@s.whatsapp.net",
        None,
        None,
        None,
        None,
    ),  # no lid
    (
        4,
        1,
        None,
        None,
        "Kalle",
        None,
        "0047-900-00-004",
        "4790000004@s.whatsapp.net",
        KALLE_LID,
        "h4",
        None,
        None,
    ),  # no full name
    (
        5,
        0,
        780_000_400,
        "Nordmann AS",
        None,
        None,
        "22 33 44 55",
        "4722334455@s.whatsapp.net",
        COMPANY_LID,
        "h5",
        None,
        None,
    ),  # no country code
    (
        6,
        0,
        780_000_500,
        "Per Nordmann",
        "Per",
        "Nordmann",
        "",
        "4790000006@s.whatsapp.net",
        PER_LID,
        "h6",
        None,
        None,
    ),  # no phone
    (
        7,
        0,
        780_000_600,
        "Ola (work)",
        "Ola",
        "Nordmann",
        "+47 900 00 007",
        "4790000007@s.whatsapp.net",
        OLA_LID,
        "h1",
        None,
        None,
    ),  # lid seen already
    (
        8,
        0,
        780_000_700,
        "Nobody",
        None,
        None,
        "+47 900 00 008",
        "4790000008@s.whatsapp.net",
        "",
        None,
        None,
        None,
    ),  # empty lid
]


def _contacts(tmp_path: Path, name: str = "ContactsV2.sqlite", rows: list[tuple] = CONTACTS) -> Path:
    p = tmp_path / name
    con = sqlite3.connect(p)
    try:
        con.executescript(DDL)
        con.executemany("INSERT INTO ZWAADDRESSBOOKCONTACT VALUES (?,1,1,?,?,?,?,?,?,?,?,?,?,?)", rows)
        con.commit()
    finally:
        con.close()
    return p


def _chat_store(tmp_path: Path) -> Path:
    """The two tables the whatsapp adapter sniffs for, and nothing this adapter wants."""
    p = tmp_path / "ChatStorage.sqlite"
    con = sqlite3.connect(p)
    try:
        con.executescript(
            "CREATE TABLE ZWACHATSESSION (Z_PK INTEGER PRIMARY KEY, ZCONTACTJID VARCHAR);"
            "CREATE TABLE ZWAMESSAGE (Z_PK INTEGER PRIMARY KEY, ZTEXT VARCHAR);"
        )
    finally:
        con.close()
    return p


def _address_book(tmp_path: Path) -> Path:
    p = tmp_path / "AddressBook.sqlitedb"
    con = sqlite3.connect(p)
    try:
        con.executescript(
            "CREATE TABLE ABPerson (ROWID INTEGER PRIMARY KEY, First TEXT, Last TEXT, Organization TEXT,"
            " Nickname TEXT, CreationDate INTEGER, ModificationDate INTEGER);"
            "CREATE TABLE ABMultiValue (UID INTEGER PRIMARY KEY, record_id INTEGER, property INTEGER,"
            " identifier INTEGER, label INTEGER, value TEXT);"
        )
        con.execute("INSERT INTO ABPerson VALUES (1,'Ola','Nordmann',NULL,NULL,NULL,NULL)")
        con.execute("INSERT INTO ABMultiValue VALUES (1,1,3,0,NULL,'+47 900 00 001')")
        con.commit()
    finally:
        con.close()
    return p


def _day_package(tmp_path: Path) -> Path:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    lb.append(
        at="2026-03-01T07:30:00Z",
        source="sim-phone",
        kind="location",
        tier=1,
        payload={"schema": "location/v1", "lat": 59.911, "lon": 10.75},
    )
    out = tmp_path / "pkg"
    write_day_package(lb, "2026-03-01", out)
    return out / "package.json"


def _by_lid(lines: list[dict]) -> dict[str, dict]:
    return {line["payload"]["ref"]["value"]: line for line in lines}


@pytest.fixture
def no_dial_prefix(monkeypatch):
    monkeypatch.delenv("LOGBOOK_DIAL_PREFIX", raising=False)


# -- registry ---------------------------------------------------------------


def test_registry_lists_whatsapp_contacts():
    assert "whatsapp-contacts" in [a.NAME for a in adapters.all_adapters()]


def test_registry_find_returns_whatsapp_contacts_for_the_store(tmp_path):
    found = adapters.find(_contacts(tmp_path))
    assert found is not None and found.NAME == "whatsapp-contacts"


def test_registry_find_by_content_not_by_name(tmp_path):
    """A Finder/iTunes backup stores the file under its hashed name, without an extension."""
    found = adapters.find(_contacts(tmp_path, "c4a9cfc0c2d3f08b5c1e3e8a0f0d5d3b7a9e1f2c"))
    assert found is not None and found.NAME == "whatsapp-contacts"


def test_registry_find_still_returns_the_others_for_theirs(tmp_path):
    assert adapters.find(_chat_store(tmp_path)).NAME == "whatsapp"
    assert adapters.find(_address_book(tmp_path)).NAME == "ios-contacts"


# -- sniff ------------------------------------------------------------------


def test_sniff_accepts_the_contacts_store(tmp_path):
    assert whatsapp_contacts.sniff(_contacts(tmp_path)) is True


def test_sniff_rejects_chat_storage_and_the_address_book(tmp_path):
    assert whatsapp_contacts.sniff(_chat_store(tmp_path)) is False
    assert whatsapp_contacts.sniff(_address_book(tmp_path)) is False


def test_sniff_rejects_dawarich_and_takeout_exports():
    assert whatsapp_contacts.sniff(DAWARICH) is False
    assert whatsapp_contacts.sniff(TAKEOUT) is False


def test_sniff_rejects_day_package(tmp_path):
    assert whatsapp_contacts.sniff(_day_package(tmp_path)) is False


def test_other_adapters_reject_the_contacts_store(tmp_path):
    p = _contacts(tmp_path)
    assert whatsapp.sniff(p) is False and ios_contacts.sniff(p) is False
    assert dawarich.sniff(p) is False and location.sniff(p) is False


@pytest.mark.parametrize(
    "ddl",
    [
        "CREATE TABLE lines (seq INTEGER, hash TEXT);",  # the logbook's own index, for instance
        "CREATE TABLE ZWAADDRESSBOOKCONTACT (Z_PK INTEGER, ZPHONENUMBER VARCHAR);",  # no lid column
        "CREATE TABLE ZWAMESSAGE (Z_PK INTEGER PRIMARY KEY, ZLID VARCHAR);",  # the column, wrong table
    ],
)
def test_sniff_rejects_unrelated_sqlite_files(tmp_path, ddl):
    p = tmp_path / "other.sqlite"
    con = sqlite3.connect(p)
    try:
        con.executescript(ddl)
    finally:
        con.close()
    assert whatsapp_contacts.sniff(p) is False


@pytest.mark.parametrize("content", ["", "just words\n", "SQLite format 3\0 but not really a database"])
def test_sniff_rejects_non_sqlite_files(tmp_path, content):
    p = tmp_path / "ContactsV2.sqlite"
    p.write_text(content, encoding="utf-8")
    assert whatsapp_contacts.sniff(p) is False


def test_sniff_rejects_directory_and_missing_file(tmp_path):
    assert whatsapp_contacts.sniff(tmp_path) is False
    assert whatsapp_contacts.sniff(tmp_path / "nope.sqlite") is False


def test_sniff_and_run_never_touch_the_source(tmp_path):
    p = _contacts(tmp_path)
    before = p.read_bytes()
    assert whatsapp_contacts.sniff(p) is True
    list(whatsapp_contacts.run(p))
    assert p.read_bytes() == before
    assert sorted(q.name for q in tmp_path.iterdir()) == [p.name]  # no -journal, -wal, -shm


# -- run: envelope ------------------------------------------------------------


def test_run_yields_alias_lines_at_the_import_time(tmp_path, no_dial_prefix):
    started = datetime.now(UTC).replace(microsecond=0)
    lines = list(whatsapp_contacts.run(_contacts(tmp_path)))
    assert len(lines) == 3  # Ola, Ines, Kalle; the rest have no lid, no usable phone, or a lid seen
    ats = {line["at"] for line in lines}
    assert len(ats) == 1
    at = datetime.strptime(ats.pop(), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    assert started <= at <= datetime.now(UTC)
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["end"] is None and line["tz"] is None
        assert line["source"] == "whatsapp-contacts" and line["kind"] == "resolution" and line["tier"] == 2
        assert line["payload"]["schema"] == "resolution/v1"
        assert line["payload"]["method"] == "exact"


def test_run_since_is_accepted_and_ignored(tmp_path, no_dial_prefix):
    p = _contacts(tmp_path)
    assert len(list(whatsapp_contacts.run(p, since="2099-01-01T00:00:00Z"))) == 3


# -- run: the alias ------------------------------------------------------------


def test_run_ref_is_the_lid_as_the_whatsapp_adapter_spells_a_sender(tmp_path, no_dial_prefix):
    lines = _by_lid(list(whatsapp_contacts.run(_contacts(tmp_path))))
    assert set(lines) == {f"{OLA_LID}@lid", INES_LID, f"{KALLE_LID}@lid"}
    for value in lines:
        assert lines[value]["payload"]["ref"] == {"kind": "handle", "value": value}
        assert whatsapp._ref(value) == {"kind": "handle", "value": value}  # the same ref, both sides


def test_run_alias_of_is_the_normalised_phone_and_nothing_is_minted(tmp_path, no_dial_prefix):
    p = _by_lid(list(whatsapp_contacts.run(_contacts(tmp_path))))[f"{OLA_LID}@lid"]["payload"]
    assert p["alias_of"] == {"kind": "phone", "value": "+4790000001"}
    assert "entity" not in p


def test_run_label_is_the_full_name(tmp_path, no_dial_prefix):
    lines = _by_lid(list(whatsapp_contacts.run(_contacts(tmp_path))))
    assert lines[f"{OLA_LID}@lid"]["payload"]["label"] == "Ola Nordmann"
    assert lines[INES_LID]["payload"]["label"] == "Ines Nordmann"


def test_run_label_falls_back_to_given_and_last_name(tmp_path, no_dial_prefix):
    lines = _by_lid(list(whatsapp_contacts.run(_contacts(tmp_path))))
    assert lines[f"{KALLE_LID}@lid"]["payload"]["label"] == "Kalle"


def test_run_label_is_absent_when_the_row_has_no_name(tmp_path, no_dial_prefix):
    rows = [(1, 0, None, None, None, None, "+47 900 00 001", None, OLA_LID, None, None, None)]
    (line,) = whatsapp_contacts.run(_contacts(tmp_path, rows=rows))
    assert "label" not in line["payload"]


def test_run_raw_id_is_alias_handle_and_the_ref_value(tmp_path, no_dial_prefix):
    for line in whatsapp_contacts.run(_contacts(tmp_path)):
        assert line["payload"]["raw_id"] == f"alias:handle:{line['payload']['ref']['value']}"


def test_run_extra_keeps_the_whatsapp_id_the_source_and_the_dates(tmp_path, no_dial_prefix):
    lines = _by_lid(list(whatsapp_contacts.run(_contacts(tmp_path))))
    extra = lines[f"{OLA_LID}@lid"]["payload"]["extra"]
    assert extra["record_id"] == 1
    assert extra["whatsapp_id"] == "4790000001@s.whatsapp.net"
    assert extra["contact_source"] == 0
    assert extra["entered"] == "+47 900 00 001"
    assert extra["last_updated"] == datetime.fromtimestamp(APPLE_EPOCH + 780_000_000, UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    assert "last_updated" not in lines[f"{KALLE_LID}@lid"]["payload"]["extra"]


# -- run: phones ------------------------------------------------------------


def test_run_phone_00_prefix_becomes_plus(tmp_path, no_dial_prefix):
    p = _by_lid(list(whatsapp_contacts.run(_contacts(tmp_path))))[f"{KALLE_LID}@lid"]["payload"]
    assert p["alias_of"]["value"] == "+4790000004"


def test_run_phone_without_country_code_is_skipped_without_a_dial_prefix(tmp_path, no_dial_prefix):
    counts: dict[str, int] = {}
    lines = _by_lid(list(whatsapp_contacts.run(_contacts(tmp_path), counts=counts)))
    assert f"{COMPANY_LID}@lid" not in lines
    assert counts["skipped_no_phone"] == 2  # the company's local number and Per's empty one


def test_run_phone_without_country_code_takes_logbook_dial_prefix(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGBOOK_DIAL_PREFIX", "47")
    lines = _by_lid(list(whatsapp_contacts.run(_contacts(tmp_path))))
    assert lines[f"{COMPANY_LID}@lid"]["payload"]["alias_of"] == {"kind": "phone", "value": "+4722334455"}
    assert lines[f"{OLA_LID}@lid"]["payload"]["alias_of"]["value"] == "+4790000001"  # untouched


# -- run: skips ------------------------------------------------------------


def test_run_skips_and_counts_rows_without_a_lid_a_phone_or_with_a_lid_seen(tmp_path, no_dial_prefix):
    counts: dict[str, int] = {}
    lines = list(whatsapp_contacts.run(_contacts(tmp_path), counts=counts))
    assert {line["payload"]["extra"]["record_id"] for line in lines} == {1, 2, 4}
    assert counts == {"skipped_no_lid": 2, "skipped_no_phone": 2, "skipped_duplicate_lid": 1}


def test_run_first_row_with_a_lid_wins(tmp_path, no_dial_prefix):
    p = _by_lid(list(whatsapp_contacts.run(_contacts(tmp_path))))[f"{OLA_LID}@lid"]["payload"]
    assert p["label"] == "Ola Nordmann" and p["extra"]["record_id"] == 1


# -- through the log: append, dedupe on re-run, names, CLI --------------------------------


def test_run_lines_append_and_re_running_appends_nothing(tmp_path, no_dial_prefix):
    p = _contacts(tmp_path)
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    assert lb.append_many(whatsapp_contacts.run(p)) == 3
    assert lb.append_many(whatsapp_contacts.run(p)) == 0
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 3
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)
        assert line["tz"] == "Europe/Oslo"


def test_lid_meets_the_address_book_through_the_alias(tmp_path, no_dial_prefix):
    """The point of the adapter: the contacts import names the phone, the alias names the lid."""
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    lb.append_many(whatsapp_contacts.run(_contacts(tmp_path)))
    assert labels(lb)[("handle", f"{OLA_LID}@lid")] == "Ola Nordmann"  # the alias line's own label
    lb.append_many(ios_contacts.run(_address_book(tmp_path)))
    found = labels(lb)
    assert found[("phone", "+4790000001")] == "Ola Nordmann"
    assert found[("handle", f"{OLA_LID}@lid")] == "Ola Nordmann"  # now the address book's


def _cli(tmp_path):
    env = {**os.environ, "LOGBOOK_HOME": str(tmp_path / "lb"), "PYTHONPATH": str(ROOT)}
    env.pop("LOGBOOK_DIAL_PREFIX", None)

    def run(*a):
        return subprocess.run(
            [sys.executable, "-m", "logbook.cli", *a],
            env=env,
            capture_output=True,
            encoding="utf-8",
            check=True,
        )

    return run


def test_cli_add_reports_lines_and_skips(tmp_path):
    run = _cli(tmp_path)
    run("init", str(tmp_path / "lb"), "--timezone", "Europe/Oslo")
    p = _contacts(tmp_path)
    out = run("add", str(p)).stdout
    assert "added 3 lines from whatsapp-contacts" in out
    assert "skipped 2 without a linked-device id, 2 without a usable phone number," in out
    assert "1 with a linked-device id already seen" in out
    assert "added 0 lines from whatsapp-contacts" in run("add", str(p)).stdout
    assert "valid — 3 lines" in run("verify").stdout


# -- property: every emitted line is a valid resolution/v1 alias -------------------


def _rfc_rules(line: dict) -> None:
    assert set(line) == ENVELOPE
    assert line["kind"] == "resolution" and line["tier"] == 2 and line["end"] is None
    assert line["source"] == "whatsapp-contacts"
    assert line["at"].endswith("Z") and len(line["at"]) == 20
    p = line["payload"]
    assert set(p) - {"label"} == {"schema", "ref", "alias_of", "method", "raw_id", "extra"}
    assert p["schema"] == "resolution/v1"
    assert p["ref"]["kind"] == "handle"
    assert re.fullmatch(r"[^@\s]+@lid", p["ref"]["value"])
    assert p["alias_of"]["kind"] == "phone"
    assert re.fullmatch(r"\+[0-9]+", p["alias_of"]["value"])
    if "label" in p:
        assert isinstance(p["label"], str) and p["label"] == p["label"].strip() and p["label"]
    assert p["method"] == "exact"
    assert p["raw_id"] == f"alias:handle:{p['ref']['value']}"
    assert isinstance(p["extra"], dict) and isinstance(p["extra"]["record_id"], int)
    json.dumps(line, allow_nan=False)


_name = st.one_of(st.none(), st.text(max_size=12))
_digits = st.text(alphabet="0123456789", min_size=0, max_size=14)
_phone = st.one_of(
    st.tuples(st.sampled_from(["", "+", "00", "0"]), _digits).map(lambda t: t[0] + t[1]),
    st.text(alphabet="0123456789 +-.()", max_size=16),
    st.text(max_size=10),
    st.none(),
)
_lid = st.one_of(
    st.none(),
    _digits,
    _digits.map(lambda d: f"{d}@lid"),
    st.text(max_size=10),
)
_date = st.one_of(st.none(), st.integers(-(2**40), 2**40), st.floats(allow_nan=False, allow_infinity=False))
_row = st.tuples(st.integers(0, 3), _date, _name, _name, _name, _phone, _name, _lid, _name, _name, _name)
_store = st.lists(_row, max_size=6)
_prefix = st.sampled_from([None, "", "41", "47"])


@settings(max_examples=40, deadline=None)
@given(_store, _prefix)
def test_any_contacts_store_yields_only_valid_lines(tmp_path_factory, store, prefix):
    env = {k: v for k, v in os.environ.items() if k != "LOGBOOK_DIAL_PREFIX"}
    if prefix is not None:
        env["LOGBOOK_DIAL_PREFIX"] = prefix
    p = tmp_path_factory.mktemp("store") / "ContactsV2.sqlite"
    rows = [(pk, *row) for pk, row in enumerate(store, start=1)]
    _contacts(p.parent, p.name, rows)
    with mock.patch.dict(os.environ, env, clear=True):
        counts: dict[str, int] = {}
        lines = list(whatsapp_contacts.run(p, counts=counts))
    for line in lines:
        _rfc_rules(line)
    refs = [line["payload"]["ref"]["value"] for line in lines]
    assert len(refs) == len(set(refs))  # one line per lid
    assert len(lines) + sum(counts.values()) == len(rows)  # every row is a line or a count
    lb = Logbook.init(p.parent / "lb", "Europe/Oslo")
    assert lb.append_many(lines) == len(lines)
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)
