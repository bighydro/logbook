"""iOS Calendar.sqlitedb → event/v1 (RFC 0009): one line per stored entry, occurrences never expanded."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import zoneinfo
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters
from logbook.adapters import dawarich, ios_calendar, ios_contacts, whatsapp
from logbook.adapters.takeout import location
from logbook.export import write_day_package
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
DAWARICH = ROOT / "tests" / "fixtures" / "dawarich" / "export.json"
TAKEOUT = ROOT / "tests" / "fixtures" / "takeout" / "Records.json"
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
APPLE_EPOCH = 978_307_200  # 2001-01-01T00:00:00Z, the zero of start_date/end_date/last_modified

DDL = """
CREATE TABLE Calendar (ROWID INTEGER PRIMARY KEY, title TEXT, type INTEGER);
CREATE TABLE CalendarItem (
    ROWID INTEGER PRIMARY KEY, unique_identifier TEXT, summary TEXT, description TEXT,
    start_date REAL, end_date REAL, start_tz TEXT, all_day INTEGER, calendar_id INTEGER,
    location_id INTEGER, status INTEGER, last_modified REAL, has_recurrences INTEGER,
    orig_item_id INTEGER, orig_date REAL
);
CREATE TABLE Participant (
    ROWID INTEGER PRIMARY KEY, entity_type INTEGER, owner_id INTEGER, email TEXT, name TEXT,
    status INTEGER, role INTEGER, type INTEGER
);
CREATE TABLE Location (ROWID INTEGER PRIMARY KEY, title TEXT, address TEXT, latitude REAL, longitude REAL);
CREATE TABLE Recurrence (
    ROWID INTEGER PRIMARY KEY, owner_id INTEGER, frequency INTEGER, interval INTEGER, count INTEGER,
    end_date REAL, by_day TEXT, by_month_day TEXT, by_month TEXT, week_start INTEGER
);
"""


def _apple(stamp: str) -> int:
    return int(datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()) - APPLE_EPOCH


SURVEY = "7E0C2D4A-9B1F-4C7E-8A2B-5D3E1F6A9C0B"
AGM = "A1F3C6D9-2B4E-4F7A-9C1D-3E5B7A9C2D4F"
TRAINING = "C4D7E1A2-5B8F-4A3C-9D6E-1F2A3B4C5D6E"
CANCELLED = "D9E2F5A8-1C4B-4E7D-8A3F-6B9C2D5E8F1A"
DINNER = "E2F5A8B1-4D7C-4B1E-9F6A-3C8D1E4F7A2B"
MODIFIED = "2026-02-27T16:05:00Z"

# (ROWID, title, type) — synthetic
CALENDARS = [(1, "Personal", 0), (2, "Sailing club", 1)]

# (ROWID, unique_identifier, summary, description, start_date, end_date, start_tz, all_day,
#  calendar_id, location_id, status, last_modified, has_recurrences, orig_item_id, orig_date)
ITEMS = [
    (  # a timed event with a place, an organizer and two attendees
        1,
        SURVEY,
        "Boat survey — Tromsø marina",
        "bring the papers",
        _apple("2026-03-03T08:30:00Z"),
        _apple("2026-03-03T09:15:00Z"),
        "Europe/Oslo",
        0,
        1,
        1,
        1,
        _apple(MODIFIED),
        0,
        None,
        None,
    ),
    (  # an all-day event, floating (no zone): the store keeps the day at UTC midnight
        2,
        AGM,
        "Sailing club AGM",
        None,
        _apple("2026-03-07T00:00:00Z"),
        _apple("2026-03-08T00:00:00Z"),
        None,
        1,
        2,
        None,
        1,
        _apple("2026-02-20T09:00:00Z"),
        0,
        None,
        None,
    ),
    (  # a recurring master: every other week on Tuesday and Thursday, ten times
        3,
        TRAINING,
        "Crew training",
        None,
        _apple("2026-03-03T17:00:00Z"),
        _apple("2026-03-03T18:30:00Z"),
        "Europe/Oslo",
        0,
        2,
        None,
        1,
        _apple("2026-02-21T12:00:00Z"),
        1,
        None,
        None,
    ),
    (  # one occurrence of it, moved an hour later; the store gives it the master's uid
        4,
        TRAINING,
        "Crew training (moved)",
        None,
        _apple("2026-03-17T18:00:00Z"),
        _apple("2026-03-17T19:30:00Z"),
        "Europe/Oslo",
        0,
        2,
        None,
        1,
        _apple("2026-03-10T08:00:00Z"),
        0,
        3,
        _apple("2026-03-17T17:00:00Z"),
    ),
    (  # cancelled, no end, one attendee whose status code is not one we know
        5,
        CANCELLED,
        "Regatta briefing",
        None,
        _apple("2026-03-05T16:00:00Z"),
        None,
        "Europe/Oslo",
        0,
        2,
        None,
        3,
        _apple("2026-03-04T20:00:00Z"),
        0,
        None,
        None,
    ),
    (  # the store's placeholder date
        6,
        "F1A2B3C4-0000-4000-8000-000000000006",
        "placeholder",
        None,
        _apple("1601-01-01T00:00:00Z"),
        None,
        None,
        0,
        1,
        None,
        0,
        _apple("2026-01-01T00:00:00Z"),
        0,
        None,
        None,
    ),
    (  # no unique identifier: keyed by row id
        7,
        None,
        "Dentist",
        None,
        _apple("2026-03-10T10:00:00Z"),
        _apple("2026-03-10T10:30:00Z"),
        "Europe/Oslo",
        0,
        1,
        None,
        1,
        _apple("2026-03-01T11:00:00Z"),
        0,
        None,
        None,
    ),
    (  # a place with coordinates and an address but no title
        8,
        DINNER,
        "Dinner",
        None,
        _apple("2026-03-12T18:00:00Z"),
        _apple("2026-03-12T20:00:00Z"),
        "Europe/Oslo",
        0,
        1,
        2,
        1,
        _apple("2026-03-02T11:00:00Z"),
        0,
        None,
        None,
    ),
    (
        9,
        "F1A2B3C4-0000-4000-8000-000000000009",
        "no start",
        None,
        None,
        None,
        None,
        0,
        1,
        None,
        1,
        0,
        0,
        None,
        None,
    ),
    (
        10,
        "F1A2B3C4-0000-4000-8000-000000000010",
        "too early",
        None,
        100.0,
        200.0,
        None,
        0,
        1,
        None,
        1,
        0,
        0,
        None,
        None,
    ),
]
# (ROWID, entity_type, owner_id, email, name, status, role, type)
PARTICIPANTS = [
    (1, 2, 1, "Kari@Example.org", "Kari Nordmann", 2, 0, 1),  # entity_type 2: the organizer
    (2, 1, 1, "Ola@Example.org", "Ola Nordmann", 2, 1, 1),  # accepted
    (3, 1, 1, "ines@example.org", None, 3, 2, 1),  # declined, no name
    (4, 1, 5, "kalle@example.org", "Kalle", 99, 1, 1),  # a status we do not know
    (5, 1, 5, None, "nobody", 2, 1, 1),  # no email: not a ref
]
# (ROWID, title, address, latitude, longitude)
LOCATIONS = [
    (1, "Tromsø småbåthavn", "Kaigata 1, Tromsø", None, None),
    (2, None, "Storgata 1, Oslo", 59.913, 10.752),
]
# (ROWID, owner_id, frequency, interval, count, end_date, by_day, by_month_day, by_month, week_start)
RECURRENCES = [(1, 3, 2, 2, 10, None, "3,5", None, None, 2)]


def _calendar(tmp_path: Path, name: str = "Calendar.sqlitedb") -> Path:
    p = tmp_path / name
    con = sqlite3.connect(p)
    try:
        con.executescript(DDL)
        con.executemany("INSERT INTO Calendar VALUES (?,?,?)", CALENDARS)
        con.executemany("INSERT INTO CalendarItem VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ITEMS)
        con.executemany("INSERT INTO Participant VALUES (?,?,?,?,?,?,?,?)", PARTICIPANTS)
        con.executemany("INSERT INTO Location VALUES (?,?,?,?,?)", LOCATIONS)
        con.executemany("INSERT INTO Recurrence VALUES (?,?,?,?,?,?,?,?,?,?)", RECURRENCES)
        con.commit()
    finally:
        con.close()
    return p


def _by_row(lines: list[dict]) -> dict[int, dict]:
    """Lines keyed by the CalendarItem.ROWID they came from (the fixture's titles are unique)."""
    titles = {item[2]: item[0] for item in ITEMS}
    return {titles[line["payload"]["title"]]: line for line in lines}


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


# -- registry ---------------------------------------------------------------


def test_registry_lists_ios_calendar():
    assert "ios-calendar" in [a.NAME for a in adapters.all_adapters()]


def test_registry_find_returns_ios_calendar_for_a_calendar_store(tmp_path):
    found = adapters.find(_calendar(tmp_path))
    assert found is not None and found.NAME == "ios-calendar"


def test_registry_find_by_content_not_by_name(tmp_path):
    """A Finder/iTunes backup stores the file under its hashed name, without an extension."""
    found = adapters.find(_calendar(tmp_path, "2041457d5fe04d39d0ab481178355df6781e6858"))
    assert found is not None and found.NAME == "ios-calendar"


# -- sniff ------------------------------------------------------------------


def test_sniff_accepts_calendar_store(tmp_path):
    assert ios_calendar.sniff(_calendar(tmp_path)) is True


def test_sniff_rejects_other_exports(tmp_path):
    assert ios_calendar.sniff(DAWARICH) is False
    assert ios_calendar.sniff(TAKEOUT) is False


def test_sniff_rejects_day_package(tmp_path):
    assert ios_calendar.sniff(_day_package(tmp_path)) is False


def test_other_adapters_reject_the_calendar_store(tmp_path):
    p = _calendar(tmp_path)
    assert dawarich.sniff(p) is False and location.sniff(p) is False
    assert ios_contacts.sniff(p) is False and whatsapp.sniff(p) is False


@pytest.mark.parametrize(
    "ddl",
    [
        "CREATE TABLE lines (seq INTEGER, hash TEXT);",
        "CREATE TABLE CalendarItem (ROWID INTEGER PRIMARY KEY, summary TEXT);",  # half of it
        "CREATE TABLE Calendar (ROWID INTEGER PRIMARY KEY, title TEXT);",
        "CREATE TABLE ABPerson (ROWID INTEGER PRIMARY KEY); CREATE TABLE ABMultiValue (UID INTEGER);",
        "CREATE TABLE ZWACHATSESSION (Z_PK INTEGER PRIMARY KEY); CREATE TABLE ZWAMESSAGE (Z_PK INTEGER);",
        "CREATE TABLE message (ROWID INTEGER PRIMARY KEY, text TEXT); CREATE TABLE handle (ROWID INTEGER);",
    ],
)
def test_sniff_rejects_unrelated_sqlite_files(tmp_path, ddl):
    p = tmp_path / "other.sqlite"
    con = sqlite3.connect(p)
    try:
        con.executescript(ddl)
    finally:
        con.close()
    assert ios_calendar.sniff(p) is False


@pytest.mark.parametrize("content", ["", "just words\n", "SQLite format 3\0 but not really a database"])
def test_sniff_rejects_non_sqlite_files(tmp_path, content):
    p = tmp_path / "Calendar.sqlitedb"
    p.write_text(content, encoding="utf-8")
    assert ios_calendar.sniff(p) is False


def test_sniff_rejects_directory_and_missing_file(tmp_path):
    assert ios_calendar.sniff(tmp_path) is False
    assert ios_calendar.sniff(tmp_path / "nope.sqlitedb") is False


def test_sniff_and_run_never_touch_the_source(tmp_path):
    p = _calendar(tmp_path)
    before = p.read_bytes()
    assert ios_calendar.sniff(p) is True
    list(ios_calendar.run(p))
    assert p.read_bytes() == before
    assert sorted(q.name for q in tmp_path.iterdir()) == [p.name]  # no -journal, -wal, -shm


# -- run: envelope ------------------------------------------------------------


def test_run_yields_event_lines_with_the_source_span(tmp_path):
    lines = list(ios_calendar.run(_calendar(tmp_path)))
    assert len(lines) == 7
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["source"] == "ios-calendar" and line["kind"] == "event" and line["tier"] == 1
        assert line["payload"]["schema"] == "event/v1"
    survey = _by_row(lines)[1]
    assert survey["at"] == "2026-03-03T08:30:00Z" and survey["end"] == "2026-03-03T09:15:00Z"
    assert survey["tz"] == "Europe/Oslo"


def test_run_streams_in_row_order(tmp_path):
    assert list(_by_row(list(ios_calendar.run(_calendar(tmp_path))))) == [1, 2, 3, 4, 5, 7, 8]


def test_run_honours_since(tmp_path):
    p = _calendar(tmp_path)
    lines = list(ios_calendar.run(p, since="2026-03-07T00:00:00Z"))
    assert list(_by_row(lines)) == [
        2,
        4,
        7,
        8,
    ]  # the floating all-day event is at 2026-03-07T00:00Z as stored
    lines = list(ios_calendar.run(p, since="2026-03-07T00:00:00Z", timezone="Europe/Oslo"))
    assert list(_by_row(lines)) == [4, 7, 8]  # in Oslo it is at 2026-03-06T23:00Z, before the cut


def test_run_skips_and_counts_placeholder_dates_and_rows_without_a_start(tmp_path):
    counts: dict[str, int] = {}
    lines = list(ios_calendar.run(_calendar(tmp_path), counts=counts))
    assert {6, 9, 10}.isdisjoint(_by_row(lines))
    assert counts == {"skipped_placeholder_date": 2, "skipped_no_start": 1, "no_unique_identifier": 1}


# -- run: the timed event -----------------------------------------------------------


def test_run_timed_event_payload(tmp_path):
    p = _by_row(list(ios_calendar.run(_calendar(tmp_path))))[1]["payload"]
    assert p["raw_id"] == f"{SURVEY}@{MODIFIED}"
    assert p["modified_at"] == MODIFIED
    assert p["title"] == "Boat survey — Tromsø marina"
    assert p["notes"] == "bring the papers"
    assert p["calendar"] == {"id": "1", "name": "Personal"}
    assert p["all_day"] is False
    assert p["status"] == "confirmed"
    assert "recurrence" not in p and "recurrence_of" not in p


def test_run_location_title_wins_and_the_address_stays_under_extra(tmp_path):
    p = _by_row(list(ios_calendar.run(_calendar(tmp_path))))[1]["payload"]
    assert p["location"] == "Tromsø småbåthavn"
    assert p["extra"]["location"] == {"address": "Kaigata 1, Tromsø"}


def test_run_location_address_when_there_is_no_title_with_coordinates_under_extra(tmp_path):
    p = _by_row(list(ios_calendar.run(_calendar(tmp_path))))[8]["payload"]
    assert p["location"] == "Storgata 1, Oslo"
    assert p["extra"]["location"] == {"latitude": 59.913, "longitude": 10.752}


def test_run_organizer_and_attendees_are_source_native_refs(tmp_path):
    p = _by_row(list(ios_calendar.run(_calendar(tmp_path))))[1]["payload"]
    assert p["organizer"] == {"kind": "email", "value": "kari@example.org"}
    assert p["attendees"] == [
        {
            "ref": {"kind": "email", "value": "ola@example.org"},
            "name": "Ola Nordmann",
            "response": "accepted",
        },
        {"ref": {"kind": "email", "value": "ines@example.org"}, "response": "declined"},
    ]
    assert "organizer_name" not in p


def test_run_organizer_by_chair_role(tmp_path):
    p = _one_item(tmp_path, participants=[(1, 1, 1, "kari@example.org", "Kari", 2, 3, 1)])["payload"]
    assert p["organizer"] == {"kind": "email", "value": "kari@example.org"}
    assert "attendees" not in p


def test_run_unknown_participant_status_is_none_with_the_code_kept(tmp_path):
    p = _by_row(list(ios_calendar.run(_calendar(tmp_path))))[5]["payload"]
    assert p["attendees"] == [
        {
            "ref": {"kind": "email", "value": "kalle@example.org"},
            "name": "Kalle",
            "response": "none",
            "extra": {"status_code": 99},
        }
    ]


def test_run_cancelled_event_is_a_line_with_no_end(tmp_path):
    line = _by_row(list(ios_calendar.run(_calendar(tmp_path))))[5]
    assert line["end"] is None
    assert line["payload"]["status"] == "cancelled"


def test_run_unknown_status_code_is_kept_under_extra(tmp_path):
    p = _one_item(tmp_path, status=7)["payload"]
    assert "status" not in p and p["extra"]["status_code"] == 7


def test_run_status_none_is_omitted(tmp_path):
    p = _one_item(tmp_path, status=0)["payload"]
    assert "status" not in p and "extra" not in p


# -- run: all-day ---------------------------------------------------------------


def test_run_floating_all_day_event_without_the_record_timezone_stays_at_utc_midnight(tmp_path):
    line = _by_row(list(ios_calendar.run(_calendar(tmp_path))))[2]
    assert line["at"] == "2026-03-07T00:00:00Z" and line["end"] == "2026-03-08T00:00:00Z"
    assert line["tz"] is None
    assert line["payload"]["all_day"] is True


def test_run_floating_all_day_event_takes_local_midnight_in_the_record_timezone(tmp_path):
    line = _by_row(list(ios_calendar.run(_calendar(tmp_path), timezone="Europe/Oslo")))[2]
    assert line["at"] == "2026-03-06T23:00:00Z" and line["end"] == "2026-03-07T23:00:00Z"
    assert line["tz"] is None  # the record's own
    assert line["payload"]["all_day"] is True


def test_run_all_day_event_with_its_own_zone(tmp_path):
    line = _one_item(
        tmp_path,
        start=_apple("2026-07-01T04:00:00Z"),  # local midnight of 2026-07-01 in New York (EDT)
        end=_apple("2026-07-02T04:00:00Z"),
        start_tz="America/New_York",
        all_day=1,
    )
    assert line["tz"] == "America/New_York"
    assert line["at"] == "2026-07-01T04:00:00Z" and line["end"] == "2026-07-02T04:00:00Z"


def test_run_all_day_event_end_is_the_next_midnight_even_when_the_store_has_none(tmp_path):
    line = _one_item(tmp_path, start=_apple("2026-03-07T00:00:00Z"), end=None, start_tz=None, all_day=1)
    assert line["at"] == "2026-03-07T00:00:00Z" and line["end"] == "2026-03-08T00:00:00Z"
    line = _one_item(tmp_path, start=_apple("2026-03-06T23:00:00Z"), end=None, all_day=1)  # Oslo midnight
    assert line["at"] == "2026-03-06T23:00:00Z" and line["end"] == "2026-03-07T23:00:00Z"


# -- run: zones -------------------------------------------------------------------


def test_run_unknown_zone_falls_back_to_the_record_and_keeps_the_text(tmp_path):
    line = _one_item(tmp_path, start_tz="_float")
    assert line["tz"] is None and line["payload"]["extra"]["start_tz"] == "_float"
    line = _one_item(tmp_path, start_tz="Mars/Olympus")
    assert line["tz"] is None and line["payload"]["extra"]["start_tz"] == "Mars/Olympus"


# -- run: recurrence ----------------------------------------------------------------


def test_run_master_carries_the_rule_as_rrule_text(tmp_path):
    p = _by_row(list(ios_calendar.run(_calendar(tmp_path))))[3]["payload"]
    assert p["recurrence"] == "FREQ=WEEKLY;INTERVAL=2;COUNT=10;BYDAY=TU,TH"
    assert "recurrence_of" not in p
    assert p["raw_id"] == f"{TRAINING}@2026-02-21T12:00:00Z"


def test_run_exception_row_points_at_the_master_bare_uid(tmp_path):
    p = _by_row(list(ios_calendar.run(_calendar(tmp_path))))[4]["payload"]
    assert p["recurrence_of"] == TRAINING
    assert "recurrence" not in p
    assert p["extra"]["original_date"] == "2026-03-17T17:00:00Z"
    assert p["raw_id"] == f"{TRAINING}/2026-03-17T17:00:00Z@2026-03-10T08:00:00Z"  # not the master's key


def test_run_exception_row_with_its_own_uid_keeps_it(tmp_path):
    lines = _two_items(
        tmp_path,
        master=(1, "M-1", "m", 1, None),
        exception=(2, "X-1", "x", 0, 1),
    )
    assert lines[1]["payload"]["recurrence_of"] == "M-1"
    assert lines[1]["payload"]["raw_id"].startswith("X-1@")


def test_run_exception_of_a_master_without_uid_points_at_its_row_id(tmp_path):
    lines = _two_items(tmp_path, master=(1, None, "m", 1, None), exception=(2, "X-1", "x", 0, 1))
    assert lines[0]["payload"]["raw_id"].startswith("1@")
    assert lines[1]["payload"]["recurrence_of"] == "1"


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        ((1, 1, None, None, None, None), "FREQ=DAILY"),
        (
            (2, 1, None, _apple("2026-12-31T23:00:00Z"), "2", None),
            "FREQ=WEEKLY;UNTIL=20261231T230000Z;BYDAY=MO",
        ),
        ((3, 3, 5, None, None, "1,15"), "FREQ=MONTHLY;INTERVAL=3;COUNT=5;BYMONTHDAY=1,15"),
        ((4, 1, None, None, None, "-1"), "FREQ=YEARLY;BYMONTHDAY=-1"),
        ((2, 1, None, None, "MO,WE", None), "FREQ=WEEKLY;BYDAY=MO,WE"),
        ((2, 1, 3, _apple("2026-12-31T23:00:00Z"), None, None), "FREQ=WEEKLY;COUNT=3"),  # count wins
    ],
)
def test_run_rrule_rendering(tmp_path, rule, expected):
    line = _one_item(tmp_path, has_recurrences=1, recurrence=rule)
    assert line["payload"]["recurrence"] == expected


