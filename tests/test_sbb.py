"""The SBB Mobile app's stores → trip/v1 (RFC 0020, mode `transit`): bought tickets from `SbbMobile.db`
and the journeys the owner saved and took from `ch.sbb.coredata.pasttrips.sqlite`; names of travellers,
QR codes and order references never copied."""

from __future__ import annotations

import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import cli
from logbook.contrib import adapters
from logbook.contrib.adapters import sbb
from logbook.core.store import Logbook

TZ = "Europe/Oslo"

MOBILE_DDL = """
CREATE TABLE PurchasedTickets (ticketId TEXT PRIMARY KEY, dossierId TEXT, infoLine TEXT,
    screenTicket_contentHtml TEXT,
    b2b TEXT, ticketType TEXT, validFrom TEXT, validUntil TEXT, screenTicket_qrCodeContent TEXT,
    wallet_applePassbookContent BLOB, refundState TEXT, traveler TEXT, travelClass TEXT, discountCard TEXT,
    paymentMethodType TEXT, displayInfo_ticketType TEXT, displayInfo_additionalInfo TEXT,
    displayInfo_titleLine_firstSegment TEXT, displayInfo_titleLine_lastSegment TEXT,
    displayInfo_titleLine_tripType TEXT, localUserId TEXT, orderItemId TEXT, nativeTicket_price_currency TEXT,
    nativeTicket_price_amount REAL, nativeTicket_productName TEXT, nativeTicket_ticketHolder TEXT,
    nativeTicket_ticketHolderDateOfBirth TEXT, nativeTicket_qrCodeContent TEXT);
CREATE TABLE TicketGroups (groupId TEXT PRIMARY KEY, orderItemIds BLOB, travelDate TEXT, validFrom TEXT,
    validUntil TEXT, displayInfo_titleLine_firstSegment TEXT, displayInfo_titleLine_lastSegment TEXT,
    displayInfo_titleLine_tripType TEXT, displayInfo_ticketTypeLine TEXT, displayInfo_additionalInfoLine TEXT,
    travelGroup_numberOfBikes INTEGER, travelGroup_numberOfDogs INTEGER, travelGroup_numberOfPersons INTEGER,
    notifications BLOB, reservations BLOB, showTicketGroupDetails INTEGER, numberPlate TEXT);
"""
TRIPS_DDL = """
CREATE TABLE ZMYTRIP (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZALARM INTEGER,
    ZISSUPERSAVER INTEGER,
    ZABFAHRTDATE VARCHAR, ZDOSSIERID VARCHAR, ZRECONSTRUCTIONCONTEXT VARCHAR, ZVERBINDUNG VARCHAR,
    ZTICKETIDS VARCHAR);
"""
PERSON = "Kari Nordmann"  # the Oslo persona; must never reach a line
# ticketId, orderItemId, validFrom, validUntil, refund, class, product, price, currency, first, last,
# trip type
TICKETS = [
    ("T-1", "O-1", "2026-03-02 00-00", "2026-03-03 05-00", "NORMAL", "SECOND", "Sparbillett", 29.0, "CHF",
     "Zürich HB", "Bern", "OUTWARDS"),
    ("T-2", "O-2", "2026-03-02 00-00", "2026-03-03 05-00", "NORMAL", "SECOND", "Sparbillett", 29.0, "CHF",
     "Zürich HB", "Bern", "OUTWARDS"),
    ("T-3", "O-3", "2026-03-09 00-00", "2026-03-10 05-00", "NORMAL", "FIRST", None, None, None,
     "Zürich HB", "Milano Centrale", "OUTWARDS"),
    ("T-4", "O-4", "2026-03-12 00-00", "2026-03-13 05-00", "REFUNDED", "SECOND", "Tageskarte", 75.0, "CHF",
     "Basel SBB", "Basel SBB", "RETURN"),
]  # fmt: skip
# groupId, order item ids, travel date, validFrom, validUntil, first, last, trip type, type line, info,
# persons
GROUPS = [
    ("G-1", ["O-1", "O-2"], "2026-03-02", "2026-03-02 00-00", "2026-03-03 05-00", "Zürich HB", "Bern",
     "OUTWARDS", "Sparbillett", None, 2),
    ("G-3", ["O-3"], "2026-03-09", "2026-03-09 00-00", "2026-03-10 05-00", "Zürich HB", "Milano Centrale",
     "OUTWARDS", "Flexpreis Europa", "via Gotthard", 1),
    ("G-4", ["O-4"], "2026-03-12", "2026-03-12 00-00", "2026-03-13 05-00", "Basel SBB", "Basel SBB", "RETURN",
     "Tageskarte", None, 1),
    ("G-5", ["O-9"], "2026-03-15", None, None, "Genève", "Lausanne", "OUTWARDS", "Sparbillett", None, 1),
]  # fmt: skip


