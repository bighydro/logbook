"""iOS CallHistory.storedata → call/v1 (RFC 0012): one line per call the phone's log stores."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook.contrib import adapters
from logbook.contrib.adapters import dawarich, ios_calendar, ios_calls, ios_contacts, whatsapp
from logbook.contrib.adapters.takeout import location
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
DAWARICH = ROOT / "tests" / "fixtures" / "dawarich" / "export.json"
TAKEOUT = ROOT / "tests" / "fixtures" / "takeout" / "Records.json"
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
APPLE_EPOCH = 978_307_200  # 2001-01-01T00:00:00Z, the zero of ZDATE

# Core Data's own layout: Z_PK the row id, Z_ENT/Z_OPT its bookkeeping, every attribute Z-prefixed.
DDL = """
CREATE TABLE ZCALLRECORD (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER,
    ZANSWERED INTEGER, ZCALLTYPE INTEGER, ZDISCONNECTED_CAUSE INTEGER, ZFACE_TIME_DATA INTEGER,
    ZHANDLE_TYPE INTEGER, ZNUMBER_AVAILABILITY INTEGER, ZORIGINATED INTEGER, ZREAD INTEGER,
    ZJUNKCONFIDENCE INTEGER, ZDATE TIMESTAMP, ZDURATION FLOAT,
    ZADDRESS VARCHAR, ZDEVICE_ID VARCHAR, ZISO_COUNTRY_CODE VARCHAR, ZLOCATION VARCHAR, ZNAME VARCHAR,
    ZSERVICE_PROVIDER VARCHAR, ZUNIQUE_ID VARCHAR, ZLOCALPARTICIPANTUUID VARCHAR,
    ZREMOTEPARTICIPANTHANDLES BLOB
);
CREATE TABLE Z_PRIMARYKEY (Z_ENT INTEGER PRIMARY KEY, Z_NAME VARCHAR, Z_SUPER INTEGER, Z_MAX INTEGER);
CREATE TABLE Z_METADATA (Z_VERSION INTEGER PRIMARY KEY, Z_UUID VARCHAR(255), Z_PLIST BLOB);
"""
COLUMNS = (
    "Z_PK", "Z_ENT", "Z_OPT", "ZANSWERED", "ZCALLTYPE", "ZDISCONNECTED_CAUSE", "ZFACE_TIME_DATA",
    "ZHANDLE_TYPE", "ZNUMBER_AVAILABILITY", "ZORIGINATED", "ZREAD", "ZJUNKCONFIDENCE", "ZDATE",
    "ZDURATION", "ZADDRESS", "ZDEVICE_ID", "ZISO_COUNTRY_CODE", "ZLOCATION", "ZNAME",
    "ZSERVICE_PROVIDER", "ZUNIQUE_ID", "ZLOCALPARTICIPANTUUID", "ZREMOTEPARTICIPANTHANDLES",
)  # fmt: skip

TELEPHONY = "com.apple.Telephony"
FACETIME = "com.apple.FaceTime"
WHATSAPP = "net.whatsapp.WhatsApp"
PHONE, FACETIME_VIDEO, FACETIME_AUDIO = 1, 8, 16  # ZCALLTYPE as the phone spells it


def _apple(stamp: str) -> float:
    return float(
        int(datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()) - APPLE_EPOCH
    )


def _uuid(n: int) -> str:
    return f"3B1F8E2A-6C4D-4F7B-9A0E-2D5C8B1F{n:04X}"


def _row(
    pk: int,
    *,
    address: object = "+4790000001",
    date: object = _apple("2026-03-02T15:04:10Z"),
    duration: object = 445.0,
    originated: object = 0,
    answered: object = 1,
    call_type: object = PHONE,
    provider: object = TELEPHONY,
    unique_id: object = "auto",
    read: object = 1,
    country: object = "no",
    location: object = "Oslo",
    name: object = None,
    disconnected: object = None,
    handles: object = None,
) -> tuple:
    values = {
        "Z_PK": pk,
        "Z_ENT": 1,
        "Z_OPT": 1,
        "ZANSWERED": answered,
        "ZCALLTYPE": call_type,
        "ZDISCONNECTED_CAUSE": disconnected,
        "ZFACE_TIME_DATA": 0,
        "ZHANDLE_TYPE": 1,
        "ZNUMBER_AVAILABILITY": 0,
        "ZORIGINATED": originated,
        "ZREAD": read,
        "ZJUNKCONFIDENCE": None,
        "ZDATE": date,
        "ZDURATION": duration,
        "ZADDRESS": address,
        "ZDEVICE_ID": None,
        "ZISO_COUNTRY_CODE": country,
        "ZLOCATION": location,
        "ZNAME": name,
        "ZSERVICE_PROVIDER": provider,
        "ZUNIQUE_ID": _uuid(pk) if unique_id == "auto" else unique_id,
        "ZLOCALPARTICIPANTUUID": None,
        "ZREMOTEPARTICIPANTHANDLES": handles,
    }
    return tuple(values[c] for c in COLUMNS)


# The synthetic Oslo persona's call log. Nobody in it exists.
ROWS = [
    _row(1),  # incoming, answered, cellular: seven and a half minutes
    _row(
        2, address="+4790000002", date=_apple("2026-03-02T16:30:00Z"), duration=62.4, originated=1
    ),  # outgoing
    _row(
        3, address="+4790000003", date=_apple("2026-03-03T07:12:00Z"), duration=0.0, answered=0, read=0
    ),  # missed
    _row(  # FaceTime video, incoming, answered, to an email address
        4,
        address="Ola@Example.org",
        date=_apple("2026-03-03T18:00:00Z"),
        duration=1200.0,
        call_type=FACETIME_VIDEO,
        provider=FACETIME,
        country=None,
        location=None,
    ),
    _row(  # FaceTime audio, outgoing, not answered
        5,
        date=_apple("2026-03-04T09:00:00Z"),
        duration=0.0,
        originated=1,
        answered=0,
        call_type=FACETIME_AUDIO,
        provider=FACETIME,
        location=None,
    ),
    _row(  # a WhatsApp call through CallKit: the provider is the app's bundle id
        6,
        address="+4790000004",
        date=_apple("2026-03-04T12:00:00Z"),
        duration=95.0,
        provider=WHATSAPP,
        location=None,
    ),
    _row(7, address=None, date=_apple("2026-03-04T13:00:00Z"), duration=0.0, answered=0, read=0),  # withheld
    _row(8, date=_apple("1601-01-01T00:00:00Z"), duration=0.0),  # the store's placeholder date
    _row(9, date=None, duration=0.0),  # no date at all
    _row(
        10, address="+4790000002", date=_apple("2026-03-05T10:00:00Z"), duration=30.0, unique_id=None
    ),  # by row
    _row(11, address="90000005", date=_apple("2026-03-05T11:00:00Z"), duration=10.0),  # national spelling
    _row(12, address=b"+4790000006", date=_apple("2026-03-05T12:00:00Z"), duration=20.0),  # address as a blob
    _row(  # no provider and a call type we do not know: no service, the code kept
        13,
        address="+4790000007",
        date=_apple("2026-03-05T13:00:00Z"),
        duration=5.0,
        call_type=99,
        provider=None,
        name="Kari Nordmann",
        disconnected=2,
    ),
]
LINES = 11  # 13 rows less the placeholder and the dateless one


def _store(tmp_path: Path, name: str = "CallHistory.storedata", rows: list[tuple] | None = None) -> Path:
    p = tmp_path / name
    con = sqlite3.connect(p)
    try:
        con.executescript(DDL)
        marks = ",".join("?" * len(COLUMNS))
        con.executemany(f"INSERT INTO ZCALLRECORD ({', '.join(COLUMNS)}) VALUES ({marks})", rows or ROWS)
        con.execute("INSERT INTO Z_PRIMARYKEY VALUES (1, 'CallRecord', 0, ?)", (len(rows or ROWS),))
        con.commit()
    finally:
        con.close()
    return p


def _by_row(lines: list[dict]) -> dict[int, dict]:
    """Lines keyed by the Z_PK they came from: the uuid's last digits, else the bare row id."""
    out: dict[int, dict] = {}
    for line in lines:
        raw = line["payload"]["raw_id"]
        out[int(raw[-4:], 16) if "-" in raw else int(raw)] = line
    return out