def test_run_unknown_frequency_gives_no_rule_and_keeps_the_row(tmp_path):
    line = _one_item(tmp_path, has_recurrences=1, recurrence=(9, 1, None, None, "3", None))
    assert "recurrence" not in line["payload"]
    assert line["payload"]["extra"]["recurrence"] == {"frequency": 9, "interval": 1, "by_day": "3"}


def test_run_unparseable_by_day_is_left_out_of_the_rule_and_kept(tmp_path):
    line = _one_item(tmp_path, has_recurrences=1, recurrence=(2, 1, None, None, "next tuesday", None))
    assert line["payload"]["recurrence"] == "FREQ=WEEKLY"
    assert line["payload"]["extra"]["recurrence"] == {"by_day": "next tuesday"}


# -- run: defensive about the schema ------------------------------------------------------


def test_run_with_the_minimal_columns_only(tmp_path):
    p = tmp_path / "Calendar.sqlitedb"
    con = sqlite3.connect(p)
    try:
        con.executescript(
            "CREATE TABLE Calendar (ROWID INTEGER PRIMARY KEY, title TEXT);"
            "CREATE TABLE CalendarItem"
            " (ROWID INTEGER PRIMARY KEY, summary TEXT, start_date REAL, end_date REAL);"
        )
        con.execute("INSERT INTO Calendar VALUES (1, 'Personal')")
        con.execute(
            "INSERT INTO CalendarItem VALUES (1, 'Dentist', ?, ?)", (_apple("2026-03-10T10:00:00Z"), None)
        )
        con.commit()
    finally:
        con.close()
    counts: dict[str, int] = {}
    (line,) = ios_calendar.run(p, counts=counts)
    assert line["at"] == "2026-03-10T10:00:00Z" and line["end"] is None and line["tz"] is None
    assert line["payload"] == {"schema": "event/v1", "raw_id": "1", "title": "Dentist", "all_day": False}
    assert counts == {"no_unique_identifier": 1}