ZH, OL, BE = (47.378, 8.540), (47.352, 7.908), (46.949, 7.439)
BE_BF, ZYT = (46.948, 7.440), (46.948, 7.448)


def _coords(lat: float, lon: float) -> dict[str, float]:
    return {"latitude": 0, "longitude": 0, "latitudeInDegrees": lat, "longitudeInDegrees": lon}


def _transport(icon: str, label: str, text: str) -> dict[str, str]:
    return {
        "oevIcon": icon,
        "transportIcon": label,
        "transportLabel": "8",
        "transportText": text,
        "transportDirection": "",
    }


def _section(
    start: str,
    end: str,
    dep: str,
    arr: str,
    icon: str | None,
    label: str,
    text: str,
    coords: tuple[float, ...],
) -> dict[str, Any]:
    d1, t1 = start.split(" ")
    d2, t2 = end.split(" ")
    return {
        "type": 0,
        "abfahrtDatum": d1,
        "abfahrtTime": t1,
        "abfahrtName": dep,
        "abfahrtGleis": "7",
        "abfahrtKoordinaten": _coords(coords[0], coords[1]),
        "ankunftDatum": d2,
        "ankunftTime": t2,
        "ankunftName": arr,
        "ankunftKoordinaten": _coords(coords[2], coords[3]),
        "transportBezeichnung": None if icon is None else _transport(icon, label, text),
        "realtimeInfo": {
            "abfahrtIstDatum": d1, "abfahrtIstZeit": t1, "ankunftIstDatum": d2, "ankunftIstZeit": t2,
            "abfahrtCancellation": False, "ankunftCancellation": False,
        },
    }  # fmt: skip