@pytest.fixture
def no_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ios_contacts.DIAL_PREFIX_ENV, raising=False)


# -- registry ---------------------------------------------------------------


def test_registry_lists_ios_calls():
    assert "ios-calls" in [a.NAME for a in adapters.all_adapters()]


def test_registry_find_returns_ios_calls_for_a_call_store(tmp_path):
    found = adapters.find(_store(tmp_path))
    assert found is not None and found.NAME == "ios-calls"


def test_registry_find_by_content_not_by_name(tmp_path):
    """A backup stores the file under its hashed name, without an extension."""
    found = adapters.find(_store(tmp_path, "5a4935c8b2f5c4a3a0e4b0c3d1e2f3a4b5c6d7e8"))
    assert found is not None and found.NAME == "ios-calls"


def test_registry_named():
    assert adapters.named("ios-calls") is ios_calls


# -- sniff ------------------------------------------------------------------


def test_sniff_accepts_call_store(tmp_path):
    assert ios_calls.sniff(_store(tmp_path)) is True


def test_sniff_rejects_other_exports(tmp_path):
    assert ios_calls.sniff(DAWARICH) is False
    assert ios_calls.sniff(TAKEOUT) is False


def test_other_adapters_reject_the_call_store(tmp_path):
    p = _store(tmp_path)
    assert dawarich.sniff(p) is False
    assert location.sniff(p) is False
    assert ios_contacts.sniff(p) is False
    assert whatsapp.sniff(p) is False
    assert ios_calendar.sniff(p) is False


