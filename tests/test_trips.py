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
    assert boat["asset"] == BOAT
    [anchorage] = boat["route"]
    assert anchorage.startswith("59.85") and "near" not in anchorage, "11 km out: coordinates, no place near"
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
    [hotel] = zurich["route"]
    assert hotel.startswith("47.37"), "9 km from the airport and no named place near: the coordinates"
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
    assert "2 trips" in text and "aboard solvind" in text and "route 47.37" in text
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
    assert len(trip["route"]) == 1 and trip["route"][0].startswith("47.37")


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


# -- the home radius ---------------------------------------------------------------------------------------

NEAR_HOME = (59.9139 + 250 / 111_320, 10.7522)  # 250 m north of Home, outside its 120 m radius


def _home_places(lb: Logbook) -> None:
    from persona import HOME

    (lb.root / "places.json").write_text(
        json.dumps({"Home": {"lat": HOME[0], "lon": HOME[1], "radius_m": 120, "kind": "home"}}),
        encoding="utf-8",
    )


def test_a_night_250_m_from_home_is_home_so_it_makes_no_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from persona import HOME, dwell, travel

    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    d1, d2 = "2026-06-10", "2026-06-11"
    lb.append_many(
        dwell(d1, "00:00", "18:00", HOME)
        + travel(d1, "18:00", "18:10", HOME, NEAR_HOME, steps=3)
        + dwell(d1, "18:10", "24:00", NEAR_HOME, noise_m=10)
        + dwell(d2, "00:00", "08:00", NEAR_HOME, noise_m=10)
        + travel(d2, "08:00", "08:10", NEAR_HOME, HOME, steps=3)
        + dwell(d2, "08:10", "24:00", HOME)
    )
    _home_places(lb)
    data = _json(capsys, "--since", d1, "--until", d2)
    assert data["trips"] == [], "a night within 400 m of a home place is a night at home"
    assert "no trips" in _run(capsys, "--since", d1, "--until", d2)


def test_a_trip_never_starts_or_ends_with_a_night_near_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from persona import HOME, ZURICH, dwell, travel

    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    d1, d2, d3, d4, d5 = "2026-06-10", "2026-06-11", "2026-06-12", "2026-06-13", "2026-06-14"
    lb.append_many(
        dwell(d1, "00:00", "24:00", NEAR_HOME, noise_m=10)  # the night before, 250 m from Home
        + dwell(d2, "00:00", "06:00", NEAR_HOME, noise_m=10)
        + dwell(d2, "10:00", "24:00", ZURICH)
        + dwell(d3, "00:00", "24:00", ZURICH)
        + dwell(d4, "00:00", "14:00", ZURICH)
        + dwell(d4, "18:00", "24:00", NEAR_HOME, noise_m=10)  # the night after, 250 m from Home
        + dwell(d5, "00:00", "08:00", NEAR_HOME, noise_m=10)
        + travel(d5, "08:00", "08:10", NEAR_HOME, HOME, steps=3)
        + dwell(d5, "08:10", "24:00", HOME)
    )
    _home_places(lb)
    [trip] = _json(capsys, "--since", d1, "--until", d5)["trips"]
    assert (trip["start"], trip["end"], trip["nights"]) == (d2, d3, 2)


# -- route labels ------------------------------------------------------------------------------------------


def _stay(where: tuple[float, float], place: str | None = None) -> Any:
    from datetime import UTC, datetime

    from logbook import stays

    return stays.Segment(
        kind=stays.STAY,
        subject=None,
        start=datetime(2026, 6, 10, 18, tzinfo=UTC),
        end=datetime(2026, 6, 11, 8, tzinfo=UTC),
        points=10,
        lat=where[0],
        lon=where[1],
        place=place,
    )


def _places() -> list[Any]:
    from persona import HOME, OFFICE

    from logbook.places import Place

    return [Place("Home", *HOME, 120, "home"), Place("Office", *OFFICE, 120)]


def test_an_unnamed_night_far_from_any_place_names_the_city_of_the_nearest_large_airport() -> None:
    """Hamburg city, 4 km from the airport and with no named place near: the coordinates, then the
    airport's city in parentheses — the city only, never the airport's name."""
    from logbook.flights import Airports
    from logbook.places import Place
    from logbook.trips import route_of

    airports = Airports.load()
    hamburg = _stay((53.5998, 10.0130))
    assert route_of([hamburg], [], airports) == ["53.5998,10.0130 (Hamburg)"]
    at_the_airport = _stay((53.6310, 9.9890))  # within 2 km of HAM: the airport's own name
    assert route_of([at_the_airport], [], airports) == ["Hamburg Helmut Schmidt Airport"]
    cabin = Place("Cabin", 53.5900, 10.0100, 150.0)  # a named place 1.1 km away wins over the city
    assert route_of([hamburg], [cabin], airports) == ["53.5998,10.0130 near Cabin, 1.1 km"]
    oslo_fjord = _stay((59.8500, 10.6000))  # 40 km from OSL: nothing within 30 km, bare coordinates
    assert route_of([oslo_fjord], [], airports) == ["59.8500,10.6000"]
    assert route_of([_stay((53.5998, 10.0130), "Hotel")], [], airports) == ["Hotel"]