def test_run_ignores_a_raw_id_collision_only_through_the_log(tmp_path):
    """Two rows with the same uid and modified time are the store's problem; the log keeps the first."""
    lines = _two_items(tmp_path, master=(1, "M-1", "a", 0, None), exception=(2, "M-1", "b", 0, None))
    assert [line["payload"]["raw_id"] for line in lines] == ["M-1@2026-03-01T11:00:00Z"] * 2
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    assert lb.append_many(lines) == 1


def _one_item(
    tmp_path: Path,
    *,
    start: float | None = None,
    end: float | None = None,
    start_tz: str | None = "Europe/Oslo",
    all_day: int = 0,
    status: int | None = 1,
    has_recurrences: int = 0,
    recurrence: tuple | None = None,
    participants: list[tuple] | None = None,
) -> dict:
    p = tmp_path / "Calendar.sqlitedb"
    if p.exists():
        p.unlink()
    con = sqlite3.connect(p)
    try:
        con.executescript(DDL)
        con.execute("INSERT INTO Calendar VALUES (1, 'Personal', 0)")
        con.execute(
            "INSERT INTO CalendarItem"
            " VALUES (1, 'U-1', 'one', NULL, ?, ?, ?, ?, 1, NULL, ?, ?, ?, NULL, NULL)",
            (
                start if start is not None else _apple("2026-03-10T10:00:00Z"),
                end if end is not None else (None if all_day else _apple("2026-03-10T10:30:00Z")),
                start_tz,
                all_day,
                status,
                _apple("2026-03-01T11:00:00Z"),
                has_recurrences,
            ),
        )
        if recurrence is not None:
            con.execute("INSERT INTO Recurrence VALUES (1, 1, ?, ?, ?, ?, ?, ?, NULL, NULL)", recurrence)
        for row in participants or []:
            con.execute("INSERT INTO Participant VALUES (?,?,?,?,?,?,?,?)", row)
        con.commit()
    finally:
        con.close()
    (line,) = ios_calendar.run(p)
    return line