@pytest.mark.parametrize(
    "ddl",
    [
        "CREATE TABLE ZWACHATSESSION (Z_PK INTEGER PRIMARY KEY);",  # another Core Data store
        "CREATE TABLE CalendarItem (ROWID INTEGER PRIMARY KEY, start_date REAL);",
        "CREATE TABLE things (id INTEGER PRIMARY KEY);",
    ],
)
def test_sniff_rejects_unrelated_sqlite_files(tmp_path, ddl):
    p = tmp_path / "other.sqlite"
    con = sqlite3.connect(p)
    con.executescript(ddl)
    con.commit()
    con.close()
    assert ios_calls.sniff(p) is False


@pytest.mark.parametrize("content", [b"", b"SQLite format 3\x00" + b"\x00" * 50, b"not a database at all"])
def test_sniff_rejects_non_sqlite_files(tmp_path, content):
    p = tmp_path / "CallHistory.storedata"
    p.write_bytes(content)
    assert ios_calls.sniff(p) is False


def test_sniff_rejects_directory_and_missing_file(tmp_path):
    assert ios_calls.sniff(tmp_path) is False
    assert ios_calls.sniff(tmp_path / "nope.storedata") is False


def test_sniff_and_run_never_touch_the_source(tmp_path):
    p = _store(tmp_path)
    before = p.read_bytes()
    assert ios_calls.sniff(p) is True
    list(ios_calls.run(p))
    assert p.read_bytes() == before
    assert sorted(q.name for q in tmp_path.iterdir()) == [p.name]  # no -journal, -wal, -shm


# -- run: envelope ------------------------------------------------------------


def test_run_yields_call_lines(tmp_path):
    lines = list(ios_calls.run(_store(tmp_path)))
    assert len(lines) == LINES
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["kind"] == "call" and line["tier"] == 1 and line["source"] == "ios-calls"
        assert line["tz"] is None  # a call log has no zone of its own; the record's applies
        assert line["payload"]["schema"] == "call/v1"


def test_run_converts_the_apple_epoch(tmp_path):
    lines = _by_row(list(ios_calls.run(_store(tmp_path))))
    assert lines[1]["at"] == "2026-03-02T15:04:10Z"
    assert lines[3]["at"] == "2026-03-03T07:12:00Z"


def test_run_end_is_start_plus_duration_when_answered(tmp_path):
    lines = _by_row(list(ios_calls.run(_store(tmp_path))))
    assert lines[1]["end"] == "2026-03-02T15:11:35Z" and lines[1]["payload"]["duration_s"] == 445
    assert (
        lines[2]["end"] == "2026-03-02T16:31:02Z" and lines[2]["payload"]["duration_s"] == 62
    )  # 62.4 rounded


