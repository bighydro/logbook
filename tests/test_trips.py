"""`logbook trips`: runs of consecutive days whose overnight stay is outside every home region, with
route, nights, places, people and the flights in and out; an asset trip when every night was aboard.
Derived, never a line (ADR 0019). Synthetic Oslo persona."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from persona import BOAT, OLA_ID, persona_record

from logbook import cli
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(["trips", *args])
    return capsys.readouterr().out


def _json(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_run(capsys, *args, "--json"))
    return data


def test_the_fortnight_has_a_weekend_aboard_and_three_nights_in_zurich(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    head = lb.meta["head"]
    data = _json(capsys, "--year", "2026")
    boat, zurich = data["trips"]
    assert boat["id"] == "trip:2026-06-13:2026-06-13"
    assert (boat["start"], boat["end"], boat["nights"], boat["until"]) == (
        "2026-06-13",
        "2026-06-13",
        1,
        "2026-06-14",
    )
    assert boat["asset"] == BOAT and boat["route"] == ["near Marina"]
    assert "Marina" in boat["places"]
    assert [p["id"] for p in boat["people"]] == [OLA_ID]
    assert boat["flights_in"] == [] and boat["flights_out"] == []
    assert (zurich["start"], zurich["end"], zurich["nights"], zurich["until"]) == (
        "2026-06-15",
        "2026-06-17",
        3,
        "2026-06-18",
    )
    assert zurich["asset"] is None and zurich["in_transit"] == 0
    assert zurich["route"] == ["Zürich"], "an unnamed night takes the nearest large airport's name"
    assert zurich["places"] == [], "no named place in Zürich yet"
    assert [p["name"] for p in zurich["people"]] == ["Ola Nordmann"]
    [flight_in], [flight_out] = zurich["flights_in"], zurich["flights_out"]
    assert (flight_in["number"], flight_in["from"], flight_in["to"]) == ("561", "OSL", "ZRH")
    assert (flight_out["number"], flight_out["date"]) == ("562", "2026-06-18")
    assert len(flight_in["lines"]) == 1
    assert set(flight_in["lines"] + flight_out["lines"]) <= set(zurich["lines"])
    assert len(zurich["lines"]) == 5, "one hotel stay (two ids), two flights, the dinner"
    assert all(len(id_) == 36 for id_ in zurich["lines"])
    assert lb.meta["head"] == head, "trips are read, never written"
    text = _run(capsys)
    assert "2 trips" in text and "aboard solvind" in text and "Zürich" in text
    assert "XY 561" in text and "XY 562" in text and "Ola Nordmann" in text and "3 nights" in text


def test_a_night_in_transit_inside_a_trip_joins_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from persona import HOME, OSL, ZURICH, dwell, travel

    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    d1, d2, d3, d4 = "2026-06-10", "2026-06-11", "2026-06-12", "2026-06-13"
    lb.append_many(
        dwell(d1, "00:00", "20:00", HOME)
        + travel(d1, "20:00", "20:40", HOME, OSL, steps=4)
        + dwell(d1, "20:40", "21:50", OSL)  # a red-eye: the night of the 10th is in transit
        + dwell(d2, "09:00", "24:00", ZURICH)
        + dwell(d3, "00:00", "14:00", ZURICH)
        + dwell(d3, "19:00", "24:00", HOME)
        + dwell(d4, "00:00", "12:00", HOME)
    )
    (lb.root / "places.json").write_text(
        json.dumps({"Home": {"lat": HOME[0], "lon": HOME[1], "radius_m": 120, "kind": "home"}}),
        encoding="utf-8",
    )
    data = _json(capsys, "--since", d1, "--until", d4)
    [trip] = data["trips"]
    assert (trip["start"], trip["end"], trip["nights"], trip["in_transit"]) == (d1, d2, 2, 1)
    assert trip["route"] == ["Zürich"]


def test_without_a_home_place_there_are_no_trips_and_the_command_says_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    persona_record(tmp_path, monkeypatch, places=None)
    data = _json(capsys)
    assert data["trips"] == [] and "home" in data["warning"]
    assert "home" in _run(capsys)


def test_an_empty_record_has_no_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    assert _json(capsys)["trips"] == []
    assert "no trips" in _run(capsys)


def test_the_decision_is_written_down() -> None:
    adr = (ROOT / "docs" / "adr" / "0019-trips-are-derived.md").read_text(encoding="utf-8")
    assert "ADR 0019" in adr and "note/v1" in adr
    assert "0019" in (ROOT / "mkdocs.yml").read_text(encoding="utf-8")


def test_a_codeshare_twin_shows_once_in_the_flights_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from persona import flight

    lb = persona_record(tmp_path, monkeypatch)
    lb.append_many(
        [flight("2026-06-15", "9561", "OSL", "ZRH", "2026-06-15T05:10:00Z", "2026-06-15T07:20:00Z")]
    )
    data = _json(capsys, "--year", "2026")
    _boat, zurich = data["trips"]
    assert [f["number"] for f in zurich["flights_in"]] == ["561"]
    text = _run(capsys)
    assert text.count("in XY 561 OSL") == 1 and "9561" not in text


def test_a_night_named_by_its_airport_drops_the_airport_words() -> None:
    from logbook.trips import _city_of_airport

    assert _city_of_airport("Zürich Airport") == "Zürich"
    assert _city_of_airport("Oslo-Gardermoen International Airport") == "Oslo-Gardermoen"
    assert _city_of_airport("Sandefjord Airport, Torp") == "Sandefjord"
