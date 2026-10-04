"""`logbook infer flights` (RFC 0013, evidence `inferred`): a calendar entry that names a flight plus
a leg in the location points from the last point at one airport to the first at another."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook.contrib.adapters import flighty
from logbook.core import flights
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
FLIGHTY = ROOT / "tests" / "fixtures" / "flighty" / "export.csv"
OSL = (60.1939, 11.1004)
ZRH = (47.4581, 8.5481)
OSLO_CITY = (59.913, 10.752)


def _event(at: str, end: str | None, title: str, **payload: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"schema": "event/v1", "raw_id": f"{title}@{at}", "title": title, "all_day": False}
    body.update(payload)
    return {"at": at, "end": end, "source": "ics", "kind": "event", "tier": 1, "payload": body}


def _point(at: str, where: tuple[float, float], source: str = "dawarich") -> dict[str, Any]:
    lat, lon = where
    return {
        "at": at,
        "source": source,
        "kind": "location",
        "tier": 1,
        "payload": {"schema": "location/v1", "lat": lat, "lon": lon, "raw_id": f"{source}:{at}"},
    }


def _track(start: str, where: tuple[float, float], minutes: int, every: int = 10) -> list[dict[str, Any]]:
    """Points at one place from `start`, one every `every` minutes for `minutes`."""
    first = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(UTC)
    stamps = [first + timedelta(minutes=m) for m in range(0, minutes + 1, every)]
    return [_point(s.strftime("%Y-%m-%dT%H:%M:%SZ"), where) for s in stamps]


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    return lb


def _flight_day(lb: Logbook, title: str = "Flight to Zurich (XY 561)", **event: Any) -> None:
    """The calendar says XY 561 at 07:05 to 09:20 local; the phone was at Oslo airport until 05:02Z,
    silent in the air, then at Zürich airport from 07:18Z."""
    lb.append_many(
        [
            _event("2026-09-27T05:05:00Z", "2026-09-27T07:20:00Z", title, **event),
            *_track("2026-09-27T04:30:00Z", OSL, 32, every=8),  # 04:30 … 05:02
            *_track("2026-09-27T07:18:00Z", ZRH, 20),
            *_track("2026-09-27T09:00:00Z", (47.37, 8.54), 60),  # Zürich city
        ]
    )


def _infer(lb: Logbook, **options: Any) -> list[dict[str, Any]]:
    return list(flights.infer(lb, flights.Airports.load(), **options))


def test_infer_a_calendar_flight_with_a_gap_between_two_airports(lb: Logbook):
    _flight_day(lb)
    counts: dict[str, int] = {}
    (d,) = _infer(lb, counts=counts)
    p = d["payload"]
    assert d["source"] == "flight-inference" and d["kind"] == "flight" and d["tier"] == 1
    assert p["evidence"] == "inferred" and p["role"] == "passenger"
    assert (p["date"], p["carrier"], p["number"]) == ("2026-09-27", "XY", "561")
    assert p["from"] == {"iata": "OSL", "icao": "ENGM"} and p["to"] == {"iata": "ZRH", "icao": "LSZH"}
    assert (
        p["scheduled_departure"] == "2026-09-27T05:05:00Z"
        and p["scheduled_arrival"] == "2026-09-27T07:20:00Z"
    )
    assert p["actual_departure"] == "2026-09-27T05:02:00Z" and p["actual_arrival"] == "2026-09-27T07:18:00Z"
    assert (
        d["at"] == "2026-09-27T05:02:00Z" and d["end"] == "2026-09-27T07:18:00Z" and d["tz"] == "Europe/Oslo"
    )
    assert p["raw_id"] == "2026-09-27:XY:561@2026-09-27T05:02:00Z/2026-09-27T07:18:00Z"
    assert p["observations"] == [{"evidence": "inferred", "source": "flight-inference"}]
    with lb.index() as idx:
        event = idx.by_kind("event")[0]
        points = idx.by_kind("location")
    assert p["extra"]["event"] == event["id"]
    assert p["extra"]["gap"] == [points[4]["id"], points[5]["id"]]
    assert counts == {"calendar_flights": 1}


def _between(a: tuple[float, float], b: tuple[float, float], fraction: float) -> tuple[float, float]:
    return a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction


def test_infer_a_phone_that_logs_through_the_climb_still_gives_the_flight(lb: Logbook):
    """The tracker keeps logging on the take-off roll and the climb, so the silence starts from a
    point in the air, near no airport: the flight is still the last point at Oslo airport to the
    first at Zürich airport."""
    lb.append_many(
        [
            _event("2026-09-27T05:05:00Z", "2026-09-27T07:20:00Z", "Flight to Zurich (XY 561)"),
            *_track("2026-09-27T04:30:00Z", OSL, 32, every=8),  # 04:30 … 05:02
            _point("2026-09-27T05:04:00Z", _between(OSL, ZRH, 0.02)),
            _point("2026-09-27T05:07:00Z", _between(OSL, ZRH, 0.05)),
            _point("2026-09-27T05:12:00Z", _between(OSL, ZRH, 0.1)),
            *_track("2026-09-27T07:18:00Z", ZRH, 20),
        ]
    )
    (d,) = _infer(lb)
    p = d["payload"]
    assert p["from"]["iata"] == "OSL" and p["to"]["iata"] == "ZRH"
    assert p["actual_departure"] == "2026-09-27T05:02:00Z" and p["actual_arrival"] == "2026-09-27T07:18:00Z"
    with lb.index() as idx:
        points = idx.by_kind("location")
    assert p["extra"]["gap"] == [points[4]["id"], points[8]["id"]]


def test_infer_a_phone_that_logs_the_whole_flight_gives_it_without_any_silence(lb: Logbook):
    """Points every ten minutes from Oslo airport to Zürich airport, none near any airport in
    between and no silence at all: still one flight."""
    aloft = [
        _point(
            f"2026-09-27T{5 + (10 + 10 * i) // 60:02d}:{(10 + 10 * i) % 60:02d}:00Z", _between(OSL, ZRH, f)
        )
        for i, f in enumerate((0.15, 0.3, 0.45, 0.6, 0.75, 0.9))
    ]
    lb.append_many(
        [
            _event("2026-09-27T05:05:00Z", "2026-09-27T07:20:00Z", "Flight XY 561"),
            *_track("2026-09-27T04:30:00Z", OSL, 30),  # 04:30 … 05:00
            *aloft,  # 05:10 … 06:00
            *_track("2026-09-27T07:18:00Z", ZRH, 20),
        ]
    )
    counts: dict[str, int] = {}
    (d,) = _infer(lb, counts=counts)
    p = d["payload"]
    assert p["from"]["iata"] == "OSL" and p["to"]["iata"] == "ZRH"
    assert p["actual_departure"] == "2026-09-27T05:00:00Z" and p["actual_arrival"] == "2026-09-27T07:18:00Z"
    assert counts == {"calendar_flights": 1}


def test_infer_date_is_the_local_date_at_the_origin_of_the_scheduled_departure(lb: Logbook):
    """22:30Z on the 26th is 00:30 on the 27th in Oslo: the flight is dated the 27th."""
    lb.append_many(
        [
            _event("2026-09-26T22:30:00Z", "2026-09-27T00:45:00Z", "Flight XY 561"),
            *_track("2026-09-26T21:50:00Z", OSL, 30),
            *_track("2026-09-27T00:40:00Z", ZRH, 20),
        ]
    )
    (d,) = _infer(lb)
    assert d["payload"]["date"] == "2026-09-27"


def test_infer_without_a_gap_nothing_is_inferred_and_it_is_counted(lb: Logbook):
    lb.append_many(
        [
            _event("2026-09-27T05:05:00Z", "2026-09-27T07:20:00Z", "Flight to Zurich (XY 561)"),
            *_track("2026-09-27T04:00:00Z", OSLO_CITY, 300),  # at home all morning
        ]
    )
    counts: dict[str, int] = {}
    assert _infer(lb, counts=counts) == []
    assert counts == {"calendar_flights": 1, "no_gap": 1}


def test_infer_a_gap_that_starts_and_ends_at_the_same_airport_is_not_a_flight(lb: Logbook):
    lb.append_many(
        [
            _event("2026-09-27T05:05:00Z", "2026-09-27T07:20:00Z", "Flight XY 561"),
            *_track("2026-09-27T04:30:00Z", OSL, 30),
            *_track("2026-09-27T07:30:00Z", OSL, 30),
        ]
    )
    counts: dict[str, int] = {}
    assert _infer(lb, counts=counts) == []
    assert counts == {"calendar_flights": 1, "no_gap": 1}


def test_infer_ignores_entries_that_do_not_name_a_flight_and_cancelled_ones(lb: Logbook):
    _flight_day(lb, title="Q3 review")
    assert _infer(lb) == []
    lb.append_many(
        [_event("2026-09-27T05:05:00Z", "2026-09-27T07:20:00Z", "Flight XY 561", status="cancelled")]
    )
    assert _infer(lb) == []


def test_infer_reads_the_latest_version_of_an_edited_entry(lb: Logbook):
    _flight_day(lb, title="Flight XY 560")
    with lb.index() as idx:
        old = idx.by_kind("event")[0]
    lb.append_many(
        [_event("2026-09-27T05:05:00Z", "2026-09-27T07:20:00Z", "Flight XY 561", supersedes=old["id"])]
    )
    (d,) = _infer(lb)
    assert d["payload"]["number"] == "561"


def test_infer_all_day_entry_has_no_scheduled_times_and_searches_the_day(lb: Logbook):
    lb.append_many(
        [
            _event("2026-09-26T22:00:00Z", "2026-09-27T22:00:00Z", "Flight XY 561", all_day=True),
            *_track("2026-09-27T04:30:00Z", OSL, 30),
            *_track("2026-09-27T07:18:00Z", ZRH, 20),
        ]
    )
    (d,) = _infer(lb)
    p = d["payload"]
    assert "scheduled_departure" not in p and p["actual_departure"] == "2026-09-27T05:00:00Z"
    assert p["date"] == "2026-09-27"


def test_infer_since_and_until_bound_the_days_considered(lb: Logbook):
    _flight_day(lb)
    assert _infer(lb, since="2026-09-28") == []
    assert _infer(lb, until="2026-09-26") == []
    assert len(_infer(lb, since="2026-09-27", until="2026-09-27")) == 1


def test_infer_airports_override_places_a_private_field(lb: Logbook, tmp_path: Path):
    field = (60.5, 11.5)
    lb.append_many(
        [
            _event("2026-09-27T05:05:00Z", "2026-09-27T07:20:00Z", "Flight XY 561"),
            *_track("2026-09-27T04:30:00Z", field, 30),
            *_track("2026-09-27T07:18:00Z", ZRH, 20),
        ]
    )
    assert list(flights.infer(lb, flights.Airports.load())) == []
    override = tmp_path / "airports.csv"
    override.write_text("iata,lat,lon,tz\nZZZ,60.5,11.5,Europe/Oslo\n", encoding="utf-8")
    (d,) = flights.infer(lb, flights.Airports.load(override))
    assert d["payload"]["from"] == {"iata": "ZZZ"}


def _cli(lb: Logbook, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "LOGBOOK_HOME": str(lb.root), "PYTHONPATH": str(ROOT)}
    return subprocess.run(
        [sys.executable, "-m", "logbook.cli", *args], env=env, capture_output=True, encoding="utf-8"
    )


def test_cli_infer_flights_writes_once_and_reports(lb: Logbook):
    _flight_day(lb)
    r = _cli(lb, "derive", "flights", "--dry-run")
    assert r.returncode == 0, r.stderr
    assert "1 flight" in r.stdout and "dry run" in r.stdout and lb.meta["seq"] == 16
    r = _cli(lb, "derive", "flights")
    assert r.returncode == 0, r.stderr
    assert "inferred 1 new flight from 1 calendar entry" in r.stdout
    assert lb.meta["seq"] == 17
    r = _cli(lb, "derive", "flights")
    assert "inferred 0 new flights from 1 calendar entry (1 already in the record)" in r.stdout
    assert lb.meta["seq"] == 17
    assert "XY 561 OSL → ZRH, arrives 09:18, inferred" in _cli(lb, "show", "2026-09-27").stdout


def test_cli_infer_counts_one_flight_however_many_entries_name_it(lb: Logbook):
    """Two calendars, two spellings, one flight: the dry run and the real run both say one."""
    lb.append_many(
        [
            _event("2026-09-27T05:05:00Z", "2026-09-27T07:20:00Z", "Flight to Zürich (XY 561)"),
            _event("2026-09-27T05:05:00Z", "2026-09-27T07:20:00Z", "Flug XY561 nach Zürich"),
            {
                **_event("2026-09-27T05:05:00Z", "2026-09-27T07:20:00Z", "Flight to Zürich (XY 561)"),
                "source": "ios-calendar",
            },
            {
                **_event("2026-09-27T05:05:00Z", "2026-09-27T07:20:00Z", "Flug XY561 nach Zürich"),
                "source": "ios-calendar",
            },
            *_track("2026-09-27T04:30:00Z", OSL, 32, every=8),
            *_track("2026-09-27T07:18:00Z", ZRH, 20),
        ]
    )
    r = _cli(lb, "derive", "flights", "--dry-run")
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("dry run: 1 flight from 4 calendar entries would be written")
    assert "merged" not in r.stdout
    r = _cli(lb, "derive", "flights")
    assert r.stdout.startswith("inferred 1 new flight from 4 calendar entries\n")
    r = _cli(lb, "derive", "flights", "--dry-run")
    assert r.stdout.startswith(
        "dry run: 0 flights from 4 calendar entries would be written (1 already in the record)"
    )
    r = _cli(lb, "derive", "flights")
    assert r.stdout.startswith("inferred 0 new flights from 4 calendar entries (1 already in the record)")


def test_cli_infer_after_flighty_attaches_to_the_tracked_flight(lb: Logbook):
    _flight_day(lb)
    lb.append_many(flighty.run(FLIGHTY))
    r = _cli(lb, "derive", "flights")
    assert r.returncode == 0, r.stderr
    assert "1 merged into a flight already in the record" in r.stdout
    with lb.index() as idx:
        last = flights.standing(idx.by_kind("flight"))
    p = last[("2026-09-27", "XY", "561")]["payload"]
    assert p["evidence"] == "tracked" and p["actual_departure"] == "2026-09-27T05:10:00Z"
    assert [o["evidence"] for o in p["observations"]] == ["tracked", "inferred"]
    assert "supersedes" in p


def test_cli_infer_rejects_anything_but_flights(lb: Logbook):
    r = _cli(lb, "derive", "trips")
    assert r.returncode == 2 and "flights" in r.stderr


# -- what a leg is not -------------------------------------------------------------------------------------

IST = (41.2749, 28.7321)
DUS = (51.2895, 6.7668)
CGN = (50.8659, 7.1427)


def test_infer_a_leg_that_is_not_the_tracked_flight_the_entry_names_carries_no_number(lb: Logbook):
    """The calendar's two-day entry names XY 123, which Flighty tracked OSL→ZRH on the first day;
    the points then show ZRH→IST on the second, the longer leg. That leg is a flight the record
    has no number for: it is written with neither carrier nor number, never XY 123's."""
    from persona import flight

    lb.append_many(
        [
            flight("2026-09-27", "123", "OSL", "ZRH", "2026-09-27T08:00:00Z", "2026-09-27T10:00:00Z"),
            _event("2026-09-26T22:00:00Z", "2026-09-28T22:00:00Z", "Flight XY 123", all_day=True),
            *_track("2026-09-27T06:00:00Z", OSL, 115, every=5),  # 06:00 … 07:55
            *_track("2026-09-27T10:05:00Z", ZRH, 20),
            *_track("2026-09-28T07:00:00Z", ZRH, 50),  # the next day, 07:00 … 07:50
            *_track("2026-09-28T10:10:00Z", IST, 20),
        ]
    )
    (d,) = _infer(lb)
    p = d["payload"]
    assert p["from"]["iata"] == "ZRH" and p["to"]["iata"] == "IST" and p["date"] == "2026-09-28"
    assert "number" not in p and "carrier" not in p and "carrier_icao" not in p
    assert flights.key(p) == ("2026-09-28", "", "ZRH>IST")
    assert p["raw_id"].startswith("2026-09-28::ZRH>IST@")
    r = _cli(lb, "derive", "flights")
    assert r.returncode == 0 and r.stdout.startswith("inferred 1 new flight"), r.stdout + r.stderr
    assert "flight-inference ZRH → IST, arrives 12:10, inferred" in _cli(lb, "show", "2026-09-28").stdout