def test_run_missed_call_has_no_end(tmp_path):
    lines = _by_row(list(ios_calls.run(_store(tmp_path))))
    assert lines[3]["end"] is None and lines[3]["payload"]["duration_s"] == 0
    assert lines[5]["end"] is None


def test_run_streams_in_row_order(tmp_path):
    lines = list(ios_calls.run(_store(tmp_path)))
    assert [line["payload"]["raw_id"] for line in lines[:3]] == [_uuid(1), _uuid(2), _uuid(3)]


def test_run_honours_since(tmp_path):
    lines = list(ios_calls.run(_store(tmp_path), since="2026-03-04T12:00:00Z"))
    assert [line["at"] for line in lines] == [
        "2026-03-04T12:00:00Z",
        "2026-03-04T13:00:00Z",
        "2026-03-05T10:00:00Z",
        "2026-03-05T11:00:00Z",
        "2026-03-05T12:00:00Z",
        "2026-03-05T13:00:00Z",
    ]


# -- run: direction and answered -------------------------------------------------


def test_run_incoming_answered(tmp_path):
    p = _by_row(list(ios_calls.run(_store(tmp_path))))[1]["payload"]
    assert p["direction"] == "incoming" and p["answered"] is True


def test_run_outgoing_answered(tmp_path):
    p = _by_row(list(ios_calls.run(_store(tmp_path))))[2]["payload"]
    assert p["direction"] == "outgoing" and p["answered"] is True


def test_run_missed_incoming(tmp_path):
    p = _by_row(list(ios_calls.run(_store(tmp_path))))[3]["payload"]
    assert p["direction"] == "incoming" and p["answered"] is False


def test_run_unanswered_outgoing(tmp_path):
    p = _by_row(list(ios_calls.run(_store(tmp_path))))[5]["payload"]
    assert p["direction"] == "outgoing" and p["answered"] is False


def test_run_answered_is_the_flag_not_the_duration(tmp_path):
    """RFC 0012 rule 3: a call that connected and dropped at once is answered with duration 0."""
    rows = [_row(1, duration=0.0, answered=1)]
    (line,) = ios_calls.run(_store(tmp_path, rows=rows))
    assert line["payload"]["answered"] is True and line["payload"]["duration_s"] == 0
    assert line["end"] is None


# -- run: service ---------------------------------------------------------------


def test_run_cellular_service(tmp_path):
    p = _by_row(list(ios_calls.run(_store(tmp_path))))[1]["payload"]
    assert p["service"] == "cellular" and p["extra"]["service_provider"] == TELEPHONY


def test_run_facetime_video_service(tmp_path):
    p = _by_row(list(ios_calls.run(_store(tmp_path))))[4]["payload"]
    assert p["service"] == "facetime" and p["extra"]["service_provider"] == FACETIME


def test_run_facetime_audio_service(tmp_path):
    p = _by_row(list(ios_calls.run(_store(tmp_path))))[5]["payload"]
    assert p["service"] == "facetime-audio"


def test_run_third_party_service_is_named_from_the_bundle_id(tmp_path):
    p = _by_row(list(ios_calls.run(_store(tmp_path))))[6]["payload"]
    assert p["service"] == "whatsapp" and p["extra"]["service_provider"] == WHATSAPP


def test_run_call_type_alone_names_the_service_when_the_provider_is_absent(tmp_path):
    rows = [_row(1, provider=None, call_type=FACETIME_AUDIO), _row(2, provider=None, call_type=PHONE)]
    lines = _by_row(list(ios_calls.run(_store(tmp_path, rows=rows))))
    assert lines[1]["payload"]["service"] == "facetime-audio"
    assert lines[2]["payload"]["service"] == "cellular"
    assert "service_provider" not in lines[1]["payload"].get("extra", {})


def test_run_unknown_service_gives_no_service_and_keeps_the_code(tmp_path):
    p = _by_row(list(ios_calls.run(_store(tmp_path))))[13]["payload"]
    assert "service" not in p
    assert p["extra"]["call_type"] == 99