def _two_items(tmp_path: Path, *, master: tuple, exception: tuple) -> list[dict]:
    """Two rows (ROWID, uid, summary, has_recurrences, orig_item_id); the second may point at the first."""
    p = tmp_path / "Calendar.sqlitedb"
    con = sqlite3.connect(p)
    try:
        con.executescript(DDL)
        con.execute("INSERT INTO Calendar VALUES (1, 'Personal', 0)")
        for rowid, uid, summary, has_recurrences, orig in (master, exception):
            con.execute(
                "INSERT INTO CalendarItem"
                " VALUES (?, ?, ?, NULL, ?, ?, 'Europe/Oslo', 0, 1, NULL, 1, ?, ?, ?, ?)",
                (
                    rowid,
                    uid,
                    summary,
                    _apple("2026-03-10T10:00:00Z"),
                    _apple("2026-03-10T10:30:00Z"),
                    _apple("2026-03-01T11:00:00Z"),
                    has_recurrences,
                    orig,
                    _apple("2026-03-10T10:00:00Z") if orig else None,
                ),
            )
        con.commit()
    finally:
        con.close()
    return list(ios_calendar.run(p))


# -- through the log: append, dedupe on re-run, CLI -----------------------------------


def test_run_lines_append_and_re_running_appends_nothing(tmp_path):
    p = _calendar(tmp_path)
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    assert lb.append_many(ios_calendar.run(p, timezone="Europe/Oslo")) == 7
    assert lb.append_many(ios_calendar.run(p, timezone="Europe/Oslo")) == 0
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 7
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)
        assert line["tz"] == "Europe/Oslo"