def test_infer_the_entry_keeps_its_number_when_the_leg_is_the_flight_it_names(lb: Logbook):
    """The same two-day entry, but the points show only the tracked leg: the inference is XY 123 and
    merges into the tracked flight (the existing behaviour, unchanged)."""
    from persona import flight

    lb.append_many(
        [
            flight("2026-09-27", "123", "OSL", "ZRH", "2026-09-27T08:00:00Z", "2026-09-27T10:00:00Z"),
            _event("2026-09-26T22:00:00Z", "2026-09-28T22:00:00Z", "Flight XY 123", all_day=True),
            *_track("2026-09-27T06:00:00Z", OSL, 115, every=5),
            *_track("2026-09-27T10:05:00Z", ZRH, 20),
        ]
    )
    (d,) = _infer(lb)
    assert (d["payload"]["carrier"], d["payload"]["number"]) == ("XY", "123")


def test_infer_a_leg_between_airports_under_150_km_is_a_drive_not_a_flight(lb: Logbook):
    """Düsseldorf to Cologne is 54 km: the points leave one airport and reach the other, but nobody
    flew; nothing is inferred and the entry counts as unconfirmed."""
    lb.append_many(
        [
            _event("2026-09-27T08:00:00Z", "2026-09-27T09:00:00Z", "Flight XY 561"),
            *_track("2026-09-27T07:30:00Z", DUS, 30),
            *_track("2026-09-27T09:10:00Z", CGN, 20),
        ]
    )
    counts: dict[str, int] = {}
    assert _infer(lb, counts=counts) == []
    assert counts == {"calendar_flights": 1, "no_gap": 1}
    assert flights.MIN_KM == 150.0


def test_infer_a_tracked_flight_arriving_after_midnight_covers_the_same_route_on_the_next_day(lb: Logbook):
    """Flighty tracked XY 123 OSL→IST leaving 10:00 and landing 02:00 the next local day. A stale
    point at Oslo airport after midnight and the points at Istanbul would otherwise infer OSL→IST a
    second time, dated the next day: the tracked flight's window covers that leg, so nothing is
    inferred and it is counted."""
    from persona import flight

    lb.append_many(
        [
            flight("2026-09-27", "123", "OSL", "IST", "2026-09-27T08:00:00Z", "2026-09-27T23:00:00Z"),
            _event("2026-09-26T22:00:00Z", "2026-09-27T22:00:00Z", "Flight XY 123", all_day=True),
            *_track("2026-09-27T06:00:00Z", OSL, 115, every=5),
            _point("2026-09-27T22:30:00Z", OSL),  # 00:30 in Oslo: a stale fix while the phone is in the air
            *_track("2026-09-27T23:05:00Z", IST, 30),
        ]
    )
    counts: dict[str, int] = {}
    assert _infer(lb, counts=counts) == []
    assert counts == {"calendar_flights": 1, "covered": 1}
