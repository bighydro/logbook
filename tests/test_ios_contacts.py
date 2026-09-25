"""iOS AddressBook.sqlitedb → resolution/v1 (RFC 0006): where a record's people come from (ADR 0013.2)."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters
from logbook.adapters import dawarich, ios_contacts
from logbook.adapters.takeout import location
from logbook.export import write_day_package
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
DAWARICH = ROOT / "tests" / "fixtures" / "dawarich" / "export.json"
TAKEOUT = ROOT / "tests" / "fixtures" / "takeout" / "Records.json"
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
APPLE_EPOCH = 978_307_200  # 2001-01-01T00:00:00Z, the zero of CreationDate/ModificationDate

PHONE, EMAIL = 3, 4

DDL = """
CREATE TABLE ABPerson (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
    First TEXT, Last TEXT, Middle TEXT, Organization TEXT, Nickname TEXT,
    CreationDate INTEGER, ModificationDate INTEGER
);
CREATE TABLE ABMultiValue (
    UID INTEGER PRIMARY KEY, record_id INTEGER, property INTEGER, identifier INTEGER,
    label INTEGER, value TEXT
);
CREATE TABLE ABMultiValueLabel (ROWID INTEGER PRIMARY KEY, value TEXT);
"""

# (ROWID, First, Last, Organization, Nickname, CreationDate, ModificationDate) — synthetic, Oslo
PERSONS = [
    (1, "Ines", "Nordmann", None, None, 700_000_000, 780_000_000),
    (2, "Ola", "Nordmann", "Nordmann AS", None, 700_000_100, 780_000_100),
    (3, None, None, "Nordmann AS", None, 700_000_200, 780_000_200),
    (4, "Kari", "Nordmann", None, None, 700_000_300, None),  # no phone, no email
    (5, None, None, None, "Kalle", 700_000_400, 780_000_400),
]
LABELS = {1: "_$!<Mobile>!$_", 2: "_$!<Work>!$_", 3: "_$!<Home>!$_"}
# (UID, record_id, property, label, value)
VALUES = [
    (10, 1, PHONE, 1, "+47 912 34 567"),  # spaces
    (11, 1, EMAIL, 3, "Ines@Example.org"),
    (12, 1, EMAIL, 2, " ines@example.org "),  # the same address, other case, padded
    (20, 2, PHONE, 1, "0047-22-33-44-55"),  # 00 prefix, dashes
    (21, 2, PHONE, 2, "(22) 33.44.55"),  # no country code
    (22, 2, EMAIL, 2, "ola@example.org"),
    (30, 3, PHONE, 2, "+47 21 00 00 00"),
    (31, 3, EMAIL, 2, "post@nordmann.example"),
    (50, 5, PHONE, 1, "+47 900 00 000"),
]


def _address_book(tmp_path: Path, name: str = "AddressBook.sqlitedb") -> Path:
    p = tmp_path / name
    con = sqlite3.connect(p)
    try:
        con.executescript(DDL)
        con.executemany("INSERT INTO ABPerson VALUES (?,?,?,NULL,?,?,?,?)", PERSONS)
        con.executemany("INSERT INTO ABMultiValueLabel VALUES (?,?)", LABELS.items())
        con.executemany("INSERT INTO ABMultiValue VALUES (?,?,?,0,?,?)", VALUES)
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


def _by_ref(lines: list[dict]) -> dict[str, dict]:
    return {line["payload"]["raw_id"]: line for line in lines}


@pytest.fixture
def no_dial_prefix(monkeypatch):
    monkeypatch.delenv("LOGBOOK_DIAL_PREFIX", raising=False)


# -- registry ---------------------------------------------------------------


def test_registry_lists_ios_contacts():
    assert "ios-contacts" in [a.NAME for a in adapters.all_adapters()]


def test_registry_find_returns_ios_contacts_for_an_address_book(tmp_path):
    found = adapters.find(_address_book(tmp_path))
    assert found is not None and found.NAME == "ios-contacts"


def test_registry_find_by_content_not_by_name(tmp_path):
    """A Finder/iTunes backup stores the file under its hashed name, without an extension."""
    found = adapters.find(_address_book(tmp_path, "31bb7ba8914766d4ba40d6dfb6113c8b614be442"))
    assert found is not None and found.NAME == "ios-contacts"


def test_registry_find_still_returns_dawarich_and_takeout_for_theirs():
    assert adapters.find(DAWARICH).NAME == "dawarich"
    assert adapters.find(TAKEOUT).NAME == "google-takeout-location"


# -- sniff ------------------------------------------------------------------


def test_sniff_accepts_address_book(tmp_path):
    assert ios_contacts.sniff(_address_book(tmp_path)) is True


def test_sniff_rejects_dawarich_and_takeout_exports():
    assert ios_contacts.sniff(DAWARICH) is False
    assert ios_contacts.sniff(TAKEOUT) is False


def test_other_adapters_reject_the_address_book(tmp_path):
    p = _address_book(tmp_path)
    assert dawarich.sniff(p) is False and location.sniff(p) is False


def test_sniff_rejects_day_package(tmp_path):
    assert ios_contacts.sniff(_day_package(tmp_path)) is False


@pytest.mark.parametrize(
    "ddl",
    [
        "CREATE TABLE lines (seq INTEGER, hash TEXT);",  # the logbook's own index, for instance
        "CREATE TABLE ABPerson (ROWID INTEGER PRIMARY KEY, First TEXT);",  # half of it
        "CREATE TABLE ABMultiValue (record_id INTEGER, value TEXT);",
    ],
)
def test_sniff_rejects_unrelated_sqlite_files(tmp_path, ddl):
    p = tmp_path / "other.sqlite"
    con = sqlite3.connect(p)
    try:
        con.executescript(ddl)
    finally:
        con.close()
    assert ios_contacts.sniff(p) is False


@pytest.mark.parametrize("content", ["", "just words\n", "SQLite format 3\0 but not really a database"])
def test_sniff_rejects_non_sqlite_files(tmp_path, content):
    p = tmp_path / "file.sqlitedb"
    p.write_text(content, encoding="utf-8")
    assert ios_contacts.sniff(p) is False


def test_sniff_rejects_directory_and_missing_file(tmp_path):
    assert ios_contacts.sniff(tmp_path) is False
    assert ios_contacts.sniff(tmp_path / "nope.sqlitedb") is False


def test_sniff_and_run_never_touch_the_source(tmp_path):
    p = _address_book(tmp_path)
    before = p.read_bytes()
    assert ios_contacts.sniff(p) is True
    list(ios_contacts.run(p))
    assert p.read_bytes() == before
    assert sorted(q.name for q in tmp_path.iterdir()) == [p.name]  # no -journal, -wal, -shm


# -- run: envelope ------------------------------------------------------------


def test_run_yields_resolution_lines_at_the_import_time(tmp_path, no_dial_prefix):
    started = datetime.now(UTC).replace(microsecond=0)
    lines = list(ios_contacts.run(_address_book(tmp_path)))
    assert len(lines) == 8  # 9 values, one a duplicate email; Kari has none
    ats = {line["at"] for line in lines}
    assert len(ats) == 1
    at = datetime.strptime(ats.pop(), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    assert started <= at <= datetime.now(UTC)
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["end"] is None and line["tz"] is None
        assert line["source"] == "ios-contacts" and line["kind"] == "resolution" and line["tier"] == 2
        assert line["payload"]["schema"] == "resolution/v1"
        assert line["payload"]["method"] == "owner"


# -- run: entities --------------------------------------------------------------


def test_run_mints_one_uuid7_per_person_and_reuses_it_across_their_refs(tmp_path, no_dial_prefix):
    lines = _by_ref(list(ios_contacts.run(_address_book(tmp_path))))
    ines = {k: v for k, v in lines.items() if v["payload"]["extra"]["record_id"] == 1}
    assert set(ines) == {"phone:+4791234567", "email:ines@example.org"}
    ids = {v["payload"]["entity"]["id"] for v in ines.values()}
    assert len(ids) == 1
    assert uuid.UUID(ids.pop()).version == 7
    all_ids = {v["payload"]["entity"]["id"] for v in lines.values()}
    assert len(all_ids) == 4  # Ines, Ola, Nordmann AS, Kalle


def test_run_person_entity_and_display_name(tmp_path, no_dial_prefix):
    p = _by_ref(list(ios_contacts.run(_address_book(tmp_path))))["email:ola@example.org"]["payload"]
    assert p["entity"] == {"type": "person", "id": p["entity"]["id"], "registry": "logbook"}
    assert p["label"] == "Ola Nordmann"
    assert p["extra"]["organization"] == "Nordmann AS"  # a person at a company stays a person


def test_run_company_when_only_organization_is_set(tmp_path, no_dial_prefix):
    p = _by_ref(list(ios_contacts.run(_address_book(tmp_path))))["email:post@nordmann.example"]["payload"]
    assert p["entity"]["type"] == "company" and p["entity"]["registry"] == "logbook"
    assert p["label"] == "Nordmann AS"
    assert "organization" not in p["extra"]


def test_run_nickname_is_the_last_fallback_for_the_label(tmp_path, no_dial_prefix):
    p = _by_ref(list(ios_contacts.run(_address_book(tmp_path))))["phone:+4790000000"]["payload"]
    assert p["entity"]["type"] == "person" and p["label"] == "Kalle"


def test_run_person_without_refs_yields_nothing_and_is_counted(tmp_path, no_dial_prefix):
    counts: dict[str, int] = {}
    lines = list(ios_contacts.run(_address_book(tmp_path), counts=counts))
    assert 4 not in {line["payload"]["extra"]["record_id"] for line in lines}
    assert counts == {"skipped_no_ref": 1, "skipped_duplicate_ref": 1}


# -- run: refs and normalisation -----------------------------------------------------


def test_run_phone_strips_spaces_and_keeps_the_entered_value(tmp_path, no_dial_prefix):
    p = _by_ref(list(ios_contacts.run(_address_book(tmp_path))))["phone:+4791234567"]["payload"]
    assert p["ref"] == {"kind": "phone", "value": "+4791234567"}
    assert p["extra"]["entered"] == "+47 912 34 567"
    assert "unnormalised" not in p["extra"]


def test_run_phone_00_prefix_becomes_plus(tmp_path, no_dial_prefix):
    lines = _by_ref(list(ios_contacts.run(_address_book(tmp_path))))
    assert "phone:+4722334455" in lines
    assert lines["phone:+4722334455"]["payload"]["extra"]["entered"] == "0047-22-33-44-55"


def test_run_phone_without_country_code_is_kept_and_flagged(tmp_path, no_dial_prefix):
    p = _by_ref(list(ios_contacts.run(_address_book(tmp_path))))["phone:22334455"]["payload"]
    assert p["ref"]["value"] == "22334455"
    assert p["extra"]["unnormalised"] is True
    assert p["extra"]["entered"] == "(22) 33.44.55"


def test_run_phone_without_country_code_takes_logbook_dial_prefix(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGBOOK_DIAL_PREFIX", "47")
    lines = _by_ref(list(ios_contacts.run(_address_book(tmp_path))))
    assert "phone:22334455" not in lines
    p = lines["phone:+4722334455"]["payload"]  # 0047… and (22)… now meet on the same ref
    assert "unnormalised" not in p["extra"]
    assert "phone:+4791234567" in lines  # a number that already had one is untouched


def _one_phone(tmp_path: Path, entered: str) -> dict:
    p = tmp_path / "AddressBook.sqlitedb"
    con = sqlite3.connect(p)
    try:
        con.executescript(DDL)
        con.execute("INSERT INTO ABPerson VALUES (1,'Ines','Nordmann',NULL,NULL,NULL,NULL,NULL)")
        con.execute("INSERT INTO ABMultiValue VALUES (1,1,?,0,'mobile',?)", (PHONE, entered))
        con.commit()
    finally:
        con.close()
    (line,) = ios_contacts.run(p)
    return line["payload"]


def test_run_dial_prefix_strips_one_national_trunk_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGBOOK_DIAL_PREFIX", "44")
    p = _one_phone(tmp_path, "07700 900123")
    assert p["ref"]["value"] == "+447700900123" and p["raw_id"] == "phone:+447700900123"
    assert "unnormalised" not in p["extra"]
    assert p["extra"]["entered"] == "07700 900123"


def test_run_dial_prefix_strips_only_one_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGBOOK_DIAL_PREFIX", "39")
    assert _one_phone(tmp_path, "06 1234 5678")["ref"]["value"] == "+39612345678"


def test_run_number_already_starting_with_the_prefix_is_kept_and_flagged(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGBOOK_DIAL_PREFIX", "44")
    p = _one_phone(tmp_path, "44 7700 900123")
    assert p["ref"]["value"] == "447700900123" and p["raw_id"] == "phone:447700900123"
    assert p["extra"]["unnormalised"] is True


def test_run_email_is_lower_cased_trimmed_and_deduped_within_a_run(tmp_path, no_dial_prefix):
    lines = list(ios_contacts.run(_address_book(tmp_path)))
    emails = [line for line in lines if line["payload"]["ref"]["kind"] == "email"]
    assert [e["payload"]["ref"]["value"] for e in emails] == [
        "ines@example.org",
        "ola@example.org",
        "post@nordmann.example",
    ]
    assert emails[0]["payload"]["extra"]["entered"] == "Ines@Example.org"  # the first one wins


def test_run_raw_id_is_kind_and_normalised_value(tmp_path, no_dial_prefix):
    for line in ios_contacts.run(_address_book(tmp_path)):
        ref = line["payload"]["ref"]
        assert line["payload"]["raw_id"] == f"{ref['kind']}:{ref['value']}"


def test_run_extra_keeps_the_source_ids_labels_and_dates(tmp_path, no_dial_prefix):
    p = _by_ref(list(ios_contacts.run(_address_book(tmp_path))))["phone:+4791234567"]["payload"]
    assert p["extra"]["record_id"] == 1 and p["extra"]["value_id"] == 10
    assert p["extra"]["label"] == "mobile"
    assert p["extra"]["created"] == datetime.fromtimestamp(APPLE_EPOCH + 700_000_000, UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    assert p["extra"]["modified"] == "2025-09-19T18:40:00Z"


def test_run_missing_modification_date_is_omitted(tmp_path, no_dial_prefix):
    p = tmp_path / "AddressBook.sqlitedb"
    con = sqlite3.connect(p)
    try:
        con.executescript(DDL)
        con.execute("INSERT INTO ABPerson VALUES (1,'Ines','Nordmann',NULL,NULL,NULL,700000000,NULL)")
        con.execute("INSERT INTO ABMultiValue VALUES (1,1,?,0,'mobile','+47 912 34 567')", (PHONE,))
        con.commit()
    finally:
        con.close()
    (line,) = ios_contacts.run(p)
    assert "modified" not in line["payload"]["extra"]
    assert line["payload"]["extra"]["label"] == "mobile"  # a text label without the label table


def test_run_labels_lose_the_apple_wrapper_and_custom_labels_stay(tmp_path, no_dial_prefix):
    lines = _by_ref(list(ios_contacts.run(_address_book(tmp_path))))
    assert lines["phone:+4722334455"]["payload"]["extra"]["label"] == "mobile"
    assert lines["phone:22334455"]["payload"]["extra"]["label"] == "work"
    assert lines["email:ines@example.org"]["payload"]["extra"]["label"] == "home"


# -- through the log: append, dedupe on re-run, CLI -----------------------------------


def test_run_lines_append_and_re_running_appends_nothing(tmp_path, no_dial_prefix):
    p = _address_book(tmp_path)
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    assert lb.append_many(ios_contacts.run(p)) == 8
    assert lb.append_many(ios_contacts.run(p)) == 0  # new uuids, same refs → deduped on raw_id
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 8
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)
        assert line["tz"] == "Europe/Oslo"


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


def test_cli_add_reports_lines_and_the_person_without_refs(tmp_path):
    run = _cli(tmp_path)
    run("init", str(tmp_path / "lb"), "--timezone", "Europe/Oslo")
    p = _address_book(tmp_path)
    out = run("add", str(p)).stdout
    assert "added 8 lines from ios-contacts" in out
    assert "skipped 1 with a phone or email already seen, 1 without a phone or email" in out
    assert "added 0 lines from ios-contacts" in run("add", str(p)).stdout
    assert "valid — 8 lines" in run("verify").stdout


# -- property: every emitted line is a valid resolution/v1 observation -------------------

UUID7 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def _rfc_rules(line: dict) -> None:
    assert set(line) == ENVELOPE
    assert line["kind"] == "resolution" and line["tier"] == 2 and line["end"] is None
    assert line["source"] == "ios-contacts"
    assert line["at"].endswith("Z") and len(line["at"]) == 20
    p = line["payload"]
    assert set(p) - {"label"} == {"schema", "ref", "entity", "method", "raw_id", "extra"}
    assert p["schema"] == "resolution/v1"
    assert set(p["ref"]) == {"kind", "value"} and p["ref"]["kind"] in {"phone", "email"}
    value = p["ref"]["value"]
    assert isinstance(value, str) and value and value == value.strip()
    if p["ref"]["kind"] == "email":
        assert value == value.lower()
    elif not p["extra"].get("unnormalised"):
        assert re.fullmatch(r"\+[0-9]+", value)
    assert set(p["entity"]) == {"type", "id", "registry"}
    assert p["entity"]["type"] in {"person", "company"} and p["entity"]["registry"] == "logbook"
    assert UUID7.match(p["entity"]["id"])
    if "label" in p:
        assert isinstance(p["label"], str) and p["label"]
    assert p["method"] == "owner"
    assert p["raw_id"] == f"{p['ref']['kind']}:{value}"
    assert isinstance(p["extra"], dict) and isinstance(p["extra"]["record_id"], int)
    json.dumps(line, allow_nan=False)


_name = st.one_of(st.none(), st.text(max_size=12))
_date = st.one_of(st.none(), st.integers(-(2**40), 2**40), st.floats(allow_nan=False, allow_infinity=False))
_person = st.tuples(_name, _name, _name, _name, _date, _date)
_digits = st.text(alphabet="0123456789", min_size=0, max_size=14)
_phone = st.one_of(
    st.tuples(st.sampled_from(["", "+", "00", "0"]), _digits).map(lambda t: t[0] + t[1]),
    st.text(alphabet="0123456789 +-.()", max_size=16),
    st.text(max_size=10),
    st.none(),
)
_email = st.one_of(st.emails().map(lambda e: e[:40]), st.text(max_size=10), st.none())
_value = st.one_of(
    st.tuples(st.just(PHONE), _phone),
    st.tuples(st.just(EMAIL), _email),
    st.tuples(st.integers(0, 30), st.text(max_size=8)),  # other properties are not ours
)
_book = st.lists(st.tuples(_person, st.lists(st.tuples(_value, _name), max_size=4)), max_size=6)
_prefix = st.sampled_from([None, "", "41", "47"])


@settings(max_examples=40, deadline=None)
@given(_book, _prefix)
def test_any_address_book_yields_only_valid_lines(tmp_path_factory, book, prefix):
    env = {k: v for k, v in os.environ.items() if k != "LOGBOOK_DIAL_PREFIX"}
    if prefix is not None:
        env["LOGBOOK_DIAL_PREFIX"] = prefix
    p = tmp_path_factory.mktemp("book") / "AddressBook.sqlitedb"
    con = sqlite3.connect(p)
    try:
        con.executescript(DDL)
        uid = 0
        for rowid, (person, values) in enumerate(book, start=1):
            con.execute("INSERT INTO ABPerson VALUES (?,?,?,NULL,?,?,?,?)", (rowid, *person))
            for (prop, value), label in values:
                uid += 1
                con.execute("INSERT INTO ABMultiValue VALUES (?,?,?,0,?,?)", (uid, rowid, prop, label, value))
        con.commit()
    finally:
        con.close()
    counts: dict[str, int] = {}
    with mock.patch.dict(os.environ, env, clear=True):
        lines = list(ios_contacts.run(p, counts=counts))
    for line in lines:
        _rfc_rules(line)
    raw_ids = [line["payload"]["raw_id"] for line in lines]
    assert len(raw_ids) == len(set(raw_ids))
    persons_with_lines = {line["payload"]["extra"]["record_id"] for line in lines}
    assert len(persons_with_lines) + counts.get("skipped_no_ref", 0) == len(book)
    lb = Logbook.init(tmp_path_factory.mktemp("lb"), "UTC")
    assert lb.append_many(lines) == len(lines)
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)
