"""Flighty CSV export → flight/v1 (RFC 0013), evidence `tracked`: one line per row, times converted
from the airports' wall clocks, a changed re-export a new observation of the same flight."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters, flights
from logbook.adapters import flighty
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "flighty" / "export.csv"
DAWARICH = ROOT / "tests" / "fixtures" / "dawarich" / "export.json"
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
LINES = 6


def _drafts(path: Path = FIXTURE, **options):
    return list(flighty.run(path, **options))


def _by_number(drafts, number: str):
    return next(d for d in drafts if d["payload"]["number"] == number)


# -- registry and sniff ---------------------------------------------------------------------------------


def test_registry_has_flighty_by_name_and_by_its_alias():
    assert adapters.named("flighty") is flighty
    assert adapters.named("flights") is flighty


def test_sniff_recognises_a_flighty_export_by_its_header(tmp_path: Path):
    assert flighty.sniff(FIXTURE)
    assert not flighty.sniff(DAWARICH)
    other = tmp_path / "other.csv"
    other.write_text("a,b\n1,2\n", encoding="utf-8")
    assert not flighty.sniff(other)
    assert not flighty.sniff(tmp_path / "missing.csv")
    assert not flighty.sniff(tmp_path)


# -- the mapping ------------------------------------------------------------------------------------------


def test_run_one_tracked_flight_per_row_with_every_time_in_utc():
    drafts = _drafts()
    assert len(drafts) == LINES
    d = _by_number(drafts, "561")
    p = d["payload"]
    assert d["source"] == "flighty" and d["kind"] == "flight" and d["tier"] == 1 and d["tz"] == "Europe/Oslo"
    assert p["schema"] == "flight/v1" and p["evidence"] == "tracked" and p["role"] == "passenger"
    assert (p["date"], p["carrier"], p["number"]) == ("2026-09-27", "XY", "561")
    assert p["from"] == {"iata": "OSL", "icao": "ENGM"} and p["to"] == {"iata": "ZRH", "icao": "LSZH"}
    assert p["scheduled_departure"] == "2026-09-27T05:05:00Z"  # Oslo, CEST
    assert p["actual_departure"] == "2026-09-27T05:10:00Z"
    assert p["scheduled_takeoff"] == "2026-09-27T05:20:00Z"
    assert p["actual_takeoff"] == "2026-09-27T05:31:00Z"
    assert p["scheduled_landing"] == "2026-09-27T07:05:00Z"  # Zürich, CEST
    assert p["actual_landing"] == "2026-09-27T07:12:00Z"
    assert p["scheduled_arrival"] == "2026-09-27T07:20:00Z"
    assert p["actual_arrival"] == "2026-09-27T07:24:00Z"
    assert d["at"] == "2026-09-27T05:10:00Z" and d["end"] == "2026-09-27T07:24:00Z"
    assert p["aircraft"] == {"type": "Airbus A320", "registration": "LN-XYA"}
    assert p["observations"] == [{"evidence": "tracked", "source": "flighty"}]
    assert p["extra"] == {
        "departure_gate": "A12",
        "arrival_terminal": "2",
        "arrival_gate": "B7",
        "seat": "1A",
        "seat_type": "window",
        "cabin": "economy",
        "reason": "personal",
    }


def test_run_never_keeps_the_booking_reference_or_the_notes():
    text = json.dumps(_drafts())
    assert "ABC123" not in text and "Window seat" not in text and "PNR" not in text


def test_run_spells_an_icao_airline_as_iata_and_strips_the_carrier_from_the_number():
    p = _by_number(_drafts(), "1210")["payload"]
    assert p["carrier"] == "LX" and p["carrier_icao"] == "SWR"
    assert p["from"]["iata"] == "ZRH"
    assert p["scheduled_departure"] == "2026-09-28T15:00:00Z" and "actual_departure" not in p
    assert p["scheduled_arrival"] == "2026-09-28T17:30:00Z"
    d = _by_number(_drafts(), "1210")
    assert (
        d["at"] == "2026-09-28T15:00:00Z"
        and d["end"] == "2026-09-28T17:30:00Z"
        and d["tz"] == "Europe/Zurich"
    )


def test_run_red_eye_keeps_the_departure_date_and_converts_the_arrival_at_the_destination():
    p = _by_number(_drafts(), "9")["payload"]
    assert p["date"] == "2026-10-03"
    assert p["actual_departure"] == "2026-10-03T21:40:00Z"
    assert p["actual_arrival"] == "2026-10-04T06:05:00Z"  # New York, EDT
    assert "actual_takeoff" not in p and "scheduled_takeoff" not in p  # blank columns leave no field
    assert p["extra"]["reason"] == "business"


def test_run_cancelled_flight_is_a_line_with_cancelled_true():
    p = _by_number(_drafts(), "77")["payload"]
    assert p["cancelled"] is True
    assert "actual_departure" not in p and "aircraft" not in p
    assert p["scheduled_departure"] == "2026-10-10T06:00:00Z"


def test_run_diversion_converts_the_arrival_at_the_airport_it_landed_at():
    p = _by_number(_drafts(), "78")["payload"]
    assert p["to"]["iata"] == "OSL" and p["diverted_to"] == {"iata": "TRF", "icao": "ENTO"}
    assert p["actual_arrival"] == "2026-10-12T17:40:00Z"


def test_run_unknown_airport_keeps_its_times_as_text(tmp_path: Path):
    counts: dict[str, int] = {}
    d = _by_number(_drafts(counts=counts), "101")
    p = d["payload"]
    assert p["from"] == {"iata": "ZZZ"}
    assert "scheduled_departure" not in p and "actual_departure" not in p
    assert p["extra"]["scheduled_departure_local"] == "2026-10-20T10:00"
    assert p["extra"]["actual_departure_local"] == "2026-10-20T10:05"
    assert p["actual_arrival"] == "2026-10-20T09:02:00Z"  # Oslo is known
    assert d["tz"] is None and d["at"] == "2026-10-20T00:00:00Z"
    assert counts["no_airport_zone"] == 1


def test_run_airports_override_makes_the_unknown_airport_known(tmp_path: Path):
    override = tmp_path / "airports.csv"
    override.write_text("iata,lat,lon,tz\nZZZ,60.5,11.5,Europe/Oslo\n", encoding="utf-8")
    p = _by_number(_drafts(airports=flights.Airports.load(override)), "101")["payload"]
    assert p["actual_departure"] == "2026-10-20T08:05:00Z"


def test_run_raw_id_is_the_flighty_id_with_a_digest_of_the_row():
    drafts = _drafts()
    ids = [d["payload"]["raw_id"] for d in drafts]
    assert all(i.startswith("fx-000") and "@" in i for i in ids) and len(set(ids)) == LINES
    assert _drafts()[0]["payload"]["raw_id"] == drafts[0]["payload"]["raw_id"]  # stable


def test_run_tolerates_an_export_with_only_the_essential_columns(tmp_path: Path):
    p = tmp_path / "small.csv"
    p.write_text("Date,Airline,Flight,From,To\n2026-09-27,XY,561,OSL,ZRH\n", encoding="utf-8")
    (d,) = _drafts(p)
    assert flights.key(d["payload"]) == ("2026-09-27", "XY", "561")
    assert d["at"] == "2026-09-26T22:00:00Z" and d["end"] is None  # local midnight at the origin
    assert d["payload"]["raw_id"].startswith("2026-09-27:XY:561@")
    assert not any(t in d["payload"] for t in flights.TIMES) and "extra" not in d["payload"]


def test_run_skips_rows_without_a_date_a_designator_or_a_route_and_counts_them(tmp_path: Path):
    p = tmp_path / "bad.csv"
    p.write_text(
        "Date,Airline,Flight,From,To\n"
        ",XY,561,OSL,ZRH\n"
        "2026-09-27,,561,OSL,ZRH\n"
        "2026-09-27,XY,,OSL,ZRH\n"
        "2026-09-27,XY,561,,ZRH\n"
        "27/09/2026,XY,561,OSL,ZRH\n"
        "2026-09-28,XY,562,ZRH,OSL\n",
        encoding="utf-8",
    )
    counts: dict[str, int] = {}
    drafts = _drafts(p, counts=counts)
    assert [d["payload"]["number"] for d in drafts] == ["562"]
    assert counts == {
        "skipped_no_date": 1,
        "skipped_bad_date": 1,
        "skipped_no_designator": 2,
        "skipped_no_route": 1,
    }


def test_run_arrival_before_departure_is_kept_and_counted(tmp_path: Path):
    p = tmp_path / "odd.csv"
    p.write_text(
        "Date,Airline,Flight,From,To,Gate Departure (Actual),Gate Arrival (Actual)\n"
        "2026-09-27,XY,561,OSL,ZRH,2026-09-27T09:00,2026-09-27T08:00\n",
        encoding="utf-8",
    )
    counts: dict[str, int] = {}
    (d,) = _drafts(p, counts=counts)
    assert d["payload"]["actual_arrival"] == "2026-09-27T06:00:00Z" and d["end"] == "2026-09-27T06:00:00Z"
    assert counts == {"arrival_before_departure": 1}


def test_run_since_cuts_on_at():
    assert [d["payload"]["number"] for d in _drafts(since="2026-10-10T00:00:00Z")] == ["77", "78", "101"]


def test_run_accepts_times_with_an_offset_or_z_as_they_say(tmp_path: Path):
    p = tmp_path / "zoned.csv"
    p.write_text(
        "Date,Airline,Flight,From,To,Gate Departure (Actual),Gate Arrival (Actual)\n"
        "2026-09-27,XY,561,OSL,ZRH,2026-09-27T05:10:00Z,2026-09-27T09:24:00+02:00\n",
        encoding="utf-8",
    )
    (d,) = _drafts(p)
    assert d["payload"]["actual_departure"] == "2026-09-27T05:10:00Z"
    assert d["payload"]["actual_arrival"] == "2026-09-27T07:24:00Z"


# -- in a record -------------------------------------------------------------------------------------------


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    return lb


def test_every_line_appended_is_a_valid_observation(lb: Logbook):
    assert lb.append_many(flighty.run(FIXTURE)) == LINES
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)
    assert lb.verify()[2] == []


def _cli(lb: Logbook, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "LOGBOOK_HOME": str(lb.root), "PYTHONPATH": str(ROOT)}
    return subprocess.run(
        [sys.executable, "-m", "logbook.cli", *args], env=env, capture_output=True, encoding="utf-8"
    )


def test_cli_add_flights_by_alias_by_name_and_by_sniff(lb: Logbook):
    r = _cli(lb, "add", "flights", str(FIXTURE))
    assert r.returncode == 0, r.stderr
    assert f"added {LINES} lines from flighty" in r.stdout
    assert "also 1 with an airport the table does not know" in r.stdout
    assert "added 0 lines from flighty" in _cli(lb, "add", "flighty", str(FIXTURE)).stdout
    assert "added 0 lines from flighty" in _cli(lb, "add", str(FIXTURE)).stdout
    assert lb.meta["seq"] == LINES


def test_cli_a_changed_export_is_a_new_observation_that_supersedes_the_first(lb: Logbook, tmp_path: Path):
    _cli(lb, "add", "flights", str(FIXTURE))
    changed = tmp_path / "later.csv"
    text = FIXTURE.read_text(encoding="utf-8").replace(
        "2026-09-28T17:00,,2026-09-28T17:15,,2026-09-28T19:15,,2026-09-28T19:30,,",
        "2026-09-28T17:00,2026-09-28T17:04,2026-09-28T17:15,2026-09-28T17:21,2026-09-28T19:15,"
        "2026-09-28T19:10,2026-09-28T19:30,2026-09-28T19:26,",
    )
    changed.write_text(text, encoding="utf-8")
    r = _cli(lb, "add", "flights", str(changed))
    assert (
        "added 1 lines from flighty" in r.stdout
        and "also 1 merged into a flight already in the record" in r.stdout
    )
    with lb.index() as idx:
        last = flights.standing(idx.by_kind("flight"))
    line = last[("2026-09-28", "LX", "1210")]
    p = line["payload"]
    assert p["actual_departure"] == "2026-09-28T15:04:00Z" and p["actual_arrival"] == "2026-09-28T17:26:00Z"
    assert p["evidence"] == "tracked" and len(p["observations"]) == 2 and "supersedes" in p
    assert lb.meta["seq"] == LINES + 1


def test_cli_show_prints_a_flight_and_marks_a_superseded_one(lb: Logbook, tmp_path: Path):
    _cli(lb, "add", "flights", str(FIXTURE))
    out = _cli(lb, "show", "2026-09-27").stdout
    assert "flight     flighty        XY 561 OSL → ZRH, arrives 09:24, Airbus A320 LN-XYA, tracked" in out
    r = _cli(lb, "add", "flight", "XY 561 OSL ZRH 2026-09-27 pilot")
    assert r.returncode == 0, r.stderr
    out = _cli(lb, "show", "2026-09-27").stdout.splitlines()
    assert any("superseded by #7" in row for row in out)
    assert any("XY 561 OSL → ZRH, arrives 09:24, Airbus A320 LN-XYA, tracked, as pilot" in row for row in out)


def test_cli_airports_flag_and_env_name_the_override(lb: Logbook, tmp_path: Path):
    override = tmp_path / "airports.csv"
    override.write_text("iata,lat,lon,tz\nZZZ,60.5,11.5,Europe/Oslo\n", encoding="utf-8")
    r = _cli(lb, "add", "flights", str(FIXTURE), "--airports", str(override))
    assert r.returncode == 0 and "does not know" not in r.stdout
    lb2 = Logbook.init(tmp_path / "lb2", "Europe/Oslo")
    env = {
        **os.environ,
        "LOGBOOK_HOME": str(lb2.root),
        "PYTHONPATH": str(ROOT),
        flights.AIRPORTS_ENV: str(override),
    }
    r = subprocess.run(
        [sys.executable, "-m", "logbook.cli", "add", "flights", str(FIXTURE)],
        env=env,
        capture_output=True,
        encoding="utf-8",
    )
    assert r.returncode == 0 and "does not know" not in r.stdout
    bad = tmp_path / "bad.csv"
    bad.write_text("iata,lat,lon,tz\nZZZ,60.5,11.5,Mars/Olympus\n", encoding="utf-8")
    r = _cli(lb, "add", "flights", str(FIXTURE), "--airports", str(bad))
    assert r.returncode == 2 and "Mars/Olympus" in r.stderr


# -- the app's own store, from an iPhone backup -------------------------------------------------------------

STORE_LINES = 4
PNR = "ABC123"


def _unix(stamp: str) -> int:
    from datetime import datetime

    return int(datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp())


def _store(folder: Path) -> Path:
    """`MainFlightyDatabase.db` with the tables and columns the adapter reads; the first flight is
    the CSV fixture's first row, so the two must give one and the same line."""
    import sqlite3

    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "MainFlightyDatabase.db"
    con = sqlite3.connect(path)
    try:
        con.executescript(
            "CREATE TABLE Airport (id TEXT PRIMARY KEY, name TEXT, iata TEXT, icao TEXT, city TEXT,"
            " timeZoneIdentifier TEXT, latitude REAL, longitude REAL, accountId INTEGER);"
            "CREATE TABLE Airline (id TEXT PRIMARY KEY, name TEXT, iata TEXT, icao TEXT, accountId INTEGER);"
            "CREATE TABLE Flight (id TEXT PRIMARY KEY, number TEXT, departureAirportId TEXT,"
            " departureTerminal TEXT, departureGate TEXT, departureScheduleGateOriginal INTEGER,"
            " departureScheduleGateEstimated INTEGER, departureScheduleGateActual INTEGER,"
            " departureScheduleRunwayOriginal INTEGER, departureScheduleRunwayEstimated INTEGER,"
            " departureScheduleRunwayActual INTEGER, scheduledArrivalAirportId TEXT,"
            " actualArrivalAirportId TEXT,"
            " arrivalTerminal TEXT, arrivalGate TEXT, arrivalScheduleGateOriginal INTEGER,"
            " arrivalScheduleGateEstimated INTEGER, arrivalScheduleGateActual INTEGER,"
            " arrivalScheduleRunwayOriginal INTEGER, arrivalScheduleRunwayEstimated INTEGER,"
            " arrivalScheduleRunwayActual INTEGER, equipmentTailNumber TEXT, equipmentModelName TEXT,"
            " airlineId TEXT, isCancelled INTEGER, created INTEGER, lastUpdated INTEGER, deleted INTEGER,"
            " accountId INTEGER);"
            "CREATE TABLE UserFlight (accountId INTEGER, userId TEXT, flightId TEXT, isRandom INTEGER,"
            " isMyFlight INTEGER, isArchived INTEGER, importSource TEXT, created INTEGER,"
            " lastUpdated INTEGER,"
            " deleted INTEGER);"
            "CREATE TABLE Ticket (accountId INTEGER, userId TEXT, flightId TEXT, pnr TEXT, seatNumber TEXT,"
            " seatPosition TEXT, cabinClass TEXT, flightReason TEXT, lastUpdated INTEGER, deleted INTEGER);"
        )
        con.executemany(
            "INSERT INTO Airport (id, name, iata, icao, timeZoneIdentifier) VALUES (?,?,?,?,?)",
            [
                ("ap-osl", "Oslo", "OSL", "ENGM", "Europe/Oslo"),
                ("ap-zrh", "Zurich", "ZRH", "LSZH", "Europe/Zurich"),
                ("ap-cph", "Copenhagen", "CPH", "EKCH", "Europe/Copenhagen"),
                ("ap-bgo", "Bergen", "BGO", "ENBR", "Europe/Oslo"),
                ("ap-xqx", "Somewhere", "XQX", "ZZZZ", "Pacific/Auckland"),  # not in the shipped table
            ],
        )
        con.executemany(
            "INSERT INTO Airline (id, name, iata, icao) VALUES (?,?,?,?)",
            [
                ("al-xy", "Example Air", "XY", None),
                ("al-lx", "Swiss", "LX", "SWR"),
                ("al-sk", "SAS", "SK", "SAS"),
            ],
        )
        flights_ = [
            # the CSV fixture's first row, to the second
            (
                "fx-0001",
                "561",
                "ap-osl",
                None,
                "A12",
                "2026-09-27T05:05:00Z",
                "2026-09-27T05:10:00Z",
                "2026-09-27T05:20:00Z",
                "2026-09-27T05:31:00Z",
                "ap-zrh",
                "ap-zrh",
                "2",
                "B7",
                "2026-09-27T07:20:00Z",
                "2026-09-27T07:24:00Z",
                "2026-09-27T07:05:00Z",
                "2026-09-27T07:12:00Z",
                "LN-XYA",
                "Airbus A320",
                "al-xy",
                0,
            ),
            # diverted: landed in Bergen, not Oslo
            (
                "fx-0003",
                "1210",
                "ap-zrh",
                "1",
                "B12",
                "2026-09-28T15:00:00Z",
                None,
                None,
                None,
                "ap-osl",
                "ap-bgo",
                None,
                None,
                "2026-09-28T17:30:00Z",
                "2026-09-28T18:02:00Z",
                None,
                None,
                "HB-JLT",
                "Airbus A321",
                "al-lx",
                0,
            ),
            # cancelled
            (
                "fx-0004",
                "0460",
                "ap-osl",
                None,
                None,
                "2026-10-01T06:00:00Z",
                None,
                None,
                None,
                "ap-cph",
                "ap-cph",
                None,
                None,
                "2026-10-01T07:10:00Z",
                None,
                None,
                None,
                None,
                None,
                "al-sk",
                1,
            ),
            # a friend's flight (not mine) and a deleted one: never read
            (
                "fx-0005",
                "77",
                "ap-osl",
                None,
                None,
                "2026-10-02T06:00:00Z",
                None,
                None,
                None,
                "ap-cph",
                "ap-cph",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                "al-sk",
                0,
            ),
            (
                "fx-0006",
                "78",
                "ap-osl",
                None,
                None,
                "2026-10-03T06:00:00Z",
                None,
                None,
                None,
                "ap-cph",
                "ap-cph",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                "al-sk",
                0,
            ),
            # from an airport the shipped table does not know: the store's zone dates it
            (
                "fx-0007",
                "77",
                "ap-xqx",
                None,
                None,
                "2026-11-01T20:00:00Z",
                None,
                None,
                None,
                "ap-zrh",
                "ap-zrh",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                "al-xy",
                0,
            ),
            # no schedule at all, and no airline
            (
                "fx-0008",
                "9",
                "ap-osl",
                None,
                None,
                None,
                None,
                None,
                None,
                "ap-zrh",
                "ap-zrh",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                "al-xy",
                0,
            ),
            (
                "fx-0009",
                "10",
                "ap-osl",
                None,
                None,
                "2026-11-05T06:00:00Z",
                None,
                None,
                None,
                "ap-zrh",
                "ap-zrh",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                0,
            ),
        ]
        for row in flights_:
            (fid, number, dep, dterm, dgate, dgo, dga, dro, dra, sarr, aarr, aterm, agate, ago, aga, aro, ara,
             tail, model, airline, cancelled) = row  # fmt: skip
            con.execute(
                "INSERT INTO Flight (id, number, departureAirportId, departureTerminal, departureGate,"
                " departureScheduleGateOriginal, departureScheduleGateActual,"
                " departureScheduleRunwayOriginal,"
                " departureScheduleRunwayActual, scheduledArrivalAirportId, actualArrivalAirportId,"
                " arrivalTerminal, arrivalGate, arrivalScheduleGateOriginal, arrivalScheduleGateActual,"
                " arrivalScheduleRunwayOriginal, arrivalScheduleRunwayActual, equipmentTailNumber,"
                " equipmentModelName, airlineId, isCancelled, created, lastUpdated, accountId)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,1,0)",
                (
                    fid,
                    number,
                    dep,
                    dterm,
                    dgate,
                    *(None if s is None else _unix(s) for s in (dgo, dga, dro, dra)),
                    sarr,
                    aarr,
                    aterm,
                    agate,
                    *(None if s is None else _unix(s) for s in (ago, aga, aro, ara)),
                    tail,
                    model,
                    airline,
                    cancelled,
                ),
            )
            mine = 0 if fid == "fx-0005" else 1
            deleted = 1_700_000_000 if fid == "fx-0006" else None
            con.execute(
                "INSERT INTO UserFlight (accountId, userId, flightId, isRandom, isMyFlight, isArchived,"
                " importSource, created, lastUpdated, deleted)"
                " VALUES (0, 'me', ?, 0, ?, 1, 'CALENDAR', 1, 1, ?)",
                (fid, mine, deleted),
            )
        con.execute(
            "INSERT INTO Ticket VALUES (0, 'me', 'fx-0001', ?, '1A', 'window', 'economy', 'personal', 1,"
            " NULL)",
            (PNR,),
        )
        con.execute(
            "INSERT INTO Ticket VALUES (0, 'me', 'fx-0003', ?, '12C', 'aisle', 'economy', 'personal', 1,"
            " NULL)",
            (PNR,),
        )
        con.commit()
    finally:
        con.close()
    return path


