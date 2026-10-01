"""`logbook rollup countries|flights|nights|places|people`: the record summed up per year, every
number with the ids of the lines it came from under --json. Synthetic Oslo persona; nothing is
appended."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from persona import BOAT, KARI_ID, OLA_ID, PLACES, persona_record

from logbook import cli, countries
from logbook.flights import Airports


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(["rollup", *args])
    return capsys.readouterr().out


def _json(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_run(capsys, *args, "--json"))
    return data


# -- the country of a point ------------------------------------------------------------------------------


def test_country_comes_from_the_place_else_the_nearest_airports_zone() -> None:
    table = countries.Countries.load()
    airports = Airports.load()
    assert table.of_zone("Europe/Oslo") == "NO" and table.of_zone("Europe/Zurich") == "CH"
    assert table.of_zone("Mars/Olympus") is None
    oslo = countries.country_of(59.9139, 10.7522, [], airports, table)
    assert oslo == countries.Country("NO", "airport", "OSL")
    zurich = countries.country_of(47.3769, 8.5417, [], airports, table)
    assert zurich.code == "CH" and zurich.method == "airport"
    from logbook.places import Place

    home = Place("Home", 59.9139, 10.7522, 120, "home", country="SE")  # the captain's word wins
    assert countries.country_of(59.9139, 10.7522, [home], airports, table) == countries.Country(
        "SE", "place", "Home"
    )
    mid_atlantic = countries.country_of(30.0, -40.0, [], airports, table)
    assert mid_atlantic == countries.Country(None, "unknown", None)


# -- countries --------------------------------------------------------------------------------------------


def test_countries_counts_days_by_the_overnight_stay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    head = lb.meta["head"]
    data = _json(capsys, "countries", "--since", "2026-06-08", "--until", "2026-06-21")
    assert data["kind"] == "countries"
    assert "airport" in data["method"] and "300" in data["method"]
    [year] = data["years"]
    assert year["year"] == "2026"
    by_code = {c["country"]: c for c in year["countries"]}
    assert by_code["NO"]["days"] == 11 and by_code["CH"]["days"] == 3
    assert by_code["CH"]["dates"] == ["2026-06-15", "2026-06-16", "2026-06-17"]
    assert "2026-06-13" in by_code["NO"]["dates"], "the night at anchor is still Norway"
    assert year["in_transit"]["days"] == 0 and year["unknown"]["days"] == 0
    assert len(by_code["CH"]["lines"]) == 6, "the first and last point of each of the three nights"
    assert all(len(id_) == 36 for id_ in by_code["CH"]["lines"])
    assert lb.meta["head"] == head
    text = _run(capsys, "countries", "--year", "2026")
    assert "NO" in text and "11 days" in text and "CH" in text and "3 days" in text


def test_a_night_in_transit_is_listed_separately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from persona import HOME, OSL, dwell, travel

    from logbook.store import Logbook

    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    day, next_day = "2026-06-10", "2026-06-11"
    lb.append_many(
        dwell(day, "09:00", "20:00", HOME)
        + travel(day, "20:00", "20:40", HOME, OSL, steps=4)
        + dwell(day, "20:40", "21:50", OSL)  # a red-eye: nothing between 22:00 and 08:00
        + dwell(next_day, "08:30", "23:59", HOME)
    )
    data = _json(capsys, "countries", "--since", day, "--until", next_day)
    [year] = data["years"]
    assert year["in_transit"] == {"days": 1, "dates": [day], "lines": []}
    assert year["countries"] == [
        {
            "country": "NO",
            "days": 1,
            "dates": [next_day],
            "lines": year["countries"][0]["lines"],
            "by": {"airport": 1},
        }
    ]
    text = _run(capsys, "countries", "--since", day, "--until", next_day)
    assert "in transit 1" in text


# -- flights ------------------------------------------------------------------------------------------------


def test_flights_are_counted_measured_and_split_by_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    persona_record(tmp_path, monkeypatch)
    data = _json(capsys, "flights", "--year", "2026")
    [year] = data["years"]
    assert year["count"] == 2
    assert 2700 < year["km"] < 2900, "OSL-ZRH twice, from the airports table"
    assert year["long_haul"] == 0 and year["unmeasured"] == 0
    assert year["by_evidence"] == {"tracked": 2}
    assert [f["number"] for f in year["flights"]] == ["561", "562"]
    first = year["flights"][0]
    assert first["from"] == "OSL" and first["to"] == "ZRH" and 1300 < first["km"] < 1500
    assert len(first["lines"]) == 1 and len(first["lines"][0]) == 36
    assert data["long_haul_km"] == 3500
    text = _run(capsys, "flights")
    assert "2 flights" in text and "km" in text and "tracked 2" in text


def test_a_long_haul_an_unknown_airport_and_a_superseded_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from persona import flight

    from logbook.store import Logbook

    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    declared = flight("2026-03-01", "9", "OSL", "JFK", "2026-03-01T10:00:00Z", "2026-03-01T18:30:00Z")
    declared["source"], declared["payload"]["evidence"] = "manual", "declared"
    declared["payload"]["raw_id"] = "declared-9"
    strip = flight("2026-03-05", "77", "OSL", "ZZZ", "2026-03-05T10:00:00Z", "2026-03-05T11:00:00Z")
    lb.append_many([declared, strip])
    [first, _second] = list(lb.lines())
    tracked = flight("2026-03-01", "9", "OSL", "JFK", "2026-03-01T10:05:00Z", "2026-03-01T18:40:00Z")
    tracked["payload"]["supersedes"] = first["id"]
    lb.append_many([tracked])
    data = _json(capsys, "flights")
    [year] = data["years"]
    assert year["count"] == 2, "the superseded line is not a second flight"
    assert year["long_haul"] == 1 and year["unmeasured"] == 1
    assert year["by_evidence"] == {"tracked": 2}, "the standing line's evidence, not the superseded one's"
    jfk = year["flights"][0]
    assert jfk["km"] > 5000 and jfk["evidence"] == "tracked"
    assert len(jfk["lines"]) == 1, "the line standing; the one it superseded is reachable from it"
    assert year["flights"][1]["km"] is None


# -- nights ------------------------------------------------------------------------------------------------


def test_nights_are_home_or_away_and_the_longest_trip_is_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    persona_record(tmp_path, monkeypatch)
    data = _json(capsys, "nights", "--since", "2026-06-08", "--until", "2026-06-21")
    [year] = data["years"]
    assert (year["home"], year["away"], year["in_transit"]) == (10, 4, 0)
    assert year["longest_trip"]["start"] == "2026-06-15" and year["longest_trip"]["end"] == "2026-06-17"
    assert year["longest_trip"]["nights"] == 3
    assert len(year["longest_trip"]["lines"]) == 6
    assert len(year["lines"]) == 28, "two line ids per night"
    assert year["aboard"] == {BOAT: 1}
    text = _run(capsys, "nights", "--year", "2026")
    assert "10 home" in text and "4 away" in text and "longest trip" in text and "3 nights" in text


def test_without_home_places_every_night_is_away_and_the_command_says_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    persona_record(tmp_path, monkeypatch, places=None)
    data = _json(capsys, "nights", "--since", "2026-06-08", "--until", "2026-06-21")
    [year] = data["years"]
    assert year["home"] == 0 and year["away"] == 14
    assert "home" in data["warning"] and "places" in data["warning"]


# -- the command --------------------------------------------------------------------------------------------


def test_year_and_since_until_are_exclusive_and_an_unknown_kind_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    persona_record(tmp_path, monkeypatch)
    with pytest.raises(SystemExit) as e:
        cli.main(["rollup", "nights", "--year", "2026", "--since", "2026-06-08"])
    assert e.value.code == 2
    with pytest.raises(SystemExit):
        cli.main(["rollup", "meals"])
    with pytest.raises(SystemExit) as e:
        cli.main(["rollup", "nights", "--year", "twenty"])
    assert e.value.code == 2


def test_an_empty_record_rolls_up_to_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from logbook.store import Logbook

    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    for kind in ("countries", "flights", "nights"):
        data = _json(capsys, kind)
        assert data["years"] == []
        assert "nothing" in _run(capsys, kind)


# -- places and people (through the with module) ----------------------------------------------------------


def test_places_rollup_counts_stays_hours_visits_and_company(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    persona_record(tmp_path, monkeypatch)
    data = _json(capsys, "places", "--year", "2026")
    [year] = data["years"]
    by_name = {p["place"]: p for p in year["places"]}
    assert set(by_name) == set(PLACES)
    home = by_name["Home"]
    assert home["kind"] == "home" and home["stays"] >= 10 and home["hours"] > 120
    assert home["first"] == "2026-06-08" and home["last"] == "2026-06-21"
    office = by_name["Office"]
    assert office["stays"] == 8  # seven office days, one of them split by lunch
    assert any(p["id"] == OLA_ID for p in office["people"]), "the transcript at the office"
    assert len(office["lines"]) == 16
    marina = by_name["Marina"]
    assert marina["kind"] == "asset-berth" and marina["stays"] == 2
    [solvind] = year["assets"]
    assert solvind["asset"] == BOAT and solvind["name"] == "Solvind"
    assert solvind["stays"] == 3 and solvind["hours"] > 26 and solvind["nights"] == 1
    assert [p["id"] for p in solvind["people"]] == [OLA_ID]
    text = _run(capsys, "places")
    assert "Home" in text and "Solvind" in text and "Ola Nordmann" in text


def test_people_rollup_counts_days_together_and_the_last_real_contact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    persona_record(tmp_path, monkeypatch)
    data = _json(capsys, "people", "--year", "2026")
    [year] = data["years"]
    by_id = {p["id"]: p for p in year["people"]}
    kari, ola = by_id[KARI_ID], by_id[OLA_ID]
    assert kari["name"] == "Kari Nordmann" and kari["days"] == 1 and kari["last_contact"] == "2026-06-10"
    assert ola["days"] == 3 and ola["last_contact"] == "2026-06-16"
    assert set(ola["places"]) >= {"Office", "aboard solvind"}
    assert all(len(id_) == 36 for id_ in ola["lines"]) and len(ola["lines"]) >= 3
    assert ola["confirmed"] == 3 and kari["confirmed"] == 1 and kari["proposed"] == 1
    text = _run(capsys, "people")
    assert "Ola Nordmann" in text and "3 days" in text and "Kari Nordmann" in text