def _cli(tmp_path):
    env = {**os.environ, "LOGBOOK_HOME": str(tmp_path / "lb"), "PYTHONPATH": str(ROOT)}

    def run(*a):
        return subprocess.run(
            [sys.executable, "-m", "logbook.cli", *a],
            env=env,
            capture_output=True,
            encoding="utf-8",
            check=True,
        )

    return run


def test_cli_add_reports_lines_and_skips_and_places_all_day_events_in_the_record_zone(tmp_path):
    run = _cli(tmp_path)
    run("init", str(tmp_path / "lb"), "--timezone", "Europe/Oslo")
    p = _calendar(tmp_path)
    out = run("add", str(p)).stdout
    assert "added 7 lines from ios-calendar" in out
    assert "skipped 2 with placeholder dates, 1 without a start" in out
    assert "also 1 without a unique identifier, keyed by row id" in out
    assert "added 0 lines from ios-calendar" in run("add", str(p)).stdout
    assert "valid — 7 lines" in run("verify").stdout
    lb = Logbook(tmp_path / "lb")  # by path: this process's LOGBOOK_HOME must not steer the check
    agm = next(line for line in lb.lines() if line["payload"].get("title") == "Sailing club AGM")
    assert agm["at"] == "2026-03-06T23:00:00Z" and agm["tz"] == "Europe/Oslo"