@pytest.fixture
def store(tmp_path: Path) -> Path:
    return _store(tmp_path / "flighty-app")


def test_sniff_recognises_the_app_store_by_its_tables(store, tmp_path):
    assert flighty.sniff(store)
    assert adapters.find(store) is flighty
    import sqlite3

    other = tmp_path / "other.db"
    con = sqlite3.connect(other)
    con.execute("CREATE TABLE Flight (id TEXT)")
    con.commit()
    con.close()
    assert not flighty.sniff(other)


def test_the_store_gives_the_same_line_as_the_export_so_the_two_dedupe(store):
    from_csv = _by_number(_drafts(), "561")
    from_store = _by_number(_drafts(store), "561")
    assert from_store == from_csv
    assert from_store["payload"]["raw_id"] == from_csv["payload"]["raw_id"]


def test_the_store_maps_diversions_cancellations_and_the_stores_own_zones(store):
    counts: dict[str, int] = {}
    drafts = list(flighty.run(store, counts=counts))
    assert len(drafts) == STORE_LINES
    assert [d["payload"]["raw_id"].split("@")[0] for d in drafts] == [
        "fx-0001",
        "fx-0003",
        "fx-0004",
        "fx-0007",
    ]
    diverted = _by_number(drafts, "1210")
    p = diverted["payload"]
    assert p["carrier"] == "LX" and p["carrier_icao"] == "SWR"
    assert p["to"] == {"iata": "OSL", "icao": "ENGM"} and p["diverted_to"] == {"iata": "BGO", "icao": "ENBR"}
    assert p["date"] == "2026-09-28" and p["scheduled_departure"] == "2026-09-28T15:00:00Z"
    assert p["actual_arrival"] == "2026-09-28T18:02:00Z" and "actual_departure" not in p
    assert p["extra"] == {
        "departure_terminal": "1",
        "departure_gate": "B12",
        "seat": "12C",
        "seat_type": "aisle",
        "cabin": "economy",
        "reason": "personal",
    }
    cancelled = _by_number(drafts, "460")
    assert cancelled["payload"]["cancelled"] is True and cancelled["payload"]["carrier"] == "SK"
    assert "aircraft" not in cancelled["payload"] and "extra" not in cancelled["payload"]
    far = _by_number(drafts, "77")
    assert far["payload"]["from"] == {"iata": "XQX", "icao": "ZZZZ"}
    assert (
        far["payload"]["date"] == "2026-11-02" and far["tz"] == "Pacific/Auckland"
    )  # NZDT: 09:00 on the 2nd
    assert counts == {"skipped_no_date": 1, "skipped_no_designator": 1}  # the store knew the zone


def test_the_pnr_never_leaves_the_store(store):
    assert PNR not in json.dumps(list(flighty.run(store)))


def test_store_since_and_dedupe_against_the_export(store, tmp_path, monkeypatch):
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    lb = Logbook.init(root, "Europe/Oslo")
    assert lb.append_many(flights.reconcile(lb, _drafts())) == LINES
    counts: dict[str, int] = {}
    added = lb.append_many(flights.reconcile(lb, flighty.run(store), counts))
    assert added == STORE_LINES - 1 and counts["merged"] == 1  # 561 is the same observation; 1210 a newer one
    later = list(flighty.run(store, since="2026-10-01T00:00:00Z"))
    assert [d["payload"]["number"] for d in later] == ["460", "77"]