TRIP_1 = {  # two legs with a change, three minutes late at the end
    "verbindungId": "V-1",
    "abfahrt": "Zürich HB",
    "ankunft": "Bern",
    "abfahrtDate": "02.03.2026",
    "abfahrtTime": "08:02",
    "ankunftDate": "02.03.2026",
    "ankunftTime": "09:26",
    "transfers": 1,
    "duration": "1 h 24 min",
    "isInternationalVerbindung": False,
    "realtimeInfo": {
        "abfahrtIstDatum": "02.03.2026", "abfahrtIstZeit": "08:02", "ankunftIstDatum": "02.03.2026",
        "ankunftIstZeit": "09:29", "isAlternative": False, "platformChange": False,
    },
    "verbindungSections": [
        _section("02.03.2026 08:02", "02.03.2026 08:58", "Zürich HB", "Olten", "ZUG", "IC", "IC 8", ZH + OL),
        _section("02.03.2026 09:04", "02.03.2026 09:26", "Olten", "Bern", "ZUG", "IR", "IR 16", OL + BE),
    ],
}  # fmt: skip
TRIP_2 = {  # one leg over midnight, abroad
    "verbindungId": "V-2",
    "abfahrt": "Zürich HB",
    "ankunft": "Milano Centrale",
    "abfahrtDate": "09.03.2026",
    "abfahrtTime": "22:33",
    "ankunftDate": "10.03.2026",
    "ankunftTime": "02:10",
    "transfers": 0,
    "duration": "3 h 37 min",
    "isInternationalVerbindung": True,
    "realtimeInfo": {},
    "verbindungSections": [
        _section("09.03.2026 22:33", "10.03.2026 02:10", "Zürich HB", "Milano Centrale", "ZUG", "EC", "EC 57",
                 (47.378, 8.540, 45.486, 9.204)),
    ],
}  # fmt: skip
TRIP_3 = {  # a walk and a bus, no realtime; the mode of the trip is the ride's
    "verbindungId": "V-3",
    "abfahrt": "Bern",
    "ankunft": "Bern, Zytglogge",
    "abfahrtDate": "02.03.2026",
    "abfahrtTime": "09:30",
    "ankunftDate": "02.03.2026",
    "ankunftTime": "09:41",
    "transfers": 0,
    "duration": "11 min",
    "isInternationalVerbindung": False,
    "verbindungSections": [
        _section("02.03.2026 09:30", "02.03.2026 09:34", "Bern", "Bern, Bahnhof", None, "", "", BE + BE_BF),
        _section(
            "02.03.2026 09:34", "02.03.2026 09:41", "Bern, Bahnhof", "Bern, Zytglogge", "BUS", "B", "12",
            BE_BF + ZYT,
        ),
    ],
}  # fmt: skip
TRIPS = [
    (1, "02.03.2026", json.dumps(TRIP_1)),
    (2, "09.03.2026", json.dumps(TRIP_2)),
    (3, "02.03.2026", json.dumps(TRIP_3)),
    (4, "01.03.2026", "{not json"),
]
TICKET_LINES = 3  # G-1, G-3, G-4; G-5 has no validity
TRIP_LINES = 3
LINES = TICKET_LINES + TRIP_LINES
SKIPS = {"skipped_no_start": 1, "skipped_unreadable_json": 1}


def _mobile_store(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / "SbbMobile.db"
    with closing(sqlite3.connect(p)) as con:
        con.executescript(MOBILE_DDL)
        for tid, oid, start, end, refund, klass, product, amount, currency, first, last, trip_type in TICKETS:
            con.execute(
                "INSERT INTO PurchasedTickets VALUES (" + ",".join("?" * 28) + ")",
                (tid, f"D-{tid}", f"Gültig {start[:10]}", "<html>…</html>", "0", None, start, end,
                 "QR-SECRET", b"pkpass", refund, PERSON, klass, None, "MASTER_CARD",
                 product or "Screen ticket", None, first,
                 last, trip_type, "U-1", oid, currency, amount, product, PERSON, "1980-01-01", "QR-SECRET"),
            )  # fmt: skip
        for gid, oids, day, start, end, first, last, trip_type, type_line, info, persons in GROUPS:
            con.execute(
                "INSERT INTO TicketGroups VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (gid, json.dumps(oids).encode(), day, start, end, first, last, trip_type, type_line, info, 0,
                 0, persons, b"[]", b"[]", 1, None),
            )  # fmt: skip
        con.commit()
    return p