def test_a_route_names_an_airport_only_within_2_km_of_it() -> None:
    from persona import ZRH, ZURICH

    from logbook import trips
    from logbook.flights import Airports

    airports = Airports.load()
    [at_airport] = trips.route_of([_stay((47.4700, 8.5481))], _places(), airports)  # 1.3 km from ZRH
    assert at_airport == "Zürich Airport"
    [in_town] = trips.route_of([_stay(ZURICH)], _places(), airports)  # 9 km from ZRH, no place near
    assert in_town == "47.3769,8.5417 (Zurich)", "far from every airport and named place: coordinates, city"
    assert trips.route_of([_stay(ZRH)], _places(), airports) == ["Zürich Airport"]


def test_a_route_point_within_5_km_of_a_named_place_says_near_it_with_the_distance() -> None:
    from persona import CAFE, FJORD

    from logbook import trips
    from logbook.flights import Airports

    airports = Airports.load()
    [label] = trips.route_of([_stay(CAFE)], _places(), airports)  # 1.6 km from Office, 960 m from Home
    assert label == "59.9200,10.7400 near Home, 1.0 km"
    [far] = trips.route_of([_stay(FJORD)], _places(), airports)  # 11 km out on the fjord
    assert far == "59.8500,10.6000"
    named = trips.route_of([_stay(CAFE, place="Cafe")], _places(), airports)
    assert named == ["Cafe"], "a named stay is its name"


def test_consecutive_route_points_within_200_m_collapse_to_one() -> None:
    from persona import ZURICH

    from logbook import trips
    from logbook.flights import Airports

    step = 10 / 111_320  # ten metres of latitude
    three = [_stay((ZURICH[0] + i * step, ZURICH[1])) for i in range(3)]
    assert trips.route_of(three, _places(), Airports.load()) == ["47.3769,8.5417 (Zurich)"]
    apart = [_stay(ZURICH), _stay((ZURICH[0] + 300 / 111_320, ZURICH[1])), _stay(ZURICH)]
    assert len(trips.route_of(apart, _places(), Airports.load())) == 3, "300 m apart stays three points"


# -- with ---------------------------------------------------------------------------------------------------

INES_ID = "019cadd3-6bc0-7dcd-9133-000000000003"


def _zurich_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: list[dict[str, Any]]) -> Logbook:
    """Two nights at the Zürich hotel, home before and after, plus `extra` lines."""
    from persona import HOME, OLA, OLA_ID, ZURICH, dwell, resolution

    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    d1, d2, d3, d4 = "2026-06-10", "2026-06-11", "2026-06-12", "2026-06-13"
    track = (
        dwell(d1, "00:00", "24:00", HOME)
        + dwell(d2, "00:00", "06:00", HOME)
        + dwell(d2, "10:00", "24:00", ZURICH)
        + dwell(d3, "00:00", "24:00", ZURICH)
        + dwell(d4, "00:00", "08:00", ZURICH)
        + dwell(d4, "14:00", "24:00", HOME)
    )
    lb.append_many([resolution(("email", OLA["email"]), OLA_ID, "Ola Nordmann"), *track, *extra])
    _home_places(lb)
    return lb


def test_the_owner_is_never_with_themselves_by_address_or_policy_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from persona import OLA, attendee, event, note, resolution, utc

    d2 = "2026-06-11"
    lb = _zurich_record(
        tmp_path,
        monkeypatch,
        [
            resolution(("email", "ines@example.org"), INES_ID, "Ines Nordmann"),
            event(
                utc(d2, "19:00"),
                utc(d2, "21:30"),
                "Dinner",
                [attendee("ines@example.org"), attendee(OLA["email"])],
            ),
            note(utc(d2, "22:00"), "Walked back with Nordmann"),
        ],
    )
    meta = json.loads((lb.root / "logbook.json").read_text(encoding="utf-8"))
    meta["owner_emails"] = ["ines@example.org"]
    (lb.root / "logbook.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    owner_file = lb.root / "policy" / "owner.json"
    empty = json.loads(owner_file.read_text(encoding="utf-8"))
    assert empty == {"names": [], "emails": [], "phones": []}, "init writes the empty aliases file"
    owner_file.write_text(json.dumps({"names": ["Nordmann"], "emails": [], "phones": []}), encoding="utf-8")
    [trip] = _json(capsys, "--since", "2026-06-10", "--until", "2026-06-13")["trips"]
    assert [p["name"] for p in trip["people"]] == ["Ola Nordmann"]
    assert "with Ola Nordmann" in _run(capsys, "--since", "2026-06-10", "--until", "2026-06-13")


def test_with_lists_at_most_twelve_names_most_evidence_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from persona import attendee, event, resolution, transcript, utc

    d2, d3 = "2026-06-11", "2026-06-12"
    guests = [
        (f"guest{n:02d}@example.org", f"Guest {n:02d}", f"019cadd3-6bc0-7dcd-9133-0000000001{n:02d}")
        for n in range(14)
    ]
    lines = [resolution(("email", email), id_, name) for email, name, id_ in guests]
    lines.append(
        event(utc(d2, "19:00"), utc(d2, "22:00"), "Dinner", [attendee(email) for email, _, _ in guests])
    )
    lines.append(transcript(utc(d3, "10:00"), utc(d3, "11:00"), "Talk", [{"email": guests[13][0]}]))
    _zurich_record(tmp_path, monkeypatch, lines)
    [trip] = _json(capsys, "--since", "2026-06-10", "--until", "2026-06-13")["trips"]
    names = [p["name"] for p in trip["people"]]
    assert len(names) == 12
    assert names[0] == "Guest 13", "two pieces of evidence come first"
    assert names[1:] == [f"Guest {n:02d}" for n in range(11)]