# -- run: counterparty --------------------------------------------------------------


def test_run_counterparty_is_a_source_native_phone_ref(tmp_path, no_prefix):
    p = _by_row(list(ios_calls.run(_store(tmp_path))))[1]["payload"]
    assert p["counterparty"] == {"kind": "phone", "value": "+4790000001"}


def test_run_counterparty_email_is_lower_cased(tmp_path):
    p = _by_row(list(ios_calls.run(_store(tmp_path))))[4]["payload"]
    assert p["counterparty"] == {"kind": "email", "value": "ola@example.org"}


def test_run_counterparty_stored_as_a_blob_is_decoded(tmp_path):
    p = _by_row(list(ios_calls.run(_store(tmp_path))))[12]["payload"]
    assert p["counterparty"] == {"kind": "phone", "value": "+4790000006"}


def test_run_national_number_completes_with_the_dial_prefix(tmp_path, monkeypatch):
    monkeypatch.setenv(ios_contacts.DIAL_PREFIX_ENV, "47")
    p = _by_row(list(ios_calls.run(_store(tmp_path))))[11]["payload"]
    assert p["counterparty"] == {"kind": "phone", "value": "+4790000005"}
    assert "unnormalised" not in p.get("extra", {})


def test_run_national_number_without_a_prefix_is_kept_and_flagged(tmp_path, no_prefix):
    p = _by_row(list(ios_calls.run(_store(tmp_path))))[11]["payload"]
    assert p["counterparty"] == {"kind": "phone", "value": "90000005"}
    assert p["extra"]["unnormalised"] is True


def test_run_handle_that_is_neither_phone_nor_email(tmp_path, no_prefix):
    (line,) = ios_calls.run(_store(tmp_path, rows=[_row(1, address="Telenor")]))
    assert line["payload"]["counterparty"] == {"kind": "handle", "value": "Telenor"}


def test_run_withheld_number_has_no_counterparty_and_is_counted(tmp_path):
    counts: dict[str, int] = {}
    lines = _by_row(list(ios_calls.run(_store(tmp_path), counts=counts)))
    assert "counterparty" not in lines[7]["payload"]
    assert counts["no_counterparty"] == 1


def test_run_never_resolves_the_counterparty(tmp_path):
    """The caller-id name the phone showed is text under extra, never part of the ref (RFC 0012 rule 2)."""
    p = _by_row(list(ios_calls.run(_store(tmp_path))))[13]["payload"]
    assert set(p["counterparty"]) == {"kind", "value"}
    assert p["extra"]["name"] == "Kari Nordmann"


# -- run: raw_id, extra, skips -------------------------------------------------------


def test_run_raw_id_is_the_unique_id(tmp_path):
    lines = _by_row(list(ios_calls.run(_store(tmp_path))))
    assert lines[1]["payload"]["raw_id"] == _uuid(1)


def test_run_row_without_a_unique_id_is_keyed_by_row_id_and_noted(tmp_path):
    counts: dict[str, int] = {}
    lines = _by_row(list(ios_calls.run(_store(tmp_path), counts=counts)))
    assert lines[10]["payload"]["raw_id"] == "10"
    assert counts["no_unique_id"] == 1


def test_run_unmapped_columns_are_kept_under_extra(tmp_path):
    p = _by_row(list(ios_calls.run(_store(tmp_path))))[1]["payload"]
    assert p["extra"]["location"] == "Oslo"
    assert p["extra"]["iso_country_code"] == "no"
    assert p["extra"]["read"] == 1
    assert p["extra"]["handle_type"] == 1
    # the mapped columns and Core Data's bookkeeping are not repeated
    for key in (
        "address",
        "date",
        "duration",
        "originated",
        "answered",
        "unique_id",
        "z_pk",
        "z_ent",
        "z_opt",
        "pk",
    ):
        assert key not in p["extra"]


def test_run_null_columns_and_blobs_stay_out_of_extra(tmp_path):
    rows = [_row(1, handles=b"\x00\x01binary", disconnected=None, name=None)]
    (line,) = ios_calls.run(_store(tmp_path, rows=rows))
    extra = line["payload"]["extra"]
    assert (
        "remoteparticipanthandles" not in extra and "disconnected_cause" not in extra and "name" not in extra
    )