# -- property: every emitted line is a valid event/v1 observation -------------------

STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
RRULE = re.compile(
    r"^FREQ=(DAILY|WEEKLY|MONTHLY|YEARLY)(;(INTERVAL|COUNT|UNTIL|BYDAY|BYMONTHDAY)=[A-Z0-9,+-]+)*$"
)
PAYLOAD_KEYS = {
    "schema", "raw_id", "modified_at", "title", "calendar", "all_day", "location", "organizer", "attendees",
    "status", "recurrence", "recurrence_of", "notes", "extra",
}  # fmt: skip


def _rfc_rules(line: dict) -> None:
    assert set(line) == ENVELOPE
    assert line["kind"] == "event" and line["tier"] == 1 and line["source"] == "ios-calendar"
    assert STAMP.match(line["at"]) and line["at"] >= "1990-"
    assert line["end"] is None or STAMP.match(line["end"])
    if line["tz"] is not None:
        zoneinfo.ZoneInfo(line["tz"])
    p = line["payload"]
    assert set(p) <= PAYLOAD_KEYS and {"schema", "raw_id", "all_day"} <= set(p)
    assert p["schema"] == "event/v1"
    assert isinstance(p["raw_id"], str) and p["raw_id"]
    assert isinstance(p["all_day"], bool)
    if p["all_day"]:
        assert line["end"] is not None and line["end"] > line["at"]
    for key in ("title", "notes", "location", "recurrence_of", "modified_at"):
        if key in p:
            assert isinstance(p[key], str) and p[key]
    if "modified_at" in p:
        assert STAMP.match(p["modified_at"]) and p["raw_id"].endswith("@" + p["modified_at"])
    if "calendar" in p:
        assert set(p["calendar"]) - {"name"} == {"id"} and isinstance(p["calendar"]["id"], str)
    if "organizer" in p:
        assert (
            p["organizer"]["kind"] == "email" and p["organizer"]["value"] == p["organizer"]["value"].lower()
        )
    for a in p.get("attendees", []):
        assert set(a) - {"name", "response", "extra"} == {"ref"}
        assert a["ref"]["kind"] == "email" and a["ref"]["value"] == a["ref"]["value"].strip().lower()
        assert a.get("response", "none") in {"accepted", "declined", "tentative", "none"}
    if "status" in p:
        assert p["status"] in {"confirmed", "tentative", "cancelled"}
    if "recurrence" in p:
        assert RRULE.match(p["recurrence"]) and "recurrence_of" not in p
    if "extra" in p:
        assert isinstance(p["extra"], dict) and p["extra"]
    json.dumps(line, allow_nan=False)