def _trips_store(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / "ch.sbb.coredata.pasttrips.sqlite"
    with closing(sqlite3.connect(p)) as con:
        con.executescript(TRIPS_DDL)
        for pk, day, verbindung in TRIPS:
            con.execute(
                "INSERT INTO ZMYTRIP VALUES (?,?,?,?,?,?,?,?,?,?)",
                (pk, 1, 1, 0, 0, day, None, "ctx", verbindung, None),
            )
        con.commit()
    return p


def _stores(folder: Path) -> Path:
    """Both stores beside each other, as `import-backup` lays them out; the SbbMobile.db path."""
    _trips_store(folder)
    return _mobile_store(folder)


def _lines(tmp_path: Path, **kw: Any) -> list[dict[str, Any]]:
    return list(sbb.run(_stores(tmp_path / "sbb"), **kw))


def _by_raw_id(lines: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {line["payload"]["raw_id"]: line for line in lines}


# -- registry and sniff ----------------------------------------------------------------------------


def test_registry_lists_sbb():
    assert sbb in adapters.file_adapters()
    assert adapters.named("sbb") is sbb


def test_sniff_takes_either_store_and_nothing_else(tmp_path):
    mobile = _stores(tmp_path / "s")
    assert sbb.sniff(mobile) and sbb.sniff(mobile.parent / "ch.sbb.coredata.pasttrips.sqlite")
    other = tmp_path / "other.sqlite"
    with closing(sqlite3.connect(other)) as con:
        con.execute("CREATE TABLE PurchasedTickets (x)")
    assert not sbb.sniff(other)  # tickets without groups is not the store
    assert not sbb.sniff(tmp_path / "missing.db")


# -- the lines -------------------------------------------------------------------------------------


def test_every_line_is_a_trip_line_in_the_rfc_shape_and_names_nobody(tmp_path):
    lines = _lines(tmp_path)  # the clocks are the app's, Swiss time: the record's zone is not asked for
    assert len(lines) == LINES
    for line in lines:
        assert set(line) == {"at", "end", "tz", "source", "kind", "tier", "payload"}
        assert (line["source"], line["kind"], line["tz"]) == ("sbb", "journey", "Europe/Zurich")
        p = line["payload"]
        assert p["schema"] == "journey/v1" and p["mode"] == "transit" and p["provider"] == "sbb"
        assert set(p["from"]) <= {"name", "latitude", "longitude"} and p["from"]["name"]
        assert set(p["to"]) <= {"name", "latitude", "longitude"} and p["to"]["name"]
        text = json.dumps(line)
        for secret in (PERSON, "QR-SECRET", "D-T-", "U-1", "1980-01-01", "<html>"):
            assert secret not in text, secret
    assert [line["at"] for line in lines] == sorted(line["at"] for line in lines)


def test_a_ticket_group_is_one_trip_with_its_validity_price_and_class(tmp_path):
    line = _by_raw_id(_lines(tmp_path))["ticket:G-1"]
    assert (line["at"], line["end"], line["tier"]) == ("2026-03-01T23:00:00Z", "2026-03-03T04:00:00Z", 3)
    assert line["payload"] == {
        "schema": "journey/v1",
        "raw_id": "ticket:G-1",
        "mode": "transit",
        "provider": "sbb",
        "from": {"name": "Zürich HB"},
        "to": {"name": "Bern"},
        "price": {"amount": "58.00", "currency": "CHF"},
        "extra": {
            "observed": "ticket",
            "travel_date": "2026-03-02",
            "ticket_type": "Sparbillett",
            "trip_type": "outwards",
            "travel_class": "second",
            "persons": 2,
            "tickets": 2,
        },
    }


def test_a_ticket_without_a_price_is_tier_1_and_a_refunded_one_is_cancelled(tmp_path):
    by = _by_raw_id(_lines(tmp_path))
    milan = by["ticket:G-3"]
    assert milan["tier"] == 1 and "price" not in milan["payload"] and "status" not in milan["payload"]
    assert (
        milan["payload"]["extra"]["travel_class"] == "first"
        and milan["payload"]["extra"]["note"] == "via Gotthard"
    )
    refunded = by["ticket:G-4"]["payload"]
    assert refunded["status"] == "cancelled" and refunded["price"] == {"amount": "75.00", "currency": "CHF"}
    assert refunded["extra"]["trip_type"] == "return"


def test_a_past_journey_is_one_trip_with_its_legs_and_the_real_arrival(tmp_path):
    line = _by_raw_id(_lines(tmp_path))["trip:V-1"]
    assert (line["at"], line["end"], line["tier"]) == ("2026-03-02T07:02:00Z", "2026-03-02T08:26:00Z", 1)
    p = line["payload"]
    assert p["from"] == {"name": "Zürich HB", "latitude": 47.378, "longitude": 8.54}
    assert p["to"] == {"name": "Bern", "latitude": 46.949, "longitude": 7.439}
    assert "price" not in p
    assert p["extra"] == {
        "observed": "journey",
        "transfers": 1,
        "actual_end": "2026-03-02T08:29:00Z",
        "legs": [
            {"from": "Zürich HB", "to": "Olten", "start": "2026-03-02T07:02:00Z",
             "end": "2026-03-02T07:58:00Z", "mode": "train", "line": "IC 8"},
            {"from": "Olten", "to": "Bern", "start": "2026-03-02T08:04:00Z", "end": "2026-03-02T08:26:00Z",
             "mode": "train", "line": "IR 16"},
        ],
    }  # fmt: skip


def test_a_journey_over_midnight_abroad_and_one_with_a_walk_and_a_bus(tmp_path):
    by = _by_raw_id(_lines(tmp_path))
    milan = by["trip:V-2"]
    assert (milan["at"], milan["end"]) == ("2026-03-09T21:33:00Z", "2026-03-10T01:10:00Z")
    assert (
        milan["payload"]["extra"]["international"] is True and "actual_end" not in milan["payload"]["extra"]
    )
    bus = by["trip:V-3"]["payload"]
    assert [leg["mode"] for leg in bus["extra"]["legs"]] == ["walk", "bus"]
    assert bus["extra"]["legs"][1]["line"] == "12" and "line" not in bus["extra"]["legs"][0]


def test_skips_are_counted(tmp_path):
    counts: dict[str, int] = {}
    assert len(_lines(tmp_path, counts=counts)) == LINES
    assert {k: v for k, v in counts.items() if k.startswith("skipped_")} == SKIPS


def test_either_store_alone_gives_its_own_lines(tmp_path):
    tickets = list(sbb.run(_mobile_store(tmp_path / "m")))
    assert len(tickets) == TICKET_LINES and all(
        line["payload"]["extra"]["observed"] == "ticket" for line in tickets
    )
    trips = list(sbb.run(_trips_store(tmp_path / "t")))
    assert len(trips) == TRIP_LINES and all(
        line["payload"]["extra"]["observed"] == "journey" for line in trips
    )
    assert len(list(sbb.run(_stores(tmp_path / "both").parent / "ch.sbb.coredata.pasttrips.sqlite"))) == LINES


def test_since_and_tier(tmp_path):
    # G-3's validity began at 23:00Z the day before, so it is before `since`
    lines = _lines(tmp_path, since="2026-03-09T00:00:00Z", tier=2)
    assert sorted(line["payload"]["raw_id"] for line in lines) == ["ticket:G-4", "trip:V-2"]
    assert {line["tier"] for line in lines} == {2}


def test_the_stores_are_never_written(tmp_path):
    store = _stores(tmp_path / "s")
    before = {p.name: p.read_bytes() for p in store.parent.iterdir()}
    list(sbb.run(store))
    assert {p.name: p.read_bytes() for p in store.parent.iterdir()} == before


# -- through the CLI --------------------------------------------------------------------------------


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook.init(root, TZ)


def test_add_sbb_appends_once_and_show_prints_the_route(lb, tmp_path, capsys):
    store = _stores(tmp_path / "s")
    cli.main(["add", "sbb", str(store)])
    out = capsys.readouterr().out
    assert f"added {LINES} lines from sbb" in out and "1 without a start" in out
    cli.main(["add", "sbb", str(store)])
    assert "added 0 lines" in capsys.readouterr().out
    cli.main(["show", "2026-03-02"])
    out = capsys.readouterr().out
    assert "journey" in out and "Zürich HB → Bern" in out and "58.00 CHF" in out and "1 change" in out
    assert PERSON not in out
    seq, _head, errors = lb.verify()
    assert (seq, errors) == (LINES, [])