def test_run_skips_and_counts_placeholder_dates_and_rows_without_a_date(tmp_path):
    counts: dict[str, int] = {}
    lines = list(ios_calls.run(_store(tmp_path), counts=counts))
    assert len(lines) == LINES
    assert counts["skipped_placeholder_date"] == 1 and counts["skipped_no_date"] == 1
    assert all(line["at"] >= "1900-" for line in lines)


def test_run_keeps_a_date_from_1900_on(tmp_path):
    (line,) = ios_calls.run(_store(tmp_path, rows=[_row(1, date=_apple("1900-01-01T00:00:00Z"))]))
    assert line["at"] == "1900-01-01T00:00:00Z"


# -- run: defensive about the schema ------------------------------------------------------


def test_run_with_the_minimal_columns_only(tmp_path):
    p = tmp_path / "CallHistory.storedata"
    con = sqlite3.connect(p)
    try:
        con.executescript(
            "CREATE TABLE ZCALLRECORD (Z_PK INTEGER PRIMARY KEY, ZDATE TIMESTAMP, ZADDRESS VARCHAR);"
        )
        con.execute("INSERT INTO ZCALLRECORD VALUES (1, ?, '+4790000001')", (_apple("2026-03-10T10:00:00Z"),))
        con.commit()
    finally:
        con.close()
    counts: dict[str, int] = {}
    (line,) = ios_calls.run(p, counts=counts)
    assert line["at"] == "2026-03-10T10:00:00Z" and line["end"] is None
    assert line["payload"] == {
        "schema": "call/v1",
        "raw_id": "1",
        "direction": "incoming",
        "answered": False,
        "duration_s": 0,
        "counterparty": {"kind": "phone", "value": "+4790000001"},
    }
    assert counts == {"no_unique_id": 1}


# -- through the log: append, dedupe on re-run, CLI -----------------------------------


def test_run_lines_append_and_re_running_appends_nothing(tmp_path):
    p = _store(tmp_path)
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    assert lb.append_many(ios_calls.run(p)) == LINES
    assert lb.append_many(ios_calls.run(p)) == 0
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == LINES
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)
        assert line["tz"] == "Europe/Oslo"


def _cli(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != ios_contacts.DIAL_PREFIX_ENV}
    env.update({"LOGBOOK_HOME": str(tmp_path / "lb"), "PYTHONPATH": str(ROOT)})

    def run(*a):
        return subprocess.run(
            [sys.executable, "-m", "logbook.cli", *a],
            env=env,
            capture_output=True,
            encoding="utf-8",
            check=True,
        )

    return run


def test_cli_add_by_name_reports_lines_skips_and_notes(tmp_path):
    run = _cli(tmp_path)
    run("init", str(tmp_path / "lb"), "--timezone", "Europe/Oslo")
    p = _store(tmp_path)
    out = run("add", "ios-calls", str(p)).stdout
    assert f"added {LINES} lines from ios-calls" in out
    assert "skipped 1 with a placeholder start (before 1900), 1 without a date" in out
    assert "also 1 without a counterparty, 1 without a unique id, keyed by row id" in out
    assert "added 0 lines from ios-calls" in run("add", "ios-calls", str(p)).stdout
    assert f"valid — {LINES} lines" in run("verify").stdout


def test_cli_add_by_sniff_writes_the_same_lines(tmp_path):
    run = _cli(tmp_path)
    run("init", str(tmp_path / "lb"), "--timezone", "Europe/Oslo")
    p = _store(tmp_path)
    assert f"added {LINES} lines from ios-calls" in run("add", str(p)).stdout
    assert "added 0 lines from ios-calls" in run("add", "ios-calls", str(p)).stdout


def test_cli_show_prints_a_call_without_resolving_it(tmp_path):
    run = _cli(tmp_path)
    run("init", str(tmp_path / "lb"), "--timezone", "Europe/Oslo")
    run("add", "ios-calls", str(_store(tmp_path)))
    out = run("show", "2026-03-02").stdout
    assert "call" in out and "+4790000001" in out and "cellular" in out
    assert "Kari" not in out