_text = st.one_of(st.none(), st.text(max_size=12))
_stamp = st.one_of(
    st.none(),
    st.integers(-(2**36), 2**36),
    st.floats(min_value=-1e11, max_value=1e11, allow_nan=False, allow_infinity=False),
    st.integers(_apple("2020-01-01T00:00:00Z"), _apple("2030-01-01T00:00:00Z")),
)
_zone = st.one_of(
    st.none(), st.sampled_from(["Europe/Oslo", "UTC", "_float", "America/New_York", "Nowhere/X"]), _text
)
_code = st.one_of(st.none(), st.integers(0, 8), st.integers(-5, 200))
_item = st.tuples(
    _text,  # uid
    _text,  # summary
    _text,  # description
    _stamp,  # start
    _stamp,  # end
    _zone,
    st.one_of(st.none(), st.integers(0, 1)),  # all_day
    st.one_of(st.none(), st.integers(0, 3)),  # calendar_id, may point past the end
    st.one_of(st.none(), st.integers(0, 3)),  # location_id
    _code,  # status
    _stamp,  # last_modified
    st.one_of(st.none(), st.integers(0, 1)),  # has_recurrences
    st.one_of(st.none(), st.integers(0, 6)),  # orig_item_id, may point at itself or past the end
    _stamp,  # orig_date
)
_email = st.one_of(st.emails().map(lambda e: e[:30]), st.just(" Ola@Example.org "), _text)
_participant = st.tuples(
    st.one_of(st.none(), st.integers(0, 3)),  # entity_type
    st.integers(1, 6),  # owner_id
    _email,
    _text,
    _code,  # status
    _code,  # role
    _code,  # type
)
_coord = st.one_of(st.none(), st.floats(-90, 90, allow_nan=False), st.integers(-1000, 1000))
_location = st.tuples(_text, _text, _coord, _coord)
_by = st.one_of(st.none(), st.sampled_from(["1", "3,5", "MO,TU", "-1", "1,15", "x", "", "8,9"]), _text)
_recurrence = st.tuples(
    st.integers(1, 6),  # owner_id
    _code,  # frequency
    st.one_of(st.none(), st.integers(-1, 5)),  # interval
    st.one_of(st.none(), st.integers(-1, 20)),  # count
    _stamp,  # end_date
    _by,
    _by,
)
_store = st.tuples(
    st.lists(st.tuples(_text, st.one_of(st.none(), st.integers(0, 5))), max_size=3),  # calendars
    st.lists(_item, max_size=6),
    st.lists(_participant, max_size=6),
    st.lists(_location, max_size=3),
    st.lists(_recurrence, max_size=3),
)