# -- property: every emitted line is a valid call/v1 observation -------------------

STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
PAYLOAD_KEYS = {"schema", "raw_id", "direction", "answered", "duration_s", "counterparty", "service", "extra"}
SERVICE = re.compile(r"^[a-z0-9-]+$")


def _rfc_rules(line: dict) -> None:
    assert set(line) == ENVELOPE
    assert line["kind"] == "call" and line["tier"] == 1 and line["source"] == "ios-calls"
    assert line["tz"] is None
    assert STAMP.match(line["at"]) and line["at"] >= "1900-"
    p = line["payload"]
    assert set(p) <= PAYLOAD_KEYS and {"schema", "raw_id", "direction", "answered", "duration_s"} <= set(p)
    assert p["schema"] == "call/v1"
    assert isinstance(p["raw_id"], str) and p["raw_id"]
    assert p["direction"] in ("incoming", "outgoing")
    assert isinstance(p["answered"], bool)
    assert isinstance(p["duration_s"], int) and not isinstance(p["duration_s"], bool) and p["duration_s"] >= 0
    if p["answered"] and p["duration_s"] > 0:
        assert line["end"] is not None and STAMP.match(line["end"]) and line["end"] > line["at"]
    else:
        assert line["end"] is None
    if "counterparty" in p:
        ref = p["counterparty"]
        assert set(ref) == {"kind", "value"} and ref["kind"] in ("phone", "email", "handle")
        assert isinstance(ref["value"], str) and ref["value"]
    if "service" in p:
        assert SERVICE.match(p["service"])
    if "extra" in p:
        assert isinstance(p["extra"], dict) and p["extra"]
        for key, value in p["extra"].items():
            assert re.match(r"^[a-z][a-z0-9_]*$", key)
            assert isinstance(value, str | int | float | bool)


def test_fixture_lines_follow_the_rfc(tmp_path):
    for line in ios_calls.run(_store(tmp_path)):
        _rfc_rules(line)


_text = st.one_of(st.none(), st.text(min_size=0, max_size=20))
_flag = st.one_of(st.none(), st.integers(min_value=0, max_value=1), st.just("x"))
_date = st.one_of(
    st.none(),
    st.floats(min_value=-13_000_000_000, max_value=3_000_000_000, allow_nan=False, allow_infinity=False),
    st.text(max_size=5),
)
_duration = st.one_of(
    st.none(), st.floats(min_value=-10, max_value=100_000, allow_nan=False, allow_infinity=False)
)
_address = st.one_of(
    st.none(),
    st.sampled_from(["+4790000001", "ola@example.org", "90000005", "Telenor", "", "  "]),
    st.binary(max_size=12),
)
_provider = st.one_of(st.none(), st.sampled_from([TELEPHONY, FACETIME, WHATSAPP, "", "org.example.Dialer"]))
_type = st.one_of(st.none(), st.integers(min_value=-1, max_value=100))


@settings(max_examples=60, deadline=None)
@given(
    rows=st.lists(
        st.tuples(_address, _date, _duration, _flag, _flag, _type, _provider, _text, _text),
        min_size=1,
        max_size=6,
    )
)
def test_every_line_from_any_row_follows_the_rfc(tmp_path_factory, rows):
    tmp_path = tmp_path_factory.mktemp("calls")
    fixture = [
        _row(
            n + 1,
            address=address,
            date=date,
            duration=duration,
            originated=originated,
            answered=answered,
            call_type=call_type,
            provider=provider,
            unique_id=unique_id,
            name=name,
        )
        for n, (
            address,
            date,
            duration,
            originated,
            answered,
            call_type,
            provider,
            unique_id,
            name,
        ) in enumerate(rows)
    ]
    counts: dict[str, int] = {}
    lines = list(ios_calls.run(_store(tmp_path, rows=fixture), counts=counts))
    for line in lines:
        _rfc_rules(line)
    assert len(lines) + counts.get("skipped_no_date", 0) + counts.get("skipped_placeholder_date", 0) == len(
        rows
    )