@settings(max_examples=40, deadline=None)
@given(_store, st.sampled_from([None, "Europe/Oslo", "UTC"]))
def test_any_calendar_store_yields_only_valid_lines(tmp_path_factory, store, timezone):
    calendars, items, participants, locations, recurrences = store
    p = tmp_path_factory.mktemp("cal") / "Calendar.sqlitedb"
    con = sqlite3.connect(p)
    try:
        con.executescript(DDL)
        for rowid, calendar in enumerate(calendars, start=1):
            con.execute("INSERT INTO Calendar VALUES (?,?,?)", (rowid, *calendar))
        for rowid, item in enumerate(items, start=1):
            con.execute("INSERT INTO CalendarItem VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (rowid, *item))
        for rowid, participant in enumerate(participants, start=1):
            con.execute("INSERT INTO Participant VALUES (?,?,?,?,?,?,?,?)", (rowid, *participant))
        for rowid, loc in enumerate(locations, start=1):
            con.execute("INSERT INTO Location VALUES (?,?,?,?,?)", (rowid, *loc))
        for rowid, rule in enumerate(recurrences, start=1):
            con.execute("INSERT INTO Recurrence VALUES (?,?,?,?,?,?,?,?,NULL,NULL)", (rowid, *rule))
        con.commit()
    finally:
        con.close()
    counts: dict[str, int] = {}
    lines = list(ios_calendar.run(p, counts=counts, timezone=timezone))
    for line in lines:
        _rfc_rules(line)
    skipped = sum(n for key, n in counts.items() if key.startswith("skipped_"))
    assert len(lines) + skipped == len(items)
    lb = Logbook.init(tmp_path_factory.mktemp("lb"), timezone or "UTC")
    appended = lb.append_many(lines)
    assert appended == len({line["payload"]["raw_id"] for line in lines})
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)
